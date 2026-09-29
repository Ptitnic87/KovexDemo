# Fichier : src/infrastructure/mise_en_page_pdf.py
"""Habillage commun des documents PDF du produit.

Le rapport de qualité des données portait seul son bandeau, ses styles et son
pied de page. Le second document — l'export du modèle de rôles — les aurait
recopiés, et les deux auraient divergé au premier ajustement : deux documents
signés du même produit, avec deux nuances de bandeau et deux tailles de titre.

Les couleurs viennent de `palette.py`, qui reprend les variables du thème de
l'interface. Un rapport imprimé doit se reconnaître comme venant du même
produit que l'écran d'où il a été demandé.

Ce module ne connaît **aucun libellé** : les textes lui sont fournis. Le
serveur rend des clés, la traduction se fait avec le catalogue de la langue
demandée.
"""

from __future__ import annotations

from typing import Dict

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm

from src.infrastructure import palette
from src.infrastructure.branding import NOM_PRODUIT


def couleur(valeur: str) -> colors.Color:
    """Couleur reportlab à partir d'un jeton hexadécimal du thème."""
    return colors.HexColor(valeur)


ENCRE = couleur(palette.ENCRE)
ENCRE_SECONDAIRE = couleur(palette.ENCRE_SECONDAIRE)
ENCRE_DISCRETE = couleur(palette.ENCRE_DISCRETE)
FOND_ALTERNE = couleur(palette.FOND_ALTERNE)
FOND_ENTETE = couleur(palette.FOND_ENTETE)
BORDURE = couleur(palette.BORDURE)
ACCENT = couleur(palette.ACCENT)
BANDEAU = couleur(palette.BANDEAU)
SUR_BANDEAU = couleur(palette.SUR_BANDEAU)

#: Hauteur du bandeau de première page, en millimètres.
HAUTEUR_BANDEAU = 26

#: Marge latérale commune à tous les documents.
MARGE = 20 * mm


def styles() -> Dict[str, ParagraphStyle]:
    """Styles de paragraphe, tirés des jetons du produit."""
    base = getSampleStyleSheet()
    return {
        "titre_bandeau": ParagraphStyle(
            "titre_bandeau", parent=base["Title"], fontName=palette.POLICE_GRASSE,
            fontSize=20, leading=24, textColor=SUR_BANDEAU, alignment=TA_LEFT,
            spaceAfter=0,
        ),
        "marque": ParagraphStyle(
            "marque", parent=base["Normal"], fontName=palette.POLICE_GRASSE,
            fontSize=9, textColor=SUR_BANDEAU, alignment=TA_LEFT,
        ),
        "section": ParagraphStyle(
            "section", parent=base["Heading2"], fontName=palette.POLICE_GRASSE,
            fontSize=13, textColor=ACCENT, spaceBefore=14, spaceAfter=8,
        ),
        "sous_section": ParagraphStyle(
            "sous_section", parent=base["Heading3"], fontName=palette.POLICE_GRASSE,
            fontSize=10.5, leading=13, textColor=ENCRE, spaceBefore=10,
            spaceAfter=4,
        ),
        "corps": ParagraphStyle(
            "corps", parent=base["Normal"], fontName=palette.POLICE,
            fontSize=9, leading=13, textColor=ENCRE,
        ),
        "etiquette": ParagraphStyle(
            "etiquette", parent=base["Normal"], fontName=palette.POLICE,
            fontSize=9, leading=13, textColor=ENCRE_SECONDAIRE,
        ),
        "identifiant": ParagraphStyle(
            "identifiant", parent=base["Normal"], fontName=palette.POLICE_MONO,
            fontSize=7, leading=9.5, textColor=ENCRE,
        ),
        "note": ParagraphStyle(
            "note", parent=base["Normal"], fontName=palette.POLICE,
            fontSize=8, leading=11, textColor=ENCRE_DISCRETE, spaceBefore=4,
        ),
        "tuile_valeur": ParagraphStyle(
            "tuile_valeur", parent=base["Normal"], fontName=palette.POLICE_GRASSE,
            fontSize=22, leading=25, alignment=TA_CENTER,
        ),
        "tuile_libelle": ParagraphStyle(
            "tuile_libelle", parent=base["Normal"], fontName=palette.POLICE,
            fontSize=8, leading=10, alignment=TA_CENTER,
        ),
    }


def bandeau_de_titre(canevas, largeur: float, hauteur_page: float,
                     titre: str, sous_titre: str) -> None:
    """Bandeau coloré en tête de première page.

    Dessiné sur le canevas plutôt que composé dans le flux : un aplat qui va
    d'un bord à l'autre ne peut pas être obtenu avec les marges du document.
    """
    hauteur = HAUTEUR_BANDEAU * mm
    canevas.saveState()
    canevas.setFillColor(BANDEAU)
    canevas.rect(0, hauteur_page - hauteur, largeur, hauteur, stroke=0, fill=1)

    canevas.setFillColor(SUR_BANDEAU)
    canevas.setFont(palette.POLICE_GRASSE, 9)
    canevas.drawString(MARGE, hauteur_page - 10 * mm, NOM_PRODUIT.upper())
    canevas.setFont(palette.POLICE_GRASSE, 17)
    canevas.drawString(MARGE, hauteur_page - 19 * mm, titre)
    if sous_titre:
        canevas.setFont(palette.POLICE, 9)
        canevas.drawRightString(largeur - MARGE, hauteur_page - 19 * mm, sous_titre)
    canevas.restoreState()


def pied_de_page(canevas, document, mention: str) -> None:
    """Numérotation et mention de bas de page.

    Un document d'audit sans pagination ne se cite pas : « page 14 » est ce qui
    permet de renvoyer à un passage précis.
    """
    canevas.saveState()
    canevas.setStrokeColor(BORDURE)
    canevas.setLineWidth(0.5)
    canevas.line(MARGE, 16 * mm, A4[0] - MARGE, 16 * mm)

    canevas.setFont(palette.POLICE, 7)
    canevas.setFillColor(ENCRE_DISCRETE)
    canevas.drawString(MARGE, 11 * mm, mention)
    canevas.drawRightString(A4[0] - MARGE, 11 * mm,
                            f"page {canevas.getPageNumber()}")
    canevas.restoreState()
