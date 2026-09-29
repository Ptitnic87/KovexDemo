# Fichier : src/core/security/auth.py
"""
Module d'authentification JWT pour PyGIA.
Fournit l'authentification basique avec tokens JWT.
"""

import base64
import binascii
import hmac
import os
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple
from dataclasses import dataclass
import hashlib
import json
import logging

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from src.infrastructure.branding import NOM_PRODUIT

# PyJWT signe et vérifie les jetons. Son absence était rattrapée par un
# `jwt = None` et un message critique : l'application démarrait, servait ses
# écrans, et chaque connexion échouait sur une erreur interne. Un produit dont
# l'authentification est inopérante ne doit pas démarrer — c'est le même
# raisonnement que pour les routeurs.
import jwt

logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

# Clé de signature JWT. Obligatoire en production : une clé générée à chaque
# démarrage invaliderait tous les jetons émis et masquerait une mauvaise configuration.
SECRET_KEY = os.environ.get("PYGIA_SECRET_KEY", "").strip()
if not SECRET_KEY:
    if os.environ.get("PYGIA_ENV", "development").lower() == "production":
        raise RuntimeError(
            "PYGIA_SECRET_KEY est obligatoire lorsque PYGIA_ENV=production. "
            "Générer une valeur avec : python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    SECRET_KEY = secrets.token_hex(32)
    logger.warning(
        "PYGIA_SECRET_KEY absente : clé éphémère générée. "
        "Les jetons seront invalidés à chaque redémarrage (développement uniquement)."
    )
ALGORITHM = "HS256"

# Hachage des mots de passe : PBKDF2-HMAC-SHA256, sel aléatoire par compte.
PBKDF2_PREFIX = "pbkdf2_sha256"
#: Coût du hachage des mots de passe. La valeur de production suit la
#: recommandation OWASP pour PBKDF2-HMAC-SHA256.
#:
#: Elle est réglable pour une seule raison : la suite de tests monte des
#: comptes des centaines de fois, à une seconde par hachage. Une suite qui
#: dure six minutes est une suite qu'on cesse de lancer — et des tests qu'on
#: ne lance plus ne protègent de rien. Un test dédié vérifie que la valeur par
#: défaut, celle d'une installation réelle, n'a pas été abaissée.
PBKDF2_ITERATIONS = int(os.environ.get("KOVEX_PBKDF2_ITERATIONS", 480_000))

#: Valeur de production, indépendante de l'environnement : sert de référence
#: au test qui vérifie qu'on ne l'a pas abaissée par inadvertance.
PBKDF2_ITERATIONS_PRODUCTION = 480_000
SALT_BYTES = 16

# Ancien schéma, uniquement reconnu en lecture le temps de migrer les comptes
# existants. Ce sel était écrit en dur dans le code et identique pour tous.
LEGACY_SALT = "pygia_salt_2024"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8 heures

#: Durée maximale d'une session, renouvellements compris. Au-delà, il faut se
#: reconnecter. Sans ce plafond, /auth/refresh prolonge indéfiniment un jeton
#: volé : chaque appel repousse l'échéance, et rien n'y met jamais fin.
SESSION_MAX_MINUTES = int(os.environ.get("KOVEX_SESSION_MAX_MINUTES", 8 * 60))

# Fichier des utilisateurs (en production: base de données)
USERS_FILE = "config/users.json"


# ============================================================================
# MODÈLES
# ============================================================================

@dataclass
class User:
    """Représentation d'un utilisateur."""
    username: str
    email: str
    full_name: str
    role: str  # "admin", "analyst", "viewer"
    disabled: bool = False
    #: Version des jetons du compte. Elle est inscrite dans chaque jeton émis ;
    #: l'incrémenter invalide instantanément tous les jetons déjà distribués à
    #: ce compte, sans toucher aux autres comptes et sans rien à purger.
    #:
    #: Une liste de révocation en mémoire aurait été plus simple et fausse :
    #: perdue au redémarrage, elle rendait valide un jeton révoqué dès que le
    #: serveur repartait.
    token_version: int = 1
    
    def has_permission(self, permission: str) -> bool:
        """Vérifie si l'utilisateur a une permission donnée."""
        permissions_map = {
            "admin": ["read", "write", "delete", "admin", "mining", "roles"],
            "analyst": ["read", "write", "mining", "roles"],
            "viewer": ["read"]
        }
        return permission in permissions_map.get(self.role, [])


@dataclass 
class TokenData:
    """Données extraites d'un token JWT."""
    username: str
    role: str
    exp: datetime
    #: Version des jetons du compte au moment de l'émission.
    token_version: int = 1
    #: Instant de la connexion initiale, en secondes. Il ne bouge pas d'un
    #: renouvellement à l'autre : c'est lui qui borne la durée d'une session.
    auth_time: int = 0


# ============================================================================
# GESTION DES UTILISATEURS
# ============================================================================

class HachageIndisponible(RuntimeError):
    """La plateforme ne sait pas calculer l'empreinte demandée.

    `hashlib.pbkdf2_hmac` vient d'OpenSSL. Un interpréteur construit sans lui —
    c'est le cas dans un navigateur — ne l'expose pas. Le produit ne baisse
    alors **ni le nombre d'itérations ni le schéma** : il refuse, et le dit. Un
    hachage dégradé en silence serait pire que pas de hachage du tout, parce
    que personne ne saurait que les empreintes ne valent plus rien.
    """


def hachage_disponible() -> bool:
    """Le calcul d'empreinte est-il possible sur cette plateforme ?"""
    return hasattr(hashlib, "pbkdf2_hmac")


class UserManager:
    """Gestionnaire des utilisateurs (fichier JSON pour démo)."""
    
    def __init__(self, users_file: str = USERS_FILE):
        self.users_file = users_file
        self._users_cache: Optional[Dict] = None
        self._ensure_default_users()
    
    def _ensure_default_users(self):
        """Amorce le fichier utilisateurs s'il n'existe pas.

        Aucun mot de passe n'est écrit en dur : les comptes de démonstration
        `admin` / `analyst` / `viewer` et leurs mots de passe `admin123`…
        étaient présents dans le code source et leurs empreintes dans le
        dépôt, ce qui rendait tous les comptes calculables hors ligne.

        - En production, rien n'est créé automatiquement. L'administrateur
          fournit le premier mot de passe par la variable d'environnement
          PYGIA_BOOTSTRAP_ADMIN_PASSWORD. Sans elle, aucun compte n'existe et
          l'authentification échoue pour tout le monde : l'installation reste
          fermée plutôt que d'être ouverte par un identifiant connu de tous.
        - En développement, un compte administrateur unique est créé avec un
          mot de passe aléatoire, journalisé une seule fois.
        """
        if os.path.exists(self.users_file):
            return

        # Là où l'authentification est désactivée, il n'y a personne à
        # authentifier : amorcer un compte n'ouvre rien et ne protège rien. Le
        # faire quand même obligeait à hacher un mot de passe **à l'import du
        # module**, et donc à disposer de PBKDF2 sur la plateforme — ce qu'un
        # navigateur n'a pas. L'application entière échouait à s'importer.
        #
        # La combinaison est refusée au démarrage quand PYGIA_ENV=production
        # (cf. src/api/main.py) : ce raccourci ne peut pas laisser une
        # instance servie sans compte.
        production = os.environ.get("PYGIA_ENV", "development").lower() == "production"
        bootstrap_password = os.environ.get("PYGIA_BOOTSTRAP_ADMIN_PASSWORD", "").strip()

        if (os.environ.get("PYGIA_AUTH_DISABLED", "false").lower() == "true"
                and not bootstrap_password):
            logger.info(
                "Authentification désactivée et aucun mot de passe d'amorçage "
                "demandé : aucun compte n'est amorcé dans %s.",
                self.users_file,
            )
            return

        if production and not bootstrap_password:
            logger.error(
                "Aucun fichier utilisateurs (%s) et PYGIA_BOOTSTRAP_ADMIN_PASSWORD "
                "non renseignée : aucun compte ne peut se connecter. Définir cette "
                "variable puis redémarrer pour créer le compte administrateur initial.",
                self.users_file,
            )
            return

        if not bootstrap_password:
            bootstrap_password = secrets.token_urlsafe(18)
            logger.warning(
                "Compte administrateur initial créé avec un mot de passe aléatoire : %s "
                "(affiché une seule fois, à changer immédiatement).",
                bootstrap_password,
            )

        parent = os.path.dirname(self.users_file)
        if parent:
            os.makedirs(parent, exist_ok=True)

        users = {
            "admin": {
                "username": "admin",
                "email": "admin@pygia.local",
                "full_name": f"Administrateur {NOM_PRODUIT}",
                "role": "admin",
                "password_hash": self._hash_password(bootstrap_password),
                "disabled": False,
            }
        }
        with open(self.users_file, 'w', encoding='utf-8') as handle:
            json.dump(users, handle, indent=4)
        logger.warning("Fichier utilisateurs créé : %s", self.users_file)
    
    def _load_users(self) -> Dict:
        """Charge les utilisateurs depuis le fichier."""
        if self._users_cache is None:
            try:
                with open(self.users_file, 'r', encoding='utf-8') as f:
                    self._users_cache = json.load(f)
            except Exception as e:
                logger.error(f"Erreur chargement utilisateurs: {e}")
                self._users_cache = {}
        return self._users_cache
    
    def _save_users(self):
        """Sauvegarde les utilisateurs dans le fichier."""
        if self._users_cache is not None:
            with open(self.users_file, 'w', encoding='utf-8') as f:
                json.dump(self._users_cache, f, indent=4)
    
    @staticmethod
    def _hash_password(password: str) -> str:
        """Calcule l'empreinte d'un mot de passe.

        PBKDF2-HMAC-SHA256, sel aléatoire par utilisateur, au format
        ``pbkdf2_sha256$<itérations>$<sel>$<empreinte>``.

        L'ancien schéma — un SHA-256 simple avec le sel global
        ``pygia_salt_2024`` écrit dans le code — permettait de retrouver
        n'importe quel mot de passe hors ligne à partir du dépôt : un seul
        passage de hachage, et un sel identique pour tous les comptes rendant
        les tables précalculées réutilisables. PBKDF2 avec un sel par compte
        supprime les deux faiblesses, sans dépendance supplémentaire.
        """
        if not hachage_disponible():
            raise HachageIndisponible(
                "cette plateforme n'expose pas hashlib.pbkdf2_hmac (OpenSSL "
                "absent) : aucune empreinte de mot de passe ne peut être "
                "calculée ici, et le schéma ne sera pas dégradé pour autant"
            )
        salt = secrets.token_bytes(SALT_BYTES)
        digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, PBKDF2_ITERATIONS)
        return "{}${}${}${}".format(
            PBKDF2_PREFIX,
            PBKDF2_ITERATIONS,
            base64.b64encode(salt).decode('ascii'),
            base64.b64encode(digest).decode('ascii'),
        )

    @staticmethod
    def _hash_password_legacy(password: str) -> str:
        """Ancien schéma, conservé pour reconnaître les empreintes existantes.

        Uniquement utilisé en lecture : une connexion réussie sur une empreinte
        de ce type déclenche immédiatement son remplacement.
        """
        return hashlib.sha256(f"{LEGACY_SALT}{password}".encode()).hexdigest()

    @classmethod
    def _matches(cls, password: str, stored_hash: str) -> Tuple[bool, bool]:
        """Compare un mot de passe à une empreinte stockée.

        Returns:
            (correspond, empreinte_obsolète)
        """
        if not stored_hash:
            return False, False

        if stored_hash.startswith(PBKDF2_PREFIX + "$"):
            if not hachage_disponible():
                # Une vérification qui jette laisserait une trace serveur à la
                # place d'un refus. Une connexion impossible est un refus.
                logger.error(
                    "Empreinte PBKDF2 présentée sur une plateforme sans "
                    "hashlib.pbkdf2_hmac : connexion refusée."
                )
                return False, False
            try:
                _, iterations, salt_b64, digest_b64 = stored_hash.split("$", 3)
                salt = base64.b64decode(salt_b64)
                expected = base64.b64decode(digest_b64)
                candidate = hashlib.pbkdf2_hmac(
                    'sha256', password.encode('utf-8'), salt, int(iterations)
                )
            except (ValueError, TypeError, binascii.Error):
                logger.error("Empreinte de mot de passe illisible, connexion refusée.")
                return False, False
            # Comparaison à temps constant : une comparaison ordinaire fuit,
            # par sa durée, le nombre d'octets corrects en tête.
            return hmac.compare_digest(candidate, expected), int(iterations) != PBKDF2_ITERATIONS

        # Empreinte de l'ancien schéma : acceptée une dernière fois, puis remplacée.
        return hmac.compare_digest(cls._hash_password_legacy(password), stored_hash), True

    def verify_password(self, username: str, password: str) -> bool:
        """Vérifie un mot de passe, et modernise l'empreinte si besoin.

        Un utilisateur inconnu déclenche tout de même un calcul PBKDF2 complet :
        sans cela, la durée de la réponse permettrait d'énumérer les comptes
        existants.
        """
        users = self._load_users()
        user_data = users.get(username)

        if not user_data:
            self._hash_password(password)
            return False

        stored = user_data.get("password_hash", "")
        correspond, obsolete = self._matches(password, stored)
        if not correspond:
            return False

        if obsolete:
            # Re-hachage transparent : l'utilisateur n'a rien à faire, et
            # l'empreinte issue de l'ancien schéma disparaît du fichier.
            user_data["password_hash"] = self._hash_password(password)
            self._save_users()
            logger.warning(
                "Empreinte du compte '%s' migrée vers PBKDF2. L'ancienne empreinte "
                "ayant pu être exposée, ce mot de passe doit être changé.",
                username,
            )

        return True

    def set_password(self, username: str, password: str) -> bool:
        """Remplace le mot de passe d'un compte existant.

        Le changement révoque les jetons en circulation. C'est le point
        essentiel : sans cela, un mot de passe changé parce qu'on le croit
        compromis laissait vivre le jeton déjà volé jusqu'à son expiration —
        et son détenteur pouvait le renouveler sans fin.
        """
        users = self._load_users()
        if username not in users:
            return False
        users[username]["password_hash"] = self._hash_password(password)
        users[username]["token_version"] = int(
            users[username].get("token_version", 1)) + 1
        self._save_users()
        logger.info(
            "Mot de passe du compte '%s' modifié ; jetons en circulation révoqués.",
            username,
        )
        return True

    def revoquer_jetons(self, username: str) -> bool:
        """Invalide immédiatement tous les jetons d'un compte.

        Un simple entier incrémenté dans le fichier des comptes : rien à
        purger, et l'effet survit à un redémarrage — contrairement à une liste
        de révocation tenue en mémoire.
        """
        users = self._load_users()
        if username not in users:
            return False
        users[username]["token_version"] = int(
            users[username].get("token_version", 1)) + 1
        self._save_users()
        logger.warning("Jetons du compte '%s' révoqués.", username)
        return True
    
    def get_user(self, username: str) -> Optional[User]:
        """Récupère un utilisateur par son nom."""
        users = self._load_users()
        user_data = users.get(username)
        if not user_data:
            return None
        return User(
            username=user_data["username"],
            email=user_data["email"],
            full_name=user_data["full_name"],
            role=user_data["role"],
            disabled=user_data.get("disabled", False),
            token_version=int(user_data.get("token_version", 1)),
        )
    
    def authenticate(self, username: str, password: str) -> Optional[User]:
        """Authentifie un utilisateur et retourne ses infos."""
        if not self.verify_password(username, password):
            return None
        user = self.get_user(username)
        if user and user.disabled:
            return None
        return user
    
    def invalidate_cache(self):
        """Invalide le cache pour recharger les utilisateurs."""
        self._users_cache = None


# Instance globale du gestionnaire
user_manager = UserManager()


# ============================================================================
# TOKENS JWT
# ============================================================================

def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Crée un token JWT."""
    to_encode = data.copy()
    maintenant = datetime.utcnow()
    expire = maintenant + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    # `auth_time` marque le début de la session, pas celui du dernier
    # renouvellement : sans lui, une chaîne de renouvellements prolonge un
    # jeton volé indéfiniment, chaque renouvellement repoussant l'échéance.
    to_encode.setdefault("auth_time", int(maintenant.timestamp()))

    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Optional[TokenData]:
    """Décode et valide un token JWT."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        role: str = payload.get("role", "viewer")
        exp = datetime.fromtimestamp(payload.get("exp", 0))

        if username is None:
            return None

        return TokenData(
            username=username, role=role, exp=exp,
            # Un jeton émis avant l'introduction de la version vaut la
            # version 1 : les sessions en cours ne sont pas cassées par la
            # mise à jour, elles le seront à leur expiration naturelle.
            token_version=int(payload.get("token_version", 1)),
            auth_time=int(payload.get("auth_time", 0)),
        )
    
    except jwt.ExpiredSignatureError:
        logger.warning("Token expiré")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Token invalide: {e}")
        return None


# ============================================================================
# DÉPENDANCES FASTAPI
# ============================================================================

# Schéma de sécurité Bearer
security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> User:
    """
    Dépendance FastAPI pour obtenir l'utilisateur courant.
    Utilisez cette dépendance dans vos routes protégées.
    """
    # Un seul refus pour toutes les causes — jeton absent, expiré, mal signé,
    # compte inconnu, version révoquée : distinguer les cas renseignerait un
    # attaquant sur ce qu'il a presque réussi.
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "auth.invalid_or_expired"},
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Le drapeau vaut **partout**, ou il ne vaut rien.
    #
    # `require_permission_or_dev` accordait déjà l'utilisateur anonyme sur
    # toutes les routes métier, mais cette dépendance-ci l'ignorait : un client
    # qui vérifie son jeton avant de continuer — ce que fait l'interface au
    # démarrage — se faisait donc déconnecter alors que le reste de l'API lui
    # répondait. Un drapeau qui vaut partout sauf à un endroit est un drapeau
    # dont on ne peut rien déduire.
    #
    # Il est relu à chaque requête, et non figé à l'import, pour la même raison
    # qu'ailleurs : rester testable, et suivre un changement de configuration
    # sans recharger le module. La combinaison est refusée au démarrage quand
    # `PYGIA_ENV=production` (cf. `src/api/main.py`) : elle ne peut donc pas
    # ouvrir une instance servie.
    if os.environ.get("PYGIA_AUTH_DISABLED", "false").lower() == "true":
        return User(
            username="anonymous",
            email="anonymous@dev.local",
            full_name="Utilisateur Anonyme (Dev)",
            role="admin",
            disabled=False,
        )

    if credentials is None:
        raise credentials_exception
    
    token_data = decode_access_token(credentials.credentials)
    if token_data is None:
        raise credentials_exception

    user = user_manager.get_user(token_data.username)
    if user is None or user.disabled:
        raise credentials_exception

    # Un jeton émis avant la dernière révocation du compte n'est plus valable,
    # même s'il n'a pas expiré. C'est ce qui rend un changement de mot de passe
    # réellement protecteur.
    if token_data.token_version != user.token_version:
        logger.warning(
            "Jeton révoqué présenté pour le compte '%s' (version %s, attendue %s).",
            user.username, token_data.token_version, user.token_version,
        )
        raise credentials_exception

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """Vérifie que l'utilisateur n'est pas désactivé."""
    if current_user.disabled:
        # Écrit en français dans le cœur : le contrôle des textes en dur ne
        # regardait que `src/api/`, et ce refus-là lui échappait.
        raise HTTPException(status_code=400,
                            detail={"code": "auth.account_disabled"})
    return current_user


# ============================================================================
# MODE DÉVELOPPEMENT
# ============================================================================

# Conservé pour compatibilité de lecture. Ne pas s'en servir pour décider d'un
# accès : la valeur est figée à l'import, alors que require_permission_or_dev
# relit la variable à chaque requête.
AUTH_DISABLED = os.environ.get("PYGIA_AUTH_DISABLED", "false").lower() == "true"


def require_permission_or_dev(permission: str):
    """
    Dépendance FastAPI exigeant une permission sur une route métier.

    Comportement :
    - PYGIA_AUTH_DISABLED=true  -> utilisateur anonyme de développement.
      Cette combinaison est refusée au démarrage quand PYGIA_ENV=production
      (cf. src/api/main.py), elle ne peut donc pas ouvrir une instance servie.
    - sinon -> jeton Bearer valide ET permission requise, 401/403 dans le cas
      contraire.

    Le drapeau est relu à chaque requête (et non figé à l'import) pour rester
    testable et pour qu'un changement de configuration ne demande pas un
    rechargement de module.
    """

    async def permission_checker(
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
    ) -> User:
        if os.environ.get("PYGIA_AUTH_DISABLED", "false").lower() == "true":
            return User(
                username="anonymous",
                email="anonymous@dev.local",
                full_name="Utilisateur Anonyme (Dev)",
                role="admin",
                disabled=False,
            )

        current_user = await get_current_user(credentials)
        if not current_user.has_permission(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "error.permission_required", "params": {"permission": permission}},
            )
        return current_user

    return permission_checker
