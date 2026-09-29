# Fichier : src/infrastructure/logging_config.py
"""Journal technique du serveur.

Ce module existait, complet, et **n'était importé par personne** : 284 lignes
de code mort. L'application configurait son journal avec `logging.basicConfig`,
qui n'écrit que sur la sortie standard.

Conséquence concrète : plusieurs refus du produit disent « consultez le journal
du serveur avant de continuer » — base de connaissances inatteignable, index de
workspaces illisible, classeur ingénérable. Sur un serveur isolé, lancé par un
raccourci ou un service, cette sortie standard n'est lue par personne et
disparaît à l'arrêt. Le message renvoyait vers un journal qui n'existait pas.

Trois choix ici.

**Le fichier est écrit par défaut**, dans `logs/`. C'est un choix par défaut,
pas une valeur en dur : `KOVEX_LOG_FILE` le déplace, une valeur vide le
désactive. Un défaut qui rend vraie la consigne affichée vaut mieux qu'un
réglage que personne n'active.

**Le fichier tourne.** Un journal en ajout continu sur un serveur isolé finit
par remplir le disque, et c'est le produit qui s'arrête. Taille et nombre de
fichiers conservés sont réglables.

**La configuration est explicite.** Le module appelait `setup_logging()` à
l'import : importer un module vidait les gestionnaires du journal racine de
toute l'application, y compris ceux d'une suite de tests. La configuration se
demande maintenant, elle ne s'impose plus.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from src.infrastructure import configuration

#: Niveau, format et destination : réglables par l'exploitant, sous l'un ou
#: l'autre préfixe (voir `configuration.py`).
NIVEAU = configuration.variable("LOG_LEVEL", "INFO").upper()
FORMAT = configuration.variable("LOG_FORMAT", "text").lower()

#: Chemin du journal. Une chaîne vide désactive l'écriture dans un fichier.
FICHIER = configuration.variable("LOG_FILE", "logs/kovex.log")

#: Rotation : au-delà de cette taille, le fichier est archivé.
TAILLE_MAX = configuration.entier("LOG_MAX_BYTES", 10 * 1024 * 1024)

#: Nombre d'archives conservées. Au-delà, la plus ancienne est effacée.
ARCHIVES = configuration.entier("LOG_BACKUPS", 5)

#: Bibliothèques dont le bavardage masque les messages du produit.
BRUIT = {
    "uvicorn.access": logging.WARNING,
    "uvicorn.error": logging.INFO,
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
}


class JSONFormatter(logging.Formatter):
    """Une ligne JSON par message.

    C'est le format du fichier, toujours : un journal d'incident se relit avec
    un outil, et une ligne colorée destinée à un terminal ne s'y prête pas.
    """

    def format(self, record: logging.LogRecord) -> str:
        donnees: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if record.exc_info:
            donnees["exception"] = self.formatException(record.exc_info)

        for attribut in ("user", "request_id", "duration_ms", "workspace"):
            if hasattr(record, attribut):
                donnees[attribut] = getattr(record, attribut)

        if hasattr(record, "extra_fields"):
            donnees.update(record.extra_fields)

        # `default=str` : un objet non sérialisable ne doit pas faire perdre
        # la ligne de journal qui l'accompagne.
        return json.dumps(donnees, ensure_ascii=False, default=str)


class ColoredFormatter(logging.Formatter):
    """Ligne lisible, colorée par niveau, pour un vrai terminal."""

    COULEURS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[41m",
    }
    NEUTRE = "\033[0m"
    NOM = "\033[34m"

    def format(self, record: logging.LogRecord) -> str:
        couleur = self.COULEURS.get(record.levelname, "")
        heure = datetime.now().strftime("%H:%M:%S")
        ligne = (f"{heure} | {couleur}{record.levelname:8}{self.NEUTRE} | "
                 f"{self.NOM}{record.name:20}{self.NEUTRE} | {record.getMessage()}")
        if record.exc_info:
            ligne += f"\n{self.formatException(record.exc_info)}"
        return ligne


class ContextLogger(logging.LoggerAdapter):
    """Logger acceptant des champs nommés, repris tels quels dans le JSON.

        journal = get_logger(__name__)
        journal.info("Import terminé", workspace="DEMO", lignes=1200)
    """

    #: Arguments que `logging` traite lui-même : ils ne sont pas du contexte.
    RESERVES = {"exc_info", "stack_info", "stacklevel", "extra"}

    def process(self, msg: str, kwargs: Dict) -> tuple:
        extra = dict(kwargs.pop("extra", {}) or {})
        contexte = {cle: kwargs.pop(cle) for cle in list(kwargs)
                    if cle not in self.RESERVES}
        if contexte:
            extra["extra_fields"] = contexte
        kwargs["extra"] = extra
        return msg, kwargs


def _formatteur_console(format_demande: str) -> logging.Formatter:
    if format_demande == "json":
        return JSONFormatter()
    if sys.stdout.isatty():
        return ColoredFormatter()
    # Sortie redirigée : les séquences de couleur y deviennent du bruit.
    return logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S")


def setup_logging(level: str = None, format_type: str = None,
                  log_file: Optional[str] = None,
                  taille_max: int = None, archives: int = None) -> logging.Logger:
    """Configure le journal de l'application et rend le logger racine.

    Les paramètres non fournis viennent de l'environnement. La fonction est
    idempotente : elle remplace les gestionnaires en place plutôt que de les
    empiler, ce qui évite qu'un second appel double chaque ligne.
    """
    level = (level or NIVEAU).upper()
    format_type = (format_type or FORMAT).lower()
    log_file = FICHIER if log_file is None else log_file
    taille_max = TAILLE_MAX if taille_max is None else taille_max
    archives = ARCHIVES if archives is None else archives

    racine = logging.getLogger()
    racine.setLevel(getattr(logging, level, logging.INFO))
    for gestionnaire in list(racine.handlers):
        racine.removeHandler(gestionnaire)
        gestionnaire.close()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(_formatteur_console(format_type))
    racine.addHandler(console)

    if log_file:
        chemin = Path(log_file)
        try:
            chemin.parent.mkdir(parents=True, exist_ok=True)
            fichier = logging.handlers.RotatingFileHandler(
                chemin, maxBytes=taille_max, backupCount=archives,
                encoding="utf-8")
            fichier.setFormatter(JSONFormatter())
            racine.addHandler(fichier)
        except OSError as erreur:
            # Disque plein, dossier en lecture seule : le produit doit
            # démarrer quand même, en le disant. Refuser de se lancer faute de
            # journal serait pire que de tourner sans.
            racine.warning(
                "Journal fichier indisponible (%s) : la sortie standard seule "
                "est utilisée.", erreur)

    for nom, seuil in BRUIT.items():
        logging.getLogger(nom).setLevel(seuil)

    racine.info("Journal configuré : niveau=%s, format=%s, fichier=%s",
                level, format_type, log_file or "aucun")
    return racine


def get_logger(name: str) -> ContextLogger:
    """Logger acceptant des champs de contexte nommés."""
    return ContextLogger(logging.getLogger(name), {})
