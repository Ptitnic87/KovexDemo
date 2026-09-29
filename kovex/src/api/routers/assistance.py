# src/api/routers/assistance.py
"""L'écran qui répond à « qu'est-ce qui peut sortir d'ici, et pour quoi faire ».

Un administrateur doit pouvoir répondre à cette question **sur un seul écran**,
sans parcourir le produit. C'est l'objet de ces deux routes : elles rendent la
matrice usage × matière telle qu'elle s'applique, et la réécrivent.

La lecture dit aussi l'état de l'infrastructure — le point de terminaison, son
hôte, si l'envoi quitte le poste — parce que les deux décisions se lisent
ensemble : un usage ouvert sans point de terminaison ne fait rien, un point de
terminaison sans usage ouvert non plus, et l'écran doit dire lequel des deux
manque plutôt que d'afficher un bouton inerte.

L'écriture est une décision de gouvernance, et elle est tracée comme telle.
"""

import json
import logging
from typing import Any, Dict, List
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from starlette.concurrency import run_in_threadpool

from src.api.dependencies import clear_all_caches, get_data_loader, get_kb
from src.api.journal import Journal, get_journal
from src.api.routers.settings import chemin_de_configuration, lire_la_configuration
from src.core.annotation.annotateur import (
    AnnotateurIndisponible,
    ReponseInexploitable,
    RienANommer,
    depuis_l_environnement,
    envoyer,
)
from src.core.annotation.assistance import (
    CLE_ASSISTANCE,
    MATIERES,
    PAR_CODE,
    USAGES,
    USAGE_ATTRIBUTS_PERTINENTS,
    USAGE_COMPTES_A_PRIVILEGES,
    USAGE_DROITS_SENSIBLES,
    USAGE_EXPLICATION_DE_CONFLIT,
    USAGE_EXPLICATION_DE_ROLE,
    Assistance,
    Autorisation,
)
from src.core.annotation.explication import (
    SCHEMA_DE_L_EXPLICATION,
    expliquer_un_role,
)
from src.core.annotation.propositions import (
    SCHEMA_DES_FRAGMENTS,
    SCHEMA_DU_CLASSEMENT,
    proposer_les_attributs,
    proposer_les_comptes_a_privileges,
    proposer_les_droits_sensibles,
)
from src.core.audit.piste_audit import Action
from src.core.data.loader import DataLoader
from src.core.knowledge.knowledge_base import KnowledgeBase
from src.core.security.auth import User, require_permission_or_dev

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assistance")

#: Régler ce qui a le droit de quitter le système est un acte d'administration.
#: Un analyste pose la question au modèle ; il ne décide pas de ce qui part.
ASSISTANCE_PERMISSION = "admin"

#: Comment l'usage a besoin d'une matière. Ces trois mots sont rendus à
#: l'écran, qui les traduit : une case cochable doit dire si la décocher rend
#: la question impossible ou seulement moins bonne.
EXIGENCE_NECESSAIRE = "necessaire"
EXIGENCE_AU_MOINS_UNE = "au_moins_une"
EXIGENCE_FACULTATIVE = "facultative"


class ColonneOuverte(BaseModel):
    """Une colonne dont les valeurs ont le droit de sortir, pour un usage.

    Aucune vérification d'existence : les colonnes du client ne sont pas
    connues à l'avance, et une autorisation écrite pour un fichier
    momentanément absent ne doit pas disparaître de la configuration au premier
    enregistrement.
    """

    model_config = ConfigDict(extra="forbid")

    referentiel: str = Field(..., min_length=1, max_length=40)
    colonne: str = Field(..., min_length=1, max_length=200)


class UsageDemande(BaseModel):
    """Ce qu'un administrateur demande pour un usage.

    `extra: forbid` : un champ inconnu est refusé plutôt qu'ignoré. Une
    version plus récente de l'écran qui enverrait un réglage que ce serveur ne
    connaît pas doit obtenir un refus visible, et non une acceptation qui
    n'aurait rien réglé.
    """

    model_config = ConfigDict(extra="forbid")

    actif: bool = Field(False)
    matiere: List[str] = Field(default_factory=list)
    #: Les colonnes ouvertes, pour les usages qui se délimitent ainsi. Vide
    #: par défaut, donc fermé : c'est la même règle que la matière.
    colonnes: List[ColonneOuverte] = Field(default_factory=list, max_length=500)


class AssistanceDemandee(BaseModel):
    """La matrice entière, jamais un fragment.

    Un usage absent du corps est écrit **fermé**. Enregistrer une matrice
    partielle laisserait ouvert ce que l'écran croyait avoir fermé : le
    document reçu fait foi dans son entier, comme l'écran le montre.
    """

    model_config = ConfigDict(extra="forbid")

    usages: Dict[str, UsageDemande] = Field(default_factory=dict)


def _point_de_terminaison(code: str) -> Dict[str, Any]:
    """Ce que l'infrastructure a configuré pour cet usage.

    L'adresse n'est pas rendue : seul son hôte l'est. Il suffit à dire si
    l'envoi reste sur la machine, et il ne peut pas transporter de secret
    glissé dans un chemin ou un paramètre. La clé, elle, n'est ni rendue, ni
    comparée, ni signalée comme présente.
    """
    from src.api.reglages_du_modele import reglages_et_origine

    commun = reglages_et_origine()[0]
    reglages, origine = reglages_et_origine(code)
    return {
        "actif": reglages.actif,
        "hote": urlsplit(reglages.adresse).hostname or "",
        "modele": reglages.modele,
        "locale": reglages.locale,
        # Qui l'a décidé : l'installation, l'écran, ou personne. L'écran s'en
        # sert pour dire ce qui se modifie ici et ce qui est imposé ailleurs.
        "origine": origine,
        # Vrai quand cet usage a son propre point de terminaison, distinct du
        # réglage commun. L'écran le dit : c'est la différence entre « tout
        # passe par le même modèle » et « cette question-là part ailleurs ».
        "propre": bool(reglages.adresse) and reglages.adresse != commun.adresse,
    }


def _exigences(code: str) -> List[Dict[str, str]]:
    """La matière que cet usage déclare, et à quel titre.

    Déclarée dans le code, jamais dans la configuration : sans cela, l'écran
    afficherait une grille de cases que personne ne saurait remplir, et le
    produit ne saurait pas refuser tôt une configuration qui ne peut rien
    donner.
    """
    usage = PAR_CODE[code]
    par_exigence = (
        (EXIGENCE_NECESSAIRE, usage.necessaires),
        (EXIGENCE_AU_MOINS_UNE, usage.au_moins_une),
        (EXIGENCE_FACULTATIVE, usage.facultatives),
    )
    declarees = {matiere: exigence
                 for exigence, matieres in par_exigence for matiere in matieres}
    # L'ordre d'affichage est celui du catalogue de matières, et non celui de
    # la déclaration : deux usages doivent présenter leurs cases dans le même
    # ordre, sans quoi l'administrateur relit à chaque bloc.
    return [{"matiere": matiere, "exigence": declarees[matiere]}
            for matiere in MATIERES if matiere in declarees]


def _vue(autorisation: Autorisation) -> Dict[str, Any]:
    return {
        "code": autorisation.usage.code,
        "actif": autorisation.actif,
        "matiere": list(autorisation.matiere_effective),
        "declarees": _exigences(autorisation.usage.code),
        # Ce qu'il faudrait ouvrir pour que la question puisse être posée. Un
        # usage actif mais muet doit le dire : sinon l'administrateur croit
        # avoir configuré, et c'est l'utilisateur qui découvre le refus.
        "manque": list(autorisation.manque),
        "posable": autorisation.posable,
        # Cet usage se délimite-t-il par colonne, et lesquelles sont ouvertes.
        # `portee_ouverte` n'est pas `posable` : la matière peut être
        # entièrement ouverte alors qu'aucune colonne ne l'est, et ce ne sont
        # pas le même geste à faire.
        "par_colonne": autorisation.usage.par_colonne,
        "colonnes": [{"referentiel": referentiel, "colonne": colonne}
                     for referentiel, colonne in autorisation.colonnes_effectives],
        "portee_ouverte": autorisation.portee_ouverte,
        "point_de_terminaison": _point_de_terminaison(autorisation.usage.code),
        # Faux pour le serveur MCP : il n'appelle aucun modèle, il répond à un
        # agent extérieur. L'écran ne lui propose donc pas de trajet à régler.
        "appelle_un_modele": autorisation.usage.appelle_un_modele,
    }


@router.get("/")
def lire_l_assistance(
    loader: DataLoader = Depends(get_data_loader),
    user: User = Depends(require_permission_or_dev(ASSISTANCE_PERMISSION)),
) -> Dict[str, Any]:
    """La matrice telle qu'elle s'applique, tous usages connus compris.

    Les usages fermés figurent aussi : une fonction invisible passe pour une
    fonction manquante, et la question revient en avant-vente.
    """
    assistance = loader.config.assistance
    return {
        "usages": [_vue(assistance.pour(usage.code)) for usage in USAGES],
        "matieres": list(MATIERES),
        # Ce qui a été écarté à la lecture : un usage ou une matière que ce
        # code ne connaît pas. Ignoré, jamais ouvert — et dit, jamais tu.
        "avertissements": list(assistance.avertissements),
    }


@router.put("/")
def ecrire_l_assistance(
    demande: AssistanceDemandee,
    journal: Journal = Depends(get_journal),
    user: User = Depends(require_permission_or_dev(ASSISTANCE_PERMISSION)),
) -> Dict[str, Any]:
    """Réécrit la matrice dans la configuration du workspace actif.

    Deux refus, tous deux fermants et tous deux explicites plutôt que
    silencieux : un usage que ce code ne sait pas conduire, et une matière que
    l'usage visé ne déclare pas. Accepter l'un ou l'autre en l'ignorant
    laisserait un administrateur croire qu'il a ouvert — ou pire, fermé —
    quelque chose.
    """
    inconnus = sorted(set(demande.usages) - set(PAR_CODE))
    if inconnus:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "assistance.unknown_usage",
                    "params": {"usages": ", ".join(inconnus)}})

    for code, voulu in demande.usages.items():
        etrangeres = sorted(set(voulu.matiere) - set(PAR_CODE[code].matieres))
        if etrangeres:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "assistance.matter_not_declared",
                        "params": {"usage": code,
                                   "matieres": ", ".join(etrangeres)}})
        if voulu.colonnes and not PAR_CODE[code].par_colonne:
            # Accepter la liste en l'ignorant laisserait croire à une
            # restriction qui n'existe pas — le refus le plus utile de tous.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "assistance.columns_not_scoped",
                        "params": {"usage": code}})

    document: Dict[str, Any] = {}
    for usage in USAGES:
        voulu = demande.usages.get(usage.code)
        entree: Dict[str, Any] = {
            "actif": bool(voulu.actif) if voulu else False,
            # Réécrit dans l'ordre du catalogue, et dédoublonné : le document
            # se relit et se compare d'une version à l'autre.
            "matiere": [matiere for matiere in MATIERES
                        if voulu and matiere in set(voulu.matiere)],
        }
        if usage.par_colonne:
            paires = sorted({(c.referentiel, c.colonne)
                             for c in (voulu.colonnes if voulu else ())})
            entree["colonnes"] = [{"referentiel": referentiel, "colonne": colonne}
                                  for referentiel, colonne in paires]
        document[usage.code] = entree

    chemin = chemin_de_configuration()
    configuration = lire_la_configuration(chemin)
    configuration[CLE_ASSISTANCE] = document
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(
            json.dumps(configuration, indent=4, ensure_ascii=False),
            encoding="utf-8")
    except OSError as erreur:
        logger.error("Assistance non enregistrée (%s) : %s", chemin, erreur)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "settings.not_saved"})

    # Sans purge, la matrice écrite ne prendrait effet qu'au redémarrage — et
    # l'administrateur verrait l'ancienne à l'écran suivant.
    clear_all_caches()

    for code, entree in sorted(document.items()):
        journal.consigner(
            Action.ASSISTANCE_MODIFIEE, "assistance", code,
            {"actif": entree["actif"],
             "categories": ", ".join(entree["matiere"]),
             # Compté, jamais nommé : la liste des colonnes ouvertes d'un
             # client dit comment son référentiel est bâti.
             "colonnes": len(entree.get("colonnes", ()))})

    assistance = Assistance.depuis_la_configuration(configuration)
    return {
        "usages": [_vue(assistance.pour(usage.code)) for usage in USAGES],
        "matieres": list(MATIERES),
        "avertissements": list(assistance.avertissements),
    }


# ------------------------------------------------------------ les propositions


#: Poser la question est un geste d'analyste : c'est lui qui règle son mining
#: et sa liste de droits sensibles. Décider de ce qui a le droit de sortir
#: reste une décision d'administration, et elle est prise ailleurs — dans la
#: matrice, avant que ce bouton n'existe.
PROPOSITION_PERMISSION = "mining"


class Demande(BaseModel):
    """La langue de la réponse, et rien d'autre.

    Ce que le modèle reçoit vient du référentiel, jamais de l'appelant : un
    client ne peut donc pas faire sortir des données en les glissant dans la
    demande.
    """

    model_config = ConfigDict(extra="forbid")

    locale: str = Field(..., min_length=2, max_length=8)


def _contexte(usage: str, loader: DataLoader):
    """Les réglages et l'autorisation de cet usage, dans cet ordre."""
    from src.api.reglages_du_modele import reglages_pour

    return (reglages_pour(usage), loader.config.assistance.pour(usage))


def _consigner(journal: Journal, usage: str, proposition: Dict[str, Any],
               reglages) -> None:
    """La trace : l'usage, ce qui est sorti, et si c'est sorti du poste.

    Jamais le contenu — il est déjà dans le référentiel, et une piste d'audit
    qui recopierait les libellés de droits deviendrait elle-même une donnée à
    protéger.
    """
    journal.consigner(
        Action.ASSISTANCE_CONSULTEE, "assistance", usage,
        {"usage": usage, "modele": proposition["modele"],
         "categories": ", ".join(proposition["categories_transmises"]),
         "hors_du_poste": not reglages.locale})


def _repondre(usage: str, appel, journal: Journal, reglages) -> Dict[str, Any]:
    """Traduit les deux refus possibles en réponses distinctes.

    Ce ne sont pas la même chose : un usage fermé se règle dans l'écran
    d'assistance, un modèle injoignable se règle sur le serveur. Les confondre
    enverrait l'utilisateur au mauvais endroit.
    """
    try:
        proposition = appel()
    except RienANommer:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "assistance.usage_closed",
                    "params": {"usage": usage}})
    except AnnotateurIndisponible as erreur:
        logger.info("Aucune proposition (%s) : %s", usage, erreur)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "annotator.unavailable"})

    _consigner(journal, usage, proposition, reglages)
    return proposition


@router.post("/droits-sensibles")
async def proposer_droits_sensibles(
    demande: Demande,
    loader: DataLoader = Depends(get_data_loader),
    journal: Journal = Depends(get_journal),
    user: User = Depends(require_permission_or_dev(PROPOSITION_PERMISSION)),
) -> Dict[str, Any]:
    """Propose les fragments de nom qui signalent un droit sensible.

    Le réglage existe depuis longtemps et reste vide chez la plupart des
    clients, faute de savoir quoi y mettre — un réglage vide est une
    fonctionnalité morte.

    **Les mots viennent du modèle, les chiffres du calcul.** Chaque fragment
    proposé est cherché dans le référentiel entier : celui qui ne correspond à
    rien est écarté, et le nombre de droits que les autres signaleraient est
    compté ici. Rien n'est enregistré : la liste remplit un champ que
    quelqu'un relit.
    """
    usage = USAGE_DROITS_SENSIBLES.code
    reglages, autorisation = _contexte(usage, loader)
    libelles = await run_in_threadpool(_libelles_de_droits, loader)

    # Le schéma part avec la demande : le point de terminaison qui sait
    # contraindre sa génération le fera, celui qui ne sait pas le refusera et
    # la négociation redescendra d'elle-même.
    return _repondre(usage, lambda: proposer_les_droits_sensibles(
        reglages, autorisation, libelles, demande.locale,
        lambda charge: envoyer(charge, reglages, SCHEMA_DES_FRAGMENTS)),
        journal, reglages)


def _libelles_de_droits(loader: DataLoader) -> List[str]:
    """Tout ce qui, dans le référentiel des droits, porte un nom.

    Toutes les colonnes textuelles, et non la seule colonne d'identifiant :
    les colonnes ne sont pas connues à l'avance, et c'est souvent un libellé
    voisin — pas l'identifiant — qui dit qu'un droit touche à la paie.
    """
    droits = loader.rights
    if droits is None or droits.empty:
        return []
    valeurs: List[str] = []
    for colonne in droits.columns:
        valeurs.extend(str(valeur) for valeur in droits[colonne].dropna().unique())
    return valeurs


@router.post("/comptes-a-privileges")
async def proposer_comptes_a_privileges(
    demande: Demande,
    loader: DataLoader = Depends(get_data_loader),
    journal: Journal = Depends(get_journal),
    user: User = Depends(require_permission_or_dev(PROPOSITION_PERMISSION)),
) -> Dict[str, Any]:
    """Propose les fragments d'identifiant qui signalent un compte à privilèges.

    **Rien ne sort.** La question posée au modèle ne parle pas de ce client :
    elle demande comment les systèmes d'habilitations nomment usuellement
    leurs comptes d'administration. Les identifiants du référentiel restent
    ici et servent au dénombrement, après la réponse.

    La proposition est donc du savoir général **éprouvé localement** : un
    fragment qui ne marque aucun compte est écarté, et le nombre montré pour
    les autres est compté sur le référentiel entier, à la place déclarée dans
    les paramètres. Rien n'est enregistré : la liste remplit un champ que
    quelqu'un relit.
    """
    usage = USAGE_COMPTES_A_PRIVILEGES.code
    reglages, autorisation = _contexte(usage, loader)
    valeurs = await run_in_threadpool(_valeurs_du_marqueur, loader)

    return _repondre(usage, lambda: proposer_les_comptes_a_privileges(
        reglages, autorisation, valeurs, loader.config.privileges.place,
        demande.locale,
        lambda charge: envoyer(charge, reglages, SCHEMA_DES_FRAGMENTS)),
        journal, reglages)


def _valeurs_du_marqueur(loader: DataLoader) -> List[str]:
    """Les valeurs où le marqueur cherche : la colonne déclarée, ou
    l'identifiant du compte.

    Une colonne déclarée puis absente rend une liste vide, et la proposition
    s'arrête sur « référentiel vide » plutôt que de se rabattre sur
    l'identifiant : compter sur une autre colonne que celle déclarée donnerait
    des nombres justes pour une règle que l'utilisateur n'a pas écrite.
    """
    identites = loader.identities
    if identites is None or identites.empty:
        return []
    colonne = loader.config.privileges.colonne or DataLoader.COL_USER_ID
    if colonne not in identites.columns:
        return []
    return [str(valeur) for valeur in identites[colonne].dropna()]


@router.post("/attributs-pertinents")
async def proposer_attributs_pertinents(
    demande: Demande,
    loader: DataLoader = Depends(get_data_loader),
    journal: Journal = Depends(get_journal),
    user: User = Depends(require_permission_or_dev(PROPOSITION_PERMISSION)),
) -> Dict[str, Any]:
    """Distingue, parmi les colonnes d'identités, le métier de l'identifiant.

    L'analyste les trouve aujourd'hui par essais successifs, à plusieurs
    minutes la tentative. La proposition ne coche rien : la règle de
    cardinalité reste le garde-fou, et c'est l'écran qui montre les deux.

    **Seuls les noms des colonnes sortent.** Juger que `matricule` identifie et
    que `service` porte du métier ne demande pas de savoir qui travaille où.
    """
    usage = USAGE_ATTRIBUTS_PERTINENTS.code
    reglages, autorisation = _contexte(usage, loader)
    identites = loader.identities
    colonnes = [] if identites is None or identites.empty else list(identites.columns)

    return _repondre(usage, lambda: proposer_les_attributs(
        reglages, autorisation, colonnes, demande.locale,
        lambda charge: envoyer(charge, reglages, SCHEMA_DU_CLASSEMENT)),
        journal, reglages)


class DemandeDExplication(Demande):
    """Un rôle candidat, et la langue de la réponse.

    Le rôle vient de l'appelant et non du serveur, comme pour le nommage : les
    candidats d'un mining vivent dans l'écran, l'utilisateur peut en avoir
    décoché des droits, et c'est **ce qu'il a sous les yeux** qu'il fait
    expliquer. Les grandeurs sont donc celles de l'écran — et c'est aussi
    pourquoi le contrôle des nombres est fait sur elles : il garantit que la
    phrase ne dit rien de plus que ce qui a été transmis, quelle qu'en soit la
    provenance.
    """

    model_config = ConfigDict(extra="forbid")

    role: Dict[str, Any] = Field(default_factory=dict)
    explication: Dict[str, Any] = Field(default_factory=dict)


@router.post("/explication-de-role")
async def expliquer_role(
    demande: DemandeDExplication,
    loader: DataLoader = Depends(get_data_loader),
    journal: Journal = Depends(get_journal),
    user: User = Depends(require_permission_or_dev(PROPOSITION_PERMISSION)),
) -> Dict[str, Any]:
    """Rédige l'explication d'un rôle, ou ne rend rien.

    C'est le livrable que le consultant écrit à la main, rôle par rôle, à la
    fin du projet. Le point délicat n'est pas la rédaction : c'est que **tout
    nombre de la phrase figure parmi ceux transmis**. Une phrase crédible qui
    annonce un effectif inventé est le pire cas pour ce produit, et elle est
    refusée — jamais corrigée, jamais tronquée.
    """
    usage = USAGE_EXPLICATION_DE_ROLE.code
    reglages, autorisation = _contexte(usage, loader)

    def appel():
        return expliquer_un_role(
            reglages, autorisation, demande.role, demande.explication,
            demande.locale,
            lambda charge: envoyer(charge, reglages, SCHEMA_DE_L_EXPLICATION))

    return _repondre(usage, _nombres_controles(usage, appel), journal, reglages)


def _nombres_controles(usage: str, appel):
    """L'appel, avec le refus d'un nombre inventé rendu comme tel.

    Ce n'est pas une panne : c'est le contrôle qui a fait son travail. Les
    confondre ferait chercher un serveur injoignable là où un modèle a inventé
    un chiffre, et l'écran doit pouvoir dire lequel.
    """
    def controle():
        try:
            return appel()
        except ReponseInexploitable as refus:
            if not refus.details.get("nombres_inventes"):
                raise
            logger.info("Explication refusée (%s) : %s", usage, refus)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "annotator.refused",
                        "params": {"nombres": ", ".join(
                            refus.details["nombres_inventes"])}})
    return controle


class DemandeDExplicationDeConflit(Demande):
    """Une règle de séparation, désignée par son identifiant.

    Rien d'autre ne vient de l'appelant : les comptes, les libellés et les
    rôles sont relus sur le serveur, sur les données du jour. Un appelant ne
    peut donc ni faire expliquer des chiffres qu'il aurait écrits, ni glisser
    dans la demande une donnée que l'administrateur n'a pas ouverte.
    """

    model_config = ConfigDict(extra="forbid")

    regle: str = Field(..., min_length=1, max_length=64)


def _cotes_en_conflit(lignes) -> tuple:
    """Les droits de chaque côté que les conflits réunissent vraiment.

    Pas les droits que la règle désigne : une règle qui nomme une application
    entière vise des centaines de droits, et le paragraphe doit parler de ceux
    que les gens détiennent. Les plus fréquents d'abord.
    """
    comptes = ({}, {})
    for ligne in lignes:
        for cote, compte in zip(("gauche", "droite"), comptes):
            for droit in ligne[cote]:
                compte[droit] = compte.get(droit, 0) + 1
    return tuple([droit for droit, _ in sorted(compte.items(),
                                               key=lambda paire: (-paire[1], paire[0]))]
                 for compte in comptes)


@router.post("/explication-de-conflit")
def expliquer_conflit(
    demande: DemandeDExplicationDeConflit,
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
    user: User = Depends(require_permission_or_dev(PROPOSITION_PERMISSION)),
) -> Dict[str, Any]:
    """Rédige le paragraphe qui explique une règle en conflit, ou ne rend rien.

    Aucune identité ne part : le paragraphe porte sur la règle, à l'échelle de
    la population. Tout nombre écrit doit figurer parmi les comptes transmis.
    """
    from src.api.routers.separation import _detail
    from src.core.annotation.explication_conflit import expliquer_un_conflit

    usage = USAGE_EXPLICATION_DE_CONFLIT.code
    reglages, autorisation = _contexte(usage, loader)
    detail = _detail(loader, kb, demande.regle)
    gauche, droite = _cotes_en_conflit(detail["lignes"])
    roles = [role["role"] or role["role_id"] for role in detail["roles"]]

    def appel():
        return expliquer_un_conflit(
            reglages, autorisation, detail, gauche, droite, roles, demande.locale,
            lambda charge: envoyer(charge, reglages, SCHEMA_DE_L_EXPLICATION))

    return _repondre(usage, _nombres_controles(usage, appel), journal, reglages)
