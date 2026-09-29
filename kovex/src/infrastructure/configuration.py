# Fichier : src/infrastructure/configuration.py
"""Lecture des variables d'environnement, pendant le changement de nom.

Le produit s'appelait PyGIA et s'appelle Kovex. Le changement de nom décidé
était « visible uniquement » : les variables d'environnement existantes
gardent leur préfixe `PYGIA_`, pour ne casser aucune installation. Mais les
réglages ajoutés depuis ont pris `KOVEX_`, et les deux préfixes coexistent
désormais dans le code — un exploitant qui lit `.env.example` ne peut pas
deviner lequel s'applique à un réglage donné.

Plutôt que de trancher au prix d'une rupture, les deux sont acceptés :
`KOVEX_` d'abord, `PYGIA_` ensuite. Une installation existante continue de
fonctionner, une nouvelle n'a qu'un préfixe à retenir, et le jour où le nom
historique disparaît il suffit de retirer le repli.
"""

from __future__ import annotations

import os
from typing import Optional

#: Préfixes acceptés, par ordre de priorité.
PREFIXES = ("KOVEX_", "PYGIA_")


def variable(suffixe: str, defaut: Optional[str] = None) -> Optional[str]:
    """Valeur d'un réglage, quel que soit le préfixe employé.

    `suffixe` est le nom sans préfixe : `LOG_LEVEL`, `SECRET_KEY`… Une variable
    définie mais vide est une réponse : elle désactive le réglage plutôt que de
    laisser le défaut s'appliquer — c'est ce qui permet, par exemple, de couper
    l'écriture du journal dans un fichier.
    """
    for prefixe in PREFIXES:
        nom = f"{prefixe}{suffixe}"
        if nom in os.environ:
            return os.environ[nom]
    return defaut


def entier(suffixe: str, defaut: int) -> int:
    """Réglage numérique. Une valeur illisible retombe sur le défaut.

    Une faute de frappe dans un fichier de configuration ne doit pas empêcher
    le produit de démarrer : elle doit être sans effet, pas fatale.
    """
    brut = variable(suffixe)
    if brut is None:
        return defaut
    try:
        return int(brut)
    except (TypeError, ValueError):
        return defaut
