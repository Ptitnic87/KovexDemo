# src/core/knowledge/perimetre.py
"""Périmètre d'analyse : le référentiel privé des identités exclues.

Exclure une identité est une décision de gouvernance — un compte de service, un
prestataire, un compte technique dont on sait qu'il fausserait les regroupements.
L'API acceptait cette décision, la persistait et l'affichait, mais **aucun moteur
ne la lisait** : `is_user_excluded()` n'avait aucun appelant. Les identités
exclues continuaient donc de peser sur les rôles découverts, sur la détection
des droits socles et sur les effectifs affichés.

Plutôt que d'ajouter un paramètre `excluded_users` à chacun des quatre moteurs —
quatre signatures à modifier, quatre occasions d'en oublier un — l'exclusion est
appliquée **une fois**, en amont : ce module rend une vue restreinte du
référentiel, que les moteurs consomment sans savoir qu'elle est restreinte.

Symétrie voulue avec les droits socles : ceux-ci sont des *droits* retirés du
périmètre, celles-là des *identités*. Les deux viennent de la Knowledge Base et
s'appliquent au même endroit.

Le périmètre ne s'applique pas au graphe des accès : explorer qui détient quoi
doit rester possible pour une identité écartée de l'analyse — c'est même souvent
la raison pour laquelle on l'examine.

**Deux façons d'écarter, et elles ne se remplacent pas.** La liste nominative
ci-dessus gèle des identifiants : elle convient à l'exception — ce compte de
service précis, avec son motif. Elle ne convient pas à une population. Un
référentiel qui porte un statut, un type de contrat ou une direction se filtre
par une **règle**, et une règle se réévalue à chaque chargement. Une liste
d'identifiants, elle, dérive en silence : les identités arrivées depuis la
décision n'y sont pas, et personne ne s'en aperçoit. C'est un piège que le jour
où le produit lira des connecteurs rafraîchis périodiquement rendrait
systématique.

**Écarter change le dénominateur de tout** — couverture, sur-octroi, effectifs.
Un produit qui filtre sans dire sur quelle population il compte remplace une
demi-vérité par une autre, en pire, parce que celle-ci est invisible. D'où
`rapport_perimetre()`, que les écrans affichent à côté de leurs chiffres.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

import pandas as pd

logger = logging.getLogger(__name__)


class Sens(str, Enum):
    """Ce qu'une règle fait des identités qu'elle désigne."""

    GARDER = "keep"
    ECARTER = "discard"


@dataclass(frozen=True)
class Regle:
    """Un filtre de périmètre sur une valeur d'attribut.

    Attributes:
        attribut: colonne d'identité sur laquelle porte la règle. Son nom vient
            du référentiel de l'utilisateur : le produit ne présuppose aucune
            colonne, ici pas plus qu'ailleurs.
        sens: `GARDER` ne conserve que les identités dont la valeur figure dans
            `valeurs` ; `ECARTER` retire celles-là et garde le reste.
        valeurs: les valeurs visées. Une règle sans valeur ne désigne rien et
            est refusée : elle passerait pour un filtre sans en être un.
        sans_valeur: sort des identités dont l'attribut est vide. Explicite,
            sans défaut : sur un référentiel réel la colonne est incomplète, et
            trancher à la place de l'utilisateur reviendrait à décider pour lui
            du sort d'une population qu'il n'a pas regardée.
    """

    attribut: str
    sens: Sens
    valeurs: frozenset
    sans_valeur: Sens

    @classmethod
    def depuis_dict(cls, brut: Dict[str, Any]) -> "Regle":
        """Construit une règle depuis sa forme stockée, en la validant.

        Raises:
            ValueError: attribut vide, ou aucune valeur. Refuser plutôt
                qu'accepter un filtre qui ne filtre rien : l'utilisateur
                croirait son périmètre restreint alors qu'il ne l'est pas.
        """
        attribut = str(brut.get("attribut") or "").strip()
        if not attribut:
            raise ValueError("une règle de périmètre porte sur un attribut")
        valeurs = frozenset(str(valeur) for valeur in (brut.get("valeurs") or ()))
        if not valeurs:
            raise ValueError(f"la règle sur « {attribut} » ne vise aucune valeur")
        return cls(
            attribut=attribut,
            sens=Sens(brut.get("sens", Sens.GARDER.value)),
            valeurs=valeurs,
            sans_valeur=Sens(brut.get("sans_valeur", Sens.ECARTER.value)),
        )


def _valeurs_normalisees(identites: pd.DataFrame, attribut: str) -> pd.Series:
    """Colonne d'attribut ramenée à des chaînes, le vide restant vide.

    Un référentiel réel mélange les types dans une même colonne — un matricule
    numérique ici, une chaîne là. Comparer sans normaliser ferait échouer la
    règle sur une partie des lignes, silencieusement.
    """
    colonne = identites[attribut]
    texte = colonne.astype(str).str.strip()
    return texte.mask(colonne.isna() | texte.eq("") | texte.eq("nan"))


def ecartees_par_regles(
    identites: pd.DataFrame,
    regles: Sequence[Regle],
    colonne_identite: str = "ID_utilisateur",
) -> Set[str]:
    """Identités que les règles retirent du périmètre.

    Les règles se cumulent : une identité reste dans le périmètre si elle
    satisfait **toutes** les règles. C'est la lecture naturelle de « les actifs
    **et** pas les prestataires ».

    Une règle dont l'attribut est absent du référentiel ne filtre rien. Le
    produit pourrait refuser, mais un rechargement de données qui renomme une
    colonne viderait alors le périmètre ou ferait échouer chaque calcul. Ne rien
    écarter est le seul défaut sûr — et `rapport_perimetre()` le dit.
    """
    if identites.empty or not regles:
        return set()

    identifiants = identites[colonne_identite].astype(str)
    ecartees: Set[str] = set()
    for regle in regles:
        if regle.attribut not in identites.columns:
            continue
        valeurs = _valeurs_normalisees(identites, regle.attribut)
        vides = valeurs.isna()
        vise = valeurs.isin(regle.valeurs)
        # Retenue par la règle : la valeur est visée si l'on garde, ne l'est pas
        # si l'on écarte ; le vide suit sa propre consigne.
        retenue = vise if regle.sens is Sens.GARDER else ~vise
        retenue = retenue.mask(vides, regle.sans_valeur is Sens.GARDER)
        ecartees.update(identifiants[~retenue.astype(bool)])
    return ecartees


def perimetre_effectif(loader, kb) -> Set[str]:
    """Toutes les identités que la Knowledge Base retire de l'analyse.

    Un seul endroit combine les deux sources — la liste nominative et les
    règles. Les moteurs continuent de recevoir ce qu'ils ont toujours reçu, un
    ensemble d'identités à écarter, et n'ont pas à savoir laquelle des deux a
    désigné qui : c'est `rapport_perimetre()` qui le raconte à l'écran.

    Passer par ici plutôt que par `kb.get_excluded_users()` est ce qui garantit
    qu'aucun moteur n'échappe aux règles — l'oubli qui avait justement laissé
    `is_user_excluded()` sans appelant pendant des mois.
    """
    exclues = {str(identite) for identite in kb.get_excluded_users()}
    return exclues | ecartees_par_regles(loader.identities, kb.regles_perimetre())


def rapport_perimetre(
    loader,
    identites_exclues: Optional[Iterable[str]] = None,
    regles: Optional[Sequence[Regle]] = None,
    colonne_identite: str = "ID_utilisateur",
) -> Dict[str, Any]:
    """Sur quelle population portent les chiffres qu'on s'apprête à afficher.

    Écarter des identités change le dénominateur de la couverture, du sur-octroi
    et des effectifs. Ce rapport accompagne ces chiffres partout où ils sont
    rendus : un total sans sa population n'est pas une mesure.

    Returns:
        dict: `identities_total` (le référentiel), `identities_in_scope`,
        `excluded_by_name` (la liste nominative), `excluded_by_rules` (les
        règles), `excluded_total` (les deux, dédupliquées) et
        `inapplicable_rules` — les attributs qu'aucune colonne ne porte, donc
        les règles qui ne filtrent rien et dont l'utilisateur doit le savoir.
    """
    identites = loader.identities
    total = len(identites)
    nommees = {str(identite) for identite in (identites_exclues or ())}
    regles = list(regles or ())

    par_regles = ecartees_par_regles(identites, regles, colonne_identite)
    inapplicables = [regle.attribut for regle in regles
                     if regle.attribut not in identites.columns]

    ensemble = nommees | par_regles
    connues = ({str(identite) for identite in identites[colonne_identite]}
               if total else set())
    return {
        "identities_total": total,
        "identities_in_scope": total - len(ensemble & connues),
        "excluded_by_name": len(nommees),
        "excluded_by_rules": len(par_regles),
        "excluded_total": len(ensemble),
        "inapplicable_rules": inapplicables,
    }


class PerimetreAnalyse:
    """Vue d'un référentiel privée de certaines identités.

    Expose la même surface que le `DataLoader` pour la partie que lisent les
    moteurs : `identities`, `habilitations`, `matrix`, `user_encoder`,
    `right_encoder`, `rights`, `config`.

    Le référentiel des droits n'est pas filtré : un droit que plus personne ne
    détient une fois les exclusions faites reste un droit du référentiel, et le
    voir disparaître du catalogue serait trompeur.
    """

    def __init__(self, loader, identites_exclues: Iterable[str]):
        self._loader = loader
        self._exclues = {str(identite) for identite in identites_exclues}
        self._identities = None
        self._habilitations = None
        self._matrice = None
        self._user_encoder = None

    # ------------------------------------------------------------- passe-plat

    @property
    def config(self):
        return self._loader.config

    @property
    def rights(self):
        return self._loader.rights

    @property
    def applications(self):
        return self._loader.applications

    @property
    def right_encoder(self) -> Dict[str, int]:
        # Les indices de droits restent ceux du référentiel complet : un droit
        # sans détenteur après exclusion donne simplement une colonne vide.
        return self._loader.right_encoder

    # ---------------------------------------------------------------- filtrés

    @property
    def identities(self):
        if self._identities is None:
            identites = self._loader.identities
            colonne = getattr(type(self._loader), "COL_USER_ID", "ID_utilisateur")
            if not identites.empty and colonne in identites.columns:
                identites = identites[~identites[colonne].astype(str).isin(self._exclues)]
            self._identities = identites
        return self._identities.copy()

    @property
    def habilitations(self):
        if self._habilitations is None:
            habilitations = self._loader.habilitations
            colonne = getattr(type(self._loader), "COL_USER_ID", "ID_utilisateur")
            if not habilitations.empty and colonne in habilitations.columns:
                habilitations = habilitations[
                    ~habilitations[colonne].astype(str).isin(self._exclues)
                ]
            self._habilitations = habilitations
        return self._habilitations.copy()

    def _construire_matrice(self) -> None:
        """Découpe les lignes de la matrice et réindexe les identités gardées."""
        matrice = self._loader.matrix
        encodeur = self._loader.user_encoder
        if matrice is None:
            self._matrice, self._user_encoder = None, {}
            return

        gardees = [
            identite for identite, _ in sorted(encodeur.items(), key=lambda couple: couple[1])
            if str(identite) not in self._exclues
        ]
        indices = [encodeur[identite] for identite in gardees]

        self._matrice = matrice[indices, :]
        self._user_encoder = {identite: rang for rang, identite in enumerate(gardees)}

    @property
    def matrix(self):
        if self._matrice is None and self._user_encoder is None:
            self._construire_matrice()
        return self._matrice

    @property
    def user_encoder(self) -> Dict[str, int]:
        if self._user_encoder is None:
            self._construire_matrice()
        return dict(self._user_encoder)


def restreindre(loader, identites_exclues: Optional[Iterable[str]],
                regles: Optional[Sequence[Regle]] = None) -> Any:
    """Rend le référentiel privé des identités hors périmètre.

    Deux sources, un seul résultat : la liste nominative et les règles se
    cumulent. Les moteurs consomment la vue sans savoir laquelle des deux a
    écarté qui — c'est `rapport_perimetre()` qui le raconte à l'écran.

    Sans exclusion ni règle, le référentiel d'origine est rendu tel quel : le
    chemin nominal ne paie rien, et le comportement est strictement inchangé.
    """
    exclues = {str(identite) for identite in (identites_exclues or ())}
    if regles:
        exclues |= ecartees_par_regles(loader.identities, regles)
    if not exclues:
        return loader

    logger.info("Périmètre d'analyse restreint : %d identités exclues", len(exclues))
    return PerimetreAnalyse(loader, exclues)
