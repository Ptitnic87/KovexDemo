# Fichier : src/api/routers/rapport_modele.py
"""Export du modèle de rôles en PDF, pour diffusion.

Le classeur sert à retravailler, ce document sert à être lu et cité. D'où trois
partis pris :

- **les membres sont résumés.** Un rôle du référentiel réel compte 6 269
  porteurs ; les lister produirait une centaine de pages pour un seul rôle. Le
  document donne le compte exact et les premiers identifiants, et **annonce**
  la troncature. Le classeur, lui, ne tronque rien ;
- **les droits sont donnés en entier.** C'est la définition du rôle : la
  tronquer viderait le document de son objet ;
- **les filtres appliqués sont en tête.** Un extrait qui ne dit pas ce qu'il a
  filtré ne permet pas de savoir si un rôle absent a été écarté ou n'existe pas.

Comme le rapport de qualité, ce module ne connaît aucun libellé : `traduire`
lui est fourni, et l'habillage vient de `mise_en_page_pdf`, partagé entre les
deux documents.
"""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Callable, Dict, List
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    Frame,
    KeepTogether,
    PageTemplate,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from src.infrastructure import mise_en_page_pdf as mise_en_page
from src.infrastructure import palette
from src.infrastructure.branding import NOM_PRODUIT

#: Identifiants de membres cités par rôle. Au-delà, le document devient un
#: annuaire : le classeur est là pour ça.
MEMBRES_CITES = 12

#: Colonnes de la grille d'identifiants.
COLONNES_LISTE = 3

LARGEUR_UTILE = A4[0] - 2 * mise_en_page.MARGE


def _table_style_base() -> TableStyle:
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), mise_en_page.FOND_ENTETE),
        ("TEXTCOLOR", (0, 0), (-1, 0), mise_en_page.ENCRE_SECONDAIRE),
        ("FONTNAME", (0, 0), (-1, 0), palette.POLICE_GRASSE),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, mise_en_page.FOND_ALTERNE]),
        ("BOX", (0, 0), (-1, -1), 0.5, mise_en_page.BORDURE),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, mise_en_page.BORDURE),
    ])


def _tuiles(valeurs: List[tuple], styles) -> Table:
    """Rangée d'indicateurs de tête."""
    cellules = [[Paragraph(f'<font color="{palette.ACCENT}">{escape(str(v))}</font>',
                           styles["tuile_valeur"]) for _, v in valeurs],
                [Paragraph(escape(libelle), styles["tuile_libelle"])
                 for libelle, _ in valeurs]]
    largeur = LARGEUR_UTILE / max(len(valeurs), 1)
    tableau = Table(cellules, colWidths=[largeur] * len(valeurs))
    tableau.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, 0), 10),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 10),
        ("BOX", (0, 0), (-1, -1), 0.5, mise_en_page.BORDURE),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, mise_en_page.BORDURE),
        ("BACKGROUND", (0, 0), (-1, -1), mise_en_page.FOND_ALTERNE),
    ]))
    return tableau


def _grille_identifiants(identifiants: List[str], style) -> Table:
    lignes = []
    for debut in range(0, len(identifiants), COLONNES_LISTE):
        tranche = identifiants[debut:debut + COLONNES_LISTE]
        cellules = [Paragraph(escape(str(v)), style) for v in tranche]
        cellules += [""] * (COLONNES_LISTE - len(cellules))
        lignes.append(cellules)

    largeur = LARGEUR_UTILE / COLONNES_LISTE
    tableau = Table(lignes, colWidths=[largeur] * COLONNES_LISTE)
    tableau.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1),
         [colors.white, mise_en_page.FOND_ALTERNE]),
        ("BOX", (0, 0), (-1, -1), 0.5, mise_en_page.BORDURE),
    ]))
    return tableau


def construire_rapport_modele(modele, traduire: Callable[..., str],
                              contexte: Dict[str, str]) -> bytes:
    """Produit le PDF du modèle et rend ses octets."""
    t = lambda cle, params=None: traduire(cle, params or {})
    styles = mise_en_page.styles()
    tampon = BytesIO()

    sous_titre = " · ".join(filter(None, [
        contexte.get("client", ""), contexte.get("workspace", ""),
        contexte.get("environnement", ""),
    ]))
    mention = " · ".join(filter(None, [
        NOM_PRODUIT,
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        contexte.get("auteur", ""),
    ]))

    document = SimpleDocTemplate(
        tampon, pagesize=A4,
        leftMargin=mise_en_page.MARGE, rightMargin=mise_en_page.MARGE,
        topMargin=18 * mm, bottomMargin=22 * mm,
        title=t("export.model.title"), author=NOM_PRODUIT,
    )

    cadre_premiere = Frame(
        mise_en_page.MARGE,
        22 * mm,
        LARGEUR_UTILE,
        A4[1] - (mise_en_page.HAUTEUR_BANDEAU * mm) - 30 * mm,
        id="premiere",
    )
    cadre_suite = Frame(mise_en_page.MARGE, 22 * mm, LARGEUR_UTILE,
                        A4[1] - 40 * mm, id="suite")

    document.addPageTemplates([
        PageTemplate(
            id="premiere", frames=[cadre_premiere],
            onPage=lambda c, d: (
                mise_en_page.bandeau_de_titre(c, A4[0], A4[1],
                                              t("export.model.title"), sous_titre),
                mise_en_page.pied_de_page(c, d, mention))),
        PageTemplate(
            id="suite", frames=[cadre_suite],
            onPage=lambda c, d: mise_en_page.pied_de_page(c, d, mention)),
    ])

    contenu: List[Any] = []
    contenu += _synthese(modele, t, styles)
    contenu += _perimetre(modele, t, styles)
    contenu += _recapitulatif(modele, t, styles)
    contenu += _fiches(modele, t, styles)

    document.build(contenu)
    return tampon.getvalue()


def _synthese(modele, t, styles) -> List[Any]:
    totaux = modele.totaux
    return [
        Spacer(1, 4 * mm),
        _tuiles([
            (t("export.scope.total_roles"), totaux["roles"]),
            (t("export.scope.total_rights"), totaux["droits"]),
            (t("export.scope.total_identities"), totaux["identites"]),
            # Ce que le destinataire n'a pas encore reçu, et ce qu'il a reçu
            # autrement : c'est cela qu'il doit traiter, pas le reste.
            (t("export.scope.new_roles"), totaux["nouveaux"]),
            (t("export.scope.changed_roles"), totaux["modifies"]),
        ], styles),
        Spacer(1, 4 * mm),
    ]


def _perimetre(modele, t, styles) -> List[Any]:
    lignes = [[Paragraph(f"<b>{escape(t('export.column.criterion'))}</b>", styles["corps"]),
               Paragraph(f"<b>{escape(t('export.column.value'))}</b>", styles["corps"])]]

    for entree in modele.filtres.description():
        libelle = t(f"export.filter.{entree['critere']}")
        if entree["critere"] == "attribute":
            libelle = f"{libelle} · {entree['attribut']}"
        valeurs = entree["valeurs"]
        if entree["critere"] in ("origins", "role_types"):
            prefixe = ("graph.origin." if entree["critere"] == "origins"
                       else "export.role_type.")
            valeurs = [t(prefixe + str(v)) for v in valeurs]
        lignes.append([
            Paragraph(escape(libelle), styles["etiquette"]),
            Paragraph(escape(", ".join(str(v) for v in valeurs)), styles["corps"]),
        ])

    tableau = Table(lignes, colWidths=[LARGEUR_UTILE * 0.32, LARGEUR_UTILE * 0.68])
    tableau.setStyle(_table_style_base())

    return [Paragraph(escape(t("export.model.scope_section")), styles["section"]),
            tableau]


def _recapitulatif(modele, t, styles) -> List[Any]:
    entetes = [t("export.column.name"), t("export.column.role_type"),
               t("export.column.status"), t("export.column.right_count"),
               t("export.column.member_count")]
    lignes = [[Paragraph(f"<b>{escape(e)}</b>", styles["corps"]) for e in entetes]]

    for role in modele.roles:
        lignes.append([
            Paragraph(escape(role.nom or role.id), styles["corps"]),
            Paragraph(escape(t(f"export.role_type.{role.type_role}")), styles["corps"]),
            Paragraph(escape(t(f"graph.origin.{role.origine}")), styles["corps"]),
            Paragraph(str(len(role.droits)), styles["corps"]),
            Paragraph(str(role.membres_total), styles["corps"]),
        ])

    largeurs = [LARGEUR_UTILE * p for p in (0.34, 0.16, 0.20, 0.15, 0.15)]
    tableau = Table(lignes, colWidths=largeurs, repeatRows=1)
    tableau.setStyle(_table_style_base())

    return [Paragraph(escape(t("export.model.summary_section")), styles["section"]),
            tableau]


def _fiches(modele, t, styles) -> List[Any]:
    contenu: List[Any] = [
        Paragraph(escape(t("export.model.detail_section")), styles["section"])]

    if not modele.roles:
        contenu.append(Paragraph(escape(t("export.model.empty")), styles["note"]))
        return contenu

    for role in modele.roles:
        bloc: List[Any] = [
            Paragraph(escape(role.nom or role.id), styles["sous_section"]),
            Paragraph(escape(role.id), styles["note"]),
        ]
        if role.description:
            bloc.append(Paragraph(escape(role.description), styles["corps"]))

        etiquettes = [
            t(f"export.role_type.{role.type_role}"),
            t(f"graph.origin.{role.origine}"),
            t("export.model.right_total", {"count": len(role.droits)}),
            t("export.model.member_total", {"count": role.membres_total}),
        ]
        if role.evolution:
            # Le même rôle dans une version différente n'est pas un rôle neuf :
            # le dire évite le doublon dans l'IGA du destinataire.
            etiquettes.append(t("revue.version", {"version": role.version}))
            etiquettes.append(t(f"export.change.{role.evolution}"))
        bloc.append(Paragraph(escape(" · ".join(etiquettes)), styles["etiquette"]))

        if role.applications:
            bloc.append(Paragraph(escape(
                f"{t('export.column.applications')} : "
                f"{', '.join(role.applications)}"), styles["corps"]))

        # Les droits en entier : c'est la définition du rôle.
        bloc.append(Spacer(1, 2 * mm))
        bloc.append(Paragraph(escape(t("export.model.rights_heading")), styles["etiquette"]))
        bloc.append(_grille_identifiants(role.droits, styles["identifiant"]))

        cites = role.membres[:MEMBRES_CITES]
        bloc.append(Spacer(1, 2 * mm))
        bloc.append(Paragraph(escape(t("export.model.members_heading")),
                              styles["etiquette"]))
        if cites:
            bloc.append(_grille_identifiants(cites, styles["identifiant"]))
        else:
            # Un intitulé suivi de rien se lit comme un défaut d'affichage.
            # Et le fait est une information de gouvernance à part entière :
            # un rôle validé que personne ne détient est un rôle mort.
            bloc.append(Paragraph(escape(t("export.model.no_member")),
                                  styles["note"]))
        if len(role.membres) > len(cites):
            # Toute troncature est annoncée : un document qui affiche « 6 269 »
            # et n'en montre que douze sans le dire est trompeur.
            bloc.append(Paragraph(escape(t("export.model.members_truncated", {
                "shown": len(cites), "total": len(role.membres)})), styles["note"]))
        if role.membres_masques:
            bloc.append(Paragraph(escape(t("export.model.members_filtered", {
                "count": role.membres_masques})), styles["note"]))

        bloc.append(Spacer(1, 4 * mm))
        # Une fiche courte reste d'un seul tenant : un rôle coupé en deux ne se
        # cite pas facilement. Une fiche longue — un rôle à 73 droits existe
        # dans le référentiel réel — doit au contraire pouvoir se répartir,
        # sinon reportlab la pousse indéfiniment.
        if len(role.droits) <= 30:
            contenu.append(KeepTogether(bloc))
        else:
            contenu.extend(bloc)

    return contenu
