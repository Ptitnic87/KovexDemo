"""
API Router pour l'internationalisation (i18n)
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any
from src.infrastructure.i18n_manager import i18n

router = APIRouter(prefix="/i18n", tags=["Internationalization"])


@router.get("/locales")
async def get_available_locales():
    """
    Liste les langues disponibles.
    
    Returns:
        {
            "locales": [
                {"code": "fr", "name": "Français", "native_name": "Français"},
                {"code": "en", "name": "English", "native_name": "English"}
            ],
            "current": "fr"
        }
    """
    return {
        "locales": i18n.get_available_locales(),
        # Plus de « langue active » du serveur : la langue est une préférence
        # du client, transmise à chaque requête. On rend la langue de repli,
        # celle utilisée quand une clé manque dans la langue demandée.
        "fallback": i18n.langue_de_reference
    }


@router.get("/translations/{locale}")
async def get_translations(locale: str):
    """
    Retourne toutes les traductions pour une langue.
    
    Args:
        locale: Code de langue (ex: 'fr', 'en')
    
    Returns:
        Dictionnaire complet des traductions
    
    Raises:
        404: Si la locale n'existe pas
    """
    if locale not in i18n.translations:
        # Le détail énumérait les langues installées : un message non
        # traduit, et un inventaire du serveur rendu à un appelant qui a juste
        # demandé une langue inconnue.
        raise HTTPException(
            status_code=404,
            detail={"code": "i18n.locale_not_found", "params": {"langue": locale}})
    
    return i18n.get_locale_data(locale)


@router.post("/reload")
async def reload_translations():
    """
    Recharge toutes les traductions depuis le disque.
    Utile après modification des fichiers de traduction.
    
    Returns:
        {"status": "reloaded", "locales": ["fr", "en", ...]}
    """
    i18n.reload_locales()
    return {
        "status": "reloaded",
        "locales": list(i18n.translations.keys())
    }


@router.get("/translate")
async def translate_key(key: str, locale: str = None):
    """
    Traduit une clé spécifique.
    
    Args:
        key: Clé de traduction (ex: 'common.save')
        locale: Langue optionnelle (défaut: langue active)
    
    Returns:
        {"key": "common.save", "translation": "Sauvegarder", "locale": "fr"}
    
    Example:
        GET /api/v1/i18n/translate?key=common.save&locale=en
        → {"key": "common.save", "translation": "Save", "locale": "en"}
    """
    translation = i18n.t(key, locale=locale)
    used_locale = locale or i18n.langue_de_reference
    
    return {
        "key": key,
        "translation": translation,
        "locale": used_locale
    }
