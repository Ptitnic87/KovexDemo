# src/core/mining/consolidation_explorer.py
"""Exploration du seuil de consolidation des rôles.

La consolidation retire les rôles quasi identiques à un rôle mieux classé. Elle
simplifie le modèle, et elle a un prix : les couples (identité, droit) que les
rôles retirés accordaient et que personne ne reprend.

Comme pour le seuil de similarité θ du mining, il n'existe pas de bonne valeur
universelle : elle dépend de la redondance du référentiel, que le produit ne
connaît pas d'avance. Ce module exécute la consolidation sur une série de seuils
fournie par l'appelant et rend la courbe correspondante, pour que le choix se
fasse sur des chiffres plutôt que sur une intuition.

Le mining n'est exécuté qu'**une fois** : la consolidation travaille sur son
résultat. Un balayage complet coûte donc à peine plus qu'un mining seul, là où
l'exploration de θ refait un mining par point.

Ce module ne recommande rien de lui-même. Il ne désigne un point que si
l'appelant a exprimé une contrainte, par exemple une perte maximale acceptable.

Il ne marque pas non plus de points « non dominés », contrairement à
l'explorateur de θ. Sur cette courbe, baisser le seuil retire toujours des rôles
et perd toujours des couples : aucun point n'en domine un autre, et un marqueur
qui répond « oui » partout est du bruit. Ce qui distingue réellement les points,
c'est le **rendement** — combien de rôles on retire par millier de couples
perdus — et surtout son évolution d'un point au suivant : le rendement marginal
décroît, et c'est là que se lit le moment où la simplification cesse de payer.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Sequence

from src.core.mining.role_quality import consolider, mesurer

logger = logging.getLogger(__name__)


class ConsolidationExplorer:
    """Balaie une série de seuils de consolidation sur un ensemble de rôles."""

    def __init__(
        self,
        roles: Sequence[Dict[str, Any]],
        total_assignments: int,
        droits_reels: Optional[Dict[str, Any]] = None,
    ):
        """
        Args:
            roles: rôles candidats issus du mining, dans leur ordre de classement.
            total_assignments: nombre d'habilitations réelles du périmètre.
            droits_reels: droits réellement détenus par identité. Fournis, ils
                rendent couverture et sur-octroi exacts à chaque point.
        """
        self.roles = list(roles)
        self.total_assignments = total_assignments
        self.droits_reels = droits_reels

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
    def _rendements(points: List[Dict[str, Any]]) -> None:
        """Ajoute à chaque point son rendement, cumulé et marginal.

        efficiency : rôles retirés par millier de couples accordés perdus,
            depuis le modèle non consolidé.
        marginal_efficiency : le même rapport, mais depuis le point précédent —
            c'est-à-dire ce que rapporte le fait de relâcher le seuil d'un cran.
            Sa décroissance montre où la simplification cesse de payer. Vaut
            ``None`` sur le premier point, qui n'a pas de précédent, et quand
            un cran ne perd aucun couple.
        """
        precedent: Optional[Dict[str, Any]] = None
        for point in points:
            perdus = point["granted_pairs_lost"]
            point["efficiency"] = (
                round(1000.0 * point["roles_absorbed"] / perdus, 1) if perdus else None
            )

            if precedent is None:
                point["marginal_efficiency"] = None
            else:
                roles_en_plus = point["roles_absorbed"] - precedent["roles_absorbed"]
                perdus_en_plus = perdus - precedent["granted_pairs_lost"]
                point["marginal_efficiency"] = (
                    round(1000.0 * roles_en_plus / perdus_en_plus, 1)
                    if perdus_en_plus > 0 else None
                )
            precedent = point

    @staticmethod
    def _sous_contrainte(
        points: Sequence[Dict[str, Any]], max_granted_loss_pct: Optional[float]
    ) -> Optional[Dict[str, Any]]:
        """Point le plus simple respectant la perte maximale acceptée.

        Critère : le moins de rôles ; à égalité, le moins de couples perdus ;
        puis le seuil le plus strict. Sans contrainte, rien n'est désigné.
        """
        if max_granted_loss_pct is None:
            return None

        eligibles = [
            point for point in points
            if point["granted_pairs_lost_pct"] <= max_granted_loss_pct
        ]
        if not eligibles:
            return None

        return min(
            eligibles,
            key=lambda point: (point["roles"], point["granted_pairs_lost"], -point["threshold"]),
        )

    def _point(self, seuil: Optional[float], roles: Sequence[Dict[str, Any]],
               absorbes: int, reference: Optional[int]) -> Dict[str, Any]:
        """Mesure un modèle et le compare à la référence sans consolidation."""
        metriques = mesurer(roles, self.total_assignments, self.droits_reels)["metrics"]
        accordes = metriques["granted_pairs"]
        perdus = (reference - accordes) if reference is not None else 0

        return {
            "threshold": seuil,
            "roles": metriques["roles_count"],
            "roles_absorbed": absorbes,
            "granted_pairs": accordes,
            "granted_pairs_lost": perdus,
            "granted_pairs_lost_pct": (
                round(100.0 * perdus / reference, 2) if reference else 0.0
            ),
            "covered_assignments": metriques["covered_assignments"],
            "coverage_pct": metriques["coverage_pct"],
            "over_granted": metriques["over_granted"],
            "compression_ratio": metriques["compression_ratio"],
            "redundancy_pct": metriques["redundancy_pct"],
            "wsc": metriques["wsc"],
        }

    def scan(
        self,
        thresholds: Sequence[float],
        max_granted_loss_pct: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Consolide à chaque seuil et rend la courbe simplification / perte.

        Args:
            thresholds: seuils à évaluer, dans ]0, 1].
            max_granted_loss_pct: part maximale des couples accordés qu'on
                accepte de perdre. Sans elle, aucun point n'est désigné.

        Returns:
            {"baseline": {...}, "points": [...], "selected": {...} | None,
             "constraint": {...}, "elapsed_ms": int}

            ``baseline`` est le modèle **sans** consolidation : c'est la
            référence de toutes les pertes annoncées. Son seuil vaut ``None``.
        """
        seuils = self._normaliser(thresholds)
        if max_granted_loss_pct is not None and max_granted_loss_pct < 0:
            raise ValueError("max_granted_loss_pct doit être positif ou nul")

        debut_total = time.perf_counter()

        reference = self._point(None, self.roles, 0, None)
        accordes_reference = reference["granted_pairs"]

        points: List[Dict[str, Any]] = []
        for seuil in seuils:
            debut = time.perf_counter()
            consolidation = consolider(self.roles, seuil_similarite=seuil)
            point = self._point(
                seuil,
                consolidation["roles"],
                consolidation["stats"]["roles_absorbed"],
                accordes_reference,
            )
            point["elapsed_ms"] = int(round((time.perf_counter() - debut) * 1000))
            points.append(point)

        self._rendements(points)

        logger.info(
            "Exploration de la consolidation : %d points sur %d rôles candidats",
            len(points), len(self.roles),
        )

        return {
            "baseline": reference,
            "points": points,
            "selected": self._sous_contrainte(points, max_granted_loss_pct),
            "constraint": {"max_granted_loss_pct": max_granted_loss_pct},
            "elapsed_ms": int(round((time.perf_counter() - debut_total) * 1000)),
        }
