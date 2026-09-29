"""Les réglages effectifs d'un usage, quels que soient ceux qui les portent.

Un seul endroit pour répondre à « où part cette question ? », parce que la
réponse a désormais deux sources et que les faire cohabiter au cas par cas
dans chaque routeur les ferait diverger.

L'ordre ne change pas ce qui existe : **l'environnement gagne**. Une
installation qui pose `KOVEX_ANNOTATEUR_URL` se comporte exactement comme
avant. La configuration du workspace n'est lue que là où l'environnement ne dit
rien — c'est-à-dire, en pratique, dans la page, où il n'y a pas
d'environnement du tout.
"""

from __future__ import annotations

import logging
import os
from typing import Tuple

from fastapi import HTTPException

from src.api.routers.settings import chemin_de_configuration, lire_la_configuration
from src.core.annotation.annotateur import Reglages
from src.core.annotation.points_de_terminaison import (Configuration,
                                                       depuis_la_configuration,
                                                       resoudre)
from src.core.annotation.porte_cles import get_porte_cles

logger = logging.getLogger(__name__)


def configuration_du_workspace() -> Configuration:
    """Le bloc du workspace actif, ou rien s'il n'y en a pas.

    Aucun workspace actif n'est pas une erreur ici : c'est l'état d'un produit
    qu'on vient d'ouvrir. L'usage sera simplement rendu inactif, comme il
    l'était déjà quand l'environnement se taisait.
    """
    try:
        chemin = chemin_de_configuration()
    except HTTPException:
        return Configuration()
    return depuis_la_configuration(lire_la_configuration(chemin))


def reglages_et_origine(usage: str = "") -> Tuple[Reglages, str]:
    """Les réglages d'un usage, et qui les a décidés."""
    return resoudre(os.environ, configuration_du_workspace(),
                    get_porte_cles(), usage)


def reglages_pour(usage: str = "") -> Reglages:
    """Les réglages d'un usage. Remplace la seule lecture de l'environnement."""
    return reglages_et_origine(usage)[0]
