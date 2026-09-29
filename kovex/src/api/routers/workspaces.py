# src/api/routers/workspaces.py
"""
API Router pour la gestion des Workspaces.
Permet de créer, switcher, et gérer les workspaces multi-clients.
"""

import os
import json
import logging
import shutil
import tempfile
import time
from typing import List, Dict, Any, Optional
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel, Field

from src.api.dependencies import clear_all_caches
from src.core.workspaces.workspace_manager import (
    WorkspaceManager,
    WorkspaceInfo,
    get_workspace_manager
)
from src.core.workspaces.theme_visuel import (
    DOSSIER_DES_THEMES,
    NOM_DU_DOCUMENT,
    ThemeInvalide,
    type_du_logo,
)
from src.api.journal import Journal, get_journal
from src.core.audit import Action

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])


# ========== MODELS ==========

class WorkspaceCreate(BaseModel):
    """Modèle pour la création d'un workspace."""
    name: str = Field(..., min_length=1, max_length=100, description="Nom affiché du workspace")
    client: str = Field(..., min_length=1, max_length=50, description="Nom du client")
    environment: str = Field(..., description="Environnement (DEV, PROD, TEST, UAT)")
    theme: str = Field(default="default", description="Thème visuel")


class WorkspaceUpdate(BaseModel):
    """Modèle pour la mise à jour d'un workspace."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    theme: Optional[str] = None


class WorkspaceResponse(BaseModel):
    """Réponse contenant les infos d'un workspace."""
    id: str
    name: str
    client: str
    environment: str
    created_at: str
    last_accessed: str
    theme: str
    data_stats: Dict[str, int]


class ThemeResponse(BaseModel):
    """Un thème utilisable par un workspace."""
    identifiant: str
    libelles: Dict[str, str]
    cle_du_libelle: str
    variantes: Dict[str, Dict[str, str]]
    logo: bool


class ThemeRefuseResponse(BaseModel):
    """Un thème déposé mais écarté, avec son motif traduisible."""
    code: str
    params: Dict[str, Any]


class ThemesListResponse(BaseModel):
    """Les thèmes d'un workspace : ceux qui servent, et ceux qui ont été refusés.

    `dossier` et `document` disent où déposer un thème. Ils voyagent avec la
    liste plutôt que d'être écrits dans l'interface : le format est décidé par
    le noyau, et deux endroits qui le décrivent finissent par se contredire.
    """
    themes: List[ThemeResponse]
    refuses: List[ThemeRefuseResponse]
    dossier: str
    document: str


class WorkspacesListResponse(BaseModel):
    """Liste des workspaces avec le workspace actif."""
    active_workspace: Optional[str]
    workspaces: List[WorkspaceResponse]
    count: int


class DataImportResponse(BaseModel):
    """Réponse après import de données."""
    status: str
    workspace_id: str
    stats: Dict[str, int]


# ========== DEPENDENCY ==========

def get_ws_manager() -> WorkspaceManager:
    """Dependency pour obtenir le WorkspaceManager."""
    return get_workspace_manager()


# ========== ENDPOINTS ==========

#: Taille maximale d'un fichier importé. Un référentiel de 500 000 identités
#: pèse environ 136 Mo ; le plafond laisse de la marge sans permettre à un
#: compte autorisé d'épuiser le disque ou la mémoire du serveur.
TAILLE_MAX_IMPORT = int(os.environ.get("KOVEX_IMPORT_MAX_BYTES", 512 * 1024 * 1024))

#: Taille des blocs de lecture pendant l'import.
TAILLE_BLOC_IMPORT = 1024 * 1024

#: Taille de l'extrait lu pour inspecter un fichier avant de l'importer.
#: Assez pour l'en-tête et quelques lignes ; assez peu pour qu'inspecter
#: quatre référentiels ne coûte rien, même sur des fichiers de 500 Mo.
TAILLE_EXTRAIT_INSPECTION = 64 * 1024

#: Référentiels du produit, dans l'ordre où ils se lisent, avec le nom du
#: fichier sous lequel chacun est rangé. Une seule table : le jour où un
#: cinquième référentiel apparaît, il n'y a qu'un endroit à changer.
FICHIERS_DU_WORKSPACE = {
    "identities": "identities.csv",
    "applications": "applications.csv",
    "rights": "droits.csv",
    "habs": "habilitations.csv",
}


def chemins_hors_perimetre(config: Dict[str, Any], perimetre: Path) -> List[str]:
    """Chemins de fichiers sources sortant du dossier du workspace.

    La comparaison se fait sur les chemins **résolus** : `..`, un chemin
    absolu et un lien symbolique doivent être ramenés à leur destination réelle
    avant d'être comparés, sinon le contrôle se contourne en une ligne.

    Un chemin relatif est résolu contre le répertoire de travail, exactement
    comme le fait le chargeur. Les deux barrières doivent résoudre de la même
    manière : résolues différemment, l'une accepterait ce que l'autre rejette,
    et le réglage enregistré ne s'appliquerait jamais.

    Un chemin vide n'est pas une anomalie : il signifie « fichier non
    configuré », ce que le chargeur sait traiter.
    """
    base = Path(perimetre).resolve()
    refuses: List[str] = []

    fichiers = config.get("files")
    if not isinstance(fichiers, dict):
        return refuses

    for description in fichiers.values():
        if not isinstance(description, dict):
            continue
        chemin = description.get("path") or ""
        if not chemin:
            continue
        try:
            Path(chemin).resolve().relative_to(base)
        except (ValueError, OSError):
            refuses.append(str(chemin))
    return refuses


@router.get("/", response_model=WorkspacesListResponse)
async def list_workspaces(manager: WorkspaceManager = Depends(get_ws_manager)):
    """
    Liste tous les workspaces disponibles.
    
    Returns:
        Liste des workspaces avec le workspace actif indiqué
    """
    workspaces = manager.list_workspaces()
    active = manager.get_active_workspace()
    
    return WorkspacesListResponse(
        active_workspace=active.id if active else None,
        workspaces=[WorkspaceResponse(**ws.to_dict()) for ws in workspaces],
        count=len(workspaces)
    )


@router.get("/active", response_model=Optional[WorkspaceResponse])
async def get_active_workspace(manager: WorkspaceManager = Depends(get_ws_manager)):
    """
    Retourne le workspace actuellement actif.
    
    Returns:
        WorkspaceResponse ou null si aucun workspace actif
    """
    active = manager.get_active_workspace()
    if active:
        return WorkspaceResponse(**active.to_dict())
    return None


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace_id: str,
    manager: WorkspaceManager = Depends(get_ws_manager)
):
    """
    Récupère les informations d'un workspace spécifique.
    
    Args:
        workspace_id: ID du workspace
    
    Returns:
        Informations du workspace
    """
    workspace = manager.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace.not_found",
                    "params": {"identifiant": workspace_id}})
    
    return WorkspaceResponse(**workspace.to_dict())


@router.post("/", response_model=WorkspaceResponse, status_code=201)
async def create_workspace(
    workspace_data: WorkspaceCreate,
    manager: WorkspaceManager = Depends(get_ws_manager),
    journal: Journal = Depends(get_journal),
):
    """
    Crée un nouveau workspace.
    
    Args:
        workspace_data: Informations du workspace à créer
    
    Returns:
        Workspace créé
    """
    try:
        workspace = manager.create_workspace(
            name=workspace_data.name,
            client=workspace_data.client,
            environment=workspace_data.environment,
            theme=workspace_data.theme
        )
        
        logger.info(f"Workspace créé: {workspace.id}")
        journal.consigner(
            Action.WORKSPACE_CREE, "workspace", workspace.id,
            {"nom": workspace_data.name, "client": workspace_data.client,
             "environnement": workspace_data.environment},
        )
        return WorkspaceResponse(**workspace.to_dict())

    except ThemeInvalide as refus:
        raise HTTPException(status_code=400,
                            detail={"code": refus.cle, "params": refus.parametres})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/switch/{workspace_id}", response_model=WorkspaceResponse)
async def switch_workspace(
    workspace_id: str,
    manager: WorkspaceManager = Depends(get_ws_manager),
    journal: Journal = Depends(get_journal),
):
    """
    Bascule vers un autre workspace.
    
    Cette action:
    - Met à jour le workspace actif
    - Met à jour last_accessed du workspace cible
    - Nécessite un rechargement du DataLoader côté client
    
    Args:
        workspace_id: ID du workspace cible
    
    Returns:
        Workspace maintenant actif
    """
    try:
        workspace = manager.switch_workspace(workspace_id)
        
        # Invalider le cache du DataLoader
        # Le frontend devra appeler /reload-data après le switch
        
        logger.info(f"Switch vers workspace: {workspace_id}")
        # Le workspace actif détermine sur quelles données portent toutes les
        # décisions suivantes : la bascule fait partie du contexte d'audit.
        journal.consigner(Action.WORKSPACE_ACTIVE, "workspace", workspace_id)
        return WorkspaceResponse(**workspace.to_dict())
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: str,
    updates: WorkspaceUpdate,
    manager: WorkspaceManager = Depends(get_ws_manager)
):
    """
    Met à jour les informations d'un workspace.
    
    Args:
        workspace_id: ID du workspace
        updates: Champs à mettre à jour
    
    Returns:
        Workspace mis à jour
    """
    try:
        # Filtrer les champs non-None
        update_dict = {k: v for k, v in updates.dict().items() if v is not None}
        
        workspace = manager.update_workspace(workspace_id, update_dict)
        return WorkspaceResponse(**workspace.to_dict())

    except ThemeInvalide as refus:
        raise HTTPException(status_code=400,
                            detail={"code": refus.cle, "params": refus.parametres})
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{workspace_id}/themes", response_model=ThemesListResponse)
async def list_workspace_themes(
    workspace_id: str,
    manager: WorkspaceManager = Depends(get_ws_manager)
):
    """Les thèmes déposés dans un workspace, et le motif de ceux qui sont refusés.

    Les refus sont renvoyés avec la liste, et non tus : un thème déposé qui
    n'apparaît nulle part sans explication renvoie l'utilisateur à une
    devinette entre un fichier mal placé, mal nommé et mal formé.
    """
    try:
        themes, refuses = manager.themes_du_workspace(workspace_id)
    except ValueError:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace.not_found",
                    "params": {"identifiant": workspace_id}})

    return ThemesListResponse(
        themes=[ThemeResponse(**theme.to_dict()) for theme in themes],
        refuses=[ThemeRefuseResponse(code=refus.cle, params=refus.parametres)
                 for refus in refuses],
        dossier=DOSSIER_DES_THEMES,
        document=NOM_DU_DOCUMENT,
    )


@router.get("/{workspace_id}/themes/{theme_id}/logo")
async def get_workspace_theme_logo(
    workspace_id: str,
    theme_id: str,
    manager: WorkspaceManager = Depends(get_ws_manager)
):
    """Sert le logo d'un thème.

    Le nom du fichier vient du thème déjà validé, jamais de l'URL : le segment
    de chemin reçu ne désigne qu'un thème, dont le contenu a été contrôlé au
    chargement. Le type servi est choisi dans la table des types acceptés et
    non déduit du nom, pour qu'aucun fichier ne soit rendu sous un type qu'il
    n'a pas.
    """
    try:
        theme = manager.theme_du_workspace(workspace_id, theme_id)
        if not theme.logo:
            raise ThemeInvalide("theme.logo_missing", theme=theme_id, logo="")
        # Le dossier vient du thème retenu, et non d'un emplacement présumé :
        # un thème livré avec l'instance ne vit pas dans l'espace de travail.
        chemin = manager.chemin_du_logo_du_theme(workspace_id, theme_id)
    except ThemeInvalide as refus:
        raise HTTPException(status_code=404,
                            detail={"code": refus.cle, "params": refus.parametres})
    except ValueError:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace.not_found",
                    "params": {"identifiant": workspace_id}})

    return FileResponse(
        path=str(chemin),
        media_type=type_du_logo(theme.logo),
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.delete("/{workspace_id}")
async def delete_workspace(
    workspace_id: str,
    manager: WorkspaceManager = Depends(get_ws_manager),
    journal: Journal = Depends(get_journal),
):
    """
    Supprime un workspace.
    
    ATTENTION: Cette action supprime définitivement:
    - Les fichiers de données
    - La Knowledge Base
    - Les exports
    
    Args:
        workspace_id: ID du workspace à supprimer
    
    Returns:
        Confirmation de suppression
    """
    try:
        manager.delete_workspace(workspace_id)
        # Consigné avant tout : la piste vit hors des workspaces, elle survit
        # donc à la suppression de celui-ci — c'est tout l'intérêt.
        journal.consigner(Action.WORKSPACE_SUPPRIME, "workspace", workspace_id)

        # Récupérer le nouveau workspace actif
        new_active = manager.get_active_workspace()
        
        return {
            "status": "deleted",
            "workspace_id": workspace_id,
            "new_active_workspace": new_active.id if new_active else None
        }
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


#: Reprises de la mise en place d'un fichier importé, et attente entre deux.
#:
#: Sur un poste Windows d'entreprise, `os.replace` échoue régulièrement pour
#: des raisons qui durent une fraction de seconde et n'appartiennent pas au
#: produit : un antivirus qui tient encore le fichier qu'on vient d'écrire, un
#: dossier synchronisé par un client de stockage. Abandonner au premier refus
#: transformait cet aléa en échec d'import.
REPRISES_DE_MISE_EN_PLACE = 5
ATTENTE_ENTRE_REPRISES_S = 0.3


def mettre_en_place(source: Path, cible: Path) -> None:
    """Remplace `cible` par `source`, en réessayant les refus passagers.

    Le remplacement reste atomique : c'est `os.replace` qui travaille, on lui
    laisse seulement plusieurs chances. Un refus qui persiste après toutes les
    reprises est rendu à l'appelant — il ne s'agit alors plus d'un aléa, et le
    masquer laisserait l'utilisateur devant un import « réussi » sans données.
    """
    for reprise in range(REPRISES_DE_MISE_EN_PLACE):
        try:
            source.replace(cible)
            return
        except OSError:
            if reprise == REPRISES_DE_MISE_EN_PLACE - 1:
                raise
            time.sleep(ATTENTE_ENTRE_REPRISES_S)


async def _extrait(fichier: Optional[UploadFile]) -> bytes:
    """Les premiers octets d'un envoi, et pas un de plus.

    Inspecter ne demande pas le fichier entier : l'en-tête et quelques lignes
    suffisent. Lire davantage donnerait à n'importe quel compte autorisé le
    moyen d'occuper la mémoire du serveur pour une opération qui ne l'exige
    pas.
    """
    return await fichier.read(TAILLE_EXTRAIT_INSPECTION) if fichier else b""


def _correspondance_configuree(manager: WorkspaceManager,
                               workspace_id: str) -> Dict[str, Any]:
    """Ce que la configuration du workspace déclare aujourd'hui.

    Rendu avec l'inspection pour que l'écran propose ce qui est déjà en place
    plutôt que de repartir de zéro à chaque nouvel import — et pour qu'on voie
    d'un coup d'œil si la déclaration correspond encore au fichier.
    """
    chemin = manager.get_workspace_config_path(workspace_id)
    try:
        configuration = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    fichiers = configuration.get("files") or {}
    return {
        cle: {"separateur": reglage.get("delimiter", ""),
              "encodage": reglage.get("encoding", ""),
              "id_column": reglage.get("id_column", ""),
              "app_id_column": reglage.get("app_id_column", ""),
              "user_id_column": reglage.get("user_id_column", ""),
              "right_id_column": reglage.get("right_id_column", "")}
        for cle, reglage in fichiers.items()
        if cle in FICHIERS_DU_WORKSPACE and isinstance(reglage, dict)
    }


@router.post("/{workspace_id}/inspecter-fichiers")
async def inspecter_fichiers(
    workspace_id: str,
    identities: Optional[UploadFile] = File(None),
    applications: Optional[UploadFile] = File(None),
    rights: Optional[UploadFile] = File(None),
    habs: Optional[UploadFile] = File(None),
    manager: WorkspaceManager = Depends(get_ws_manager),
):
    """Ce que les fichiers contiennent, avant de décider quoi en faire.

    Le produit ne connaît pas les colonnes à l'avance. Il lit un extrait, dit
    quel encodage le décode, quel séparateur le découpe régulièrement, quelles
    colonnes il porte — et **ne décide rien**. La personne confirme, et c'est
    sa confirmation qui sera écrite dans la configuration.

    Cette route ne touche à rien : ni au workspace, ni aux fichiers déjà en
    place. Elle lit ce qu'on lui donne et rend ce qu'elle y a vu.
    """
    from src.core.data.inspection import inspecter

    workspace = manager.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace.not_found",
                    "params": {"identifiant": workspace_id}})

    envois = {"identities": identities, "applications": applications,
              "rights": rights, "habs": habs}
    resultats = {}
    for cle, envoi in envois.items():
        if envoi is None:
            continue
        resultats[cle] = inspecter(await _extrait(envoi))

    if not resultats:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "workspace.import_no_file"})

    return {"fichiers": resultats,
            "correspondance_actuelle": _correspondance_configuree(manager, workspace_id)}


def _correspondance_demandee(brut: Optional[str]):
    """La correspondance déclarée, validée avant d'être regardée.

    Elle arrive en JSON dans un envoi multipart — un formulaire de fichiers ne
    sait pas transporter d'objet. Elle est donc relue par le schéma, qui refuse
    tout champ inconnu : une correspondance qui porterait un chemin ferait
    écrire n'importe où par une route d'import.
    """
    from src.api.schemas import CorrespondanceDesFichiers

    if not brut:
        return None
    try:
        return CorrespondanceDesFichiers.model_validate(json.loads(brut))
    except (ValueError, TypeError) as erreur:
        logger.info("Correspondance de fichiers refusée : %s", erreur)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "workspace.import_mapping_invalid"})


def _verifier_la_correspondance(temporaires: Dict[str, Path],
                                correspondance) -> None:
    """Refuse une déclaration que le fichier ne porte pas.

    C'est le contrôle qui manquait. Le chargeur ne renomme que les colonnes
    qu'il trouve et se tait sur les autres : une colonne déclarée mais absente
    donnait un référentiel vide, sans un mot. On préfère un refus au moment du
    chargement, quand la personne a encore le fichier sous la main.
    """
    from src.core.data.inspection import (colonnes_du_fichier,
                                          correspondance_invalide)

    for cle, temporaire in temporaires.items():
        declaration = getattr(correspondance, cle, None)
        if declaration is None:
            continue
        colonnes = colonnes_du_fichier(temporaire, declaration.separateur,
                                       declaration.encodage)
        absentes = correspondance_invalide(colonnes, [
            declaration.id_column, declaration.app_id_column,
            declaration.user_id_column, declaration.right_id_column])
        if absentes:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "workspace.import_column_missing",
                        "params": {"fichier": cle,
                                   "colonnes": ", ".join(absentes)}})


def _ecrire_la_correspondance(manager: WorkspaceManager, workspace_id: str,
                              correspondance) -> List[str]:
    """Écrit la déclaration dans la configuration du workspace.

    Seuls les réglages de lecture sont touchés : le chemin du fichier reste
    celui que le produit a posé. Une route d'import n'a pas à décider d'où les
    données sont lues.
    """
    chemin = manager.get_workspace_config_path(workspace_id)
    try:
        configuration = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.error("Configuration du workspace %s illisible : la "
                     "correspondance déclarée n'a pas été écrite", workspace_id)
        return []

    fichiers = configuration.setdefault("files", {})
    ecrits = []
    for cle in FICHIERS_DU_WORKSPACE:
        declaration = getattr(correspondance, cle, None)
        if declaration is None:
            continue
        reglage = fichiers.setdefault(cle, {})
        reglage.update({
            "delimiter": declaration.separateur,
            "encoding": declaration.encodage,
            "id_column": declaration.id_column,
            "app_id_column": declaration.app_id_column,
            "user_id_column": declaration.user_id_column,
            "right_id_column": declaration.right_id_column,
        })
        ecrits.append(cle)

    chemin.write_text(json.dumps(configuration, indent=4, ensure_ascii=False),
                      encoding="utf-8")
    return ecrits


@router.post("/{workspace_id}/import-data", response_model=DataImportResponse)
async def import_data_files(
    workspace_id: str,
    identities: Optional[UploadFile] = File(None, description="Fichier identités CSV"),
    applications: Optional[UploadFile] = File(None, description="Fichier applications CSV"),
    rights: Optional[UploadFile] = File(None, description="Fichier droits CSV"),
    habs: Optional[UploadFile] = File(None, description="Fichier habilitations CSV"),
    correspondance: Optional[str] = Form(
        None, description="Correspondance déclarée, en JSON"),
    manager: WorkspaceManager = Depends(get_ws_manager),
    journal: Journal = Depends(get_journal),
):
    """
    Importe des fichiers de données dans un workspace.
    
    Accepte les fichiers CSV pour:
    - identities: Utilisateurs/Identités
    - applications: Applications
    - rights: Droits/Permissions
    - habs: Habilitations (liens user-right)
    
    Args:
        workspace_id: ID du workspace cible
        identities, applications, rights, habs: Fichiers CSV uploadés
    
    Returns:
        Statistiques des données importées
    """
    workspace = manager.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace.not_found",
                    "params": {"identifiant": workspace_id}})
    
    data_path = manager.get_workspace_data_path(workspace_id)
    data_path.mkdir(parents=True, exist_ok=True)
    
    declaree = _correspondance_demandee(correspondance)

    envois = {"identities": identities, "applications": applications,
              "rights": rights, "habs": habs}
    file_mapping = {cle: (envois[cle], nom)
                    for cle, nom in FICHIERS_DU_WORKSPACE.items()}
    
    stats = {"users": 0, "apps": 0, "rights": 0, "habs": 0}
    stat_keys = {"identities": "users", "applications": "apps", "rights": "rights", "habs": "habs"}
    
    # L'import écrivait directement dans le fichier de destination, ouvert en
    # 'wb' donc **tronqué avant la première écriture**. Un disque plein, un
    # client interrompu ou un fichier verrouillé détruisaient le référentiel
    # existant, l'erreur était avalée par un simple journal, et la réponse
    # restait `200 {"status": "imported"}` avec des compteurs faux.
    #
    # Chaque fichier est désormais écrit à côté, puis mis en place seulement
    # une fois complet. Le moindre échec annule l'ensemble de l'import : un
    # référentiel à moitié remplacé n'a aucun sens, les fichiers se référencent
    # entre eux par identifiants.
    # Deux listes distinctes, et c'est nécessaire : `crees` sert au nettoyage,
    # `temporaires` à la mise en place. Un fichier dont l'écriture échoue en
    # cours de route existe déjà sur le disque mais n'est pas exploitable ; ne
    # tenir qu'une seule liste, alimentée après succès, laissait ces fichiers
    # `.import` derrière chaque échec — et un envoi trop volumineux laissait
    # sa partie déjà écrite occuper le disque.
    crees: List[Path] = []
    temporaires: Dict[str, Path] = {}
    try:
        for file_type, (upload_file, target_name) in file_mapping.items():
            if not upload_file:
                continue

            destination = data_path / target_name
            temporaire = destination.with_suffix(destination.suffix + ".import")
            crees.append(temporaire)

            # Écriture par blocs plutôt qu'un `read()` unique : un référentiel
            # de 500 000 identités pèse déjà 136 Mo, et rien ne bornait la
            # taille acceptée. Tout charger en mémoire donne à n'importe quel
            # compte autorisé le moyen d'épuiser celle du serveur.
            octets = 0
            lignes = 0
            dernier_octet = b""
            with open(temporaire, "wb") as flux:
                while True:
                    bloc = await upload_file.read(TAILLE_BLOC_IMPORT)
                    if not bloc:
                        break
                    octets += len(bloc)
                    if octets > TAILLE_MAX_IMPORT:
                        raise ValueError(
                            f"fichier {file_type} trop volumineux "
                            f"(limite : {TAILLE_MAX_IMPORT} octets)"
                        )
                    lignes += bloc.count(b"\n")
                    dernier_octet = bloc[-1:]
                    flux.write(bloc)
                flux.flush()
                os.fsync(flux.fileno())

            # Une ligne n'est pas un caractère `\n` : la dernière ligne d'un
            # fichier n'en porte pas, et un tableur comme une main humaine
            # n'en mettent pas. Compter les retours à la ligne perdait donc
            # une identité, un droit et une habilitation à chaque import —
            # et ce chiffre est repris dans la piste d'audit, qui atteste de
            # ce qui a été chargé.
            if dernier_octet and dernier_octet != b"\n":
                lignes += 1

            if octets == 0:
                raise ValueError(f"fichier {file_type} vide")

            temporaires[file_type] = temporaire
            stats[stat_keys[file_type]] = max(0, lignes - 1)  # l'en-tête ne compte pas

    except Exception as erreur:
        for temporaire in crees:
            try:
                temporaire.unlink()
            except OSError:
                pass
        logger.exception("Import de données interrompu pour le workspace %s", workspace_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "workspace.import_failed", "params": {"reason": str(erreur)}},
        )

    if not temporaires:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "workspace.import_no_file"},
        )

    # La correspondance se vérifie sur le fichier temporaire, **avant** la mise
    # en place : refuser après aurait déjà remplacé le référentiel.
    if declaree is not None:
        try:
            _verifier_la_correspondance(temporaires, declaree)
        except HTTPException:
            for temporaire in crees:
                try:
                    temporaire.unlink()
                except OSError:
                    pass
            raise

    # Mise en place : `replace` est atomique, le référentiel précédent n'est
    # remplacé qu'une fois le nouveau intégralement sur le disque.
    for file_type, temporaire in temporaires.items():
        try:
            mettre_en_place(temporaire, data_path / file_mapping[file_type][1])
        except OSError as erreur:
            logger.error("Mise en place impossible pour %s (%s) : %s",
                         file_type, workspace_id, erreur)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "workspace.import_locked",
                        "params": {"file": file_mapping[file_type][1]}},
            )

    # La déclaration est écrite après la mise en place : une configuration qui
    # décrirait des fichiers qui ne sont pas arrivés serait pire que pas de
    # configuration du tout.
    correspondance_ecrite = (_ecrire_la_correspondance(manager, workspace_id, declaree)
                             if declaree is not None else [])

    manager.update_data_stats(workspace_id, stats)
    # Les données du workspace actif ont changé : les caches doivent tomber,
    # sans quoi l'application continue de servir le référentiel précédent.
    clear_all_caches()
    # Remplacer le référentiel change ce sur quoi porteront toutes les
    # décisions suivantes, et invalide les rôles déjà validés : la piste
    # d'audit doit pouvoir dater ce basculement.
    journal.consigner(
        Action.DONNEES_IMPORTEES, "workspace", workspace_id,
        {"fichiers": sorted(temporaires),
         "correspondance": sorted(correspondance_ecrite), **stats},
    )
    logger.info(
        "Import terminé pour %s : %s",
        workspace_id, ", ".join(f"{cle}={valeur}" for cle, valeur in stats.items()),
    )

    return DataImportResponse(
        status="imported",
        workspace_id=workspace_id,
        stats=stats
    )


@router.get("/{workspace_id}/config")
async def get_workspace_config(
    workspace_id: str,
    manager: WorkspaceManager = Depends(get_ws_manager)
):
    """
    Récupère la configuration d'un workspace.
    
    Args:
        workspace_id: ID du workspace
    
    Returns:
        Configuration du workspace (fichiers, paramètres mining, etc.)
    """
    workspace = manager.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace.not_found",
                    "params": {"identifiant": workspace_id}})
    
    config_path = manager.get_workspace_config_path(workspace_id)
    
    if not config_path.exists():
        raise HTTPException(
            status_code=404, detail={"code": "workspace.config_missing"})
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as erreur:
        # Le détail reste au journal : renvoyé, il décrivait l'arborescence du
        # serveur à qui savait provoquer l'erreur.
        logger.error("Configuration du workspace %s illisible : %s",
                     workspace_id, erreur)
        raise HTTPException(
            status_code=500, detail={"code": "settings.unreadable"})


@router.put("/{workspace_id}/config")
async def update_workspace_config(
    workspace_id: str,
    config: Dict[str, Any],
    manager: WorkspaceManager = Depends(get_ws_manager),
    journal: Journal = Depends(get_journal),
):
    """
    Met à jour la configuration d'un workspace.
    
    Args:
        workspace_id: ID du workspace
        config: Nouvelle configuration
    
    Returns:
        Configuration mise à jour
    """
    workspace = manager.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace.not_found",
                    "params": {"identifiant": workspace_id}})

    config_path = manager.get_workspace_config_path(workspace_id)

    # Un chemin de fichier source doit désigner un fichier du workspace, et
    # rien d'autre. Sans ce contrôle, y écrire `.env` puis consulter
    # l'explorateur rendait le contenu du fichier — donc la clé de signature
    # des jetons — par une réponse d'API parfaitement normale.
    hors_perimetre = chemins_hors_perimetre(config, config_path.parent)
    if hors_perimetre:
        raise HTTPException(
            status_code=422,
            detail={"code": "workspace.config_path_outside",
                    "params": {"chemins": ", ".join(sorted(hors_perimetre))}},
        )

    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)

        # Seules les clés changent de mains dans la piste : une configuration
        # peut contenir des chemins et, demain, une référence de secret.
        journal.consigner(
            Action.CONFIG_MODIFIEE, "workspace", workspace_id,
            {"champs": sorted(str(cle) for cle in config.keys())},
        )
        return {"status": "updated", "config": config}
        
    except Exception as erreur:
        logger.error("Configuration du workspace %s non enregistrée : %s",
                     workspace_id, erreur)
        raise HTTPException(
            status_code=500, detail={"code": "settings.not_saved"})


def _effacer_repertoire(chemin: str) -> None:
    """Efface le répertoire temporaire d'un export, sans faire échouer la
    réponse déjà partie."""
    shutil.rmtree(chemin, ignore_errors=True)


@router.post("/{workspace_id}/export")
async def export_workspace(
    workspace_id: str,
    manager: WorkspaceManager = Depends(get_ws_manager)
):
    """
    Exporte un workspace complet en archive ZIP.
    
    Args:
        workspace_id: ID du workspace
    
    Returns:
        Fichier ZIP téléchargeable

    L'archive était construite dans le dossier `output/` du workspace,
    c'est-à-dire **à l'intérieur de ce qu'elle compressait** : elle s'incluait
    elle-même et produisait un fichier de plusieurs gigaoctets, illisible, que
    rien ne nettoyait. Elle est désormais construite dans un répertoire
    temporaire propre à la requête, puis effacée une fois la réponse envoyée —
    le même traitement que les exports de qualité des données.
    """
    workspace = manager.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace.not_found",
                    "params": {"identifiant": workspace_id}})
    
    try:
        repertoire = tempfile.mkdtemp(prefix="kovex-export-")
        try:
            zip_path = manager.export_workspace(workspace_id, repertoire)
        except Exception:
            _effacer_repertoire(repertoire)
            raise

        return FileResponse(
            path=zip_path,
            filename=Path(zip_path).name,
            media_type="application/zip",
            background=BackgroundTask(_effacer_repertoire, repertoire),
        )
        
    except Exception as erreur:
        logger.error("Export du workspace %s impossible : %s", workspace_id, erreur)
        raise HTTPException(
            status_code=500, detail={"code": "workspace.export_failed"})


@router.get("/{workspace_id}/kb-path")
async def get_workspace_kb_path(
    workspace_id: str,
    manager: WorkspaceManager = Depends(get_ws_manager)
):
    """
    Retourne le chemin de la KB d'un workspace.
    Utile pour l'intégration avec les autres modules.
    
    Args:
        workspace_id: ID du workspace
    
    Returns:
        Chemin de la KB
    """
    workspace = manager.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace.not_found",
                    "params": {"identifiant": workspace_id}})
    
    kb_path = manager.get_workspace_kb_path(workspace_id)
    
    return {
        "workspace_id": workspace_id,
        "kb_path": str(kb_path),
        "exists": kb_path.exists()
    }


# === ENDPOINTS POUR INTÉGRATION AVEC DATA LOADER ===

@router.post("/reload-data")
async def reload_data_for_active_workspace(
    manager: WorkspaceManager = Depends(get_ws_manager)
):
    """Recharge réellement les données du workspace actif.

    Ce point d'entrée ne rechargeait rien : il rendait un chemin de
    configuration accompagné d'un commentaire « ici on pourrait invalider le
    cache ». Le client l'appelait après avoir modifié les fichiers sur le
    disque et l'application continuait de servir le référentiel précédent,
    sans aucun signe visible.

    Il ne rend plus de chemin serveur non plus : l'emplacement des fichiers
    sur la machine ne regarde pas le navigateur.
    """
    active = manager.get_active_workspace()
    if not active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "workspace.none_active", "params": {}},
        )

    clear_all_caches()
    logger.info("Données rechargées pour le workspace %s", active.id)

    return {"status": "reloaded", "workspace_id": active.id}
