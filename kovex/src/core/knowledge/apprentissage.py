# Fichier : src/core/knowledge/apprentissage.py
"""« Ce candidat ressemble à ce que vous validez » — appris des décisions du workspace.

Chaque validation et chaque refus d'un candidat du mining est consigné avec
les chiffres que la personne avait sous les yeux (lot 37). Ce module apprend de
cet historique, localement : une régression logistique sur cinq grandeurs du
candidat, quelques millisecondes de calcul, aucun réseau, aucun modèle de
langue. Le marché fait la même chose dans son cloud (Saviynt entraîne un modèle
par client) ; ici, il tient dans le workspace et se recalcule à chaque lecture.

Quatre règles, posées dans la note du 13 septembre :

1. **le score porte son nom.** Ce n'est pas une « confiance » ni un risque :
   c'est la probabilité que *vous* validiez un candidat qui a ces chiffres,
   estimée sur *vos* décisions ;
2. **il est réfutable.** Le modèle est mesuré à rebours, décision par
   décision, en le réentraînant sans elle : combien il en aurait prédit juste,
   et combien la simple proportion majoritaire en aurait deviné. Un modèle qui
   ne fait pas mieux que la majorité le dit ;
3. **il est décomposable.** Chaque score vient avec ce qui le tire vers le haut
   et vers le bas, grandeur par grandeur. « Surtout à cause du sur-octroi » se
   vérifie ; « 0,82 » ne se vérifie pas ;
4. **il ne décide rien, et il se désapprend.** Il ordonne l'attention, il
   n'agit pas. Chaque décision peut être retirée de l'apprentissage, toutes
   d'un coup aussi, et rien n'est conservé d'autre que ce choix : le modèle se
   reconstruit à chaque lecture depuis l'historique visible.

Le démarrage à froid s'écrit en chiffres : « 12 décisions sur les 40
nécessaires ». Les seuils sont des réglages du workspace.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

VALIDEE = "validee"
REJETEE = "rejetee"

#: Valeurs de départ des réglages, remplaçables par le workspace.
DECISIONS_MIN = 40
PAR_VERDICT_MIN = 10
REGULARISATION = 1.0

#: Itérations de Newton au plus. Cinq grandeurs et une régularisation : la
#: convergence est atteinte en moins de dix pas sur tout historique réel ; la
#: borne protège d'une donnée pathologique, elle n'est pas un réglage.
ITERATIONS_MAX = 50
TOLERANCE = 1e-9


def _log(valeur: float) -> float:
    return math.log1p(max(0.0, float(valeur)))


def _part_du_sur_octroi(indicateurs: Mapping[str, Any]) -> Optional[float]:
    attributions = float(indicateurs["right_count"]) * float(indicateurs["user_count"])
    if attributions <= 0:
        return None
    return float(indicateurs["over_granted"]) / attributions


#: Les grandeurs, dans l'ordre : leur nom (celui de l'écran), les indicateurs
#: dont elles ont besoin, et leur transformation. Les tailles passent au
#: logarithme : un rôle de 400 porteurs n'est pas dix fois plus « gros » qu'un
#: rôle de 40 au sens où une décision le perçoit.
GRANDEURS: Tuple[Tuple[str, Tuple[str, ...], Any], ...] = (
    ("droits", ("right_count",), lambda ind: _log(ind["right_count"])),
    ("porteurs", ("user_count",), lambda ind: _log(ind["user_count"])),
    ("sur_octroi", ("over_granted", "right_count", "user_count"), _part_du_sur_octroi),
    ("adherence", ("fit_pct",), lambda ind: float(ind["fit_pct"]) / 100.0),
    ("redondance", ("redundancy_pct",), lambda ind: float(ind["redundancy_pct"]) / 100.0),
)


@dataclass(frozen=True)
class Reglages:
    decisions_min: int = DECISIONS_MIN
    par_verdict_min: int = PAR_VERDICT_MIN
    regularisation: float = REGULARISATION

    @classmethod
    def depuis_la_configuration(cls, config) -> "Reglages":
        return cls(
            decisions_min=max(2, int(config.get("apprentissage_decisions_min", DECISIONS_MIN))),
            par_verdict_min=max(1, int(config.get("apprentissage_par_verdict_min",
                                                  PAR_VERDICT_MIN))),
            regularisation=max(0.0, float(config.get("apprentissage_regularisation",
                                                     REGULARISATION))),
        )


def vecteur(indicateurs: Mapping[str, Any]) -> Tuple[Optional[List[float]], List[str]]:
    """Les grandeurs d'un candidat, ou la liste de celles qui manquent.

    Une grandeur manquante n'est pas remplacée par zéro : un sur-octroi non
    mesuré n'est pas un sur-octroi nul, et le score dirait le contraire de la
    vérité.
    """
    valeurs: List[float] = []
    manquantes: List[str] = []
    for nom, besoins, transformer in GRANDEURS:
        if any(not isinstance(indicateurs.get(cle), (int, float))
               or isinstance(indicateurs.get(cle), bool) for cle in besoins):
            manquantes.append(nom)
            continue
        valeur = transformer(indicateurs)
        if valeur is None:
            manquantes.append(nom)
            continue
        valeurs.append(float(valeur))
    return (None if manquantes else valeurs), manquantes


def _ajuster(X: np.ndarray, y: np.ndarray, regularisation: float) -> np.ndarray:
    """Régression logistique régularisée (L2, sans pénaliser l'ordonnée), par Newton.

    Déterministe : mêmes décisions, mêmes coefficients, à l'arrondi flottant
    près. Aucun tirage, aucune initialisation aléatoire.
    """
    n, p = X.shape
    Xb = np.hstack([np.ones((n, 1)), X])
    beta = np.zeros(p + 1)
    penalite = np.eye(p + 1) * regularisation
    penalite[0, 0] = 0.0
    for _ in range(ITERATIONS_MAX):
        probabilites = 1.0 / (1.0 + np.exp(-(Xb @ beta)))
        poids = probabilites * (1.0 - probabilites)
        gradient = Xb.T @ (y - probabilites) - penalite @ beta
        hessienne = (Xb.T * poids) @ Xb + penalite
        pas = np.linalg.solve(hessienne + np.eye(p + 1) * 1e-9, gradient)
        beta = beta + pas
        if float(np.max(np.abs(pas))) < TOLERANCE:
            break
    return beta


@dataclass
class Modele:
    """Ce qui a été appris : de quoi scorer, et de quoi le vérifier."""

    moyennes: np.ndarray
    ecarts: np.ndarray
    coefficients: np.ndarray

    def standardiser(self, valeurs: Sequence[float]) -> np.ndarray:
        return (np.asarray(valeurs, dtype=float) - self.moyennes) / self.ecarts

    def probabilite(self, valeurs: Sequence[float]) -> float:
        z = self.standardiser(valeurs)
        return float(1.0 / (1.0 + math.exp(-(self.coefficients[0] + z @ self.coefficients[1:]))))

    def contributions(self, valeurs: Sequence[float]) -> List[Dict[str, Any]]:
        """Ce que chaque grandeur ajoute ou retire, en points de log-cote.

        Rangées de la plus forte à la plus faible en valeur absolue : la
        première est la raison principale, dans un sens ou dans l'autre.
        """
        z = self.standardiser(valeurs)
        rendues = [{"grandeur": nom, "contribution": round(float(coefficient * valeur), 3)}
                   for (nom, _, _), coefficient, valeur
                   in zip(GRANDEURS, self.coefficients[1:], z)]
        rendues.sort(key=lambda une: (-abs(une["contribution"]), une["grandeur"]))
        return rendues


def entrainer(X: np.ndarray, y: np.ndarray, regularisation: float) -> Modele:
    moyennes = X.mean(axis=0)
    ecarts = X.std(axis=0)
    # Une grandeur constante dans l'historique n'apprend rien : son écart est
    # ramené à un pour que sa contribution soit nulle, sans division par zéro.
    ecarts = np.where(ecarts > 0, ecarts, 1.0)
    return Modele(moyennes, ecarts, _ajuster((X - moyennes) / ecarts, y, regularisation))


def _exemples(decisions: Sequence[Mapping[str, Any]]):
    """Les décisions qui servent : un verdict connu, les cinq grandeurs, non exclues."""
    retenues, exclues, incompletes = [], 0, 0
    for decision in decisions:
        if decision.get("verdict") not in (VALIDEE, REJETEE):
            continue
        if decision.get("exclue_de_l_apprentissage"):
            exclues += 1
            continue
        valeurs, _ = vecteur(decision.get("indicateurs") or {})
        if valeurs is None:
            incompletes += 1
            continue
        retenues.append((valeurs, 1.0 if decision["verdict"] == VALIDEE else 0.0))
    return retenues, exclues, incompletes


def mesurer_a_rebours(X: np.ndarray, y: np.ndarray, regularisation: float) -> Dict[str, Any]:
    """Chaque décision prédite par un modèle qui ne l'a pas vue.

    C'est ce qui rend le score réfutable. La référence est le verdict le plus
    fréquent de l'historique : « deviner toujours la même chose » est ce que
    tout score doit battre pour valoir quelque chose. Elle est comptée sur
    l'historique entier, et non décision par décision : retirer une décision
    d'un historique équilibré ferait basculer la majorité contre elle à chaque
    fois, et la référence tomberait à zéro sans rien mesurer.
    """
    justes = 0
    for rang in range(len(y)):
        garder = np.arange(len(y)) != rang
        modele = entrainer(X[garder], y[garder], regularisation)
        predit = modele.probabilite(X[rang]) >= 0.5
        justes += int(predit == bool(y[rang]))
    validees = int(y.sum())
    majorite = max(validees, int(len(y)) - validees)
    return {"decisions": int(len(y)), "justes": justes, "majorite": majorite,
            "meilleur_que_la_majorite": justes > majorite}


def apprendre(decisions: Sequence[Mapping[str, Any]], reglages: Reglages,
              mesurer: bool = True) -> Dict[str, Any]:
    """L'état de l'apprentissage, et le modèle s'il y a de quoi apprendre.

    `mesurer` refait la mesure à rebours — un modèle par décision. L'écran de
    l'apprentissage la montre ; le score des candidats n'en a pas besoin.
    """
    retenues, exclues, incompletes = _exemples(decisions)
    validees = sum(1 for _, verdict in retenues if verdict)
    etat: Dict[str, Any] = {
        "decisions": len(retenues), "validees": validees,
        "rejetees": len(retenues) - validees,
        "exclues": exclues, "incompletes": incompletes,
        "decisions_min": reglages.decisions_min,
        "par_verdict_min": reglages.par_verdict_min,
        "grandeurs": [nom for nom, _, _ in GRANDEURS],
        "pret": False, "mesure": None, "modele": None,
        "porteurs_de_l_historique": None, "toile_des_validees": None,
        "axes_de_la_toile": list(AXES_DE_LA_TOILE),
    }
    if (len(retenues) < reglages.decisions_min
            or min(validees, len(retenues) - validees) < reglages.par_verdict_min):
        return etat
    X = np.array([valeurs for valeurs, _ in retenues], dtype=float)
    y = np.array([verdict for _, verdict in retenues], dtype=float)
    etat["modele"] = entrainer(X, y, reglages.regularisation)
    # La toile de référence : la forme moyenne de ce que vous avez validé,
    # sur les mêmes axes. C'est à elle que la toile d'un candidat se compare.
    porteurs = np.sort(X[:, 1])
    etat["porteurs_de_l_historique"] = porteurs
    toiles = [toile(ligne, porteurs) for ligne, verdict in zip(X, y) if verdict]
    etat["toile_des_validees"] = {axe: round(float(np.mean([une[axe] for une in toiles])), 1)
                                  for axe in AXES_DE_LA_TOILE}
    if mesurer:
        etat["mesure"] = mesurer_a_rebours(X, y, reglages.regularisation)
    etat["pret"] = True
    return etat


#: Les axes de la toile, dans l'ordre du dessin. Tous sur 0-100, tous dans le
#: même sens — plus haut vaut mieux. Mélanger les sens sur une même toile est
#: l'erreur classique du radar : la forme se lirait à l'envers sur un axe.
AXES_DE_LA_TOILE = ("porteurs", "adherence", "sans_sur_octroi", "sans_redondance")


def _borner(valeur: float) -> float:
    return round(min(100.0, max(0.0, valeur)), 1)


def toile(valeurs: Sequence[float], porteurs_de_l_historique: np.ndarray) -> Dict[str, float]:
    """La forme d'un candidat, axe par axe, sur 0-100.

    Aucun axe n'est inventé : ce sont les grandeurs du score. La population
    n'a pas d'échelle absolue — 40 porteurs est beaucoup ici, peu ailleurs —
    et se lit donc en rang : la part des décisions de l'historique qui
    portaient au plus autant de personnes.
    """
    _, porteurs, part_sur_octroi, adherence, redondance = valeurs
    rang = (float(np.searchsorted(porteurs_de_l_historique, porteurs, side="right"))
            / len(porteurs_de_l_historique))
    return {"porteurs": _borner(100.0 * rang),
            "adherence": _borner(100.0 * adherence),
            "sans_sur_octroi": _borner(100.0 * (1.0 - part_sur_octroi)),
            "sans_redondance": _borner(100.0 * (1.0 - redondance))}


def ressemblance(modele: Modele, indicateurs: Mapping[str, Any],
                 porteurs_de_l_historique: Optional[np.ndarray] = None) -> Dict[str, Any]:
    """Le score d'un candidat, avec ce qui le fait, ou ce qui l'en empêche.

    Avec l'historique, la toile du candidat part avec le score : les deux se
    livrent ensemble, jamais le score seul — un analyste qui suit un chiffre
    arrête de regarder, une forme se regarde.
    """
    valeurs, manquantes = vecteur(indicateurs)
    if valeurs is None:
        return {"comparable": False, "manquantes": manquantes}
    rendu = {"comparable": True,
             "probabilite_pct": round(100.0 * modele.probabilite(valeurs), 1),
             "contributions": modele.contributions(valeurs)}
    if porteurs_de_l_historique is not None:
        rendu["toile"] = toile(valeurs, porteurs_de_l_historique)
    return rendu
