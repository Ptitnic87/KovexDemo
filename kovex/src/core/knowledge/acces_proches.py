# src/core/knowledge/acces_proches.py
"""Les accès proches d'un rôle : faut-il faire entrer cet accès dans le rôle ?

Un rôle validé désigne une population. Hors du rôle, certains accès sont
détenus par presque toute cette population — et par presque personne d'autre.
Ce sont des candidats à l'entrée : le rôle les accorderait, et on retirerait
autant d'attributions individuelles.

La question ne se tranche pas sur un pourcentage. Elle se tranche sur **trois
populations**, par couple (rôle, accès) :

- les porteurs du rôle qui détiennent l'accès — ceux pour qui l'entrée ne
  change rien, sinon qu'elle remplace une attribution individuelle ;
- les détenteurs de l'accès **hors du rôle** — ceux qui le garderont en
  attribution individuelle ;
- les porteurs du rôle **sans** l'accès — ceux à qui l'entrée l'accorderait :
  c'est le sur-octroi que coûterait la décision, nommé.

L'indice de Jaccard des deux populations — détenteurs de l'accès, porteurs du
rôle — les résume en un nombre : la première population sur la réunion des
trois. Il classe, il ne décide pas ; les trois comptes restent à côté, et
chacun se déplie en liste nominative.

La forme vient d'IdentityStream/RoleMining (`JaccardIndex.cs`, MIT) ; le calcul
est réécrit ici sur les données de Kovex.
"""

from __future__ import annotations

from collections import Counter
from fractions import Fraction
from typing import Any, Dict, Iterable, List, Mapping, Set

#: Les trois populations d'un couple (rôle, accès). Chaque code est aussi une
#: clé de traduction — `role.proches.population.<code>`.
AVEC_LE_ROLE = "avec_le_role"
HORS_DU_ROLE = "hors_du_role"
SANS_L_ACCES = "sans_l_acces"
POPULATIONS: tuple = (AVEC_LE_ROLE, HORS_DU_ROLE, SANS_L_ACCES)


def _part(valeur: float) -> Fraction:
    """La part telle que l'utilisateur l'a écrite, sans erreur binaire.

    `0.7` n'a pas d'écriture binaire exacte : comparé en flottants, un accès
    à exactement 70 % pouvait sortir de la liste sans que rien ne le dise.
    """
    return Fraction(str(valeur))


def acces_proches(membres: Set[str],
                  droits_du_role: Iterable[str],
                  detenteurs: Mapping[str, Set[str]],
                  droits_par_identite: Mapping[str, Set[str]],
                  jaccard_min: float,
                  limite: int,
                  exclus: Iterable[str] = ()) -> Dict[str, Any]:
    """Les accès hors du rôle les plus proches de sa population.

    Args:
        membres: les porteurs du rôle, sur les données du jour.
        droits_du_role: ses droits — ils ne sont pas candidats à y entrer.
        detenteurs: pour chaque droit, qui le détient.
        droits_par_identite: pour chaque identité, ce qu'elle détient.
        jaccard_min: indice en dessous duquel un accès n'est pas rendu. Choisi
            par l'utilisateur : le produit n'en pose aucun.
        limite: nombre maximal d'accès rendus, les plus proches d'abord.
        exclus: droits à ne jamais proposer — le socle, que tout le monde
            détient et que le rôle socle porte déjà.

    Returns:
        {"acces": [...], "candidats": int, "sous_le_seuil": int,
         "au_dela_de_la_limite": int}
        `candidats` compte les accès détenus par au moins un porteur ;
        `sous_le_seuil` ceux qu'écarte l'indice, `au_dela_de_la_limite` ceux
        qu'écarte la limite — pour qu'une liste courte ne se lise pas comme
        un rôle sans voisins.
    """
    if not 0.0 <= jaccard_min <= 1.0:
        raise ValueError("jaccard_min doit appartenir à [0, 1]")
    if limite < 1:
        raise ValueError("limite doit être positive")

    ecartes = set(droits_du_role) | set(exclus)
    communs: Counter = Counter()
    for membre in membres:
        communs.update(droit for droit in droits_par_identite.get(membre, ())
                       if droit not in ecartes)

    seuil = _part(jaccard_min)
    retenus: List[Dict[str, Any]] = []
    for droit, avec in communs.items():
        hors = len(detenteurs.get(droit, ())) - avec
        sans = len(membres) - avec
        indice = Fraction(avec, avec + hors + sans)
        if indice < seuil:
            continue
        retenus.append({
            "droit": droit,
            AVEC_LE_ROLE: avec,
            HORS_DU_ROLE: hors,
            SANS_L_ACCES: sans,
            "jaccard": indice,
        })

    # Du plus proche au moins proche ; à indice égal, celui que le plus de
    # porteurs détiennent ; puis l'ordre des codes, pour qu'une même donnée
    # rende toujours la même liste.
    retenus.sort(key=lambda ligne: (-ligne["jaccard"], -ligne[AVEC_LE_ROLE],
                                    ligne["droit"]))
    for ligne in retenus:
        ligne["jaccard"] = round(float(ligne["jaccard"]), 4)
    return {
        "acces": retenus[:limite],
        "candidats": len(communs),
        "sous_le_seuil": len(communs) - len(retenus),
        "au_dela_de_la_limite": max(0, len(retenus) - limite),
    }


def population(membres: Set[str], droit: str,
               detenteurs: Mapping[str, Set[str]], quelle: str) -> Set[str]:
    """L'une des trois populations d'un couple (rôle, accès), nommée."""
    if quelle not in POPULATIONS:
        raise ValueError(f"population inconnue : {quelle}")
    ont = detenteurs.get(droit, set())
    if quelle == AVEC_LE_ROLE:
        return membres & ont
    if quelle == HORS_DU_ROLE:
        return ont - membres
    return membres - ont
