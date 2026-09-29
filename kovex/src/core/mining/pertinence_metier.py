# src/core/mining/pertinence_metier.py
"""Ce qu'un rôle applicatif veut dire pour un responsable d'application.

Le mining applicatif rend un ensemble de droits et une population. Ni l'un ni
l'autre ne dit *pourquoi* ces personnes vont ensemble. Un modèle peut être
compact, peu redondant, bien hiérarchisé — et rester invalidable, parce que
personne ne signe une liste de droits accordée à une population qu'il ne sait
pas décrire.

Ce module répond à une seule question, a posteriori, sur un rôle déjà trouvé :
**qu'ont en commun ses porteurs que le reste de la population n'a pas ?**

Un rôle **métier** ne pose pas cette question : il est né d'une règle sur les
attributs, et cette règle *est* sa définition. Lui chercher une règle
retournerait celle qui a servi à le construire — un écran qui se donne raison
tout seul. Ce module lui rend donc seulement le diagnostic, bâti sur ses
propres chiffres (voir `diagnostiquer_un_role_metier`).

La réponse prend la forme d'une règle — une conjonction de valeurs
d'attributs, « Comptabilité *et* cadre » — accompagnée de ce qu'elle coûte.
Une règle n'est pas un constat : elle désigne une population. Deux chiffres,
et deux seulement, disent ce qu'elle vaut, et ils s'opposent :

- la **pureté** : parmi les personnes que la règle désigne, la part qui est
  effectivement porteuse du rôle. Son complément est le sur-octroi qu'on
  accepterait en appliquant la règle telle quelle ;
- la **couverture** : parmi les porteurs du rôle, la part que la règle
  désigne. Son complément est le nombre d'exceptions, c'est-à-dire les
  porteurs que la règle n'explique pas.

Ajouter un terme à la règle fait monter la pureté et baisser la couverture.
Le module ne tranche pas ce compromis : il rend la règle **la plus pure qui
explique encore au moins la part de porteurs exigée par l'appelant**. C'est la
même ligne de conduite que l'exploration de seuil : on ne désigne un point que
sous une contrainte exprimée.

Deux garde-fous, sans lesquels le résultat serait au mieux inutile, au pire
trompeur.

Les deux répondent à des questions différentes, et il faut les deux.

**La significativité — « est-ce réel ? »** Une pureté de 100 % sur trois
porteurs est un hasard courant ; sur trois cents, elle ne l'est pas. La
probabilité d'observer au moins cette concordance par tirage aléatoire sans
remise se calcule exactement (loi hypergéométrique). Un petit rôle devra donc
être bien plus pur qu'un grand pour mériter la même conclusion.

**Le lift — « est-ce utile ? »** Si 92 % des identités portent la mention
« actif », alors « 92 % des porteurs sont actifs » n'explique rien. Le lift
rapporte la pureté de la règle à celle d'un tirage au hasard : à 1, la règle
n'apprend rien.

Sur un grand référentiel, une régularité minuscule devient statistiquement
certaine : 51 % de porteurs là où le hasard en donnerait 50 %, mesuré sur
neuf mille personnes, a une p-valeur écrasante et un lift de 1,02. C'est un
fait, et ce n'est pas une règle métier. La significativité seule laisserait
passer ce genre d'explication, d'autant plus facilement que le référentiel est
gros — exactement là où le produit doit servir. Le lift minimal est donc une
contrainte à part entière, exprimée par l'appelant.

C'est aussi ce qui écarte par le calcul les colonnes sans pouvoir explicatif,
plutôt que par une liste de noms de colonnes interdits : les colonnes ne sont
pas connues à l'avance.

Ce module ne nomme pas les rôles. Un libellé fabriqué à partir des attributs
serait un texte généré, donc non traduisible, et donnerait à une corrélation
l'apparence d'une décision. Le produit propose la règle ; c'est un humain qui
nomme.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy.stats import hypergeom

logger = logging.getLogger(__name__)

#: Valeur de code réservée aux attributs non renseignés. Une valeur absente
#: n'explique rien : elle ne peut ni former un terme de règle, ni compter
#: parmi les porteurs qu'un terme désigne.
_ABSENT = -1


class ReferentielDAttributs:
    """Les attributs des identités, encodés une fois pour tout un lot de rôles.

    Chaque colonne devient un tableau d'entiers : une valeur distincte, un
    code. Compter les porteurs d'une valeur dans un sous-ensemble revient
    alors à un ``bincount`` sur les rangs de ce sous-ensemble, quel que soit
    le nombre de rôles à expliquer. Sans cet encodage, chaque rôle rebalaierait
    le référentiel entier, une fois par attribut.
    """

    def __init__(self, identites, colonne_identite: str,
                 attributs: Sequence[str]) -> None:
        colonnes = list(identites.columns) if identites is not None else []
        if colonne_identite not in colonnes:
            raise ValueError(
                f"Colonne d'identité absente du référentiel : {colonne_identite}")

        inconnus = [nom for nom in attributs if nom not in colonnes]
        if inconnus:
            raise ValueError(
                f"Attributs absents du référentiel : {', '.join(sorted(inconnus))}")

        self.attributs: List[str] = [nom for nom in attributs
                                     if nom != colonne_identite]
        self.total = int(len(identites))
        self._rang_par_identifiant: Dict[str, int] = {
            str(valeur): rang
            for rang, valeur in enumerate(identites[colonne_identite].tolist())
        }

        self._codes: Dict[str, np.ndarray] = {}
        self._libelles: Dict[str, List[str]] = {}
        self._effectifs: Dict[str, np.ndarray] = {}
        for nom in self.attributs:
            codes, libelles = _encoder(identites[nom])
            self._codes[nom] = codes
            self._libelles[nom] = libelles
            self._effectifs[nom] = _compter(codes, len(libelles))

    # ---------------------------------------------------------------- accès

    def rangs(self, identifiants: Sequence[Any]) -> np.ndarray:
        """Rangs des identités connues, dans l'ordre du référentiel.

        Un identifiant absent du référentiel est ignoré : un rôle peut porter
        des utilisateurs que le fichier d'identités ne décrit pas, et ce sont
        alors des porteurs qu'aucune règle ne peut expliquer.
        """
        rangs = [self._rang_par_identifiant[str(identifiant)]
                 for identifiant in identifiants
                 if str(identifiant) in self._rang_par_identifiant]
        return np.unique(np.asarray(rangs, dtype=np.int64))

    def codes(self, attribut: str) -> np.ndarray:
        return self._codes[attribut]

    def libelle(self, attribut: str, code: int) -> str:
        return self._libelles[attribut][code]

    def effectifs(self, attribut: str) -> np.ndarray:
        """Effectif de chaque valeur dans la population entière."""
        return self._effectifs[attribut]


def _encoder(colonne) -> Tuple[np.ndarray, List[str]]:
    """Associe un code entier à chaque valeur distincte, ``_ABSENT`` aux vides."""
    libelles: List[str] = []
    index: Dict[str, int] = {}
    codes = np.full(len(colonne), _ABSENT, dtype=np.int64)
    for rang, valeur in enumerate(colonne.tolist()):
        if valeur is None or (isinstance(valeur, float) and np.isnan(valeur)):
            continue
        texte = str(valeur).strip()
        if not texte:
            continue
        code = index.get(texte)
        if code is None:
            code = len(libelles)
            index[texte] = code
            libelles.append(texte)
        codes[rang] = code
    return codes, libelles


def _compter(codes: np.ndarray, nombre_de_valeurs: int) -> np.ndarray:
    """Effectif de chaque code, les absents écartés."""
    if nombre_de_valeurs == 0:
        return np.zeros(0, dtype=np.int64)
    presents = codes[codes >= 0]
    return np.bincount(presents, minlength=nombre_de_valeurs).astype(np.int64)


# ------------------------------------------------------------------ mesures


def _mesurer(porteurs_designes: np.ndarray, designes: np.ndarray,
             porteurs: int, total: int) -> Dict[str, np.ndarray]:
    """Pureté, couverture, lift et p-valeur, pour un lot de candidats.

    ``porteurs_designes`` et ``designes`` sont deux tableaux de même longueur :
    pour chaque candidat, le nombre de porteurs qu'il désigne et le nombre de
    personnes qu'il désigne en tout.

    La p-valeur est la probabilité d'observer *au moins* autant de porteurs en
    tirant au hasard le même nombre de personnes dans la même population.
    C'est une loi hypergéométrique — tirage sans remise — et non binomiale :
    sur des effectifs de quelques dizaines dans une population de quelques
    milliers, l'écart n'est pas négligeable, et il va dans le sens permissif.
    """
    purete = np.divide(porteurs_designes, designes,
                       out=np.zeros(len(designes), dtype=float),
                       where=designes > 0)
    couverture = porteurs_designes / porteurs
    reference = porteurs / total
    return {
        "purete": purete,
        "couverture": couverture,
        "lift": purete / reference,
        "p_valeur": hypergeom.sf(porteurs_designes - 1, total, porteurs, designes),
    }


# ------------------------------------------------------------- construction


def expliquer_un_role(
    referentiel: ReferentielDAttributs,
    identifiants: Sequence[Any],
    *,
    couverture_minimale: float,
    lift_minimal: float,
    profondeur: int,
    signification_maximale: float,
) -> Dict[str, Any]:
    """Cherche la règle la plus pure qui explique assez de porteurs.

    La construction est gloutonne et bornée : à chaque tour, on ajoute le
    terme qui fait le plus monter la pureté, parmi ceux qui laissent la
    couverture au-dessus de la contrainte et dont la concordance n'est pas
    attribuable au hasard. On s'arrête quand aucun terme ne remplit ces trois
    conditions, ou à la profondeur demandée.

    Le glouton ne rend pas la meilleure règle possible : il rend une règle
    dont chaque terme se justifie seul, ce qui est la condition pour qu'un
    responsable d'application puisse la lire et la contester. Une recherche
    exhaustive sur toutes les conjonctions serait exponentielle en nombre
    d'attributs, et rendrait des règles que personne ne saurait défendre.
    """
    total = referentiel.total
    rangs = referentiel.rangs(identifiants)
    porteurs = int(rangs.size)
    if porteurs == 0 or total == 0:
        return _sans_regle(porteurs, total, len(identifiants))

    est_porteur = np.zeros(total, dtype=bool)
    est_porteur[rangs] = True

    designes = np.ones(total, dtype=bool)
    termes: List[Dict[str, Any]] = []
    restants = list(referentiel.attributs)
    purete_courante = porteurs / total

    for _ in range(profondeur):
        meilleur = _meilleur_terme(
            referentiel, restants, designes, est_porteur, porteurs, total,
            couverture_minimale=couverture_minimale,
            lift_minimal=lift_minimal,
            purete_a_battre=purete_courante,
            signification_maximale=signification_maximale,
        )
        if meilleur is None:
            break
        termes.append(meilleur["terme"])
        designes = meilleur["designes"]
        purete_courante = meilleur["purete"]
        restants.remove(meilleur["terme"]["attribut"])

    return _restituer(termes, designes, est_porteur, porteurs, total,
                      len(identifiants))


def _meilleur_terme(
    referentiel: ReferentielDAttributs,
    restants: Sequence[str],
    designes: np.ndarray,
    est_porteur: np.ndarray,
    porteurs: int,
    total: int,
    *,
    couverture_minimale: float,
    lift_minimal: float,
    purete_a_battre: float,
    signification_maximale: float,
) -> Optional[Dict[str, Any]]:
    """Le terme qui fait le plus monter la pureté, ou rien s'il n'y en a pas.

    Le départage est complet et ne dépend d'aucun ordre de parcours : pureté,
    puis couverture, puis nom d'attribut, puis valeur. Deux exécutions sur les
    mêmes données rendent la même règle.
    """
    rangs_designes = np.flatnonzero(designes)
    rangs_porteurs = rangs_designes[est_porteur[rangs_designes]]

    candidats: List[Tuple[float, float, str, str, np.ndarray]] = []
    for attribut in restants:
        codes = referentiel.codes(attribut)
        nombre = referentiel.effectifs(attribut).size
        effectif_designe = _compter(codes[rangs_designes], nombre)
        effectif_porteur = _compter(codes[rangs_porteurs], nombre)

        mesures = _mesurer(effectif_porteur, effectif_designe, porteurs, total)
        retenus = np.flatnonzero(
            (effectif_designe > 0)
            & (mesures["couverture"] >= couverture_minimale)
            & (mesures["lift"] >= lift_minimal)
            & (mesures["purete"] > purete_a_battre)
            & (mesures["p_valeur"] <= signification_maximale)
        )
        for code in retenus:
            candidats.append((
                float(mesures["purete"][code]),
                float(mesures["couverture"][code]),
                attribut,
                referentiel.libelle(attribut, int(code)),
                designes & (codes == code),
            ))

    if not candidats:
        return None

    candidats.sort(key=lambda c: (-c[0], -c[1], c[2], c[3]))
    purete, _couverture, attribut, valeur, masque = candidats[0]
    return {
        "terme": {"attribut": attribut, "valeur": valeur},
        "designes": masque,
        "purete": purete,
    }


# -------------------------------------------------------------- restitution


def _sans_regle(porteurs: int, total: int, demandes: int) -> Dict[str, Any]:
    """Réponse pour un rôle qu'aucune règle ne peut décrire.

    Un rôle sans porteur connu du référentiel d'identités n'est pas un rôle
    mal expliqué : il est hors de portée de la mesure. Le distinguer d'un rôle
    inexpliqué évite de faire passer une absence de donnée pour un mauvais
    résultat.
    """
    return {
        "regle": [],
        "explicable": False,
        "porteurs": porteurs,
        "porteurs_hors_referentiel": demandes - porteurs,
        "designes": total if porteurs else 0,
        "porteurs_designes": porteurs,
        "purete": 0.0,
        "couverture": 0.0,
        "lift": 0.0,
        "p_valeur": 1.0,
        "exceptions": porteurs,
        "sur_octroi": 0,
    }


def _restituer(termes: List[Dict[str, Any]], designes: np.ndarray,
               est_porteur: np.ndarray, porteurs: int, total: int,
               demandes: int) -> Dict[str, Any]:
    """Met en forme la règle trouvée et ce qu'elle laisse de côté.

    ``exceptions`` et ``sur_octroi`` sont rendus avec la règle et non calculés
    par l'appelant : ce sont eux qui décident si un responsable la valide, et
    une règle présentée sans eux se lit comme une certitude.
    """
    nombre_designes = int(np.count_nonzero(designes))
    nombre_porteurs_designes = int(np.count_nonzero(designes & est_porteur))
    mesures = _mesurer(np.array([nombre_porteurs_designes]),
                       np.array([nombre_designes]), porteurs, total)
    return {
        "regle": termes,
        "explicable": bool(termes),
        "porteurs": porteurs,
        "porteurs_hors_referentiel": demandes - porteurs,
        "designes": nombre_designes,
        "porteurs_designes": nombre_porteurs_designes,
        "purete": float(mesures["purete"][0]),
        "couverture": float(mesures["couverture"][0]),
        "lift": float(mesures["lift"][0]),
        "p_valeur": float(mesures["p_valeur"][0]),
        "exceptions": porteurs - nombre_porteurs_designes,
        "sur_octroi": nombre_designes - nombre_porteurs_designes,
    }


def expliquer_les_roles(
    roles: Sequence[Dict[str, Any]],
    referentiel: ReferentielDAttributs,
    *,
    couverture_minimale: float,
    fiabilite_attendue: float,
    lift_minimal: float,
    profondeur: int,
    signification_maximale: float,
) -> Dict[str, Any]:
    """Explique chaque rôle et rend la part du modèle qui l'est.

    ``part_explicable`` porte sur les rôles, pas sur les habilitations : c'est
    la question que se pose un comité de validation devant une liste de rôles
    à signer, et non celle du taux de couverture, déjà mesurée ailleurs.
    """
    explications = []
    for role in roles:
        explication = expliquer_un_role(
            referentiel, role.get("users", ()),
            couverture_minimale=couverture_minimale,
            lift_minimal=lift_minimal,
            profondeur=profondeur,
            signification_maximale=signification_maximale,
        )
        explication["role_id"] = role.get("id")
        explication["diagnostic"] = diagnostiquer(
            explication, fiabilite_attendue=fiabilite_attendue)
        explications.append(explication)

    explicables = sum(1 for e in explications if e["explicable"])
    return {
        "explications": explications,
        "roles_expliques": explicables,
        "roles_total": len(explications),
        "part_explicable": explicables / len(explications) if explications else 0.0,
    }


# ---------------------------------------------------------------- diagnostic

#: Verdicts, du plus au moins gênant. L'ordre est celui de la restitution :
#: ce qui empêche de valider se lit avant ce qui rassure.
BLOQUANT = "bloquant"
RESERVE = "reserve"
FAVORABLE = "favorable"

_RANG_DES_VERDICTS = {BLOQUANT: 0, RESERVE: 1, FAVORABLE: 2}


def diagnostiquer(explication: Dict[str, Any], *,
                  fiabilite_attendue: float) -> List[Dict[str, Any]]:
    """Ce qui plaide pour et contre la validation, critère par critère.

    Volontairement pas un score. Un chiffre unique — « 78 % de chances d'être
    validé » — ne peut être ni vérifié ni contesté par la personne qui signe,
    et il donne à une pondération choisie par nous l'autorité d'une mesure.
    Un décideur doit pouvoir s'opposer point par point.

    Chaque constat porte son code, ses chiffres bruts et son verdict. Le
    serveur nomme le constat ; la phrase est composée par le client, dans sa
    langue, et les nombres y sont mis en forme selon cette langue.

    Rien ici n'est une opinion du produit : la fiabilité attendue est celle que
    l'appelant a exprimée, et tous les autres constats sont des faits mesurés.
    """
    constats: List[Dict[str, Any]] = []

    if explication["porteurs_hors_referentiel"]:
        constats.append({
            "code": "explanation.outside_repository",
            "params": {"count": explication["porteurs_hors_referentiel"]},
            "verdict": RESERVE,
        })

    if not explication["explicable"]:
        constats.append({
            "code": "explanation.no_rule",
            "params": {"count": explication["porteurs"]},
            "verdict": BLOQUANT,
        })
        return _ordonner(constats)

    tient = explication["purete"] >= fiabilite_attendue
    constats.append({
        "code": "explanation.reliability",
        "params": {"part": explication["purete"], "attendu": fiabilite_attendue},
        "verdict": FAVORABLE if tient else BLOQUANT,
    })
    constats.append({
        "code": "explanation.explanatory_power",
        "params": {"lift": explication["lift"]},
        "verdict": FAVORABLE,
    })
    constats.append({
        "code": "explanation.not_by_chance",
        "params": {"p": explication["p_valeur"]},
        "verdict": FAVORABLE,
    })

    exceptions = explication["exceptions"]
    constats.append({
        "code": "explanation.exceptions" if exceptions else "explanation.no_exception",
        "params": {"count": exceptions,
                   "part": exceptions / explication["porteurs"]},
        "verdict": RESERVE if exceptions else FAVORABLE,
    })

    sur_octroi = explication["sur_octroi"]
    constats.append({
        "code": "explanation.over_granting" if sur_octroi
                else "explanation.no_over_granting",
        "params": {"count": sur_octroi,
                   "part": sur_octroi / explication["designes"]},
        "verdict": RESERVE if sur_octroi else FAVORABLE,
    })

    return _ordonner(constats)


def _ordonner(constats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Bloquant, puis réserve, puis favorable ; à verdict égal, l'ordre d'ajout.

    Le tri est stable : deux exécutions rendent la même liste, dans le même
    ordre. Un diagnostic qui se réorganise d'un affichage à l'autre se lit
    comme un résultat instable.
    """
    return sorted(constats, key=lambda constat: _RANG_DES_VERDICTS[constat["verdict"]])


#: Au-delà de cette part, les membres laissés de côté par la règle ne sont plus
#: des exceptions dispersées mais un bloc : ils ne détiennent aucun des droits.
#:
#: Le seuil ne sert qu'à formuler le constat — il n'écarte aucun candidat, et
#: rien n'en dépend dans le calcul. Sa valeur vient de la mesure : sur un
#: référentiel exact, aucune règle réelle du banc ne dépasse zéro, et les
#: groupes scindés se situent entre 30 et 86 % (`tests/test_scission.py`). La
#: moitié laisse donc la marge la plus large des deux côtés.
SCISSION_NOTABLE = 0.5


def diagnostiquer_un_role_metier(role: Dict[str, Any], *,
                                 couverture_attendue: float) -> List[Dict[str, Any]]:
    """Ce qui plaide pour et contre la validation d'un rôle métier.

    Un rôle métier est déjà une règle : `service = Compta et statut = Cadre`.
    La question n'est donc pas de savoir ce que ses porteurs ont en commun,
    mais **ce que la règle coûterait appliquée telle quelle** — c'est-à-dire
    exactement ce que le moteur a déjà mesuré.

    ``couverture_attendue`` est la part minimale du groupe qui doit détenir un
    droit pour qu'il entre dans le rôle : la contrainte que l'appelant a
    lui-même exprimée au lancement. Le diagnostic la lui rappelle plutôt que
    d'en inventer une autre.

    Même vocabulaire et même tri que le diagnostic d'un rôle applicatif : un
    comité ne devrait pas avoir à apprendre deux grilles de lecture selon
    l'origine du rôle.
    """
    porteurs = int(role.get("user_count") or 0)
    droits = int(role.get("right_count") or len(role.get("rights") or ()))
    couverture = float(role.get("coverage_pct") or 0.0) / 100.0
    sur_octroi = int(role.get("stats_over_provisioning") or 0)
    accorde = porteurs * droits

    constats: List[Dict[str, Any]] = [{
        "code": "diagnostic.rule_coverage",
        "params": {"part": couverture, "attendu": couverture_attendue},
        "verdict": FAVORABLE if couverture >= couverture_attendue else RESERVE,
    }]

    constats.append({
        "code": "diagnostic.over_provisioning" if sur_octroi
                else "diagnostic.no_over_provisioning",
        "params": {"count": sur_octroi,
                   "part": sur_octroi / accorde if accorde else 0.0},
        "verdict": RESERVE if sur_octroi else FAVORABLE,
    })

    # Une règle RH qui ne désigne qu'une poignée de personnes n'est pas une
    # règle : c'est une exception qu'on a écrite comme une règle.
    constats.append({
        "code": "diagnostic.population",
        "params": {"count": porteurs},
        "verdict": FAVORABLE if porteurs > 1 else BLOQUANT,
    })

    # Comment le groupe se partage devant ces droits. La couverture n'en dit
    # rien : 85 % recouvre « chacun manque un droit sur sept » aussi bien que
    # « un membre sur cinq n'en détient aucun ». Le premier cas est le bruit
    # ordinaire d'un référentiel ; le second n'est pas une règle à exceptions,
    # c'est une population que l'attribut choisi ne décrit pas.
    scission = float(role.get("scission_pct") or 0.0) / 100.0
    hors_noyau = porteurs - round(porteurs * float(role.get("noyau_pct") or 0.0) / 100.0)
    if hors_noyau > 0:
        constats.append({
            "code": ("diagnostic.split_group" if scission >= SCISSION_NOTABLE
                     else "diagnostic.scattered_exceptions"),
            "params": {"count": round(hors_noyau * scission),
                       "total": hors_noyau,
                       "part": scission},
            "verdict": RESERVE if scission >= SCISSION_NOTABLE else FAVORABLE,
        })

    return _ordonner(constats)
