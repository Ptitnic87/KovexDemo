#!/usr/bin/env python3
# Fichier : empaqueter.py
"""Une seule archive à copier sur le serveur de démonstration.

Le serveur n'a pas d'accès réseau : il ne clone ni ce dépôt ni le sous-module.
Cette commande réunit, dans un zip, les fichiers **suivis par git** des deux
dépôts — la démonstration et le Kovex du sous-module, à la version figée —
plus le fichier ``kovex/.kovex_version`` qui permet à ``restaurer.py`` de
vérifier la version sans ``.git``.

    python empaqueter.py --sortie ../KovexDemo.zip

Seuls les fichiers suivis partent : un ``.env``, des comptes, des espaces de
travail ou une clé présents sur le poste de construction ne sont jamais dans
l'archive, puisqu'aucun n'est versionné.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import List, Optional, Sequence

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))

from restaurer import FICHIER_VERSION, KOVEX, version_de_kovex  # noqa: E402


def fichiers_suivis(depot: Path) -> List[str]:
    """Les fichiers suivis par git, sans les sous-modules eux-mêmes."""
    sortie = subprocess.run(["git", "-C", str(depot), "ls-files", "-z", "--stage"],
                            capture_output=True, check=True)
    fichiers = []
    for entree in sortie.stdout.decode("utf-8").split("\0"):
        if not entree:
            continue
        mode, _, reste = entree.partition(" ")
        chemin = reste.split("\t", 1)[1]
        if mode == "160000":  # un sous-module : empaqueté à part
            continue
        fichiers.append(chemin)
    return sorted(fichiers)


def empaqueter(sortie: Path) -> int:
    version = version_de_kovex(KOVEX)
    if not version or not (KOVEX / "run_api.py").exists():
        raise SystemExit("Kovex est absent de kovex/ : git submodule update --init.")
    etat = subprocess.run(["git", "-C", str(KOVEX), "status", "--porcelain",
                           "--untracked-files=no"], capture_output=True, text=True, check=True)
    if etat.stdout.strip():
        raise SystemExit("Le sous-module kovex/ porte des modifications non commitées : "
                         "l'archive ne correspondrait à aucune version.")
    nombre = 0
    with zipfile.ZipFile(sortie, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for chemin in fichiers_suivis(ICI):
            archive.write(ICI / chemin, "KovexDemo/" + chemin)
            nombre += 1
        for chemin in fichiers_suivis(KOVEX):
            archive.write(KOVEX / chemin, "KovexDemo/kovex/" + chemin)
            nombre += 1
        archive.writestr("KovexDemo/kovex/" + FICHIER_VERSION, version + "\n")
    return nombre


def main(arguments: Optional[Sequence[str]] = None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    analyseur.add_argument("--sortie", default=str(ICI.parent / "KovexDemo.zip"))
    options = analyseur.parse_args(arguments)
    nombre = empaqueter(Path(options.sortie))
    print("Archive écrite : %s (%d fichiers, Kovex %s)"
          % (options.sortie, nombre, (version_de_kovex(KOVEX) or "")[:12]))
    return 0


if __name__ == "__main__":  # pragma: no cover - point d'entrée
    raise SystemExit(main())
