# src/api/routers/coherence.py
"""La cohérence des valeurs d'une colonne : repérer, décider, recoder.

Le mining regroupe par valeurs identiques. `Infirmier`, `INF` et `Infimier`
font trois populations, et sur un effectif minimal à quinze, soixante
infirmiers écrits de cinq façons ne produisent aucun rôle — **sans que rien à
l'écran ne le dise**.

Ces routes ne mettent aucune intelligence artificielle dans le calcul. Le
repérage est local et déterministe ; ce qui est enregistré est une table de
recodage, et c'est elle, seule, que le calcul relit ensuite.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from src.api.dependencies import clear_all_caches, get_data_loader, get_kb
from src.api.journal import Journal, get_journal
from src.api.routers.settings import chemin_de_configuration, lire_la_configuration
from src.core.annotation.annotateur import (
    AnnotateurIndisponible,
    RienANommer,
    depuis_l_environnement,
    envoyer,
)
from src.core.annotation.assistance import USAGE_COHERENCE_DES_VALEURS
from src.core.annotation.regroupeur import proposer_les_regroupements
from src.core.audit import Action
from src.core.data import coherence
from src.core.data.loader import DataLoader
from src.core.data.transformations import Operation, Regle
from src.core.knowledge.knowledge_base import KnowledgeBase
from src.core.security.auth import User, require_permission_or_dev

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/coherence")

#: Référentiels analysables, et la colonne d'identifiant de chacun.
#:
#: Les trois sont couverts, pas seulement les identités : les libellés
#: d'applications et de droits souffrent des mêmes dispersions, et un libellé
#: propre améliore aussi bien le nommage que la lecture des rôles applicatifs.
REFERENTIELS: Dict[str, str] = {
    "identities": DataLoader.COL_USER_ID,
    "rights": DataLoader.COL_RIGHT_ID,
    "applications": DataLoader.COL_APP_ID,
}


def _referentiel_connu(referentiel: str) -> str:
    if referentiel not in REFERENTIELS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "referential.unknown",
                    "params": {"referentiel": referentiel}})
    return referentiel


def _colonnes_du_referentiel(loader: DataLoader, referentiel: str):
    """Le cadre de données d'un référentiel, ou rien."""
    return {"identities": loader.identities, "rights": loader.rights,
            "applications": loader.applications}[referentiel]


def _eligible(serie, total: int, identifiant: str, colonne: str) -> bool:
    """La règle déjà en service pour les attributs de mining, moins le seuil.

    Une colonne constante ne regroupe rien ; une colonne dont chaque ligne a
    une valeur distincte est un identifiant, pas un attribut.

    Le seuil de cardinalité, lui, n'écarte rien ici : une colonne à forte
    cardinalité est déconseillée *comme critère de mining*, elle reste
    parfaitement analysable pour sa cohérence — c'est même là que les
    dispersions abondent.
    """
    if colonne == identifiant:
        return False
    distinctes = int(serie.nunique(dropna=True))
    return 2 <= distinctes < total or (distinctes >= 2 and total == 0)


@router.get("/colonnes")
async def colonnes_analysables(
    loader: DataLoader = Depends(get_data_loader),
    user: User = Depends(require_permission_or_dev("read")),
) -> Dict[str, Any]:
    """Les colonnes qu'on peut analyser, par référentiel.

    Aucun nom n'est présumé : la liste vient des fichiers du client. Le type
    détecté est calculé sur les valeurs — une colonne de dates n'est pas
    analysée parce que la proximité textuelle y produit du bruit, et non parce
    qu'elle s'appellerait `date`.
    """
    autorisation = loader.config.assistance.pour(USAGE_COHERENCE_DES_VALEURS.code)
    rendu = []
    for referentiel, identifiant in REFERENTIELS.items():
        cadre = _colonnes_du_referentiel(loader, referentiel)
        if cadre is None or cadre.empty:
            continue
        total = len(cadre)
        for colonne in cadre.columns:
            if not _eligible(cadre[colonne], total, identifiant, colonne):
                continue
            distinctes = cadre[colonne].dropna().astype(str)
            part = coherence.est_typee(distinctes.unique())
            typee = part > loader.config.coherence.part_typee_max
            rendu.append({
                "referentiel": referentiel,
                "colonne": colonne,
                "valeurs_distinctes": int(distinctes.nunique()),
                "lignes": total,
                "part_typee": round(part, 4),
                "typee": typee,
                # Dit ici, et non découvert au clic : un bouton qu'on presse
                # pour apprendre qu'il était fermé envoie chercher au mauvais
                # endroit. Une colonne typée n'est jamais soumise — rien de ce
                # qu'un modèle dirait de `2024-01-01` ne vaut de l'avoir
                # envoyé.
                "enrichissable": (not typee) and autorisation.autorise_la_colonne(
                    referentiel, colonne),
            })
    return {"colonnes": rendu,
            # L'état de l'assistance pour cet usage, sans détail de matière :
            # l'écran doit pouvoir distinguer « l'assistance est fermée » de
            # « cette colonne-là n'est pas ouverte », qui ne se règlent pas au
            # même endroit.
            "assistance": {
                "actif": autorisation.actif,
                "posable": autorisation.posable,
                "portee_ouverte": autorisation.portee_ouverte,
            },
            "reglages": {
                "distance_edition_max": loader.config.coherence.distance_edition_max,
                "longueur_racine_min": loader.config.coherence.longueur_racine_min,
                "ecart_effectif_significatif":
                    loader.config.coherence.ecart_effectif_significatif,
                "valeurs_analysees_max":
                    loader.config.coherence.valeurs_analysees_max,
                "part_typee_max": loader.config.coherence.part_typee_max,
            }}


class ColonneDemandee(BaseModel):
    """Une colonne d'un référentiel. Rien d'autre ne sort de l'appelant."""

    model_config = ConfigDict(extra="forbid")

    referentiel: str = Field(..., min_length=1, max_length=40)
    colonne: str = Field(..., min_length=1, max_length=200)


def _serie(loader: DataLoader, referentiel: str, colonne: str):
    cadre = _colonnes_du_referentiel(loader, _referentiel_connu(referentiel))
    if cadre is None or cadre.empty or colonne not in cadre.columns:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "coherence.column_unknown",
                    "params": {"colonne": colonne}})
    return cadre[colonne]


@router.post("/analyser")
async def analyser_une_colonne(
    demande: ColonneDemandee,
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
    user: User = Depends(require_permission_or_dev("read")),
) -> Dict[str, Any]:
    """Repère les valeurs qui semblent désigner la même chose.

    **Aucune sortie réseau.** Cette étape est complète et utile à elle seule :
    sur un serveur isolé sans modèle installé, elle apporte l'essentiel du
    gain. Un modèle, s'il est disponible, ne fera qu'amplifier.

    La conséquence du regroupement est calculée avec l'effectif minimal du
    workspace : « ces cinq valeurs font une population de 63, au-dessus de
    votre seuil de 15 — elle était invisible au mining ». C'est la seule mesure
    qui justifie l'opération, et elle est rendue avant toute acceptation.
    """
    serie = _serie(loader, demande.referentiel, demande.colonne)
    refus = kb.rapprochements_refuses(demande.referentiel, demande.colonne)
    analyse = await run_in_threadpool(
        coherence.analyser, serie.tolist(), demande.referentiel,
        demande.colonne, loader.config.coherence, refus)

    journal.consigner(Action.VALEURS_ANALYSEES, "colonne",
                      f"{demande.referentiel}.{demande.colonne}",
                      {"grappes": len(analyse.grappes),
                       "valeurs": analyse.valeurs_distinctes})
    return analyse.en_document(loader.config.mining_min_users)


class Enrichissement(ColonneDemandee):
    """Une colonne, et la langue de la réponse.

    Rien d'autre ne vient de l'appelant : les valeurs soumises sont lues dans
    le référentiel du serveur. Un client ne peut donc pas faire sortir des
    données en les glissant dans la demande.
    """

    locale: str = Field(..., min_length=2, max_length=8)


#: Poser la question est un geste d'analyste ; décider que les valeurs d'une
#: colonne peuvent sortir est un acte d'administration, et il a été posé
#: ailleurs — dans la matrice, colonne par colonne, avant que ce bouton
#: n'existe.
ENRICHISSEMENT_PERMISSION = "mining"


@router.post("/enrichir")
async def enrichir_par_un_modele(
    demande: Enrichissement,
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
    user: User = Depends(require_permission_or_dev(ENRICHISSEMENT_PERMISSION)),
) -> Dict[str, Any]:
    """Demande à un modèle les rapprochements que le repérage local ne voit pas.

    `AS` pour `Aide-soignant`, `RRH` pour `Responsable ressources humaines`,
    deux nomenclatures d'un groupe né d'une fusion : aucune comparaison de
    chaînes ne les trouve, et c'est la seule chose qu'un modèle apporte ici.

    **Les mots viennent du modèle, les chiffres du calcul.** Les effectifs, la
    conséquence du regroupement et le seuil affichés sont ceux du serveur ; la
    réponse n'apporte que des ensembles de valeurs, et chacune doit exister
    telle quelle dans la colonne. Ce qui n'y résiste pas est compté et rendu,
    parce qu'un compte d'écarts qui grossit dit que ce modèle-là ne convient
    pas.

    Rien n'est enregistré : les grappes s'affichent à côté de celles du
    repérage local, et c'est `/coherence/appliquer` — donc un geste humain —
    qui écrit la table.
    """
    referentiel = _referentiel_connu(demande.referentiel)
    serie = _serie(loader, referentiel, demande.colonne)
    autorisation = loader.config.assistance.pour(USAGE_COHERENCE_DES_VALEURS.code)
    if not autorisation.autorise_la_colonne(referentiel, demande.colonne):
        # Distinct d'un usage fermé : ici l'usage peut être ouvert et la
        # matière autorisée, et c'est **cette colonne-là** qui ne l'est pas.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "coherence.column_not_authorised",
                    "params": {"colonne": demande.colonne}})

    from src.api.reglages_du_modele import reglages_pour

    reglages = reglages_pour(USAGE_COHERENCE_DES_VALEURS.code)
    refus = kb.rapprochements_refuses(referentiel, demande.colonne)
    try:
        proposition = await run_in_threadpool(
            proposer_les_regroupements, reglages, autorisation, serie.tolist(),
            referentiel, demande.colonne, loader.config.coherence,
            demande.locale, lambda charge: envoyer(charge, reglages), refus)
    except RienANommer as erreur:
        logger.info("Aucun enrichissement (%s.%s) : %s", referentiel,
                    demande.colonne, erreur)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "assistance.usage_closed",
                    "params": {"usage": USAGE_COHERENCE_DES_VALEURS.code}})
    except AnnotateurIndisponible as erreur:
        logger.info("Modèle indisponible (%s.%s) : %s", referentiel,
                    demande.colonne, erreur)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "annotator.unavailable"})

    journal.consigner(
        Action.VALEURS_SOUMISES, "colonne", f"{referentiel}.{demande.colonne}",
        {"valeurs": proposition["valeurs_soumises"],
         "grappes": len(proposition["grappes"]),
         "modele": proposition["modele"],
         "categories": ", ".join(proposition["categories_transmises"]),
         "hors_du_poste": not reglages.locale})

    effectif_minimal = loader.config.mining_min_users
    return {
        "referentiel": referentiel,
        "colonne": demande.colonne,
        "grappes": [grappe.en_document(effectif_minimal)
                    for grappe in proposition["grappes"]],
        "ecartees": proposition["ecartees"],
        "valeurs_soumises": proposition["valeurs_soumises"],
        "valeurs_distinctes": proposition["valeurs_distinctes"],
        "modele": proposition["modele"],
        "categories_transmises": proposition["categories_transmises"],
        "effectif_minimal": effectif_minimal,
    }


class Recodage(BaseModel):
    """Ce qui devient une entrée de table : des valeurs et leur forme retenue.

    La forme retenue n'est pas contrainte d'appartenir aux valeurs : une
    organisation peut profiter du recodage pour adopter sa nomenclature cible.
    """

    model_config = ConfigDict(extra="forbid")

    valeurs: List[str] = Field(..., min_length=1, max_length=1000)
    forme_retenue: str = Field(..., min_length=1, max_length=500)
    origine: str = Field("locale", max_length=40)


class Application(BaseModel):
    model_config = ConfigDict(extra="forbid")

    referentiel: str = Field(..., min_length=1, max_length=40)
    colonne: str = Field(..., min_length=1, max_length=200)
    grappes: List[Recodage] = Field(..., min_length=1, max_length=1000)


def _pipeline_du_document(configuration: Dict[str, Any]) -> Dict[str, Any]:
    transformations = configuration.get("transformations")
    return transformations if isinstance(transformations, dict) else {}


@router.post("/appliquer")
async def appliquer_le_recodage(
    demande: Application,
    journal: Journal = Depends(get_journal),
    user: User = Depends(require_permission_or_dev("write")),
) -> Dict[str, Any]:
    """Transforme des grappes acceptées en entrées de table de recodage.

    La table rejoint le pipeline de transformations du workspace : elle
    s'exporte avec lui, s'édite à la main, et **le calcul ne relit qu'elle**.
    Deux exécutions sur les mêmes fichiers et la même table donnent le même
    résultat, modèle éteint ou absent.

    Une règle de recodage existe au plus une fois par colonne : les entrées
    nouvelles complètent la table en place plutôt que d'empiler des règles que
    personne ne saurait plus ordonner.
    """
    referentiel = _referentiel_connu(demande.referentiel)
    chemin = chemin_de_configuration()
    configuration = lire_la_configuration(chemin)
    transformations = _pipeline_du_document(configuration)
    regles = list(transformations.get(referentiel) or [])

    ajouts: Dict[str, str] = {}
    for grappe in demande.grappes:
        for valeur in grappe.valeurs:
            if valeur == grappe.forme_retenue:
                # Recoder une valeur vers elle-même n'est pas une entrée : ce
                # serait faire croire à une modification qui n'existe pas.
                continue
            ajouts[valeur] = grappe.forme_retenue

    existante = next((regle for regle in regles
                      if regle.get("operation") == Operation.RECODER.value
                      and regle.get("column") == demande.colonne), None)
    if existante is None:
        existante = {"column": demande.colonne,
                     "operation": Operation.RECODER.value, "table": {}}
        regles.append(existante)
    table = dict(existante.get("table") or {})
    table.update(ajouts)
    existante["table"] = dict(sorted(table.items()))

    try:
        # Relue par le modèle du domaine avant d'être écrite : une table que le
        # chargeur refuserait ne doit pas atteindre le disque, sans quoi le
        # workspace ne se rechargerait plus.
        Regle.depuis_document(existante)
    except Exception as erreur:  # pragma: no cover - garde de forme
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "coherence.table_invalid",
                    "params": {"motif": str(erreur)}})

    transformations[referentiel] = regles
    configuration["transformations"] = transformations
    _ecrire(chemin, configuration)

    origines = sorted({grappe.origine for grappe in demande.grappes})
    journal.consigner(Action.VALEURS_RECODEES, "colonne",
                      f"{referentiel}.{demande.colonne}",
                      {"entrees": len(ajouts), "total": len(table),
                       "origines": ", ".join(origines)})
    return {"status": "recoded", "entrees_ajoutees": len(ajouts),
            "table": existante["table"]}


class Refus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    referentiel: str = Field(..., min_length=1, max_length=40)
    colonne: str = Field(..., min_length=1, max_length=200)
    valeurs: List[str] = Field(..., min_length=2, max_length=1000)


@router.post("/refuser")
async def refuser_un_rapprochement(
    demande: Refus,
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
    user: User = Depends(require_permission_or_dev("write")),
) -> Dict[str, Any]:
    """Mémorise que ces valeurs ne désignent pas la même chose.

    `Cadre` et `Cadre de santé` sont proches et ne doivent pas fusionner.
    L'utilisateur ne doit avoir à le dire qu'une fois : sans mémoire, le
    repérage lui reproposerait la même grappe à chaque analyse, et il finirait
    par accepter par lassitude.
    """
    referentiel = _referentiel_connu(demande.referentiel)
    ajoutees = await run_in_threadpool(
        kb.refuser_le_rapprochement, referentiel, demande.colonne,
        demande.valeurs, journal.acteur)
    journal.consigner(Action.VALEURS_REFUSEES, "colonne",
                      f"{referentiel}.{demande.colonne}",
                      {"paires": ajoutees, "valeurs": len(demande.valeurs)})
    return {"status": "refused", "paires_ajoutees": ajoutees}


class Table(BaseModel):
    """Une table écrite à la main.

    C'est le mode dégradé — aucun modèle, aucune analyse — et c'est aussi le
    mode expert : un client qui possède déjà sa table de correspondance la
    saisit, et n'a besoin de rien d'autre.
    """

    model_config = ConfigDict(extra="forbid")

    table: Dict[str, str] = Field(default_factory=dict, max_length=20000)


@router.get("/table/{referentiel}/{colonne}")
async def lire_la_table(
    referentiel: str, colonne: str,
    user: User = Depends(require_permission_or_dev("read")),
) -> Dict[str, Any]:
    """La table de recodage d'une colonne, ou une table vide."""
    _referentiel_connu(referentiel)
    configuration = lire_la_configuration(chemin_de_configuration())
    regles = _pipeline_du_document(configuration).get(referentiel) or []
    regle = next((r for r in regles
                  if r.get("operation") == Operation.RECODER.value
                  and r.get("column") == colonne), None)
    return {"referentiel": referentiel, "colonne": colonne,
            "table": dict(regle.get("table") or {}) if regle else {}}


@router.put("/table/{referentiel}/{colonne}")
async def ecrire_la_table(
    referentiel: str, colonne: str, demande: Table,
    journal: Journal = Depends(get_journal),
    user: User = Depends(require_permission_or_dev("write")),
) -> Dict[str, Any]:
    """Remplace la table d'une colonne. Une table vide retire la règle.

    Le document reçu fait foi dans son entier : une table partielle laisserait
    en place des correspondances que l'écran croyait avoir retirées.
    """
    _referentiel_connu(referentiel)
    chemin = chemin_de_configuration()
    configuration = lire_la_configuration(chemin)
    transformations = _pipeline_du_document(configuration)
    regles = [r for r in (transformations.get(referentiel) or [])
              if not (r.get("operation") == Operation.RECODER.value
                      and r.get("column") == colonne)]

    table = {source: cible for source, cible in demande.table.items()
             if str(source).strip() and source != cible}
    if table:
        regles.append({"column": colonne,
                       "operation": Operation.RECODER.value,
                       "table": dict(sorted(table.items()))})
    if regles:
        transformations[referentiel] = regles
    else:
        transformations.pop(referentiel, None)
    configuration["transformations"] = transformations
    _ecrire(chemin, configuration)

    journal.consigner(Action.VALEURS_RECODEES, "colonne",
                      f"{referentiel}.{colonne}",
                      {"entrees": len(table), "total": len(table),
                       "origines": "manuelle"})
    return {"status": "saved", "table": dict(sorted(table.items()))}


def _ecrire(chemin, configuration: Dict[str, Any]) -> None:
    """Écrit la configuration et purge le cache du chargeur.

    Sans purge, la table écrite ne s'appliquerait qu'au prochain démarrage — et
    l'utilisateur relancerait un mining sur les données d'avant en croyant
    mesurer son recodage.
    """
    import json

    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps(configuration, indent=4,
                                     ensure_ascii=False), encoding="utf-8")
    except OSError as erreur:
        logger.error("Table non enregistrée (%s) : %s", chemin, erreur)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "settings.not_saved"})
    clear_all_caches()
