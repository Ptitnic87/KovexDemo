# Fichier : src/api/routers/export_modele.py
"""Export du modèle de rôles : Excel pour retravailler, PDF pour diffuser.

Le produit savait montrer le modèle à l'écran, jamais le sortir. Or c'est le
livrable d'un comité de gouvernance : la liste des rôles métiers et
applicatifs, leurs droits, leurs porteurs, leur statut.

L'extrait est **filtrable**, et c'est ce qui le rend utilisable : personne ne
présente 8 000 droits en réunion, on présente ce qui concerne une application,
un métier ou une population. Les critères de filtrage identitaires viennent des
colonnes du fichier du client, jamais d'une liste écrite ici — les colonnes ne
sont pas connues à l'avance.

Les deux formats partent du même assemblage : un Excel et un PDF demandés le
même jour qui ne donneraient pas les mêmes comptes seraient l'un et l'autre
inutilisables.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from src.api.dependencies import get_data_loader, get_kb
from src.api.journal import Journal, get_journal
from src.api.routers.graph import ORIGINES, contexte_du_modele
from src.api.routers.rapport_modele import construire_rapport_modele
from src.core.audit import Action
from src.core.data.loader import DataLoader
from src.core.knowledge.knowledge_base import KnowledgeBase
from src.core.knowledge import modele_roles
from src.core.knowledge.modele_roles import Filtres, TYPES
from src.infrastructure.branding import PREFIXE_FICHIERS
from src.infrastructure.classeur_modele import construire_classeur
from src.infrastructure.i18n_manager import i18n

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/export/modele", tags=["Export du modèle"])

TYPE_XLSX = ("application/vnd.openxmlformats-officedocument"
             ".spreadsheetml.sheet")


def _liste(valeur: Optional[List[str]]) -> List[str]:
    """Aplatit une liste de paramètres, séparés par des virgules ou répétés."""
    if not valeur:
        return []
    return [element.strip() for brut in valeur
            for element in str(brut).split(",") if element.strip()]


def _valider(demandees: List[str], connues, code: str) -> List[str]:
    """Refuse une valeur inconnue plutôt que de l'ignorer.

    Ignorée, elle produirait un extrait qui ne contient pas ce qu'on croit
    avoir demandé — et un extrait faux qui ne se signale pas est pire qu'un
    refus.
    """
    inconnues = sorted(set(demandees) - set(connues))
    if inconnues:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": code, "params": {"valeurs": ", ".join(inconnues)}},
        )
    return demandees


def _filtres(origins, role_types, applications, identities,
             attribute, attribute_values) -> Filtres:
    origines = _valider(_liste(origins), ORIGINES, "export.unknown_origin") \
        or list(ORIGINES)
    types = _valider(_liste(role_types), TYPES, "export.unknown_role_type") \
        or list(TYPES)

    return Filtres(
        origines=tuple(origines),
        types=tuple(types),
        applications=set(_liste(applications)),
        identites=set(_liste(identities)),
        attribut=attribute or None,
        valeurs_attribut=set(_liste(attribute_values)),
    )


def _assembler(loader: DataLoader, kb: KnowledgeBase, filtres: Filtres,
               langue: str = "fr"):
    """Assemble le modèle, avec ce qui a changé depuis le dernier export.

    La borne est lue ici et pas plus bas : l'assemblage est le seul endroit qui
    voit à la fois les rôles et la date du dernier document produit.

    La langue ne sert qu'au libellé de repli du socle, tant que personne ne l'a
    nommé : un document allemand ne doit pas porter un nom français pour la
    seule ligne que le client n'a pas encore baptisée.
    """
    contexte = contexte_du_modele(loader, kb, loader.identities, filtres.origines)
    return modele_roles.assembler(contexte, loader.identities,
                                  DataLoader.COL_USER_ID, filtres,
                                  depuis_export=kb.dernier_export(),
                                  nom_socle=i18n.t("role.socle.default_name",
                                                   locale=langue))


def _horodatage_lisible(iso: Optional[str]) -> str:
    """Une date d'export dans un document, sans la précision d'une machine.

    Un horodatage ISO à la microseconde dans une feuille de périmètre se lit
    mal et n'apporte rien : la minute suffit à situer le document précédent.
    """
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(str(iso)).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(iso)


def _contexte_document(request: Request, journal: Journal,
                       dernier_export: Optional[str] = None) -> Dict[str, str]:
    """Provenance du document : workspace, client, et compte demandeur.

    L'auteur vient du jeton, jamais d'un en-tête que l'appelant contrôle : un
    document d'audit signé d'un nom fourni par le demandeur n'a aucune valeur.
    """
    infos = {}
    entete = request.headers.get("X-Workspace-Info", "")
    if entete:
        try:
            infos = json.loads(entete)
        except (ValueError, TypeError):
            logger.warning("En-tête X-Workspace-Info illisible, ignoré")

    return {
        "auteur": journal.acteur,
        "workspace": str(infos.get("name", "") or journal.workspace),
        "client": str(infos.get("client", "")),
        "environnement": str(infos.get("environment", "")),
        "dernier_export": _horodatage_lisible(dernier_export),
    }


def _traducteur(langue: str):
    def traduire(cle, params=None):
        return i18n.t(cle, locale=langue, **(params or {}))
    return traduire


def _nom_de_fichier(extension: str) -> str:
    horodatage = datetime.now().strftime("%Y%m%d-%H%M")
    return f"{PREFIXE_FICHIERS}_modele_roles_{horodatage}.{extension}"


# --------------------------------------------------------------- filtres


@router.get("/filtres")
async def filtres_disponibles(
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
) -> Dict[str, object]:
    """Ce sur quoi l'extrait peut être filtré, tel que les fichiers le portent.

    L'écran construit ses cases à cocher à partir de cette réponse. Écrire les
    attributs filtrables dans le code aurait proposé `fonction` ou
    `departement` à un client dont le fichier ne porte ni l'un ni l'autre.
    """
    return await run_in_threadpool(_decrire_filtres, loader, kb)


def _decrire_filtres(loader: DataLoader, kb: KnowledgeBase) -> Dict[str, object]:
    attributs = modele_roles.attributs_identite(loader.identities,
                                                DataLoader.COL_USER_ID)
    applications = []
    if not loader.applications.empty and DataLoader.COL_APP_ID in loader.applications.columns:
        applications = sorted(
            {str(v) for v in loader.applications[DataLoader.COL_APP_ID].dropna()})

    return {
        "origins": list(ORIGINES),
        "role_types": list(TYPES),
        "applications": applications,
        "attributes": [
            {"name": attribut,
             "values": modele_roles.valeurs_d_attribut(loader.identities, attribut)}
            for attribut in attributs
        ],
    }


# --------------------------------------------------------------- aperçu


@router.get("/apercu")
async def apercu(
    origins: Optional[List[str]] = Query(None),
    role_types: Optional[List[str]] = Query(None),
    applications: Optional[List[str]] = Query(None),
    identities: Optional[List[str]] = Query(None),
    attribute: Optional[str] = Query(None),
    attribute_values: Optional[List[str]] = Query(None),
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
) -> Dict[str, object]:
    """Ce que l'extrait contiendra, avant de le produire.

    Un filtre trop étroit produit un document vide, et on ne le découvre qu'en
    l'ouvrant. Les compteurs sont ceux de l'assemblage réel, pas une
    estimation : un aperçu qui ne correspondrait pas au fichier serait pire que
    pas d'aperçu du tout.
    """
    filtres = _filtres(origins, role_types, applications, identities,
                       attribute, attribute_values)
    modele = await run_in_threadpool(_assembler, loader, kb, filtres)

    totaux = modele.totaux
    return {
        "roles": totaux["roles"],
        "rights": totaux["droits"],
        "identities": totaux["identites"],
        "by_origin": {origine: totaux.get(f"origine_{origine}", 0)
                      for origine in ORIGINES},
        "by_type": {type_role: totaux.get(f"type_{type_role}", 0)
                    for type_role in TYPES},
        "filtered_members": sum(role.membres_masques for role in modele.roles),
    }


# ---------------------------------------------------------------- Excel


@router.get("/excel")
async def exporter_excel(
    request: Request,
    langue: str = Query("fr"),
    origins: Optional[List[str]] = Query(None),
    role_types: Optional[List[str]] = Query(None),
    applications: Optional[List[str]] = Query(None),
    identities: Optional[List[str]] = Query(None),
    attribute: Optional[str] = Query(None),
    attribute_values: Optional[List[str]] = Query(None),
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
) -> Response:
    """Modèle de rôles en classeur Excel, filtré selon la demande."""
    filtres = _filtres(origins, role_types, applications, identities,
                       attribute, attribute_values)
    modele = await run_in_threadpool(_assembler, loader, kb, filtres, langue)

    contenu = await run_in_threadpool(
        construire_classeur, modele, _traducteur(langue),
        _contexte_document(request, journal, kb.dernier_export()))

    # La borne bouge une fois le document produit, pas avant : un export qui
    # échoue ne doit pas faire croire au suivant que tout a été livré.
    await run_in_threadpool(kb.enregistrer_export)
    journal.consigner(Action.EXPORT_PRODUIT, "modele_roles", "",
                      {"format": "xlsx", "roles": len(modele.roles),
                       "nouveaux": modele.totaux["nouveaux"],
                       "modifies": modele.totaux["modifies"],
                       "filtres": filtres.description()})

    nom = _nom_de_fichier("xlsx")
    return Response(content=contenu, media_type=TYPE_XLSX,
                    headers={"Content-Disposition": f'attachment; filename="{nom}"'})


# ------------------------------------------------------------------ PDF


@router.get("/pdf")
async def exporter_pdf(
    request: Request,
    langue: str = Query("fr"),
    origins: Optional[List[str]] = Query(None),
    role_types: Optional[List[str]] = Query(None),
    applications: Optional[List[str]] = Query(None),
    identities: Optional[List[str]] = Query(None),
    attribute: Optional[str] = Query(None),
    attribute_values: Optional[List[str]] = Query(None),
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
) -> Response:
    """Modèle de rôles en PDF, pour diffusion."""
    filtres = _filtres(origins, role_types, applications, identities,
                       attribute, attribute_values)
    modele = await run_in_threadpool(_assembler, loader, kb, filtres, langue)

    try:
        contenu = await run_in_threadpool(
            construire_rapport_modele, modele, _traducteur(langue),
            _contexte_document(request, journal, kb.dernier_export()))
    except Exception as erreur:
        logger.error("Génération du PDF du modèle impossible : %s", erreur)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "report.generation_failed", "params": {}},
        )

    await run_in_threadpool(kb.enregistrer_export)
    journal.consigner(Action.EXPORT_PRODUIT, "modele_roles", "",
                      {"format": "pdf", "roles": len(modele.roles),
                       "nouveaux": modele.totaux["nouveaux"],
                       "modifies": modele.totaux["modifies"],
                       "filtres": filtres.description()})

    nom = _nom_de_fichier("pdf")
    return Response(content=contenu, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{nom}"'})
