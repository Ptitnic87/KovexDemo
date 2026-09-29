# Fichier : src/api/routers/apprentissage.py
"""Ce que le workspace apprend de ses décisions, vu de l'API.

Quatre routes : l'état de l'apprentissage et sa mesure à rebours ; le score
d'un lot de candidats ; retirer une décision de l'apprentissage ou l'y
remettre ; tout oublier. Le modèle n'est conservé nulle part — il se
reconstruit à chaque lecture depuis l'historique des décisions, qui est ce qui
se lit, se gouverne et se désapprend.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Union

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from src.api.dependencies import get_data_loader, get_kb
from src.api.journal import Journal, get_journal
from src.core.audit.piste_audit import Action
from src.core.data.loader import DataLoader
from src.core.knowledge.apprentissage import (Reglages, apprendre, ressemblance,
                                              vecteur)
from src.core.knowledge.knowledge_base import KnowledgeBase
from src.core.security.auth import User, require_permission_or_dev

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/apprentissage", tags=["Apprentissage"])

#: Lire l'apprentissage et scorer des candidats : un geste d'analyste.
LECTURE = "mining"
#: Désapprendre change ce que le produit recommandera à tous : c'est un geste
#: de gouvernance, au même titre que valider un rôle.
GOUVERNANCE = "roles"

#: Candidats scorés en un appel : l'écran des résultats les envoie tous.
CANDIDATS_MAX = 2000
CLE_MAX = 200


class CandidatScore(BaseModel):
    """Les chiffres d'un candidat, tels que l'écran les affiche. Rien d'autre."""

    model_config = ConfigDict(extra="forbid")

    cle: str = Field(..., min_length=1, max_length=CLE_MAX)
    indicateurs: Dict[str, Union[int, float]] = Field(default_factory=dict)


class DemandeDeRessemblance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidats: List[CandidatScore] = Field(default_factory=list, max_length=CANDIDATS_MAX)


class Exclusion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exclue: bool


def _decisions_lisibles(kb: KnowledgeBase) -> List[Dict[str, Any]]:
    """L'historique tel que l'écran le montre : ce qui a appris, et ce qui non."""
    rendues = []
    for decision in kb.get_decisions():
        _, manquantes = vecteur(decision.get("indicateurs") or {})
        rendues.append({"role_id": decision.get("role_id"),
                        "verdict": decision.get("verdict"),
                        "decided_at": decision.get("decided_at"),
                        "exclue": bool(decision.get("exclue_de_l_apprentissage")),
                        "manquantes": manquantes})
    return rendues


@router.get("")
async def etat(
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    user: User = Depends(require_permission_or_dev(LECTURE)),
) -> Dict[str, Any]:
    """Où en est l'apprentissage, sa mesure à rebours, et l'historique qui le nourrit."""
    def _calculer():
        rendu = apprendre(kb.get_decisions(), Reglages.depuis_la_configuration(loader.config))
        rendu.pop("modele")
        rendu.pop("porteurs_de_l_historique")
        rendu["historique"] = _decisions_lisibles(kb)
        return rendu

    return await run_in_threadpool(_calculer)


@router.post("/ressemblance")
async def scorer(
    demande: DemandeDeRessemblance,
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    user: User = Depends(require_permission_or_dev(LECTURE)),
) -> Dict[str, Any]:
    """Pour chaque candidat : ressemble-t-il à ce que ce workspace valide ?

    Sans assez de décisions, aucun score n'est rendu : l'état dit combien il
    en manque. Un score calculé sur six décisions se lirait comme un avis.
    """
    def _calculer():
        appris = apprendre(kb.get_decisions(), Reglages.depuis_la_configuration(loader.config),
                           mesurer=False)
        rendu = {cle: valeur for cle, valeur in appris.items()
                 if cle not in ("modele", "porteurs_de_l_historique")}
        rendu["candidats"] = (
            [{"cle": candidat.cle,
              **ressemblance(appris["modele"], candidat.indicateurs,
                             appris["porteurs_de_l_historique"])}
             for candidat in demande.candidats]
            if appris["pret"] else [])
        return rendu

    return await run_in_threadpool(_calculer)


@router.put("/decisions/{role_id}")
async def exclure(
    role_id: str,
    demande: Exclusion,
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
    user: User = Depends(require_permission_or_dev(GOUVERNANCE)),
) -> Dict[str, Any]:
    """Retire une décision de l'apprentissage, ou l'y remet. Elle reste dans l'historique."""
    if not kb.exclure_de_l_apprentissage(role_id, demande.exclue):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail={"code": "apprentissage.decision_inconnue",
                                    "params": {"role": role_id}})
    journal.consigner(Action.APPRENTISSAGE_MODIFIE, "decision", role_id,
                      {"exclue": demande.exclue})
    return {"role_id": role_id, "exclue": demande.exclue}


@router.post("/oublier")
async def oublier(
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
    user: User = Depends(require_permission_or_dev(GOUVERNANCE)),
) -> Dict[str, Any]:
    """Retire toutes les décisions présentes de l'apprentissage."""
    retirees = kb.oublier_l_apprentissage()
    journal.consigner(Action.APPRENTISSAGE_MODIFIE, "apprentissage", "",
                      {"oubliees": retirees})
    return {"oubliees": retirees}
