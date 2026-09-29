# Fichier : src/core/data/troncature.py
"""Les comptes qui tombent exactement sur une borne d'export.

Un export tronqué ne ressemble pas à une erreur. Il ressemble à une donnée.
Le fichier se charge, les écrans s'affichent, les chiffres sont plausibles — et
tout ce qui suit est faux sans que rien ne le signale : les effectifs des rôles,
la couverture du mining, les cumuls attendus d'une règle de séparation des
tâches, qui se calculent tous à partir de ces comptes.

Le seul indice disponible est la **rondeur**. Les systèmes sources plafonnent à
des valeurs précises : mille pour la pagination LDAP par défaut, mille cinq
cents pour la récupération par plage d'un attribut multivalué d'annuaire, cinq
mille pour le seuil de vue de liste d'un portail documentaire ou un `TOP 5000`
écrit à la main, soixante-cinq mille cinq cent trente-six et un million
quarante-huit mille cinq cent soixante-seize pour les deux limites de lignes
d'un tableur — celles-là disent qu'un fichier est passé par Excel.

Ce que le produit affirme, et ce qu'il n'affirme pas
-----------------------------------------------------
Il n'affirme **pas** que l'export est tronqué. Un groupe peut compter exactement
mille personnes ; c'est improbable, ce n'est pas impossible. Il affirme qu'un
compte tombe exactement sur une borne connue, et que cela se vérifie à la source
avant de bâtir quoi que ce soit dessus.

C'est une suspicion, et elle est rendue comme telle : `warning`, jamais
`critical`. Une alerte critique sur une coïncidence apprendrait à ignorer les
alertes critiques.

Rien n'est deviné, rien n'est appris : deux lectures des mêmes données rendent
les mêmes suspects, dans le même ordre.

Pourquoi la liste des bornes est un réglage
--------------------------------------------
Parce qu'elle décrit les **systèmes sources du client**, pas le produit. Une
liste vide désactive le contrôle, et c'est un choix légitime : sur un
référentiel dont on sait qu'il est exporté sans plafond, la ligne n'apporte que
du bruit.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, Tuple

#: Bornes d'export courantes, livrées comme valeur de départ du réglage.
#:
#: Chacune correspond à un plafond réel d'un système source, et non à une
#: intuition de rondeur : un compte de 3 000 n'est pas suspect, un compte de
#: 1 500 l'est, parce que 1 500 est la taille de plage d'un annuaire et que
#: 3 000 n'est la limite de rien.
BORNES_USUELLES: Tuple[int, ...] = (
    1000,     # pagination LDAP par défaut
    1500,     # récupération par plage d'un attribut multivalué d'annuaire
    5000,     # seuil de vue de liste d'un portail documentaire, `TOP 5000`
    10000,
    20000,
    50000,
    65536,    # limite de lignes d'un tableur, ancien format
    100000,
    1048576,  # limite de lignes d'un tableur, format courant
)


def bornes_depuis_la_configuration(config: Mapping[str, Any]) -> Tuple[int, ...]:
    """Les bornes déclarées pour ce workspace, ou celles livrées.

    Une valeur illisible ne fait pas échouer le chargement : le contrôle
    s'éteint et le reste du rapport de qualité reste consultable. Refuser le
    référentiel entier pour un réglage mal orthographié coûterait plus que le
    contrôle ne rapporte.
    """
    brut = config.get("troncature_bornes", BORNES_USUELLES)
    if brut is None:
        return ()
    if not isinstance(brut, (list, tuple)):
        return ()
    bornes = []
    for valeur in brut:
        try:
            borne = int(valeur)
        except (TypeError, ValueError):
            continue
        if borne > 0:
            bornes.append(borne)
    return tuple(sorted(set(bornes)))


def comptes_suspects(comptes: Mapping[str, int],
                     bornes: Sequence[int]) -> List[Dict[str, Any]]:
    """Les entrées dont le compte égale **exactement** une borne.

    L'égalité est stricte, et c'est tout l'intérêt. Un seuil « proche d'une
    borne » signalerait la moitié du référentiel et ne voudrait rien dire : ce
    qui rend le fait remarquable, c'est justement qu'un compte réel n'a aucune
    raison de tomber pile.

    Rendues triées par compte décroissant : un plafond atteint sur un droit très
    porté fausse davantage que sur un droit marginal.
    """
    if not bornes:
        return []
    interdites = set(int(borne) for borne in bornes)
    suspects = [
        {"identifiant": str(cle), "compte": int(compte), "borne": int(compte)}
        for cle, compte in comptes.items()
        if int(compte) in interdites
    ]
    # Tri stable et total : le compte décroissant, puis l'identifiant. Sans le
    # second critère, deux droits de même compte s'ordonneraient au gré du
    # dictionnaire, et deux lectures ne rendraient pas la même liste.
    suspects.sort(key=lambda suspect: (-suspect["compte"], suspect["identifiant"]))
    return suspects
