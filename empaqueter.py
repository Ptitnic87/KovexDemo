#!/usr/bin/env python3
# Fichier : empaqueter.py
"""Une seule archive à copier sur un serveur de démonstration sans réseau.

Le dépôt se suffit : Kovex y est copié (``kovex/``). Cette commande n'en fait
qu'un zip, limité aux fichiers **suivis par git** — un ``.env``, des comptes,
des espaces ou une clé présents sur le poste qui empaquette n'y entrent
jamais, puisqu'aucun n'est versionné.

    python empaqueter.py --sortie ../KovexDemo.zip
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

from restaurer import KOVEX, version_de_kovex  # noqa: E402


def fichiers_suivis(depot: Path) -> List[str]:
    sortie = subprocess.run(["git", "-C", str(depot), "ls-files", "-z"],
                            capture_output=True, check=True)
    return sorted(nom for nom in sortie.stdout.decode("utf-8").split("\0") if nom)


def empaqueter(sortie: Path) -> int:
    if not version_de_kovex(KOVEX) or not (KOVEX / "run_api.py").exists():
        raise SystemExit("Kovex est absent de kovex/ : python mettre_a_jour_kovex.py.")
    fichiers = fichiers_suivis(ICI)
    with zipfile.ZipFile(sortie, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for nom in fichiers:
            archive.write(ICI / nom, "KovexDemo/" + nom)
    return len(fichiers)


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
