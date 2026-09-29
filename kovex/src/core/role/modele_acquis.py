# Fichier : src/core/role/modele_acquis.py
"""Ce que le catalogue déjà validé octroie, et à qui.

Le mining calculait comme si le catalogue était vide, puis la route retirait du
résultat les candidats dont l'ensemble de droits était **exactement** celui d'un
rôle validé. Un candidat qui recouvrait le même terrain à quatre-vingt-dix pour
cent passait donc au travers, et un droit déjà octroyé à tous ses membres se
retrouvait dans un rôle de plus.

Le cas remonté du terrain le dit mieux qu'une explication :

    Un rôle « Interne » et un rôle « Externe » sont validés, tous deux porteurs
    du droit MFA. Ensemble ils couvrent toute la population. Un mining relancé
    propose un rôle pour une direction — et lui remet le droit MFA.

Ce module répond à deux questions, et à elles seules :

- **qu'est-ce qui est déjà octroyé à *tous* les membres d'un candidat ?** Ces
  droits n'ont rien à faire dedans, et le candidat doit dire lesquels ont été
  retirés, sinon un droit disparaît sans explication — pire que le droit en trop ;
- **quel rôle validé est le parent d'un candidat ?** Celui qui couvre toute sa
  population *et* dont les droits sont inclus dans les siens. Le candidat
  s'exprime alors comme « hérite de X, plus ces droits-ci », qui est la forme
  normale d'un modèle de rôles et ce que le client attend dans son IGA.

**Les acquis sont calculés par identité, pas par règle.** Comparer la règle d'un
candidat à celle d'un rôle validé n'aurait couvert que les rôles issus du
mining : un catalogue réel contient aussi des rôles composés à la main, qui n'ont
pas de règle d'attributs. L'intersection des acquis de ses membres répond pour
tous les cas avec un seul mécanisme.

**Les membres sont calculés, jamais lus.** Un rôle est une règle ; sa population
est celle d'aujourd'hui, pas celle du jour de la validation. Sans quoi le
complément se calculerait contre un fantôme. C'est la même définition que celle
du graphe, dans le même ordre de préséance, pour que les deux écrans ne puissent
pas se contredire.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Set

import pandas as pd


@dataclass(frozen=True)
class RoleAcquis:
    """Un rôle du catalogue, réduit à ce dont le complément a besoin."""

    identifiant: str
    nom: str
    droits: FrozenSet[str]
    membres: FrozenSet[str]

    @property
    def vide(self) -> bool:
        return not self.droits or not self.membres


def _membres_par_regle(regle: Mapping[str, Any],
                       identites: pd.DataFrame,
                       colonne_identifiant: str) -> Set[str]:
    """Identités désignées par une conjonction d'attributs.

    Le référentiel des identités fait foi, et non le périmètre miné : c'est lui
    qui décidera qui reçoit le rôle une fois le modèle appliqué.
    """
    colonnes = [nom for nom in regle if nom in identites.columns]
    if not colonnes or colonne_identifiant not in identites.columns:
        return set()
    retenues = identites
    for nom in colonnes:
        retenues = retenues[retenues[nom].astype(str) == str(regle[nom])]
    return {str(valeur) for valeur in retenues[colonne_identifiant].tolist()}


def _detenteurs_de_tous(droits: Iterable[str],
                        detenteurs_par_droit: Mapping[str, Set[str]]) -> Set[str]:
    """Identités détenant l'intégralité des droits — la règle d'un rôle applicatif."""
    droits = list(droits)
    if not droits:
        return set()
    membres = set(detenteurs_par_droit.get(droits[0], set()))
    for droit in droits[1:]:
        membres &= detenteurs_par_droit.get(droit, set())
        if not membres:
            break
    return membres


def construire(roles_valides: Sequence[Mapping[str, Any]],
               identites: pd.DataFrame,
               colonne_identifiant: str,
               detenteurs_par_droit: Optional[Mapping[str, Set[str]]] = None
               ) -> "ModeleAcquis":
    """Assemble le modèle acquis à partir du catalogue et des données du jour.

    L'ordre de préséance reprend celui du graphe : la règle d'abord, la liste
    enregistrée ensuite, la détention de tous les droits en dernier. Un rôle
    dont aucune de ces trois voies ne rend de membre n'octroie rien et n'entre
    pas dans le modèle — il ne sert qu'à peser sur des comptes.
    """
    detenteurs_par_droit = detenteurs_par_droit or {}
    acquis: List[RoleAcquis] = []
    for role in roles_valides:
        droits = frozenset(str(droit) for droit in (role.get("rights") or ()))
        if not droits:
            continue
        regle = role.get("source_attributes") or {}
        if regle:
            membres = _membres_par_regle(regle, identites, colonne_identifiant)
        elif role.get("users"):
            membres = {str(membre) for membre in role["users"]}
        else:
            membres = _detenteurs_de_tous(droits, detenteurs_par_droit)
        if not membres:
            continue
        acquis.append(RoleAcquis(
            identifiant=str(role.get("id") or role.get("name") or ""),
            nom=str(role.get("name") or ""),
            droits=droits,
            membres=frozenset(membres),
        ))
    return ModeleAcquis(acquis)


class ModeleAcquis:
    """Le catalogue validé, prêt à répondre pour un candidat.

    L'index par identité est construit une fois. Un candidat de deux cent
    trente membres interroge alors deux cent trente entrées d'un dictionnaire,
    au lieu de comparer sa population à celle de chaque rôle validé.
    """

    def __init__(self, roles: Sequence[RoleAcquis]) -> None:
        self.roles = list(roles)
        self._droits_par_identite: Dict[str, Set[str]] = {}
        for role in self.roles:
            for membre in role.membres:
                self._droits_par_identite.setdefault(membre, set()).update(role.droits)

    @property
    def vide(self) -> bool:
        """Un catalogue vide ne retire rien : le mining se comporte comme avant."""
        return not self.roles

    def droits_de(self, identite: str) -> Set[str]:
        return self._droits_par_identite.get(str(identite), set())

    def deja_octroyes(self, membres: Iterable[str]) -> Set[str]:
        """Droits que **tous** les membres détiennent déjà par le catalogue.

        L'intersection, et non l'union : un droit qu'une partie seulement des
        membres possède doit rester dans le candidat, sans quoi le rôle
        cesserait de l'accorder à ceux qui ne l'ont pas.
        """
        membres = list(membres)
        if not membres or self.vide:
            return set()
        commun: Optional[Set[str]] = None
        for membre in membres:
            droits = self._droits_par_identite.get(str(membre))
            if not droits:
                return set()
            commun = set(droits) if commun is None else commun & droits
            if not commun:
                return set()
        return commun or set()

    def parents(self, membres: Iterable[str],
                droits_du_candidat: Iterable[str]) -> List[RoleAcquis]:
        """Rôles validés dont le candidat peut hériter.

        Deux conditions, et les deux comptent :

        - le rôle couvre **toute** la population du candidat. Un rôle qui n'en
          couvre qu'une partie n'est pas un parent : le rattacher priverait les
          autres membres de ses droits. Ce recouvrement partiel est un constat,
          traité ailleurs ;
        - ses droits sont **inclus** dans ceux du candidat. Un parent qui
          apporterait un droit de plus ne retirerait rien : il ajouterait, et
          l'héritage accorderait alors aux membres du candidat un accès que
          personne n'a décidé de leur donner.
        """
        population = {str(membre) for membre in membres}
        if not population:
            return []
        portee = {str(droit) for droit in droits_du_candidat}
        return [role for role in self.roles
                if role.droits <= portee and population <= role.membres]
