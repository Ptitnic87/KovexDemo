# Fichier : src/core/security/path_validator.py
"""
Validation sécurisée des chemins de fichiers.
Protège contre les attaques de type Path Traversal.
"""

import os
import logging
from pathlib import Path
from typing import Optional, List

logger = logging.getLogger(__name__)


class PathValidationError(ValueError):
    """Chemin refusé : il sort du répertoire autorisé, ou il est inexploitable.

    Hérite de ValueError pour que les appelants qui traitent déjà un paramètre
    invalide — les routeurs répondent 404 ou 422 — n'aient rien à changer.
    """


class SecurePathValidator:
    """
    Validateur de chemins sécurisé.
    
    Empêche les attaques de type:
    - Path Traversal (../../etc/passwd)
    - Symlink attacks
    - Null byte injection
    """
    
    def __init__(
        self, 
        base_directory: str,
        allowed_extensions: Optional[List[str]] = None,
        allow_symlinks: bool = False
    ):
        """
        Initialise le validateur.
        
        Args:
            base_directory: Répertoire racine autorisé
            allowed_extensions: Extensions de fichiers autorisées (ex: ['.csv', '.json'])
            allow_symlinks: Autoriser les liens symboliques
        """
        self.base_directory = Path(base_directory).resolve()
        self.allowed_extensions = allowed_extensions or []
        self.allow_symlinks = allow_symlinks
        
        # Créer le répertoire de base s'il n'existe pas
        self.base_directory.mkdir(parents=True, exist_ok=True)
    
    def validate(self, user_path: str) -> Path:
        """
        Valide et résout un chemin utilisateur.
        
        Args:
            user_path: Chemin fourni par l'utilisateur
            
        Returns:
            Path: Chemin résolu et validé
            
        Raises:
            PathValidationError: Si le chemin est invalide ou dangereux
        """
        if not user_path:
            raise PathValidationError("Chemin vide")
        
        # 1. Nettoyer le chemin
        cleaned_path = self._clean_path(user_path)
        
        # 2. Construire le chemin complet
        if os.path.isabs(cleaned_path):
            # Chemin absolu - vérifier qu'il est dans le répertoire de base
            full_path = Path(cleaned_path)
        else:
            # Chemin relatif - le joindre au répertoire de base
            full_path = self.base_directory / cleaned_path
        
        # 3. Résoudre le chemin (élimine .., ., etc.)
        try:
            resolved_path = full_path.resolve()
        except (OSError, ValueError) as e:
            raise PathValidationError(f"Chemin invalide: {e}")
        
        # 4. Vérifier que le chemin est dans le répertoire de base
        try:
            resolved_path.relative_to(self.base_directory)
        except ValueError:
            logger.warning(f"Tentative d'accès hors répertoire: {user_path} -> {resolved_path}")
            raise PathValidationError(
                f"Accès refusé: le chemin sort du répertoire autorisé"
            )
        
        # 5. Vérifier les liens symboliques, si non autorisés.
        #
        # Le contrôle porte sur le chemin **avant** résolution : `resolve()`
        # déréférence les liens, si bien qu'un test sur le chemin résolu ne
        # renvoie jamais vrai — il ne servait à rien. Chaque composant est
        # examiné jusqu'au répertoire de base, un lien placé sur un répertoire
        # intermédiaire déplaçant tout ce qu'il contient.
        if not self.allow_symlinks:
            composant = full_path
            while True:
                if composant.is_symlink():
                    logger.warning("Lien symbolique refusé : %s", composant)
                    raise PathValidationError(
                        "Les liens symboliques ne sont pas autorisés"
                    )
                if composant == self.base_directory or composant == composant.parent:
                    break
                composant = composant.parent
        
        # 6. Vérifier l'extension si des restrictions sont définies
        if self.allowed_extensions:
            if resolved_path.suffix.lower() not in [ext.lower() for ext in self.allowed_extensions]:
                raise PathValidationError(
                    f"Extension non autorisée. Extensions permises: {self.allowed_extensions}"
                )
        
        return resolved_path
    
    def validate_existing(self, user_path: str) -> Path:
        """
        Valide un chemin et vérifie que le fichier existe.
        """
        validated_path = self.validate(user_path)
        
        if not validated_path.exists():
            raise PathValidationError(f"Fichier non trouvé: {validated_path.name}")
        
        return validated_path
    
    def validate_for_write(self, user_path: str) -> Path:
        """
        Valide un chemin pour l'écriture (vérifie que le parent existe).
        """
        validated_path = self.validate(user_path)
        
        # Vérifier que le répertoire parent existe
        parent = validated_path.parent
        if not parent.exists():
            raise PathValidationError(f"Répertoire parent inexistant: {parent}")
        
        return validated_path
    
    def _clean_path(self, path: str) -> str:
        """
        Nettoie un chemin des caractères dangereux.
        """
        # Supprimer les null bytes (attaque injection)
        cleaned = path.replace('\x00', '')
        
        # Supprimer les espaces en début/fin
        cleaned = cleaned.strip()
        
        # Normaliser les séparateurs
        cleaned = cleaned.replace('\\', '/')
        
        # Supprimer les doubles slashes
        while '//' in cleaned:
            cleaned = cleaned.replace('//', '/')
        
        return cleaned
    
# Ce module n'expose plus d'instances pré-configurées ni de raccourcis.
#
# Trois validateurs (`data`, `config`, `exports`) étaient créés à l'import, et
# le constructeur crée son répertoire de base : importer ce module fabriquait
# donc trois dossiers dans le répertoire courant, où que l'application soit
# lancée. Aucun n'était utilisé. Les raccourcis `safe_join`, `is_safe`,
# `get_safe_path`, `validate_csv_path` et `validate_config_path` ne l'étaient
# pas davantage : du code non exercé dans un module de sécurité est du code
# dont personne ne sait s'il fonctionne.
