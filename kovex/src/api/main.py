# src/api/main.py
"""
Point d'entrée de l'API PyGIA.
Version corrigée - Avec le routeur GRAPH activé.
"""

import logging
import os
import time
import uuid

# Charger les variables d'environnement depuis .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv optionnel

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from src.api.security_policy import appliquer_politique
from src.api.routers import audit, documentation, birth_rights
from src.api.routers import knowledge
from src.api.routers import workspaces
from src.api.routers import reports
from src.api.routers import roles
from src.api.routers import i18n
from src.api.routers import data_quality_exports
from src.infrastructure.branding import NOM_PRODUIT, VERSION_PRODUIT


# Journal de l'application.
#
# `basicConfig` n'écrivait que sur la sortie standard. Plusieurs refus du
# produit renvoient l'exploitant vers « le journal du serveur » ; sur un
# serveur isolé, lancé par un raccourci ou un service, cette sortie n'est lue
# par personne et disparaît à l'arrêt. `setup_logging` ajoute un fichier, qui
# tourne pour ne pas remplir le disque.
from src.infrastructure.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

# === Configuration ===
PYGIA_ENV = os.getenv("PYGIA_ENV", "development")
IS_PRODUCTION = PYGIA_ENV == "production"

# Authentification. Le défaut est désormais 'activée' : une plateforme de gouvernance
# des accès ne doit pas s'ouvrir en grand parce qu'une variable d'environnement manque.
AUTH_DISABLED = os.getenv("PYGIA_AUTH_DISABLED", "false").lower() == "true"

if IS_PRODUCTION and AUTH_DISABLED:
    raise RuntimeError(
        "PYGIA_AUTH_DISABLED=true est incompatible avec PYGIA_ENV=production : "
        "les endpoints exposeraient les données d'habilitations sans authentification."
    )

# CORS - Domaines autorisés
ALLOWED_ORIGINS = os.getenv(
    "PYGIA_ALLOWED_ORIGINS", 
    "http://localhost:3000,http://127.0.0.1:3000,http://localhost:8000,http://127.0.0.1:8000"
).split(",")

# === Application FastAPI ===
# La documentation interactive expose la cartographie complète de l'API et
# n'est pas protégeable par jeton (Swagger charge le schéma sans en-tête) :
# elle est donc fermée en production.
app = FastAPI(
    title=f"{NOM_PRODUIT} API",
    description="Plateforme de Gouvernance des Identités et des Accès",
    version=VERSION_PRODUIT,
    docs_url=None if IS_PRODUCTION else "/api/docs",
    redoc_url=None if IS_PRODUCTION else "/api/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)

# === Middlewares ===

# 1. CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    # Durée de mise en cache de la requête préparatoire. Sans elle, le
    # navigateur redemande l'autorisation avant **chaque** appel portant un
    # jeton : le nombre de requêtes double, et l'écran de cartographie, qui en
    # émet quatre par sélection, en émet huit.
    max_age=int(os.environ.get("KOVEX_CORS_MAX_AGE", 600)),
    allow_headers=["*"],
    # Sans cette ligne, le navigateur cache `Content-Disposition` à
    # l'interface : elle n'est pas dans la liste des en-têtes exposés
    # d'office, et l'interface est servie sur un autre port que l'API — donc
    # une autre origine.
    #
    # Conséquence observée : tous les téléchargements retombaient sur le nom
    # de secours écrit côté client. Le serveur nommait le rapport
    # « kovex_… _20260830.pdf », le navigateur l'enregistrait sous le nom
    # générique. Le code affirmait le contraire dans ses commentaires ; c'est
    # un test navigateur qui a montré que la lecture rendait `null`.
    # `X-Duree-Ms` doit franchir l'inter-origine comme `Content-Disposition` :
    # un en-tête que le navigateur ne peut pas lire ne sert à personne.
    expose_headers=["Content-Disposition", "X-Duree-Ms"],
)

# 2. Limitation de débit. Activée par défaut : sans elle, rien ne freine une
# attaque par force brute sur /auth/login. Il faut la désactiver explicitement,
# et le journal le rappelle quand c'est le cas.
RATE_LIMIT_ENABLED = os.getenv("PYGIA_RATE_LIMIT", "true").lower() == "true"

if RATE_LIMIT_ENABLED:
    from src.core.security.rate_limiter import RateLimitMiddleware

    app.add_middleware(RateLimitMiddleware)
    logger.info("Limitation de débit activée")
else:
    logger.warning(
        "Limitation de débit DESACTIVEE (PYGIA_RATE_LIMIT=false) : "
        "rien ne freine une attaque par force brute sur /auth/login."
    )

#: Durée à partir de laquelle une requête est consignée comme lente, en
#: millisecondes. Ce n'est pas un seuil d'alerte : c'est la limite au-delà de
#: laquelle un utilisateur commence à attendre, et donc celle à partir de
#: laquelle le journal doit garder une trace de ce qui s'est passé.
#:
#: Ce contrôle manquait, et son absence a coûté cher : une base de connaissance
#: relue et réécrite entièrement à chaque clic rendait une validation de rôle
#: interminable sans que rien, ni dans les journaux ni dans les graphes système,
#: ne le signale. Une lenteur dont personne ne garde trace est une lenteur que
#: personne ne corrige.
SEUIL_LENTEUR_MS = float(os.environ.get("KOVEX_JOURNAL_LENTEUR_MS", "1000"))


# === Middleware de logging ===
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log les requêtes, et le temps qu'elles ont pris quand il se remarque."""
    if request.url.path not in ["/", "/health", "/favicon.ico"]:
        logger.debug(f"➡️ {request.method} {request.url.path}")

    depart = time.perf_counter()
    response = await call_next(request)
    duree_ms = (time.perf_counter() - depart) * 1000

    if response.status_code >= 400:
        logger.warning(f"⚠️ {request.method} {request.url.path} → {response.status_code}")

    if duree_ms >= SEUIL_LENTEUR_MS:
        logger.warning("⏱️ %s %s → %d en %.0f ms", request.method,
                       request.url.path, response.status_code, duree_ms)

    # La durée voyage avec la réponse : l'écran peut alors distinguer ce que le
    # serveur a mis de ce que le navigateur met à afficher, sans outil.
    response.headers["X-Duree-Ms"] = f"{duree_ms:.0f}"
    return response

# === Gestionnaire d'exceptions ===
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Capture les exceptions non gérées.

    Le message d'exception n'est **jamais** renvoyé au client, y compris en
    développement. Les exceptions pandas contiennent couramment des chemins
    disque, des noms de colonnes client et des extraits de données ; et le
    lanceur fourni crée un `.env` en mode développement, ce qui faisait de la
    fuite le comportement par défaut d'une installation.

    Un identifiant de corrélation est renvoyé et journalisé : il permet de
    retrouver la trace complète dans le journal du serveur sans rien exposer.
    """
    correlation = uuid.uuid4().hex[:12]
    logger.error(
        "Exception non gérée [%s] sur %s %s : %s",
        correlation, request.method, request.url.path, exc, exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": {"code": "error.internal", "params": {"reference": correlation}}},
    )

# === Routes de base ===
@app.get("/", tags=["Système"])
async def root():
    return {
        "app": NOM_PRODUIT,
        "version": VERSION_PRODUIT,
        "status": "running",
        "auth_enabled": not AUTH_DISABLED
    }

@app.get("/health", tags=["Système"])
async def health_check():
    return {"status": "healthy", "environment": PYGIA_ENV}

# === Import des routeurs ===

# Routeurs de base (toujours présents)
from src.api.routers import (apprentissage, assistance, coherence, controles, derogations, identites, usage, users, stats,
                             points_de_terminaison,
                             explorer, mouvement, nommage, privileges,
                             reports, separation, settings)

app.include_router(birth_rights.router, prefix="/api/v1", tags=["0. Droits socles"], dependencies=[Depends(appliquer_politique)])
app.include_router(users.router, prefix="/api/v1", tags=["Données"], dependencies=[Depends(appliquer_politique)])
app.include_router(stats.router, prefix="/api/v1", tags=["Données"], dependencies=[Depends(appliquer_politique)])
app.include_router(explorer.router, prefix="/api/v1", tags=["Explorateur"], dependencies=[Depends(appliquer_politique)])
app.include_router(reports.router, prefix="/api/v1", tags=["Rapports"], dependencies=[Depends(appliquer_politique)])
app.include_router(settings.router, prefix="/api/v1", tags=["Configuration"], dependencies=[Depends(appliquer_politique)])
app.include_router(assistance.router, prefix="/api/v1", tags=["Configuration"], dependencies=[Depends(appliquer_politique)])
app.include_router(points_de_terminaison.router, prefix="/api/v1", tags=["Configuration"], dependencies=[Depends(appliquer_politique)])
app.include_router(privileges.router, prefix="/api/v1", tags=["Configuration"], dependencies=[Depends(appliquer_politique)])
app.include_router(separation.router, prefix="/api/v1", tags=["Séparation des tâches"], dependencies=[Depends(appliquer_politique)])
app.include_router(derogations.router, prefix="/api/v1", tags=["Dérogations"], dependencies=[Depends(appliquer_politique)])
app.include_router(controles.router, prefix="/api/v1", tags=["Contrôles compensatoires"], dependencies=[Depends(appliquer_politique)])
app.include_router(usage.router, prefix="/api/v1", tags=["Usage"], dependencies=[Depends(appliquer_politique)])
app.include_router(apprentissage.router, prefix="/api/v1", tags=["Apprentissage"], dependencies=[Depends(appliquer_politique)])
app.include_router(identites.router, prefix="/api/v1", tags=["Identités"], dependencies=[Depends(appliquer_politique)])
app.include_router(mouvement.router, prefix="/api/v1", tags=["Mouvement"], dependencies=[Depends(appliquer_politique)])
app.include_router(nommage.router, prefix="/api/v1", tags=["Nommage des droits"], dependencies=[Depends(appliquer_politique)])
app.include_router(coherence.router, prefix="/api/v1", tags=["Qualité"], dependencies=[Depends(appliquer_politique)])
app.include_router(knowledge.router, prefix="/api/v1", tags=["KB"], dependencies=[Depends(appliquer_politique)])
app.include_router(workspaces.router, prefix="/api/v1", tags=["Workspaces"], dependencies=[Depends(appliquer_politique)])
app.include_router(i18n.router, prefix="/api/v1", tags=["Internationalization"], dependencies=[Depends(appliquer_politique)])
app.include_router(roles.router, prefix="/api/v1", dependencies=[Depends(appliquer_politique)])
app.include_router(data_quality_exports.router, prefix="/api/v1", dependencies=[Depends(appliquer_politique)])
app.include_router(audit.router, prefix="/api/v1", dependencies=[Depends(appliquer_politique)])
app.include_router(documentation.router, prefix="/api/v1", dependencies=[Depends(appliquer_politique)])

# Sprint 2 : Habilitations (drill-down)
from src.api.routers import habilitations
app.include_router(habilitations.router, prefix="/api/v1", tags=["Habilitations"], dependencies=[Depends(appliquer_politique)])
logger.info("✅ Routeur habilitations chargé")

# --- ROUTEUR GRAPH (Import strict pour debug) ---
from src.api.routers import graph
app.include_router(graph.router, prefix="/api/v1", tags=["Graph"], dependencies=[Depends(appliquer_politique)])

from src.api.routers import export_modele
app.include_router(export_modele.router, prefix="/api/v1", tags=["Export du modèle"], dependencies=[Depends(appliquer_politique)])

from src.api.routers import agent
app.include_router(agent.router, prefix="/api/v1", tags=["Agent de navigation"], dependencies=[Depends(appliquer_politique)])
logger.info("✅ Routeur graph chargé")
# ------------------------------------------------

# Routeurs Mining
# Routeurs de mining et métier.
#
# Chacun était enveloppé dans un `try / except ImportError` qui se contentait
# d'un avertissement. Une dépendance manquante ou une faute de frappe faisait
# donc **démarrer l'application sans son moteur de mining** : l'interface
# recevait des 404 sur des écrans entiers, et rien à l'écran ne disait
# pourquoi. Sur un produit dont le mining est l'objet, démarrer amputé est pire
# que refuser de démarrer.
from src.api.routers import business, mining, mining_metiers

app.include_router(mining.router, prefix="/api/v1", tags=["Mining"],
                   dependencies=[Depends(appliquer_politique)])
app.include_router(mining_metiers.router, prefix="/api/v1", tags=["Mining Métier"],
                   dependencies=[Depends(appliquer_politique)])
app.include_router(business.router, prefix="/api/v1", tags=["Métier"],
                   dependencies=[Depends(appliquer_politique)])

# Le routeur "ai_assistant" a été retiré et ses fichiers supprimés. Son
# endpoint POST /analyze-role renvoyait une phrase tirée au hasard parmi quatre
# et un score de risque tiré au sort entre 1 et 10, présentés comme une analyse.
# Sur un objet de gouvernance des accès, un score de risque inventé est pire
# qu'absent : rien n'empêche qu'il soit repris tel quel dans une campagne de
# recertification.

# Routeur d'authentification. Même raison : démarrer sans lui ouvrirait une
# API dont plus personne ne peut obtenir de jeton.
from src.api.routers import auth

app.include_router(auth.router, prefix="/api/v1", tags=["Authentification"],
                   dependencies=[Depends(appliquer_politique)])

# === Événement de démarrage ===
@app.on_event("startup")
async def startup_event():
    logger.info(f"{NOM_PRODUIT} démarre en mode {PYGIA_ENV}")
    logger.info(f"🔐 Authentification: {'DÉSACTIVÉE' if AUTH_DISABLED else 'ACTIVÉE'}")
    logger.info(f"🌐 CORS autorisé pour: {ALLOWED_ORIGINS}")
    
    # Pré-charger les données
    try:
        from src.api.dependencies import get_data_loader
        loader = get_data_loader()
        logger.info(f"📊 Données chargées: {len(loader.identities)} utilisateurs")
    except Exception as e:
        logger.error(f"⚠️ Erreur chargement données: {e}")

# === Point d'entrée ===
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.api.main:app",
        host="127.0.0.1",
        port=8000,
        reload=not IS_PRODUCTION
    )

    