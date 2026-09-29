# src/core/mining/selection_exacte.py
"""
Sélection exacte des rôles parmi les candidats.

Le glouton retient, à chaque pas, le candidat qui explique le plus
d'habilitations encore non couvertes. C'est une bonne heuristique, mais pas la
plus courte : un grand rôle pris tôt peut devenir inutile une fois les rôles
suivants retenus, et le glouton ne revient jamais en arrière. Sur les jeux de
référence HP, il rend 66 rôles là où 64 suffisent (Firewall-1) et 564 là où
398 suffisent (Americas large).

Cette sélection repart **du même vivier** et **de la même couverture** et
cherche le plus petit ensemble de candidats qui l'atteint. C'est un problème de
couverture d'ensemble, posé en programme linéaire en nombres entiers et résolu
par HiGHS, livré avec scipy : aucune dépendance de plus, aucun appel réseau, et
le même solveur dans la page que sur un poste.

Trois garanties, qui font que ce mode ne peut jamais rendre pire que le glouton :

- **Même couverture.** Chaque habilitation que le glouton expliquait doit l'être
  encore : c'est la contrainte du programme, pas une vérification a posteriori.
- **Aucun sur-octroi.** Elle ne s'applique qu'à θ = 1, où chaque candidat
  n'accorde que des droits détenus. En dessous, elle n'est pas appliquée, et
  le compte rendu le dit.
- **Pas plus de rôles.** Si le solveur ne trouve pas mieux dans l'effort
  accordé, le résultat du glouton est gardé, et le compte rendu le dit.

Ce n'est **pas** le réglage par défaut, et c'est mesuré. Sur un référentiel
bruité — omissions et exceptions, comme sur toute donnée réelle —, le plus
petit ensemble de rôles n'est pas celui qui retrouve les rôles réels : sur le
banc de vérité terrain à 5 % d'omission et 2 % d'exception, à θ = 1, le glouton
retrouve 13 des 15 rôles plantés à l'identique et la sélection exacte aucun. Le
modèle le plus court recoupe les rôles réels avec des fragments de bruit. Elle
sert là où la donnée est propre, et là où l'on veut opposer un nombre de rôles
à l'état de l'art.

La recherche est bornée par un **nombre de nœuds**, pas par un temps : deux
exécutions sur les mêmes données rendent le même modèle, quelle que soit la
vitesse de la machine. Un délai protège en plus le serveur ; s'il mord, le
compte rendu le signale, parce qu'un arrêt au temps n'est plus reproductible.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Sequence

import numpy as np

logger = logging.getLogger(__name__)

#: Les deux façons de choisir les rôles parmi les candidats. Liste fermée, et
#: chaque code est aussi une clé de traduction — `mining.selection.<code>`.
SELECTION_GLOUTONNE = "gloutonne"
SELECTION_EXACTE = "exacte"
SELECTIONS: tuple = (SELECTION_GLOUTONNE, SELECTION_EXACTE)

#: Repli de la sélection quand le workspace n'en déclare aucune : le glouton.
#: Moins de rôles n'est pas de meilleurs rôles — sur donnée bruitée, la
#: sélection exacte perd les rôles réels (voir plus haut). C'est aussi le
#: calcul d'avant : aucun référentiel ne change de résultat à la mise à jour.
SELECTION_PAR_DEFAUT = SELECTION_GLOUTONNE

#: Nœuds de branchement accordés au solveur, en repli. Sur les neuf jeux HP,
#: l'optimum est prouvé à la racine ou presque ; cette valeur ne mord que sur
#: un référentiel où la preuve coûte, et elle y rend alors le meilleur modèle
#: trouvé.
EFFORT_PAR_DEFAUT = 2000

#: Délai de protection, en secondes, en repli. Ce n'est pas un réglage de
#: qualité — c'est la borne qui empêche une demande de tenir le serveur.
DELAI_PAR_DEFAUT_S = 120.0

#: Pourquoi la recherche s'est arrêtée. Chaque code est une clé de traduction
#: — `mining.selection.arret.<code>`.
ARRET_OPTIMUM = "optimum"
ARRET_EFFORT = "effort"
ARRET_DELAI = "delai"
ARRET_SANS_GAIN = "sans_gain"
ARRET_RIEN_A_CHOISIR = "rien_a_choisir"
ARRET_PLANCHER = "plancher"
ARRET_NON_APPLICABLE = "non_applicable"


def valider_selection(selection: str) -> str:
    """Refuse une sélection inconnue plutôt que de l'ignorer.

    Ignorée, une faute de frappe ferait tourner le glouton sans que
    l'utilisateur sache que son choix n'a pas été appliqué.
    """
    if selection not in SELECTIONS:
        raise ValueError(f"sélection inconnue : {selection}")
    return selection


def _incidence(candidats, indptr, indices, n_droits, a_couvrir):
    """Pour chaque candidat, les positions à couvrir qu'il explique.

    Une position est un couple (identité, droit) de la matrice creuse. Un
    candidat explique les couples que ses membres **détiennent** parmi ses
    droits.
    """
    lignes: List[np.ndarray] = []
    colonnes: List[np.ndarray] = []
    appartient = np.zeros(n_droits, dtype=bool)

    for rang, candidat in enumerate(candidats):
        droits, membres = candidat["rights"], candidat["users"]
        appartient[droits] = True
        debuts, fins = indptr[membres], indptr[membres + 1]
        longueurs = fins - debuts
        # Toutes les positions des membres, d'un seul tenant : pour chaque
        # membre, l'intervalle [début, fin) de sa ligne.
        decalage = np.repeat(debuts - np.cumsum(longueurs) + longueurs, longueurs)
        positions = np.arange(int(longueurs.sum()), dtype=np.intp) + decalage
        detenues = positions[appartient[indices[positions]]]
        appartient[droits] = False

        utiles = detenues[a_couvrir[detenues]]
        if utiles.size:
            lignes.append(utiles)
            colonnes.append(np.full(utiles.size, rang, dtype=np.intp))

    if not lignes:
        return None
    return np.concatenate(lignes), np.concatenate(colonnes)


def selectionner(
    candidats: Sequence[Dict[str, np.ndarray]],
    indptr: np.ndarray,
    indices: np.ndarray,
    n_droits: int,
    a_couvrir: np.ndarray,
    roles_glouton: int,
    effort: int = EFFORT_PAR_DEFAUT,
    delai_s: float = DELAI_PAR_DEFAUT_S,
) -> Dict[str, Any]:
    """Le plus petit sous-ensemble de candidats qui couvre `a_couvrir`.

    Args:
        candidats: le vivier du mining, tel que les générateurs l'ont produit.
        indptr, indices: la matrice creuse identités × droits (CSR).
        n_droits: nombre de colonnes de la matrice.
        a_couvrir: masque des positions que le résultat doit expliquer — celles
            que le glouton expliquait, catalogue validé exclu.
        roles_glouton: nombre de rôles du glouton. Un résultat qui n'en a pas
            strictement moins n'est pas rendu.
        effort: nœuds de branchement accordés au solveur.
        delai_s: délai de protection, en secondes.

    Returns:
        {"retenus": [indices des candidats] | None, "arret": code,
         "borne": int | None, "optimale": bool}
        `retenus` vaut None quand le glouton doit être gardé.
    """
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import csr_matrix

    if effort < 1:
        raise ValueError("l'effort de la sélection exacte doit être positif")
    if delai_s <= 0:
        raise ValueError("le délai de la sélection exacte doit être positif")

    rien = {"retenus": None, "arret": ARRET_RIEN_A_CHOISIR,
            "borne": None, "optimale": False}
    if roles_glouton <= 1 or not np.any(a_couvrir):
        return rien

    incidence = _incidence(candidats, indptr, indices, n_droits, a_couvrir)
    if incidence is None:
        return rien
    positions, rangs = incidence

    # Les lignes du programme sont les seules positions à couvrir, renumérotées
    # d'un seul tenant : une ligne vide serait une contrainte impossible.
    numero = np.full(a_couvrir.size, -1, dtype=np.intp)
    utiles = np.flatnonzero(a_couvrir)
    numero[utiles] = np.arange(utiles.size, dtype=np.intp)
    matrice = csr_matrix(
        (np.ones(positions.size), (numero[positions], rangs)),
        shape=(utiles.size, len(candidats)))

    resultat = milp(
        np.ones(len(candidats)),
        constraints=[LinearConstraint(matrice, lb=1, ub=np.inf)],
        integrality=np.ones(len(candidats)),
        bounds=Bounds(0, 1),
        options={"node_limit": int(effort), "time_limit": float(delai_s),
                 "disp": False},
    )

    borne = getattr(resultat, "mip_dual_bound", None)
    borne = int(np.ceil(borne - 1e-6)) if borne is not None and np.isfinite(borne) else None
    optimale = resultat.status == 0
    if optimale:
        arret = ARRET_OPTIMUM
    elif "time" in str(resultat.message).lower():
        arret = ARRET_DELAI
    else:
        arret = ARRET_EFFORT

    if resultat.x is None:
        logger.info("Sélection exacte : aucune solution dans l'effort accordé (%s)", arret)
        return {"retenus": None, "arret": arret, "borne": borne, "optimale": False}

    retenus = [int(rang) for rang in np.flatnonzero(resultat.x > 0.5)]
    if len(retenus) >= roles_glouton:
        # Pas mieux que le glouton : on le garde, et on dit pourquoi.
        return {"retenus": None,
                "arret": ARRET_SANS_GAIN if optimale else arret,
                "borne": borne, "optimale": optimale}

    logger.info("Sélection exacte : %d rôles au lieu de %d (%s, borne %s)",
                len(retenus), roles_glouton, arret, borne)
    return {"retenus": retenus, "arret": arret, "borne": borne,
            "optimale": optimale}
