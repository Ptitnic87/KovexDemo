# Fichier : src/core/knowledge/comptes_secondaires.py
"""La convention des comptes à privilèges, mesurée dans les données du client.

C'est la première question de l'entretien du premier import (note du 13/09),
et **ce n'est pas un modèle qui trouve**. Le produit repère les personnes qui
portent plusieurs comptes — les lignes qui partagent les colonnes que
l'utilisateur a désignées comme « la personne » (nom et prénom, matricule RH…) :
il n'en devine aucune. Pour chaque personne, il relève ce que les
identifiants de ses comptes ont de différent : `599326084` et `fkciadm1` → le
fragment `adm`. Puis il **compte**. Si `adm` distingue le second compte de
180 personnes et n'apparaît que chez 3 comptes isolés, ce n'est plus une
supposition sur une convention de nommage : c'est une convention mesurée.

La question se pose avec sa preuve — combien de personnes, combien de paires
de comptes sans aucun droit commun, combien de comptes seuls portent aussi le
fragment — et la réponse passe par la déclaration existante du marqueur, qui
se relit et se retire dans les paramètres. Rien n'est appliqué d'office.

Le vendre comme « l'IA a trouvé vos comptes d'administration » serait faux, et
le jour où la mesure se tromperait, le client ne croirait plus rien. La mesure
est vérifiable ligne à ligne : c'est son seul argument, et il suffit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Set, Tuple

from src.core.knowledge.privileges import (FRAGMENT_LONGUEUR_MAX,
                                           FRAGMENT_LONGUEUR_MIN, PLACES,
                                           porte_le_fragment)

#: Les suites de lettres d'un identifiant : les chiffres y changent d'un compte
#: à l'autre (un matricule, un numéro d'ordre) et ne font pas une convention.
_LETTRES = re.compile(r"[^\W\d_]+")

#: Valeurs de départ, remplaçables par le workspace.
GROUPES_MIN = 2
FRAGMENTS_MAX = 10
EXEMPLES_MAX = 5


@dataclass(frozen=True)
class Reglages:
    #: Personnes à plusieurs comptes qu'un fragment doit distinguer pour être
    #: proposé. Un seul cas est une coïncidence.
    groupes_min: int = GROUPES_MIN
    fragments_max: int = FRAGMENTS_MAX

    @classmethod
    def depuis_la_configuration(cls, config) -> "Reglages":
        return cls(
            groupes_min=max(1, int(config.get("privileges_mesure_groupes_min", GROUPES_MIN))),
            fragments_max=max(1, int(config.get("privileges_mesure_fragments_max",
                                                FRAGMENTS_MAX))))


def fragments_de(identifiant: str) -> Set[str]:
    """Toutes les sous-suites de lettres d'un identifiant, en minuscules."""
    trouves: Set[str] = set()
    for suite in _LETTRES.findall(str(identifiant).lower()):
        for debut in range(len(suite)):
            for fin in range(debut + FRAGMENT_LONGUEUR_MIN,
                             min(len(suite), debut + FRAGMENT_LONGUEUR_MAX) + 1):
                trouves.add(suite[debut:fin])
    return trouves


def personnes(lignes: Iterable[Tuple[str, Sequence[Any]]]) -> Dict[Tuple[str, ...], List[str]]:
    """Les comptes regroupés par personne, sur les colonnes désignées.

    Une ligne dont une des colonnes est vide n'est rattachée à personne : deux
    comptes sans nom ne sont pas deux comptes de la même personne.
    """
    groupes: Dict[Tuple[str, ...], List[str]] = {}
    for identifiant, valeurs in lignes:
        cle = tuple("" if valeur is None else str(valeur).strip().casefold()
                    for valeur in valeurs)
        if not identifiant or any(not une or une == "nan" for une in cle):
            continue
        groupes.setdefault(cle, []).append(str(identifiant))
    return groupes


def mesurer(lignes: Sequence[Tuple[str, Sequence[Any]]],
            droits: Mapping[str, Set[str]], reglages: Reglages) -> Dict[str, Any]:
    """Les fragments qui distinguent le second compte d'une personne, mesurés."""
    groupes = [comptes for comptes in personnes(lignes).values() if len(comptes) > 1]
    en_groupe = {compte for comptes in groupes for compte in comptes}
    tous = [str(identifiant) for identifiant, _ in lignes if identifiant]
    releves: Dict[str, Dict[str, Any]] = {}
    for comptes in groupes:
        par_compte = {compte: fragments_de(compte) for compte in comptes}
        candidats = set().union(*par_compte.values())
        for fragment in candidats:
            avec = [compte for compte in comptes if fragment in par_compte[compte]]
            if len(avec) == len(comptes):
                continue
            sans = [compte for compte in comptes if fragment not in par_compte[compte]]
            releve = releves.setdefault(fragment, {"groupes": 0, "secondaires": [],
                                                   "paires": 0, "sans_droit_commun": 0})
            releve["groupes"] += 1
            releve["secondaires"].extend(avec)
            for un in avec:
                for autre in sans:
                    releve["paires"] += 1
                    if not (droits.get(un, set()) & droits.get(autre, set())):
                        releve["sans_droit_commun"] += 1
    # Les comptes isolés qui portent aussi le fragment : ceux qu'il marquerait
    # sans qu'aucune seconde identité ne l'explique. Comptés en une passe — un
    # fragment de lettres est dans un identifiant si, et seulement si, il est
    # dans une de ses suites de lettres.
    isoles: Dict[str, int] = {}
    for compte in tous:
        if compte not in en_groupe:
            for fragment in fragments_de(compte):
                isoles[fragment] = isoles.get(fragment, 0) + 1
    candidats = [{"fragment": fragment, "groupes": releve["groupes"],
                  "comptes_secondaires": len(set(releve["secondaires"])),
                  "paires": releve["paires"],
                  "sans_droit_commun": releve["sans_droit_commun"],
                  "isoles": isoles.get(fragment, 0),
                  "exemples": sorted(set(releve["secondaires"]))[:EXEMPLES_MAX]}
                 for fragment, releve in releves.items()
                 if releve["groupes"] >= reglages.groupes_min]
    # Le plus de personnes d'abord, puis le moins de comptes isolés, puis le
    # plus long : à mesure égale, le fragment le plus précis.
    candidats.sort(key=lambda un: (-un["groupes"], un["isoles"], -len(un["fragment"]),
                                   un["fragment"]))
    retenus: List[Dict[str, Any]] = []
    for candidat in candidats:
        # Un fragment contenu dans un plus long déjà retenu, qui distingue
        # exactement les mêmes comptes, n'apporte rien : « ad » et « dm » ne
        # s'ajoutent pas à « adm ». L'ordre garantit que le plus long passe
        # avant.
        if any(candidat["fragment"] in retenu["fragment"]
               and candidat["groupes"] == retenu["groupes"]
               and candidat["comptes_secondaires"] == retenu["comptes_secondaires"]
               for retenu in retenus):
            continue
        retenus.append(candidat)
        if len(retenus) >= reglages.fragments_max:
            break
    for un in retenus:
        # Ce que le marqueur marquerait à chaque place, sur tout le référentiel :
        # le fragment se choisit avec le nombre qu'il produira vraiment.
        un["comptes_par_place"] = {place: sum(1 for compte in tous if porte_le_fragment(
            compte, un["fragment"].upper(), place)) for place in PLACES}
    return {"personnes_a_plusieurs_comptes": len(groupes),
            "comptes_en_groupe": len(en_groupe),
            "comptes": len(tous),
            "fragments": retenus}
