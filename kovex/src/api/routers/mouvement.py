# Fichier : src/api/routers/mouvement.py
"""Les droits qu'on garde d'un poste qu'on a quitté, vus de l'API.

Une seule route, et elle prend un paramètre qui n'a pas de valeur par défaut :
la **colonne qui définit les pairs**. Le produit ne connaît aucune colonne des
fichiers du client — ni `service`, ni `direction`, ni `jobtitle` — et en
choisir une d'office produirait des constats sur un regroupement que personne
n'a voulu.

Le calcul se refait à chaque appel, sur les données du jour : un droit résiduel
retiré cesse d'être signalé sans qu'on ait à toucher à quoi que ce soit.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from starlette.concurrency import run_in_threadpool

from src.api.dependencies import get_data_loader, get_kb
from src.core.data.loader import DataLoader
from src.core.knowledge.derogations import FAMILLE_ECART_AU_PAIR, cible_d_ecart
from src.core.knowledge.knowledge_base import KnowledgeBase
from src.core.knowledge.perimetre import perimetre_effectif
from src.core.knowledge.population import droits_par_identite
from src.core.mining.mouvement import Reglages, constats, synthese
from src.core.security.auth import User, require_permission_or_dev

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mouvement", tags=["Mouvement"])

#: Lire ce constat est un geste d'analyste, au même titre que lire les conflits
#: de séparation : il ne modifie rien et ne décide rien.
LECTURE = "mining"

#: Longueur maximale d'un nom de colonne accepté. Ce n'est pas une borne
#: métier : c'est la borne d'une chaîne qui vient de l'extérieur.
COLONNE_MAX = 200


def _groupes(loader: DataLoader, kb: KnowledgeBase,
             attribut: str) -> Dict[str, str]:
    """Chaque identité analysée, et la valeur qui définit ses pairs.

    Les identités **hors périmètre** sont écartées ici comme partout ailleurs :
    les comparer à un groupe dont elles ne font pas partie de l'analyse
    produirait des constats sur des gens qu'on a décidé de ne pas regarder.

    Une identité dont la valeur est vide n'a pas de pairs et ne figure pas dans
    le relevé. Lui en inventer — la ranger avec les autres valeurs vides —
    reviendrait à comparer entre eux des gens que rien ne rapproche.
    """
    identites = loader.identities
    # Pas de garde sur un référentiel vide : la route refuse déjà l'attribut
    # avant d'arriver ici, puisqu'un référentiel vide n'offre aucune colonne.
    # Une branche pour un cas qui ne se produit pas est une branche que
    # personne ne peut éprouver.
    if DataLoader.COL_USER_ID not in identites.columns:
        # Un référentiel chargé sans sa colonne d'identifiant ne permet aucun
        # rapprochement — le cas que la pagination des lignes connaît déjà.
        return {}
    ecartees = perimetre_effectif(loader, kb)
    groupes: Dict[str, str] = {}
    for identifiant, valeur in zip(identites[DataLoader.COL_USER_ID],
                                   identites[attribut]):
        cle = str(identifiant or "")
        groupe = "" if valeur is None else str(valeur).strip()
        if not cle or cle in ecartees or not groupe or groupe.lower() == "nan":
            continue
        groupes[cle] = groupe
    return groupes


@router.get("")
async def droits_conserves(
    attribut: str = Query(..., min_length=1, max_length=COLONNE_MAX),
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    user: User = Depends(require_permission_or_dev(LECTURE)),
) -> Dict[str, Any]:
    """Qui détient des droits atypiques de son groupe et typiques d'un autre.

    Le constat ne dit **pas** que la personne a changé de poste : la mobilité
    est l'explication la plus fréquente de cette forme, pas la seule. Le
    produit rend le rapprochement et ce qui l'a motivé ; conclure appartient à
    celui qui connaît l'organisation.
    """
    identites = loader.identities
    colonnes = list(identites.columns) if identites is not None and not getattr(
        identites, "empty", True) else []
    if attribut not in colonnes or attribut == DataLoader.COL_USER_ID:
        # Refusé plutôt que rendu vide : une liste vide se lirait « aucun
        # constat », alors que le regroupement demandé n'a pas eu lieu.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "mouvement.attribut_inconnu",
                    "params": {"attribut": attribut}})
    return await run_in_threadpool(_calculer, loader, kb, attribut)


def _calculer(loader: DataLoader, kb: KnowledgeBase,
              attribut: str) -> Dict[str, Any]:
    reglages = Reglages.depuis_la_configuration(loader.config)
    groupes = _groupes(loader, kb, attribut)
    detenus = droits_par_identite(loader.habilitations,
                                  DataLoader.COL_USER_ID,
                                  DataLoader.COL_RIGHT_ID)
    trouves = constats(groupes, detenus, reglages)
    return {
        "attribut": attribut,
        **synthese(groupes, trouves, len(groupes), reglages),
        # `lignes` et non `constats` : la synthèse emploie déjà `constats` pour
        # le **compte**, et rendre une liste sous le même nom la remplacerait
        # purement et simplement — un écran qui affiche « 200 » au lieu de
        # « 4 312 » sans que rien ne le signale. Le défaut a été écrit ici, et
        # c'est un test qui l'a rendu visible.
        "lignes": _justifies(loader, kb, [constat.en_dict()
                                          for constat in trouves[:reglages.constats_max]]),
        # Les bornes partent avec le résultat : l'écran doit pouvoir dire sur
        # quels seuils le constat repose, sans quoi « aucun constat » ne
        # s'interprète pas.
        "reglages": {
            "groupe_min": reglages.groupe_min,
            "rarete_max_pct": reglages.rarete_max_pct,
            "typique_min_pct": reglages.typique_min_pct,
            "droits_min": reglages.droits_min,
        },
    }


def _justifies(loader: DataLoader, kb: KnowledgeBase,
               lignes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Marque les droits dont l'écart a été justifié par une dérogation.

    Marqués, pas retirés : un droit justifié reste un droit résiduel, et un
    auditeur doit voir ce qui a été assumé. Le constat compte les mêmes droits
    qu'avant ; l'écran dit lesquels ont reçu une réponse.
    """
    from src.api.routers.derogations import etat_des_derogations

    couvertes = etat_des_derogations(loader, kb, FAMILLE_ECART_AU_PAIR)[0]
    for ligne in lignes:
        for droit in ligne["droits"]:
            droit["justifie"] = cible_d_ecart(ligne["identite"], droit["droit"]) in couvertes
    return lignes
