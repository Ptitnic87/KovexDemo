"""Consultation de la piste d'audit.

Aucune route n'écrit ni ne supprime : la piste s'alimente depuis les actions
qu'elle enregistre, et rien dans le produit ne permet d'en retirer une entrée.
Une piste qu'une interface peut vider n'a pas de valeur probante.

La lecture exige la permission `admin`. Un compte qui peut être audité ne
choisit pas ce que l'audit montre.
"""

import csv
import io
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from src.core.audit import Action, PisteAudit, get_piste_audit
from src.core.security.auth import User, require_permission_or_dev
from src.infrastructure.branding import PREFIXE_FICHIERS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audit", tags=["Piste d'audit"])

#: Nombre d'entrées rendues par page. Une piste se compte en dizaines de
#: milliers d'entrées : tout rendre figerait le navigateur.
TAILLE_PAGE_MAX = 500


def get_piste() -> PisteAudit:
    return get_piste_audit()


@router.get("")
async def lire_piste(
    acteur: Optional[str] = None,
    action: Optional[str] = None,
    workspace: Optional[str] = None,
    depuis: Optional[str] = None,
    jusqu_a: Optional[str] = None,
    recherche: Optional[str] = None,
    page: int = Query(1, ge=1),
    taille: int = Query(50, ge=1, le=TAILLE_PAGE_MAX),
    piste: PisteAudit = Depends(get_piste),
):
    """Entrées de la piste, filtrées et paginées, de la plus récente à la plus ancienne."""
    entrees = await run_in_threadpool(
        piste.lire, acteur, action, workspace, depuis, jusqu_a, recherche
    )
    debut = (page - 1) * taille
    tranche = entrees[debut:debut + taille]
    return {
        "total": len(entrees),
        "page": page,
        "taille": taille,
        "entrees": [
            {
                "sequence": e.sequence,
                "horodatage": e.horodatage,
                "acteur": e.acteur,
                "action": e.action,
                "objet_type": e.objet_type,
                "objet_id": e.objet_id,
                "workspace": e.workspace,
                "details": e.details,
            }
            for e in tranche
        ],
    }


@router.get("/actions")
async def lister_actions():
    """Codes d'action possibles, pour alimenter le filtre du client."""
    return {"actions": Action.toutes()}


@router.get("/acteurs")
async def lister_acteurs(piste: PisteAudit = Depends(get_piste)):
    """Comptes apparaissant dans la piste."""
    return {"acteurs": await run_in_threadpool(piste.acteurs)}


@router.get("/verification")
async def verifier_piste(piste: PisteAudit = Depends(get_piste)):
    """Constat d'intégrité de la chaîne d'empreintes.

    Rend un constat, jamais une erreur : une piste rompue est un fait à
    afficher à l'auditeur, pas une panne du service.
    """
    return await run_in_threadpool(piste.verifier)


@router.get("/export")
async def exporter_piste(
    acteur: Optional[str] = None,
    action: Optional[str] = None,
    workspace: Optional[str] = None,
    depuis: Optional[str] = None,
    jusqu_a: Optional[str] = None,
    recherche: Optional[str] = None,
    piste: PisteAudit = Depends(get_piste),
    utilisateur: User = Depends(require_permission_or_dev("admin")),
):
    """Export CSV de la piste filtrée.

    L'export est lui-même consigné : sortir des données de gouvernance est une
    action auditable, y compris quand elle porte sur la piste elle-même.
    """
    entrees = await run_in_threadpool(
        piste.lire, acteur, action, workspace, depuis, jusqu_a, recherche
    )

    tampon = io.StringIO()
    graveur = csv.writer(tampon, delimiter=";")
    graveur.writerow([
        "sequence", "horodatage", "acteur", "action",
        "objet_type", "objet_id", "workspace", "details",
    ])
    for e in entrees:
        graveur.writerow([
            e.sequence, e.horodatage, e.acteur, e.action,
            e.objet_type, e.objet_id, e.workspace,
            "; ".join(f"{c}={v}" for c, v in sorted(e.details.items())),
        ])

    await run_in_threadpool(
        piste.consigner,
        utilisateur.username, Action.EXPORT_PRODUIT,
        "audit", "", "", {"format": "csv", "lignes": len(entrees)},
    )

    contenu = "﻿" + tampon.getvalue()
    return StreamingResponse(
        io.BytesIO(contenu.encode("utf-8")),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition":
                f'attachment; filename="{PREFIXE_FICHIERS}_audit.csv"'
        },
    )
