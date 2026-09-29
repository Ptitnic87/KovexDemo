#!/usr/bin/env python3
# Fichier : rotation_secrets.py
"""Renouvelle les secrets d'une installation, après une fuite du dépôt.

`.env` et `config/users.json` figurent dans l'historique git du projet
(commits `c1b00b5` et `b5c92b6`). Ils n'y sont plus suivis, mais l'historique
les conserve : `git show c1b00b5:.env` rend la clé de signature des jetons, et
le fichier des comptes rend les empreintes des mots de passe.

Conséquence : la faille refermée dans le code — faire lire `.env` par le
produit pour forger un jeton administrateur — reste ouverte pour quiconque
possède un clone, **sans aucun exploit**.

Réécrire l'historique ne suffit pas : un clone déjà pris garde l'ancienne
version. Ce qui referme réellement la brèche, c'est de **renouveler les
secrets** — une clé de signature changée rend inutilisable tout jeton forgé
avec l'ancienne, y compris ceux déjà fabriqués. C'est ce que fait ce script.

    python rotation_secrets.py                 # constate, ne modifie rien
    python rotation_secrets.py --appliquer     # renouvelle

Les nouveaux mots de passe sont affichés **une seule fois**. Le fichier `.env`
est sauvegardé avant modification.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import sys
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parent
CHEMIN_ENV = RACINE / ".env"
CHEMIN_COMPTES = RACINE / "config" / "users.json"

#: Variable portant la clé de signature des jetons.
CLE_SIGNATURE = "PYGIA_SECRET_KEY"

#: Longueur de la clé, en octets. 32 octets = 256 bits, la taille attendue par
#: HMAC-SHA256 ; en dessous, PyJWT émet un avertissement et la signature est
#: plus facile à attaquer hors ligne.
OCTETS_CLE = 32

#: Longueur des mots de passe engendrés. Assez pour qu'ils ne soient pas
#: mémorisés — ils ont vocation à être déposés dans un gestionnaire.
LONGUEUR_MOT_DE_PASSE = 24


def nouvelle_cle() -> str:
    return secrets.token_hex(OCTETS_CLE)


def nouveau_mot_de_passe() -> str:
    return secrets.token_urlsafe(LONGUEUR_MOT_DE_PASSE)


def remplacer_variable(contenu: str, nom: str, valeur: str) -> str:
    """Remplace une variable dans un `.env`, ou l'ajoute si elle en est absente.

    Les commentaires et l'ordre des autres variables sont conservés : un
    fichier de configuration réécrit de zéro perd les notes que
    l'exploitant y a laissées.
    """
    motif = re.compile(rf"^(\s*){re.escape(nom)}\s*=.*$", re.MULTILINE)
    if motif.search(contenu):
        return motif.sub(lambda m: f"{m.group(1)}{nom}={valeur}", contenu, count=1)
    separateur = "" if contenu.endswith("\n") or not contenu else "\n"
    return f"{contenu}{separateur}{nom}={valeur}\n"


def comptes_existants() -> dict:
    if not CHEMIN_COMPTES.exists():
        return {}
    try:
        return json.loads(CHEMIN_COMPTES.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as erreur:
        print(f"  ! fichier des comptes illisible ({erreur})")
        return {}


def constater() -> int:
    """Affiche ce qui serait renouvelé, sans rien modifier."""
    print("Constat, aucune modification :\n")

    if CHEMIN_ENV.exists():
        contenu = CHEMIN_ENV.read_text(encoding="utf-8")
        presente = re.search(rf"^\s*{CLE_SIGNATURE}\s*=\s*\S", contenu, re.MULTILINE)
        print(f"  .env                 : présent, {CLE_SIGNATURE} "
              f"{'renseignée' if presente else 'absente'}")
    else:
        print("  .env                 : absent (il sera créé)")

    comptes = comptes_existants()
    if comptes:
        print(f"  config/users.json    : {len(comptes)} compte(s) — "
              + ", ".join(sorted(comptes)))
    else:
        print("  config/users.json    : absent ou vide")

    print("\nRelancer avec --appliquer pour renouveler.")
    return 0


def appliquer() -> int:
    horodatage = datetime.now().strftime("%Y%m%d-%H%M%S")

    # --- clé de signature ------------------------------------------------
    contenu = CHEMIN_ENV.read_text(encoding="utf-8") if CHEMIN_ENV.exists() else ""
    if CHEMIN_ENV.exists():
        # Construit explicitement : `Path(".env").with_suffix(...)` traite
        # `.env` comme un nom sans extension et produit `.env.env.avant-…`.
        sauvegarde = CHEMIN_ENV.parent / f".env.avant-{horodatage}"
        shutil.copy2(CHEMIN_ENV, sauvegarde)
        print(f"  .env sauvegardé dans {sauvegarde.name}")

    CHEMIN_ENV.write_text(
        remplacer_variable(contenu, CLE_SIGNATURE, nouvelle_cle()),
        encoding="utf-8")
    try:
        os.chmod(CHEMIN_ENV, 0o600)
    except OSError:  # pragma: no cover - systèmes sans permissions POSIX
        pass
    print(f"  {CLE_SIGNATURE} renouvelée — tous les jetons en circulation, "
          "y compris ceux forgés avec l'ancienne clé, sont désormais invalides.")

    # --- mots de passe ---------------------------------------------------
    comptes = comptes_existants()
    if not comptes:
        print("  Aucun compte à renouveler.")
        return 0

    # Import tardif : charger `auth` impose la clé de signature, et on veut
    # que la nouvelle soit déjà en place.
    os.environ[CLE_SIGNATURE] = re.search(
        rf"^\s*{CLE_SIGNATURE}\s*=\s*(\S+)",
        CHEMIN_ENV.read_text(encoding="utf-8"), re.MULTILINE).group(1)
    sys.path.insert(0, str(RACINE))
    from src.core.security.auth import UserManager

    gestionnaire = UserManager(str(CHEMIN_COMPTES))
    nouveaux = {}
    for nom in sorted(comptes):
        mot_de_passe = nouveau_mot_de_passe()
        if gestionnaire.set_password(nom, mot_de_passe):
            nouveaux[nom] = mot_de_passe

    print("\n  Nouveaux mots de passe — affichés une seule fois :\n")
    for nom, mot_de_passe in nouveaux.items():
        print(f"    {nom:<12} {mot_de_passe}")

    print("\n  Déposez-les dans votre gestionnaire de mots de passe, puis "
          "effacez cette sortie.")
    print("  Les sessions ouvertes sont fermées : chacun devra se reconnecter.")
    return 0


def main(arguments=None) -> int:
    analyseur = argparse.ArgumentParser(
        description="Renouvelle la clé de signature et les mots de passe.")
    analyseur.add_argument(
        "--appliquer", action="store_true",
        help="renouvelle réellement ; sans cette option, le script se contente "
             "de constater")
    options = analyseur.parse_args(arguments)

    return appliquer() if options.appliquer else constater()


if __name__ == "__main__":  # pragma: no cover - point d'entrée
    raise SystemExit(main())
