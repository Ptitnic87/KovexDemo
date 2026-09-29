# src/core/workspaces/workspace_manager.py
"""
Gestionnaire de Workspaces pour PyGIA.
Permet de gérer plusieurs clients/environnements avec isolation complète.
"""

import json
import os
import shutil
import logging
import zipfile
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass, asdict

from src.core.annotation.assistance import Assistance
from src.core.knowledge.derogations import DUREE_MAX_JOURS, PREAVIS_JOURS
from src.core.mining.mouvement import (CONSTATS_MAX, DROITS_MIN, GROUPE_MIN,
                                       RARETE_MAX_PCT, TYPIQUE_MIN_PCT)
from src.core.mining.approximate_miner import PROFILS_CROISES_MAX, TREILLIS_MAX
from src.core.knowledge.privileges import PLACE_JETON
from src.core.security.path_validator import PathValidationError, SecurePathValidator
from src.core.workspaces.theme_visuel import (
    IDENTIFIANT_PAR_DEFAUT,
    ThemeInvalide,
    ThemeVisuel,
    chemin_du_logo,
    dossier_des_themes,
    lister,
    theme_utilisable,
)

#: Dossier des artefacts régénérables d'un workspace. Exclu des exports.
DOSSIER_SORTIES = "output"

logger = logging.getLogger(__name__)


class IndexWorkspacesIllisible(RuntimeError):
    """L'index des workspaces est inexploitable et des données existent.

    Repartir d'un index vide ferait disparaître des workspaces clients de
    l'application alors que leurs fichiers sont toujours là : mieux vaut
    refuser de démarrer et le dire.
    """


@dataclass
class WorkspaceInfo:
    """Informations d'un workspace."""
    id: str
    name: str
    client: str
    environment: str
    created_at: str
    last_accessed: str
    theme: str = "default"
    data_stats: Dict[str, int] = None
    
    def __post_init__(self):
        if self.data_stats is None:
            self.data_stats = {"users": 0, "apps": 0, "rights": 0, "habs": 0}
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'WorkspaceInfo':
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            client=data.get("client", ""),
            environment=data.get("environment", ""),
            created_at=data.get("created_at", ""),
            last_accessed=data.get("last_accessed", ""),
            theme=data.get("theme", "default"),
            data_stats=data.get("data_stats", {"users": 0, "apps": 0, "rights": 0, "habs": 0})
        )


class WorkspaceManager:
    """
    Gestionnaire central des workspaces.
    
    Structure des fichiers:
    workspaces/
    ├─ workspaces.json          # Index des workspaces + workspace actif
    ├─ {client}_{env}/
    │  ├─ data/                 # Fichiers CSV copiés
    │  │  ├─ identities.csv
    │  │  ├─ applications.csv
    │  │  ├─ droits.csv
    │  │  └─ habilitations.csv
    │  ├─ knowledge_base.json   # KB isolée
    │  ├─ config.json           # Config spécifique
    │  └─ output/               # Exports
    """
    
    WORKSPACES_DIR = Path("workspaces")
    INDEX_FILE = "workspaces.json"
    
    def __init__(self, base_path: Optional[Path] = None):
        """
        Initialise le gestionnaire de workspaces.
        
        Args:
            base_path: Chemin de base (par défaut: dossier courant)
        """
        self.base_path = base_path or Path(".")
        self.workspaces_dir = self.base_path / self.WORKSPACES_DIR
        self.index_path = self.workspaces_dir / self.INDEX_FILE
        
        # Créer le dossier workspaces si nécessaire
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)

        # Tout chemin de workspace passe par ce validateur : il garantit que
        # l'identifiant, quelle qu'en soit l'origine, ne fait pas sortir de
        # `workspaces/`.
        self._validateur = SecurePathValidator(str(self.workspaces_dir))

        # Charger ou créer l'index
        self._index = self._load_index()
    
    def _load_index(self) -> Dict[str, Any]:
        """Charge l'index des workspaces.

        Un index illisible était remplacé en silence par un index vide :
        `GET /workspaces/` répondait 200 avec une liste vide, les données des
        clients restaient sur le disque, invisibles, et **la première écriture
        rendait la perte définitive**.

        L'index est désormais mis de côté avant toute réinitialisation, comme
        l'est déjà une Knowledge Base corrompue, et le contenu du répertoire est
        inspecté : si des workspaces existent sur le disque, on refuse de
        démarrer sur un index vide plutôt que de faire croire qu'il n'y a rien.

        Raises:
            IndexWorkspacesIllisible: si l'index est illisible alors que des
                workspaces existent sur le disque.
        """
        if not self.index_path.exists():
            return self._create_empty_index()

        try:
            with open(self.index_path, 'r', encoding='utf-8') as flux:
                index = json.load(flux)
        except (json.JSONDecodeError, OSError) as erreur:
            copie = self.index_path.with_name(
                f"workspaces.corrupted-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
            )
            try:
                shutil.copy2(self.index_path, copie)
                logger.error("Index des workspaces illisible (%s). Copie conservée dans %s.",
                             erreur, copie)
            except OSError as echec:
                logger.error("Index des workspaces illisible (%s), copie impossible (%s).",
                             erreur, echec)

            orphelins = self._workspaces_sur_disque()
            if orphelins:
                raise IndexWorkspacesIllisible(
                    f"L'index des workspaces est illisible alors que {len(orphelins)} "
                    f"workspace(s) existent sur le disque : {', '.join(orphelins)}. "
                    f"Une copie de l'index a été conservée. Réparez-le ou reconstruisez-le "
                    f"avant de continuer : repartir d'un index vide effacerait ces "
                    f"workspaces de l'application."
                )

            logger.warning("Index illisible et aucun workspace sur le disque : index vide.")
            return self._create_empty_index()

        if not isinstance(index, dict) or "workspaces" not in index:
            raise IndexWorkspacesIllisible(
                "L'index des workspaces n'a pas la structure attendue."
            )
        return index

    def _workspaces_sur_disque(self) -> List[str]:
        """Répertoires qui ressemblent à un workspace, index mis à part."""
        if not self.workspaces_dir.is_dir():
            return []
        return sorted(
            chemin.name for chemin in self.workspaces_dir.iterdir()
            if chemin.is_dir() and (chemin / "config.json").exists()
        )
    
    def _create_empty_index(self) -> Dict[str, Any]:
        """Crée un index vide."""
        return {
            "version": "1.0",
            "active_workspace": None,
            "workspaces": []
        }
    
    def _save_index(self) -> None:
        """Sauvegarde l'index sur disque."""
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)
        
        # Sauvegarde atomique
        temp_path = self.index_path.with_suffix('.tmp')
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(self._index, f, indent=4, ensure_ascii=False)
        temp_path.replace(self.index_path)
    
    def _generate_workspace_id(self, client: str, environment: str) -> str:
        """Génère un ID de workspace à partir du client et de l'environnement."""
        # Nettoyer les caractères spéciaux
        clean_client = "".join(c if c.isalnum() else "_" for c in client)
        clean_env = "".join(c if c.isalnum() else "_" for c in environment)
        return f"{clean_client}_{clean_env}"
    
    def _get_workspace_path(self, workspace_id: str) -> Path:
        """Retourne le dossier d'un workspace, en le confinant sous `workspaces/`.

        Tous les chemins manipulés par ce gestionnaire — données, configuration,
        Knowledge Base, exports — dérivent de cette méthode. La validation est
        donc posée ici plutôt que dans chaque appelant : un identifiant
        remontant l'arborescence (`../../etc`) est refusé quel que soit
        l'endroit qui l'a laissé passer.

        Aujourd'hui, chaque endpoint vérifie d'abord l'existence du workspace
        dans l'index, ce qui ferme déjà la porte. Cette validation est la
        seconde serrure : elle survit à l'ajout d'un endpoint qui oublierait
        la première.

        Raises:
            PathValidationError: si le chemin sort du répertoire des workspaces.
        """
        return self._validateur.validate(workspace_id)
    
    # === CRUD Operations ===
    
    def list_workspaces(self) -> List[WorkspaceInfo]:
        """Liste tous les workspaces."""
        return [WorkspaceInfo.from_dict(ws) for ws in self._index.get("workspaces", [])]
    
    def get_workspace(self, workspace_id: str) -> Optional[WorkspaceInfo]:
        """Récupère un workspace par son ID."""
        for ws in self._index.get("workspaces", []):
            if ws.get("id") == workspace_id:
                return WorkspaceInfo.from_dict(ws)
        return None
    
    def get_active_workspace(self) -> Optional[WorkspaceInfo]:
        """Retourne le workspace actuellement actif."""
        active_id = self._index.get("active_workspace")
        if active_id:
            return self.get_workspace(active_id)
        return None
    
    def create_workspace(
        self,
        name: str,
        client: str,
        environment: str,
        theme: str = "default",
        source_data_paths: Optional[Dict[str, str]] = None
    ) -> WorkspaceInfo:
        """
        Crée un nouveau workspace.
        
        Args:
            name: Nom affiché du workspace
            client: Nom du client
            environment: Environnement (DEV, PROD, TEST, UAT)
            theme: Thème visuel à utiliser
            source_data_paths: Chemins des fichiers data source à copier
                              {"identities": "/path/to/file.csv", ...}
        
        Returns:
            WorkspaceInfo du workspace créé
        
        Raises:
            ValueError: Si un workspace avec cet ID existe déjà
        """
        workspace_id = self._generate_workspace_id(client, environment)

        if self.get_workspace(workspace_id):
            raise ValueError(f"Un workspace '{workspace_id}' existe déjà")

        # L'unicité n'était vérifiée que dans l'index. Un dossier resté sur le
        # disque — index perdu, suppression interrompue — était repris tel quel,
        # et la Knowledge Base y était recréée **vide** : les décisions de
        # gouvernance du workspace précédent disparaissaient.
        ws_path = self._get_workspace_path(workspace_id)
        if ws_path.exists() and any(ws_path.iterdir()):
            raise ValueError(
                f"Le dossier du workspace '{workspace_id}' existe déjà sur le disque "
                f"({ws_path}) mais ne figure pas dans l'index. Il peut contenir des "
                f"décisions de gouvernance : archivez-le ou renommez-le avant de "
                f"recréer un workspace portant ce nom."
            )

        ws_path.mkdir(parents=True, exist_ok=True)
        (ws_path / "data").mkdir(exist_ok=True)
        (ws_path / DOSSIER_SORTIES).mkdir(exist_ok=True)
        # Le dossier est créé vide et à la création : c'est là que les thèmes
        # du client se déposent, et un dossier absent n'indique aucun endroit.
        dossier_des_themes(ws_path).mkdir(exist_ok=True)

        # Un workspace neuf n'a pas encore de thème déposé — son dossier vient
        # d'être créé. Demander autre chose que le thème d'origine à cet
        # instant ne peut désigner qu'un thème absent, et un identifiant
        # silencieusement conservé serait un habillage qui ne s'applique
        # jamais.
        if theme != IDENTIFIANT_PAR_DEFAUT:
            raise ThemeInvalide("theme.unavailable_at_creation", theme=theme)
        
        # Copier les fichiers data si fournis
        data_stats = {"users": 0, "apps": 0, "rights": 0, "habs": 0}
        if source_data_paths:
            data_stats = self._copy_data_files(workspace_id, source_data_paths)
        
        # Créer la KB vide
        self._create_empty_kb(workspace_id)
        
        # Créer le config.json
        self._create_workspace_config(workspace_id)
        
        # Créer l'objet workspace
        now = datetime.now().isoformat()
        workspace_info = WorkspaceInfo(
            id=workspace_id,
            name=name,
            client=client,
            environment=environment,
            created_at=now,
            last_accessed=now,
            theme=theme,
            data_stats=data_stats
        )
        
        # Ajouter à l'index
        self._index["workspaces"].append(workspace_info.to_dict())
        
        # Si c'est le premier workspace, l'activer automatiquement
        if len(self._index["workspaces"]) == 1:
            self._index["active_workspace"] = workspace_id
        
        self._save_index()
        
        logger.info(f"Workspace créé: {workspace_id}")
        return workspace_info
    
    def _copy_data_files(
        self,
        workspace_id: str,
        source_paths: Dict[str, str]
    ) -> Dict[str, int]:
        """
        Copie les fichiers data dans le workspace.
        
        Args:
            workspace_id: ID du workspace
            source_paths: Dict {type: chemin_source}
        
        Returns:
            Statistiques des fichiers copiés
        """
        ws_data_path = self._get_workspace_path(workspace_id) / "data"
        stats = {"users": 0, "apps": 0, "rights": 0, "habs": 0}
        
        file_mapping = {
            "identities": ("identities.csv", "users"),
            "applications": ("applications.csv", "apps"),
            "rights": ("droits.csv", "rights"),
            "habs": ("habilitations.csv", "habs")
        }
        
        for file_type, (target_name, stat_key) in file_mapping.items():
            source = source_paths.get(file_type)
            if source and Path(source).exists():
                target = ws_data_path / target_name
                shutil.copy2(source, target)
                
                # Compter les lignes
                try:
                    with open(target, 'r', encoding='utf-8') as f:
                        stats[stat_key] = sum(1 for _ in f) - 1  # -1 pour le header
                except Exception as e:
                    logger.warning(f"Erreur comptage lignes {target}: {e}")
                
                logger.info(f"Copié {source} → {target}")
        
        return stats
    
    def _create_empty_kb(self, workspace_id: str) -> None:
        """Crée une KB vide pour le workspace."""
        kb_path = self._get_workspace_path(workspace_id) / "knowledge_base.json"
        
        kb_data = {
            "version": "1.0",
            "workspace_id": workspace_id,
            "created_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "birth_rights": {
                "threshold": 90.0,
                "detected_at": None,
                "rights": []
            },
            "validated_roles": [],
            "rejected_roles": [],
            "excluded_users": [],
            "mining_runs": []
        }
        
        with open(kb_path, 'w', encoding='utf-8') as f:
            json.dump(kb_data, f, indent=4, ensure_ascii=False)
    
    def _create_workspace_config(self, workspace_id: str) -> None:
        """Crée le fichier config.json pour le workspace."""
        config_path = self._get_workspace_path(workspace_id) / "config.json"
        ws_data_path = f"workspaces/{workspace_id}/data"
        
        config = {
            "files": {
                "identities": {
                    "path": f"{ws_data_path}/identities.csv",
                    "delimiter": ";",
                    "encoding": "utf-8",
                    "id_column": "ID_utilisateur",
                    "user_id_column": "",
                    "right_id_column": ""
                },
                "applications": {
                    "path": f"{ws_data_path}/applications.csv",
                    "delimiter": ";",
                    "encoding": "utf-8",
                    "id_column": "ID_application",
                    "user_id_column": "",
                    "right_id_column": ""
                },
                "rights": {
                    "path": f"{ws_data_path}/droits.csv",
                    "delimiter": ";",
                    "encoding": "utf-8",
                    "id_column": "ID_droit",
                    # Le rattachement d'un droit à son application. La clé
                    # manquait ici alors que le chargeur la lit : l'écran des
                    # paramètres n'avait rien à afficher, et la jointure était
                    # impossible dès que les deux fichiers ne nommaient pas
                    # l'application de la même façon.
                    "app_id_column": "",
                    "user_id_column": "",
                    "right_id_column": ""
                },
                "habs": {
                    "path": f"{ws_data_path}/habilitations.csv",
                    "delimiter": ";",
                    "encoding": "utf-8",
                    "id_column": "",
                    "user_id_column": "ID_utilisateur",
                    "right_id_column": "ID_droit"
                }
            },
            "mining_min_users": 3,
            "mining_min_rights": 2,
            "mining_attribute_max_cardinality_ratio": 0.5,
            "health_threshold_alert": 10.0,
            "health_threshold_critical": 50.0,
            # Ce qui signale un compte à privilèges dans ce référentiel-ci.
            # La liste part vide et le produit ne marque alors rien : `ADM`
            # est un compte d'administration chez un client et l'abréviation
            # d'« administratif » chez un autre, et un marquage livré d'usine
            # se tromperait silencieusement — un compte à privilèges non
            # signalé passe la revue.
            "privileged_account_keywords": [],
            "privileged_account_column": "",
            "privileged_account_place": PLACE_JETON,
            # Les bornes de l'exception assumée. Une dérogation perpétuelle
            # n'est pas une exception : c'est une suppression silencieuse de la
            # règle, avec le désavantage que la règle reste affichée et qu'on
            # la croit appliquée. La durée maximale est donc réglable, mais
            # elle existe toujours.
            "derogation_duree_max_jours": DUREE_MAX_JOURS,
            # À partir de quand une échéance qui approche est annoncée. C'est
            # du travail qui arrive, et le dire tard revient à ne pas le dire.
            "derogation_preavis_jours": PREAVIS_JOURS,
            # Une dérogation doit-elle citer un contrôle compensatoire qui
            # tourne pour couvrir son constat ? Non à la création : le client
            # décrit d'abord ses contrôles, puis décide de les exiger.
            "derogation_controle_exige": False,
            # Une dérogation doit-elle être approuvée par une autre personne
            # que celle qui la demande ? Non à la création, pour la même raison.
            "derogation_approbation_exigee": False,
            # Les bornes du repérage des droits conservés d'un poste
            # précédent. Ce sont des seuils de bruit et non des valeurs
            # métier : une organisation de trois cents personnes réparties en
            # six services ne se comporte pas comme une de trente mille en
            # huit cents.
            "mouvement_groupe_min": GROUPE_MIN,
            "mouvement_rarete_max_pct": RARETE_MAX_PCT,
            "mouvement_typique_min_pct": TYPIQUE_MIN_PCT,
            "mouvement_droits_min": DROITS_MIN,
            "mouvement_constats_max": CONSTATS_MAX,
            # La convention de nommage des droits. Vide par défaut, et le
            # produit ne dérive alors rien : le séparateur est un souligné chez
            # l'un, un point chez l'autre, et beaucoup de référentiels n'ont
            # aucune convention du tout. Une convention livrée d'usine
            # déduirait une application de travers, ce qui vaut moins que pas
            # d'application.
            "right_naming_column": "",
            "right_naming_separator": "",
            "right_naming_positions": [],
            # Combien de profils distincts le croisement confronte, dans le
            # mining approché. Le croisement est quadratique : vingt mille
            # profils font deux cents millions de paires, soit une dizaine de
            # minutes — et quarante mille en feraient quatre fois plus.
            #
            # La valeur livrée était de deux mille, et c'était trop bas d'un
            # ordre de grandeur : un référentiel de vingt et un mille identités
            # porte onze mille cinq cents profils distincts, et le croisement
            # n'était donc jamais tenté. La fonctionnalité était juste et hors
            # d'atteinte.
            #
            # Ce n'est pas un choix métier : c'est le temps qu'on accepte de
            # payer. Au-delà, le produit croise un échantillon et le dit.
            "mining_profils_croises_max": PROFILS_CROISES_MAX,
            # Le treillis ne tourne que si l'utilisateur coche sa case ; sa
            # borne protège le serveur quand il tourne. Voir
            # `approximate_miner.TREILLIS_MAX`.
            "mining_treillis_max": TREILLIS_MAX,
            # Ce qui, dans la revue du modèle, mérite d'être signalé. Un
            # référentiel bouge tout le temps : signaler chaque frémissement
            # rend la revue illisible et on cesse de la lire. Ces deux seuils
            # ne sont pas des valeurs métier, ce sont des seuils de bruit — et
            # un référentiel de trois cents identités ne bouge pas à la même
            # échelle qu'un de trois cent mille.
            "revue_ecart_significatif_pct": 20.0,
            "revue_recouvrement_pct": 80.0,
            # Adhérence en dessous de laquelle un droit du rôle est proposé au
            # retrait. Ce n'est pas une règle : un rôle peut légitimement
            # accorder ce que ses membres n'ont pas encore — c'est même le
            # propre d'un modèle qui harmonise. Le réglage dit où, chez ce
            # client, on cesse de lire un écart comme une harmonisation.
            "revue_adherence_minimale_pct": 80.0,
            # Ce que le produit a le droit de demander à un modèle, usage par
            # usage, pour CE workspace. Tout fermé : un oubli de configuration
            # ne divulgue rien. Ce sont des politiques, pas des secrets — elles
            # s'exportent avec le workspace, et c'est voulu : la règle voyage
            # avec les données qu'elle protège. Le document est écrit complet,
            # usages fermés compris, pour qu'il se relise sans dépendre du code
            # qui l'a produit.
            # Seuils du repérage de cohérence des valeurs. Ce sont des seuils
            # de bruit, pas des choix métier : un référentiel de trois cents
            # identités ne se disperse pas comme un de trois cent mille. Aucun
            # de ces nombres n'apparaît ailleurs que ci-dessous.
            "coherence_distance_edition_max": 2,
            "coherence_longueur_racine_min": 4,
            "coherence_ecart_effectif_significatif": 20.0,
            "coherence_valeurs_analysees_max": 2000,
            "coherence_part_typee_max": 0.5,
            # Combien de valeurs quittent le système d'information à chaque
            # demande faite à un modèle. Ce n'est pas un seuil de bruit : c'est
            # une décision, et elle se règle plus bas que le plafond d'analyse.
            "coherence_valeurs_soumises_max": 300,
            "assistance": Assistance().en_document(),
        }
        
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
    
    def switch_workspace(self, workspace_id: str) -> WorkspaceInfo:
        """
        Bascule vers un autre workspace.
        
        Args:
            workspace_id: ID du workspace cible
        
        Returns:
            WorkspaceInfo du nouveau workspace actif
        
        Raises:
            ValueError: Si le workspace n'existe pas
        """
        workspace = self.get_workspace(workspace_id)
        if not workspace:
            raise ValueError(f"Workspace '{workspace_id}' introuvable")
        
        # Mettre à jour l'index
        self._index["active_workspace"] = workspace_id
        
        # Mettre à jour last_accessed
        for ws in self._index["workspaces"]:
            if ws["id"] == workspace_id:
                ws["last_accessed"] = datetime.now().isoformat()
                break
        
        self._save_index()
        
        logger.info(f"Workspace actif: {workspace_id}")
        return self.get_workspace(workspace_id)
    
    def update_workspace(
        self,
        workspace_id: str,
        updates: Dict[str, Any]
    ) -> WorkspaceInfo:
        """
        Met à jour les informations d'un workspace.
        
        Args:
            workspace_id: ID du workspace
            updates: Champs à mettre à jour (name, theme, etc.)
        
        Returns:
            WorkspaceInfo mis à jour
        """
        # Le thème est vérifié **avant** d'être écrit dans l'index : un
        # identifiant enregistré sans que le thème existe donne un workspace
        # qui s'ouvre sur la palette d'origine en affichant le nom d'un autre
        # habillage, et le défaut ne se voit pas — les deux se ressemblent.
        if "theme" in updates:
            self.theme_du_workspace(workspace_id, updates["theme"])

        for ws in self._index["workspaces"]:
            if ws["id"] == workspace_id:
                # Ne pas permettre de modifier l'ID
                updates.pop("id", None)
                ws.update(updates)
                self._save_index()
                return WorkspaceInfo.from_dict(ws)
        
        raise ValueError(f"Workspace '{workspace_id}' introuvable")
    
    def delete_workspace(self, workspace_id: str) -> bool:
        """
        Supprime un workspace.
        
        Args:
            workspace_id: ID du workspace à supprimer
        
        Returns:
            True si supprimé avec succès
        """
        if not self.get_workspace(workspace_id):
            raise ValueError(f"Workspace '{workspace_id}' introuvable")

        ws_path = self._get_workspace_path(workspace_id)

        # La Knowledge Base est la seule donnée que personne ne peut recalculer :
        # elle est mise à l'abri avant toute destruction. Les référentiels, eux,
        # viennent des fichiers du client.
        kb_path = ws_path / "knowledge_base.json"
        if kb_path.exists():
            archives = self.base_path / self.WORKSPACES_DIR / "_archives"
            archives.mkdir(parents=True, exist_ok=True)
            archive = archives / (
                f"{workspace_id}-knowledge_base-"
                f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
            )
            shutil.copy2(kb_path, archive)
            logger.info("Décisions de gouvernance de %s archivées dans %s",
                        workspace_id, archive)

        # L'index est mis à jour **avant** la destruction. Dans l'ordre inverse,
        # un rmtree interrompu — fichier verrouillé, antivirus — laissait un
        # workspace à moitié effacé toujours référencé et toujours servi.
        self._index["workspaces"] = [
            ws for ws in self._index["workspaces"]
            if ws["id"] != workspace_id
        ]
        
        # Si c'était le workspace actif, basculer vers un autre
        if self._index["active_workspace"] == workspace_id:
            if self._index["workspaces"]:
                self._index["active_workspace"] = self._index["workspaces"][0]["id"]
            else:
                self._index["active_workspace"] = None
        
        self._save_index()

        if ws_path.exists():
            try:
                shutil.rmtree(ws_path)
            except OSError as erreur:
                # L'index est déjà propre : le workspace n'est plus servi. Il
                # reste des fichiers à retirer à la main, et on le dit.
                logger.error(
                    "Workspace %s retiré de l'index, mais son dossier n'a pas pu être "
                    "entièrement supprimé (%s) : %s reste à nettoyer.",
                    workspace_id, erreur, ws_path,
                )

        logger.info("Workspace %s supprimé", workspace_id)
        return True
    
    def update_data_stats(self, workspace_id: str, stats: Dict[str, int]) -> None:
        """Met à jour les statistiques de données d'un workspace."""
        for ws in self._index["workspaces"]:
            if ws["id"] == workspace_id:
                ws["data_stats"] = stats
                self._save_index()
                return
    
    def get_workspace_config_path(self, workspace_id: str) -> Path:
        """Retourne le chemin du config.json d'un workspace."""
        return self._get_workspace_path(workspace_id) / "config.json"
    
    def get_workspace_kb_path(self, workspace_id: str) -> Path:
        """Retourne le chemin de la KB d'un workspace."""
        return self._get_workspace_path(workspace_id) / "knowledge_base.json"
    
    def get_workspace_data_path(self, workspace_id: str) -> Path:
        """Retourne le chemin du dossier data d'un workspace."""
        return self._get_workspace_path(workspace_id) / "data"
    
    def get_workspace_output_path(self, workspace_id: str) -> Path:
        """Retourne le chemin du dossier output d'un workspace."""
        return self._get_workspace_path(workspace_id) / DOSSIER_SORTIES

    def get_workspace_themes_path(self, workspace_id: str) -> Path:
        """Retourne le chemin du dossier des thèmes d'un workspace."""
        return dossier_des_themes(self._get_workspace_path(workspace_id))

    def themes_du_workspace(self, workspace_id: str):
        """Les thèmes utilisables d'un workspace, et les dépôts refusés.

        Deux dépôts sont lus : celui de l'instance — un cabinet dépose sa
        marque une fois pour tous ses dossiers — et celui de l'espace, qui
        prime à identifiant égal.
        """
        if not self.get_workspace(workspace_id):
            raise ValueError(f"Workspace '{workspace_id}' introuvable")
        return lister(self._get_workspace_path(workspace_id), self.base_path)

    def theme_du_workspace(self, workspace_id: str, identifiant: str) -> ThemeVisuel:
        """Le thème demandé, ou le refus motivé s'il n'est pas utilisable."""
        if not self.get_workspace(workspace_id):
            raise ValueError(f"Workspace '{workspace_id}' introuvable")
        theme = theme_utilisable(self._get_workspace_path(workspace_id), identifiant,
                                 self.base_path)
        if theme is None:
            raise ThemeInvalide("theme.unknown", theme=identifiant)
        return theme

    def chemin_du_logo_du_theme(self, workspace_id: str, identifiant: str):
        """Le fichier du logo, cherché là où le thème retenu se trouve.

        Présumer le dossier de l'espace de travail servait un logo absent pour
        un thème livré avec l'instance.
        """
        if not self.get_workspace(workspace_id):
            raise ValueError(f"Workspace '{workspace_id}' introuvable")
        return chemin_du_logo(self._get_workspace_path(workspace_id), identifiant,
                              self.base_path)
    
    def import_data_files(
        self,
        workspace_id: str,
        file_paths: Dict[str, str]
    ) -> Dict[str, int]:
        """
        Importe des fichiers data dans un workspace existant.
        
        Args:
            workspace_id: ID du workspace
            file_paths: Dict {type: chemin_source}
        
        Returns:
            Nouvelles statistiques
        """
        if not self.get_workspace(workspace_id):
            raise ValueError(f"Workspace '{workspace_id}' introuvable")
        
        stats = self._copy_data_files(workspace_id, file_paths)
        self.update_data_stats(workspace_id, stats)
        
        return stats
    
    def export_workspace(self, workspace_id: str, export_path: str) -> str:
        """Exporte un workspace en archive ZIP, hors de son propre répertoire.

        L'archive était écrite dans le dossier `output/` du workspace, et
        `shutil.make_archive` compressait le workspace **entier**, `output/`
        compris. L'archive s'ajoutait donc à elle-même pendant son écriture :
        sur un référentiel de 17 Mo, le fichier produit faisait **8,6 Go et
        n'était pas un ZIP valide**. Rien ne le signalait, rien ne le
        nettoyait, et il restait sur le disque du serveur.

        Deux garde-fous plutôt qu'un :

        - la destination ne peut pas être à l'intérieur du workspace, et c'est
          refusé explicitement ;
        - `output/` est exclu de l'archive. Il ne contient que des artefacts
          régénérables — exports, rapports — qui n'ont rien à faire dans une
          sauvegarde, et son exclusion rend l'auto-inclusion impossible même si
          le premier garde-fou venait à être contourné.

        Args:
            workspace_id: identifiant du workspace.
            export_path: répertoire de destination, **hors** du workspace.

        Returns:
            Chemin du fichier ZIP créé.

        Raises:
            ValueError: workspace introuvable, ou destination située dans le
                workspace à archiver.
        """
        ws_path = self._get_workspace_path(workspace_id)
        if not ws_path.exists():
            raise ValueError(f"Workspace '{workspace_id}' introuvable")

        racine = ws_path.resolve()
        destination = Path(export_path).resolve()
        if destination == racine or racine in destination.parents:
            raise ValueError(
                "La destination de l'export est à l'intérieur du workspace à "
                "archiver : l'archive s'inclurait elle-même.")

        horodatage = datetime.now().strftime('%Y%m%d_%H%M%S')
        export_file = destination / f"{workspace_id}_export_{horodatage}.zip"

        with zipfile.ZipFile(export_file, "w", zipfile.ZIP_DEFLATED) as archive:
            for chemin in sorted(racine.rglob("*")):
                if not chemin.is_file():
                    continue
                relatif = chemin.relative_to(racine)
                if relatif.parts[0] == DOSSIER_SORTIES:
                    continue
                archive.write(chemin, relatif)

        logger.info("Workspace %s exporté : %s (%d octets)",
                    workspace_id, export_file.name, export_file.stat().st_size)
        return str(export_file)


# Singleton global pour l'application
_workspace_manager: Optional[WorkspaceManager] = None


def get_workspace_manager() -> WorkspaceManager:
    """Retourne l'instance singleton du WorkspaceManager."""
    global _workspace_manager
    if _workspace_manager is None:
        _workspace_manager = WorkspaceManager()
    return _workspace_manager


def reset_workspace_manager() -> None:
    """Réinitialise le singleton (pour les tests)."""
    global _workspace_manager
    _workspace_manager = None
