# Fichier : src/api/routers/identites.py
"""Le panneau d'une identité : ses constats rassemblés, sans score.

Une route. Elle ne calcule rien que les autres écrans ne calculent déjà — elle
les appelle pour une seule personne, par les mêmes fonctions, pour que le
panneau et l'écran dont vient chaque constat disent toujours la même chose.

Chaque section dit si elle a pu être établie. L'écart aux pairs exige qu'on
ait déclaré **qui sont les pairs** : le paramètre `attribut_pairs` n'a pas de
valeur par défaut, et sans lui la section le dit plutôt que de rendre une liste
vide qui se lirait « rien d'atypique ». Le marqueur de comptes à privilèges,
les règles de séparation et le catalogue suivent la même règle.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Set

from fastapi import APIRouter, Depends, HTTPException, Query, status
from starlette.concurrency import run_in_threadpool

from src.api.dependencies import get_data_loader, get_kb
from src.api.routers.derogations import etat_des_derogations
from src.api.routers.mouvement import _groupes
from src.api.routers.separation import (_couvertures, _derogation_du_conflit,
                                        _inoperantes, _modele, _resolues,
                                        _roles_par_identite)
from src.core.data.loader import DataLoader
from src.core.knowledge.constats_identite import (hors_modele, hors_referentiel,
                                                  roles_de_l_identite)
from src.core.knowledge.derogations import (FAMILLE_ECART_AU_PAIR,
                                            cible_d_ecart, cible_de_separation)
from src.core.knowledge.knowledge_base import KnowledgeBase
from src.core.knowledge.perimetre import perimetre_effectif
from src.core.knowledge.population import droits_par_identite
from src.core.knowledge.privileges import fragments_portes
from src.core.knowledge.separation import conflits, rang_de_severite
from src.core.mining.mouvement import Reglages, ecart_aux_pairs
from src.core.security.auth import User, require_permission_or_dev

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/identites", tags=["Identités"])

#: Lire des constats est un geste d'analyste, comme sur chacun des écrans dont
#: ils viennent : aucun n'est plus ouvert ici qu'il ne l'est là-bas.
LECTURE = "mining"

#: Bornes de chaînes venues de l'extérieur, pas des bornes métier.
IDENTIFIANT_MAX = 500
COLONNE_MAX = 200


def _detenus(loader: DataLoader, identite: str) -> Set[str]:
    habilitations = loader.habilitations
    if habilitations is None or habilitations.empty:
        return set()
    lignes = habilitations[habilitations[DataLoader.COL_USER_ID].astype(str) == identite]
    return set(lignes[DataLoader.COL_RIGHT_ID].astype(str))


def _ligne_d_identite(loader: DataLoader, identite: str):
    identites = loader.identities
    if (identites is None or getattr(identites, "empty", True)
            or DataLoader.COL_USER_ID not in identites.columns):
        return None
    lignes = identites[identites[DataLoader.COL_USER_ID].astype(str) == identite]
    return None if lignes.empty else lignes.iloc[0]


def _privileges(loader: DataLoader, ligne) -> Dict[str, Any]:
    """Le marqueur appliqué à ce compte, par la colonne déclarée et elle seule."""
    marqueur = loader.config.privileges
    colonne = marqueur.colonne or DataLoader.COL_USER_ID
    rendu = {"declare": marqueur.declare, "colonne": colonne,
             "colonne_absente": False, "fragments": []}
    if not marqueur.declare or ligne is None:
        return rendu
    if colonne not in ligne.index:
        # Une colonne déclarée puis absente de l'export : ne rien marquer, et
        # le dire. Se rabattre sur l'identifiant donnerait un résultat
        # crédible et faux.
        rendu["colonne_absente"] = True
        return rendu
    rendu["fragments"] = list(fragments_portes(ligne[colonne], marqueur))
    return rendu


def _referencies(loader: DataLoader) -> Set[str]:
    droits = loader.rights
    if droits is None or droits.empty or DataLoader.COL_RIGHT_ID not in droits.columns:
        return set()
    return set(droits[DataLoader.COL_RIGHT_ID].astype(str))


def _pairs(loader: DataLoader, kb: KnowledgeBase, identite: str,
           attribut: str) -> Dict[str, Any]:
    reglages = Reglages.depuis_la_configuration(loader.config)
    rendu: Dict[str, Any] = {"declare": bool(attribut), "attribut": attribut,
                             "reglages": {"groupe_min": reglages.groupe_min,
                                          "rarete_max_pct": reglages.rarete_max_pct,
                                          "typique_min_pct": reglages.typique_min_pct,
                                          "droits_min": reglages.droits_min}}
    if not attribut:
        return rendu
    detenus = droits_par_identite(loader.habilitations, DataLoader.COL_USER_ID,
                                  DataLoader.COL_RIGHT_ID)
    rendu.update(ecart_aux_pairs(identite, _groupes(loader, kb, attribut),
                                 detenus, reglages))
    # Chaque droit atypique dit s'il a été justifié, et sinon pourquoi une
    # justification en cours ne vaut pas : il reste affiché dans les deux cas.
    # Le retirer cacherait à un auditeur ce qui a été assumé.
    couvertes, inoperantes = etat_des_derogations(loader, kb, FAMILLE_ECART_AU_PAIR)
    for atypique in rendu["atypiques"]:
        cle = cible_d_ecart(identite, atypique["droit"])
        derogation = couvertes.get(cle)
        atypique["derogation"] = derogation.en_dict() if derogation else None
        atypique["derogation_inoperante"] = (None if derogation
                                             else inoperantes.get(cle))
    return rendu


def _separation(loader: DataLoader, kb: KnowledgeBase, identite: str,
                detenus: Set[str], catalogue, acquis) -> Dict[str, Any]:
    """Les règles qu'elle enfreint, avec la dérogation qui la couvre ou non."""
    regles = _resolues(loader, kb, catalogue)
    severites = loader.config.sod_severites
    roles = _roles_par_identite(acquis).get(identite, {})
    couvertes = _couvertures(loader, kb)
    inoperantes = _inoperantes(loader, kb)
    lignes = []
    for regle in regles:
        for conflit in conflits(regle, {identite: detenus}, {identite: roles}):
            document = {**conflit.en_dict(), "libelle": regle.libelle,
                        "severite": regle.severite,
                        "proprietaire": regle.proprietaire}
            document["derogation"] = _derogation_du_conflit(conflit, couvertes)
            document["derogation_inoperante"] = (
                None if document["derogation"] is not None
                else inoperantes.get(cible_de_separation(conflit.regle, identite)))
            lignes.append(document)
    # Ce qui reste à traiter d'abord, puis le plus grave : le même ordre que
    # l'écran des conflits.
    lignes.sort(key=lambda ligne: (ligne["derogation"] is not None,
                                   rang_de_severite(ligne["severite"], severites),
                                   ligne["regle"]))
    return {"regles_applicables": sum(1 for regle in regles if regle.applicable),
            "conflits": lignes}


@router.get("/{identite}/constats")
async def constats_d_une_identite(
    identite: str,
    attribut_pairs: str = Query("", max_length=COLONNE_MAX),
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    user: User = Depends(require_permission_or_dev(LECTURE)),
) -> Dict[str, Any]:
    """Ce que le produit constate sur cette personne, section par section."""
    if len(identite) > IDENTIFIANT_MAX:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail={"code": "identites.identifiant_trop_long",
                                    "params": {"max": IDENTIFIANT_MAX}})
    if attribut_pairs:
        identites = loader.identities
        colonnes = (list(identites.columns) if identites is not None
                    and not getattr(identites, "empty", True) else [])
        if attribut_pairs not in colonnes or attribut_pairs == DataLoader.COL_USER_ID:
            # Refusé plutôt que rendu vide, comme sur l'écran des droits
            # conservés : une section vide se lirait « rien d'atypique ».
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail={"code": "mouvement.attribut_inconnu",
                                        "params": {"attribut": attribut_pairs}})
    return await run_in_threadpool(_calculer, loader, kb, identite, attribut_pairs)


def _calculer(loader: DataLoader, kb: KnowledgeBase, identite: str,
              attribut: str) -> Dict[str, Any]:
    ligne = _ligne_d_identite(loader, identite)
    detenus = _detenus(loader, identite)
    if ligne is None and not detenus:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail={"code": "identites.inconnue",
                                    "params": {"identifiant": identite}})
    catalogue, acquis = _modele(loader, kb)
    referencies = _referencies(loader)
    return {
        "identite": identite,
        "referentiel": {
            # Détenue dans les habilitations, absente des identités : un
            # compte que personne ne sait rattacher à une personne.
            "connue": ligne is not None,
            "hors_perimetre": identite in perimetre_effectif(loader, kb),
            "droits_detenus": len(detenus),
            "referentiel_des_droits": bool(referencies),
        },
        "privileges": _privileges(loader, ligne),
        "hors_referentiel": hors_referentiel(detenus, referencies),
        "pairs": _pairs(loader, kb, identite, attribut),
        "roles_valides": len(catalogue),
        "roles": roles_de_l_identite(identite, acquis, detenus),
        "hors_modele": hors_modele(identite, acquis, detenus, kb.get_birth_rights()),
        "separation": _separation(loader, kb, identite, detenus, catalogue, acquis),
    }
