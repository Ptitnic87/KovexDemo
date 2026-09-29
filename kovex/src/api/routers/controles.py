# Fichier : src/api/routers/controles.py
"""Décrire les contrôles compensatoires, et consigner leurs exécutions.

Deux gestes, et leur asymétrie dit la conception.

Le **catalogue** se remplace en bloc, comme les règles de séparation : l'écran
rend l'état complet, et un ajout laisserait sans moyen de retirer un contrôle.

Une **exécution** s'ajoute et ne se retire jamais. C'est une piste, pas un
état : « le contrôle a été fait le 3 mars, par elle, relu par lui, conforme,
preuve au ticket 4412 » reste vrai quand le contrôle suivant échoue.

Deux champs ne sont jamais acceptés de l'appelant : qui consigne et quand. Sur
l'objet qui rend une exception défendable, ce sont ceux qu'il ne faut pas
prendre de l'extérieur.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from src.api.dependencies import get_kb
from src.api.journal import Journal, get_journal
from src.core.audit.piste_audit import Action
from src.core.knowledge.controles import (PREUVE_MAX, RESULTATS, TEXTE_MAX,
                                          ControleInvalide, etat_du_controle)
from src.core.knowledge.knowledge_base import KnowledgeBase
from src.core.security.auth import User, require_permission_or_dev

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/controles", tags=["Contrôles compensatoires"])

#: Décrire un contrôle et consigner son exécution sont des décisions de
#: gouvernance, au même titre qu'accorder une dérogation.
PERMISSION = "mining"


class ControleEnvoye(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=64)
    libelle: str = Field(..., min_length=1, max_length=TEXTE_MAX)
    executant: str = Field(..., min_length=1, max_length=TEXTE_MAX)
    relecteur: str = Field(..., min_length=1, max_length=TEXTE_MAX)
    age_max_jours: int = Field(..., ge=1)
    actif: bool = True


class ControlesEnvoyes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    controles: List[ControleEnvoye] = Field(default_factory=list)


class ExecutionEnvoyee(BaseModel):
    """Ce que l'écran envoie pour consigner une exécution.

    Ni qui consigne, ni quand : ils viennent du serveur.
    """

    model_config = ConfigDict(extra="forbid")

    execute_le: str = Field(..., min_length=10, max_length=10)
    executant: str = Field(..., min_length=1, max_length=TEXTE_MAX)
    relecteur: str = Field(default="", max_length=TEXTE_MAX)
    resultat: str = Field(..., min_length=1, max_length=32)
    preuve: str = Field(..., min_length=1, max_length=PREUVE_MAX)


def _aujourdhui():
    """Le jour, emprunté aux dérogations : les deux se jugent sur le même."""
    from src.api.routers.derogations import _aujourdhui as jour

    return jour()


def _refus(erreur: ControleInvalide) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": "controle.invalide", "params": {"motif": str(erreur)}})


def _catalogue(kb: KnowledgeBase) -> Dict[str, Any]:
    executions = kb.executions_de_controle()
    aujourdhui = _aujourdhui()
    return {"controles": [etat_du_controle(controle, executions, aujourdhui)
                          for controle in kb.controles().values()],
            "resultats": list(RESULTATS),
            "aujourdhui": aujourdhui.isoformat()}


@router.get("")
async def lister(
    kb: KnowledgeBase = Depends(get_kb),
    user: User = Depends(require_permission_or_dev(PERMISSION)),
) -> Dict[str, Any]:
    """Le catalogue, chaque contrôle avec sa dernière exécution et ses raisons.

    Les raisons sont celles qu'une dérogation citant ce contrôle hériterait :
    l'écran les montre ici pour qu'on les corrige avant qu'elles ne fassent
    revenir des conflits.
    """
    return _catalogue(kb)


@router.put("")
async def enregistrer(
    envoi: ControlesEnvoyes,
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
    user: User = Depends(require_permission_or_dev(PERMISSION)),
) -> Dict[str, Any]:
    bruts = [controle.model_dump() for controle in envoi.controles]
    try:
        kb.enregistrer_les_controles(bruts)
    except ControleInvalide as erreur:
        raise _refus(erreur)
    journal.consigner(Action.CONTROLES_MODIFIES, "controle", "catalogue",
                      {"controles": len(bruts)})
    return _catalogue(kb)


@router.get("/{identifiant}/executions")
async def executions(
    identifiant: str,
    kb: KnowledgeBase = Depends(get_kb),
    user: User = Depends(require_permission_or_dev(PERMISSION)),
) -> Dict[str, Any]:
    """Toutes les exécutions d'un contrôle, la plus récente d'abord."""
    if identifiant not in kb.controles():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "controle.inconnu", "params": {"controle": identifiant}})
    siennes = [une.en_dict() for une in kb.executions_de_controle()
               if une.controle == identifiant]
    siennes.sort(key=lambda une: (une["execute_le"], une["consignee_le"]),
                 reverse=True)
    return {"executions": siennes}


@router.post("/{identifiant}/executions")
async def consigner(
    identifiant: str,
    envoi: ExecutionEnvoyee,
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
    user: User = Depends(require_permission_or_dev(PERMISSION)),
) -> Dict[str, Any]:
    """Consigne une exécution, datée du jour et signée de celui qui la consigne."""
    brute = {**envoi.model_dump(), "controle": identifiant,
             "consignee_par": getattr(user, "username", "") or "",
             "consignee_le": _aujourdhui().isoformat()}
    try:
        consignee = kb.consigner_une_execution(brute)
    except ControleInvalide as erreur:
        raise _refus(erreur)
    journal.consigner(Action.CONTROLE_EXECUTE, "controle", identifiant,
                      {"resultat": consignee["resultat"],
                       "execute_le": consignee["execute_le"]})
    return consignee
