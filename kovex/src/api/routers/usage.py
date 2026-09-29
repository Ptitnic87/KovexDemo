# Fichier : src/api/routers/usage.py
"""Le signal d'usage, vu de l'API : ce qui est détenu et ne sert plus.

Toutes les routes prennent la même déclaration, et aucune pièce n'a de valeur
par défaut : la colonne qui porte la date (sur les habilitations, sur les
identités, ou les deux), le format de ses dates, le seuil d'inactivité. Le
produit ne connaît aucune colonne des fichiers du client, et un seuil choisi à
sa place produirait des constats que personne n'a décidés.

Le calcul se refait à chaque appel, sur les données du jour et le périmètre
d'analyse : une identité écartée de l'analyse ne l'est pas ici non plus.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from starlette.concurrency import run_in_threadpool

from src.api.dependencies import get_data_loader, get_kb
from src.api.lignes import (REFERENTIELS_DE_LIGNES, TAILLE_DE_PAGE_MAX,
                            LignesRendues, Pagination, restreindre_puis_paginer)
from src.core.data.loader import DataLoader
from src.core.knowledge.knowledge_base import KnowledgeBase
from src.core.knowledge.perimetre import perimetre_effectif
from src.core.knowledge.usage import (Declaration, DeclarationInvalide,
                                      bilan_des_identites, dormants_du_droit,
                                      habilitations_dormantes,
                                      identites_inactives, lire_les_dates,
                                      reference_effective)
from src.core.security.auth import User, require_permission_or_dev

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/usage", tags=["Usage"])

#: Lire ce constat est un geste d'analyste : il ne modifie rien.
LECTURE = "mining"

#: Borne d'une chaîne venue de l'extérieur, pas une borne métier.
TEXTE_MAX = 200

#: Les colonnes que le produit pose lui-même et qui ne portent jamais une date
#: d'usage : les proposer ferait choisir l'identifiant comme date.
_RESERVEES = (DataLoader.COL_USER_ID, DataLoader.COL_RIGHT_ID)


def _colonnes(tableau) -> List[str]:
    if tableau is None or getattr(tableau, "empty", True):
        return []
    return [str(colonne) for colonne in tableau.columns if colonne not in _RESERVEES]


@router.get("/colonnes")
async def colonnes(
    loader: DataLoader = Depends(get_data_loader),
    user: User = Depends(require_permission_or_dev(LECTURE)),
) -> Dict[str, Any]:
    """Les colonnes où une date d'usage peut se trouver, fichier par fichier."""
    return {"habilitations": _colonnes(loader.habilitations),
            "identites": _colonnes(loader.identities)}


class _Demande:
    """La déclaration d'une requête, validée une fois pour toutes les routes."""

    def __init__(self, loader: DataLoader, colonne_habilitation: str,
                 colonne_identite: str, format_date: str, inactivite_jours: int,
                 date_reference: str):
        if not colonne_habilitation and not colonne_identite:
            raise _refus("usage.colonne_requise", {})
        for colonne, tableau in ((colonne_habilitation, loader.habilitations),
                                 (colonne_identite, loader.identities)):
            if colonne and colonne not in _colonnes(tableau):
                # Refusée plutôt que lue vide : « aucun constat » se lirait
                # comme un référentiel où tout sert.
                raise _refus("usage.colonne_inconnue", {"colonne": colonne})
        try:
            self.declaration = Declaration.lue(format_date, inactivite_jours,
                                               date_reference)
        except DeclarationInvalide as erreur:
            raise _refus("usage.declaration_invalide", {"motif": str(erreur)})
        self.colonne_habilitation = colonne_habilitation
        self.colonne_identite = colonne_identite


def _refus(code: str, params: Dict[str, Any]) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                         detail={"code": code, "params": params})


def _lire(loader: DataLoader, kb: KnowledgeBase, demande: _Demande):
    """Les lignes du périmètre, leurs dates lues, et la date de l'export."""
    ecartees = perimetre_effectif(loader, kb)
    seuil = demande.declaration.inactivite_jours
    habilitations = identites = None
    if demande.colonne_habilitation:
        table = loader.habilitations
        garder = ~table[DataLoader.COL_USER_ID].astype(str).isin(ecartees)
        table = table[garder]
        habilitations = (table[DataLoader.COL_USER_ID].astype(str).tolist(),
                         table[DataLoader.COL_RIGHT_ID].astype(str).tolist(),
                         lire_les_dates(table[demande.colonne_habilitation].tolist(),
                                        demande.declaration.format_date))
    if demande.colonne_identite:
        table = loader.identities
        garder = ~table[DataLoader.COL_USER_ID].astype(str).isin(ecartees)
        table = table[garder]
        identites = (table[DataLoader.COL_USER_ID].astype(str).tolist(),
                     lire_les_dates(table[demande.colonne_identite].tolist(),
                                    demande.declaration.format_date))
    lectures = [une[-1] for une in (habilitations, identites) if une is not None]
    reference, deduite = reference_effective(demande.declaration, *lectures)
    return habilitations, identites, reference, deduite, seuil


@router.get("")
async def signal_d_usage(
    format_date: str = Query(..., min_length=1, max_length=64),
    inactivite_jours: int = Query(..., ge=1),
    limite: int = Query(..., ge=1, le=TAILLE_DE_PAGE_MAX),
    colonne_habilitation: str = Query("", max_length=TEXTE_MAX),
    colonne_identite: str = Query("", max_length=TEXTE_MAX),
    date_reference: str = Query("", max_length=10),
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    user: User = Depends(require_permission_or_dev(LECTURE)),
) -> Dict[str, Any]:
    """Ce qui ne sert plus : les droits les plus dormants, les comptes inactifs.

    Le compte des dates illisibles et des cellules vides part avec le
    résultat : un format mal déclaré qui ferait disparaître des lignes se voit
    au lieu de rendre un constat faux.
    """
    demande = _Demande(loader, colonne_habilitation, colonne_identite,
                       format_date, inactivite_jours, date_reference)

    def _calculer() -> Dict[str, Any]:
        habilitations, identites, reference, deduite, seuil = _lire(loader, kb, demande)
        rendu: Dict[str, Any] = {
            "date_reference": reference.isoformat() if reference else "",
            "date_reference_deduite": deduite,
            "inactivite_jours": seuil,
            "habilitations": None, "identites": None,
        }
        if habilitations is not None:
            _, droits, lecture = habilitations
            rendu["habilitations"] = habilitations_dormantes(
                droits, lecture, reference, seuil, limite)
        if identites is not None:
            rendu["identites"] = bilan_des_identites(identites[1], reference, seuil)
        return rendu

    return await run_in_threadpool(_calculer)


def _paginer(loader: DataLoader, identifiants: List[str],
             pagination: Pagination) -> LignesRendues:
    source, colonne = REFERENTIELS_DE_LIGNES["identities"]
    return restreindre_puis_paginer(source(loader), colonne, identifiants,
                                    pagination, loader.config.privileges)


@router.get("/dormants", response_model=LignesRendues)
async def dormants(
    droit: str = Query(..., min_length=1, max_length=500),
    format_date: str = Query(..., min_length=1, max_length=64),
    inactivite_jours: int = Query(..., ge=1),
    colonne_habilitation: str = Query(..., min_length=1, max_length=TEXTE_MAX),
    # L'autre colonne, si la synthèse l'employait : sans elle, la date de
    # l'export déduite ne serait pas la même, et la liste ne dirait pas les
    # mêmes personnes que le compte qu'elle déplie.
    colonne_identite: str = Query("", max_length=TEXTE_MAX),
    date_reference: str = Query("", max_length=10),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=TAILLE_DE_PAGE_MAX),
    search: Optional[str] = Query(None, max_length=200),
    sort_col: Optional[str] = Query(None, max_length=200),
    sort_desc: bool = False,
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    user: User = Depends(require_permission_or_dev(LECTURE)),
) -> LignesRendues:
    """Les détenteurs d'un droit qui ne s'en servent plus, avec les colonnes du client."""
    demande = _Demande(loader, colonne_habilitation, colonne_identite, format_date,
                       inactivite_jours, date_reference)
    pagination = Pagination(page=page, size=size, search=search,
                            sort_col=sort_col, sort_desc=sort_desc)

    def _calculer() -> LignesRendues:
        habilitations, _, reference, _, seuil = _lire(loader, kb, demande)
        identifiants, droits, lecture = habilitations
        return _paginer(loader, dormants_du_droit(identifiants, droits, lecture,
                                                  reference, seuil, droit), pagination)

    return await run_in_threadpool(_calculer)


@router.get("/inactives", response_model=LignesRendues)
async def inactives(
    format_date: str = Query(..., min_length=1, max_length=64),
    inactivite_jours: int = Query(..., ge=1),
    colonne_identite: str = Query(..., min_length=1, max_length=TEXTE_MAX),
    colonne_habilitation: str = Query("", max_length=TEXTE_MAX),
    date_reference: str = Query("", max_length=10),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=TAILLE_DE_PAGE_MAX),
    search: Optional[str] = Query(None, max_length=200),
    sort_col: Optional[str] = Query(None, max_length=200),
    sort_desc: bool = False,
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    user: User = Depends(require_permission_or_dev(LECTURE)),
) -> LignesRendues:
    """Les identités dont la dernière connexion précède le seuil."""
    demande = _Demande(loader, colonne_habilitation, colonne_identite, format_date,
                       inactivite_jours, date_reference)
    pagination = Pagination(page=page, size=size, search=search,
                            sort_col=sort_col, sort_desc=sort_desc)

    def _calculer() -> LignesRendues:
        _, identites, reference, _, seuil = _lire(loader, kb, demande)
        identifiants, lecture = identites
        return _paginer(loader, identites_inactives(identifiants, lecture,
                                                    reference, seuil), pagination)

    return await run_in_threadpool(_calculer)
