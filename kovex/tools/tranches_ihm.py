#!/usr/bin/env python3
"""Répartit les modules de tests d'interface en tranches égales.

D'un seul tenant, les sept cent cinquante tests navigateur épuisent la mémoire
d'une machine ordinaire : la campagne se découpe. Le découpage était écrit dans
un script de circonstance, à la main, à chaque campagne — donc jamais deux fois
le même, et impossible à rejouer quand une tranche échouait.

    python tools/tranches_ihm.py 2 4      # les modules de la tranche 2 sur 4

Deux propriétés tiennent le découpage, et elles sont testées :

- **exhaustivité** — la réunion des tranches est exactement la liste des
  modules. Un module oublié ne fait échouer aucune tranche : il rend une
  couverture plus basse, qu'on met alors sur le compte du code ;
- **stabilité** — le même module tombe toujours dans la même tranche, parce
  que la liste est triée. Une tranche qui échoue se rejoue seule, et rejoue
  bien la même chose.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Sequence

RACINE = Path(__file__).resolve().parents[1]

#: Où vivent les tests d'interface, relativement à la racine du dépôt.
DOSSIER = Path("tests") / "ihm"

#: Motif des modules exécutables. `conftest.py`, `harnais.py` et
#: `couverture_js.py` ne sont pas des tranches : ce sont les outils que chaque
#: tranche charge.
MOTIF = "test_*.py"


def modules(racine: Path = RACINE) -> List[str]:
    """Les modules de tests d'interface, dans un ordre stable."""
    dossier = racine / DOSSIER
    return sorted(chemin.relative_to(racine).as_posix()
                  for chemin in dossier.glob(MOTIF))


def tranche(numero: int, total: int, tous: Sequence[str]) -> List[str]:
    """Les modules de la tranche `numero` sur `total`.

    La répartition est **cyclique** plutôt que par blocs contigus. Par blocs,
    les modules d'un même écran — qui se suivent par ordre alphabétique et
    coûtent le même temps — tombent dans la même tranche : une tranche dure
    trois fois les autres, et la campagne attend la plus lente. En cycle, les
    coûts voisins se répartissent.
    """
    if total < 1:
        raise ValueError("le nombre de tranches doit valoir au moins 1")
    if not 1 <= numero <= total:
        raise ValueError(
            f"tranche {numero} hors de 1..{total}")
    return [module for rang, module in enumerate(tous)
            if rang % total == numero - 1]


def main(arguments=None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    analyseur.add_argument("numero", type=int, help="numéro de la tranche, à partir de 1")
    analyseur.add_argument("total", type=int, help="nombre de tranches")
    options = analyseur.parse_args(arguments)
    try:
        choisis = tranche(options.numero, options.total, modules())
    except ValueError as erreur:
        print(str(erreur), file=sys.stderr)
        return 1
    if not choisis:
        # Une tranche vide n'est pas une erreur — plus de tranches que de
        # modules — mais elle ne doit pas se lire comme une campagne réussie
        # sans rien exécuter.
        print("aucun module dans cette tranche", file=sys.stderr)
        return 1
    print(" ".join(choisis))
    return 0


if __name__ == "__main__":  # pragma: no cover - point d'entrée
    raise SystemExit(main())
