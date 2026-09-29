#!/usr/bin/env python3
# Fichier : banc_performance.py
"""Banc de volumétrie : combien coûte le mining, et jusqu'où il tient.

Les garde-fous de `tests/test_performance.py` tournent à chaque campagne, sur
de petits volumes, et affirment des rapports. Ce banc-ci fait l'inverse : il
monte en volume, prend du temps, et produit des **chiffres** — ceux qu'on cite
quand un client demande si le produit tient sur son référentiel.

    python banc_performance.py                      # jusqu'à 20 000 identités
    python banc_performance.py --jusqu-a 100000     # plus loin, plus long
    python banc_performance.py --json mesures.json  # pour comparer plus tard

Le jeu d'essai reproduit deux caractéristiques du référentiel réel : 13
habilitations par identité, et 69,6 % de signatures distinctes. Ce second
chiffre décide de la difficulté : un jeu trop régulier rend le mining
artificiellement rapide, et un banc optimiste ne sert à rien.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Dict, List

RACINE = Path(__file__).resolve().parent
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from tests.performance.generateur import (  # noqa: E402
    DROITS_SOCLES,
    construire,
    taux_de_signatures_distinctes,
)

#: Paliers parcourus par défaut.
PALIERS = (1000, 2000, 5000, 10000, 20000)

SEUIL = 0.8
MIN_USERS = 3
MIN_RIGHTS = 2


def _socles() -> List[str]:
    return [f"D{r:06d}" for r in range(DROITS_SOCLES)]


def _mesurer(jeu, exclure_socles: bool) -> Dict[str, float]:
    """Temps et mémoire, en **deux passages distincts**.

    `tracemalloc` instrumente chaque allocation : mesurer le temps pendant
    qu'il tourne le multiplie par deux à ce volume. Un banc qui publie des
    secondes gonflées par son propre outil de mesure est pire qu'un banc
    absent — on en tire des conclusions fausses.
    """
    from src.core.mining.approximate_miner import ApproximateRoleMiner

    exclus = _socles() if exclure_socles else None

    def lancer():
        return ApproximateRoleMiner(jeu).mine(
            similarity_threshold=SEUIL, min_users=MIN_USERS,
            min_rights=MIN_RIGHTS, excluded_rights=exclus)

    depart = time.perf_counter()
    resultat = lancer()
    secondes = time.perf_counter() - depart

    tracemalloc.start()
    lancer()
    _, pic = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    return {
        "secondes": round(secondes, 3),
        "memoire_mo": round(pic / 1024 / 1024, 1),
        "roles": len(resultat["roles"]),
        "couverture_pct": round(resultat["stats"]["coverage_pct"], 1),
    }


def executer(paliers) -> List[Dict]:
    mesures = []
    for n in paliers:
        jeu = construire(n)
        ligne = {
            "identites": n,
            "droits": jeu.droits,
            "habilitations": jeu.habilitations,
            "signatures_distinctes_pct": round(
                taux_de_signatures_distinctes(jeu) * 100, 1),
            "avec_droits_universels": _mesurer(jeu, exclure_socles=False),
            "socles_exclus": _mesurer(jeu, exclure_socles=True),
        }
        mesures.append(ligne)
        _afficher_ligne(ligne)
    return mesures


def _afficher_ligne(ligne: Dict) -> None:
    avec, sans = ligne["avec_droits_universels"], ligne["socles_exclus"]
    print(f"{ligne['identites']:>9} {ligne['habilitations']:>10} "
          f"{avec['secondes']:>10.2f} {avec['roles']:>7} "
          f"{sans['secondes']:>10.2f} {sans['roles']:>7} "
          f"{sans['memoire_mo']:>9.1f}", flush=True)


def _extrapoler(mesures: List[Dict], cible: int) -> None:
    """Projection vers un volume non mesuré, à partir des deux derniers paliers.

    Une extrapolation n'est pas une mesure : elle suppose que la croissance
    observée se poursuit. Elle est donnée pour situer un ordre de grandeur, pas
    pour être citée comme un chiffre.
    """
    if len(mesures) < 2:
        return

    avant, apres = mesures[-2], mesures[-1]
    for cle, etiquette in (("socles_exclus", "socles exclus"),
                           ("avec_droits_universels", "droits socles laissés")):
        t1, t2 = avant[cle]["secondes"], apres[cle]["secondes"]
        n1, n2 = avant["identites"], apres["identites"]
        if t1 <= 0 or n2 <= n1:
            continue
        import math

        exposant = math.log(t2 / t1) / math.log(n2 / n1)
        projection = t2 * (cible / n2) ** exposant
        print(f"  {etiquette:<28} croissance en n^{exposant:.2f} → "
              f"{projection / 60:.1f} min pour {cible:,} identités"
              .replace(",", " "))


def main(arguments=None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    analyseur.add_argument("--jusqu-a", type=int, default=max(PALIERS),
                           help="volume maximal parcouru")
    analyseur.add_argument("--json", type=str, default="",
                           help="enregistre les mesures dans ce fichier")
    analyseur.add_argument("--cible", type=int, default=500000,
                           help="volume pour lequel extrapoler")
    options = analyseur.parse_args(arguments)

    paliers = [p for p in PALIERS if p <= options.jusqu_a]
    if options.jusqu_a not in paliers:
        paliers.append(options.jusqu_a)

    print(f"{'identites':>9} {'habilit.':>10} "
          f"{'avec(s)':>10} {'roles':>7} {'sans(s)':>10} {'roles':>7} {'Mo':>9}")
    mesures = executer(paliers)

    print("\nExtrapolation — une projection, pas une mesure :")
    _extrapoler(mesures, options.cible)

    if options.json:
        Path(options.json).write_text(
            json.dumps(mesures, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nMesures enregistrées dans {options.json}")

    return 0


if __name__ == "__main__":  # pragma: no cover - point d'entrée
    raise SystemExit(main())
