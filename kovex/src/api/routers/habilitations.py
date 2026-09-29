# Fichier : src/api/routers/habilitations.py
"""Détail d'une habilitation, vu depuis une identité, une application ou un droit.

Ce module présupposait des colonnes que le produit n'impose pas : `Nom`,
`Description`, `Departement`, `Date_attribution`. Absentes du fichier du
client — ce qui est le cas courant, puisque **les colonnes ne sont pas connues
à l'avance** —, elles étaient remplacées par une chaîne vide ou par « N/A ». Le
détail affichait donc quatre colonnes systématiquement vides, sans que rien
n'indique qu'il ne s'agissait pas d'une donnée manquante chez le client mais
d'un nom de colonne inventé par le produit.

Le principe retenu est celui déjà appliqué au graphe : **transmettre les
colonnes réelles**, dans l'ordre du fichier, sans en présumer aucune. Le client
affiche ce que le référentiel contient, et rien d'autre.

Les jointures passent par pandas. Elles étaient faites par un balayage complet
du référentiel à l'intérieur d'une boucle sur les lignes : pour un droit détenu
par treize mille identités, cela faisait treize mille parcours du fichier des
identités. La pagination borne par ailleurs la réponse — une modale n'affiche
pas treize mille lignes, et rien ne justifie de les sérialiser.
"""

import logging
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, status
from starlette.concurrency import run_in_threadpool

from src.api.dependencies import get_data_loader
from src.core.data.loader import DataLoader

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/habilitations", tags=["Habilitations"])

#: Nombre de lignes rendues par défaut. La pagination existe pour les cas
#: réels : un droit socle est détenu par des dizaines de milliers d'identités.
TAILLE_PAGE_DEFAUT = 50

#: Plafond par requête, pour que la taille de page reste un choix de l'appelant
#: sans qu'une valeur extrême ne serve de levier contre le serveur.
TAILLE_PAGE_MAX = 500


def _valeur(brute: Any) -> Optional[Any]:
    """Valeur exploitable d'une cellule, `None` si elle n'est pas renseignée.

    `None` plutôt que chaîne vide : dans une revue d'accès, savoir qu'un champ
    n'est pas renseigné est une information, pas un vide typographique.
    """
    if brute is None or (isinstance(brute, float) and pd.isna(brute)):
        return None
    texte = str(brute).strip()
    if not texte or texte.lower() in ("nan", "none", "nat"):
        return None
    return texte


def _attributs(ligne: pd.Series, colonnes: List[str]) -> List[Dict[str, Any]]:
    """Attributs d'une ligne, dans l'ordre des colonnes du fichier."""
    return [{"name": colonne, "value": _valeur(ligne.get(colonne))}
            for colonne in colonnes]


def _colonnes_utiles(cadre: pd.DataFrame, exclues) -> List[str]:
    """Colonnes du cadre, hors identifiants déjà portés par la réponse."""
    return [c for c in cadre.columns if c not in set(exclues)]


def _page(taille: int, debut: int, total: int) -> Dict[str, int]:
    return {"limit": taille, "offset": debut, "total": total,
            "has_more": debut + taille < total}


# ------------------------------------------------------------- par identité


@router.get("/user/{user_id}")
async def get_user_habilitations(
    user_id: str,
    limit: int = Query(TAILLE_PAGE_DEFAUT, ge=1, le=TAILLE_PAGE_MAX),
    offset: int = Query(0, ge=0),
    loader: DataLoader = Depends(get_data_loader),
) -> Dict[str, Any]:
    """Droits détenus par une identité, avec les colonnes réelles des fichiers.

    Chaque ligne porte les colonnes de l'habilitation **et** celles du
    référentiel des droits. Les deux peuvent se contredire — une habilitation
    qui rattache un droit à une application, un référentiel qui le rattache à
    une autre — et c'est précisément ce qu'une revue doit pouvoir constater.
    """
    return await run_in_threadpool(_habilitations_identite, loader, user_id,
                                   limit, offset)


def _habilitations_identite(loader: DataLoader, user_id: str,
                            limit: int, offset: int) -> Dict[str, Any]:
    habs = loader.habilitations
    droits = loader.rights
    col_user = DataLoader.COL_USER_ID
    col_droit = DataLoader.COL_RIGHT_ID

    if habs.empty or col_user not in habs.columns:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "habilitations.user_without_rights",
                    "params": {"identifiant": user_id}},
        )

    lignes = habs[habs[col_user].astype(str) == str(user_id)]
    if lignes.empty:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "habilitations.user_without_rights",
                    "params": {"identifiant": user_id}},
        )

    referencies = (set(droits[col_droit].astype(str))
                   if not droits.empty and col_droit in droits.columns else set())

    fusion = _joindre(lignes, droits, col_droit)
    colonnes = _colonnes_utiles(fusion, (col_user, col_droit))

    total = len(fusion)
    page = fusion.iloc[offset:offset + limit]

    elements = []
    for _, ligne in page.iterrows():
        identifiant = _valeur(ligne.get(col_droit))
        elements.append({
            "id": identifiant,
            # Un droit détenu mais absent du référentiel n'est pas une donnée
            # manquante : c'est une anomalie de gouvernance, signalée comme
            # telle par un drapeau que le client sait traduire.
            "orphan": identifiant is not None and identifiant not in referencies,
            "attributes": _attributs(ligne, colonnes),
        })

    return {
        "user_id": user_id,
        "columns": colonnes,
        "total_habilitations": total,
        "habilitations": elements,
        "page": _page(limit, offset, total),
    }


# --------------------------------------------------------- par application


@router.get("/application/{app_id}")
async def get_app_habilitations(
    app_id: str,
    limit: int = Query(TAILLE_PAGE_DEFAUT, ge=1, le=TAILLE_PAGE_MAX),
    offset: int = Query(0, ge=0),
    loader: DataLoader = Depends(get_data_loader),
) -> Dict[str, Any]:
    """Droits d'une application et nombre d'identités qui les détiennent."""
    return await run_in_threadpool(_habilitations_application, loader, app_id,
                                   limit, offset)


def _habilitations_application(loader: DataLoader, app_id: str,
                               limit: int, offset: int) -> Dict[str, Any]:
    habs = loader.habilitations
    droits = loader.rights
    col_app = DataLoader.COL_APP_ID
    col_droit = DataLoader.COL_RIGHT_ID
    col_user = DataLoader.COL_USER_ID

    if droits.empty or col_app not in droits.columns:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "habilitations.application_without_rights",
                    "params": {"identifiant": app_id}},
        )

    droits_app = droits[droits[col_app].astype(str) == str(app_id)]
    if droits_app.empty:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "habilitations.application_without_rights",
                    "params": {"identifiant": app_id}},
        )

    identifiants = set(droits_app[col_droit].astype(str))
    concernees = (habs[habs[col_droit].astype(str).isin(identifiants)]
                  if not habs.empty and col_droit in habs.columns
                  else habs.iloc[0:0])

    # Nombre d'identités **distinctes**, et non nombre de lignes : un fichier
    # d'habilitations qui répète un couple (identité, droit) — deux sources,
    # deux imports — gonflait le compte affiché.
    if concernees.empty or col_user not in concernees.columns:
        porteurs = pd.Series(dtype="int64")
    else:
        porteurs = concernees.groupby(
            concernees[col_droit].astype(str))[col_user].nunique()

    colonnes = _colonnes_utiles(droits_app, (col_droit,))
    lignes = []
    for _, ligne in droits_app.iterrows():
        identifiant = _valeur(ligne.get(col_droit))
        lignes.append({
            "id": identifiant,
            "user_count": int(porteurs.get(str(identifiant), 0)),
            "attributes": _attributs(ligne, colonnes),
        })
    lignes.sort(key=lambda element: (-element["user_count"],
                                     element["id"] or ""))

    total = len(lignes)
    return {
        "application_id": app_id,
        "columns": colonnes,
        # Deux comptes distincts, là où un seul était rendu sous un nom
        # ambigu : les droits déclarés par le référentiel, et ceux qu'au moins
        # une identité détient. Leur écart est une information de gouvernance.
        "total_rights": total,
        "rights_with_holders": int((porteurs > 0).sum()) if len(porteurs) else 0,
        "total_users": int(concernees[col_user].nunique())
                       if not concernees.empty and col_user in concernees.columns else 0,
        "total_habilitations": int(len(concernees)),
        "rights": lignes[offset:offset + limit],
        "page": _page(limit, offset, total),
    }


# ---------------------------------------------------------------- par droit


@router.get("/right/{right_id}")
async def get_right_holders(
    right_id: str,
    limit: int = Query(TAILLE_PAGE_DEFAUT, ge=1, le=TAILLE_PAGE_MAX),
    offset: int = Query(0, ge=0),
    loader: DataLoader = Depends(get_data_loader),
) -> Dict[str, Any]:
    """Identités détenant un droit, avec les colonnes réelles des fichiers."""
    return await run_in_threadpool(_detenteurs_du_droit, loader, right_id,
                                   limit, offset)


def _detenteurs_du_droit(loader: DataLoader, right_id: str,
                         limit: int, offset: int) -> Dict[str, Any]:
    habs = loader.habilitations
    identites = loader.identities
    droits = loader.rights
    col_user = DataLoader.COL_USER_ID
    col_droit = DataLoader.COL_RIGHT_ID

    if habs.empty or col_droit not in habs.columns:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "habilitations.right_without_holders",
                    "params": {"identifiant": right_id}},
        )

    lignes = habs[habs[col_droit].astype(str) == str(right_id)]
    if lignes.empty:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "habilitations.right_without_holders",
                    "params": {"identifiant": right_id}},
        )

    connues = (set(identites[col_user].astype(str))
               if not identites.empty and col_user in identites.columns else set())

    fusion = _joindre(lignes, identites, col_user)
    colonnes = _colonnes_utiles(fusion, (col_user, col_droit))

    total = len(fusion)
    page = fusion.iloc[offset:offset + limit]

    detenteurs = []
    for _, ligne in page.iterrows():
        identifiant = _valeur(ligne.get(col_user))
        detenteurs.append({
            "id": identifiant,
            "orphan": identifiant is not None and identifiant not in connues,
            "attributes": _attributs(ligne, colonnes),
        })

    return {
        "right_id": right_id,
        # Le droit lui-même, tel que le référentiel le décrit — sans supposer
        # qu'il y figure : un droit détenu peut n'être déclaré nulle part.
        "right": _description_du_droit(droits, col_droit, right_id),
        "columns": colonnes,
        "total_holders": total,
        "holders": detenteurs,
        "page": _page(limit, offset, total),
    }


def _description_du_droit(droits: pd.DataFrame, col_droit: str,
                          right_id: str) -> Optional[Dict[str, Any]]:
    if droits.empty or col_droit not in droits.columns:
        return None
    trouve = droits[droits[col_droit].astype(str) == str(right_id)]
    if trouve.empty:
        return None
    ligne = trouve.iloc[0]
    colonnes = _colonnes_utiles(droits, (col_droit,))
    return {"id": str(right_id), "attributes": _attributs(ligne, colonnes)}


# ------------------------------------------------------------------ commun


def _joindre(gauche: pd.DataFrame, referentiel: pd.DataFrame,
             cle: str) -> pd.DataFrame:
    """Jointure à gauche sur une clé, en une passe.

    Le rapprochement se faisait par un balayage du référentiel **par ligne** :
    un droit détenu par treize mille identités provoquait treize mille
    parcours complets du fichier des identités. À volumétrie réelle, la modale
    de détail était le point le plus lent du produit.

    Les clés sont comparées en texte : un référentiel qui numérote ses
    identifiants et un fichier d'habilitations qui les cite entre guillemets
    ne se rapprochaient pas, et toutes les lignes ressortaient orphelines.
    """
    if referentiel.empty or cle not in referentiel.columns:
        return gauche.copy()

    gauche = gauche.copy()
    droite = referentiel.copy()
    gauche["__cle"] = gauche[cle].astype(str)
    droite["__cle"] = droite[cle].astype(str)
    # Un référentiel qui déclare deux fois le même identifiant multiplierait
    # les lignes de la jointure : on garde la première déclaration, celle que
    # le reste du produit utilise déjà.
    droite = droite.drop_duplicates(subset="__cle", keep="first")
    droite = droite.drop(columns=[cle])

    fusion = gauche.merge(droite, on="__cle", how="left", suffixes=("", "_ref"))
    return fusion.drop(columns=["__cle"])


# ------------------------------------------------------------ statistiques


@router.get("/stats")
async def get_habilitations_stats(
    loader: DataLoader = Depends(get_data_loader),
) -> Dict[str, Any]:
    """Compteurs globaux sur le fichier des habilitations."""
    return await run_in_threadpool(_statistiques, loader)


def _statistiques(loader: DataLoader) -> Dict[str, Any]:
    habs = loader.habilitations
    col_user = DataLoader.COL_USER_ID
    col_droit = DataLoader.COL_RIGHT_ID

    if habs.empty or col_user not in habs.columns or col_droit not in habs.columns:
        return {"total_habilitations": 0, "unique_users": 0, "unique_rights": 0,
                "avg_rights_per_user": 0, "avg_users_per_right": 0}

    total = len(habs)
    identites = int(habs[col_user].nunique())
    droits = int(habs[col_droit].nunique())

    return {
        "total_habilitations": total,
        "unique_users": identites,
        "unique_rights": droits,
        "avg_rights_per_user": round(total / identites, 1) if identites else 0,
        "avg_users_per_right": round(total / droits, 1) if droits else 0,
    }
