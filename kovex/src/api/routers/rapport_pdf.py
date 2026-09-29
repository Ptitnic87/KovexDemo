"""Rapport de qualité des données en PDF.

Ce module remplace une génération qui n'en était pas une. La version
précédente assemblait une page HTML par concaténation de chaînes puis tentait
de la convertir avec `xhtml2pdf`, absent des dépendances : à l'exécution, le
service retombait silencieusement sur un fichier `.html` servi sous le nom
d'un rapport PDF. Elle limitait par ailleurs chaque liste à dix identifiants
et ne couvrait que trois anomalies sur douze.

Trois choix ici.

**reportlab plutôt qu'un moteur HTML.** Il est en Python pur, sans dépendance
système, ce qui compte sur un serveur isolé où l'on ne peut pas installer les
bibliothèques natives qu'exigent les convertisseurs HTML. Et il produit un PDF,
pas un fichier renommé.

**Aucune concaténation de HTML.** Les identifiants viennent des fichiers du
client : un droit nommé ``<b>`` ou contenant une balise cassait la mise en
page de la version précédente, et un identifiant plus hostile aurait pu y
injecter du contenu. Ici chaque valeur passe par un échappement avant d'entrer
dans un paragraphe.

**Tout, par défaut.** Un rapport d'audit qui annonce « 3 573 » et n'en liste
que dix est trompeur. La limite existe toujours — un référentiel pathologique
produirait des milliers de pages — mais elle est explicite, réglable par
l'appelant, et le document dit quand elle s'applique.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    CondPageBreak,
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

logger = logging.getLogger(__name__)

#: Colonnes d'identifiants par page de liste. Au-delà, les identifiants longs
#: se chevauchent sur une page A4.
COLONNES_LISTE = 3

#: Sévérités, de la plus grave à la moins grave. L'ordre du rapport suit la
#: sévérité : un auditeur lit le début.
ORDRE_SEVERITE = {"critical": 0, "warning": 1, "info": 2}


def _c(valeur: str) -> colors.Color:
    """Conservé pour les couleurs de sévérité, propres à ce rapport."""
    return mise_en_page.couleur(valeur)


COULEUR_SEVERITE = {nom: _c(valeur)
                    for nom, valeur in palette.SEVERITE_TEXTE.items()}
FOND_SEVERITE = {nom: _c(valeur)
                 for nom, valeur in palette.SEVERITE_FOND.items()}

# L'habillage — couleurs de base, styles, bandeau, pied de page — est partagé
# avec l'export du modèle de rôles. Recopié, il aurait divergé au premier
# ajustement : deux documents signés du même produit, avec deux nuances de
# bandeau.
ENCRE = mise_en_page.ENCRE
ENCRE_SECONDAIRE = mise_en_page.ENCRE_SECONDAIRE
ENCRE_DISCRETE = mise_en_page.ENCRE_DISCRETE
FOND_ALTERNE = mise_en_page.FOND_ALTERNE
FOND_ENTETE = mise_en_page.FOND_ENTETE
BORDURE = mise_en_page.BORDURE
ACCENT = mise_en_page.ACCENT
BANDEAU = mise_en_page.BANDEAU
SUR_BANDEAU = mise_en_page.SUR_BANDEAU

HAUTEUR_BANDEAU = mise_en_page.HAUTEUR_BANDEAU

#: Indicateurs du tableau de synthèse : (clé du compteur, clé de disponibilité).
#: Les douze contrôles y figurent, y compris ceux à zéro : un rapport d'audit
#: doit montrer ce qui a été vérifié, pas seulement ce qui a échoué.
INDICATEURS: List[Tuple[str, Optional[str]]] = [
    ("orphan_rights_count", None),
    ("orphan_users_count", None),
    ("broken_habs_count", None),
    ("incomplete_habs_count", None),
    ("unknown_app_refs_count", "unknown_app_refs"),
    ("unused_rights_count", "unused_rights"),
    ("rights_without_app_count", "rights_without_app"),
    ("unused_applications_count", "unused_applications"),
    ("empty_applications_count", "empty_applications"),
    ("duplicate_users_count", None),
    ("duplicate_rights_count", None),
    ("duplicate_applications_count", None),
]


def _styles() -> Dict[str, ParagraphStyle]:
    return mise_en_page.styles()


def _bandeau_de_titre(canevas, largeur: float, hauteur_page: float,
                      titre: str, sous_titre: str) -> None:
    mise_en_page.bandeau_de_titre(canevas, largeur, hauteur_page,
                                  titre, sous_titre)


def _tuiles_severite(comptes: Dict[str, int], traduire, styles) -> Table:
    """Rangée d'indicateurs : combien d'anomalies à chaque gravité.

    Trois nombres, pas un graphique : c'est un titre chiffré, et une forme
    graphique n'y ajouterait qu'un décor. Chaque tuile porte son libellé — une
    gravité signalée par la seule couleur disparaît à l'impression en noir et
    blanc et échappe à une partie des lecteurs.
    """
    severites = ("critical", "warning", "info")
    cellules = []
    for severite in severites:
        valeur = ParagraphStyle(
            f"valeur_{severite}", parent=styles["tuile_valeur"],
            textColor=COULEUR_SEVERITE[severite],
        )
        libelle = ParagraphStyle(
            f"libelle_{severite}", parent=styles["tuile_libelle"],
            textColor=COULEUR_SEVERITE[severite],
        )
        # Une cellule peut contenir plusieurs flowables : le nombre au-dessus,
        # son libellé en dessous.
        cellules.append([
            Paragraph(str(comptes.get(severite, 0)), valeur),
            Paragraph(escape(traduire(f"quality.severity.{severite}", {})), libelle),
        ])

    largeur = (A4[0] - 40 * mm) / len(severites)
    tableau = Table([cellules], colWidths=[largeur] * len(severites), hAlign="LEFT")

    regles = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        # Un filet de séparation de la couleur du fond : les tuiles restent
        # distinctes sans trait supplémentaire.
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    for indice, severite in enumerate(severites):
        regles += [
            ("BACKGROUND", (indice, 0), (indice, 0), FOND_SEVERITE[severite]),
            ("LINEABOVE", (indice, 0), (indice, 0), 2.5, COULEUR_SEVERITE[severite]),
        ]
    tableau.setStyle(TableStyle(regles))
    return tableau


def _pied_de_page(canevas, document, mention: str) -> None:
    mise_en_page.pied_de_page(canevas, document, mention)


def _tableau_identifiants(identifiants: List[str], style: ParagraphStyle) -> Table:
    """Dispose des identifiants en colonnes, pour tenir en un nombre de pages
    raisonnable sans les tronquer."""
    lignes = []
    for debut in range(0, len(identifiants), COLONNES_LISTE):
        tranche = identifiants[debut:debut + COLONNES_LISTE]
        cellules = [Paragraph(escape(str(valeur)), style) for valeur in tranche]
        cellules += [""] * (COLONNES_LISTE - len(cellules))
        lignes.append(cellules)

    largeur = (A4[0] - 40 * mm) / COLONNES_LISTE
    tableau = Table(lignes, colWidths=[largeur] * COLONNES_LISTE, repeatRows=0)
    tableau.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        # Une ligne sur deux teintée : sur des centaines d'identifiants
        # monospacés, c'est ce qui permet de suivre une ligne du regard.
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, FOND_ALTERNE]),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDURE),
    ]))
    return tableau


def construire_rapport(
    rapport: Dict[str, Any],
    traduire,
    contexte: Dict[str, str],
    limite_par_anomalie: int = 0,
) -> bytes:
    """Produit le PDF et rend ses octets.

    `traduire(cle, params)` est fourni par l'appelant : ce module ne connaît
    aucun libellé, conformément à la règle du produit — le serveur rend des
    clés, la traduction se fait avec le catalogue de la langue demandée.

    `limite_par_anomalie` à 0 signifie « aucune limite ». Toute troncature est
    annoncée dans le document.
    """
    styles = _styles()
    tampon = BytesIO()
    genere_le = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    titre_document = traduire("report.quality.title", {})
    sous_titre = " · ".join(filter(None, [
        contexte.get("client", ""), contexte.get("workspace", ""),
        contexte.get("environnement", ""),
    ]))

    document = SimpleDocTemplate(
        tampon, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=22 * mm,
        title=titre_document,
        author=NOM_PRODUIT,
    )

    elements: List[Any] = []

    # --- Contexte : qui, quoi, quand. Un rapport non daté et non signé n'a
    # aucune valeur dans un dossier d'audit.
    contexte_lignes = [
        (traduire("report.field.generated_at", {}), genere_le),
        (traduire("report.field.generated_by", {}), contexte.get("auteur", "")),
        (traduire("report.field.workspace", {}), contexte.get("workspace", "")),
        (traduire("report.field.analysed_at", {}), str(rapport.get("last_cleaned", ""))),
    ]
    tableau_contexte = Table(
        [[Paragraph(escape(etiquette), styles["etiquette"]),
          Paragraph(escape(valeur), styles["corps"])]
         for etiquette, valeur in contexte_lignes],
        colWidths=[52 * mm, None],
    )
    tableau_contexte.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements += [tableau_contexte, Spacer(1, 8 * mm)]

    # --- Combien d'anomalies, à quelle gravité. C'est la première question
    # que pose un lecteur ; elle mérite d'être en tête et non déduite du
    # tableau qui suit.
    comptes = {}
    for anomalie in rapport.get("issues_summary", []):
        severite = anomalie.get("severity", "info")
        comptes[severite] = comptes.get(severite, 0) + 1
    elements += [_tuiles_severite(comptes, traduire, styles), Spacer(1, 8 * mm)]

    # --- Synthèse : tous les contrôles, y compris ceux à zéro.
    elements.append(
        Paragraph(escape(traduire("report.section.summary", {})), styles["section"])
    )
    disponible = rapport.get("checks_available", {})
    style_entete = ParagraphStyle(
        "entete_tableau", parent=styles["corps"],
        fontName=palette.POLICE_GRASSE, textColor=SUR_BANDEAU,
    )
    lignes = [[
        Paragraph(escape(traduire("report.column.control", {})), style_entete),
        Paragraph(escape(traduire("report.column.count", {})), style_entete),
    ]]
    for cle_compteur, cle_disponibilite in INDICATEURS:
        calcule = disponible.get(cle_disponibilite, True) if cle_disponibilite else True
        valeur = (str(rapport.get(cle_compteur, 0)) if calcule
                  else traduire("report.value.not_checked", {}))
        lignes.append([
            Paragraph(escape(traduire(f"report.control.{cle_compteur}", {})), styles["corps"]),
            Paragraph(escape(valeur), styles["corps"]),
        ])

    tableau = Table(lignes, colWidths=[None, 32 * mm], repeatRows=1)
    tableau.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BANDEAU),
        ("TEXTCOLOR", (0, 0), (-1, 0), SUR_BANDEAU),
        # Une ligne sur deux teintée plutôt qu'un filet par ligne : le tableau
        # se lit sans quadrillage, qui ferait concurrence aux chiffres.
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, FOND_ALTERNE]),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, BORDURE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    elements += [tableau, Spacer(1, 4 * mm)]
    elements.append(
        Paragraph(escape(traduire("report.note.not_checked", {})), styles["note"])
    )

    # --- Détail : une section par anomalie constatée, liste complète.
    anomalies = sorted(
        rapport.get("issues_summary", []),
        key=lambda a: (ORDRE_SEVERITE.get(a.get("severity", "info"), 9), -a.get("count", 0)),
    )

    if not anomalies:
        elements += [
            Spacer(1, 8 * mm),
            Paragraph(escape(traduire("quality.no_major_issues", {})), styles["corps"]),
        ]

    for anomalie in anomalies:
        # Saut de page conditionnel plutôt que systématique : un saut à chaque
        # anomalie produisait huit pages presque vides sur un rapport qui en
        # méritait trois. On ne change de page que si la section n'a pas la
        # place de commencer, pour ne jamais laisser un intitulé seul en bas.
        elements.append(CondPageBreak(55 * mm))
        severite = anomalie.get("severity", "info")
        titre = ParagraphStyle(
            f"section_{severite}", parent=styles["section"],
            textColor=COULEUR_SEVERITE.get(severite, ENCRE),
            spaceBefore=0, spaceAfter=0, fontSize=11, leading=14,
        )
        # Pastille de gravité + intitulé : la couleur ne porte jamais seule
        # l'information, le mot est là.
        pastille = ParagraphStyle(
            f"pastille_{severite}", parent=styles["note"],
            fontName=palette.POLICE_GRASSE, textColor=SUR_BANDEAU,
            alignment=TA_CENTER, spaceBefore=0,
        )
        entete = Table(
            [[Paragraph(escape(traduire(f"quality.severity.{severite}", {})), pastille),
              Paragraph(escape(traduire(anomalie.get("description_key", ""),
                                        anomalie.get("description_params", {}))), titre)]],
            colWidths=[28 * mm, None],
        )
        entete.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), COULEUR_SEVERITE[severite]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (1, 0), (1, 0), 8),
        ]))
        elements.append(KeepTogether([entete, Spacer(1, 4 * mm)]))

        cle_liste = anomalie.get("list_key")
        identifiants = list(rapport.get(cle_liste) or []) if cle_liste else []

        if not identifiants:
            elements += [
                Paragraph(escape(traduire("report.no_identifiers", {})), styles["corps"]),
                Spacer(1, 9 * mm),
            ]
            continue

        total = len(identifiants)
        tronque = 0 < limite_par_anomalie < total
        if tronque:
            identifiants = identifiants[:limite_par_anomalie]

        elements.append(Paragraph(
            escape(traduire("report.identifiers_listed",
                            {"affiches": len(identifiants), "total": total})),
            styles["note"],
        ))
        if tronque:
            # Une troncature silencieuse est ce qui rendait le rapport
            # précédent trompeur : elle est ici annoncée dans le document.
            elements.append(Paragraph(
                escape(traduire("report.truncated", {"limite": limite_par_anomalie})),
                styles["note"],
            ))
        # L'espace après la liste sépare visuellement deux anomalies : sans
        # lui, l'intitulé suivant colle au tableau précédent et le document se
        # lit comme un bloc continu.
        elements += [Spacer(1, 3 * mm),
                     _tableau_identifiants(identifiants, styles["identifiant"]),
                     Spacer(1, 9 * mm)]

    mention = traduire("report.footer",
                       {"produit": NOM_PRODUIT, "date": genere_le,
                        "auteur": contexte.get("auteur", "")})
    def premiere_page(canevas, doc):
        _bandeau_de_titre(canevas, A4[0], A4[1], titre_document, sous_titre)
        _pied_de_page(canevas, doc, mention)

    # Deux gabarits : la première page réserve la hauteur du bandeau, les
    # suivantes retrouvent une marge haute normale. Un `topMargin` unique
    # laisserait quatre centimètres de blanc en tête de chaque page.
    cadre_titre = Frame(
        20 * mm, 22 * mm,
        A4[0] - 40 * mm, A4[1] - (HAUTEUR_BANDEAU + 12) * mm - 22 * mm,
        id="titre", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
    )
    cadre_courant = Frame(
        20 * mm, 22 * mm, A4[0] - 40 * mm, A4[1] - 18 * mm - 22 * mm,
        id="courant", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
    )
    document.addPageTemplates([
        PageTemplate(id="premiere", frames=[cadre_titre], onPage=premiere_page),
        PageTemplate(id="suivantes", frames=[cadre_courant],
                     onPage=lambda c, d: _pied_de_page(c, d, mention)),
    ])

    document.build(elements)
    return tampon.getvalue()
