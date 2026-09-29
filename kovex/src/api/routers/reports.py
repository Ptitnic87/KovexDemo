# src/api/routers/reports.py
"""Rapport de qualité des données du workspace actif."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.api.dependencies import get_data_loader
from src.api.routers.explorer import PaginatedResponse, process_dataframe
from src.api.schemas import CleaningReport
from src.core.data.loader import DataLoader
from src.core.data.politique_cles import REFERENTIELS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["Rapports"])


@router.get("/cleaning", response_model=CleaningReport)
def get_cleaning_report(loader: DataLoader = Depends(get_data_loader)):
    """Retourne le rapport de qualité des données.

    L'implémentation précédente appelait `loader.report` et
    `loader.run_full_analysis()`, qui n'existent pas sur le DataLoader :
    l'endpoint répondait systématiquement 500. Le rapport est produit par
    `get_cleaning_status()`, qui le calcule à la demande s'il n'est pas
    encore en cache.
    """
    try:
        rapport = loader.get_cleaning_status()
    except Exception:
        logger.exception("Échec du calcul du rapport de qualité")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "report.generation_failed"},
        )

    logger.debug(
        "Rapport de qualité : %d utilisateurs orphelins, %d droits orphelins, "
        "%d utilisateurs sans habilitation",
        rapport.get("orphan_users_count", 0),
        rapport.get("orphan_rights_count", 0),
        rapport.get("forest_users_count", 0),
    )
    return CleaningReport(**rapport)


@router.get("/transformations/{referentiel}", response_model=PaginatedResponse)
def get_transformation_differences(
    referentiel: str,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=500),
    search: Optional[str] = None,
    loader: DataLoader = Depends(get_data_loader),
):
    """Valeurs que les transformations ont changées dans un référentiel.

    L'échantillon du rapport de qualité montre l'effet d'une règle ; cet écran
    répond à l'autre question, celle qui se pose quand un rapprochement échoue
    : « qu'est-ce que le produit a fait de cet identifiant-là ». Sans lui, la
    seule façon de le savoir serait de rouvrir les CSV — c'est-à-dire de sortir
    du produit, ce que ce lot existe précisément pour éviter.
    """
    if referentiel not in REFERENTIELS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "report.unknown_referential"},
        )
    return process_dataframe(
        loader.differences_transformation(referentiel), page, size, search)
