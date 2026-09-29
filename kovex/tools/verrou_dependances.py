"""Régénère `requirements.lock` à partir de l'environnement qui exécute la suite.

Un verrou écrit à la main se périme au premier `pip install`. Celui-ci est
relevé : il lit les bornes de `requirements.txt`, suit les dépendances de
chaque paquet installé, et écrit les versions présentes. Ce qu'il fige est donc
exactement ce que les tests viennent d'exécuter — pas ce qu'un index proposait
le jour où quelqu'un a lancé `pip freeze`.

    python -m tools.verrou_dependances            # affiche l'écart, ne touche à rien
    python -m tools.verrou_dependances --ecrire   # met le fichier à jour

Le code de sortie vaut 1 quand le verrou diffère de l'environnement : utilisable
tel quel dans une chaîne d'intégration.
"""

from __future__ import annotations

import argparse
import importlib.metadata as metadonnees
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

RACINE = Path(__file__).resolve().parents[1]
EXECUTION = RACINE / "requirements.txt"
VERROU = RACINE / "requirements.lock"

#: Marqueurs de plateforme conservés dans le verrou. Ils viennent des métadonnées
#: de `uvicorn[standard]`, où ils sont mêlés à la condition `extra ==` : la
#: conserver telle quelle produirait une ligne que `pip` ignorerait toujours,
#: puisque le verrou ne demande aucun extra.
MARQUEURS = {
    "uvloop": ('sys_platform != "win32" and sys_platform != "cygwin" '
               'and platform_python_implementation != "PyPy"'),
    "colorama": 'sys_platform == "win32"',
    "tzdata": 'sys_platform == "win32"',
}

#: Paquets conditionnés par la plateforme. Sur celle qui exécute la suite, une
#: partie d'entre eux s'installe et le reste non : `uvloop` hors Windows,
#: `colorama` et `tzdata` sous Windows.
#:
#: Ils doivent figurer dans le verrou **quelle que soit** la plateforme qui le
#: relève, sans quoi `pip` en choisirait librement la version là où ils
#: s'installent. Leur version est donc lue dans l'environnement quand ils y
#: sont, et reprise du verrou existant sinon.
#:
#: La liste était d'abord pensée depuis Linux, et ne contenait que les paquets
#: absents *ici*. Régénérer le verrou depuis Windows en faisait alors
#: disparaître `uvloop`.
CONDITIONNES_PAR_LA_PLATEFORME = {"colorama", "tzdata", "uvloop"}


def exigences_declarees(fichier: Path) -> List[Requirement]:
    """Lignes de `requirements.txt`, commentaires et inclusions retirés."""
    exigences = []
    for ligne in fichier.read_text(encoding="utf-8").splitlines():
        ligne = ligne.split("#")[0].strip()
        if not ligne or ligne.startswith("-"):
            continue
        exigences.append(Requirement(ligne))
    return exigences


def cloture(exigences: List[Requirement]) -> Dict[str, Set[str]]:
    """Tous les paquets atteints depuis les exigences, avec leurs extras.

    Les extras comptent : `uvicorn[standard]` tire six paquets de plus, et un
    verrou qui les oublie laisse `pip` en choisir la version.
    """
    atteints: Dict[str, Set[str]] = {}
    pile: List[Tuple[str, Set[str]]] = [
        (exigence.name, set(exigence.extras)) for exigence in exigences]

    while pile:
        nom, extras = pile.pop()
        cle = canonicalize_name(nom)
        if cle in atteints and extras <= atteints[cle]:
            continue
        atteints[cle] = atteints.get(cle, set()) | extras

        try:
            distribution = metadonnees.distribution(cle)
        except metadonnees.PackageNotFoundError:
            continue

        contextes = [{"extra": ""}] + [{"extra": extra} for extra in atteints[cle]]
        for brut in distribution.requires or []:
            dependance = Requirement(brut)
            if dependance.marker and not any(
                    dependance.marker.evaluate(contexte) for contexte in contextes):
                continue
            pile.append((dependance.name, set(dependance.extras)))
    return atteints


def versions_conservees(verrou: Path) -> Dict[str, str]:
    """Versions déjà inscrites, pour les paquets qu'on ne peut pas relever ici."""
    if not verrou.is_file():
        return {}
    conservees = {}
    for ligne in verrou.read_text(encoding="utf-8").splitlines():
        ligne = ligne.split("#")[0].strip()
        if "==" not in ligne:
            continue
        nom, reste = ligne.split("==", 1)
        conservees[canonicalize_name(nom)] = reste.split(";")[0].strip()
    return conservees


def epingles(exigences: List[Requirement], conservees: Dict[str, str]) -> List[str]:
    """Lignes `nom==version` du verrou, marqueurs compris, triées."""
    lignes = []
    atteints = set(cloture(exigences)) | CONDITIONNES_PAR_LA_PLATEFORME
    for cle in sorted(atteints):
        try:
            version = metadonnees.version(cle)
        except metadonnees.PackageNotFoundError:
            # Absent d'ici : soit il est conditionné par la plateforme et sa
            # version vient du verrou, soit il n'a rien à y faire.
            version = conservees.get(cle) \
                if cle in CONDITIONNES_PAR_LA_PLATEFORME else None
            if version is None:
                continue
        ligne = f"{cle}=={version}"
        if cle in MARQUEURS:
            ligne += f" ; {MARQUEURS[cle]}"
        lignes.append(ligne)
    return lignes


#: En-tête d'un verrou créé de zéro. Le fichier livré porte une explication
#: bien plus longue, écrite à la main : elle est conservée telle quelle d'une
#: régénération à l'autre, parce qu'un verrou sans son mode d'emploi se
#: réinstalle mal.
ENTETE_PAR_DEFAUT = ("# Versions figées de l'exécution.\n"
                     "# Régénérer avec : python -m tools.verrou_dependances --ecrire")


def entete(verrou: Path) -> str:
    """En-tête du verrou existant : c'est de la documentation, pas du relevé."""
    if not verrou.is_file():
        return ENTETE_PAR_DEFAUT
    lignes = []
    for ligne in verrou.read_text(encoding="utf-8").splitlines():
        if ligne.startswith("#") or not ligne.strip():
            lignes.append(ligne)
            continue
        break
    return "\n".join(lignes).rstrip("\n")


def contenu(verrou: Path, exigences: List[Requirement]) -> str:
    corps = "\n".join(epingles(exigences, versions_conservees(verrou)))
    return f"{entete(verrou)}\n\n{corps}\n"


def main(arguments: List[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--ecrire", action="store_true",
                           help="met à jour requirements.lock")
    options = analyseur.parse_args(arguments)

    attendu = contenu(VERROU, exigences_declarees(EXECUTION))
    actuel = VERROU.read_text(encoding="utf-8") if VERROU.is_file() else ""

    if attendu == actuel:
        print("requirements.lock est à jour.")
        return 0

    if options.ecrire:
        VERROU.write_text(attendu, encoding="utf-8")
        print(f"requirements.lock mis a jour ({VERROU}).")
        return 0

    print("requirements.lock ne correspond pas a l'environnement installe.",
          file=sys.stderr)
    print("Relancer avec --ecrire apres avoir verifie que la suite passe.",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
