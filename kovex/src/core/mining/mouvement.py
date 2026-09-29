# Fichier : src/core/mining/mouvement.py
"""Les droits qu'on garde d'un poste qu'on a quitté.

C'est le constat que les clients demandent en premier et que presque aucun
outil ne rend : quelqu'un change de service, reçoit les accès de son nouveau
poste, et **garde ceux de l'ancien**. Personne ne les retire, parce que
personne ne sait qu'ils sont là. Au bout de trois mobilités, la personne peut
tout faire.

Le problème apparent est qu'il faudrait un historique — deux exports à deux
dates, ou une colonne qui porte le poste précédent — et qu'un référentiel n'en
a presque jamais. Or **un seul instantané suffit**, et c'est le cœur de ce
module.

Le raisonnement
---------------
Un droit résiduel n'est pas un droit *rare*. C'est un droit **typique
d'ailleurs**.

Si Marie est aux Achats et détient sept droits que personne d'autre de son
service ne détient, ce sont peut-être sept exceptions légitimes. Mais si ces
sept droits sont détenus par quatre-vingt-neuf pour cent du service
Comptabilité, ce ne sont pas des exceptions : c'est le poste qu'elle occupait
avant. Le produit **nomme le service d'origine sans qu'on le lui ait dit**, et
c'est ce rapprochement — atypique ici, typique là-bas — qui fait le constat.

Ce qui le rend utilisable par un auditeur : aucun modèle n'y intervient, rien
n'y est appris, et deux lectures des mêmes données rendent les mêmes constats
dans le même ordre.

La rareté se mesure sans la personne elle-même
----------------------------------------------
Une identité fait partie de son propre groupe et détient le droit qu'on examine
: `1 / 34` sur un service de trente-quatre, `1 / 10` sur un service de dix. Le
même fait — « elle est la seule » — donnerait deux nombres différents, et un
seuil en pourcentage laisserait passer les petits groupes.

La part est donc calculée **sur les autres** : `(porteurs − 1) / (effectif − 1)`.
« Elle est la seule » vaut alors zéro quelle que soit la taille du groupe.

Ce que le produit ne dit pas
----------------------------
Il ne dit **pas** que la personne a changé de poste. La mobilité est
l'explication la plus fréquente de ce qu'il constate, pas la seule : une double
casquette, un remplacement, un transfert de mission produisent la même forme.
Le produit rend le constat et ce qui l'a motivé ; conclure appartient à celui
qui connaît l'organisation.

Il ne dit pas non plus « aucun droit résiduel » quand il ne trouve rien : un
référentiel où chaque service donne les mêmes droits à tout le monde ne produit
aucun constat, et un référentiel sans attribut exploitable non plus.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import (Any, Dict, Iterable, List, Mapping, Optional, Sequence,
                    Set, Tuple)

#: Effectif en deçà duquel un groupe ne dit rien.
#:
#: « Personne d'autre de son service ne l'a » sur un service de deux personnes
#: ne signifie rien : c'est l'autre personne qui est peut-être l'exception. Le
#: constat repose entièrement sur le fait que le groupe soit assez nombreux
#: pour avoir une habitude.
GROUPE_MIN = 5

#: Part des **autres** membres du groupe, en pourcentage, en deçà de laquelle un
#: droit est atypique pour cette personne. Zéro signifie « elle est la seule ».
RARETE_MAX_PCT = 5.0

#: Part d'un autre groupe, en pourcentage, au-delà de laquelle le droit y est
#: typique. C'est ce qui distingue un droit résiduel d'une exception : une
#: exception n'est typique nulle part.
TYPIQUE_MIN_PCT = 60.0

#: Nombre de droits concordants en deçà duquel aucun constat n'est rendu.
#:
#: Un droit atypique isolé est du bruit — un remplacement, un projet, une
#: astreinte. Deux droits atypiques qui désignent **le même** autre groupe ne
#: se produisent pas par hasard.
DROITS_MIN = 2

#: Nombre de constats rendus. Une liste de mille lignes ne se relit pas.
CONSTATS_MAX = 200


@dataclass(frozen=True)
class Reglages:
    """Les bornes du repérage, toutes réglables par le workspace.

    Aucune n'est écrite ailleurs que dans les valeurs de départ : ce sont des
    seuils de bruit, et une organisation de trois cents personnes réparties en
    six services ne se comporte pas comme une de trente mille en huit cents.
    """

    groupe_min: int = GROUPE_MIN
    rarete_max_pct: float = RARETE_MAX_PCT
    typique_min_pct: float = TYPIQUE_MIN_PCT
    droits_min: int = DROITS_MIN
    constats_max: int = CONSTATS_MAX

    @classmethod
    def depuis_la_configuration(cls, config: Mapping[str, Any]) -> "Reglages":
        return cls(
            groupe_min=int(config.get("mouvement_groupe_min", GROUPE_MIN)),
            rarete_max_pct=float(config.get("mouvement_rarete_max_pct",
                                            RARETE_MAX_PCT)),
            typique_min_pct=float(config.get("mouvement_typique_min_pct",
                                             TYPIQUE_MIN_PCT)),
            droits_min=int(config.get("mouvement_droits_min", DROITS_MIN)),
            constats_max=int(config.get("mouvement_constats_max",
                                        CONSTATS_MAX)),
        )


@dataclass(frozen=True)
class DroitResiduel:
    """Un droit atypique ici et typique ailleurs, avec ses deux parts.

    Les deux nombres sont rendus, et non un score qui les résumerait : « elle
    est la seule des trente-trois autres » et « quatre-vingt-neuf pour cent de
    l'autre service l'ont » sont deux faits distincts, et c'est leur
    rapprochement qui motive la décision.
    """

    droit: str
    #: Combien des **autres** membres de son groupe le détiennent.
    autres_du_groupe: int
    #: Part des autres membres de son groupe, en pourcentage.
    part_du_groupe: float
    #: Part du groupe d'origine présumé, en pourcentage.
    part_de_l_origine: float


@dataclass(frozen=True)
class Constat:
    """Une personne, un groupe d'origine présumé, et les droits concordants."""

    identite: str
    groupe: str
    effectif: int
    origine: str
    effectif_origine: int
    droits: Tuple[DroitResiduel, ...]

    @property
    def part_minimale(self) -> float:
        """La part la plus faible dans le groupe d'origine.

        Rendue plutôt qu'une moyenne : « chacun de ces sept droits est détenu
        par au moins quatre-vingt-deux pour cent du service » est une phrase
        vérifiable, là où une moyenne se laisse tirer vers le haut par un seul
        droit universel.
        """
        return min(droit.part_de_l_origine for droit in self.droits)

    def en_dict(self) -> Dict[str, Any]:
        return {
            "identite": self.identite,
            "groupe": self.groupe,
            "effectif": self.effectif,
            "origine": self.origine,
            "effectif_origine": self.effectif_origine,
            "part_minimale": round(self.part_minimale, 1),
            "droits": [{"droit": droit.droit,
                        "autres_du_groupe": droit.autres_du_groupe,
                        "part_du_groupe": round(droit.part_du_groupe, 1),
                        "part_de_l_origine": round(droit.part_de_l_origine, 1)}
                       for droit in self.droits],
        }


def _effectifs(groupes: Mapping[str, str]) -> Dict[str, int]:
    effectifs: Dict[str, int] = {}
    for groupe in groupes.values():
        effectifs[groupe] = effectifs.get(groupe, 0) + 1
    return effectifs


def _porteurs_par_droit(groupes: Mapping[str, str],
                        detenus: Mapping[str, Set[str]],
                        droits: Optional[Set[str]] = None
                        ) -> Dict[str, Dict[str, int]]:
    """Combien de membres de chaque groupe détiennent chaque droit.

    Indexé par droit puis par groupe, et pas l'inverse : le calcul qui suit
    cherche, pour un droit donné, le groupe où il est le plus répandu. L'index
    inverse obligerait à parcourir tous les groupes pour chaque droit atypique.

    `droits` restreint le relevé aux droits d'une seule personne : son panneau
    n'a pas besoin de compter les dix mille autres droits du référentiel.
    """
    par_droit: Dict[str, Dict[str, int]] = {}
    for identite, groupe in groupes.items():
        for droit in detenus.get(identite, ()):
            if droits is not None and droit not in droits:
                continue
            par_droit.setdefault(droit, {})
            compte = par_droit[droit]
            compte[groupe] = compte.get(groupe, 0) + 1
    return par_droit


def _origine_la_plus_forte(parts: Mapping[str, int], effectifs: Mapping[str, int],
                           sauf: str) -> Optional[Tuple[str, float]]:
    """Le groupe, autre que celui-ci, où ce droit est le plus répandu."""
    meilleur: Optional[Tuple[str, float]] = None
    for groupe, porteurs in parts.items():
        if groupe == sauf:
            continue
        part = 100.0 * porteurs / effectifs[groupe]
        # La part la plus forte ; à part égale, le nom le plus petit. Deux
        # lectures des mêmes données doivent rendre le même groupe d'origine,
        # et un départage par l'ordre d'un dictionnaire n'en donne aucune
        # garantie.
        if meilleur is None or (-part, groupe) < (-meilleur[1], meilleur[0]):
            meilleur = (groupe, part)
    return meilleur


@dataclass(frozen=True)
class DroitAtypique:
    """Un droit que presque personne d'autre de son groupe ne détient.

    L'autre groupe où il est le plus répandu est rendu **même s'il n'y est pas
    typique** : « personne d'autre ici, 12 % au service Paie » est une
    exception, « personne d'autre ici, 89 % au service Paie » est un droit
    résiduel. Les deux se lisent, et c'est le lecteur qui voit la différence.
    """

    droit: str
    autres_du_groupe: int
    part_du_groupe: float
    #: Le groupe, autre que le sien, où ce droit est le plus répandu ; vide si
    #: aucun autre groupe examiné ne le détient.
    origine: str
    part_de_l_origine: float

    def en_dict(self) -> Dict[str, Any]:
        return {"droit": self.droit,
                "autres_du_groupe": self.autres_du_groupe,
                "part_du_groupe": round(self.part_du_groupe, 1),
                "origine": self.origine,
                "part_de_l_origine": round(self.part_de_l_origine, 1)}


def _atypiques(identite: str, groupe: str, detenus: Mapping[str, Set[str]],
               par_droit: Mapping[str, Mapping[str, int]],
               effectifs: Mapping[str, int],
               reglages: Reglages) -> List[DroitAtypique]:
    """Les droits de cette personne que son groupe ne partage presque pas."""
    effectif = effectifs[groupe]
    trouves: List[DroitAtypique] = []
    for droit in sorted(detenus.get(identite, ())):
        # `par_droit` a été construit sur ces mêmes identités : un droit que
        # celle-ci détient y figure forcément. Aucune garde ici — une branche
        # pour un cas qui ne se produit pas est une branche que personne ne
        # peut éprouver.
        parts = par_droit[droit]
        autres = parts.get(groupe, 0) - 1
        part_du_groupe = 100.0 * autres / (effectif - 1)
        if part_du_groupe > reglages.rarete_max_pct:
            continue
        origine = _origine_la_plus_forte(parts, effectifs, groupe)
        trouves.append(DroitAtypique(
            droit=droit, autres_du_groupe=autres, part_du_groupe=part_du_groupe,
            origine=origine[0] if origine else "",
            part_de_l_origine=origine[1] if origine else 0.0))
    return trouves


def _constats_de(identite: str, groupe: str, detenus: Mapping[str, Set[str]],
                 par_droit: Mapping[str, Mapping[str, int]],
                 effectifs: Mapping[str, int],
                 reglages: Reglages) -> List[Constat]:
    """Les constats d'une personne : ses droits atypiques, rangés par origine.

    Par groupe d'origine présumé : plusieurs droits qui désignent le même
    groupe font le constat, un droit isolé ne fait rien.
    """
    par_origine: Dict[str, List[DroitResiduel]] = {}
    for atypique in _atypiques(identite, groupe, detenus, par_droit,
                               effectifs, reglages):
        if not atypique.origine or atypique.part_de_l_origine < reglages.typique_min_pct:
            continue
        par_origine.setdefault(atypique.origine, []).append(
            DroitResiduel(droit=atypique.droit,
                          autres_du_groupe=atypique.autres_du_groupe,
                          part_du_groupe=atypique.part_du_groupe,
                          part_de_l_origine=atypique.part_de_l_origine))
    return [Constat(identite=identite, groupe=groupe, effectif=effectifs[groupe],
                    origine=origine, effectif_origine=effectifs[origine],
                    droits=tuple(residuels))
            for origine, residuels in par_origine.items()
            if len(residuels) >= max(reglages.droits_min, 1)]


def _groupes_retenus(effectifs: Mapping[str, int], reglages: Reglages) -> Set[str]:
    """Les groupes assez nombreux pour avoir une habitude."""
    return {groupe for groupe, effectif in effectifs.items()
            if effectif >= max(reglages.groupe_min, 2)}


def ecart_aux_pairs(identite: str, groupes: Mapping[str, str],
                    detenus: Mapping[str, Set[str]],
                    reglages: Optional[Reglages] = None) -> Dict[str, Any]:
    """Ce qu'une seule personne détient que ses pairs n'ont pas.

    Le même calcul que `constats`, restreint à une personne : ses droits
    atypiques — y compris ceux qui ne sont typiques nulle part — et, parmi
    eux, les constats de droits résiduels que l'écran « mouvement » rend pour
    elle. Deux chemins de calcul donneraient deux réponses à la même question.

    `examinee` dit si la comparaison a eu lieu : une personne sans valeur
    d'attribut, ou dans un groupe trop petit, n'a pas de pairs, et une liste
    vide ne voudrait alors pas dire « rien d'atypique ».
    """
    reglages = reglages or Reglages()
    groupe = groupes.get(identite, "")
    effectifs = _effectifs(groupes)
    rendu: Dict[str, Any] = {"groupe": groupe,
                             "effectif": effectifs.get(groupe, 0),
                             "examinee": False, "atypiques": [], "constats": []}
    retenus = _groupes_retenus(effectifs, reglages)
    if groupe not in retenus:
        return rendu
    examinees = {une: son_groupe for une, son_groupe in groupes.items()
                 if son_groupe in retenus}
    par_droit = _porteurs_par_droit(examinees, detenus,
                                    set(detenus.get(identite, ())))
    atypiques = _atypiques(identite, groupe, detenus, par_droit, effectifs, reglages)
    # Le plus rare d'abord, puis le plus typique ailleurs : c'est l'ordre dans
    # lequel on les lit pour décider.
    atypiques.sort(key=lambda un: (un.autres_du_groupe, -un.part_de_l_origine, un.droit))
    trouves = _constats_de(identite, groupe, detenus, par_droit, effectifs, reglages)
    trouves.sort(key=lambda constat: (-len(constat.droits), -constat.part_minimale,
                                      constat.origine))
    rendu.update(examinee=True,
                 atypiques=[un.en_dict() for un in atypiques],
                 constats=[constat.en_dict() for constat in trouves])
    return rendu


def constats(groupes: Mapping[str, str], detenus: Mapping[str, Set[str]],
             reglages: Optional[Reglages] = None) -> List[Constat]:
    """Les personnes qui détiennent des droits typiques d'un autre groupe.

    `groupes` associe chaque identité analysée à la valeur de l'attribut qui
    définit ses pairs — une colonne **choisie par l'utilisateur**, le produit
    n'en connaissant aucune. Les identités sans valeur n'y figurent pas : elles
    n'ont pas de pairs, et leur en inventer reviendrait à les comparer à tout
    le monde.
    """
    reglages = reglages or Reglages()
    effectifs = _effectifs(groupes)
    # Un groupe trop petit n'a pas d'habitude : ni pour dire qu'un droit y est
    # atypique, ni pour dire qu'il est typique ailleurs.
    retenus = _groupes_retenus(effectifs, reglages)
    if not retenus:
        return []
    examinees = {identite: groupe for identite, groupe in groupes.items()
                 if groupe in retenus}
    par_droit = _porteurs_par_droit(examinees, detenus)

    trouves: List[Constat] = []
    for identite, groupe in examinees.items():
        trouves.extend(_constats_de(identite, groupe, detenus, par_droit,
                                    effectifs, reglages))

    # Le plus de droits concordants d'abord : c'est le constat le plus sûr, et
    # celui qu'on veut lire en premier. Puis la part la plus élevée dans le
    # groupe d'origine, puis l'identité — l'ordre doit être total, sans quoi
    # deux lectures des mêmes données rendraient deux listes.
    trouves.sort(key=lambda constat: (-len(constat.droits),
                                      -constat.part_minimale,
                                      constat.identite, constat.origine))
    return trouves


def synthese(groupes: Mapping[str, str], trouves: Sequence[Constat],
             population: int, reglages: Optional[Reglages] = None
             ) -> Dict[str, Any]:
    """Ce que le repérage a regardé, et ce qu'il n'a pas pu regarder.

    Les deux se disent. « Aucun constat » sur une population dont les trois
    quarts n'ont pas de groupe exploitable n'est pas la même information que
    « aucun constat » sur une population entièrement couverte — et les
    confondre ferait conclure à un référentiel sain.
    """
    reglages = reglages or Reglages()
    effectifs = _effectifs(groupes)
    plancher = max(reglages.groupe_min, 2)
    examinees = sum(effectif for effectif in effectifs.values()
                    if effectif >= plancher)
    return {
        "population": population,
        # Les identités rattachées à un groupe assez nombreux pour dire
        # quelque chose. Le reste — sans valeur, ou dans un groupe trop petit —
        # n'est pas analysé, et le taire ferait lire la liste comme complète.
        "examinees": examinees,
        "groupes": len(effectifs),
        "groupes_retenus": sum(1 for effectif in effectifs.values()
                               if effectif >= plancher),
        "identites_concernees": len({constat.identite for constat in trouves}),
        "constats": len(trouves),
        "tronquee": len(trouves) > reglages.constats_max,
    }
