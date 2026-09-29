# src/core/security/rate_limiter.py
"""
Rate Limiter simple pour PyGIA.
Fonctionne en mémoire - pas de dépendance externe (Redis, etc.)
Adapté pour un usage local/mono-instance.
"""

import os
import time
from typing import Dict, Tuple, Optional
from fastapi import Request
import logging

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Limiteur de requêtes en mémoire utilisant l'algorithme Token Bucket.
    
    Avantages:
    - Pas de dépendance externe
    - Léger et rapide
    - Adapté pour usage local
    
    Limitations:
    - Se réinitialise au redémarrage du serveur
    - Ne fonctionne pas en multi-instance
    """
    
    def __init__(self):
        # {clé de seau: {"tokens": float, "last_update": float}}
        # Un seau est créé **plein** : un client qui arrive doit pouvoir faire
        # sa première requête. Créé vide, il était refusé d'entrée.
        self._buckets: Dict[str, Dict[str, float]] = {}

        # Débits par famille d'endpoint, réglables par variable
        # d'environnement : un poste d'analyste et un serveur mutualisé n'ont
        # pas le même profil d'usage, et un débit écrit en dur ne se corrige
        # qu'en modifiant le code.
        self._limits = {
            "default": self._debit("DEFAULT", 120, 60),
            # Seuls les points d'entrée qui vérifient un mot de passe relèvent
            # du débit strict : ce sont eux la surface d'une attaque.
            "auth": self._debit("AUTH", 5, 60),
            "mining": self._debit("MINING", 10, 60),
            # Poser une question à un modèle n'est pas lancer un calcul de
            # mining. Le nommage en lot en envoie une par rôle candidat, à la
            # file : sur un catalogue de trois cents rôles, un débit taillé
            # pour une opération lourde refuse tout après les dix premières —
            # c'est ce qui s'est produit sur un poste réel, six cents refus
            # d'affilée, et le produit annonçait « sans réponse du modèle »
            # alors que c'était lui qui refusait.
            #
            # Le vrai régulateur de ce flux est le modèle lui-même : il répond
            # à une question à la fois. Le seau n'est là que pour borner un
            # client emballé.
            "assistance": self._debit("ASSISTANCE", 60, 60),
            "export": self._debit("EXPORT", 5, 300),
            # Lecture : l'écran de cartographie interroge quatre colonnes à
            # chaque sélection. Un débit calculé pour une navigation page par
            # page bloque une interface qui rayonne.
            "api_read": self._debit("READ", 600, 60),
        }

    @staticmethod
    def _debit(nom: str, rate_defaut: int, per_defaut: int) -> Dict[str, int]:
        """Débit d'une famille, surchargeable par l'environnement."""
        return {
            "rate": int(os.environ.get(f"KOVEX_RATE_{nom}", rate_defaut)),
            "per": int(os.environ.get(f"KOVEX_RATE_{nom}_PER", per_defaut)),
        }
    
    def _get_client_id(self, request: Request) -> str:
        """
        Identifie le client par IP + User-Agent (basique mais efficace en local).
        """
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "")[:50]
        return f"{client_ip}:{hash(user_agent) % 10000}"
    
    def _get_bucket_key(self, client_id: str, limit_type: str) -> str:
        """Génère une clé unique pour le bucket."""
        return f"{client_id}:{limit_type}"
    
    def check_rate_limit(
        self, 
        request: Request, 
        limit_type: str = "default"
    ) -> Tuple[bool, Dict[str, any]]:
        """
        Vérifie si la requête est autorisée selon le rate limit.
        
        Returns:
            Tuple[bool, Dict]: (autorisé, infos_limite)
        """
        client_id = self._get_client_id(request)
        bucket_key = self._get_bucket_key(client_id, limit_type)
        
        # Récupérer la configuration de limite
        limit_config = self._limits.get(limit_type, self._limits["default"])
        max_tokens = limit_config["rate"]
        refill_period = limit_config["per"]
        refill_rate = max_tokens / refill_period  # tokens par seconde
        
        bucket = self._buckets.get(bucket_key)
        if bucket is None:
            bucket = {"tokens": float(max_tokens), "last_update": time.time()}
            self._buckets[bucket_key] = bucket
        current_time = time.time()
        
        # Calculer les tokens accumulés depuis la dernière requête
        time_passed = current_time - bucket["last_update"]
        bucket["tokens"] = min(
            max_tokens,
            bucket["tokens"] + (time_passed * refill_rate)
        )
        bucket["last_update"] = current_time
        
        # Vérifier si on peut consommer un token
        if bucket["tokens"] >= 1:
            bucket["tokens"] -= 1
            allowed = True
        else:
            allowed = False
        
        # Calculer le temps avant reset
        retry_after = int((1 - bucket["tokens"]) / refill_rate) + 1 if not allowed else 0
        
        info = {
            "limit": max_tokens,
            "remaining": int(bucket["tokens"]),
            "reset_in": retry_after,
            "limit_type": limit_type
        }
        
        if not allowed:
            logger.warning(
                f"Rate limit exceeded for {client_id} on {limit_type}",
                extra={"client": client_id, "limit_type": limit_type}
            )
        
        return allowed, info
    
    def get_headers(self, info: Dict[str, any]) -> Dict[str, str]:
        """Génère les headers HTTP standard pour le rate limiting."""
        return {
            "X-RateLimit-Limit": str(info["limit"]),
            "X-RateLimit-Remaining": str(info["remaining"]),
            "X-RateLimit-Reset": str(info["reset_in"]),
        }
    
    def cleanup_old_buckets(self, max_age: int = 3600):
        """
        Nettoie les buckets inactifs depuis plus de max_age secondes.
        À appeler périodiquement pour éviter les fuites mémoire.
        """
        current_time = time.time()
        keys_to_delete = []
        
        for key, bucket in self._buckets.items():
            if current_time - bucket["last_update"] > max_age:
                keys_to_delete.append(key)
        
        for key in keys_to_delete:
            del self._buckets[key]
        
        if keys_to_delete:
            logger.info(f"Cleaned up {len(keys_to_delete)} old rate limit buckets")


# Instance globale (singleton)
_rate_limiter = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    """Retourne l'instance globale du rate limiter."""
    return _rate_limiter


# Le décorateur `rate_limit()` qui vivait ici a été retiré : aucune route ne
# l'utilisait, le middleware s'appliquant à toutes. Deux mécanismes pour un même
# besoin, dont un jamais exercé — donc jamais vérifié.


# === Middleware FastAPI ===

class RateLimitMiddleware:
    """
    Middleware FastAPI pour appliquer le rate limiting global.
    
    Usage dans main.py:
        from src.core.security.rate_limiter import RateLimitMiddleware
        app.add_middleware(RateLimitMiddleware)
    """
    
    def __init__(self, app):
        self.app = app
        self.limiter = get_rate_limiter()
        
        # Familles d'endpoints, dans l'ordre d'examen.
        #
        # Seuls les endpoints qui **vérifient un mot de passe** relèvent du
        # débit strict : ce sont eux la surface d'une attaque par force brute.
        # Le motif « /auth/ » y rangeait aussi /auth/me, /auth/verify,
        # /auth/logout et /auth/refresh, que l'interface appelle en usage
        # normal — cinq requêtes par minute les rendaient inutilisables.
        self._url_patterns = [
            ("/auth/login", "auth"),
            ("/auth/token", "auth"),
            ("/mining", "mining"),
            ("/find-roles", "mining"),
            # Plus long que « /mining », donc gagnant : voir `_get_limit_type`.
            ("/mining/suggest-name", "assistance"),
            ("/assistance/", "assistance"),
            ("/coherence/enrichir", "assistance"),
            ("/export", "export"),
            # Le seau `api_read` était déclaré mais aucun motif ne l'atteignait :
            # toute la lecture tombait dans `default`. Une configuration qui
            # paraît réglée et ne l'est pas est pire qu'une absence de réglage.
            ("/graph/", "api_read"),
            ("/habilitations/", "api_read"),
            ("/i18n/", "api_read"),
            ("/documentation/", "api_read"),
        ]
    
    def _get_limit_type(self, path: str) -> str:
        """La famille de débit d'une route : **le motif le plus précis gagne**.

        La résolution se faisait dans l'ordre de déclaration, et ce fichier
        porte déjà la trace de deux défauts identiques : le motif « /auth/ »
        attrapait `/auth/me` et rendait l'interface inutilisable à cinq
        requêtes par minute ; le seau `api_read` était déclaré et
        inatteignable. Un troisième est arrivé : « /mining » attrapait
        `/mining/suggest-name`, et le nommage en lot mourait après dix rôles
        sous un débit taillé pour lancer un calcul.

        Le classement par longueur retire la cause commune aux trois. Un motif
        plus précis décrit une route plus précise ; l'ordre dans lequel
        quelqu'un l'a écrite ne dit rien de ce qu'elle coûte. Ajouter un motif
        ne peut plus, à lui seul, en neutraliser un autre.
        """
        path_lower = path.lower()
        gagnant = None
        for pattern, limit_type in self._url_patterns:
            if pattern in path_lower and (gagnant is None
                                          or len(pattern) > len(gagnant[0])):
                gagnant = (pattern, limit_type)
        return gagnant[1] if gagnant else "default"
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        # Créer un objet Request minimal pour le rate limiter
        from starlette.requests import Request
        request = Request(scope, receive)
        
        # Une requête préparatoire CORS n'est pas une action de l'utilisateur :
        # c'est le navigateur qui demande l'autorisation d'envoyer la vraie
        # requête. La compter double le débit observé, et la refuser fait
        # échouer la requête utile avant qu'elle parte — l'interface rapporte
        # alors une erreur CORS, qui n'aide personne à comprendre.
        if scope.get("method", "").upper() == "OPTIONS":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        limit_type = self._get_limit_type(path)
        
        allowed, info = self.limiter.check_rate_limit(request, limit_type)
        
        if not allowed:
            # Répondre avec 429 Too Many Requests
            from starlette.responses import JSONResponse
            # Le corps était une phrase anglaise écrite en dur. Le produit ne
            # rend jamais de phrase : il rend un code de traduction et ses
            # paramètres, et c'est le client qui connaît la langue de son
            # utilisateur. `retry_after` reste à côté du code, parce qu'un
            # client qui se cale sur le débit a besoin du nombre, pas du texte.
            entetes = dict(self.limiter.get_headers(info))
            # En-tête HTTP standard : un client qui respecte le protocole le
            # cherche là, et pas dans le corps.
            entetes["Retry-After"] = str(info["reset_in"])
            response = JSONResponse(
                status_code=429,
                content={
                    "detail": {
                        "code": "error.rate_limited",
                        "params": {"secondes": info["reset_in"]},
                        "retry_after": info["reset_in"],
                    }
                },
                headers=entetes
            )
            await response(scope, receive, send)
            return
        
        # Ajouter les headers de rate limit à la réponse
        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                for key, value in self.limiter.get_headers(info).items():
                    headers[key.lower().encode()] = value.encode()
                message["headers"] = list(headers.items())
            await send(message)
        
        await self.app(scope, receive, send_with_headers)
