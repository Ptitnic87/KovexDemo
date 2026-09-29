# src/api/routers/business.py

from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import json
import logging
import os
import uuid
from datetime import datetime

# Import des schémas (RoleRBAC pour la lecture, RoleCreate pour la création manuelle)
from src.api.schemas import RoleRBAC, RoleCreate
from src.core.data.loader import DataLoader
from src.api.dependencies import get_data_loader

logger = logging.getLogger(__name__)

router = APIRouter()

# Fichier de stockage (Base de données fichier)
ROLES_FILE = "business_roles.json"

# --- Modèle pour la création (Input du Mining) ---
class BusinessRoleCreate(BaseModel):
    name: str
    description: str = ""
    rights: List[str]
    attributes: Dict[str, Any]
    user_count: int
    stats: Optional[Dict[str, Any]] = None

# Les trois routes de ce module ont été retirées : GET /roles, POST /roles et
# POST /business/create.
#
# Elles lisaient et écrivaient `business_roles.json`, un chemin relatif nu,
# résolu contre le répertoire du processus et donc **hors workspace**. Les rôles
# métier d'un client — identifiants de droits et valeurs d'attributs RH —
# étaient écrits dans un fichier unique et restitués à l'utilisateur d'un autre
# workspace.
#
# Elles doublaient par ailleurs les routes de `roles.py` à une barre oblique
# près : `GET /api/v1/roles` servait ce fichier global, `GET /api/v1/roles/` la
# Knowledge Base du workspace. Deux réponses de forme et de source différentes
# selon la présence d'un caractère, et le frontend lisait sur l'une en écrivant
# sur l'autre.
#
# La source de vérité des rôles est la Knowledge Base du workspace actif, servie
# par `roles.py`. Le fichier `business_roles.json`, s'il existe sur une
# installation, est à archiver puis à supprimer : son contenu peut mêler
# plusieurs clients.


# GET /rights a été retiré d'ici : la même route était déclarée par
# `explorer.py`, enregistré avant ce routeur, si bien que cette version n'était
# jamais atteinte. Deux implémentations pour une seule route, dont une morte.
# Le référentiel des droits est servi par `explorer.get_all_rights`.