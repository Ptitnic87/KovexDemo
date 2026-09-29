# Fichier : src/api/routers/separation.py
"""La séparation des tâches, vue de l'API.

Cinq routes, et leur découpage dit la conception :

- les **règles** se lisent et s'écrivent comme les règles de périmètre : une
  décision de gouvernance, dans la base de connaissance, jamais dans la
  configuration ;
- les **conflits** se recalculent à chaque appel, sur les données du jour. Une
  liste de conflits conservée serait fausse dès le prochain chargement, et
  personne ne saurait de quand elle date ;
- le **détail** d'une règle rend les identités et l'origine de leur conflit,
  parce que « quarante conflits » ne se traite pas, alors que « trente-huit
  d'entre eux viennent d'un rôle » se traite en une décision ;
- les **couples candidats** se calculent sur la matrice, et ne s'enregistrent
  pas : ils proposent une règle à écrire, ils n'en écrivent aucune ;
- la **marque du catalogue** dit quels rôles validés enfreignent une règle, sans
  lire une seule habilitation : un rôle est en conflit par ce qu'il accorde, et
  le savoir ne demande pas de relever qui le porte.

Aucune de ces routes ne retire un droit ni ne rejette un rôle. Le produit rend
ce qui est ; la remédiation appartient à celui qui répond du contrôle interne.
"""

from __future__ import annotations

import logging
from typing import (Any, Dict, FrozenSet, List, Mapping, Optional,
                    Sequence)

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.concurrency import run_in_threadpool

from src.api.dependencies import get_data_loader, get_kb
from src.api.journal import Journal, get_journal
from src.core.audit.piste_audit import Action
from src.core.data.loader import DataLoader
from src.core.knowledge.knowledge_base import KnowledgeBase
from src.core.knowledge.derogations import (FAMILLE_SEPARATION,
                                            Reglages as ReglagesDeDerogation,
                                            cible_de_separation)
from src.core.knowledge.population import (detenteurs_par_droit,
                                            droits_par_identite)
from src.core.knowledge.privileges import marques_parmi_les_comptes
from src.core.knowledge.separation import (IDENTITES_DETAILLEES_MAX, TYPES,
                                           Regle, RegleInvalide,
                                           SeveriteInconnue, conflits,
                                           rang_de_severite, resoudre,
                                           roles_en_conflit, synthese,
                                           verifier_les_severites)
from src.core.mining.antagonisme import (Reglages, couples_antagonistes,
                                         couples_declares)
from src.core.role.modele_acquis import construire
from src.core.security.auth import User, require_permission_or_dev

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/separation", tags=["Séparation des tâches"])

#: Lire les conflits est un geste d'analyste ; écrire une règle est une
#: décision de gouvernance, au même titre qu'écarter une identité de l'analyse.
LECTURE = "mining"
ECRITURE = "mining"


class ReferenceEnvoyee(BaseModel):
    """Ce qu'un côté nomme : un droit, une application, ou un rôle du catalogue.

    Le type est validé ici plutôt que plus bas parce qu'un type inconnu est une
    faute de l'appelant, et qu'un refus rendu à la saisie se corrige — là où une
    règle rangée puis ignorée ne se corrige jamais.
    """

    model_config = ConfigDict(extra="forbid")

    type: str = Field(..., min_length=1, max_length=32)
    id: str = Field(..., min_length=1, max_length=200)

    @field_validator("type")
    @classmethod
    def _type_connu(cls, valeur):
        if valeur not in TYPES:
            raise ValueError(
                f"type inconnu : {valeur!r} (attendu : {', '.join(TYPES)})")
        return valeur


class RegleEnvoyee(BaseModel):
    """Une règle telle que l'écran la rend.

    `extra="forbid"` : un champ inconnu est une faute de frappe dans un nom de
    clé, et l'accepter en silence enregistrerait une règle amputée.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=64)
    libelle: str = Field(..., min_length=1, max_length=200)
    gauche: List[ReferenceEnvoyee] = Field(default_factory=list)
    droite: List[ReferenceEnvoyee] = Field(default_factory=list)
    active: bool = True
    # Sévérité, processus, propriétaire : facultatifs, pour qu'une règle
    # déclarée avant ce lot se réenregistre telle quelle. La sévérité est
    # vérifiée contre la liste du workspace.
    severite: str = Field(default="", max_length=200)
    processus: str = Field(default="", max_length=200)
    proprietaire: str = Field(default="", max_length=200)


class ReglesEnvoyees(BaseModel):
    model_config = ConfigDict(extra="forbid")

    regles: List[RegleEnvoyee] = Field(default_factory=list)


def _droits_par_application(loader: DataLoader) -> Dict[str, set]:
    """Les droits de chaque application, d'après le référentiel des droits.

    Le rattachement vient de la colonne déclarée dans la configuration : le
    produit ne présume aucun nom de colonne, ici pas plus qu'ailleurs. Sans ce
    rattachement, une règle qui nomme une application ne désigne rien — et elle
    le dit plutôt que de se taire.
    """
    droits = loader.rights
    if droits is None or droits.empty:
        return {}
    if DataLoader.COL_APP_ID not in droits.columns:
        return {}
    return {str(application): {str(droit) for droit in groupe.unique()}
            for application, groupe in droits.groupby(
                DataLoader.COL_APP_ID, observed=True)[DataLoader.COL_RIGHT_ID]}


def _droits_par_role(roles: Sequence[Mapping[str, Any]]) -> Dict[str, set]:
    """Ce que chaque rôle du catalogue accorde.

    Indexé par identifiant **et** par nom : une règle écrite par un humain
    nomme souvent le rôle tel qu'il le lit à l'écran, et refuser cette forme
    ferait buter la saisie sur un détail d'implémentation.
    """
    par_role: Dict[str, set] = {}
    for role in roles:
        droits = {str(droit) for droit in (role.get("rights") or ())}
        if not droits:
            continue
        for cle in (role.get("id"), role.get("name")):
            if cle:
                par_role.setdefault(str(cle), set()).update(droits)
    return par_role


def _resolues(loader: DataLoader, kb: KnowledgeBase,
              roles: Optional[Sequence[Mapping[str, Any]]] = None) -> List[Any]:
    """Les règles du workspace, ramenées aux droits qu'elles visent aujourd'hui.

    C'est ici que la durée de vie d'une règle se paie : la résolution se refait
    à chaque appel, sur les données du jour. Une application qui gagne un droit
    élargit d'elle-même la règle qui la nomme.
    """
    if roles is None:
        roles = kb.get_validated_roles()
    par_application = _droits_par_application(loader)
    par_role = _droits_par_role(roles)
    return [resoudre(regle, par_application, par_role)
            for regle in kb.regles_separation()]


def _modele(loader: DataLoader, kb: KnowledgeBase):
    """Le modèle acquis du jour : quels rôles, pour quelles identités.

    Le même calcul que la revue, le complément et le graphe. Un conflit dont
    l'origine serait établie par un autre chemin que celui qui décide de la
    population d'un rôle finirait par désigner un rôle que l'écran des porteurs
    ne montre pas.
    """
    from src.core.knowledge.population import detenteurs_par_droit

    roles = kb.get_validated_roles()
    droits = {str(droit) for role in roles for droit in (role.get("rights") or ())}
    detenteurs = detenteurs_par_droit(loader.habilitations,
                                      DataLoader.COL_USER_ID,
                                      DataLoader.COL_RIGHT_ID, droits)
    return roles, construire(roles, loader.identities, DataLoader.COL_USER_ID,
                             detenteurs_par_droit=detenteurs)


def _roles_par_identite(acquis) -> Dict[str, Dict[str, frozenset]]:
    """Ce que chaque identité reçoit, rôle par rôle.

    Construit une fois pour toutes les règles : le faire par règle referait le
    même parcours autant de fois qu'il y a de règles, pour un résultat
    identique.
    """
    par_identite: Dict[str, Dict[str, frozenset]] = {}
    for role in acquis.roles:
        for membre in role.membres:
            par_identite.setdefault(str(membre), {})[role.identifiant] = role.droits
    return par_identite


@router.get("/regles")
async def lire_les_regles(
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    user: User = Depends(require_permission_or_dev(LECTURE)),
) -> Dict[str, Any]:
    """Les règles déclarées, telles qu'elles sont stockées.

    Rendues brutes et non validées : l'écran doit pouvoir montrer une règle
    devenue illisible pour qu'on la corrige, là où les calculs, eux, l'ignorent.
    Avec elles, les niveaux de sévérité du workspace : ce sont les seuls que
    la saisie accepte.
    """
    return {"regles": kb.get_sod_rules(),
            "severites": list(loader.config.sod_severites)}


@router.put("/regles")
async def ecrire_les_regles(
    envoi: ReglesEnvoyees,
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
    user: User = Depends(require_permission_or_dev(ECRITURE)),
) -> Dict[str, Any]:
    """Remplace les règles par celles de l'écran.

    Le refus est **structuré**, jamais une phrase : le serveur ne connaît pas
    la langue de l'utilisateur, et c'est le client qui compose le message.
    """
    regles = [regle.model_dump() if hasattr(regle, "model_dump") else regle.dict()
              for regle in envoi.regles]
    try:
        verifier_les_severites(regles, loader.config.sod_severites)
    except SeveriteInconnue as erreur:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "separation.severite_inconnue",
                    "params": {"regle": erreur.regle, "severite": erreur.severite}})
    try:
        kb.set_sod_rules(regles)
    except RegleInvalide as erreur:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "separation.regle_invalide",
                    "params": {"motif": str(erreur)}})
    journal.consigner(Action.SOD_REGLES_MODIFIEES, "separation", "regles",
                      {"regles": len(regles)})
    return {"regles": kb.get_sod_rules(),
            "severites": list(loader.config.sod_severites)}


@router.get("/conflits")
async def lire_les_conflits(
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    user: User = Depends(require_permission_or_dev(LECTURE)),
) -> Dict[str, Any]:
    """Le compte des conflits, règle par règle, sur les données du jour.

    `par_les_roles` est la part du conflit que corriger le modèle ferait
    disparaître. La distinguer change la décision : quarante conflits dont
    trente-huit viennent d'un rôle ne se traitent pas comme quarante
    exceptions.
    """
    return await run_in_threadpool(_synthese, loader, kb)


def _couvertures(loader: DataLoader, kb: KnowledgeBase):
    """Les dérogations qui couvrent un conflit de séparation, aujourd'hui."""
    from src.api.routers.derogations import etat_des_derogations

    return etat_des_derogations(loader, kb, FAMILLE_SEPARATION)[0]


def _inoperantes(loader: DataLoader, kb: KnowledgeBase):
    """Les dérogations en cours qui ne couvrent plus, avec leurs raisons.

    Un conflit qui revient alors qu'on l'avait accepté doit dire pourquoi : le
    contrôle n'a pas tourné, il a échoué, il a été relu par son exécutant. Sans
    cela, l'auditeur voit un conflit « non traité » là où une décision existe
    et a cessé de valoir.
    """
    from src.api.routers.derogations import etat_des_derogations

    return etat_des_derogations(loader, kb, FAMILLE_SEPARATION)[1]


def _derogation_du_conflit(conflit, couvertes) -> Optional[Dict[str, Any]]:
    derogation = couvertes.get(
        cible_de_separation(conflit.regle, conflit.identite))
    return derogation.en_dict() if derogation is not None else None


def _posture(loader: DataLoader, kb: KnowledgeBase, regles) -> Dict[str, int]:
    """Ce que le programme de séparation dit de lui-même.

    Ce ne sont pas des conflits d'habilitation, ce sont des défauts du
    contrôle : une règle active dont personne ne répond, une règle suspendue
    qu'on a peut-être oublié de rallumer, une exception qui attend une décision.
    Trois comptes, sans score : chacun dit ce qu'il faut aller faire.
    """
    from src.api.routers.derogations import _aujourdhui
    from src.core.knowledge.derogations import DEMANDEE

    reglages = ReglagesDeDerogation.depuis_la_configuration(loader.config)
    aujourdhui = _aujourdhui()
    return {
        "regles_sans_proprietaire": sum(
            1 for regle in regles if regle.active and not regle.proprietaire),
        "regles_suspendues": sum(1 for regle in regles if not regle.active),
        "derogations_en_attente": sum(
            1 for derogation in kb.derogations(reglages)
            if derogation.famille == FAMILLE_SEPARATION
            and derogation.statut == DEMANDEE
            and not derogation.expiree(aujourdhui)),
    }


def _synthese(loader: DataLoader, kb: KnowledgeBase) -> Dict[str, Any]:
    catalogue, acquis = _modele(loader, kb)
    regles = _resolues(loader, kb, catalogue)
    severites = loader.config.sod_severites
    posture = _posture(loader, kb, regles)
    if not regles:
        return {"regles": [], "identites_en_conflit": 0,
                "identites_derogees": 0, "population": 0,
                "severites": list(severites), **posture}
    detenus = droits_par_identite(loader.habilitations, DataLoader.COL_USER_ID,
                                  DataLoader.COL_RIGHT_ID)
    par_identite = _roles_par_identite(acquis)
    couvertes = _couvertures(loader, kb)

    lignes = []
    concernees = set()
    derogees = set()
    for regle in regles:
        trouves = conflits(regle, detenus, par_identite)
        couverts = [conflit for conflit in trouves
                    if _derogation_du_conflit(conflit, couvertes) is not None]
        concernees.update(conflit.identite for conflit in trouves)
        derogees.update(conflit.identite for conflit in couverts)
        # Deux nombres et non un : un conflit couvert reste compté et reste
        # affiché, il est seulement rangé à part. Le fondre dans le total
        # ferait croire qu'il reste à traiter ; le retirer du total cacherait
        # à un auditeur ce qui a été accepté.
        lignes.append({**synthese(regle, trouves,
                                  roles_en_conflit(regle, catalogue)),
                       "derogees": len(couverts)})
    # La plus grave d'abord ; à sévérité égale, l'ordre de déclaration. Une
    # règle non qualifiée vient après : elle n'est pas moins grave, elle n'est
    # pas qualifiée.
    lignes.sort(key=lambda ligne: rang_de_severite(ligne["severite"], severites))
    return {"regles": lignes,
            "severites": list(severites),
            # Une règle active sans propriétaire est un constat sur le
            # programme lui-même : personne n'est là pour répondre du risque.
            **posture,
            # Les identités distinctes, et non la somme des conflits : une
            # personne qui viole trois règles est une personne, et c'est elle
            # qu'on va voir.
            "identites_en_conflit": len(concernees),
            "identites_derogees": len(derogees),
            "population": len(detenus)}


@router.get("/conflits/{regle_id}")
async def detailler_un_conflit(
    regle_id: str,
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    user: User = Depends(require_permission_or_dev(LECTURE)),
) -> Dict[str, Any]:
    """Qui est en conflit sur cette règle, et par quoi.

    Les rôles qui portent les deux côtés sont rendus **à part** : ils ne se
    corrigent pas identité par identité, et les noyer dans la liste des
    porteurs ferait traiter cent fois un défaut unique.
    """
    return await run_in_threadpool(_detail, loader, kb, regle_id)


def _detail(loader: DataLoader, kb: KnowledgeBase,
            regle_id: str) -> Dict[str, Any]:
    catalogue, acquis = _modele(loader, kb)
    regles = {regle.identifiant: regle
              for regle in _resolues(loader, kb, catalogue)}
    regle = regles.get(regle_id)
    if regle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "separation.regle_inconnue",
                    "params": {"regle": regle_id}})
    detenus = droits_par_identite(loader.habilitations, DataLoader.COL_USER_ID,
                                  DataLoader.COL_RIGHT_ID)
    trouves = conflits(regle, detenus, _roles_par_identite(acquis))
    toxiques = roles_en_conflit(regle, catalogue)
    couvertes = _couvertures(loader, kb)
    inoperantes = _inoperantes(loader, kb)
    lignes = []
    for conflit in trouves:
        document = conflit.en_dict()
        document["derogation"] = _derogation_du_conflit(conflit, couvertes)
        document["derogation_inoperante"] = (
            None if document["derogation"] is not None
            else inoperantes.get(cible_de_separation(conflit.regle,
                                                      conflit.identite)))
        lignes.append(document)
    # Ce qui reste à traiter d'abord : une liste qui commence par ce qu'on a
    # déjà tranché est une liste qu'on cesse de dérouler.
    lignes.sort(key=lambda ligne: (ligne["derogation"] is not None,
                                   ligne["identite"]))
    montrees = lignes[:IDENTITES_DETAILLEES_MAX]
    # Un cumul porté par un compte d'administration ne se lit pas comme un
    # cumul porté par un compte nominatif : c'est le même constat sur une
    # personne et sur un pouvoir. Marqué sur les seules lignes montrées — les
    # relever toutes pour en afficher cinq cents serait payer pour rien.
    marques = marques_parmi_les_comptes(
        loader.identities, loader.config.privileges, DataLoader.COL_USER_ID,
        (ligne["identite"] for ligne in montrees))
    # Les origines sont des identifiants : c'est ce qui reste stable quand un
    # rôle est renommé, et ce qu'une dérogation peut citer. L'écran, lui, doit
    # montrer le nom — « role_applicatif_0d3f… » ne dit rien à un auditeur.
    # Seuls les rôles cités par les lignes montrées sont nommés.
    cites = {origine for ligne in montrees
             for origine in (*ligne["origines_gauche"], *ligne["origines_droite"])}
    noms = {str(role.get("id") or ""): str(role.get("name") or "")
            for role in catalogue}
    return {
        **synthese(regle, trouves, toxiques),
        "derogees": sum(1 for ligne in lignes if ligne["derogation"]),
        "roles": toxiques,
        # `lignes` et non `identites` : la synthèse emploie déjà `identites`
        # pour le **compte**, et rendre une liste sous le même nom ferait
        # écrire `identites.length` là où il fallait `identites` — un écran qui
        # affiche « 2 » au lieu de « 40 » sans que rien ne le signale.
        "lignes": montrees,
        # Rendus à part des lignes : une clé ajoutée à un enregistrement du
        # client écraserait celle qui porterait ce nom chez lui.
        "comptes_a_privileges": sorted(marques),
        "noms_des_roles": {identifiant: noms[identifiant]
                           for identifiant in sorted(cites)
                           if noms.get(identifiant)},
        # Dit quand la liste est tronquée : un écran qui montre cinq cents
        # lignes sur douze mille sans le dire se lit comme un écran complet.
        "tronquee": len(trouves) > IDENTITES_DETAILLEES_MAX,
    }


#: Ensembles examinés en un appel. L'écran des résultats de mining en marque
#: toutes les cartes d'un coup : les contrôler un par un ferait autant d'allers
#: et retours que de candidats.
ENSEMBLES_MAX = 200

#: Droits et membres d'un ensemble. Les premiers bornent le calcul, les seconds
#: la taille de la demande — un candidat peut légitimement compter des milliers
#: de porteurs, et c'est l'écran qui les envoie.
DROITS_PAR_ENSEMBLE_MAX = 5000
MEMBRES_PAR_ENSEMBLE_MAX = 100_000


class EnsembleExamine(BaseModel):
    """Un ensemble de droits à confronter aux règles.

    Les droits viennent de l'appelant et non du serveur, comme pour
    l'explication d'un rôle : un candidat de mining vit dans l'écran,
    l'utilisateur peut en avoir décoché des droits, et c'est **ce qu'il a sous
    les yeux** qu'il faut contrôler. Contrôler le candidat tel que le serveur
    l'a calculé rassurerait sur un rôle que personne ne va valider.

    `membres` est **facultatif**, et c'est ce qui distingue les deux usages : la
    liste des résultats veut savoir quelles cartes marquer et n'envoie que les
    droits ; la fenêtre de validation veut en plus le coût de chaque retrait, et
    envoie les porteurs.
    """

    model_config = ConfigDict(extra="forbid")

    cle: str = Field(..., min_length=1, max_length=200)
    droits: List[str] = Field(default_factory=list,
                              max_length=DROITS_PAR_ENSEMBLE_MAX)
    membres: List[str] = Field(default_factory=list,
                               max_length=MEMBRES_PAR_ENSEMBLE_MAX)


class EnsemblesExamines(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ensembles: List[EnsembleExamine] = Field(default_factory=list,
                                             max_length=ENSEMBLES_MAX)


def _retrait(cote: FrozenSet[str], detenteurs: Mapping[str, set],
             membres: Sequence[str]) -> Dict[str, Any]:
    """Ce que coûterait le retrait de ce côté-ci du rôle.

    Le coût n'est pas « combien de personnes perdent un accès » : le rôle n'est
    pas encore appliqué, et un porteur qui détient le droit directement le garde
    quoi qu'il arrive. Ce qui change est **ce que le rôle explique** — c'est la
    grandeur que le produit emploie partout ailleurs, et la seule qui soit vraie
    ici.
    """
    concernes = set()
    habilitations = 0
    for droit in sorted(cote):
        porteurs = detenteurs.get(droit, set())
        touches = porteurs.intersection(membres) if membres else set()
        habilitations += len(touches)
        concernes |= touches
    return {"droits": sorted(cote), "habilitations": habilitations,
            "membres": len(concernes)}


@router.get("/roles")
async def marquer_le_catalogue(
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    user: User = Depends(require_permission_or_dev(LECTURE)),
) -> Dict[str, Any]:
    """Les rôles validés qui portent à eux seuls les deux côtés d'une règle.

    Le catalogue est la donnée du serveur : lui faire renvoyer les droits de
    chacun de ses rôles pour qu'on les lui contrôle coûterait un aller-retour
    proportionnel au référentiel, pour un calcul qu'il peut faire seul.

    Cette route ne lit **aucune habilitation** et **aucune identité** : un rôle
    en conflit l'est par ce qu'il accorde, pas par qui le porte. C'est ce qui la
    rend assez peu chère pour marquer un catalogue à chaque affichage — et c'est
    aussi ce qui la rend exacte pour un rôle qui n'a encore aucun porteur.
    """
    return await run_in_threadpool(_marques, loader, kb)


def _marques(loader: DataLoader, kb: KnowledgeBase) -> Dict[str, Any]:
    catalogue = kb.get_validated_roles()
    regles = [regle for regle in _resolues(loader, kb, catalogue)
              if regle.applicable]
    par_role: Dict[str, List[Dict[str, Any]]] = {}
    for regle in regles:
        for trouve in roles_en_conflit(regle, catalogue):
            par_role.setdefault(trouve["role_id"], []).append(
                {"regle": regle.identifiant, "libelle": regle.libelle,
                 "gauche": trouve["gauche"], "droite": trouve["droite"]})
    return {"roles": par_role}


@router.post("/controler")
async def controler_des_droits(
    envoi: EnsemblesExamines,
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    user: User = Depends(require_permission_or_dev(LECTURE)),
) -> Dict[str, Any]:
    """Les règles qu'un ou plusieurs ensembles de droits enfreindraient.

    C'est le même calcul que les rôles du catalogue, posé **avant** la
    validation plutôt qu'après : un rôle qui réunit deux pouvoirs incompatibles
    donnera le conflit à tous ses porteurs, présents et futurs, et le moment où
    cela coûte le moins cher à corriger est celui où on le regarde.

    Quand les membres sont fournis, chaque règle enfreinte porte **les deux
    retraits possibles** et ce que chacun coûterait. Le produit ne choisit pas :
    il ne sait pas de quel pouvoir le rôle est censé parler, et les deux chiffres
    côte à côte rendent la décision évidente sans qu'il ait à trancher.

    Le produit **signale et ne refuse pas**. Un rôle peut légitimement réunir
    deux droits qu'une règle sépare — parce que la règle est trop large, parce
    que la population visée est contrôlée autrement. Refuser à la place de
    l'analyste ferait contourner le contrôle plutôt que le respecter, et le
    produit perdrait la trace de la décision.
    """
    return await run_in_threadpool(_controler, loader, kb, envoi)


def _controler(loader: DataLoader, kb: KnowledgeBase,
               envoi: EnsemblesExamines) -> Dict[str, Any]:
    if not envoi.ensembles:
        return {"ensembles": []}
    regles = [regle for regle in _resolues(loader, kb) if regle.applicable]
    if not regles:
        return {"ensembles": [{"cle": ensemble.cle, "regles": []}
                              for ensemble in envoi.ensembles]}

    # Les détenteurs ne sont relevés que si quelqu'un demande un coût, et
    # seulement sur les droits des règles : le référentiel entier coûterait le
    # prix d'un mining pour décorer une fenêtre.
    vises = {droit for regle in regles for droit in (regle.gauche | regle.droite)}
    detenteurs: Dict[str, set] = {}
    if any(ensemble.membres for ensemble in envoi.ensembles):
        detenteurs = detenteurs_par_droit(loader.habilitations,
                                          DataLoader.COL_USER_ID,
                                          DataLoader.COL_RIGHT_ID, vises)

    rendus = []
    for ensemble in envoi.ensembles:
        detenus = {str(droit) for droit in ensemble.droits}
        enfreintes = []
        for regle in regles:
            gauche = regle.gauche & detenus
            droite = regle.droite & detenus
            if not gauche or not droite:
                continue
            enfreinte = {"regle": regle.identifiant, "libelle": regle.libelle,
                         "gauche": sorted(gauche), "droite": sorted(droite)}
            if ensemble.membres:
                enfreinte["retraits"] = [
                    _retrait(gauche, detenteurs, ensemble.membres),
                    _retrait(droite, detenteurs, ensemble.membres)]
            enfreintes.append(enfreinte)
        rendus.append({"cle": ensemble.cle, "regles": enfreintes})
    return {"ensembles": rendus}


@router.get("/candidats")
async def proposer_des_couples(
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    user: User = Depends(require_permission_or_dev(LECTURE)),
) -> Dict[str, Any]:
    """Les couples de droits que la population sépare déjà.

    Un client devant une liste de règles vide et quarante mille droits ne la
    remplira jamais. Les données, elles, savent quelque chose : deux droits que
    beaucoup détiennent séparément et que personne ne réunit sont une règle que
    l'organisation applique sans l'avoir écrite.

    Rien n'est enregistré, et rien n'est affirmé : le produit rend le couple et
    ce qui l'a motivé — combien de personnes ont l'un, combien ont l'autre,
    combien on en attendrait avec les deux. La règle reste à écrire à la main.
    """
    return await run_in_threadpool(_candidats, loader, kb)


def _candidats(loader: DataLoader, kb: KnowledgeBase) -> Dict[str, Any]:
    matrice = loader.matrix
    encodeur = loader.right_encoder
    if matrice is None or not encodeur:
        return {"couples": [], "droits_confrontes": 0}
    droits = [""] * len(encodeur)
    for droit, rang in encodeur.items():
        droits[rang] = str(droit)
    reglages = Reglages.depuis_la_configuration(loader.config)
    couples = couples_antagonistes(
        matrice, droits, reglages,
        declares=couples_declares(_resolues(loader, kb)))
    return {"couples": couples,
            "droits_confrontes": min(len(droits),
                                     reglages.droits_confrontes_max)}
