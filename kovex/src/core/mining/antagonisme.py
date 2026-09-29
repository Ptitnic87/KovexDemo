# Fichier : src/core/mining/antagonisme.py
"""Les couples de droits que personne ne réunit — et que beaucoup ont séparés.

Une règle de séparation des tâches se déclare. Encore faut-il savoir laquelle
déclarer : un client qui ouvre l'écran devant une liste vide et quarante mille
droits ne la remplira jamais. C'est le sort du réglage des droits sensibles
avant qu'on ne le peuple, et ce serait le sort de celui-ci.

Or les données savent quelque chose. Si quatre cents personnes détiennent `A`,
trois cents détiennent `B`, et que **personne** ne détient les deux, ce n'est
pas un hasard : c'est une règle que l'organisation applique déjà, sans l'avoir
écrite nulle part. Le produit la rend visible, et l'utilisateur dit si c'en
est une.

Le calcul, et pourquoi il est honnête
-------------------------------------
Sous l'hypothèse que les deux droits s'attribuent indépendamment, on attendrait
`n_a × n_b / N` personnes détenant les deux. On en observe `n_ab`. L'écart —
**les cumuls manquants** — est ce que le produit montre : « on en attendrait
quatre-vingt-quatre, il n'y en a aucun ». Ce n'est pas un score entre zéro et
un dont personne ne sait ce qu'il vaut, c'est un nombre de personnes.

Rien n'y est appris, rien n'y est deviné, et aucun modèle n'y intervient : deux
lectures des mêmes données rendent les mêmes couples, dans le même ordre. C'est
la condition pour qu'un auditeur s'en serve.

Ce que le produit ne dit pas
----------------------------
Il ne dit pas que le couple **doit** être séparé. Deux droits jamais réunis
peuvent l'être parce qu'ils appartiennent à deux métiers qui ne se croisent
pas, ou à deux applications dont personne n'a les deux. Le produit rend un
candidat et ce qui l'a motivé ; la règle reste une décision de gouvernance, et
elle se déclare à la main.

Il ne dit pas non plus « aucun risque » quand il ne trouve rien : un référentiel
où tout le monde a tout ne produit aucun couple, et c'est le référentiel le plus
inquiétant qui soit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

#: Nombre de droits confrontés deux à deux, les plus portés d'abord.
#:
#: Ce n'est pas un choix métier, c'est une borne de calcul : la confrontation
#: est quadratique, et vingt mille droits en feraient deux cents millions de
#: couples. Les droits les moins portés sont écartés les premiers — un droit
#: détenu par trois personnes ne peut pas produire d'écart significatif, quelle
#: que soit sa nature.
DROITS_CONFRONTES_MAX = 400

#: Part de la population en deçà de laquelle un droit ne dit rien.
#:
#: Un droit détenu par deux personnes n'a aucune chance d'être réuni à un autre
#: par hasard : il produirait un « cumul manquant » de zéro virgule quelque
#: chose, et noierait la liste. Exprimé en part et non en nombre : trois
#: personnes sur trois cents et trois sur trois cent mille ne sont pas le même
#: fait.
SUPPORT_MINIMAL_PCT = 1.0

#: Nombre de cumuls manquants en deçà duquel un couple n'est pas proposé.
#:
#: C'est le seuil de bruit, et le seul. Il porte sur des **personnes** : « il
#: manque deux cumuls » ne motive aucune règle, « il en manque quatre-vingts »
#: se regarde.
CUMULS_MANQUANTS_MIN = 5.0

#: Couples rendus, les plus marqués d'abord.
COUPLES_MAX = 50


@dataclass(frozen=True)
class Reglages:
    """Les bornes du repérage, toutes réglables par le workspace.

    Aucune n'est écrite ailleurs que dans les valeurs de départ : ce sont des
    seuils de bruit, et un référentiel de trois cents identités ne se disperse
    pas comme un de trois cent mille.
    """

    droits_confrontes_max: int = DROITS_CONFRONTES_MAX
    support_minimal_pct: float = SUPPORT_MINIMAL_PCT
    cumuls_manquants_min: float = CUMULS_MANQUANTS_MIN
    couples_max: int = COUPLES_MAX

    @classmethod
    def depuis_la_configuration(cls, config: Mapping[str, Any]) -> "Reglages":
        return cls(
            droits_confrontes_max=int(config.get(
                "sod_droits_confrontes_max", DROITS_CONFRONTES_MAX)),
            support_minimal_pct=float(config.get(
                "sod_support_minimal_pct", SUPPORT_MINIMAL_PCT)),
            cumuls_manquants_min=float(config.get(
                "sod_cumuls_manquants_min", CUMULS_MANQUANTS_MIN)),
            couples_max=int(config.get("sod_couples_max", COUPLES_MAX)),
        )


def _retenus(effectifs: np.ndarray, population: int,
             reglages: Reglages) -> np.ndarray:
    """Les indices des droits confrontés, les plus portés d'abord."""
    plancher = population * reglages.support_minimal_pct / 100.0
    eligibles = np.flatnonzero(effectifs >= plancher)
    if eligibles.size <= reglages.droits_confrontes_max:
        return eligibles
    ordre = np.argsort(-effectifs[eligibles], kind="stable")
    return eligibles[ordre[:reglages.droits_confrontes_max]]


def couples_antagonistes(matrice, droits: Sequence[str],
                         reglages: Optional[Reglages] = None,
                         declares: Optional[Sequence[Tuple[frozenset, frozenset]]] = None
                         ) -> List[Dict[str, Any]]:
    """Les couples de droits que la population sépare déjà.

    `matrice` est la matrice creuse identités × droits du chargeur, `droits` la
    liste des identifiants dans l'ordre de ses colonnes.

    `declares` porte les deux côtés des règles existantes : un couple déjà
    couvert n'est pas reproposé. Le reproposer ferait passer pour une découverte
    ce que l'utilisateur a écrit lui-même, et remplirait la liste de ce qu'il a
    déjà traité.

    Le produit matriciel `Mᵀ·M` donne les cumuls observés de tous les couples en
    une opération ; sa diagonale donne les effectifs. C'est ce qui rend le
    repérage tenable sur un référentiel réel, où la boucle en Python coûterait
    des minutes.
    """
    reglages = reglages or Reglages()
    if matrice is None or matrice.shape[0] == 0 or matrice.shape[1] < 2:
        return []
    population = int(matrice.shape[0])

    binaire = matrice.copy()
    # La matrice porte des 1 ; un chargement qui laisserait passer un doublon
    # donnerait des 2, et tous les comptes seraient faux sans le dire.
    binaire.data = np.ones_like(binaire.data)
    effectifs = np.asarray(binaire.sum(axis=0)).ravel()

    indices = _retenus(effectifs, population, reglages)
    if indices.size < 2:
        return []

    restreinte = binaire[:, indices]
    cumuls = np.asarray((restreinte.T @ restreinte).todense())
    effectifs_retenus = effectifs[indices]

    # Attendus sous indépendance, pour tous les couples à la fois.
    attendus = np.outer(effectifs_retenus, effectifs_retenus) / population
    manquants = attendus - cumuls

    # Seule la moitié supérieure stricte : un couple n'est pas deux couples, et
    # la diagonale compare un droit à lui-même.
    hauts = np.triu_indices(indices.size, k=1)
    valeurs = manquants[hauts]
    garde = np.flatnonzero(valeurs >= reglages.cumuls_manquants_min)
    if garde.size == 0:
        return []

    ordre = garde[np.argsort(-valeurs[garde], kind="stable")]
    declares = declares or []
    couples: List[Dict[str, Any]] = []
    for rang in ordre:
        i, j = int(hauts[0][rang]), int(hauts[1][rang])
        gauche, droite = str(droits[indices[i]]), str(droits[indices[j]])
        if est_declare(gauche, droite, declares):
            continue
        couples.append({
            "gauche": gauche,
            "droite": droite,
            "porteurs_gauche": int(effectifs_retenus[i]),
            "porteurs_droite": int(effectifs_retenus[j]),
            "cumuls_observes": int(cumuls[i, j]),
            # Arrondi à l'entier : c'est un nombre de personnes, et « 83,7
            # personnes » ne veut rien dire à l'écran.
            "cumuls_attendus": int(round(float(attendus[i, j]))),
            "cumuls_manquants": int(round(float(manquants[i, j]))),
        })
        if len(couples) == reglages.couples_max:
            break
    return couples


def couples_declares(regles: Sequence[Any]) -> List[Tuple[frozenset, frozenset]]:
    """Les deux côtés de chaque règle applicable, prêts à être interrogés.

    Les **paires** ne sont pas énumérées, et c'est délibéré : une règle qui
    nomme deux applications se résout en deux milliers de droits par côté, soit
    quatre millions de paires à construire pour en écarter quelques dizaines.
    On garde les deux ensembles, et on teste l'appartenance — deux recherches
    par couple candidat, quelle que soit la taille de la règle.
    """
    return [(frozenset(str(droit) for droit in regle.gauche),
             frozenset(str(droit) for droit in regle.droite))
            for regle in regles
            if getattr(regle, "applicable", True)]


def est_declare(gauche: str, droite: str,
                declares: Sequence[Tuple[frozenset, frozenset]]) -> bool:
    """Ce couple est-il déjà couvert par une règle ?

    Dans les deux sens : une règle « créer / payer » couvre le couple
    « payer / créer », qui est le même fait vu de l'autre bout.
    """
    for cote_gauche, cote_droite in declares:
        if ((gauche in cote_gauche and droite in cote_droite)
                or (droite in cote_gauche and gauche in cote_droite)):
            return True
    return False
