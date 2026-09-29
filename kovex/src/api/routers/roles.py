# src/api/routers/roles.py
"""
Routeur UNIFIÉ pour la gestion des rôles (Applicatifs ET Métiers)
Utilise la Knowledge Base comme source unique de vérité
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from src.core.knowledge.knowledge_base import KnowledgeBase
from src.core.data.loader import DataLoader
from src.api.dependencies import get_kb, get_data_loader
from src.api.journal import Journal, get_journal
from src.core.audit import Action
from src.api import schemas
from src.core.knowledge.socle import (IDENTIFIANT_SOCLE, TYPE_SOCLE,
                                      membres_du_socle, role_socle,
                                      socle_du_workspace)
from src.core.role.identite import TYPES_DE_ROLE, identifiant_applicatif

router = APIRouter(prefix="/roles", tags=["Roles Management"])


# ========== MODELS ==========

class RoleCreate(BaseModel):
    """Modèle pour la création de rôle (Applicatif OU Métier).

    Volontairement sans champ `users` : un rôle est une règle, pas une liste
    figée. Les membres d'un rôle métier se déduisent de `source_attributes`,
    ceux d'un rôle applicatif des identités détenant l'intégralité de ses
    droits — c'est déjà la définition retenue pour `user_count`. Une liste
    stockée à la validation deviendrait fausse au premier mouvement de
    l'annuaire.
    """
    name: str
    description: str = ""
    role_type: str  # "APPLICATIF" ou "METIER"
    rights: List[str] = []
    sub_role_ids: List[str] = []
    additional_rights: List[str] = []
    # Champs optionnels pour rôles métier
    rh_rule: Optional[str] = None
    source_attributes: Optional[Dict[str, Any]] = None
    #: Candidat du mining dont ce rôle est issu, s'il en vient. Il permet de
    #: savoir ce qui reste à décider : une validation crée un rôle dont
    #: l'identifiant est neuf, et rien ne le reliait plus au candidat.
    candidate_id: Optional[str] = None
    #: Chiffres affichés au moment de la décision. Présents quand le rôle vient
    #: d'un candidat du mining, absents quand il est composé à la main : c'est
    #: ce qui distingue une décision, qui est un exemple, d'une création, qui
    #: n'en est pas un.
    indicateurs: Optional[schemas.IndicateursDeDecision] = None


def consigner_la_creation(journal: Journal, role: Dict[str, Any],
                          candidat: Optional[str]) -> None:
    """Trace l'entrée d'un rôle au catalogue.

    C'est la route qu'emprunte l'écran pour **toutes** les validations — un
    candidat du mining accepté, modifié, ou un rôle composé à la main. Elle ne
    laissait aucune trace : la piste d'audit disait qui avait refusé un rôle,
    jamais qui en avait ouvert un, alors que c'est la décision qui ouvre des
    accès. Un rôle issu d'un candidat est une validation (le candidat est
    nommé) ; un rôle bâti à la main est une création.
    """
    parametres = {
        "nom": role.get("name", ""),
        "type": role.get("role_type", ""),
        "droits": len(role.get("rights") or []),
        "utilisateurs": role.get("user_count") or 0,
    }
    if candidat:
        parametres["candidat"] = candidat
        journal.consigner(Action.ROLE_VALIDE, "role", role["id"], parametres)
    else:
        journal.consigner(Action.ROLE_CREE, "role", role["id"], parametres)


def _droits_des_sous_roles(roles_existants, identifiants):
    """Droits apportés par les sous-rôles désignés, et ceux qui n'existent pas.

    Un identifiant inconnu doit être refusé plutôt qu'ignoré : le rôle produit
    ne porterait pas les droits que l'utilisateur croit y avoir mis.
    """
    par_identifiant = {r.get("id"): r for r in roles_existants}
    droits, inconnus = set(), []
    for identifiant in identifiants or ():
        sous_role = par_identifiant.get(identifiant)
        if sous_role is None:
            inconnus.append(str(identifiant))
            continue
        droits.update(sous_role.get("rights") or ())
    return droits, inconnus


# ========== ENDPOINTS ==========

@router.post("/create")
async def create_role(
    role_data: RoleCreate,
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
):
    """
    Crée un rôle (Applicatif ou Métier) et le persiste dans la KB.
    
    Endpoint UNIFIÉ qui remplace:
    - /business/create (ancien)
    - /roles (ancien)
    - Corrige le 404 lors de la création depuis Mining Applicatif
    
    Args:
        role_data: Données du rôle à créer
    
    Returns:
        Dict avec status, role_id, et infos du rôle créé
    
    Raises:
        HTTPException 400: Si un rôle avec ce nom existe déjà
    """
    
    nom = role_data.name.strip()
    if not nom:
        raise HTTPException(
            status_code=422, detail={"code": "role.name_and_rights_required"}
        )

    if role_data.role_type not in TYPES_DE_ROLE:
        raise HTTPException(
            status_code=422,
            detail={"code": "role.unknown_type", "params": {"type": role_data.role_type}},
        )

    existing_roles = kb.get_validated_roles()
    for r in existing_roles:
        if str(r.get("name") or "").lower() == nom.lower():
            raise HTTPException(
                status_code=409,
                detail={"code": "role.name_already_used", "params": {"name": nom}},
            )

    # Les sous-rôles apportent leurs droits. Sans cette résolution, un rôle
    # composé uniquement de sous-rôles — ce que l'interface envoie, avec
    # `rights: []` et le commentaire « les droits seront calculés par le
    # backend » — était enregistré sans aucun droit et avec un effectif nul.
    droits_des_sous_roles, inconnus = _droits_des_sous_roles(
        existing_roles, role_data.sub_role_ids
    )
    if inconnus:
        raise HTTPException(
            status_code=422,
            detail={"code": "role.unknown_sub_roles", "params": {"roles": ", ".join(inconnus)}},
        )

    all_rights = sorted(
        set(role_data.rights) | set(role_data.additional_rights) | droits_des_sous_roles
    )
    if not all_rights:
        raise HTTPException(
            status_code=422, detail={"code": "role.name_and_rights_required"}
        )

    user_count = calculate_user_count(loader, all_rights)

    # L'identité d'un rôle est l'empreinte de ses droits triés : renommer un
    # rôle ne doit pas le faire réapparaître après un rejet, et deux rôles de
    # droits identiques ne doivent pas coexister sous deux identifiants.
    role_id = identifiant_applicatif(all_rights, f"role_{role_data.role_type.lower()}")

    if kb.is_role_rejected(role_id):
        raise HTTPException(
            status_code=409, detail={"code": "role.previously_rejected"}
        )

    role = {
        "id": role_id,
        "name": nom,
        "description": role_data.description,
        "role_type": role_data.role_type,
        "rights": all_rights,
        "sub_roles": role_data.sub_role_ids,
        "additional_rights": role_data.additional_rights,
        "user_count": user_count,
        "created_at": datetime.now().isoformat()
    }
    
    # Ajouter champs spécifiques métier si présents
    if role_data.role_type == "METIER":
        if role_data.rh_rule:
            role["rh_rule"] = role_data.rh_rule
        if role_data.source_attributes:
            role["source_attributes"] = role_data.source_attributes
    
    # Persister dans la KB
    kb.add_validated_role(role)
    if role_data.indicateurs is not None:
        kb.enregistrer_decision(role_id, "validee", role_data.indicateurs.dict(),
                                candidate_id=role_data.candidate_id or "")
    consigner_la_creation(journal, role, role_data.candidate_id)

    return {
        "status": "success",
        "code": "role.created",
        "params": {"type": role_data.role_type, "nom": role_data.name},
        "role": role,
    }


@router.get("/")
async def list_roles(
    role_type: Optional[str] = None,
    kb: KnowledgeBase = Depends(get_kb),
    loader: DataLoader = Depends(get_data_loader),
):
    """
    Liste les rôles du catalogue : le socle, puis les rôles validés.

    Le socle vient en tête parce que c'est ce que tout le monde reçoit en
    arrivant : les rôles métiers et applicatifs s'ajoutent par-dessus. Il ne
    figurait nulle part — ni ici, ni dans l'export — alors que le produit
    savait le détecter et l'enregistrer depuis le premier jour. L'intégrateur
    recevait donc un modèle amputé de la seule chose commune à tous.

    Il est **dérivé**, jamais stocké : il se recalcule depuis la décision de
    détection et le périmètre du jour. Un rôle validé enregistré à côté
    deviendrait faux dès la détection suivante.

    Query params:
        role_type: Filtrer par "APPLICATIF", "METIER", "SOCLE", ou None pour
            tous.

    Returns:
        Liste des rôles avec leurs détails
    """
    roles = [] if role_type == TYPE_SOCLE else kb.get_validated_roles(role_type=role_type)

    if role_type in (None, TYPE_SOCLE):
        socle = socle_du_workspace(kb)
        if socle.existe:
            membres = membres_du_socle(loader, kb, DataLoader.COL_USER_ID)
            roles = [role_socle(socle, membres)] + list(roles)

    return {
        "roles": roles,
        "total": len(roles),
        "filter_applied": role_type
    }


@router.get("/{role_id}")
async def get_role(
    role_id: str,
    kb: KnowledgeBase = Depends(get_kb)
):
    """
    Récupère un rôle spécifique par son ID.
    
    Args:
        role_id: ID du rôle
    
    Returns:
        Détails complets du rôle
    
    Raises:
        HTTPException 404: Si le rôle n'existe pas
    """
    role = kb.get_role_by_id(role_id)
    
    if role is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "role.not_found", "params": {"identifiant": role_id}},
        )
    
    return role


@router.put("/{role_id}")
async def update_role(
    role_id: str,
    updates: Dict[str, Any],
    kb: KnowledgeBase = Depends(get_kb)
):
    """
    Met à jour un rôle existant.
    
    Args:
        role_id: ID du rôle à mettre à jour
        updates: Dictionnaire des champs à modifier
    
    Returns:
        Status de la mise à jour
    
    Raises:
        HTTPException 404: Si le rôle n'existe pas
    """
    try:
        kb.update_validated_role(role_id, updates)
        return {
            "status": "updated",
            "role_id": role_id,
            "updated_fields": list(updates.keys())
        }
    except ValueError:
        # Le message de l'exception est en français, écrit dans le cœur : il
        # ne doit pas ressortir tel quel dans une réponse d'API.
        raise HTTPException(
            status_code=404,
            detail={"code": "role.not_found", "params": {"identifiant": role_id}})


@router.delete("/{role_id}")
async def delete_role(
    role_id: str,
    kb: KnowledgeBase = Depends(get_kb)
):
    """
    Supprime un rôle de la KB.
    
    Args:
        role_id: ID du rôle à supprimer
    
    Returns:
        Status de la suppression
    """
    # Vérifier que le rôle existe
    role = kb.get_role_by_id(role_id)
    if role is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "role.not_found", "params": {"identifiant": role_id}},
        )
    
    kb.delete_validated_role(role_id)
    
    return {
        "status": "deleted",
        "role_id": role_id,
        "role_name": role.get("name")
    }


@router.get("/stats/summary")
async def get_roles_stats(kb: KnowledgeBase = Depends(get_kb)):
    """
    Statistiques sur les rôles.
    
    Returns:
        Compteurs par type, total, etc.
    """
    all_roles = kb.get_validated_roles()
    
    app_roles = [r for r in all_roles if r.get("role_type") == "APPLICATIF"]
    business_roles = [r for r in all_roles if r.get("role_type") == "METIER"]
    
    total_rights = sum(len(r.get("rights", [])) for r in all_roles)
    total_users_covered = sum(r.get("user_count", 0) for r in all_roles)
    
    return {
        "total_roles": len(all_roles),
        "applicatif_roles": len(app_roles),
        "metier_roles": len(business_roles),
        "total_rights_in_roles": total_rights,
        "total_users_covered": total_users_covered,
        "avg_rights_per_role": round(total_rights / len(all_roles), 2) if all_roles else 0
    }


# ========== HELPER FUNCTIONS ==========

def calculate_user_count(loader: DataLoader, rights: List[str]) -> int:
    """
    Calcule le nombre d'utilisateurs qui possèdent TOUS les droits spécifiés.
    
    Args:
        loader: DataLoader avec les habilitations
        rights: Liste des droits requis
    
    Returns:
        Nombre d'utilisateurs impactés
    """
    if loader.habilitations is None or loader.habilitations.empty:
        return 0
    
    if not rights:
        return 0
    
    try:
        # Pour chaque utilisateur, vérifier s'il a tous les droits
        habs = loader.habilitations
        user_rights = habs.groupby('ID_utilisateur')['ID_droit'].apply(set).to_dict()
        
        rights_set = set(rights)
        matching_users = sum(1 for user_rights_set in user_rights.values() 
                           if rights_set.issubset(user_rights_set))
        
        return matching_users
        
    except Exception as e:
        logger.warning("Calcul de l'effectif du rôle impossible : %s", e)
        return 0