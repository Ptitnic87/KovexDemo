# Fichier : src/core/knowledge/usage.py
"""Le signal d'usage : ce qui est détenu et ne sert plus.

Dix éditeurs fondent leurs recommandations de retrait sur une seule question —
**depuis quand ce droit n'a-t-il pas servi ?** Kovex ne la posait pas : il ne
lisait que qui détient quoi. Le client a pourtant souvent la réponse dans son
export — une colonne « dernière utilisation » sur les habilitations, une
colonne « dernière connexion » sur les identités.

Le produit ne connaît aucune de ces colonnes. Il ne les devine pas : c'est
l'utilisateur qui les **déclare**, avec le format de leurs dates et le seuil
d'inactivité. Sans déclaration, la fonction est muette — et elle le dit,
plutôt que de rendre un « rien à signaler » qui ne vaudrait rien.

Trois refus font la conception :

1. **aucune date n'est inventée.** Une cellule vide n'est pas « jamais
   utilisé » : c'est « pas de date ». Les deux se comptent à part, parce que
   le premier se retire et le second se vérifie ;
2. **une date illisible est comptée et montrée**, jamais écartée en silence.
   Un format mal déclaré qui ferait disparaître la moitié des lignes rendrait
   un constat faux sans que rien ne l'indique ;
3. **l'inactivité se mesure à la date de l'export**, pas au jour du calcul.
   Un export d'avril lu en septembre ne rend pas tout le monde inactif. Sans
   date déclarée, la plus récente date observée dans la colonne tient lieu de
   date de l'export — et l'écran le dit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

#: Exemples de valeurs illisibles rendus avec le compte : de quoi reconnaître
#: le format réel sans rendre la colonne entière.
EXEMPLES_MAX = 5


class DeclarationInvalide(ValueError):
    """Une déclaration d'usage que le produit ne peut pas appliquer."""


@dataclass(frozen=True)
class Declaration:
    """Ce que l'utilisateur a déclaré. Rien n'a de valeur par défaut."""

    format_date: str
    inactivite_jours: int
    date_reference: Optional[date] = None

    @classmethod
    def lue(cls, format_date: str, inactivite_jours: int,
            date_reference: str = "") -> "Declaration":
        format_date = str(format_date or "").strip()
        if not format_date or "%" not in format_date:
            raise DeclarationInvalide(
                "le format des dates n'est pas déclaré (par exemple %Y-%m-%d)")
        if int(inactivite_jours) < 1:
            raise DeclarationInvalide("le seuil d'inactivité doit être positif")
        reference = None
        if str(date_reference or "").strip():
            try:
                reference = date.fromisoformat(str(date_reference).strip())
            except ValueError:
                raise DeclarationInvalide(
                    f"la date de l'export n'est pas une date AAAA-MM-JJ : "
                    f"{date_reference!r}") from None
        return cls(format_date=format_date, inactivite_jours=int(inactivite_jours),
                   date_reference=reference)


@dataclass(frozen=True)
class Lecture:
    """Ce qu'une colonne de dates a donné, ligne par ligne."""

    dates: Tuple[Optional[date], ...]
    sans_date: int
    illisibles: int
    exemples_illisibles: Tuple[str, ...]


def lire_les_dates(valeurs: Iterable[Any], format_date: str) -> Lecture:
    """Lit une colonne de dates au format déclaré.

    Une cellule vide donne `None` et compte « sans date » ; une cellule qui ne
    suit pas le format donne `None` et compte « illisible », avec quelques
    exemples. Rien n'est deviné : un format qui ne correspond pas se voit.
    """
    dates: List[Optional[date]] = []
    sans_date = 0
    illisibles = 0
    exemples: List[str] = []
    for valeur in valeurs:
        texte = "" if valeur is None else str(valeur).strip()
        if not texte or texte.lower() in ("nan", "nat", "none"):
            dates.append(None)
            sans_date += 1
            continue
        try:
            dates.append(datetime.strptime(texte, format_date).date())
        except ValueError:
            dates.append(None)
            illisibles += 1
            if len(exemples) < EXEMPLES_MAX and texte not in exemples:
                exemples.append(texte)
    return Lecture(dates=tuple(dates), sans_date=sans_date, illisibles=illisibles,
                   exemples_illisibles=tuple(exemples))


def reference_effective(declaration: Declaration,
                        *lectures: Lecture) -> Tuple[Optional[date], bool]:
    """La date à laquelle l'inactivité se mesure, et si elle a été déduite.

    Déclarée, elle s'applique. Sinon, la plus récente date observée : c'est la
    meilleure estimation de la date de l'export, et l'écran dit qu'elle est
    déduite. Sans aucune date lisible, il n'y en a pas — et rien ne se mesure.
    """
    if declaration.date_reference is not None:
        return declaration.date_reference, False
    observees = [une for lecture in lectures for une in lecture.dates if une is not None]
    return (max(observees), True) if observees else (None, True)


def _bilan(lecture: Lecture, reference: Optional[date], seuil: int) -> Dict[str, Any]:
    datees = sum(1 for une in lecture.dates if une is not None)
    limite = reference - timedelta(days=seuil) if reference else None
    inactives = (sum(1 for une in lecture.dates if une is not None and une < limite)
                 if limite else 0)
    return {"lignes": len(lecture.dates), "datees": datees,
            "sans_date": lecture.sans_date, "illisibles": lecture.illisibles,
            "exemples_illisibles": list(lecture.exemples_illisibles),
            "inactives": inactives}


def inactif(une: Optional[date], reference: Optional[date], seuil: int) -> bool:
    return (une is not None and reference is not None
            and une < reference - timedelta(days=seuil))


def habilitations_dormantes(droits: Sequence[str],
                            lecture: Lecture, reference: Optional[date],
                            seuil: int, limite: int) -> Dict[str, Any]:
    """Par droit : combien le détiennent, combien ne s'en servent plus.

    Les droits sont rangés du plus dormant au moins dormant — la part, puis le
    nombre, puis le code. Une part se lit : « 40 des 42 détenteurs ne s'en
    servent plus depuis 90 jours » dit quoi retirer ; un total ne le dit pas.
    """
    par_droit: Dict[str, Dict[str, Any]] = {}
    for droit, une in zip(droits, lecture.dates):
        entree = par_droit.setdefault(droit, {"droit": droit, "detenteurs": 0,
                                              "dormants": 0, "sans_date": 0,
                                              "derniere_utilisation": None})
        entree["detenteurs"] += 1
        if une is None:
            entree["sans_date"] += 1
            continue
        if inactif(une, reference, seuil):
            entree["dormants"] += 1
        if entree["derniere_utilisation"] is None or une > entree["derniere_utilisation"]:
            entree["derniere_utilisation"] = une
    lignes = [entree for entree in par_droit.values() if entree["dormants"]]
    for entree in lignes:
        entree["part_pct"] = round(100.0 * entree["dormants"] / entree["detenteurs"], 1)
    lignes.sort(key=lambda entree: (-entree["part_pct"], -entree["dormants"],
                                    entree["droit"]))
    for entree in par_droit.values():
        entree["derniere_utilisation"] = (entree["derniere_utilisation"].isoformat()
                                          if entree["derniere_utilisation"] else "")
    return {**_bilan(lecture, reference, seuil),
            "droits_concernes": len(lignes),
            "au_dela_de_la_limite": max(0, len(lignes) - limite),
            "droits": lignes[:limite]}


def dormants_du_droit(identites: Sequence[str], droits: Sequence[str],
                      lecture: Lecture, reference: Optional[date], seuil: int,
                      droit: str) -> List[str]:
    """Les détenteurs de ce droit qui ne s'en servent plus."""
    return sorted({identite for identite, porte, une in zip(identites, droits, lecture.dates)
                   if porte == droit and inactif(une, reference, seuil)})


def identites_inactives(identites: Sequence[str], lecture: Lecture,
                        reference: Optional[date], seuil: int) -> List[str]:
    """Les identités dont la dernière connexion précède le seuil."""
    return sorted({identite for identite, une in zip(identites, lecture.dates)
                   if inactif(une, reference, seuil)})


def bilan_des_identites(lecture: Lecture, reference: Optional[date],
                        seuil: int) -> Dict[str, Any]:
    return _bilan(lecture, reference, seuil)
