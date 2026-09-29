# src/api/routers/settings.py
"""Lecture et écriture de la configuration du workspace actif.

Cet écran écrivait dans `config/config.json`, la configuration de repli, alors
que le chargeur de données lit **en priorité** le `config.json` du workspace
actif. Tant qu'un workspace était actif — c'est le cas normal — les réglages
saisis ici n'étaient jamais relus : l'utilisateur croyait paramétrer, rien ne
changeait.

L'écriture se fait désormais au même endroit que la lecture, et **par fusion** :
les clés que le modèle ne connaît pas sont conservées telles quelles. Sans cela,
enregistrer depuis cet écran effaçait les réglages absents du modèle — dont
`mining_attribute_max_cardinality_ratio`, qui pilote les attributs proposés au
mining métier.

Il subsistait un repli vers `config/config.json` quand aucun workspace n'était
actif. Cet écran écrivait alors des chemins de fichiers sources dans un
document que le chargeur lisait **sans périmètre de lecture** : y inscrire
`.env` puis consulter l'explorateur rendait la clé de signature des jetons. Le
repli est supprimé des deux côtés — hors d'un workspace, il n'y a rien à
configurer — et les chemins sont vérifiés à l'écriture comme ils le sont déjà
à l'import d'un workspace.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, status

from src.api.dependencies import (
    clear_all_caches,
    get_active_workspace_config_path,
)
from src.api.routers.workspaces import chemins_hors_perimetre
from src.api.schemas import AppConfigModel
from src.core.knowledge.nommage import (
    ConventionInvalide, depuis_la_configuration)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings")


def chemin_de_configuration() -> Path:
    """Le fichier que le chargeur lira : celui du workspace actif.

    Aucun repli : le chargeur de données n'en a plus, et écrire des réglages
    dans un fichier que rien ne relit est précisément le défaut que cet écran
    a déjà connu.
    """
    chemin_workspace = get_active_workspace_config_path()
    if chemin_workspace is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "workspace.none_active"},
        )
    return Path(chemin_workspace)


def lire_la_configuration(chemin: Path) -> Dict[str, Any]:
    if not chemin.exists():
        return {}
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as erreur:
        logger.error("Configuration illisible (%s) : %s", chemin, erreur)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "settings.unreadable"},
        )


@router.get("/", response_model=AppConfigModel)
def get_settings() -> AppConfigModel:
    """Retourne la configuration effective, celle que le chargeur applique."""
    return AppConfigModel(**lire_la_configuration(chemin_de_configuration()))


@router.post("/", response_model=AppConfigModel)
def save_settings(config: AppConfigModel) -> AppConfigModel:
    """Enregistre la configuration là où le chargeur la lira.

    Les clés absentes du modèle sont préservées : l'écran ne connaît pas tous
    les réglages d'un workspace, il n'a pas à les effacer.
    """
    chemin = chemin_de_configuration()
    existant = lire_la_configuration(chemin)
    # Pydantic v1 et v2 exposent l'export sous deux noms différents ; le poste
    # cible tourne en Python 3.14, la version de Pydantic n'y est pas figée.
    nouveau = config.model_dump() if hasattr(config, "model_dump") else config.dict()
    existant.update(nouveau)

    # Une convention de nommage est refusée ici, et non dans le modèle : ce
    # même modèle sert à relire la configuration, et un refus à la lecture
    # rendrait l'écran inaccessible sur le seul workspace où il faut aller la
    # corriger. Refusée seulement à l'écriture, elle ne s'installe jamais.
    #
    # La règle n'est pas réécrite : c'est la lecture du moteur qui est
    # appelée. Deux règles séparées divergeraient, et l'écran finirait par
    # accepter une convention que le chargeur écarte — donc un réglage
    # enregistré qui ne s'applique jamais, ce que rien n'indiquerait.
    try:
        depuis_la_configuration(existant)
    except ConventionInvalide as erreur:
        # Les valeurs attendues sont jointes ici : le message générique des
        # erreurs d'API substitue les paramètres tels quels, et une liste
        # brute s'y afficherait collée. L'écran du découpage les joint déjà
        # de son côté ; la phrase doit se lire pareil des deux endroits.
        params = erreur.document()
        params["attendues"] = ", ".join(params["attendues"])
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "nommage.invalide", "params": params},
        )

    # Première barrière : refuser d'écrire un chemin sortant du workspace. Le
    # chargeur refuse aussi de le lire, mais un réglage accepté puis ignoré
    # laisse croire qu'il s'applique — l'écran doit dire non tout de suite.
    hors_perimetre = chemins_hors_perimetre(existant, chemin.parent)
    if hors_perimetre:
        logger.warning("Chemins refusés hors du workspace : %s", hors_perimetre)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "workspace.config_path_outside",
                    "params": {"chemins": ", ".join(hors_perimetre)}},
        )

    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(
            json.dumps(existant, indent=4, ensure_ascii=False), encoding="utf-8"
        )
    except OSError as erreur:
        logger.error("Écriture de la configuration impossible (%s) : %s", chemin, erreur)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "settings.not_saved"},
        )

    # La configuration est mise en cache par le chargeur : sans purge, la
    # modification ne prendrait effet qu'au prochain démarrage.
    clear_all_caches()
    logger.info("Configuration enregistrée dans %s", chemin)

    return AppConfigModel(**existant)
