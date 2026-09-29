# src/api/routers/data_quality_exports.py
"""
Routeur Data Quality - VERSION ULTRA-PREMIUM
PDF professionnel avec branding complet
"""

import json
import tempfile

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from src.api.dependencies import get_data_loader
from src.api.journal import Journal, get_journal
from src.api.routers.rapport_pdf import construire_rapport
from src.core.audit import Action
from src.core.data.loader import DataLoader
from src.infrastructure.branding import PREFIXE_FICHIERS
from src.infrastructure import palette
from src.infrastructure.i18n_manager import i18n
from datetime import datetime, timezone
import os
import logging
import traceback
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/data-quality",
    tags=["Data Quality"]
)


#: Contrôles portés par la synthèse, dans l'ordre de gravité décroissante.
#: Chaque entrée : clé du compteur, gravité, et clé de disponibilité — un
#: contrôle que la configuration des fichiers ne permet pas de calculer ne
#: doit pas être exporté à zéro, un zéro dans un rapport d'audit se lit
#: « vérifié, aucune anomalie ».
CONTROLES = (
    ("orphan_rights_count", "critical", None),
    ("orphan_users_count", "critical", None),
    ("broken_habs_count", "critical", None),
    ("unknown_app_refs_count", "critical", "unknown_app_refs"),
    ("unused_rights_count", "warning", "unused_rights"),
    ("rights_without_app_count", "warning", "rights_without_app"),
    ("unused_applications_count", "warning", "unused_applications"),
    ("empty_applications_count", "info", "empty_applications"),
    ("forest_users_count", "warning", None),
)

#: Feuilles d'identifiants : clé de la liste, clé du nom d'onglet, et clé du
#: libellé de la colonne d'identifiants.
FEUILLES = (
    ("orphan_users_list", "report.sheet.orphan_users", "ID_utilisateur"),
    ("orphan_rights_list", "report.sheet.orphan_rights", "ID_droit"),
    ("unknown_app_refs_list", "report.sheet.unknown_app_refs", "ID_application"),
    ("unused_rights_list", "report.sheet.unused_rights", "ID_droit"),
    ("rights_without_app_list", "report.sheet.rights_without_app", "ID_droit"),
    ("unused_applications_list", "report.sheet.unused_applications", "ID_application"),
    ("empty_applications_list", "report.sheet.empty_applications", "ID_application"),
    ("forest_users_list", "report.sheet.forest_users", "ID_utilisateur"),
)

#: Longueur maximale d'un nom d'onglet imposée par le format Excel.
LONGUEUR_ONGLET = 31


def _teinte(couleur: str) -> str:
    """Convertit une couleur `#rrggbb` de la palette au format d'openpyxl."""
    return couleur.lstrip("#").upper()


def _nom_d_onglet(libelle: str, deja_pris: set) -> str:
    r"""Nom d'onglet valide et unique.

    Excel refuse les noms de plus de 31 caractères et les caractères
    ``[]:*?/\``. Les libellés viennent des catalogues : une traduction plus
    longue que prévu ne doit pas faire échouer l'export entier.

    La chaîne est brute : sans cela, ``\``` est une séquence d'échappement
    invalide, que Python signale déjà et refusera un jour.
    """
    propre = "".join(" " if caractere in "[]:*?/\\" else caractere
                     for caractere in libelle).strip()
    propre = (propre or "?")[:LONGUEUR_ONGLET]
    candidat, suffixe = propre, 2
    while candidat.lower() in deja_pris:
        marque = f" ({suffixe})"
        candidat = propre[:LONGUEUR_ONGLET - len(marque)] + marque
        suffixe += 1
    deja_pris.add(candidat.lower())
    return candidat


def _construire_classeur(rapport: dict, traduire, contexte: dict, chemin: str) -> None:
    """Écrit le classeur de qualité des données.

    Les libellés passaient tous par des chaînes françaises écrites ici, et les
    couleurs par des codes hexadécimaux sans rapport avec le thème : le PDF et
    le classeur décrivaient le même rapport en deux vocabulaires et deux
    palettes. Les deux emploient désormais les mêmes clés de traduction et la
    même palette.
    """
    classeur = openpyxl.Workbook()
    feuille = classeur.active
    noms_pris = set()
    feuille.title = _nom_d_onglet(traduire("report.sheet.summary"), noms_pris)

    blanc = _teinte(palette.SUR_BANDEAU)
    entete = Font(bold=True, color=blanc)
    fond_entete = PatternFill(start_color=_teinte(palette.FOND_ENTETE),
                              end_color=_teinte(palette.FOND_ENTETE),
                              fill_type="solid")

    feuille["A1"] = traduire("report.quality.title")
    feuille["A1"].font = Font(size=18, bold=True, color=blanc)
    feuille["A1"].fill = PatternFill(start_color=_teinte(palette.BANDEAU),
                                     end_color=_teinte(palette.BANDEAU),
                                     fill_type="solid")
    feuille["A1"].alignment = Alignment(horizontal="center")
    feuille.merge_cells("A1:C1")

    # Le même cartouche que le rapport PDF : sans lui, un classeur détaché de
    # son contexte ne dit ni qui l'a produit ni sur quel référentiel.
    ligne = 2
    for cle, valeur in (
        ("report.field.generated_at",
         datetime.now(timezone.utc).astimezone().isoformat(timespec="minutes")),
        ("report.field.generated_by", contexte.get("auteur", "")),
        ("report.field.workspace", contexte.get("workspace", "")),
        ("report.field.analysed_at", str(rapport.get("last_cleaned", ""))),
    ):
        feuille[f"A{ligne}"] = traduire(cle)
        feuille[f"A{ligne}"].font = Font(bold=True)
        feuille[f"B{ligne}"] = valeur
        ligne += 1

    ligne += 1
    for colonne, cle in (("A", "report.column.control"),
                         ("B", "report.column.count"),
                         ("C", "report.column.severity")):
        cellule = feuille[f"{colonne}{ligne}"]
        cellule.value = traduire(cle)
        cellule.font = entete
        cellule.fill = fond_entete
        cellule.font = Font(bold=True)
    ligne += 1

    disponible = rapport.get("checks_available", {})
    non_verifie = traduire("report.value.not_checked")
    for cle_compteur, severite, cle_disponibilite in CONTROLES:
        calcule = cle_disponibilite is None or disponible.get(cle_disponibilite, True)
        feuille[f"A{ligne}"] = traduire(f"report.control.{cle_compteur}")
        feuille[f"B{ligne}"] = rapport.get(cle_compteur, 0) if calcule else non_verifie
        cellule = feuille[f"C{ligne}"]
        cellule.value = traduire(f"quality.severity.{severite}")
        # La gravité est portée par le mot autant que par la couleur : un
        # aplat seul disparaît à l'impression en noir et blanc.
        cellule.fill = PatternFill(
            start_color=_teinte(palette.SEVERITE_FOND[severite]),
            end_color=_teinte(palette.SEVERITE_FOND[severite]), fill_type="solid")
        cellule.font = Font(bold=True, color=_teinte(palette.SEVERITE_TEXTE[severite]))
        ligne += 1

    ligne += 1
    feuille[f"A{ligne}"] = traduire("report.note.not_checked")

    feuille.column_dimensions["A"].width = 52
    feuille.column_dimensions["B"].width = 14
    feuille.column_dimensions["C"].width = 16

    for cle_liste, cle_onglet, colonne in FEUILLES:
        identifiants = rapport.get(cle_liste, [])
        if not identifiants:
            continue
        onglet = classeur.create_sheet(_nom_d_onglet(traduire(cle_onglet), noms_pris))
        onglet["A1"] = traduire("report.total", {"count": len(identifiants)})
        onglet["A1"].font = Font(bold=True)
        onglet["A3"] = traduire("report.column.identifier")
        # Le nom de la colonne du référentiel n'est pas traduit : c'est celui
        # du fichier du client.
        onglet["B3"] = colonne
        for cellule in (onglet["A3"], onglet["B3"]):
            cellule.font = Font(bold=True)
            cellule.fill = fond_entete
        # Liste complète : la version précédente s'arrêtait à 100 identifiants
        # sans le dire. Un rapport d'audit annonçant « Total : 3573 » et n'en
        # listant que 100 est trompeur.
        for indice, identifiant in enumerate(identifiants, start=1):
            onglet[f"A{indice + 3}"] = indice
            onglet[f"B{indice + 3}"] = str(identifiant)
        onglet.column_dimensions["A"].width = 8
        onglet.column_dimensions["B"].width = 40

    classeur.save(chemin)


@router.get("/export/excel")
async def export_excel(
    request: Request,
    langue: str = Query("fr"),
    loader: DataLoader = Depends(get_data_loader),
    journal: Journal = Depends(get_journal),
):
    """Exporte le rapport de qualité des données au format Excel.

    Le classeur était écrit dans `output/`, sous un nom horodaté à la minute :
    deux exports rapprochés — deux workspaces, deux analystes — se marchaient
    dessus, et les fichiers s'accumulaient sur un serveur que personne ne vient
    nettoyer. Il est désormais construit dans un fichier temporaire propre à la
    requête, puis supprimé une fois la réponse envoyée.

    Il est produit dans la langue demandée, comme le PDF, et consigné dans la
    piste d'audit, comme lui : sortir la liste des anomalies d'un référentiel
    est une action qui doit laisser une trace.
    """
    horodatage = datetime.now().strftime("%Y%m%d-%H%M")
    nom = f"{PREFIXE_FICHIERS}_qualite_donnees_{horodatage}.xlsx"
    descripteur, chemin = tempfile.mkstemp(
        suffix=".xlsx", prefix=f"{PREFIXE_FICHIERS}-qualite-")
    os.close(descripteur)

    try:
        rapport = await run_in_threadpool(loader.get_cleaning_status)
        contexte = _contexte(request, journal)

        def traduire(cle, params=None):
            return i18n.t(cle, locale=langue, **(params or {}))

        await run_in_threadpool(_construire_classeur, rapport, traduire, contexte, chemin)

        journal.consigner(
            Action.EXPORT_PRODUIT, "data_quality", "",
            {"format": "excel",
             "anomalies": len(rapport.get("issues_summary", []))},
        )

        return FileResponse(
            chemin,
            media_type=('application/vnd.openxmlformats-officedocument'
                        '.spreadsheetml.sheet'),
            filename=nom,
            background=BackgroundTask(_supprimer, chemin),
        )

    except Exception as erreur:
        # Le message d'exception était renvoyé au client, en texte brut, avec
        # un code 500 : il décrit l'arborescence du serveur à qui sait le
        # provoquer. Il reste au journal.
        _supprimer(chemin)
        logger.error("Génération du classeur impossible : %s", erreur)
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail={"code": "report.generation_failed", "params": {}},
        )


def _contexte(request: Request, journal: Journal) -> dict:
    """Cartouche du document : qui produit, sur quel workspace.

    L'auteur vient du jeton, jamais d'un en-tête que l'appelant contrôle.
    """
    workspace_info = {}
    entete = request.headers.get("X-Workspace-Info", "")
    if entete:
        try:
            workspace_info = json.loads(entete)
        except (ValueError, TypeError):
            # Un en-tête illisible ne doit pas empêcher de produire le
            # rapport : le contexte est un confort, les données sont l'objet.
            logger.warning("En-tête X-Workspace-Info illisible, ignoré")

    return {
        "auteur": journal.acteur,
        "workspace": str(workspace_info.get("name", "") or journal.workspace),
        "client": str(workspace_info.get("client", "")),
        "environnement": str(workspace_info.get("environment", "")),
    }


def _supprimer(chemin: str) -> None:
    """Efface le fichier temporaire, sans faire échouer la réponse partie."""
    try:
        os.unlink(chemin)
    except OSError:  # pragma: no cover - dépend du système de fichiers
        logger.warning("Fichier temporaire non supprimé : %s", chemin)


@router.get("/export/pdf")
async def export_pdf(
    request: Request,
    langue: str = Query("fr"),
    limite_par_anomalie: int = Query(
        0, ge=0,
        description="Nombre maximal d'identifiants listés par anomalie. "
                    "0 = aucune limite, ce qui est le défaut.",
    ),
    loader: DataLoader = Depends(get_data_loader),
    journal: Journal = Depends(get_journal),
):
    """Rapport de qualité des données, en PDF.

    Le rapport couvre **tous** les contrôles, y compris ceux à zéro et ceux
    qui n'ont pas pu être calculés, et liste **tous** les identifiants de
    chaque anomalie. La version précédente n'en montrait que dix par anomalie,
    ne couvrait que trois anomalies sur douze, et — `xhtml2pdf` n'ayant jamais
    figuré dans les dépendances — servait en réalité un fichier HTML sous le
    nom d'un rapport PDF.
    """
    rapport = await run_in_threadpool(loader.get_cleaning_status)

    # L'auteur vient du jeton, jamais d'un en-tête que l'appelant contrôle.
    # La version précédente signait « Administrateur » en dur, quel que soit
    # le compte : un rapport d'audit signé d'un nom inventé n'a aucune valeur.
    contexte = _contexte(request, journal)

    def traduire(cle, params=None):
        return i18n.t(cle, locale=langue, **(params or {}))

    try:
        contenu = await run_in_threadpool(
            construire_rapport, rapport, traduire, contexte, limite_par_anomalie
        )
    except Exception as erreur:
        logger.error("Génération du rapport PDF impossible : %s", erreur)
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail={"code": "report.generation_failed", "params": {}},
        )

    journal.consigner(
        Action.EXPORT_PRODUIT, "data_quality", "",
        {"format": "pdf", "anomalies": len(rapport.get("issues_summary", []))},
    )

    horodatage = datetime.now().strftime("%Y%m%d-%H%M")
    nom = f"{PREFIXE_FICHIERS}_qualite_donnees_{horodatage}.pdf"
    return Response(
        content=contenu,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nom}"'},
    )
