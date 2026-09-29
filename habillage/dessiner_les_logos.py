#!/usr/bin/env python3
# Fichier : habillage/dessiner_les_logos.py
"""Les logos des clients fictifs de la démonstration, dessinés ici.

Des formes simples, dessinées par ce script : aucune marque existante n'est
reproduite, aucune police n'est embarquée. Le rendu est fait à quatre fois la
taille puis réduit, pour des bords lissés. Déterministe : relancer le script
redonne les mêmes fichiers.

    python habillage/dessiner_les_logos.py
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Callable, Dict, Tuple

from PIL import Image, ImageChops, ImageDraw

ICI = Path(__file__).resolve().parent
TAILLE = 256
ECHELLE = 4
BLANC = (255, 255, 255, 255)
OR = (212, 175, 55, 255)

Couleur = Tuple[int, int, int, int]


def _hex(code: str) -> Couleur:
    code = code.lstrip("#")
    return (int(code[0:2], 16), int(code[2:4], 16), int(code[4:6], 16), 255)


def _fond(d: ImageDraw.ImageDraw, s: int, couleur: Couleur) -> None:
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.22), fill=couleur)


def alvea(d: ImageDraw.ImageDraw, s: int) -> None:
    """Assurance : un bouclier, et un chevron qui monte."""
    c = s / 2
    bouclier = [(c, s * 0.16), (s * 0.78, s * 0.28), (s * 0.74, s * 0.58),
                (c, s * 0.86), (s * 0.26, s * 0.58), (s * 0.22, s * 0.28)]
    d.polygon(bouclier, outline=BLANC, width=int(s * 0.05))
    d.line([(s * 0.36, s * 0.62), (c, s * 0.36), (s * 0.64, s * 0.62)],
           fill=BLANC, width=int(s * 0.06), joint="curve")


def helior(d: ImageDraw.ImageDraw, s: int) -> None:
    """Énergie : un soleil levant sur un horizon."""
    c = s / 2
    r = s * 0.16
    cy = s * 0.56
    d.pieslice((c - r, cy - r, c + r, cy + r), 180, 360, fill=BLANC)
    for i in range(1, 6):
        angle = math.pi + i * math.pi / 6
        x1, y1 = c + math.cos(angle) * s * 0.23, cy + math.sin(angle) * s * 0.23
        x2, y2 = c + math.cos(angle) * s * 0.33, cy + math.sin(angle) * s * 0.33
        d.line([(x1, y1), (x2, y2)], fill=BLANC, width=int(s * 0.045))
    d.rectangle((s * 0.18, cy, s * 0.82, cy + s * 0.05), fill=BLANC)
    d.rectangle((s * 0.30, cy + s * 0.12, s * 0.70, cy + s * 0.16), fill=BLANC)


def marelle(d: ImageDraw.ImageDraw, s: int) -> None:
    """Commerce : les cases d'une marelle."""
    cote = s * 0.17
    marge = s * 0.025
    cases = [(0, 2), (-0.5, 1), (0.5, 1), (0, 0)]
    for dx, rang in cases:
        x = s / 2 + dx * (cote + marge) - cote / 2
        y = s * 0.20 + rang * (cote + marge)
        d.rounded_rectangle((x, y, x + cote, y + cote), radius=int(cote * 0.18),
                            fill=BLANC if rang != 1 or dx < 0 else None,
                            outline=BLANC, width=int(s * 0.03))


def aurele(d: ImageDraw.ImageDraw, s: int) -> None:
    """Luxe : un diamant taillé, trait d'or."""
    c = s / 2
    haut, milieu, bas = s * 0.28, s * 0.42, s * 0.78
    contour = [(s * 0.34, haut), (s * 0.66, haut), (s * 0.80, milieu), (c, bas),
               (s * 0.20, milieu)]
    largeur = int(s * 0.035)
    d.polygon(contour, outline=OR, width=largeur)
    d.line([(s * 0.20, milieu), (s * 0.80, milieu)], fill=OR, width=largeur)
    d.line([(s * 0.34, haut), (s * 0.42, milieu), (c, bas), (s * 0.58, milieu),
            (s * 0.66, haut)], fill=OR, width=largeur, joint="curve")


def tilleuls(d: ImageDraw.ImageDraw, s: int) -> None:
    """Santé : une feuille de tilleul et une croix."""
    # La feuille : l'intersection de deux disques, posée en diagonale.
    a = Image.new("L", (s, s), 0)
    b = Image.new("L", (s, s), 0)
    r = s * 0.30
    ImageDraw.Draw(a).ellipse((s * 0.40 - r, s * 0.58 - r, s * 0.40 + r, s * 0.58 + r), fill=255)
    ImageDraw.Draw(b).ellipse((s * 0.58 - r, s * 0.40 - r, s * 0.58 + r, s * 0.40 + r), fill=255)
    d.bitmap((0, 0), ImageChops.multiply(a, b), fill=BLANC)
    d.line([(s * 0.25, s * 0.73), (s * 0.66, s * 0.32)], fill=_hex("166534"),
           width=int(s * 0.03))
    bras, epaisseur = s * 0.08, s * 0.045
    cx, cy = s * 0.76, s * 0.76
    d.rectangle((cx - epaisseur / 2, cy - bras, cx + epaisseur / 2, cy + bras), fill=BLANC)
    d.rectangle((cx - bras, cy - epaisseur / 2, cx + bras, cy + epaisseur / 2), fill=BLANC)


#: Thème → (couleur de fond, dessin).
LOGOS: Dict[str, Tuple[str, Callable[[ImageDraw.ImageDraw, int], None]]] = {
    "alvea": ("1e3a8a", alvea),
    "helior": ("9a3412", helior),
    "marelle": ("be123c", marelle),
    "aurele": ("111827", aurele),
    "tilleuls": ("166534", tilleuls),
}


def dessiner(nom: str) -> Image.Image:
    fond, dessin = LOGOS[nom]
    s = TAILLE * ECHELLE
    image = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    _fond(d, s, _hex(fond))
    dessin(d, s)
    return image.resize((TAILLE, TAILLE), Image.LANCZOS)


def main() -> int:
    for nom in LOGOS:
        dossier = ICI / nom
        dossier.mkdir(exist_ok=True)
        dessiner(nom).save(dossier / "logo.png", optimize=True)
        print("%s/logo.png" % nom)
    return 0


if __name__ == "__main__":  # pragma: no cover - point d'entrée
    raise SystemExit(main())
