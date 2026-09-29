# Fichier : src/core/accessibilite/palette.py
"""La palette du produit, lue à sa source unique : la feuille des jetons.

Le contrat de contraste — quelle encre a le droit de s'écrire sur quelle
surface — était écrit dans un test, et n'existait donc qu'au moment où la
campagne tournait. Tant que la palette était figée, cela suffisait : elle ne
changeait que par une modification du code, et le test la gardait.

Un thème de workspace change la palette **à l'exécution**, sur un poste où
aucun test ne tourne. Le contrat doit alors être calculable par le produit
lui-même, pour qu'un thème qui rend un texte illisible soit refusé au
chargement plutôt que découvert en clientèle. Ce module est cette bascule : il
porte la résolution des jetons, le calcul WCAG, et la liste des paires
opposables. Le test de la palette d'origine et le validateur de thèmes lisent
désormais le même contrat, ce qui interdit qu'ils divergent.

Aucune couleur n'est écrite ici. Les valeurs viennent de `variables.css`, qui
reste le seul endroit du produit où une couleur d'interface est décidée.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from src.infrastructure.chemins import RACINE_PROJET

#: Feuille où vivent les jetons de couleur.
FEUILLE_DES_JETONS = RACINE_PROJET / "frontend" / "css" / "variables.css"

#: Les deux variantes d'affichage. Elles ne sont pas des thèmes clients : un
#: thème client se décline dans les deux.
VARIANTES: Tuple[str, ...] = ("dark", "light")

#: Seuils WCAG 2.1 AA, repris par le RGAA 4 (critères 3.2 et 3.3).
SEUIL_TEXTE = 4.5
SEUIL_COMPOSANT = 3.0

#: Un jeton peut en citer un autre. La chaîne est bornée pour qu'une citation
#: circulaire s'arrête au lieu de tourner.
PROFONDEUR_MAXIMALE = 8

MOTIF_COULEUR = re.compile(r"#[0-9a-fA-F]{6}")
MOTIF_RENVOI = re.compile(r"var\(--([\w-]+)\)")
MOTIF_DECLARATION = re.compile(r"--([\w-]+)\s*:\s*([^;]+);")

#: Surfaces sur lesquelles se pose du texte courant, à n'importe quel niveau
#: d'encre. Toute encre de l'échelle doit y être lisible.
SURFACES_DE_TEXTE: Tuple[str, ...] = (
    "bg-primary", "bg-secondary", "bg-tertiary", "bg-elevated",
    "card-bg", "input-bg", "table-header-bg",
)

#: Surfaces d'état — survol, sélection. Elles ne portent que du texte mis en
#: avant : les niveaux atténués n'y ont pas cours.
SURFACES_D_ETAT: Tuple[str, ...] = ("bg-hover", "bg-active", "table-row-hover")

ECHELLE_D_ENCRES: Tuple[str, ...] = (
    "text-primary", "text-secondary", "text-tertiary", "text-muted",
)
ENCRES_MISES_EN_AVANT: Tuple[str, ...] = ("text-primary", "text-secondary")

#: Familles d'accent. Chacune existe en deux jetons : l'aplat `--accent-…`,
#: qui porte du texte, et l'encre `--encre-…`, qui en est.
FAMILLES: Tuple[str, ...] = (
    "primary", "secondary", "success", "warning", "danger", "info",
)

#: Jeton portant le fond de la barre latérale. Sa valeur est un dégradé : les
#: deux arrêts sont lus dans la feuille plutôt que recopiés ici.
JETON_BARRE = "sidebar-bg"

#: Encres de la barre latérale. Elle est sombre dans les deux variantes et un
#: thème peut la repeindre : ses textes ne peuvent donc être jugés ni sur les
#: surfaces du thème, ni sur la rampe de gris — seulement sur son propre fond.
ENCRES_DE_LA_BARRE: Tuple[str, ...] = (
    "sidebar-encre", "sidebar-encre-lien", "sidebar-encre-attenuee",
    "sidebar-titre-de-section",
)

#: Fond de l'élément de navigation sélectionné, en deux arrêts. C'est la seule
#: surface de la barre qui ne soit pas son dégradé, et elle porte du texte.
SELECTION_DE_LA_BARRE: Tuple[str, ...] = (
    "sidebar-selection-debut", "sidebar-selection-fin",
)


class PaletteIllisible(RuntimeError):
    """La feuille des jetons ne présente pas la forme attendue."""


# --- lecture de la feuille -------------------------------------------------

def _bloc(source: str, selecteur: str) -> str:
    trouve = re.search(re.escape(selecteur) + r"\s*\{(.*?)\n\}", source, re.S)
    if not trouve:
        raise PaletteIllisible(f"bloc {selecteur} introuvable dans {FEUILLE_DES_JETONS.name}")
    return trouve.group(1)


def _declarations(texte: str) -> Dict[str, str]:
    return {nom: valeur.strip() for nom, valeur in MOTIF_DECLARATION.findall(texte)}


@lru_cache(maxsize=1)
def _tables() -> Tuple[Dict[str, str], Dict[str, Dict[str, str]]]:
    """Les déclarations de `:root` et de chaque variante, lues une fois."""
    source = FEUILLE_DES_JETONS.read_text(encoding="utf-8")
    racine = _declarations(_bloc(source, ":root"))
    variantes = {variante: _declarations(_bloc(source, f'[data-theme="{variante}"]'))
                 for variante in VARIANTES}
    return racine, variantes


def _resoudre(nom: str, table: Dict[str, str], racine: Dict[str, str],
              surcharge: Dict[str, str], profondeur: int = 0) -> Optional[str]:
    """Suit la chaîne des citations comme le ferait le navigateur.

    L'ordre est celui de la cascade telle que le produit la construit : une
    surcharge de thème est posée sur l'élément racine, donc elle gagne contre
    la variante, qui gagne elle-même contre `:root`.
    """
    valeur = surcharge.get(nom, table.get(nom, racine.get(nom)))
    if valeur is None or profondeur > PROFONDEUR_MAXIMALE:
        return None
    renvoi = MOTIF_RENVOI.fullmatch(valeur)
    if renvoi:
        return _resoudre(renvoi.group(1), table, racine, surcharge, profondeur + 1)
    return valeur if MOTIF_COULEUR.fullmatch(valeur) else None


def palette(surcharges: Optional[Dict[str, Dict[str, str]]] = None
            ) -> Dict[str, Dict[str, Optional[str]]]:
    """Résout chaque jeton en couleur, pour chaque variante.

    `surcharges` porte les jetons d'un thème client, par variante. Les jetons
    qu'il ne cite pas gardent la valeur d'origine : un thème habille, il ne
    reconstruit pas la feuille.
    """
    racine, variantes = _tables()
    surcharges = surcharges or {}
    resultat: Dict[str, Dict[str, Optional[str]]] = {}
    for variante, table in variantes.items():
        surcharge = surcharges.get(variante, {})
        noms = set(racine) | set(table) | set(surcharge)
        resultat[variante] = {
            nom: _resoudre(nom, table, racine, surcharge) for nom in noms
        }
    return resultat


@lru_cache(maxsize=1)
def jetons_colorables() -> Tuple[str, ...]:
    """Les jetons qu'un thème a le droit de redéfinir.

    Ce sont ceux que la feuille déclare dans **les deux** variantes et qui s'y
    résolvent en une couleur pleine. Tout le reste est hors de portée d'un
    thème, et c'est voulu : un dégradé, un voile translucide ou un mélange
    calculé ne se remplacent pas par un hexadécimal sans casser l'effet qu'ils
    produisent, et leur laisser la porte ouverte reviendrait à accepter une
    valeur arbitraire dans une déclaration CSS.

    La liste n'est écrite nulle part : elle est dérivée de la feuille, donc
    elle suit la palette sans qu'on ait à y penser.
    """
    _, variantes = _tables()
    resolue = palette()
    communs = set.intersection(*(set(table) for table in variantes.values()))
    return tuple(sorted(
        nom for nom in communs
        if all(resolue[variante].get(nom) for variante in VARIANTES)
    ))


def arrets_de_la_barre(resolue: Dict[str, Optional[str]]) -> Tuple[str, ...]:
    """Les jetons de couleur cités par le dégradé de la barre latérale.

    La barre est sombre dans les deux variantes : ses encres ne peuvent pas
    être jugées sur les surfaces du thème, mais sur son propre fond.
    """
    _, variantes = _tables()
    valeur = variantes[VARIANTES[0]].get(JETON_BARRE, "")
    arrets = tuple(nom for nom in MOTIF_RENVOI.findall(valeur) if resolue.get(nom))
    if not arrets:
        raise PaletteIllisible(
            f"le fond de la barre latérale n'est plus un dégradé de jetons ({JETON_BARRE})")
    return arrets


# --- calcul WCAG -----------------------------------------------------------

def luminance(couleur: str) -> float:
    canaux = [int(couleur[position:position + 2], 16) / 255 for position in (1, 3, 5)]
    lineaire = [canal / 12.92 if canal <= 0.03928 else ((canal + 0.055) / 1.055) ** 2.4
                for canal in canaux]
    return 0.2126 * lineaire[0] + 0.7152 * lineaire[1] + 0.0722 * lineaire[2]


def contraste(encre: str, fond: str) -> float:
    premiere, seconde = luminance(encre), luminance(fond)
    return (max(premiere, seconde) + 0.05) / (min(premiere, seconde) + 0.05)


# --- le contrat ------------------------------------------------------------

def exigences(resolue: Dict[str, Optional[str]]
              ) -> Tuple[Tuple[Sequence[str], Sequence[str], float], ...]:
    """Les paires encre/fond opposables, pour une variante résolue.

    Le contrat est ici, et nulle part ailleurs : le test qui garde la palette
    d'origine et le validateur qui juge un thème client le lisent tous deux à
    cet endroit.
    """
    return (
        (ECHELLE_D_ENCRES, SURFACES_DE_TEXTE, SEUIL_TEXTE),
        (ENCRES_MISES_EN_AVANT, SURFACES_D_ETAT, SEUIL_TEXTE),
        (tuple(f"encre-{famille}" for famille in FAMILLES), SURFACES_DE_TEXTE, SEUIL_TEXTE),
        (("border-focus",), SURFACES_DE_TEXTE, SEUIL_COMPOSANT),
        (ENCRES_DE_LA_BARRE, arrets_de_la_barre(resolue), SEUIL_TEXTE),
        (("sidebar-encre",), SELECTION_DE_LA_BARRE, SEUIL_TEXTE),
        (("pastille-encre",), ("pastille-fond",), SEUIL_TEXTE),
    )


def manquements(resolue: Dict[str, Optional[str]], encres: Iterable[str],
                fonds: Iterable[str], seuil: float) -> List[str]:
    """Les paires qui passent sous le seuil, nommées et chiffrées."""
    encres, fonds = tuple(encres), tuple(fonds)
    absents = [nom for nom in (*encres, *fonds) if not resolue.get(nom)]
    if absents:
        return [f"jetons non résolus : {', '.join(sorted(absents))}"]
    fautes = []
    for encre in encres:
        for fond in fonds:
            rapport = contraste(resolue[encre], resolue[fond])
            if rapport < seuil:
                fautes.append(
                    f"{encre} ({resolue[encre]}) sur {fond} ({resolue[fond]}) : "
                    f"{rapport:.2f}:1 < {seuil}")
    return fautes


def defauts_de_contraste(surcharges: Optional[Dict[str, Dict[str, str]]] = None
                         ) -> List[str]:
    """Tout ce qui, palette surchargée comprise, ne tient pas le contrat."""
    resolue = palette(surcharges)
    fautes = []
    for variante in VARIANTES:
        for encres, fonds, seuil in exigences(resolue[variante]):
            fautes.extend(f"{variante} : {faute}"
                          for faute in manquements(resolue[variante], encres, fonds, seuil))
    return fautes
