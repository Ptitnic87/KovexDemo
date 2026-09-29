"""
API Router pour la Knowledge Base
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime
from src.core.knowledge.knowledge_base import KnowledgeBase
# Renommé à l'import : la route de ce module s'appelle aussi
# `porteurs_du_role`, et la seconde définition recouvrait la première — les
# porteurs d'un rôle étaient alors calculés par une coroutine jamais attendue.
from src.core.knowledge.population import droits_par_identite
from src.core.knowledge.population import porteurs_du_role as porteurs_calcules
from src.core.knowledge.socle import (IDENTIFIANT_SOCLE, detail_du_socle,
                                      membres_du_socle)
from src.core.knowledge.travail_en_attente import travail_en_attente
from src.core.role.identite import TYPES_DE_ROLE
from src.api.journal import Journal, get_journal
from src.core.audit import Action
from src.api.dependencies import get_data_loader, get_kb  # Import depuis dependencies pour workspaces
from src.api import schemas
from src.api.lignes import (REFERENTIELS_DE_LIGNES, TAILLE_DE_PAGE_MAX,
                            LignesRendues, Pagination, restreindre_puis_paginer)
from src.core.data.loader import DataLoader

#: Au-delà de ce nombre de valeurs distinctes, une colonne d'identité n'est plus
#: un critère de périmètre mais un identifiant. La proposer noierait celles qui
#: en sont un — et le produit ne connaît pas les colonnes à l'avance, il ne peut
#: donc pas les distinguer autrement que par leur cardinalité.
VALEURS_PROPOSEES_MAX = 200

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/kb", tags=["Knowledge Base"])


# ========== MODELS ==========

class BirthRightsSet(BaseModel):
    rights: List[str]
    threshold: float = 90.0
    #: Nom du rôle socle. Absent, il conserve celui qui est enregistré :
    #: relancer une détection ne doit pas effacer le nom sous lequel
    #: l'intégrateur a déjà reçu le socle.
    name: Optional[str] = Field(None, max_length=200)


class NomDuSocle(BaseModel):
    """Le nom sous lequel l'IGA recevra le socle.

    Il n'est pas écrit dans le code : « Socle commun » chez un client,
    « Droits d'accueil » chez un autre, et parfois une convention de nommage
    imposée. Vide, le socle garde son libellé traduit à l'écran.
    """

    name: str = Field("", max_length=200)


class ApplicationDeProposition(BaseModel):
    """Ce que le client renvoie pour appliquer une proposition de la revue.

    **Une empreinte, jamais un ordre.** Le serveur recalcule la revue et
    n'applique que la proposition qu'il retrouve sous cette empreinte : une
    charge forgée — « retire tel droit de tel rôle » — ne correspond à aucune
    proposition recalculée et n'est pas appliquée. Une route d'analyse ne doit
    pas pouvoir servir de porte d'entrée pour modifier le catalogue.
    """

    model_config = {"extra": "forbid"}

    empreinte: str


class RenommageDeRole(BaseModel):
    """Le nom et la description d'un rôle validé.

    Renommer versionne. Le nom fait partie de ce que l'IGA du client a reçu :
    un rôle renommé en silence, c'est le doublon que le versionnement existe
    précisément pour éviter.
    """

    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class NomRetenu(BaseModel):
    """Un nom et une description retenus pour un candidat.

    Bornés comme ceux d'un rôle validé : un candidat nommé ici finit dans le
    catalogue, et un intitulé qu'on ne peut pas afficher n'y serait pas moins
    gênant pour avoir transité par un lot.
    """

    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class NomsDeCandidats(BaseModel):
    """Les noms retenus d'un lot, par identifiant de candidat.

    Le plafond n'est pas un choix d'ergonomie : c'est une borne sur la taille
    d'une écriture que l'API accepte. Un lot plus grand s'envoie en plusieurs
    fois, ce que l'écran fait déjà puisqu'il interroge le modèle un rôle
    après l'autre.
    """

    model_config = {"extra": "forbid"}

    noms: Dict[str, NomRetenu] = Field(default_factory=dict, max_length=5000)


class DevalidationDeRole(BaseModel):
    """Sortir un rôle du catalogue, et dire pourquoi.

    Le motif est obligatoire, comme pour un rejet : c'est lui qui, dans six
    mois, expliquera pourquoi ce rôle n'existe plus.
    """

    model_config = {"extra": "forbid"}

    motif: str = Field(min_length=1, max_length=2000)


class RoleValidation(BaseModel):
    id: str
    name: str
    description: str
    role_type: str
    rights: List[str]
    users: Optional[List[str]] = []
    user_count: int
    sub_roles: Optional[List[str]] = []
    additional_rights: Optional[List[str]] = []
    indicateurs: Optional[schemas.IndicateursDeDecision] = None


class RoleRejection(BaseModel):
    role_id: str
    reason: Optional[str] = ""
    indicateurs: Optional[schemas.IndicateursDeDecision] = None


class UserExclusion(BaseModel):
    user_id: str
    reason: Optional[str] = ""


class BackupRestore(BaseModel):
    backup_path: str


# ========== DEPENDENCY ==========


# ========== ENDPOINTS ==========

@router.get("/stats")
async def get_kb_stats(kb: KnowledgeBase = Depends(get_kb)):
    """Retourne des statistiques sur la KB."""
    return kb.get_stats()


@router.get("/pending-work")
async def get_pending_work(
    kb: KnowledgeBase = Depends(get_kb),
    loader: DataLoader = Depends(get_data_loader),
):
    """Ce qu'il reste à décider sur les candidats du dernier mining.

    Un produit de gouvernance a une obligation particulière avec ce genre
    d'indicateur : il ne doit annoncer que du travail réel. Un compteur qui
    montre un chiffre parce qu'un calcul a eu lieu, et non parce qu'une
    décision est attendue, apprend à l'utilisateur à l'ignorer — et le jour où
    il compte, il est déjà ignoré.

    Le chiffre est donc calculé, jamais stocké : il se déduit des candidats
    conservés et des décisions prises. Aucun nouvel état à tenir à jour, donc
    aucun état à désynchroniser.

    L'obsolescence est rendue avec le compte : ce qui reste à décider peut
    porter sur des données rechargées depuis. Le dire est le minimum ; masquer
    le compte serait pire, puisque le travail existe toujours.
    """
    empreinte = await run_in_threadpool(loader.empreinte_donnees)
    return travail_en_attente(kb, TYPES_DE_ROLE, empreinte)


def _type_de_role_connu(role_type: str) -> str:
    """Refuse un type inconnu plutôt que de rendre un résultat vide.

    Une faute de frappe dans l'appel rendrait « aucun candidat », ce qui se lit
    comme « il n'y a rien à décider ». Sur cet écran, c'est le contresens à ne
    pas laisser passer.
    """
    if role_type not in TYPES_DE_ROLE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "role.unknown_type", "params": {"type": role_type}})
    return role_type


@router.get("/candidates/{role_type}")
async def get_candidates(
    role_type: str,
    kb: KnowledgeBase = Depends(get_kb),
    loader: DataLoader = Depends(get_data_loader),
):
    """Les candidats conservés du dernier mining d'un type, tels qu'affichés.

    Un mining sur un référentiel de vingt mille identités prend plusieurs
    minutes. Son résultat était conservé côté serveur depuis longtemps — le
    graphe s'en sert, le détail de population aussi — mais l'écran qui l'a
    produit ne le relisait jamais : revenir dessus affichait « Mining non
    lancé », et la seule façon de retrouver son travail était de tout
    recalculer. L'indicateur de travail en attente a rendu la contradiction
    visible : il annonçait des candidats que l'écran concerné disait ne pas
    avoir.

    La charge utile est celle du mining lui-même — rôles et indicateurs — pour
    que le résultat repris soit identique au résultat calculé, et non une
    version appauvrie. Elle est volumineuse : c'est pourquoi l'écran ne la
    demande que lorsque l'utilisateur choisit d'afficher le résultat conservé,
    et se contente sinon du comptage rendu par `pending-work`.
    """
    run = kb.get_candidate_run(_type_de_role_connu(role_type))
    if not run:
        return {"roles": [], "params": {}, "stats": {},
                "computed_at": None, "stale": False}

    empreinte = await run_in_threadpool(loader.empreinte_donnees)
    empreinte_du_run = run.get("data_fingerprint") or ""
    return {
        "roles": list(run.get("roles") or []),
        "params": run.get("params") or {},
        # Absents des minings antérieurs à leur conservation : le client
        # affiche alors les rôles sans le bandeau d'indicateurs, plutôt que des
        # cases vides qui se liraient comme des mesures nulles.
        "stats": run.get("stats") or {},
        "computed_at": run.get("computed_at"),
        "stale": bool(empreinte_du_run) and empreinte_du_run != empreinte,
    }


@router.post("/candidates/{role_type}/noms")
async def nommer_les_candidats(
    role_type: str,
    demande: NomsDeCandidats,
    kb: KnowledgeBase = Depends(get_kb),
) -> Dict[str, Any]:
    """Conserve les noms retenus sur les candidats d'un mining.

    Ce travail vivait dans la page : un rechargement perdait une heure de
    relecture. Il est écrit là où le mining est déjà conservé.

    **Aucune décision de gouvernance n'est prise ici**, et rien n'est donc
    consigné dans la piste d'audit : un candidat nommé n'est ni validé ni
    refusé, il attend toujours qu'on décide de lui. Les demandes faites au
    modèle, elles, sont tracées une par une au moment où elles partent — c'est
    là qu'une donnée quitte le système, pas ici.

    Un identifiant inconnu du jeu conservé est ignoré : le nombre rendu dit ce
    qui a réellement été écrit, et l'écran peut le comparer à ce qu'il a
    envoyé.
    """
    ecrits = await run_in_threadpool(
        kb.nommer_les_candidats, _type_de_role_connu(role_type),
        {identifiant: retenu.dict()
         for identifiant, retenu in demande.noms.items()})
    return {"status": "named", "role_type": role_type, "nommes": ecrits,
            "demandes": len(demande.noms)}


@router.delete("/candidates/{role_type}")
async def forget_candidates(
    role_type: str,
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
):
    """Oublie les candidats conservés d'un type.

    Sans cette porte de sortie, un mining lancé par erreur — ou devenu sans
    objet après un rechargement des données — resterait annoncé comme du
    travail en attente jusqu'à ce que quelqu'un relance un calcul de plusieurs
    minutes pour le remplacer.

    Ce n'est pas une décision de gouvernance : les candidats oubliés ne sont ni
    validés ni refusés, ils sont simplement retirés de l'écran. Un mining
    ultérieur les proposera de nouveau.
    """
    kb.clear_candidate_roles(_type_de_role_connu(role_type))
    journal.consigner(Action.CANDIDATS_OUBLIES, "mining", role_type)
    return {"status": "cleared", "role_type": role_type}


# === DROITS SOCLES ===

@router.get("/birth-rights")
async def get_birth_rights(kb: KnowledgeBase = Depends(get_kb)) -> List[str]:
    """Récupère les droits socles détectés."""
    return kb.get_birth_rights()


@router.get("/birth-rights/info")
async def get_birth_rights_info(kb: KnowledgeBase = Depends(get_kb)):
    """
    Récupère les infos complètes sur les droits socles.
    
    Returns:
        Dict avec threshold, detected_at, rights, count
    """
    return kb.get_birth_rights_info()


@router.post("/birth-rights")
async def set_birth_rights(
    data: BirthRightsSet,
    kb: KnowledgeBase = Depends(get_kb)
):
    """Enregistre les droits socles détectés."""
    kb.set_birth_rights(data.rights, data.threshold, data.name)
    return {"status": "success", "count": len(data.rights)}


@router.put("/birth-rights/name")
async def nommer_le_socle(
    demande: NomDuSocle,
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
) -> Dict[str, Any]:
    """Nomme le rôle socle.

    Le socle apparaît dans le catalogue et dans l'export comme n'importe quel
    autre rôle : il lui faut un nom, et ce nom est une décision du client, pas
    une constante du produit.
    """
    nom = await run_in_threadpool(kb.nommer_le_socle, demande.name)
    journal.consigner(Action.ROLE_MODIFIE, "role", IDENTIFIANT_SOCLE,
                      {"champs": ["name"], "nom": nom})
    return {"status": "renamed", "name": nom}


@router.delete("/birth-rights")
async def clear_birth_rights(kb: KnowledgeBase = Depends(get_kb)):
    """Efface les droits socles pour relancer une détection."""
    kb.clear_birth_rights()
    return {"status": "cleared"}


# === VALIDATED ROLES ===

@router.get("/validated-roles")
async def get_validated_roles(
    role_type: Optional[str] = None,
    kb: KnowledgeBase = Depends(get_kb)
):
    """
    Récupère les rôles validés.
    
    Query params:
        role_type: APPLICATIF, METIER, ou None pour tous
    """
    roles = kb.get_validated_roles(role_type=role_type)
    return {"roles": roles, "count": len(roles)}


def _revue_du_modele(loader: DataLoader, kb: KnowledgeBase) -> Dict[str, Any]:
    """Assemble la revue. Appelée hors de la boucle d'événements.

    Les membres viennent du **même** calcul que le complément et que le graphe :
    la règle d'abord, la liste enregistrée ensuite, la détention de tous les
    droits en dernier. Trois écrans qui ne diront jamais des choses différentes
    sur qui relève de quoi.
    """
    from src.core.knowledge.derive import (ADHERENCE_MINIMALE_PCT,
                                           ECART_SIGNIFICATIF_PCT,
                                           RECOUVREMENT_PCT, analyser)
    from src.core.role.modele_acquis import construire

    roles = kb.get_validated_roles()
    habilitations = loader.habilitations
    detenteurs: Dict[str, set] = {}
    droits_par_identite: Dict[str, set] = {}
    if habilitations is not None and not habilitations.empty:
        for droit, groupe in habilitations.groupby(
                DataLoader.COL_RIGHT_ID, observed=True)[DataLoader.COL_USER_ID]:
            detenteurs[str(droit)] = {str(membre) for membre in groupe.unique()}
        droits_par_identite = {
            str(identite): {str(droit) for droit in groupe.unique()}
            for identite, groupe in habilitations.groupby(
                DataLoader.COL_USER_ID, observed=True)[DataLoader.COL_RIGHT_ID]}

    acquis = construire(roles, loader.identities, DataLoader.COL_USER_ID,
                        detenteurs_par_droit=detenteurs)
    membres_par_role = {role.identifiant: set(role.membres) for role in acquis.roles}

    configuration = loader.config or {}
    return analyser(
        roles, membres_par_role, droits_par_identite, kb.get_decisions(),
        effectif_minimal=int(configuration.get("mining_min_users") or 0),
        ecart_significatif=float(configuration.get(
            "revue_ecart_significatif_pct", ECART_SIGNIFICATIF_PCT)),
        recouvrement=float(configuration.get(
            "revue_recouvrement_pct", RECOUVREMENT_PCT)),
        adherence_minimale=float(configuration.get(
            "revue_adherence_minimale_pct", ADHERENCE_MINIMALE_PCT)),
    )


@router.get("/revue")
async def revue_du_modele(
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
) -> Dict[str, Any]:
    """Ce que le catalogue est devenu depuis qu'on l'a validé.

    Un rôle est une règle, et une règle vieillit avec les données : six mois
    après, la population qu'elle désigne a changé, les droits que ses membres
    détiennent aussi. Le produit affichait le catalogue comme au premier jour,
    avec les chiffres du jour de la décision.

    **Cette route ne modifie rien.** Un rôle validé est une décision de
    gouvernance, et il a peut-être déjà été provisionné dans l'IGA du client :
    aucune correction ne s'applique sans un geste humain.
    """
    return await run_in_threadpool(_revue_du_modele, loader, kb)


def _appliquer_la_proposition(loader: DataLoader, kb: KnowledgeBase,
                              empreinte: str, acteur: str) -> Dict[str, Any]:
    """Applique une proposition de la revue, après l'avoir retrouvée.

    Le calcul est refait ici, sur les données du jour : la proposition affichée
    la veille peut ne plus exister. Appliquer sans revérifier reviendrait à
    faire confiance à l'écran, c'est-à-dire à ce que le client envoie.
    """
    from src.core.knowledge.derive import proposition_par_empreinte

    revue = _revue_du_modele(loader, kb)
    proposition = proposition_par_empreinte(revue, empreinte)
    if proposition is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "revue.proposition.introuvable", "params": {}})
    if not proposition.get("applicable"):
        # Retirer un rôle du catalogue ou en fusionner deux fait disparaître un
        # rôle qui a peut-être déjà été provisionné chez le client. Ce geste ne
        # se décide pas depuis un écran d'analyse.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "revue.proposition.geste_manuel",
                    "params": {"type": proposition.get("type", "")}})

    return _executer(kb, proposition, acteur)


def _role_ou_404(kb: KnowledgeBase, role_id: str) -> Dict[str, Any]:
    role = kb.get_role_by_id(role_id)
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "role.not_found", "params": {"identifiant": role_id}})
    return role


def _executer(kb: KnowledgeBase, proposition: Dict[str, Any],
              acteur: str) -> Dict[str, Any]:
    """Applique la proposition retrouvée, et dit ce qui a été fait.

    Rien n'est effacé, quel que soit le type : un rôle qui sort du catalogue y
    reste consultable avec son motif, et un rôle dont les droits changent garde
    son identifiant et sa version précédente.
    """
    releve = str((kb.dernier_releve_de_donnees() or {}).get("recorded_at") or "")
    constat = proposition.get("constat", "")
    type_de_proposition = proposition["type"]
    concernes = {str(droit) for droit in proposition.get("droits") or ()}

    if type_de_proposition in ("restreindre", "elargir"):
        role = _role_ou_404(kb, proposition["role_id"])
        droits = {str(droit) for droit in (role.get("rights") or ())}
        droits = (droits - concernes if type_de_proposition == "restreindre"
                  else droits | concernes)
        modifie = kb.versionner_role(
            proposition["role_id"], {"rights": sorted(droits)},
            constat=constat, auteur=acteur, etat_des_donnees=releve)
        return {"role": modifie, "devalide": "", "proposition": proposition}

    if type_de_proposition == "retirer":
        _role_ou_404(kb, proposition["role_id"])
        sorti = kb.devalider_role(proposition["role_id"], motif="",
                                  constat=constat, auteur=acteur)
        return {"role": sorti, "devalide": proposition["role_id"],
                "proposition": proposition}

    # Fusionner. Le survivant prend les droits des deux, l'autre sort du
    # catalogue. L'ordre compte : si la seconde étape échouait, on aurait un
    # rôle élargi et un rôle encore présent — visible et rattrapable, là où
    # l'ordre inverse ferait disparaître un rôle sans que rien ne le reprenne.
    parametres = proposition.get("parametres") or {}
    survivant = _role_ou_404(kb, str(parametres.get("survivant_id") or ""))
    absorbe = _role_ou_404(kb, str(parametres.get("absorbe_id") or ""))
    droits = {str(droit) for droit in (survivant.get("rights") or ())}
    droits |= {str(droit) for droit in (absorbe.get("rights") or ())}
    modifie = kb.versionner_role(
        survivant["id"], {"rights": sorted(droits)},
        constat=constat, auteur=acteur, etat_des_donnees=releve)
    kb.devalider_role(absorbe["id"], motif="", constat=constat, auteur=acteur)
    return {"role": modifie, "devalide": absorbe["id"], "proposition": proposition}


@router.post("/revue/appliquer")
async def appliquer_une_proposition(
    demande: ApplicationDeProposition,
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
) -> Dict[str, Any]:
    """Le geste humain : appliquer une proposition de la revue.

    C'est la seule route par laquelle un constat peut modifier le catalogue, et
    elle demande une action explicite. Le produit n'applique rien de lui-même,
    quel que soit le degré de certitude d'un constat.

    Le rôle garde son identifiant et gagne une version : l'intégrateur qui a
    déjà reçu la précédente doit pouvoir voir qu'il s'agit du même rôle, sinon
    il en crée un doublon dans l'IGA.
    """
    resultat = await run_in_threadpool(
        _appliquer_la_proposition, loader, kb, demande.empreinte, journal.acteur)
    proposition = resultat["proposition"]
    # Le code du constat et la date de l'état des données sont dans la trace :
    # « pourquoi ce rôle a-t-il changé le 3 mars » doit se répondre sans
    # rouvrir les données.
    releve = str((kb.dernier_releve_de_donnees() or {}).get("recorded_at") or "")
    details = {"constat": proposition.get("constat", ""),
               "proposition": proposition.get("type", ""),
               "droits": sorted(proposition.get("droits") or []),
               "etat_des_donnees": releve}

    # Une fusion fait les deux : un rôle élargi, un rôle sorti du catalogue.
    # Les deux entrées portent le même constat, et se relisent ensemble.
    if resultat["devalide"] and proposition["type"] != "retirer":
        journal.consigner(Action.ROLE_MODIFIE_APRES_CONSTAT, "role",
                          resultat["role"].get("id", ""),
                          {**details, "version": resultat["role"].get("version")})
    if resultat["devalide"]:
        journal.consigner(Action.ROLE_DEVALIDE, "role", resultat["devalide"],
                          details)
    else:
        journal.consigner(Action.ROLE_MODIFIE_APRES_CONSTAT, "role",
                          proposition["role_id"],
                          {**details, "version": resultat["role"].get("version")})

    return {"status": "applied", "role": resultat["role"],
            "devalide": resultat["devalide"],
            "version": resultat["role"].get("version")}


@router.get("/validated-roles/{role_id}")
async def get_validated_role_by_id(
    role_id: str,
    kb: KnowledgeBase = Depends(get_kb)
):
    """
    Récupère un rôle validé par son ID.
    
    Args:
        role_id: ID du rôle à récupérer
    
    Returns:
        Dict du rôle
    
    Raises:
        HTTPException 404: Si le rôle est introuvable
    """
    role = kb.get_role_by_id(role_id)
    if role is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "role.not_found", "params": {"identifiant": role_id}},
        )
    return role


def _index_des_habilitations(loader: DataLoader):
    """Qui détient chaque droit, et ce que détient chaque identité.

    Les deux sens de la même table : le détail d'un rôle et ses accès proches
    les lisent tous deux, et deux constructions finiraient par ne plus
    compter de la même façon.
    """
    habilitations = loader.habilitations
    detenteurs: Dict[str, set] = {}
    droits_par_identite: Dict[str, set] = {}
    if habilitations is not None and not habilitations.empty:
        for droit, groupe in habilitations.groupby(
                DataLoader.COL_RIGHT_ID, observed=True)[DataLoader.COL_USER_ID]:
            detenteurs[str(droit)] = {str(membre) for membre in groupe.unique()}
        droits_par_identite = {
            str(identite): {str(droit) for droit in groupe.unique()}
            for identite, groupe in habilitations.groupby(
                DataLoader.COL_USER_ID, observed=True)[DataLoader.COL_RIGHT_ID]}
    return detenteurs, droits_par_identite


def _membres_du_jour(loader: DataLoader, role: Dict[str, Any],
                     detenteurs: Dict[str, set]) -> set:
    """Les porteurs d'un rôle validé, par le calcul du modèle acquis."""
    from src.core.role.modele_acquis import construire

    acquis = construire([role], loader.identities, DataLoader.COL_USER_ID,
                        detenteurs_par_droit=detenteurs)
    return set(acquis.roles[0].membres) if acquis.roles else set()


def _detail_du_role(loader: DataLoader, kb: KnowledgeBase,
                    role_id: str) -> Dict[str, Any]:
    """Ce que contient un rôle validé, sur les données du jour.

    Les membres et les mesures viennent du **même** calcul que la revue, le
    complément et le graphe. Un écran de détail qui compterait autrement ferait
    dire deux choses différentes au produit sur le même rôle, et c'est le
    défaut que ce projet passe son temps à corriger.

    L'adhérence est rendue **droit par droit** : c'est elle qui dit où se loge
    le sur-octroi. « Ce rôle accorde 340 attributions en trop » ne se corrige
    pas ; « ce droit-ci, quatre membres sur cent le détiennent » se décide.
    """
    from src.core.knowledge.derive import mesurer_aujourdhui

    role = _role_ou_404(kb, role_id)
    detenteurs, droits_par_identite = _index_des_habilitations(loader)
    membres = _membres_du_jour(loader, role, detenteurs)
    ordonnes = sorted(membres)

    droits = sorted(str(droit) for droit in (role.get("rights") or ()))
    detail_droits = []
    for droit in droits:
        porteurs = len([membre for membre in membres
                        if droit in droits_par_identite.get(membre, set())])
        detail_droits.append({
            "droit": droit,
            "detenteurs": porteurs,
            "adherence_pct": round(100.0 * porteurs / len(membres), 1) if membres else 0.0,
        })

    return {
        "role": {cle: valeur for cle, valeur in role.items() if cle != "versions"},
        "mesures": mesurer_aujourdhui(role, membres, droits_par_identite),
        "droits": detail_droits,
        # La liste elle-même n'est plus rendue ici : elle se lit dans le
        # tableau des porteurs, page par page, avec les colonnes du client.
        # Un rôle de onze mille porteurs ne se lit pas d'un bloc, et le rendre
        # entièrement faisait passer plusieurs mégaoctets par une fenêtre qu'on
        # ouvre pour vérifier une intuition.
        "membres_total": len(ordonnes),
        # L'historique sans le contenu des versions : la fenêtre dit qu'il y a
        # eu trois versions et pourquoi, pas ce que chacune contenait.
        "versions": [{"version": entree.get("version"),
                      "remplacee_le": entree.get("remplacee_le"),
                      "auteur": entree.get("auteur"),
                      "constat": entree.get("constat"),
                      "droits": len((entree.get("role") or {}).get("rights") or [])}
                     for entree in (role.get("versions") or [])],
    }


@router.get("/validated-roles/{role_id}/detail")
async def detail_du_role(
    role_id: str,
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
) -> Dict[str, Any]:
    """Le contenu d'un rôle validé : ses droits, ses mesures, son historique.

    Le catalogue n'affichait qu'un nom et deux compteurs. Décider de garder, de
    corriger ou de retirer un rôle demande de voir ce qu'il contient — et le
    faire hors de l'outil, en rouvrant le fichier de la base de connaissance,
    est exactement ce qu'un produit de gouvernance doit éviter.

    Les porteurs ont leur propre route : ils se lisent dans un tableau, avec
    les colonnes du client, une recherche et un tri. Ici ne reste que leur
    nombre.

    Le socle passe par la même route, et rend la même forme : tout ce qui
    affiche un rôle doit pouvoir l'afficher sans savoir d'où il vient.
    """
    if role_id == IDENTIFIANT_SOCLE:
        return await run_in_threadpool(_socle_ou_404, loader, kb)
    return await run_in_threadpool(_detail_du_role, loader, kb, role_id)


def _socle_ou_404(loader: DataLoader, kb: KnowledgeBase) -> Dict[str, Any]:
    """Le socle, ou un 404 si aucune détection n'a été enregistrée.

    Un workspace sans droits socles n'a pas de rôle socle : rendre un rôle
    vide le ferait apparaître au catalogue comme un rôle qui n'accorde rien.
    """
    detail = _detail_du_socle(loader, kb)
    if detail is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "role.not_found",
                    "params": {"identifiant": IDENTIFIANT_SOCLE}})
    return detail


def _detail_du_socle(loader: DataLoader,
                     kb: KnowledgeBase) -> Optional[Dict[str, Any]]:
    """L'adhérence du socle, droit par droit, sur les données du jour."""
    return detail_du_socle(
        loader, kb, DataLoader.COL_USER_ID,
        droits_par_identite(loader.habilitations, DataLoader.COL_USER_ID,
                            DataLoader.COL_RIGHT_ID))


def _porteurs_du_role(loader: DataLoader, role: Dict[str, Any]) -> List[str]:
    """Qui porte ce rôle, aujourd'hui, dans les données chargées.

    Le calcul vit dans `src/core/knowledge/population.py`, avec les deux autres
    relevés dont tout le produit dépend : deux écrans qui compteraient les
    porteurs d'un rôle par deux chemins finiraient par ne pas dire la même
    chose du même rôle.
    """
    return porteurs_calcules(role, loader.identities, DataLoader.COL_USER_ID,
                             loader.habilitations, DataLoader.COL_RIGHT_ID)


@router.get("/validated-roles/{role_id}/porteurs", response_model=LignesRendues)
async def porteurs_du_role(
    role_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=TAILLE_DE_PAGE_MAX),
    search: Optional[str] = Query(None, max_length=200),
    sort_col: Optional[str] = Query(None, max_length=200),
    sort_desc: bool = False,
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
) -> LignesRendues:
    """Les porteurs d'un rôle validé, avec les colonnes du client.

    La fenêtre de détail affichait « 100 porteurs affichés sur 6 269 » suivis
    d'une liste d'identifiants, et un bouton pour en voir cent de plus. Six
    mille deux cent soixante-neuf identifiants ne se lisent pas : on ne cherche
    pas quelqu'un dedans, on ne reconnaît personne, et la seule question qu'on
    se pose devant un rôle — *qui est concerné ?* — n'a pas de réponse.

    Ce sont les mêmes lignes que la fenêtre de validation, par le même chemin :
    recherche sur toutes les colonnes, tri, pagination, et les colonnes du
    fichier du client dont le produit ne connaît aucun nom.

    La pagination est faite **par le serveur** : envoyer la liste complète des
    porteurs au navigateur pour qu'il la découpe ferait passer plusieurs
    mégaoctets par une fenêtre qu'on ouvre pour vérifier une intuition.
    """
    demande = Pagination(page=page, size=size, search=search,
                         sort_col=sort_col, sort_desc=sort_desc)
    source, colonne = REFERENTIELS_DE_LIGNES["identities"]

    if role_id == IDENTIFIANT_SOCLE:
        # Les porteurs du socle sont les identités analysées — toutes. Il n'y
        # a pas de rôle à chercher dans la base : il se dérive de la décision
        # de détection et du périmètre du jour.
        def _porteurs_du_socle() -> LignesRendues:
            _socle_ou_404(loader, kb)
            return restreindre_puis_paginer(
                source(loader), colonne,
                membres_du_socle(loader, kb, DataLoader.COL_USER_ID), demande,
                loader.config.privileges)

        return await run_in_threadpool(_porteurs_du_socle)

    role = _role_ou_404(kb, role_id)

    def _calculer() -> LignesRendues:
        # Les porteurs d'un rôle sont des identités : un compte à privilèges
        # parmi eux ne se lit pas comme un compte nominatif de plus.
        return restreindre_puis_paginer(source(loader), colonne,
                                        _porteurs_du_role(loader, role), demande,
                                        loader.config.privileges)

    return await run_in_threadpool(_calculer)


@router.get("/validated-roles/{role_id}/acces-proches")
async def acces_proches_du_role(
    role_id: str,
    jaccard_min: float = Query(..., ge=0.0, le=1.0),
    limite: int = Query(..., ge=1, le=TAILLE_DE_PAGE_MAX),
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
) -> Dict[str, Any]:
    """Les accès hors du rôle les plus proches de sa population.

    Pour chacun, trois comptes : porteurs du rôle qui le détiennent,
    détenteurs hors du rôle, porteurs du rôle sans lui. C'est la forme
    auditable de « faut-il faire entrer cet accès dans le rôle » : la dernière
    population est ce que l'entrée accorderait en trop, nommée.

    L'indice et la limite viennent de l'appelant, sans valeur par défaut : le
    produit ne décide pas à partir de quand deux populations se ressemblent.
    Le socle n'est jamais proposé — le rôle socle le porte déjà.
    """
    from src.core.knowledge.acces_proches import acces_proches

    role = _role_ou_404(kb, role_id)

    def _calculer() -> Dict[str, Any]:
        detenteurs, droits_par_identite = _index_des_habilitations(loader)
        membres = _membres_du_jour(loader, role, detenteurs)
        resultat = acces_proches(
            membres, [str(droit) for droit in (role.get("rights") or ())],
            detenteurs, droits_par_identite, jaccard_min, limite,
            exclus=kb.get_birth_rights())
        resultat["membres_total"] = len(membres)
        return resultat

    return await run_in_threadpool(_calculer)


@router.get("/validated-roles/{role_id}/acces-proches/population",
            response_model=LignesRendues)
async def population_d_un_acces_proche(
    role_id: str,
    droit: str = Query(..., min_length=1, max_length=500),
    population: str = Query(...),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=TAILLE_DE_PAGE_MAX),
    search: Optional[str] = Query(None, max_length=200),
    sort_col: Optional[str] = Query(None, max_length=200),
    sort_desc: bool = False,
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
) -> LignesRendues:
    """L'une des trois populations d'un couple (rôle, accès), nommée.

    Mêmes lignes que les porteurs du rôle, par le même chemin : les colonnes
    du client, la recherche, le tri, la pagination côté serveur. Un compte
    qu'on ne peut pas déplier en noms ne se vérifie pas.
    """
    from src.core.knowledge.acces_proches import POPULATIONS
    from src.core.knowledge.acces_proches import population as nommer

    if population not in POPULATIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "role.proches.population_inconnue",
                    "params": {"population": population}})
    role = _role_ou_404(kb, role_id)
    demande = Pagination(page=page, size=size, search=search,
                         sort_col=sort_col, sort_desc=sort_desc)
    source, colonne = REFERENTIELS_DE_LIGNES["identities"]

    def _calculer() -> LignesRendues:
        detenteurs, _ = _index_des_habilitations(loader)
        membres = _membres_du_jour(loader, role, detenteurs)
        return restreindre_puis_paginer(
            source(loader), colonne,
            sorted(nommer(membres, droit, detenteurs, population)), demande,
            loader.config.privileges)

    return await run_in_threadpool(_calculer)


@router.post("/validated-roles/{role_id}/ancrer")
async def ancrer_le_role(
    role_id: str,
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
) -> Dict[str, Any]:
    """Retient les mesures du jour comme point de comparaison du rôle.

    Un rôle composé à la main n'est passé par aucune validation de candidat :
    aucun chiffre n'a été consigné à sa création, et la revue ne pouvait donc
    rien dire de lui. Elle l'annonçait — « ce rôle n'a pas de point de
    comparaison » — et s'arrêtait là. C'était une impasse : le produit mesurait
    le rôle chaque jour sans jamais pouvoir dire s'il avait bougé.

    Ce geste pose la référence manquante. Il ne modifie pas le rôle, il ne
    juge rien : il écrit les chiffres d'aujourd'hui pour que ceux de demain
    puissent s'y comparer. Le 3 mars devient le jour où quelqu'un a dit « à
    partir de maintenant, c'est cela, le rôle ».

    **Un rôle qui a déjà une référence est refusé.** Réancrer effacerait
    précisément l'écart que la revue a mis au jour : ce serait un bouton pour
    faire disparaître un constat, et c'est le contraire de ce que fait ce
    produit. Assumer une dérive et repartir d'une nouvelle base est une autre
    décision, qui devra dire ce qu'elle assume.
    """
    if role_id == IDENTIFIANT_SOCLE:
        # Le socle n'a pas de référence à poser : il se dérive de la décision
        # de détection, et c'est elle qui le fait bouger.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "role.anchor.not_applicable", "params": {}})

    role = _role_ou_404(kb, role_id)
    deja = {str(decision.get("role_id")): decision
            for decision in kb.get_decisions()}.get(role_id) or {}
    if deja.get("indicateurs"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "role.anchor.already_set", "params": {}})

    detail = await run_in_threadpool(_detail_du_role, loader, kb, role_id)
    mesures = detail["mesures"]
    await run_in_threadpool(kb.enregistrer_decision, role_id, "validee", mesures)
    journal.consigner(Action.ROLE_ANCRE, "role", role_id,
                      {"nom": str(role.get("name") or ""), **mesures})
    return {"status": "anchored", "role_id": role_id, "mesures": mesures}


@router.post("/validated-roles/{role_id}/renommer")
async def renommer_le_role(
    role_id: str,
    demande: RenommageDeRole,
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
) -> Dict[str, Any]:
    """Change le nom et la description d'un rôle validé, en versionnant.

    Le nom fait partie de ce que l'intégrateur a reçu. Le changer sans le dire
    lui fait croire à un rôle neuf, et il en crée un doublon dans l'IGA — le
    versionnement existe pour ça.
    """
    _role_ou_404(kb, role_id)
    modifie = await run_in_threadpool(
        kb.versionner_role, role_id,
        {"name": demande.name, "description": demande.description},
        "", journal.acteur, "")
    journal.consigner(Action.ROLE_MODIFIE, "role", role_id,
                      {"champs": ["description", "name"],
                       "version": modifie.get("version")})
    return {"status": "renamed", "role": modifie,
            "version": modifie.get("version")}


@router.post("/validated-roles/{role_id}/devalider")
async def devalider_le_role(
    role_id: str,
    demande: DevalidationDeRole,
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
) -> Dict[str, Any]:
    """Sort un rôle du catalogue, sans effacer qu'il y a été.

    Jusqu'ici, revenir sur une validation demandait d'éditer à la main le
    fichier de la base de connaissance — c'est-à-dire de sortir de l'outil pour
    défaire une décision de gouvernance, sans trace et sans motif.

    Le rôle reste consultable avec son motif et son auteur, et le candidat dont
    il venait redevient à décider.
    """
    _role_ou_404(kb, role_id)
    sorti = await run_in_threadpool(kb.devalider_role, role_id, demande.motif,
                                    "", journal.acteur)
    journal.consigner(Action.ROLE_DEVALIDE, "role", role_id,
                      {"nom": sorti.get("name", ""), "motif": demande.motif,
                       "droits": len(sorti.get("rights") or [])})
    return {"status": "unvalidated", "role_id": role_id}


@router.get("/devalidated-roles")
async def roles_devalides(kb: KnowledgeBase = Depends(get_kb)) -> Dict[str, Any]:
    """Les rôles sortis du catalogue, avec leur motif.

    Dévalider n'est pas supprimer : six mois plus tard, quelqu'un demandera ce
    que contenait ce rôle et pourquoi il n'y est plus.
    """
    sortis = kb.roles_devalides()
    return {"roles": sortis, "count": len(sortis)}


@router.post("/validate-role")
async def validate_role(
    role: RoleValidation,
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
):
    """Valide et enregistre un rôle dans la KB."""
    role_dict = role.dict()
    role_dict.pop("indicateurs", None)
    kb.add_validated_role(role_dict)
    if role.indicateurs is not None:
        # Sur cette route, le rôle est enregistré sous l'identifiant fourni :
        # c'est celui du candidat. Le consigner rend la décision rattachable au
        # candidat, comme sur les routes qui créent un identifiant neuf.
        kb.enregistrer_decision(role.id, "validee", role.indicateurs.dict(),
                                candidate_id=role.id)
    # Valider un rôle, c'est ouvrir des accès : la décision, son auteur et son
    # périmètre doivent rester opposables des années plus tard.
    journal.consigner(
        Action.ROLE_VALIDE, "role", role.id,
        {"nom": role_dict.get("name", ""),
         "droits": len(role_dict.get("rights") or []),
         "utilisateurs": len(role_dict.get("users") or [])},
    )
    return {"status": "validated", "role_id": role.id}


@router.put("/validated-roles/{role_id}")
async def update_validated_role(
    role_id: str,
    updates: Dict[str, Any],
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
):
    """Met à jour un rôle validé."""
    try:
        kb.update_validated_role(role_id, updates)
        journal.consigner(
            Action.ROLE_MODIFIE, "role", role_id,
            {"champs": sorted(updates.keys())},
        )
        return {"status": "updated"}
    except ValueError:
        # Le message de l'exception est en français, écrit dans le cœur : il
        # ne doit pas ressortir tel quel dans une réponse d'API.
        raise HTTPException(
            status_code=404,
            detail={"code": "role.not_found", "params": {"identifiant": role_id}})


@router.delete("/validated-roles/{role_id}")
async def delete_validated_role(
    role_id: str,
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
):
    """Supprime un rôle validé de la KB."""
    kb.delete_validated_role(role_id)
    journal.consigner(Action.ROLE_SUPPRIME, "role", role_id)
    return {"status": "deleted"}


# === REJECTED ROLES ===

@router.get("/rejected-roles")
async def get_rejected_roles(kb: KnowledgeBase = Depends(get_kb)):
    """Récupère la liste des rôles rejetés."""
    return {"rejected_roles": kb.get_rejected_roles()}


@router.get("/rejected-roles/{role_id}/check")
async def check_role_rejected(
    role_id: str,
    kb: KnowledgeBase = Depends(get_kb)
):
    """
    Vérifie si un rôle est dans la blacklist.
    
    Args:
        role_id: ID du rôle à vérifier
    
    Returns:
        Dict avec is_rejected boolean
    """
    return {
        "role_id": role_id,
        "is_rejected": kb.is_role_rejected(role_id)
    }


@router.post("/reject-role")
async def reject_role(
    rejection: RoleRejection,
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
):
    """Ajoute un rôle à la blacklist du workspace actif.

    Le rôle est identifié par l'empreinte de ses droits : le renommer ne le fera
    pas réapparaître dans un mining ultérieur.
    """
    kb.reject_role(rejection.role_id, rejection.reason)
    # Un rejet sans indicateurs n'est pas une décision d'un analyste sur un
    # candidat : c'est l'écartement automatique du rôle d'origine quand
    # quelqu'un en modifie un. Le confondre avec un refus fausserait
    # l'historique dans le sens le plus trompeur.
    if rejection.indicateurs is not None:
        kb.enregistrer_decision(rejection.role_id, "rejetee",
                                rejection.indicateurs.dict(),
                                motif=rejection.reason or "")
    logger.info(
        "Rôle %s refusé (%d rôles refusés au total)",
        rejection.role_id, len(kb.get_rejected_roles()),
    )
    journal.consigner(
        Action.ROLE_REJETE, "role", rejection.role_id,
        {"motif": rejection.reason or ""},
    )

    return {"status": "rejected", "role_id": rejection.role_id}


@router.delete("/rejected-roles/{role_id}")
async def unreject_role(
    role_id: str,
    kb: KnowledgeBase = Depends(get_kb)
):
    """
    Retire un rôle de la blacklist (le rendre à nouveau proposable).
    
    Args:
        role_id: ID du rôle à réhabiliter
    
    Returns:
        Status de l'opération
    """
    kb.unreject_role(role_id)
    return {"status": "unrejected", "role_id": role_id}


# === EXCLUDED USERS ===

@router.get("/excluded-users")
async def get_excluded_users(kb: KnowledgeBase = Depends(get_kb)):
    """Récupère la liste des utilisateurs exclus."""
    return {"excluded_users": kb.get_excluded_users()}


@router.post("/exclude-user")
async def exclude_user(
    exclusion: UserExclusion,
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
):
    """Exclut un utilisateur du mining."""
    kb.exclude_user(exclusion.user_id, exclusion.reason)
    journal.consigner(
        Action.PERIMETRE_MODIFIE, "perimetre", "excluded_users",
        {"ajoutees": 1, "motif": exclusion.reason or ""},
    )
    return {"status": "excluded"}


@router.post("/exclude-users")
async def exclude_users(
    exclusion: schemas.UsersExclusion,
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
):
    """Écarte plusieurs identités du périmètre, en une seule écriture.

    Le détail par groupe en désigne parfois quelques centaines d'un coup. Une
    par une, chacune relirait et réécrirait le document sous verrou.

    La décision est tracée : écarter une population déplace la couverture, le
    sur-octroi et les effectifs de toutes les analyses suivantes, et deux
    minings aux résultats différents sur les mêmes données resteraient
    autrement inexplicables.
    """
    ajoutees = kb.exclude_users(exclusion.user_ids, exclusion.reason or "")
    if ajoutees:
        journal.consigner(
            Action.PERIMETRE_MODIFIE, "perimetre", "excluded_users",
            {"ajoutees": len(ajoutees), "motif": exclusion.reason or ""},
        )
    return {"status": "excluded", "added": ajoutees,
            "excluded_users": kb.get_excluded_users()}


@router.delete("/excluded-users/{user_id}")
async def remove_excluded_user(
    user_id: str,
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
):
    """Réintègre un utilisateur précédemment exclu.

    Tracée au même titre que l'exclusion : une décision de gouvernance qu'on
    défait est une décision, et l'historique doit porter les deux sens.
    """
    kb.unexclude_user(user_id)
    journal.consigner(Action.PERIMETRE_MODIFIE, "perimetre", "excluded_users",
                      {"reintegree": user_id})
    return {"status": "removed"}


# === RÈGLES DE PÉRIMÈTRE ===


@router.get("/perimeter-rules")
async def get_perimeter_rules(
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
):
    """Les règles de périmètre, et l'effet qu'elles ont sur ce référentiel-ci.

    L'écran a besoin des deux : les règles pour les modifier, et leur effet
    pour que personne ne pose un filtre sans voir combien d'identités il
    écarte. Les valeurs observées de chaque colonne d'identité sont rendues
    avec — le produit ne présuppose aucune colonne, il ne peut donc pas
    présupposer non plus les valeurs qu'elle prend.
    """
    from src.core.knowledge.perimetre import rapport_perimetre

    identites = loader.identities
    colonnes = {}
    if not identites.empty:
        for colonne in identites.columns:
            if colonne == DataLoader.COL_USER_ID:
                continue
            valeurs = identites[colonne].dropna().astype(str).str.strip()
            valeurs = sorted({valeur for valeur in valeurs if valeur})
            # Une colonne à quelques centaines de valeurs distinctes n'est pas
            # un critère de périmètre, c'est un identifiant : la proposer
            # noierait celles qui en sont un.
            if 0 < len(valeurs) <= VALEURS_PROPOSEES_MAX:
                colonnes[colonne] = valeurs

    return {
        "rules": kb.get_perimeter_rules(),
        "attributes": colonnes,
        # La borne est rendue avec la liste : l'écran doit pouvoir l'expliquer
        # sans la connaître, et les deux ne peuvent pas diverger.
        "values_max": VALEURS_PROPOSEES_MAX,
        "perimeter": rapport_perimetre(loader, kb.get_excluded_users(),
                                       kb.regles_perimetre()),
    }


@router.put("/perimeter-rules")
async def set_perimeter_rules(
    demande: schemas.PerimeterRules,
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
):
    """Remplace les règles de périmètre, et rend l'effet du nouveau jeu.

    Un remplacement et non un ajout : l'écran envoie l'état complet, sans quoi
    il n'y aurait aucun moyen de retirer une règle.
    """
    from src.core.knowledge.perimetre import rapport_perimetre

    try:
        kb.set_perimeter_rules([regle.model_dump() for regle in demande.rules])
        journal.consigner(
            Action.PERIMETRE_MODIFIE, "perimetre", "rules",
            {"regles": len(demande.rules)},
        )
    except ValueError as erreur:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "perimeter.invalid_rule",
                    "params": {"reason": str(erreur)}},
        )
    return {"rules": kb.get_perimeter_rules(),
            "perimeter": rapport_perimetre(loader, kb.get_excluded_users(),
                                           kb.regles_perimetre())}


# === MINING HISTORY ===

@router.get("/mining-history")
async def get_mining_history(
    limit: int = 10,
    kb: KnowledgeBase = Depends(get_kb)
):
    """Récupère l'historique des runs de mining."""
    return {"history": kb.get_mining_history(limit)}


@router.post("/mining-history")
async def add_mining_run(
    run_info: Dict[str, Any],
    kb: KnowledgeBase = Depends(get_kb)
):
    """Enregistre un run de mining."""
    kb.add_mining_run(run_info)
    return {"status": "recorded"}


# === BACKUP & RESTORE ===

@router.post("/backup")
async def create_backup(kb: KnowledgeBase = Depends(get_kb)):
    """Crée une sauvegarde de la KB."""
    backup_path = f"backups/kb_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    kb.export_backup(backup_path)
    return {"status": "backed_up", "path": backup_path}


@router.post("/restore")
async def restore_backup(
    data: BackupRestore,
    kb: KnowledgeBase = Depends(get_kb)
):
    """
    Restaure la KB depuis un fichier de backup.
    
    Args:
        backup_path: Chemin vers le fichier de backup
    
    Returns:
        Status de la restauration
    
    Raises:
        HTTPException 404: Si le backup est introuvable
        HTTPException 400: Si le backup est invalide
    """
    try:
        kb.import_backup(data.backup_path)
        return {"status": "restored", "backup_path": data.backup_path,
                "code": "kb.restored"}
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"code": "kb.backup_not_found",
                    "params": {"chemin": data.backup_path}})
    except (json.JSONDecodeError, ValueError) as erreur:
        # Le détail reste au journal : il cite un chemin du serveur.
        logger.error("Sauvegarde invalide (%s) : %s", data.backup_path, erreur)
        raise HTTPException(status_code=400, detail={"code": "kb.backup_invalid"})


@router.delete("/clear-all")
async def clear_all_kb(
    confirm: bool = False,
    kb: KnowledgeBase = Depends(get_kb)
):
    """
    ⚠️ DANGEREUX : Efface TOUTES les données de la KB.
    
    Query params:
        confirm: Doit être True pour confirmer l'effacement
    
    Returns:
        Status de l'opération
    
    Raises:
        HTTPException 400: Si confirm n'est pas True
    """
    if not confirm:
        raise HTTPException(
            status_code=400, detail={"code": "kb.clear_requires_confirmation"})
    
    try:
        kb.clear_all(confirm=True)
        return {"status": "cleared", "code": "kb.cleared"}
    except Exception as erreur:
        logger.error("Effacement de la base impossible : %s", erreur)
        raise HTTPException(status_code=500, detail={"code": "kb.clear_failed"})