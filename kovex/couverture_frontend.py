#!/usr/bin/env python3
# Fichier : couverture_frontend.py
"""Couverture du JavaScript : mesure, rapport, et seuil opposable.

Le backend est mesuré par coverage.py depuis le premier jour. Le frontend ne
l'était pas : douze fichiers de tests navigateur existaient, sans que personne
ne sache quelle part des 8 700 lignes de JavaScript ils exerçaient. « Des
tests existent » n'est pas une mesure.

    python couverture_frontend.py                 # mesure puis rapport
    python couverture_frontend.py --seuil 95      # échoue en dessous
    python couverture_frontend.py --relire        # rapport sans relancer
    python couverture_frontend.py --detail js/app.js
    python couverture_frontend.py --fusionner t1.json t2.json   # tranches

La campagne se découpe en tranches : d'un seul tenant, les tests navigateur
épuisent la mémoire d'une machine ordinaire, et en intégration continue ils se
répartissent sur plusieurs exécutions parallèles. Chaque tranche rend un relevé
partiel ; `--fusionner` les réunit par union avant que le seuil ne soit opposé.
Sans cette réunion, chaque tranche annonce à zéro les fichiers qu'une autre
exerce.

La mesure vient de V8 lui-même, via le protocole Chrome DevTools, pendant que
les tests Playwright tournent. Aucune dépendance nouvelle, aucune chaîne npm,
aucune étape de build : le produit doit s'installer sur un serveur sans accès,
son outillage de test aussi.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

RACINE = Path(__file__).resolve().parent
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from tests.ihm.couverture_js import Collecteur  # noqa: E402

FRONTEND = RACINE / "frontend"
RELEVE_PAR_DEFAUT = RACINE / "output" / "couverture_frontend.json"

#: Seuil par défaut. L'exigence du projet est 100 % ; la valeur reste
#: réglable, parce qu'un seuil que l'on ne peut pas abaisser temporairement
#: est un seuil que l'on finit par contourner en supprimant la mesure.
SEUIL_PAR_DEFAUT = 100.0


def mesurer(releve: Path, arguments_pytest: Optional[List[str]] = None) -> int:
    """Lance les tests d'interface avec la mesure armée."""
    environnement = dict(os.environ)
    environnement["KOVEX_COUVERTURE_JS"] = str(releve)
    commande = [sys.executable, "-m", "pytest", "tests/ihm", "-q"]
    commande.extend(arguments_pytest or [])
    return subprocess.call(commande, cwd=str(RACINE), env=environnement)


def fusionner(destination: Path, sources: List[Path]) -> int:
    """Réunit les relevés de tranches en un seul, puis l'écrit.

    Écrire le relevé réuni **après** la campagne le rend plus récent que les
    fichiers qu'il mesure : le contrôle de fraîcheur, qui refuse un relevé plus
    vieux que le code, est donc satisfait par construction plutôt que par
    chance.
    """
    manquants = [chemin for chemin in sources if not chemin.is_file()]
    if manquants:
        print("Relevé de tranche introuvable : "
              + ", ".join(str(chemin) for chemin in manquants), file=sys.stderr)
        return 1

    reuni = Collecteur(FRONTEND)
    for chemin in sources:
        try:
            reuni.fusionner(Collecteur.depuis_fichier(FRONTEND, chemin))
        except ValueError as erreur:
            print(f"Réunion impossible : {erreur}", file=sys.stderr)
            return 1
    # Un fichier qu'aucune tranche n'a chargé doit apparaître à zéro, et non
    # disparaître : c'est le seul moyen de voir qu'un module neuf n'a aucun
    # test.
    reuni.completer_avec_les_fichiers_non_charges()
    reuni.ecrire(destination)
    print(f"{len(sources)} tranches réunies dans {destination}")
    return 0


def imprimer_rapport(collecteur: Collecteur, seuil: float) -> bool:
    """Affiche le tableau par fichier. Rend True si le seuil est tenu."""
    largeur = max((len(cle) for cle in collecteur.releves), default=10)
    largeur = max(largeur, len("fichier"))
    print(f"{'fichier':<{largeur}} {'lignes':>7} {'couvertes':>10} {'%':>7}")
    print("-" * (largeur + 27))
    for cle, releve in sorted(collecteur.releves.items(),
                              key=lambda couple: (couple[1].pourcentage, couple[0])):
        print(f"{cle:<{largeur}} {len(releve.executables):7d} "
              f"{len(releve.executees):10d} {releve.pourcentage:6.1f}%")
    executees, executables = collecteur.total()
    global_ = collecteur.pourcentage_global()
    print("-" * (largeur + 27))
    print(f"{'TOTAL':<{largeur}} {executables:7d} {executees:10d} {global_:6.1f}%")
    tenu = global_ + 1e-9 >= seuil
    if not tenu:
        manque = executables - executees
        print(f"\nSeuil {seuil:.1f} % non tenu : {manque} ligne(s) non exercée(s).")
    return tenu


def imprimer_detail(collecteur: Collecteur, fichier: str) -> int:
    """Liste les lignes non exercées d'un fichier, avec leur contenu."""
    releve = collecteur.releves.get(fichier)
    if releve is None:
        proches = [cle for cle in collecteur.releves if fichier in cle]
        if len(proches) != 1:
            print(f"Fichier inconnu : {fichier}", file=sys.stderr)
            if proches:
                print("Candidats : " + ", ".join(sorted(proches)), file=sys.stderr)
            return 1
        releve = collecteur.releves[proches[0]]

    source = (FRONTEND / releve.chemin).read_text(encoding="utf-8").splitlines()
    manquantes = releve.manquantes
    if not manquantes:
        print(f"{releve.chemin} : intégralement exercé.")
        return 0
    print(f"{releve.chemin} — {len(manquantes)} ligne(s) non exercée(s) "
          f"sur {len(releve.executables)} :")
    for numero in manquantes:
        contenu = source[numero - 1] if numero <= len(source) else ""
        print(f"  {numero:5d} | {contenu}")
    return 0


def main(arguments=None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    analyseur.add_argument("--seuil", type=float, default=SEUIL_PAR_DEFAUT,
                           help="pourcentage minimal exigé")
    analyseur.add_argument("--releve", type=str, default=str(RELEVE_PAR_DEFAUT),
                           help="fichier de relevé produit par la mesure")
    analyseur.add_argument("--relire", action="store_true",
                           help="lit un relevé existant sans relancer les tests")
    analyseur.add_argument("--fusionner", nargs="+", default=[], metavar="RELEVE",
                           help="réunit ces relevés de tranches dans --releve, "
                                "puis produit le rapport")
    analyseur.add_argument("--detail", type=str, default="",
                           help="liste les lignes non exercées de ce fichier")
    analyseur.add_argument("--pytest", nargs=argparse.REMAINDER, default=[],
                           help="arguments transmis tels quels à pytest")
    options = analyseur.parse_args(arguments)

    releve = Path(options.releve)
    if options.fusionner:
        code = fusionner(releve, [Path(chemin) for chemin in options.fusionner])
        if code != 0:
            return code
    elif not options.relire:
        code = mesurer(releve, options.pytest)
        if code != 0:
            print("\nLes tests d'interface ont échoué : le relevé de couverture "
                  "est partiel et ne prouve rien.", file=sys.stderr)
            return code

    if not releve.is_file():
        print(f"Relevé introuvable : {releve}", file=sys.stderr)
        return 1

    collecteur = Collecteur.depuis_fichier(FRONTEND, releve)
    if options.detail:
        return imprimer_detail(collecteur, options.detail)
    return 0 if imprimer_rapport(collecteur, options.seuil) else 1


if __name__ == "__main__":  # pragma: no cover - point d'entrée
    raise SystemExit(main())
