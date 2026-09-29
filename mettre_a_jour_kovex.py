#!/usr/bin/env python3
# Fichier : mettre_a_jour_kovex.py
"""Recopie une version de Kovex dans ``kovex/``, pour que ce dépôt se suffise.

La démonstration doit tourner à partir de ce seul dépôt : quiconque le
récupère a un Kovex complet, sans accès au dépôt du produit. Kovex y est donc
**copié**, à une version précise, et cette commande est la seule façon de le
changer :

    python mettre_a_jour_kovex.py --source ../KovexD-mo --commit <commit de main>

Elle prend les fichiers **suivis** du commit demandé (``git archive``), sans ce
dont un serveur de démonstration n'a pas l'usage : la page autonome et ses
paquets (``pages/``, ``page/``) et la suite de tests (``tests/``), qui tournent
dans l'intégration continue du produit.

Ce qui vit sur le serveur n'est jamais touché : ``.env``, comptes, porte-clés,
espaces, piste d'audit. Seuls les fichiers que la copie précédente avait
posés sont remplacés. Le commit est écrit dans ``kovex/.kovex_version`` : c'est
lui que ``restaurer.py`` compare à celui de l'instantané. Après une mise à
jour, l'instantané se reconstruit (``construire_la_demo.py``).
"""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))

from restaurer import FICHIER_VERSION, KOVEX  # noqa: E402

#: Ce qu'un serveur de démonstration ne sert pas.
ECARTES = ("pages/", "page/", "tests/")
#: La liste des fichiers posés par la dernière copie, pour ne retirer qu'eux.
FICHIER_INVENTAIRE = ".kovex_fichiers"


def commit_complet(source: Path, commit: str) -> str:
    sortie = subprocess.run(["git", "-C", str(source), "rev-parse", "--verify",
                             commit + "^{commit}"],
                            capture_output=True, text=True, check=True)
    return sortie.stdout.strip()


def retenu(nom: str) -> bool:
    return not any(nom == ecarte.rstrip("/") or nom.startswith(ecarte) for ecarte in ECARTES)


def retirer_l_ancienne_copie(cible: Path) -> None:
    """Retire les fichiers de la copie précédente, et seulement eux."""
    inventaire = cible / FICHIER_INVENTAIRE
    if not inventaire.exists():
        return
    for nom in inventaire.read_text(encoding="utf-8").splitlines():
        chemin = cible / nom
        if nom and chemin.is_file():
            chemin.unlink()


def copier(source: Path, commit: str, cible: Path) -> List[str]:
    """Extrait les fichiers retenus du commit dans ``cible``, sans lien ni évasion."""
    archive = subprocess.run(["git", "-C", str(source), "archive", "--format=tar", commit],
                             capture_output=True, check=True).stdout
    poses: List[str] = []
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for membre in tar.getmembers():
            nom = membre.name
            if not membre.isfile() or not retenu(nom):
                continue
            if nom.startswith("/") or ".." in Path(nom).parts:
                raise SystemExit("chemin refusé dans l'archive : %s" % nom)
            destination = cible / nom
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(tar.extractfile(membre).read())  # type: ignore[union-attr]
            poses.append(nom)
    return sorted(poses)


def mettre_a_jour(source: Path, commit: str, cible: Path = KOVEX) -> str:
    complet = commit_complet(source, commit)
    cible.mkdir(parents=True, exist_ok=True)
    retirer_l_ancienne_copie(cible)
    poses = copier(source, complet, cible)
    (cible / FICHIER_INVENTAIRE).write_text("\n".join(poses) + "\n", encoding="utf-8")
    (cible / FICHIER_VERSION).write_text(complet + "\n", encoding="utf-8")
    return complet


def main(arguments: Optional[Sequence[str]] = None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    analyseur.add_argument("--source", required=True, help="un clone du dépôt de Kovex")
    analyseur.add_argument("--commit", required=True, help="commit, branche ou étiquette à copier")
    options = analyseur.parse_args(arguments)
    complet = mettre_a_jour(Path(options.source), options.commit)
    print("Kovex %s copié dans %s. Reconstruisez l'instantané : "
          "python construire_la_demo.py" % (complet[:12], KOVEX))
    return 0


if __name__ == "__main__":  # pragma: no cover - point d'entrée
    raise SystemExit(main())
