# Fichier : src/api/routers/auth.py
"""
Routes d'authentification pour PyGIA.
"""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, OAuth2PasswordRequestForm
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

from typing import Optional

from src.core.security import (
    User,
    user_manager,
    create_access_token,
    get_current_user,
    get_current_active_user,
    ACCESS_TOKEN_EXPIRE_MINUTES,
)
from src.core.security.auth import (
    SESSION_MAX_MINUTES,
    decode_access_token,
    security,
)

router = APIRouter(
    prefix="/auth",
    tags=["Authentification"]
)


# ============================================================================
# SCHEMAS
# ============================================================================

class Token(BaseModel):
    """Réponse de token d'authentification."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # Secondes
    user: dict


class LoginRequest(BaseModel):
    """Requête de connexion."""
    username: str
    password: str


class UserResponse(BaseModel):
    """Réponse utilisateur (sans données sensibles)."""
    username: str
    email: str
    full_name: str
    role: str


class ChangePasswordRequest(BaseModel):
    """Requête de changement de mot de passe.

    La longueur minimale est le seul contrôle imposé : une politique de
    complexité relève de la gouvernance du client, elle n'a pas à être décidée
    dans le code du produit.
    """

    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=12)


# ============================================================================
# ROUTES
# ============================================================================

@router.post("/login", response_model=Token)
async def login(request: LoginRequest, http_request: Request):
    """Authentifie un utilisateur et retourne un jeton JWT.

    Ce docstring listait les trois comptes livrés et leurs mots de passe.
    FastAPI le publie dans `/openapi.json`, que la documentation interactive
    sert **sans jeton** hors production : les identifiants d'administration
    étaient donc lisibles par quiconque atteignait le port de l'API.
    """
    user = user_manager.authenticate(request.username, request.password)

    if not user:
        logger.warning(
            "Échec d'authentification pour '%s' depuis %s",
            request.username,
            http_request.client.host if http_request.client else "origine inconnue",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "auth.invalid_credentials"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.info(
        "Connexion de '%s' (%s) depuis %s",
        user.username, user.role,
        http_request.client.host if http_request.client else "origine inconnue",
    )
    
    # Créer le token
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role,
              "token_version": user.token_version},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    
    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user={
            "username": user.username,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role
        }
    )


@router.post("/token", response_model=Token)
async def login_oauth2(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    Endpoint OAuth2 standard (pour compatibilité Swagger UI).
    """
    user = user_manager.authenticate(form_data.username, form_data.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "auth.invalid_credentials"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role,
              "token_version": user.token_version},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    
    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user={
            "username": user.username,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role
        }
    )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_active_user)):
    """
    Retourne les informations de l'utilisateur connecté.
    """
    return UserResponse(
        username=current_user.username,
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role
    )


@router.post("/logout")
async def logout(current_user: User = Depends(get_current_user)):
    """Journalise la déconnexion. Le jeton reste valide jusqu'à son expiration.

    Un jeton JWT ne se révoque pas sans registre de révocation, qui n'existe
    pas encore. Cet endpoint ne prétend donc pas invalider quoi que ce soit :
    il trace la déconnexion, et le client oublie son jeton.
    """
    logger.info("Déconnexion de '%s'", current_user.username)
    return {"code": "auth.logged_out"}


@router.post("/change-password")
async def change_password(
    request: ChangePasswordRequest,
    current_user: User = Depends(get_current_active_user),
):
    """Change le mot de passe du compte connecté.

    Cet endpoint n'existait pas : le modèle de requête était défini et
    inutilisé. Sans lui, aucun utilisateur ne pouvait changer son mot de passe,
    et le compte créé à l'initialisation avec un mot de passe aléatoire
    journalisé une seule fois était inutilisable dans la durée.
    """
    if not user_manager.verify_password(current_user.username, request.current_password):
        logger.warning(
            "Changement de mot de passe refusé pour '%s' : mot de passe actuel invalide",
            current_user.username,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "auth.current_password_invalid"},
        )

    if request.new_password == request.current_password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "auth.password_unchanged"},
        )

    if not user_manager.set_password(current_user.username, request.new_password):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "auth.password_not_changed"},
        )

    logger.info("Mot de passe changé pour '%s'", current_user.username)
    return {"code": "auth.password_changed"}


@router.post("/refresh", response_model=Token)
async def refresh_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    current_user: User = Depends(get_current_active_user),
):
    """Renouvelle le jeton du compte connecté, dans la limite de la session.

    Le renouvellement reconduit l'instant de **connexion initiale**, il ne le
    remet pas à zéro. Sans ce report, la chaîne de renouvellements prolongeait
    un jeton volé indéfiniment : chaque appel repoussait l'échéance, et rien
    n'y mettait jamais fin.
    """
    donnees = decode_access_token(credentials.credentials) if credentials else None
    debut_session = donnees.auth_time if donnees else 0

    if debut_session:
        age = datetime.now(timezone.utc).timestamp() - debut_session
        if age > SESSION_MAX_MINUTES * 60:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "auth.session_expired", "params": {}},
                headers={"WWW-Authenticate": "Bearer"},
            )

    access_token = create_access_token(
        data={"sub": current_user.username, "role": current_user.role,
              "token_version": current_user.token_version,
              "auth_time": debut_session or None},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    
    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user={
            "username": current_user.username,
            "email": current_user.email,
            "full_name": current_user.full_name,
            "role": current_user.role
        }
    )


@router.get("/verify")
async def verify_token(current_user: User = Depends(get_current_user)):
    """
    Vérifie si le token est valide.
    """
    return {
        "valid": True,
        "username": current_user.username,
        "role": current_user.role
    }
