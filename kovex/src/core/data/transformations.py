"""Transformations appliquées aux fichiers sources, déclarées par l'utilisateur.

Rien ne permettait de réparer un référentiel au chargement. Si les identifiants
d'un client portent un préfixe de domaine d'un côté et pas de l'autre, si une
colonne est en majuscules dans l'annuaire et en minuscules dans l'extract
applicatif, ou si un fichier d'habilitations met plusieurs droits dans une même
cellule, le rapprochement échoue — et la seule issue était d'éditer les CSV à
la main, hors du produit, sans trace.

Sept opérations, déclarées colonne par colonne et **dans l'ordre voulu** : c'est
l'ordre qui donne sa puissance au mécanisme. Découper une cellule multivaluée
puis élaguer chaque morceau n'est pas la même chose que l'inverse.

Deux principes, les mêmes qu'ailleurs dans ce chargeur :

- **La valeur d'origine est conservée.** Un rapprochement raté se diagnostique
  sans rouvrir les fichiers, et un audit peut remonter à la source. Elle vit
  dans une structure parallèle, pas dans les tableaux affichés : ajouter une
  colonne jumelle à chaque colonne transformée doublerait l'explorateur et les
  exports sans rien apprendre à qui ne cherche pas.
- **Une règle qui ne s'applique pas le dit.** Une colonne absente du fichier —
  faute de frappe, en-tête changé entre deux extractions — est signalée comme
  telle et non silencieusement ignorée. Une transformation qu'on croit active
  et qui ne l'est pas produit exactement le défaut qu'elle devait corriger.

Ces transformations tournent **avant** la standardisation des colonnes et avant
la politique de qualité des clés : elles portent sur les noms de colonnes du
fichier de l'utilisateur, et c'est sur leur résultat que les doublons se
comptent — sans quoi « u1 » et « u1 » précédé d'un espace resteraient deux
identifiants distincts jusque dans la matrice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

from src.core.data.politique_cles import REFERENTIELS


class Operation(str, Enum):
    """Ce qu'une règle fait d'une colonne."""

    #: Retire les espaces de début et de fin.
    ELAGUER = "trim"
    #: Passe en majuscules.
    MAJUSCULES = "upper"
    #: Passe en minuscules.
    MINUSCULES = "lower"
    #: Retire un préfixe s'il est présent — un domaine, un code d'entité.
    RETIRER_PREFIXE = "strip_prefix"
    #: Ajoute un préfixe. L'opération inverse, quand c'est l'autre fichier qui
    #: fait autorité.
    AJOUTER_PREFIXE = "add_prefix"
    #: Découpe une cellule multivaluée : une ligne devient autant de lignes que
    #: la cellule contenait de valeurs.
    DECOUPER = "split"
    #: Remplace des valeurs par d'autres, selon une table déclarée.
    #:
    #: C'est la forme déterministe que prend un rapprochement accepté : le
    #: calcul ne rappelle jamais ce qui a servi à construire la table — un
    #: repérage, un modèle —, il relit la table. Deux exécutions sur les mêmes
    #: fichiers et la même table donnent le même résultat.
    #:
    #: Elle se distingue des six autres sur un point : sa valeur n'est pas une
    #: chaîne mais une correspondance.
    RECODER = "recode"


#: Opérations qui exigent une valeur : un préfixe, un séparateur. Les autres
#: n'en acceptent pas — une valeur saisie mais ignorée est un réglage qui ne
#: fait rien, et un réglage qui ne fait rien est pire qu'un réglage refusé.
OPERATIONS_AVEC_VALEUR = frozenset({
    Operation.RETIRER_PREFIXE,
    Operation.AJOUTER_PREFIXE,
    Operation.DECOUPER,
})

#: Opérations qui exigent une table plutôt qu'une chaîne. Une seule aujourd'hui,
#: mais la distinction est portée par une constante et non par un test sur
#: l'opération : le jour où une deuxième arrive, il n'y a qu'un endroit à
#: changer.
OPERATIONS_AVEC_TABLE = frozenset({Operation.RECODER})

#: Nombre de couples (avant, après) retenus dans l'échantillon d'un rapport.
TAILLE_ECHANTILLON = 5


class RegleInvalide(ValueError):
    """Une règle que le produit ne sait pas appliquer.

    Levée plutôt qu'ignorée : l'utilisateur doit apprendre qu'il s'est trompé
    au moment où il enregistre, pas six écrans plus loin en constatant que son
    rapprochement échoue toujours.
    """

    def __init__(self, motif: str, champ: str, valeur: Any,
                 attendues: Sequence[str] = ()):
        self.motif = motif
        self.champ = champ
        self.valeur = valeur
        self.attendues = list(attendues)
        details = f" (attendu : {', '.join(self.attendues)})" if self.attendues else ""
        super().__init__(f"{motif} — {champ} = {valeur!r}{details}")


@dataclass(frozen=True)
class Regle:
    """Une opération sur une colonne d'un référentiel."""

    colonne: str
    operation: Operation
    valeur: str = ""
    #: Correspondance source → cible, pour les opérations qui en prennent une.
    #:
    #: Un couple de couples plutôt qu'un dictionnaire : une règle est figée, et
    #: un dictionnaire la rendrait modifiable après coup — une table qui change
    #: sous le pipeline ferait mentir le rapport qui l'accompagne.
    table: Tuple[Tuple[str, str], ...] = ()

    def __post_init__(self):
        if not str(self.colonne).strip():
            raise RegleInvalide("colonne non renseignée", "column", self.colonne)
        exige = self.operation in OPERATIONS_AVEC_VALEUR
        if exige and not self.valeur:
            raise RegleInvalide("valeur exigée par l'opération",
                                "value", self.valeur)
        if not exige and self.valeur:
            raise RegleInvalide("valeur inutile pour cette opération",
                                "value", self.valeur)
        exige_table = self.operation in OPERATIONS_AVEC_TABLE
        if exige_table and not self.table:
            raise RegleInvalide("table exigée par l'opération", "table",
                                self.table)
        if not exige_table and self.table:
            raise RegleInvalide("table inutile pour cette opération", "table",
                                self.table)
        if any(not str(source).strip() for source, _ in self.table):
            # Recoder l'absence reviendrait à inventer une donnée : une valeur
            # vide reste vide, et le produit ne devine la fonction de personne.
            raise RegleInvalide("valeur source vide dans la table", "table",
                                self.table)

    @property
    def correspondance(self) -> Dict[str, str]:
        return {source: cible for source, cible in self.table}

    def en_document(self) -> Dict[str, Any]:
        document: Dict[str, Any] = {"column": self.colonne,
                                    "operation": self.operation.value}
        if self.valeur:
            document["value"] = self.valeur
        if self.table:
            document["table"] = self.correspondance
        return document

    @classmethod
    def depuis_document(cls, document: Mapping[str, Any]) -> "Regle":
        if not isinstance(document, Mapping):
            raise RegleInvalide("règle illisible", "rule",
                                type(document).__name__)
        brute = document.get("operation")
        try:
            operation = (brute if isinstance(brute, Operation)
                         else Operation(brute))
        except ValueError:
            raise RegleInvalide(
                "opération inconnue", "operation", brute,
                [membre.value for membre in Operation]) from None
        table = document.get("table")
        if table is not None and not isinstance(table, Mapping):
            raise RegleInvalide("table illisible", "table",
                                type(table).__name__)
        return cls(
            colonne=str(document.get("column") or ""),
            operation=operation,
            valeur=str(document.get("value") or ""),
            # Triée : le document se relit et se compare d'une version à
            # l'autre, et deux tables équivalentes s'écrivent pareil.
            table=tuple(sorted((str(source), str(cible))
                               for source, cible in (table or {}).items())),
        )


@dataclass(frozen=True)
class Pipeline:
    """Les règles du workspace, par référentiel et dans l'ordre déclaré."""

    par_referentiel: Dict[str, Tuple[Regle, ...]] = field(default_factory=dict)

    def pour(self, referentiel: str) -> Tuple[Regle, ...]:
        return self.par_referentiel.get(referentiel, ())

    @property
    def vide(self) -> bool:
        return not any(self.par_referentiel.values())

    def en_document(self) -> Dict[str, List[Dict[str, str]]]:
        return {
            nom: [regle.en_document() for regle in regles]
            for nom, regles in sorted(self.par_referentiel.items())
            if regles
        }

    @classmethod
    def depuis_document(
        cls, document: Optional[Mapping[str, Any]]
    ) -> "Pipeline":
        """Construit le pipeline depuis le `config.json` du workspace.

        Forme attendue :

        ```json
        {"habs": [{"column": "matricule", "operation": "trim"},
                  {"column": "matricule", "operation": "strip_prefix",
                   "value": "CORP\\\\"}]}
        ```

        L'ordre de la liste est l'ordre d'application, et il compte.
        """
        if not document:
            return cls()
        if not isinstance(document, Mapping):
            raise RegleInvalide("bloc de transformations illisible",
                                "transformations", type(document).__name__)
        par_referentiel: Dict[str, Tuple[Regle, ...]] = {}
        for nom, regles in document.items():
            if nom not in REFERENTIELS:
                raise RegleInvalide("référentiel inconnu", "referential", nom,
                                    REFERENTIELS)
            if not isinstance(regles, Sequence) or isinstance(regles, (str, bytes)):
                raise RegleInvalide("liste de règles attendue", nom,
                                    type(regles).__name__)
            par_referentiel[nom] = tuple(
                Regle.depuis_document(regle) for regle in regles)
        return cls(par_referentiel=par_referentiel)


@dataclass(frozen=True)
class RapportRegle:
    """Ce qu'une règle a fait.

    `applicable` à faux signifie que la colonne nommée n'existe pas dans le
    fichier : les compteurs valent alors zéro parce qu'il n'y avait rien à
    transformer, pas parce que tout était déjà en ordre.
    """

    referentiel: str
    regle: Regle
    applicable: bool = False
    lignes_lues: int = 0
    valeurs_modifiees: int = 0
    #: Lignes gagnées par un découpage. Nul pour toute autre opération.
    lignes_produites: int = 0
    #: Couples (avant, après), bornés, pour que l'utilisateur voie l'effet.
    echantillon: Tuple[Tuple[str, str], ...] = ()

    def en_document(self) -> Dict[str, Any]:
        return {
            "referential": self.referentiel,
            "column": self.regle.colonne,
            "operation": self.regle.operation.value,
            "value": self.regle.valeur,
            "applicable": self.applicable,
            "rows_read": self.lignes_lues,
            "values_changed": self.valeurs_modifiees,
            "rows_produced": self.lignes_produites,
            "sample": [{"before": avant, "after": apres}
                       for avant, apres in self.echantillon],
        }


def _appliquer_operation(colonne: pd.Series, regle: Regle) -> pd.Series:
    """Applique une opération autre que le découpage.

    Les valeurs manquantes le restent : les accesseurs `.str` de pandas les
    propagent, là où un passage par `astype(str)` en ferait la chaîne « nan »
    — un identifiant qui n'existe pas, mais que plus rien ne distinguerait
    d'une absence.
    """
    if regle.operation is Operation.ELAGUER:
        return colonne.str.strip()
    if regle.operation is Operation.MAJUSCULES:
        return colonne.str.upper()
    if regle.operation is Operation.MINUSCULES:
        return colonne.str.lower()
    if regle.operation is Operation.RETIRER_PREFIXE:
        return colonne.str.removeprefix(regle.valeur)
    if regle.operation is Operation.RECODER:
        # Une valeur absente de la table reste ce qu'elle est : la table dit
        # ce qu'on rapproche, pas ce qu'on autorise. Et une absence reste une
        # absence — `map` la propage, là où un passage par `str` en ferait la
        # chaîne « nan ».
        correspondance = regle.correspondance
        return colonne.map(
            lambda valeur: valeur if pd.isna(valeur)
            else correspondance.get(valeur, valeur))
    return colonne.radd(regle.valeur)


def _differences(avant: pd.Series, apres: pd.Series) -> pd.Series:
    """Masque des valeurs réellement changées.

    Deux absences ne sont pas une différence : sans ce traitement, une colonne
    à moitié vide compterait autant de « modifications » que de trous.
    """
    manquantes = avant.isna() & apres.isna()
    return (avant != apres) & ~manquantes


def appliquer(
    dataframe: pd.DataFrame,
    regles: Sequence[Regle],
    referentiel: str,
    taille_echantillon: int = TAILLE_ECHANTILLON,
) -> Tuple[pd.DataFrame, pd.DataFrame, List[RapportRegle]]:
    """Applique les règles d'un référentiel, dans l'ordre.

    Args:
        dataframe: le référentiel tel qu'il a été lu.
        regles: les règles déclarées, dans l'ordre d'application.
        referentiel: son nom, repris dans les rapports.
        taille_echantillon: nombre de couples (avant, après) conservés.

    Returns:
        Le référentiel transformé, les valeurs d'origine des colonnes touchées
        — alignées sur l'index du résultat, y compris après un découpage — et
        un rapport par règle.
    """
    resultat = dataframe
    origines = pd.DataFrame(index=dataframe.index)
    rapports: List[RapportRegle] = []

    for regle in regles:
        if regle.colonne not in resultat.columns:
            rapports.append(RapportRegle(
                referentiel=referentiel, regle=regle, applicable=False,
                lignes_lues=len(resultat)))
            continue

        # La valeur d'origine est celle d'avant la **première** règle qui
        # touche la colonne : deux règles enchaînées sur la même colonne ne
        # doivent pas faire passer le résultat intermédiaire pour la source.
        if regle.colonne not in origines.columns:
            origines[regle.colonne] = resultat[regle.colonne]

        avant = resultat[regle.colonne]
        lignes_avant = len(resultat)

        if regle.operation is Operation.DECOUPER:
            decoupe = avant.str.split(regle.valeur)
            resultat = resultat.assign(**{regle.colonne: decoupe})
            resultat = resultat.explode(regle.colonne)
            apres = resultat[regle.colonne]
            # Une ligne découpée en trois compte trois valeurs changées : ce
            # sont bien trois habilitations là où le fichier n'en portait
            # qu'une, et c'est ce que l'utilisateur veut voir.
            modifiees = int(_differences(
                avant.reindex(resultat.index), apres).sum())
            echantillon = _echantillon(
                avant.reindex(resultat.index), apres, taille_echantillon)
        else:
            apres = _appliquer_operation(avant, regle)
            resultat = resultat.assign(**{regle.colonne: apres})
            modifiees = int(_differences(avant, apres).sum())
            echantillon = _echantillon(avant, apres, taille_echantillon)

        rapports.append(RapportRegle(
            referentiel=referentiel,
            regle=regle,
            applicable=True,
            lignes_lues=lignes_avant,
            valeurs_modifiees=modifiees,
            lignes_produites=len(resultat) - lignes_avant,
            echantillon=echantillon,
        ))

    if not origines.columns.empty:
        origines = origines.reindex(resultat.index)
    return resultat, origines, rapports


def _echantillon(avant: pd.Series, apres: pd.Series,
                 taille: int) -> Tuple[Tuple[str, str], ...]:
    """Premiers couples (avant, après) réellement différents.

    Pris dans l'ordre du fichier plutôt que triés : l'utilisateur veut voir ce
    qui arrive à ses premières lignes, celles qu'il a sous les yeux.
    """
    change = _differences(avant, apres)
    positions = change.to_numpy().nonzero()[0][:taille]
    return tuple(
        ("" if pd.isna(avant.iloc[int(p)]) else str(avant.iloc[int(p)]),
         "" if pd.isna(apres.iloc[int(p)]) else str(apres.iloc[int(p)]))
        for p in positions
    )
