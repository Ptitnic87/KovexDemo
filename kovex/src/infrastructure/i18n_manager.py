"""
PyGIA Internationalization Manager
Gestion centralisée des traductions multi-langues
"""

import logging
import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
from src.infrastructure.chemins import RACINE_PROJET


logger = logging.getLogger(__name__)


class I18nManager:
    """
    Gestionnaire de traductions avec support multi-langues.
    Singleton pattern pour instance unique.
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(I18nManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        # Chemin ancré sur l'emplacement du code, jamais sur le répertoire
        # courant. Un chemin relatif était résolu au moment de l'import : un
        # serveur lancé depuis un autre dossier — ou un test qui change de
        # répertoire avant le premier import — ne chargeait aucun catalogue,
        # et l'interface affichait les clés brutes sans la moindre erreur.
        self.locales_dir = (
            RACINE_PROJET / "config" / "locales"
        )
        # Langue de repli, et **uniquement** cela. Il n'existe plus de « langue
        # active » du processus : elle était mutable par n'importe quel compte
        # authentifié, y compris un simple lecteur, et changeait la langue de
        # tous les autres utilisateurs connectés au même serveur. La langue est
        # une préférence du client ; elle voyage avec la requête.
        self.langue_de_reference = "fr"
        self.translations: Dict[str, Dict[str, Any]] = {}
        
        # Créer le dossier si nécessaire
        self.locales_dir.mkdir(parents=True, exist_ok=True)
        
        # Charger toutes les traductions disponibles
        self.load_all_locales()
        
        self._initialized = True
    
    def load_all_locales(self):
        """Charge toutes les traductions disponibles depuis le dossier locales/."""
        if not self.locales_dir.exists():
            logger.warning("Dossier des catalogues introuvable : %s", self.locales_dir)
            return
        
        for locale_file in self.locales_dir.glob("*.json"):
            locale_code = locale_file.stem
            try:
                with open(locale_file, 'r', encoding='utf-8') as f:
                    self.translations[locale_code] = json.load(f)
                    logger.info("Catalogue chargé : %s", locale_code)
            except Exception as e:
                logger.error("Chargement du catalogue %s impossible : %s", locale_code, e)
    
    def t(self, key: str, locale: Optional[str] = None, **kwargs) -> str:
        """
        Traduit une clé avec paramètres optionnels.
        
        Args:
            key: Clé de traduction (ex: 'common.save')
            locale: Langue spécifique (ou None pour langue active)
            **kwargs: Paramètres de substitution (ex: count=5)
        
        Returns:
            Chaîne traduite ou clé si traduction introuvable
        
        Examples:
            >>> i18n.t('common.save')
            'Sauvegarder'
            >>> i18n.t('birth_rights.results_count', count=42)
            '42 droits socles détectés'
        """
        target_locale = locale or self.langue_de_reference
        catalogue = self.translations.get(target_locale, {})

        # Accès direct d'abord : les catalogues du produit sont **plats**, une
        # clé y est une chaîne unique ("quality.issue.orphan_users"). La version
        # précédente découpait systématiquement sur les points et descendait un
        # arbre qui n'existe pas : `catalogue.get("quality")` valait None, et la
        # fonction rendait la clé brute. Autrement dit, aucune traduction côté
        # serveur ne fonctionnait — un rapport produit en anglais affichait les
        # identifiants de clés.
        value = catalogue.get(key)

        if value is None:
            # Repli sur une éventuelle structure hiérarchique, pour un
            # catalogue fourni par un tiers dans cette forme.
            value = catalogue
            for k in key.split('.'):
                if isinstance(value, dict):
                    value = value.get(k)
                else:
                    value = None
                    break

        if value is None or isinstance(value, dict):
            # Essayer fallback si pas trouvé
            if target_locale != self.langue_de_reference:
                return self.t(key, locale=self.langue_de_reference, **kwargs)
            return key
        
        # Remplacer les placeholders {variable}
        if kwargs:
            for param, val in kwargs.items():
                value = value.replace(f"{{{param}}}", str(val))
        
        return value
    
    def get_available_locales(self) -> List[Dict[str, str]]:
        """
        Retourne la liste des langues disponibles avec métadonnées.
        
        Returns:
            Liste de dictionnaires {code, name, native_name}
        """
        locales_info = []

        for code in sorted(self.translations.keys()):
            catalogue = self.translations[code]
            meta = catalogue.get("_meta", {})
            # Les catalogues du produit sont **plats** : le nom d'une langue y
            # est une clé comme une autre. La version précédente ne lisait que
            # `_meta`, absent de tous les catalogues livrés : l'API annonçait
            # « FR », « EN », « DE », et l'interface a donc fini par écrire sa
            # propre liste de langues en dur.
            natif = (catalogue.get("locale.native_name")
                     or meta.get("native_name") or meta.get("name") or code.upper())
            nom = meta.get("name") or natif

            locales_info.append({
                "code": code,
                "name": nom,
                "native_name": natif,
            })

        return locales_info
    
    def get_locale_data(self, locale_code: Optional[str] = None) -> Dict[str, Any]:
        """
        Retourne toutes les traductions pour une langue.
        
        Args:
            locale_code: Code de langue (ou None pour langue active)
        
        Returns:
            Dictionnaire complet des traductions
        """
        target_locale = locale_code or self.langue_de_reference
        return self.translations.get(target_locale, {})
    
    def reload_locales(self):
        """Recharge toutes les traductions depuis le disque."""
        self.translations.clear()
        self.load_all_locales()


# Singleton global
i18n = I18nManager()


# Fonction helper pour templates
def t(key: str, **kwargs) -> str:
    """Shortcut pour i18n.t()"""
    return i18n.t(key, **kwargs)
