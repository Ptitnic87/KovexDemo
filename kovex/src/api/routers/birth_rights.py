# Fichier : src/api/routers/birth_rights.py
"""Détection des droits socles (« birth rights » dans la littérature).

Un droit socle est détenu par la quasi-totalité de la population : badge,
messagerie, intranet. Il n'apporte aucune information de regroupement et il
fausse le mining s'il n'est pas isolé au préalable.

Trois défauts corrigés ici :

- un seuil hors bornes rendait `{"error": "..."}` avec un **code HTTP 200**.
  Le client ne pouvait pas distinguer une détection réussie d'un refus, et le
  message était écrit en français dans le code du serveur ;
- l'export Excel écrivait toujours dans le même fichier,
  `output/01_birth_rights_candidates.xlsx`, sans distinction de workspace. Deux
  clients analysés sur le même serveur écrasaient l'export l'un de l'autre, et
  un téléchargement lancé au mauvais moment servait le fichier du voisin ;
- la détection s'exécutait dans la boucle d'événements. Sur un référentiel
  volumineux, elle y bloquait toutes les autres requêtes.
"""

import logging
import os
import tempfile
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from src.api.dependencies import get_data_loader, get_kb
from src.core.data.loader import DataLoader
from src.core.knowledge.knowledge_base import KnowledgeBase
from src.core.knowledge.perimetre import perimetre_effectif, restreindre
from src.core.mining.birth_rights_detector import BirthRightsDetector
from src.infrastructure.branding import PREFIXE_FICHIERS
from src.infrastructure.i18n_manager import i18n

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/birth-rights", tags=["Détection des droits socles"])

#: Seuil par défaut, en pourcentage de la population.
SEUIL_DEFAUT = 90.0


class BirthRightsRequest(BaseModel):
    """Paramètres de détection.

    Les bornes sont portées par le modèle : un seuil hors bornes est refusé
    par un 422 avant d'atteindre le code, au lieu d'être signalé par un objet
    d'erreur rendu avec un code de succès.
    """

    frequency_threshold: float = Field(SEUIL_DEFAUT, ge=0, le=100)


def _detecter(loader: DataLoader, kb: KnowledgeBase,
              seuil: float) -> Dict[str, Any]:
    detecteur = BirthRightsDetector(restreindre(loader, perimetre_effectif(loader, kb)))
    return detecteur.detect_birth_rights(frequency_threshold=seuil)


@router.post("/detect")
async def detect_birth_rights(
    request: BirthRightsRequest,
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
) -> Dict[str, Any]:
    """Détecte les droits détenus par au moins `frequency_threshold` % de la
    population, et décrit le rôle socle qu'ils formeraient."""
    return await run_in_threadpool(_detecter, loader, kb,
                                   request.frequency_threshold)


@router.post("/export")
async def export_birth_rights_excel(
    request: BirthRightsRequest,
    langue: str = Query("fr"),
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
) -> FileResponse:
    """Exporte les droits socles détectés dans un classeur Excel.

    Le classeur est écrit dans un fichier temporaire propre à la requête, puis
    supprimé une fois la réponse envoyée. Un emplacement fixe et partagé
    faisait qu'un export chassait le précédent : sur un serveur qui héberge
    plusieurs workspaces, le fichier téléchargé pouvait être celui d'un autre
    client.

    Il est produit dans la langue demandée, comme le PDF et l'export de qualité
    des données : le serveur ne devine pas la langue de qui télécharge.
    """
    chemin = await run_in_threadpool(_construire_classeur, loader, kb,
                                     request.frequency_threshold, langue)

    return FileResponse(
        path=chemin,
        filename=f"{PREFIXE_FICHIERS}_droits_socles.xlsx",
        media_type=("application/vnd.openxmlformats-officedocument"
                    ".spreadsheetml.sheet"),
        background=BackgroundTask(_supprimer, chemin),
    )


def _construire_classeur(loader: DataLoader, kb: KnowledgeBase,
                         seuil: float, langue: str = "fr") -> str:
    resultat = _detecter(loader, kb, seuil)

    def traduire(cle, params=None):
        return i18n.t(cle, locale=langue, **(params or {}))

    descripteur, chemin = tempfile.mkstemp(suffix=".xlsx",
                                           prefix=f"{PREFIXE_FICHIERS}-socles-")
    os.close(descripteur)

    try:
        BirthRightsDetector(restreindre(loader, perimetre_effectif(loader, kb))) \
            .export_to_excel(resultat, chemin, traduire)
    except Exception as erreur:
        _supprimer(chemin)
        logger.error("Classeur des droits socles non généré : %s", erreur)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "birth_rights.export_failed"},
        )

    if not os.path.exists(chemin) or os.path.getsize(chemin) == 0:
        _supprimer(chemin)
        logger.error("Classeur des droits socles vide ou absent : %s", chemin)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "birth_rights.export_failed"},
        )

    return chemin


def _supprimer(chemin: str) -> None:
    """Efface le fichier temporaire, sans faire échouer la réponse déjà partie."""
    try:
        os.unlink(chemin)
    except OSError as erreur:  # pragma: no cover - dépend du système de fichiers
        logger.warning("Fichier temporaire non supprimé (%s) : %s", chemin, erreur)


@router.get("/stats")
async def get_birth_rights_stats(
    threshold: float = Query(SEUIL_DEFAUT, ge=0, le=100),
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
) -> Dict[str, Any]:
    """Compteurs seuls, sans la liste : de quoi alimenter les indicateurs.

    Le seuil n'était borné nulle part sur cette route, alors qu'il l'était sur
    la détection : les deux écrans pouvaient donc répondre différemment à la
    même question.
    """
    resultat = await run_in_threadpool(_detecter, loader, kb, threshold)
    socle = resultat["socle_role"]

    return {
        "stats": resultat["stats"],
        "socle_role_summary": {
            "name": socle["name"],
            "right_count": socle["right_count"],
            "user_count": socle["user_count"],
        },
    }
