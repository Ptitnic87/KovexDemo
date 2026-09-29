# src/api/routers/stats.py
"""Statistiques de synthèse du tableau de bord.

Aucun chiffre restitué ici n'est simulé : tout est calculé à partir des
fichiers du workspace actif. Les libellés ne sont pas construits côté serveur —
l'API renvoie des clés de traduction, le client les affiche.
"""

from typing import Any, Dict

import pandas as pd
from fastapi import APIRouter, Depends

from src.api.dependencies import get_data_loader, get_kb
from src.api.schemas import GlobalStats
from src.core.data.loader import DataLoader
from src.core.knowledge.knowledge_base import KnowledgeBase

router = APIRouter(prefix="/stats")


@router.get("/dashboard", response_model=GlobalStats)
def get_dashboard_stats(
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
) -> Dict[str, Any]:
    """Compteurs et indicateurs de santé du workspace actif.

    L'évolution accompagne les compteurs quand le référentiel a déjà été
    chargé dans deux versions différentes. Elle est absente sinon — et c'était
    tout le problème du « +12 % » qui figurait sous le nombre de droits : un
    chiffre écrit dans le gabarit, qui ne mesurait rien et ne bougeait jamais.
    """
    identities = loader.identities
    applications = loader.applications
    rights = loader.rights
    habilitations = loader.habilitations
    health = loader.get_health_score()

    # Applications portant le plus de droits. Le rattachement vient du
    # référentiel des droits ; sans cette colonne, le classement n'existe pas.
    top_apps: Dict[str, int] = {}
    if DataLoader.COL_APP_ID in rights.columns:
        top_apps = rights[DataLoader.COL_APP_ID].value_counts().head(5).to_dict()

    avg_rights = len(habilitations) / len(identities) if not identities.empty else 0.0

    return {
        "evolution": kb.evolution_du_referentiel(),
        "total_users": len(identities),
        "total_applications": len(applications),
        "total_rights": len(rights),
        "total_habilitations": len(habilitations),
        "top_applications": {str(key): int(value) for key, value in top_apps.items()},
        "avg_rights_per_user": round(avg_rights, 2),
        "health_score": health["score"],
        # Clé i18n, jamais un libellé : le serveur ne connaît pas la langue
        # de l'utilisateur.
        "health_status_key": health["status_key"],
    }


@router.get("/rights-distribution")
def get_rights_distribution(loader: DataLoader = Depends(get_data_loader)) -> Dict[str, Any]:
    """Distribution du nombre de droits détenus par identité.

    C'est la forme du référentiel, et elle décide de ce que le mining peut
    faire : une distribution étalée signifie peu de signatures partagées, donc
    peu de regroupements exacts possibles.

    La distribution est rendue exhaustive, sans regroupement en classes : le
    choix d'une largeur de classe serait un parti pris de lecture, et il
    reviendrait à l'utilisateur.
    """
    identities = loader.identities
    habilitations = loader.habilitations
    vide = {
        "distribution": [],
        "identities_total": len(identities),
        "identities_without_rights": len(identities),
        "max_rights": 0,
        "median_rights": 0.0,
    }

    if habilitations.empty or DataLoader.COL_USER_ID not in habilitations.columns:
        return vide

    par_identite = habilitations.groupby(DataLoader.COL_USER_ID).size()

    # Les identités du référentiel absentes des habilitations détiennent zéro
    # droit : les omettre décalerait la médiane et masquerait les comptes
    # inactifs, qui sont précisément ce qu'un audit cherche.
    sans_droit = 0
    if not identities.empty and DataLoader.COL_USER_ID in identities.columns:
        connues = set(identities[DataLoader.COL_USER_ID].dropna().astype(str))
        porteuses = set(par_identite.index.astype(str))
        sans_droit = len(connues - porteuses)

    comptes = pd.concat([par_identite, pd.Series([0] * sans_droit, dtype=par_identite.dtype)])
    if comptes.empty:
        return vide

    occurrences = comptes.value_counts().sort_index()

    return {
        "distribution": [
            {"rights": int(nombre_de_droits), "identities": int(effectif)}
            for nombre_de_droits, effectif in occurrences.items()
        ],
        "identities_total": int(len(comptes)),
        "identities_without_rights": int(sans_droit),
        "max_rights": int(comptes.max()),
        "median_rights": float(comptes.median()),
    }
