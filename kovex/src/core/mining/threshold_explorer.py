# src/core/mining/threshold_explorer.py
"""Exploration du seuil de similarité θ du mining approché.

θ décide du résultat : il arbitre entre la couverture des habilitations et le
sur-octroi — les droits qu'un rôle accorderait à des membres qui ne les
détiennent pas aujourd'hui. La mesure de justesse du moteur montre qu'il n'y a
pas de bonne valeur universelle : sur des données propres θ = 1 restitue
exactement les rôles sous-jacents, alors qu'à 20 % d'habilitations manquantes il
n'en retrouve plus qu'une minorité, là où un θ plus bas les retrouve.

Ce module exécute le mining approché sur une série de seuils fournie par
l'appelant et rend la courbe correspondante, pour que le choix se fasse sur des
chiffres du référentiel réel plutôt que sur une intuition.

Il ne recommande rien de lui-même : il marque les points **non dominés** — un
point est dominé si un autre couvre au moins autant en octroyant au plus autant
en trop — ce qui est un fait mathématique, et il ne désigne un point que si
l'appelant a exprimé une contrainte, par exemple un sur-octroi maximal
acceptable. Le compromis reste une décision de gouvernance.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Sequence

from src.core.mining.approximate_miner import (APPORT_MINIMAL,
                                               PROFILS_CROISES_MAX,
                                               TREILLIS_MAX,
                                               ApproximateRoleMiner)
from src.core.mining.selection_exacte import (DELAI_PAR_DEFAUT_S,
                                              EFFORT_PAR_DEFAUT,
                                              SELECTION_PAR_DEFAUT)

logger = logging.getLogger(__name__)


class ThresholdExplorer:
    """Balaie une série de seuils θ et restitue la courbe couverture / sur-octroi."""

    def __init__(self, loader):
        self.loader = loader

    @staticmethod
    def _normaliser(thresholds: Sequence[float]) -> List[float]:
        """Valide, dédoublonne et ordonne les seuils du plus strict au plus lâche."""
        if not thresholds:
            raise ValueError("au moins un seuil est requis")

        uniques = set()
        for seuil in thresholds:
            valeur = float(seuil)
            if not 0.0 < valeur <= 1.0:
                raise ValueError("chaque seuil doit appartenir à ]0, 1]")
            uniques.add(round(valeur, 4))
        return sorted(uniques, reverse=True)

    @staticmethod
    def front_de_pareto(points: Sequence[Dict[str, Any]]) -> List[float]:
        """Seuils dont aucun autre point ne fait strictement mieux.

        Un point est dominé lorsqu'un autre couvre au moins autant
        d'habilitations en en octroyant au plus autant en trop, et qu'il est
        strictement meilleur sur au moins un des deux critères.

        Le sur-octroi se compare **en valeur absolue** et non en part. Il était
        rapporté à la somme de ce que les rôles retenus accordent — un
        dénominateur qui grandit avec le nombre de rôles. Un seuil qui en
        retient davantage gonflait donc le sien, et pouvait afficher un taux
        plus bas *tout en sur-octroyant davantage* : la domination annoncée
        n'était pas une propriété, c'était un artefact de dénominateur.

        Les deux points comparés décrivent le même référentiel : leurs nombres
        d'habilitations en trop sont directement comparables, sans être rapportés
        à quoi que ce soit.
        """
        def en_trop(point: Dict[str, Any]) -> float:
            return float(point["over_granted"])

        retenus: List[float] = []
        for point in points:
            domine = any(
                autre is not point
                and autre["coverage_pct"] >= point["coverage_pct"]
                and en_trop(autre) <= en_trop(point)
                and (
                    autre["coverage_pct"] > point["coverage_pct"]
                    or en_trop(autre) < en_trop(point)
                )
                for autre in points
            )
            if not domine:
                retenus.append(point["threshold"])
        return retenus

    @staticmethod
    def _sous_contrainte(
        points: Sequence[Dict[str, Any]], max_over_granted_pct: Optional[float]
    ) -> Optional[Dict[str, Any]]:
        """Meilleur point respectant la contrainte de sur-octroi de l'appelant.

        Critère : couverture maximale ; à couverture égale, le moins de rôles ;
        puis le seuil le plus strict. Sans contrainte, rien n'est désigné.
        """
        if max_over_granted_pct is None:
            return None

        eligibles = [
            point for point in points
            if point["over_granted_pct"] <= max_over_granted_pct
        ]
        if not eligibles:
            return None

        return max(
            eligibles,
            key=lambda point: (point["coverage_pct"], -point["roles"], point["threshold"]),
        )

    def scan(
        self,
        thresholds: Sequence[float],
        min_users: int,
        min_rights: int,
        max_roles: int,
        excluded_rights: Optional[Sequence[str]] = None,
        max_over_granted_pct: Optional[float] = None,
        generateurs: Optional[Sequence[str]] = None,
        profils_croises_max: int = PROFILS_CROISES_MAX,
        apport_minimal: int = APPORT_MINIMAL,
        selection: str = SELECTION_PAR_DEFAUT,
        selection_effort: int = EFFORT_PAR_DEFAUT,
        selection_delai_s: float = DELAI_PAR_DEFAUT_S,
        treillis_max: int = TREILLIS_MAX,
    ) -> Dict[str, Any]:
        """Exécute le mining approché sur chaque seuil et rend la courbe.

        Args:
            thresholds: seuils à évaluer, dans ]0, 1]. Dédoublonnés et ordonnés
                du plus strict au plus lâche.
            min_users, min_rights, max_roles: mêmes bornes qu'un mining ordinaire ;
                le balayage doit être comparable à ce que produira l'exécution.
            excluded_rights: droits ignorés, droits socles compris.
            max_over_granted_pct: sur-octroi maximal acceptable, exprimé par
                l'utilisateur. Sans lui, aucun point n'est désigné.
            generateurs, profils_croises_max, apport_minimal: les trois autres
                réglages qui changent le résultat d'un mining. Ils n'étaient
                pas transmis : la phrase « le balayage doit être comparable à
                ce que produira l'exécution », deux lignes plus haut, était
                fausse. L'utilisateur choisissait un point, relançait le mining
                avec ses propres réglages, et obtenait autre chose — sans que
                rien ne dise laquelle des deux mesures décrivait son
                référentiel.
            selection, selection_effort, selection_delai_s: la façon de
                choisir les rôles parmi les candidats, pour la même raison.
                La sélection exacte ne joue qu'à θ = 1 ; chaque point dit ce
                qu'elle a fait (`selection_arret`).
            treillis_max: la borne du treillis, pour la même raison ; chaque
                point dit s'il l'a atteinte (`treillis_borne`).

        Returns:
            {"points": [...], "undominated": [...], "selected": {...} | None,
             "constraint": {...}, "total_assignments": int, "elapsed_ms": int}
        """
        seuils = self._normaliser(thresholds)
        if max_over_granted_pct is not None and max_over_granted_pct < 0:
            raise ValueError("max_over_granted_pct doit être positif ou nul")

        moteur = ApproximateRoleMiner(self.loader)
        points: List[Dict[str, Any]] = []
        total_assignments = 0
        debut_total = time.perf_counter()

        for seuil in seuils:
            debut = time.perf_counter()
            resultat = moteur.mine(
                similarity_threshold=seuil,
                min_users=min_users,
                min_rights=min_rights,
                excluded_rights=list(excluded_rights or ()),
                max_roles=max_roles,
                generateurs=generateurs,
                profils_croises_max=profils_croises_max,
                apport_minimal=apport_minimal,
                selection=selection,
                selection_effort=selection_effort,
                selection_delai_s=selection_delai_s,
                treillis_max=treillis_max,
            )
            stats = resultat["stats"]
            total_assignments = max(total_assignments, stats["total_assignments"])
            points.append({
                "threshold": seuil,
                "roles": len(resultat["roles"]),
                "coverage_pct": stats["coverage_pct"],
                "covered_assignments": stats["covered_assignments"],
                "over_granted": stats["over_granted"],
                "over_granted_pct": stats["over_granted_pct"],
                "users_covered": stats["users_covered"],
                "rights_covered": stats["rights_covered"],
                # Le plafond de rôles a été atteint : la courbe est bornée par
                # ce plafond et non par le référentiel. L'IHM doit le signaler,
                # sans quoi le point est lu comme un résultat du moteur.
                "capped": len(resultat["roles"]) >= max_roles,
                # Ce que la sélection a fait à ce seuil : le nombre de rôles
                # du point n'est pas celui du glouton quand elle a joué.
                "selection_arret": stats["selection_arret"],
                "selection_roles_glouton": stats["selection_roles_glouton"],
                # Le treillis s'est arrêté sur sa borne à ce seuil : le nombre
                # de rôles du point n'est pas le plus petit possible.
                "treillis_borne": stats["treillis_borne"],
                "elapsed_ms": int(round((time.perf_counter() - debut) * 1000)),
            })

        logger.info(
            "Exploration du seuil : %d points calculés entre θ=%.2f et θ=%.2f",
            len(points), seuils[-1], seuils[0],
        )

        return {
            "points": points,
            "undominated": self.front_de_pareto(points),
            "selected": self._sous_contrainte(points, max_over_granted_pct),
            "constraint": {"max_over_granted_pct": max_over_granted_pct},
            "total_assignments": total_assignments,
            "elapsed_ms": int(round((time.perf_counter() - debut_total) * 1000)),
        }
