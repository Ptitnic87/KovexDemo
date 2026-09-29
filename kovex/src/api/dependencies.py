# src/api/dependencies.py
"""
Injection de dépendances pour l'API FastAPI.
Version avec support des Workspaces (Sprint 7).
"""

import json
import logging
from typing import Dict, Optional
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException, status

from src.core.data.loader import DataLoader, DataLoaderConfig
from src.core.knowledge.knowledge_base import KnowledgeBase
from src.core.workspaces.workspace_manager import (
    WorkspaceInfo,
    get_workspace_manager,
)


logger = logging.getLogger(__name__)

# Cache du DataLoader par workspace
_data_loader_cache: dict = {}
_current_workspace_id: Optional[str] = None


def clear_all_caches() -> None:
    """Vide tous les caches (après switch de workspace)."""
    global _data_loader_cache, _current_workspace_id
    _data_loader_cache.clear()
    _current_workspace_id = None
    load_config_file.cache_clear()


@lru_cache(maxsize=5)
def load_config_file(config_path: str) -> dict:
    """Lit un document de configuration JSON.

    Le chemin est exigé. Il était facultatif, et l'absence d'argument
    désignait la configuration de repli du projet : un appel distrait lisait
    la configuration d'un autre workspace que celui qu'on croyait.

    Un document illisible rend `{}` plutôt qu'une exception : l'appelant
    distingue ce cas et décide quoi en faire — `get_data_loader` refuse de
    servir des données sur cette base.
    """
    path = Path(config_path)

    if not path.exists():
        logger.warning("Fichier de configuration non trouvé : %s", path)
        return {}

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as erreur:
        logger.error("Configuration illisible (%s) : %s", path, erreur)
        return {}


def get_active_workspace_config_path() -> Optional[Path]:
    """Chemin du `config.json` du workspace actif, `None` s'il n'y en a pas.

    Un incident — index illisible, droits, disque — rendait `None`, exactement
    comme une installation neuve. L'écran de paramétrage annonçait alors
    « aucun workspace actif » et invitait à en créer un : on créait un second
    workspace par-dessus un index cassé, dont les décisions de gouvernance
    étaient toujours là. Absence et panne sont deux réponses différentes.

    Raises:
        HTTPException: 503 si le workspace actif est indéterminable.
    """
    try:
        manager = get_workspace_manager()
        active = manager.get_active_workspace()
        return manager.get_workspace_config_path(active.id) if active else None
    except Exception as erreur:
        logger.error("Workspace actif indéterminable : %s", erreur)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "data.unavailable"},
        )


def get_kb() -> KnowledgeBase:
    """Knowledge Base du workspace actif.

    Cette fonction retombait sur un `knowledge_base.json` relatif au répertoire
    du processus dès qu'une exception survenait — index des workspaces
    illisible, droits, disque. Le fichier était créé vide : l'interface
    affichait « 0 rôle validé », **indiscernable d'un workspace neuf**, et les
    décisions prises ensuite étaient écrites hors du workspace, où plus personne
    n'irait les chercher. Un incident visible devenait une corruption
    silencieuse.

    Deux situations, deux réponses distinctes :

    - aucun workspace actif — cas légitime d'une installation neuve : 409, et
      l'interface invite à en créer un ;
    - un workspace existe mais sa Knowledge Base est inatteignable — incident :
      503. Refuser de répondre vaut mieux que répondre « aucune décision ».

    Raises:
        HTTPException: 409 si aucun workspace n'est actif, 503 si la base est
            inatteignable.
    """
    try:
        manager = get_workspace_manager()
        active = manager.get_active_workspace()
    except Exception as erreur:
        logger.error("Workspace actif indéterminable : %s", erreur)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "kb.unavailable"},
        )

    if active is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "workspace.none_active"},
        )

    try:
        return KnowledgeBase(str(manager.get_workspace_kb_path(active.id)))
    except Exception as erreur:
        logger.error(
            "Knowledge Base du workspace %s inatteignable : %s", active.id, erreur
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "kb.unavailable"},
        )


def get_data_loader() -> DataLoader:
    """Chargeur de données du workspace actif.

    Cette fonction avalait toute erreur de résolution du workspace et retombait
    sur `config/config.json`, la configuration de repli, **sans périmètre de
    lecture**. Deux conséquences, l'une visible et l'autre non :

    - un index de workspaces illisible affichait les données d'ailleurs sans
      rien signaler, alors que `get_kb` refusait au même instant de rendre les
      décisions de gouvernance : deux écrans du même produit ne parlaient plus
      du même workspace ;
    - le périmètre de lecture — le garde-fou qui empêche un chemin inscrit dans
      la configuration de désigner `.env` ou `config/users.json` — n'était posé
      que sur la branche « workspace actif ». Sur la branche de repli, que
      `POST /settings` alimente quand aucun workspace n'est actif, il valait
      `None` : aucune borne. Le contournement tenait en une écriture de
      configuration suivie d'une consultation de l'explorateur.

    Le repli est donc supprimé. Le produit est organisé par workspace ; hors
    d'un workspace il n'y a pas de données à servir, et c'est déjà ce que
    répond `get_kb`.

    Raises:
        HTTPException: 409 si aucun workspace n'est actif, 503 si le workspace
            est indéterminable ou sa configuration inutilisable.
    """
    global _data_loader_cache, _current_workspace_id

    try:
        manager = get_workspace_manager()
        active = manager.get_active_workspace()
    except Exception as erreur:
        logger.error("Workspace actif indéterminable : %s", erreur)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "data.unavailable"},
        )

    if active is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "workspace.none_active"},
        )

    workspace_id = active.id

    if workspace_id != _current_workspace_id:
        # Changement de workspace : les chargeurs mis en cache portent la
        # configuration et les données d'un autre référentiel.
        _data_loader_cache.clear()
    elif workspace_id in _data_loader_cache:
        return _data_loader_cache[workspace_id]

    try:
        config_path = Path(manager.get_workspace_config_path(workspace_id))
    except Exception as erreur:
        logger.error(
            "Chemin de configuration du workspace %s introuvable : %s",
            workspace_id, erreur,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "data.unavailable"},
        )

    config_dict = load_config_file(str(config_path)) if config_path.exists() else {}

    if not config_dict:
        logger.error(
            "Configuration absente ou vide pour le workspace %s (%s)",
            workspace_id, config_path,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "data.config_missing"},
        )

    try:
        # Périmètre de lecture : le dossier du workspace, et rien d'autre.
        # Les chemins des fichiers sources viennent de `config.json`, que
        # l'API laisse écrire ; sans cette borne, y placer `.env` puis
        # consulter l'explorateur rendait la clé de signature des jetons.
        loader = DataLoader(DataLoaderConfig.from_dict(
            config_dict, base_autorisee=str(config_path.parent)))
    except Exception as erreur:
        # Le détail reste dans le journal du serveur. Renvoyé au client, il
        # décrivait l'arborescence du serveur à qui savait provoquer l'erreur.
        logger.error("Chargeur de données inconstructible : %s", erreur)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "data.unavailable"},
        )

    _data_loader_cache[workspace_id] = loader
    _current_workspace_id = workspace_id

    volumes = {
        "users": len(loader.identities),
        "apps": len(loader.applications),
        "rights": len(loader.rights),
        "habs": len(loader.habilitations),
    }

    try:
        manager.update_data_stats(workspace_id, volumes)
    except Exception as erreur:
        # Les compteurs affichés dans la liste des workspaces sont un confort ;
        # leur mise à jour ne doit pas empêcher de servir les données.
        logger.warning("Statistiques du workspace non mises à jour : %s", erreur)

    _relever_volumetrie(workspace_id, loader, volumes)
    return loader


def _relever_volumetrie(workspace_id: str, loader: DataLoader,
                        volumes: Dict[str, int]) -> None:
    """Consigne la taille du référentiel au moment où il vient d'être chargé.

    C'est le seul instant où la question se pose : le chargement est ce qui
    fait changer les données. Le relevé n'est ajouté que si l'empreinte diffère
    du précédent — rouvrir l'application n'est pas un événement.

    L'échec n'interrompt rien. Une mesure d'évolution est un confort ; servir
    le référentiel ne l'est pas.
    """
    try:
        kb = KnowledgeBase(str(get_workspace_manager()
                               .get_workspace_kb_path(workspace_id)))
        kb.relever_volumetrie(volumes, loader.empreinte_donnees())
    except Exception as erreur:
        logger.warning("Volumétrie non relevée : %s", erreur)


def reload_data_loader() -> DataLoader:
    """
    Force le rechargement du DataLoader.
    À appeler après un switch de workspace ou un import de données.
    
    Returns:
        Nouveau DataLoader rechargé
    """
    global _data_loader_cache, _current_workspace_id
    
    # Vider le cache
    _data_loader_cache.clear()
    _current_workspace_id = None
    load_config_file.cache_clear()
    
    # Recharger
    return get_data_loader()

def get_current_workspace() -> Optional[WorkspaceInfo]:
    """Workspace actif, `None` s'il n'y en a pas.

    Raises:
        HTTPException: 503 si le workspace actif est indéterminable. Comme
            ailleurs dans ce module, une panne ne se déguise pas en absence.
    """
    try:
        return get_workspace_manager().get_active_workspace()
    except Exception as erreur:
        logger.error("Workspace actif indéterminable : %s", erreur)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "data.unavailable"},
        )

# === HELPER POUR TESTS ===

def reset_dependencies() -> None:
    """Réinitialise toutes les dépendances (pour les tests)."""
    clear_all_caches()
