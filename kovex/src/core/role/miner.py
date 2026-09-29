# src/core/role/miner.py
"""
Mining exact de rôles applicatifs.

Regroupe les utilisateurs ayant strictement la même signature de droits.
C'est le critère le plus conservateur qui soit : un rôle produit ici décrit
un ensemble d'utilisateurs réellement identiques, et n'octroie aucun droit
que ses membres ne détiennent déjà.

C'est aussi sa limite : sur un référentiel réel, la majorité des utilisateurs
ont une signature unique et ne sont donc jamais regroupés. Le mining approché
(src/core/mining/approximate_miner.py) relâche cette contrainte au moyen d'un
seuil de similarité choisi par l'utilisateur.
"""

import logging
from collections import defaultdict
from typing import Any, Dict, List

import numpy as np

from src.core.role.identite import identifiant_applicatif

logger = logging.getLogger(__name__)


class RoleMinerEngine:
    """Moteur de mining exact, basé sur la signature de droits des utilisateurs."""

    def __init__(self, loader):
        self.loader = loader
        matrix = loader.matrix

        if matrix is not None:
            self.matrix = matrix
            self.user_decoder = {v: k for k, v in loader.user_encoder.items()}
            self.right_decoder = {v: k for k, v in loader.right_encoder.items()}
        else:
            self.matrix = None
            self.user_decoder = {}
            self.right_decoder = {}

        self.min_rights = loader.config.get('mining_min_rights', 2)
        self.min_users = loader.config.get('mining_min_users', 5)

    @staticmethod
    def _metrics(users: List[str], rights: List[str]) -> Dict[str, Any]:
        """Métriques d'un rôle exact.

        `fit_pct` vaut 100 par construction : tous les membres détiennent tous
        les droits du rôle. Le champ est présent pour que l'IHM puisse traiter
        de la même façon les rôles exacts et les rôles approchés.
        """
        return {
            "user_count": len(users),
            "right_count": len(rights),
            "score": len(users) * len(rights),
            "fit_pct": 100.0,
            "over_granted": 0,
            "over_granted_pct": 0.0,
        }

    def mine_roles_exact(self, excluded_rights: List[str]) -> List[Dict[str, Any]]:
        """Retourne les rôles formés d'utilisateurs à signature de droits identique.

        Les droits exclus sont **retirés des signatures**, pas leurs porteurs
        du périmètre. C'est tout l'intérêt d'exclure un droit : deux identités
        qui ne différaient que par lui deviennent comparables, et se
        regroupent. La version précédente écartait l'identité entière dès
        qu'elle détenait un droit exclu — un droit socle étant détenu par la
        quasi-totalité de la population, activer la détection vidait le mining
        de ses identités au lieu de les rapprocher. Le mining approché, lui,
        masquait déjà correctement les droits : les deux moteurs
        interprétaient le même paramètre en sens inverse.

        Une identité dont il ne reste rien après exclusion sort du calcul :
        elle n'a plus de signature à comparer.

        L'implémentation lit directement la structure CSR de la matrice
        (`indptr` / `indices`), qui donne les droits d'un utilisateur en temps
        constant. La version précédente rebalayait la matrice entière pour
        chaque utilisateur, soit un coût quadratique.
        """
        if self.matrix is None or self.matrix.shape[0] == 0:
            return []

        excluded_indices = {
            self.loader.right_encoder[right]
            for right in excluded_rights
            if right in self.loader.right_encoder
        }

        csr = self.matrix.tocsr() if hasattr(self.matrix, "tocsr") else self.matrix
        indptr = np.asarray(csr.indptr, dtype=np.int64)
        indices = np.asarray(csr.indices, dtype=np.int64)

        signatures: Dict[tuple, List[int]] = defaultdict(list)
        for user_index in range(csr.shape[0]):
            user_rights = indices[indptr[user_index]:indptr[user_index + 1]]
            if user_rights.size == 0:
                continue
            signature = tuple(sorted(
                int(r) for r in user_rights if int(r) not in excluded_indices))
            if not signature:
                continue
            signatures[signature].append(user_index)

        roles: List[Dict[str, Any]] = []
        for signature, user_indices in signatures.items():
            if len(user_indices) < self.min_users or len(signature) < self.min_rights:
                continue

            users = [self.user_decoder[u] for u in user_indices]
            rights = sorted(self.right_decoder[r] for r in signature)

            roles.append({
                # L'identité d'un rôle applicatif est son ensemble de droits,
                # non un tirage. Un identifiant aléatoire rendait impossible de
                # rattacher une décision au candidat sur lequel elle a été
                # prise : un rôle refusé revenait proposé au calcul suivant. Le
                # mining métier avait été corrigé, celui-ci ne l'avait pas été.
                "id": identifiant_applicatif(rights),
                # Nom technique. Le libellé lisible est construit par le client
                # à partir de la clé i18n ci-dessous.
                "name": f"APP_ROLE_{len(roles) + 1}_{len(rights)}R",
                "description_key": "mining.role.exact_description",
                "description_params": {"rights": len(rights), "users": len(users)},
                "role_type": "APPLICATIF",
                "mining_mode": "EXACT",
                "rights": rights,
                "users": users,
                **self._metrics(users, rights),
            })

        roles.sort(key=lambda role: (-role["score"], role["name"]))
        logger.info("Mining exact : %d rôles retenus sur %d signatures distinctes",
                    len(roles), len(signatures))
        return roles
