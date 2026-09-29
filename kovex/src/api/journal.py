"""Consignation d'une action dans la piste d'audit, depuis une route.

Une route ne doit pas avoir à savoir où vit la piste, ni comment retrouver le
compte appelant, ni quel workspace était actif. Elle déclare `journal: Journal`
et écrit une ligne. C'est ce qui rend la consignation systématique plutôt
qu'optionnelle : oublier de journaliser doit demander un effort, pas être le
comportement par défaut.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials

from src.core.audit import PisteAudit, get_piste_audit
from src.core.security.auth import decode_access_token, security

logger = logging.getLogger(__name__)

#: Acteur retenu quand l'authentification est désactivée (développement).
#: Un nom explicite, jamais un compte réel : une entrée d'audit produite sans
#: authentification ne doit pas être imputable à quelqu'un.
ACTEUR_SANS_AUTHENTIFICATION = "authentification-desactivee"


class Journal:
    """Point d'écriture de la piste, lié à un appelant et à un workspace."""

    def __init__(self, piste: PisteAudit, acteur: str, workspace: str):
        self.piste = piste
        self.acteur = acteur
        self.workspace = workspace

    def consigner(
        self,
        action: str,
        objet_type: str = "",
        objet_id: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Écrit une décision dans la piste.

        Une écriture qui échoue est signalée en erreur mais n'annule pas
        l'action métier déjà réalisée : refuser après coup une validation de
        rôle déjà enregistrée dans la base de connaissances laisserait les deux
        états incohérents. Le trou est donc tracé côté serveur, et la
        vérification d'intégrité reste le garde-fou.
        """
        try:
            self.piste.consigner(
                acteur=self.acteur,
                action=action,
                objet_type=objet_type,
                objet_id=objet_id,
                workspace=self.workspace,
                details=details or {},
            )
        except Exception as erreur:  # pragma: no cover - défaillance disque
            logger.error(
                "Piste d'audit : impossible de consigner %s par %s (%s)",
                action, self.acteur, erreur,
            )


def _acteur(credentials: Optional[HTTPAuthorizationCredentials]) -> str:
    if credentials is None:
        return ACTEUR_SANS_AUTHENTIFICATION
    donnees = decode_access_token(credentials.credentials)
    if donnees is None or not getattr(donnees, "username", ""):
        return ACTEUR_SANS_AUTHENTIFICATION
    return donnees.username


def _workspace_actif() -> str:
    """Workspace actif, ou chaîne vide si la notion ne s'applique pas.

    Import local : `dependencies` importe déjà beaucoup, et une importation
    circulaire au chargement du module casserait le démarrage de l'API.
    """
    try:
        from src.core.workspaces.workspace_manager import get_workspace_manager

        actif = get_workspace_manager().get_active_workspace()
        return getattr(actif, "id", "") or ""
    except Exception:
        return ""


async def get_journal(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Journal:
    """Dépendance FastAPI : le journal du compte appelant."""
    return Journal(get_piste_audit(), _acteur(credentials), _workspace_actif())
