"""Politique de qualité des clés, déclarée par l'utilisateur.

Le chargeur *détectait* déjà les clés vides et les doublons — le rapport de
qualité les compte depuis longtemps — mais son **comportement** était figé
dans le code : les habilitations incomplètes étaient écartées en silence, les
habilitations en double dédupliquées, et les doublons d'identifiants des trois
autres référentiels conservés tels quels. Trois traitements différents, aucun
choisi par celui qui connaît ses données.

Ce module rend le comportement déclaratif. L'utilisateur pose une politique par
défaut pour le workspace, et la surcharge fichier par fichier quand un
référentiel le mérite — un extract RH propre et un extract applicatif douteux
n'appellent pas le même traitement.

Deux principes tenus ici :

- **Un contrôle non applicable n'est pas un contrôle satisfait.** Si la colonne
  qui porte la clé n'a pas été associée, le rapport le dit (`applicable` à
  faux) au lieu de rendre zéro anomalie, ce qui se lirait « tout va bien ».
- **Rien n'est écarté en silence.** Chaque ligne retirée est comptée, motivée,
  et un échantillon de clés est rendu pour que l'utilisateur puisse aller voir
  dans son fichier.

Les actions portent des jetons stables (`reject`, `discard`, `first`, `last`) :
ils sont écrits dans le `config.json` du workspace et rendus par l'API. Leur
libellé est traduit côté client — le serveur ne fabrique aucun texte.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import pandas as pd


class ActionCleVide(str, Enum):
    """Ce que devient une ligne dont la clé n'est pas renseignée.

    Deux actions seulement, et c'est délibéré : « garder la première
    occurrence » n'a aucun sens pour une clé vide, qui ne désigne personne. Un
    menu qui proposerait un choix sans signification est pire qu'un menu court.
    """

    #: Refuser le chargement : les données ne sont pas exploitées du tout.
    REFUSER = "reject"
    #: Écarter la ligne et poursuivre. Défaut.
    ECARTER = "discard"


class ActionDoublon(str, Enum):
    """Ce que deviennent plusieurs lignes portant la même clé."""

    #: Refuser le chargement.
    REFUSER = "reject"
    #: Écarter **toutes** les occurrences : la clé devient inconnue. C'est le
    #: choix de celui qui préfère perdre un identifiant plutôt que d'en retenir
    #: arbitrairement une version sur deux.
    ECARTER = "discard"
    #: Garder la première occurrence rencontrée dans le fichier. Défaut : c'est
    #: la lecture naturelle de « écarter les lignes en trop », et elle préserve
    #: l'identifiant.
    PREMIERE = "first"
    #: Garder la dernière occurrence — le comportement attendu d'un extract où
    #: la dernière ligne est la plus récente.
    DERNIERE = "last"


#: Référentiels sur lesquels une politique peut être déclarée. Nommer ici la
#: liste plutôt que de la répéter dans le chargeur et dans le schéma d'API
#: évite qu'une surcharge portant un nom inconnu soit acceptée à l'écriture
#: puis ignorée au chargement — un réglage qui ne fait rien est pire qu'un
#: réglage refusé.
REFERENTIELS: Tuple[str, ...] = ("identities", "applications", "rights", "habs")

#: Motifs d'écartement, rendus tels quels à l'interface qui les traduit.
MOTIF_CLE_VIDE = "empty_key"
MOTIF_DOUBLON = "duplicate_key"

#: Nombre de clés retenues dans l'échantillon d'un rapport. Borné : un
#: référentiel entièrement dupliqué produirait sinon une réponse d'API de la
#: taille du fichier.
TAILLE_ECHANTILLON = 20


class ValeurDePolitiqueInconnue(ValueError):
    """Le document de configuration porte une action que le produit ne connaît pas.

    Levée plutôt qu'ignorée : un `config.json` corrigé à la main avec une faute
    de frappe doit être signalé, pas rattrapé par un défaut silencieux qui
    ferait croire à un réglage actif.
    """

    def __init__(self, champ: str, valeur: Any, attendues: Sequence[str]):
        self.champ = champ
        self.valeur = valeur
        self.attendues = list(attendues)
        super().__init__(
            f"{champ} : valeur inconnue {valeur!r} "
            f"(attendu : {', '.join(self.attendues)})"
        )


@dataclass(frozen=True)
class PolitiqueCles:
    """Politique appliquée à un référentiel."""

    cle_vide: ActionCleVide = ActionCleVide.ECARTER
    doublon: ActionDoublon = ActionDoublon.PREMIERE

    def en_document(self) -> Dict[str, str]:
        """Forme sérialisable, telle qu'elle est écrite dans le workspace."""
        return {"empty_key": self.cle_vide.value, "duplicate_key": self.doublon.value}

    @classmethod
    def depuis_document(
        cls,
        document: Optional[Mapping[str, Any]],
        defaut: Optional["PolitiqueCles"] = None,
    ) -> "PolitiqueCles":
        """Construit une politique à partir d'un document partiel.

        Une clé absente hérite de `defaut` : une surcharge par fichier n'a pas
        à répéter ce qu'elle ne change pas.
        """
        base = defaut or cls()
        if not document:
            return base
        return cls(
            cle_vide=_action(document, "empty_key", ActionCleVide, base.cle_vide),
            doublon=_action(document, "duplicate_key", ActionDoublon, base.doublon),
        )


def _action(document: Mapping[str, Any], champ: str, enumeration, defaut):
    """Lit une action, ou rend le défaut si le champ est absent."""
    if champ not in document or document[champ] is None:
        return defaut
    valeur = document[champ]
    if isinstance(valeur, enumeration):
        return valeur
    try:
        return enumeration(valeur)
    except ValueError:
        raise ValeurDePolitiqueInconnue(
            champ, valeur, [membre.value for membre in enumeration]
        ) from None


@dataclass(frozen=True)
class PolitiqueQualite:
    """Politique du workspace : un défaut, et des surcharges par référentiel."""

    defaut: PolitiqueCles = field(default_factory=PolitiqueCles)
    par_referentiel: Dict[str, PolitiqueCles] = field(default_factory=dict)

    def pour(self, referentiel: str) -> PolitiqueCles:
        """Politique effective d'un référentiel : sa surcharge, sinon le défaut."""
        return self.par_referentiel.get(referentiel, self.defaut)

    def en_document(self) -> Dict[str, Any]:
        return {
            "default": self.defaut.en_document(),
            "files": {
                nom: politique.en_document()
                for nom, politique in sorted(self.par_referentiel.items())
            },
        }

    @classmethod
    def depuis_document(
        cls, document: Optional[Mapping[str, Any]]
    ) -> "PolitiqueQualite":
        """Construit la politique du workspace depuis son `config.json`.

        Forme attendue :

        ```json
        {"default": {"empty_key": "discard", "duplicate_key": "first"},
         "files": {"habs": {"duplicate_key": "last"}}}
        ```

        Un document absent donne la politique par défaut : écarter les lignes
        sans clé, garder la première occurrence d'un doublon.

        Sur les habilitations, ce défaut reproduit à l'identique ce que le
        produit faisait déjà — écarter les lignes incomplètes, ne compter
        qu'une fois une même paire. Sur les trois autres référentiels il
        **change** le comportement : les doublons d'identifiants y étaient
        conservés, et le sont désormais une seule fois. Sur le référentiel de
        démonstration, cela retire deux lignes du fichier des applications,
        que le rapport de qualité signalait déjà sans que rien n'en soit fait.
        """
        if not document:
            return cls()
        defaut = PolitiqueCles.depuis_document(document.get("default"))
        fichiers = document.get("files") or {}
        if not isinstance(fichiers, Mapping):
            raise ValeurDePolitiqueInconnue(
                "files", type(fichiers).__name__, ["objet"]
            )
        for nom in fichiers:
            if nom not in REFERENTIELS:
                raise ValeurDePolitiqueInconnue("files", nom, REFERENTIELS)
        return cls(
            defaut=defaut,
            par_referentiel={
                nom: PolitiqueCles.depuis_document(surcharge, defaut)
                for nom, surcharge in fichiers.items()
            },
        )


@dataclass(frozen=True)
class RapportPolitique:
    """Ce que la politique a fait d'un référentiel.

    `applicable` à faux signifie que le contrôle n'a pas eu lieu — colonne de
    clé non associée, ou référentiel non chargé. Les compteurs valent alors
    zéro parce qu'il n'y a rien à compter, pas parce que tout est propre : la
    distinction est portée par le champ, jamais devinée depuis les compteurs.
    """

    referentiel: str
    politique: PolitiqueCles
    applicable: bool = False
    colonnes_manquantes: Tuple[str, ...] = ()
    lignes_lues: int = 0
    lignes_retenues: int = 0
    cles_vides: int = 0
    #: Nombre de clés distinctes présentes plusieurs fois.
    cles_dupliquees: int = 0
    #: Nombre de lignes écartées au titre des doublons.
    lignes_dupliquees: int = 0
    #: Motif du refus de chargement, ou `None`.
    refus: Optional[str] = None
    echantillon_cles_vides: Tuple[int, ...] = ()
    echantillon_cles_dupliquees: Tuple[str, ...] = ()

    @property
    def lignes_ecartees(self) -> int:
        return self.lignes_lues - self.lignes_retenues

    def en_document(self) -> Dict[str, Any]:
        """Forme rendue par l'API. Aucun texte : des jetons et des nombres."""
        return {
            "referential": self.referentiel,
            "policy": self.politique.en_document(),
            "applicable": self.applicable,
            "missing_columns": list(self.colonnes_manquantes),
            "rows_read": self.lignes_lues,
            "rows_kept": self.lignes_retenues,
            "rows_discarded": self.lignes_ecartees,
            "empty_keys": self.cles_vides,
            "duplicate_keys": self.cles_dupliquees,
            "duplicate_rows": self.lignes_dupliquees,
            "refused": self.refus,
            "empty_key_rows_sample": list(self.echantillon_cles_vides),
            "duplicate_keys_sample": list(self.echantillon_cles_dupliquees),
        }


def _cle_lisible(valeurs: Sequence[Any]) -> str:
    """Représentation d'une clé, simple ou composée, pour l'échantillon."""
    return " | ".join("" if v is None else str(v) for v in valeurs)


def appliquer(
    dataframe: pd.DataFrame,
    colonnes: Sequence[str],
    politique: PolitiqueCles,
    referentiel: str,
    taille_echantillon: int = TAILLE_ECHANTILLON,
) -> Tuple[pd.DataFrame, RapportPolitique]:
    """Applique la politique à un référentiel et rend ce qu'elle en a fait.

    Les clés vides sont traitées **avant** les doublons : une ligne déjà
    écartée faute de clé ne doit pas être comptée une seconde fois comme
    doublon d'une autre ligne vide.

    En cas de refus, le dataframe est rendu **inchangé** : c'est à l'appelant
    de décider ce que devient un chargement refusé, et il a besoin des données
    pour dire combien de lignes l'ont provoqué.

    Args:
        dataframe: le référentiel chargé.
        colonnes: colonnes composant la clé. Une seule pour un référentiel,
            deux pour les habilitations.
        politique: les deux actions déclarées.
        referentiel: nom du référentiel, repris dans le rapport.
        taille_echantillon: nombre de clés retenues pour l'échantillon.

    Returns:
        Le dataframe conservé et le rapport correspondant.
    """
    colonnes = list(colonnes)
    manquantes = tuple(c for c in colonnes if c not in dataframe.columns)
    if not colonnes or manquantes:
        return dataframe, RapportPolitique(
            referentiel=referentiel,
            politique=politique,
            applicable=False,
            colonnes_manquantes=manquantes or tuple(colonnes),
            lignes_lues=len(dataframe),
            lignes_retenues=len(dataframe),
        )

    lignes_lues = len(dataframe)

    # Une clé est vide si l'une de ses colonnes est absente de valeur, ou ne
    # contient que des espaces. Le chargeur lit tout en texte : une cellule
    # vide arrive en NaN, une cellule à blanc arrive en chaîne d'espaces, et
    # les deux désignent la même absence.
    vide = pd.Series(False, index=dataframe.index)
    for colonne in colonnes:
        valeurs = dataframe[colonne]
        vide |= valeurs.isna() | (valeurs.astype(str).str.strip() == "")

    nb_vides = int(vide.sum())
    # Numéros de ligne, 1 pour la première ligne de données. Calculés par
    # position et non par index : l'utilisateur ouvre son fichier, pas le
    # dataframe. `nonzero` évite de parcourir 234 000 lignes en Python.
    echantillon_vides = tuple(
        int(position) + 1
        for position in vide.to_numpy().nonzero()[0][:taille_echantillon]
    )

    if nb_vides and politique.cle_vide is ActionCleVide.REFUSER:
        return dataframe, RapportPolitique(
            referentiel=referentiel,
            politique=politique,
            applicable=True,
            lignes_lues=lignes_lues,
            lignes_retenues=lignes_lues,
            cles_vides=nb_vides,
            refus=MOTIF_CLE_VIDE,
            echantillon_cles_vides=echantillon_vides,
        )

    retenu = dataframe.loc[~vide]

    # Les doublons se comptent sur les clés normalisées : « DUPONT » et
    # « DUPONT » entouré d'espaces désignent la même personne dans un fichier
    # exporté à la main, et les traiter comme deux identifiants distincts
    # laisserait passer précisément ce que ce contrôle cherche.
    if retenu.empty:
        normalisees = pd.DataFrame(index=retenu.index)
    else:
        normalisees = pd.DataFrame(
            {c: retenu[c].astype(str).str.strip() for c in colonnes},
            index=retenu.index,
        )

    duplique_toutes = (
        normalisees.duplicated(keep=False)
        if not retenu.empty
        else pd.Series(dtype=bool, index=retenu.index)
    )
    nb_cles_dupliquees = int(
        normalisees.loc[duplique_toutes].drop_duplicates().shape[0]
    ) if not retenu.empty else 0
    echantillon_doublons = tuple(
        sorted(
            _cle_lisible(ligne)
            for ligne in normalisees.loc[duplique_toutes]
            .drop_duplicates()
            .itertuples(index=False, name=None)
        )
    )[:taille_echantillon]

    if nb_cles_dupliquees and politique.doublon is ActionDoublon.REFUSER:
        return dataframe, RapportPolitique(
            referentiel=referentiel,
            politique=politique,
            applicable=True,
            lignes_lues=lignes_lues,
            lignes_retenues=lignes_lues,
            cles_vides=nb_vides,
            cles_dupliquees=nb_cles_dupliquees,
            refus=MOTIF_DOUBLON,
            echantillon_cles_vides=echantillon_vides,
            echantillon_cles_dupliquees=echantillon_doublons,
        )

    if nb_cles_dupliquees:
        if politique.doublon is ActionDoublon.ECARTER:
            a_garder = ~duplique_toutes
        else:
            garde = "first" if politique.doublon is ActionDoublon.PREMIERE else "last"
            a_garder = ~normalisees.duplicated(keep=garde)
        lignes_dupliquees = int(len(retenu) - int(a_garder.sum()))
        retenu = retenu.loc[a_garder]
    else:
        lignes_dupliquees = 0

    return retenu, RapportPolitique(
        referentiel=referentiel,
        politique=politique,
        applicable=True,
        lignes_lues=lignes_lues,
        lignes_retenues=len(retenu),
        cles_vides=nb_vides,
        cles_dupliquees=nb_cles_dupliquees,
        lignes_dupliquees=lignes_dupliquees,
        echantillon_cles_vides=echantillon_vides,
        echantillon_cles_dupliquees=echantillon_doublons,
    )
