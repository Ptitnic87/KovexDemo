#!/usr/bin/env python3
# Fichier : habiller.py
"""Pose le thème de chaque client fictif dans les espaces figés.

Chaque espace de démonstration prend les **couleurs du thème Wavestone** livré
avec Kovex (``kovex/config/themes/wavestone``) et le **logo de son client
fictif**. C'est le mécanisme des thèmes du produit — un dossier
``themes/<thème>/`` dans l'espace, validé par Kovex au chargement —, rien de
plus. Dans ``habillage/<client>/`` : le libellé et le logo ; les couleurs sont
reprises du thème de base au moment d'habiller, pour ne jamais diverger de
lui. La fiche de chaque secteur dit quel habillage est le sien (``theme``), et
l'espace brut de l'atelier prend celui de son client.

    python habiller.py

Appelé aussi par ``construire_la_demo.py`` au moment de figer. Relancé sur un
instantané déjà habillé, il remplace les thèmes à l'identique.
"""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path
from typing import Dict, Optional, Sequence

ICI = Path(__file__).resolve().parent
HABILLAGE = ICI / "habillage"
SECTEURS = ICI / "secteurs"
INSTANTANE = ICI / "instantane"
#: Le thème dont les couleurs habillent tous les espaces.
THEME_DE_BASE = ICI / "kovex" / "config" / "themes" / "wavestone" / "theme.json"
#: Fichiers d'un thème qui entrent dans l'espace. Le script qui dessine les
#: logos reste dans le dépôt.
FICHIERS_DU_THEME = ("theme.json", "logo.png")


def themes_par_client(secteurs: Path = SECTEURS) -> Dict[str, str]:
    themes: Dict[str, str] = {}
    for fiche in sorted(secteurs.glob("*.json")):
        document = json.loads(fiche.read_text(encoding="utf-8"))
        if document.get("theme"):
            themes[document["client"]] = document["theme"]
    return themes


def document_du_theme(theme: str, habillage: Path = HABILLAGE,
                      base: Path = THEME_DE_BASE) -> bytes:
    """Le libellé et le logo du client, les couleurs du thème de base."""
    document = json.loads((habillage / theme / "theme.json").read_text(encoding="utf-8"))
    document["variantes"] = json.loads(base.read_text(encoding="utf-8"))["variantes"]
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def habiller_l_archive(archive: Path, identifiant: str, theme: str,
                       habillage: Path = HABILLAGE, base: Path = THEME_DE_BASE) -> None:
    """Réécrit l'archive d'un espace avec le thème, sans rien toucher d'autre."""
    with tarfile.open(archive, "r:gz") as source:
        membres = [(m, source.extractfile(m).read() if m.isfile() else None)
                   for m in source.getmembers()]
    prefixe = "%s/themes/%s/" % (identifiant, theme)
    membres = [(m, contenu) for m, contenu in membres if not m.name.startswith(prefixe)]
    with tarfile.open(archive, "w:gz") as sortie:
        for membre, contenu in membres:
            sortie.addfile(membre, io.BytesIO(contenu) if contenu is not None else None)
        for nom in FICHIERS_DU_THEME:
            octets = (document_du_theme(theme, habillage, base) if nom == "theme.json"
                      else (habillage / theme / nom).read_bytes())
            info = tarfile.TarInfo(prefixe + nom)
            info.size = len(octets)
            info.mode = 0o644
            sortie.addfile(info, io.BytesIO(octets))


def habiller(instantane: Path = INSTANTANE, habillage: Path = HABILLAGE,
             secteurs: Path = SECTEURS, base: Path = THEME_DE_BASE) -> Dict[str, str]:
    """Habille chaque espace de l'index dont le client a un thème."""
    themes = themes_par_client(secteurs)
    chemin = instantane / "index.json"
    index = json.loads(chemin.read_text(encoding="utf-8"))
    poses: Dict[str, str] = {}
    for entree in index["espaces"]:
        theme = themes.get(entree.get("client", ""))
        if not theme:
            continue
        habiller_l_archive(instantane / ("%s.tar.gz" % entree["id"]), entree["id"],
                           theme, habillage, base)
        entree["theme"] = theme
        poses[entree["id"]] = theme
    chemin.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return poses


def main(arguments: Optional[Sequence[str]] = None) -> int:
    for identifiant, theme in habiller().items():
        print("%-16s %s" % (identifiant, theme))
    return 0


if __name__ == "__main__":  # pragma: no cover - point d'entrée
    raise SystemExit(main())
