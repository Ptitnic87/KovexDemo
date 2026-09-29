from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import Callable, List, Dict, Any, Optional, Tuple
from pydantic import BaseModel, ConfigDict, Field
from src.api.dependencies import get_data_loader
from src.api.lignes import (IDENTIFIANTS_MAX, REFERENTIELS_DE_LIGNES,  # noqa: F401
                            TAILLE_DE_PAGE_MAX, LignesDemandees, LignesRendues,
                            PaginatedResponse, process_dataframe,
                            restreindre_puis_paginer)
from src.core.data.loader import DataLoader
from src.api.journal import Journal, get_journal
from src.core.audit import Action
import logging

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

router = APIRouter()

# --- ROUTES ---

@router.get("/users/list", response_model=PaginatedResponse)
def list_users_full(
    page: int = 1, size: int = 50, 
    search: Optional[str] = None, 
    sort_col: Optional[str] = None, 
    sort_desc: bool = False, 
    loader: DataLoader = Depends(get_data_loader)
):
    # L'explorateur est le premier endroit où l'on regarde une population. Un
    # compte d'administration y figurait à côté du compte nominatif de la même
    # personne, et rien ne disait lequel était lequel : c'est l'utilisateur qui
    # lisait `ADM` dans l'identifiant.
    return process_dataframe(loader.identities, page, size, search, sort_col,
                             not sort_desc, DataLoader.COL_USER_ID,
                             loader.config.privileges)

# 🔧 FIX CRITIQUE : Route /rights DOIT être AVANT /rights/list !
@router.get("/rights")
def get_all_rights(loader: DataLoader = Depends(get_data_loader)):
    """
    Retourne tous les droits, sans pagination, pour le compositeur de rôles.

    Ce routeur n'a pas de préfixe : la route est `/api/v1/rights`. Le
    commentaire annonçait `/api/v1/explorer/rights`, qui n'existe pas — un
    lecteur cherchant cette route ne la trouvait nulle part.
    """
    if loader.rights.empty:
        logger.info("Référentiel des droits vide : aucun droit à retourner")
        return {"data": [], "total": 0}

    rights_list = loader.rights.fillna("").to_dict(orient="records")
    return {"data": rights_list, "total": len(rights_list)}

@router.get("/rights/list", response_model=PaginatedResponse)
def list_rights(
    page: int = 1, size: int = 50, 
    search: Optional[str] = None, 
    sort_col: Optional[str] = None, 
    sort_desc: bool = False,
    loader: DataLoader = Depends(get_data_loader)
):
    # Aucun marqueur : un droit n'est pas un compte. La colonne d'identifiant
    # part quand même — le tableau s'en sert pour rattacher une ligne.
    return process_dataframe(loader.rights, page, size, search, sort_col,
                             not sort_desc, DataLoader.COL_RIGHT_ID)

@router.post("/referentiels/{referentiel}/lignes", response_model=LignesRendues)
def lignes_du_referentiel(
    referentiel: str,
    demande: LignesDemandees,
    loader: DataLoader = Depends(get_data_loader),
) -> LignesRendues:
    """Les lignes d'un référentiel pour un ensemble d'identifiants.

    La fenêtre de validation d'un rôle ne montrait que l'identifiant de chaque
    porteur et de chaque droit. C'est la seule colonne que le produit connaisse
    par construction — et c'est justement celle qui ne dit rien : personne ne
    décoche `U0042` en connaissance de cause. Les autres colonnes sont celles
    du fichier du client, et il faut aller les chercher.

    **Un identifiant inconnu du référentiel est rendu quand même**, avec ce
    seul champ rempli. C'est le point délicat : cette liste décide de ce qui
    sera validé. Un droit orphelin — présent dans les habilitations, absent du
    référentiel des droits — disparaîtrait silencieusement du rôle, et le rôle
    validé ne serait pas celui qui a été proposé.
    """
    if referentiel not in REFERENTIELS_DE_LIGNES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "referential.unknown",
                    "params": {"referentiel": referentiel}})

    source, colonne = REFERENTIELS_DE_LIGNES[referentiel]
    # Le marqueur ne part que pour les identités : appliqué au référentiel des
    # droits, il chercherait un fragment de nommage de compte dans des
    # identifiants de droit et marquerait au hasard.
    marqueur = (loader.config.privileges if referentiel == "identities"
                else None)
    return restreindre_puis_paginer(source(loader), colonne,
                                    demande.identifiants, demande, marqueur)


@router.get("/applications/list", response_model=PaginatedResponse)
def list_applications(
    page: int = 1, size: int = 50, 
    search: Optional[str] = None, 
    sort_col: Optional[str] = None, 
    sort_desc: bool = False,
    loader: DataLoader = Depends(get_data_loader)
):
    return process_dataframe(loader.applications, page, size, search, sort_col, not sort_desc)

@router.get("/data-status")
async def get_data_cleaning_status(
    loader: DataLoader = Depends(get_data_loader) 
):
    """Récupère le statut et le rapport des incohérences de données."""
    report = loader.get_cleaning_status() 
    return report

@router.post("/data-recertify")
async def launch_data_recertification(
    loader: DataLoader = Depends(get_data_loader),
    journal: Journal = Depends(get_journal),
):
    """Simule le lancement d'un processus de recertification."""
    total_issues = loader.get_health_score()["total_issues"]
    journal.consigner(
        Action.RECERTIFICATION_LANCEE, "data_quality", "",
        {"anomalies": total_issues},
    )
    
    # Le serveur nomme le cas et donne le nombre ; la phrase est composée par
    # le client, dans sa langue. Elle était écrite ici, en français.
    return {
        "status": "success" if total_issues else "warning",
        "code": ("recertification.launched" if total_issues
                 else "recertification.nothing_to_do"),
        "params": {"count": total_issues},
    }
