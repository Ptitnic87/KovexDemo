# Fichier : src/core/knowledge/constats_identite.py
"""Ce que le produit constate sur une personne, rassemblé en un panneau.

Le marché appelle cela un score de risque : SailPoint note chaque identité de
0 à 100 à partir de sept facteurs nommés. Kovex a déjà ces facteurs, écran par
écran — écart aux pairs, droits conservés d'un poste précédent, conflits de
séparation, compte à privilèges, droits hors référentiel, droits que son rôle
lui accorderait sans qu'elle les ait. Il lui manquait de les montrer ensemble,
pour une personne.

Il ne les additionne pas. Un score se défend mal devant un comité : « 73 »
ne dit pas quoi retirer, et deux personnes à 73 peuvent n'avoir rien en
commun. Chaque constat garde son chiffre et sa définition, et le panneau dit,
pour chacun, s'il a pu être établi — un constat que rien ne permettait de
calculer n'est pas un constat négatif.

Ce module ne recalcule rien que les autres écrans calculent déjà : il lit le
modèle acquis, les règles résolues et les relevés du jour. Deux chemins de
calcul finiraient par dire deux choses de la même personne.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Set


def roles_de_l_identite(identite: str, acquis, detenus: Set[str]) -> List[Dict[str, Any]]:
    """Les rôles validés dont elle est porteuse aujourd'hui, et ce qu'ils lui donnent.

    `non_detenus` est le sur-octroi qu'elle reçoit : ce que le rôle accorde et
    qu'elle n'a pas dans l'export. Attribuer le rôle le lui donnerait ; le
    montrer ici dit, avant de le faire, ce que cela changerait pour elle.
    """
    rendus = []
    for role in acquis.roles:
        if identite not in role.membres:
            continue
        rendus.append({"id": role.identifiant, "nom": role.nom,
                       "droits": len(role.droits),
                       "non_detenus": sorted(role.droits - detenus)})
    rendus.sort(key=lambda role: (-len(role["non_detenus"]), role["nom"], role["id"]))
    return rendus


def hors_modele(identite: str, acquis, detenus: Set[str],
                socle: Iterable[str]) -> List[str]:
    """Ce qu'elle détient qu'aucun de ses rôles ni le socle n'explique.

    Ce n'est pas un droit illégitime : c'est un droit qu'une revue devra
    regarder un par un, faute de rôle pour en répondre.
    """
    return sorted(set(detenus) - acquis.droits_de(identite) - {str(un) for un in socle})


def hors_referentiel(detenus: Set[str], referencies: Set[str]) -> List[str]:
    """Les droits détenus que le référentiel des droits ne connaît pas.

    Sans référentiel chargé, rien n'est signalé : on ne peut pas dire d'un
    droit qu'il manque à une liste qui n'existe pas.
    """
    if not referencies:
        return []
    return sorted(set(detenus) - referencies)
