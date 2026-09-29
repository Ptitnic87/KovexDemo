#!/usr/bin/env python3
# Fichier : construire_le_site.py
"""Construit le site GitHub Pages de la démonstration dans ``docs/``.

Le site est la page autonome de Kovex — le produit entier qui tourne dans le
navigateur, sans serveur — à la même version que l'instantané, plus une
**amorce** : à chaque ouverture, la page remet les espaces de démonstration
tels qu'ils ont été figés, datés du jour, avec leurs minings conservés.

    python construire_le_site.py --source ../KovexD-mo

La page vient du dépôt de Kovex (``pages/`` au commit de l'instantané, lu par
``git archive`` : le dossier de travail peut être sur une autre branche). On
n'y change qu'une chose : l'amorce est insérée dans le pont, à un endroit
repéré par deux ancres. Si une version de Kovex déplace ces ancres, la
construction s'arrête au lieu de produire une page qui démarrerait vide.

Rien de secret n'entre dans le site : pas de clé, pas de compte, pas de donnée
réelle. Tout ce qui y est publié est lisible par quiconque a l'adresse.
"""

from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Optional, Sequence

ICI = Path(__file__).resolve().parent
INSTANTANE = ICI / "instantane"
AMORCE_JS = ICI / "site" / "amorce.js"
SORTIE = ICI / "docs"

#: Où l'amorce s'insère dans le pont. Chacune doit apparaître une fois.
ANCRE_FONCTION = "  async function demarrer() {\n"
ANCRE_APPEL = "    await monterLeDisque(pyodide);\n"


class SiteImpossible(RuntimeError):
    """Une construction qui produirait une page fausse."""


def extraire_les_pages(source: Path, commit: str, destination: Path) -> None:
    """``pages/`` du commit demandé, sans les bancs du produit."""
    archive = subprocess.run(["git", "-C", str(source), "archive", "--format=tar",
                              commit, "pages"], capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for membre in tar.getmembers():
            parties = Path(membre.name).parts
            if not membre.isfile() or len(parties) < 2 or parties[1] == "banc":
                continue
            if ".." in parties or membre.name.startswith("/"):
                raise SiteImpossible("chemin refusé : %s" % membre.name)
            cible = destination.joinpath(*parties[1:])
            cible.parent.mkdir(parents=True, exist_ok=True)
            cible.write_bytes(tar.extractfile(membre).read())  # type: ignore[union-attr]


def inserer_l_amorce(pont: str, amorce: str) -> str:
    for ancre in (ANCRE_FONCTION, ANCRE_APPEL):
        if pont.count(ancre) != 1:
            raise SiteImpossible("ancre introuvable ou ambiguë dans pont.js : %r" % ancre)
    pont = pont.replace(ANCRE_FONCTION, amorce + ANCRE_FONCTION)
    return pont.replace(ANCRE_APPEL, ANCRE_APPEL + "    await amorcerLaDemo(pyodide);\n")


def marquer_le_pont(index_html: str) -> str:
    """Change l'adresse du pont : un navigateur qui a déjà ouvert KovexPublic
    ne doit pas resservir, depuis son cache, un pont sans amorce."""
    ancre = 'src="moteur/pont.js?v='
    if index_html.count(ancre) != 1:
        raise SiteImpossible("balise du pont introuvable dans index.html")
    return index_html.replace(ancre, 'src="moteur/pont.js?demo=1&v=')


def construire(pages: Path, sortie: Path = SORTIE, instantane: Path = INSTANTANE) -> int:
    """Assemble le site à partir d'un dossier ``pages/`` déjà extrait."""
    if not (pages / "moteur" / "kovex-src.zip").exists():
        raise SiteImpossible("la page de Kovex n'embarque pas kovex-src.zip")
    if sortie.exists():
        shutil.rmtree(sortie)
    shutil.copytree(pages, sortie)
    pont = sortie / "moteur" / "pont.js"
    pont.write_text(inserer_l_amorce(pont.read_text(encoding="utf-8"),
                                     AMORCE_JS.read_text(encoding="utf-8")), encoding="utf-8")
    index = sortie / "index.html"
    index.write_text(marquer_le_pont(index.read_text(encoding="utf-8")), encoding="utf-8")

    amorce = sortie / "amorce"
    amorce.mkdir()
    for fichier in sorted(instantane.iterdir()):
        if fichier.suffix in (".gz", ".json"):
            shutil.copy2(fichier, amorce / fichier.name)
    shutil.copy2(ICI / "restaurer.py", amorce / "restaurer.py")
    shutil.copy2(ICI / "modele.json", amorce / "modele.json")
    # Sans ce fichier, GitHub Pages passe le site dans Jekyll, qui écarte ce
    # qui commence par un souligné.
    (sortie / ".nojekyll").write_text("", encoding="utf-8")
    return sum(1 for f in sortie.rglob("*") if f.is_file())


def main(arguments: Optional[Sequence[str]] = None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    analyseur.add_argument("--source", required=True, help="un clone du dépôt de Kovex")
    analyseur.add_argument("--commit", default=None,
                           help="version de Kovex ; celle de l'instantané par défaut")
    analyseur.add_argument("--forcer-version", action="store_true",
                           help="construire même si la version diffère de l'instantané")
    options = analyseur.parse_args(arguments)

    attendue = json.loads((INSTANTANE / "index.json").read_text(encoding="utf-8")
                          ).get("kovex_version")
    commit = options.commit or attendue
    if not commit:
        raise SystemExit("aucune version de Kovex : passez --commit")
    complet = subprocess.run(["git", "-C", options.source, "rev-parse", "--verify",
                              commit + "^{commit}"], capture_output=True, text=True,
                             check=True).stdout.strip()
    if attendue and complet != attendue and not options.forcer_version:
        raise SystemExit("l'instantané a été construit pour Kovex %s, pas %s"
                         % (attendue[:12], complet[:12]))
    temporaire = ICI / ".pages-temporaires"
    if temporaire.exists():
        shutil.rmtree(temporaire)
    try:
        extraire_les_pages(Path(options.source), complet, temporaire)
        nombre = construire(temporaire)
    finally:
        shutil.rmtree(temporaire, ignore_errors=True)
    print("Site écrit dans %s : %d fichiers, Kovex %s." % (SORTIE, nombre, complet[:12]))
    return 0


if __name__ == "__main__":  # pragma: no cover - point d'entrée
    raise SystemExit(main())
