"""Point de lancement de l'API Kovex.

Le port et le rechargement automatique étaient écrits en dur. Le premier
empêchait de faire cohabiter deux instances ou de contourner un port déjà
occupé ; le second, actif en permanence, fait tourner un processus surveillant
tous les fichiers du projet — utile en développement, inutile et coûteux sur
un serveur d'exploitation, où il redémarre l'API au moindre fichier touché.
"""

import logging
import os
import sys
from pathlib import Path

import uvicorn

# Le dossier du projet doit être dans le chemin d'import : les modules sont
# référencés par `src.…` et le script peut être lancé depuis n'importe où.
RACINE = Path(__file__).resolve().parent
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

# Le fichier `.env` est chargé **ici**, et non seulement dans l'application.
#
# `src.api.main` le charge déjà, mais uvicorn ne l'importe qu'après avoir reçu
# ses propres réglages : une variable posée dans `.env` pour ce lanceur —
# KOVEX_API_HOST, KOVEX_API_PORT, KOVEX_API_RELOAD — n'était donc pas lue, sans
# que rien ne le dise. Un exploitant qui coupe le rechargement dans `.env`
# doit obtenir un rechargement coupé.
# Le `.env` cherché est celui du **répertoire de travail**, avec celui du
# script pour repli. C'est la convention déjà en vigueur ici : les chemins des
# fichiers sources sont relatifs dans `config.json` et résolus contre le
# répertoire courant, et le lanceur Windows s'y place explicitement.
try:
    from dotenv import load_dotenv

    for candidat in (Path.cwd() / ".env", RACINE / ".env"):
        if candidat.is_file():
            load_dotenv(candidat)
            break
except ImportError:  # pragma: no cover - python-dotenv est dans requirements
    pass

from src.infrastructure.branding import NOM_PRODUIT  # noqa: E402

from src.infrastructure.logging_config import setup_logging

HOTE_PAR_DEFAUT = "127.0.0.1"
PORT_PAR_DEFAUT = 8000

#: Ce que le rechargement automatique surveille. Sans cette liste, uvicorn
#: surveille le répertoire de travail **en entier** — donc `workspaces/`, où
#: l'application écrit. Un import de données provoquait alors un redémarrage
#: du serveur pendant la requête qui l'écrivait, et la mise en place du
#: fichier échouait avec un refus d'accès que rien n'expliquait.
#:
#: Seul le code de l'API justifie un redémarrage : l'interface est servie par
#: un autre processus, et le navigateur la recharge tout seul.
DOSSIERS_SURVEILLES = ("src",)


def main() -> None:
    # Journal commun à l'API et au lanceur : un incident au démarrage doit
    # se retrouver dans le même fichier que ceux d'après.
    setup_logging()

    hote = os.environ.get("KOVEX_API_HOST", HOTE_PAR_DEFAUT)
    port = int(os.environ.get("KOVEX_API_PORT", PORT_PAR_DEFAUT))

    # Le rechargement automatique ne s'active qu'en développement, et se coupe
    # explicitement. En exploitation, il n'a aucune raison d'être.
    environnement = os.environ.get("PYGIA_ENV", "development").lower()
    rechargement = os.environ.get(
        "KOVEX_API_RELOAD", "true" if environnement == "development" else "false"
    ).lower() == "true"

    print(f"Demarrage de l'API {NOM_PRODUIT} sur http://{hote}:{port}")
    if rechargement:
        print("Rechargement automatique actif (environnement de developpement).")

    reglages = {"host": hote, "port": port, "reload": rechargement}
    if rechargement:
        reglages["reload_dirs"] = [str(RACINE / dossier)
                                   for dossier in DOSSIERS_SURVEILLES]
    uvicorn.run("src.api.main:app", **reglages)


if __name__ == "__main__":
    main()
