# Fichier : src/core/knowledge/population.py
"""Qui porte quoi, aujourd'hui, dans les données chargées.

Ce module ne calcule rien de nouveau : il rassemble les deux relevés dont tout
le reste dépend — les droits détenus par identité, et les porteurs d'un rôle —
pour qu'ils ne soient pas réécrits à chaque écran qui en a besoin.

C'est la règle que ce produit s'impose partout : **un chiffre, une
définition**. Deux écrans qui compteraient les porteurs d'un rôle par deux
chemins différents finiraient par ne pas dire la même chose du même rôle, et
c'est le défaut le plus coûteux d'un outil de gouvernance — celui qui fait
perdre confiance dans tous les autres chiffres.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Set


def droits_par_identite(habilitations, colonne_identite: str,
                        colonne_droit: str) -> Dict[str, Set[str]]:
    """Ce que chaque identité détient, d'après les habilitations."""
    if habilitations is None or habilitations.empty:
        return {}
    return {
        str(identite): {str(droit) for droit in groupe.unique()}
        for identite, groupe in habilitations.groupby(
            colonne_identite, observed=True)[colonne_droit]}


def detenteurs_par_droit(habilitations, colonne_identite: str,
                         colonne_droit: str,
                         droits: Optional[Set[str]] = None) -> Dict[str, Set[str]]:
    """Qui détient chaque droit — ou chacun des droits demandés.

    Restreindre aux droits utiles n'est pas une optimisation gratuite : un
    tableau qui pagine appelle ce relevé à chaque page, et regrouper
    l'ensemble des habilitations coûterait alors le prix du référentiel entier
    pour afficher vingt-cinq lignes. Le résultat est identique sur les droits
    demandés — c'est le même regroupement, sur moins de lignes.
    """
    if habilitations is None or habilitations.empty:
        return {}
    cadre = habilitations
    if droits is not None:
        if not droits:
            return {}
        cadre = cadre[cadre[colonne_droit].astype(str).isin(droits)]
        if cadre.empty:
            return {}
    return {
        str(droit): {str(membre) for membre in groupe.unique()}
        for droit, groupe in cadre.groupby(
            colonne_droit, observed=True)[colonne_identite]}


def porteurs_du_role(role: Mapping[str, Any], identites, colonne_identite: str,
                     habilitations, colonne_droit: str) -> List[str]:
    """Les porteurs d'un rôle, par le calcul du modèle acquis.

    Le même que la revue, le complément et le graphe : un rôle est une règle,
    pas une liste figée, et sa population se recalcule sur les données du jour.
    """
    from src.core.role.modele_acquis import construire

    droits = {str(droit) for droit in (role.get("rights") or ())}
    detenteurs = detenteurs_par_droit(habilitations, colonne_identite,
                                      colonne_droit, droits)
    acquis = construire([role], identites, colonne_identite,
                        detenteurs_par_droit=detenteurs)
    return sorted(acquis.roles[0].membres) if acquis.roles else []
