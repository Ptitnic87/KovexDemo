#!/usr/bin/env python3
# Fichier : restaurer.py
"""Remet les espaces de démonstration dans leur état figé, datés d'aujourd'hui.

À chaque lancement de la plateforme de démonstration, les espaces reviennent
tels que ``construire_la_demo.py`` les a figés : ce qu'une séance précédente a
validé, refusé ou supprimé disparaît, et le mining conservé est de nouveau là.

**Les dates suivent le jour de la restauration.** Un contrôle compensatoire
exécuté « il y a sept jours » le jour de la construction serait périmé trois
semaines plus tard, et la dérogation qui le cite s'afficherait « sans effet »
devant un client. Toutes les dates des espaces sont donc décalées du même
nombre de jours : l'histoire racontée reste la même, à la même distance
d'aujourd'hui.

**Le modèle est réglé ici, pas dans l'instantané.** ``modele.json`` porte
l'adresse du fournisseur, le nom du modèle et les usages ouverts ; il est lu et
vérifié par le code du produit lui-même, puis écrit dans chaque espace. La clé,
elle, n'est ni dans ce fichier ni dans le dépôt : elle se pose une fois sur le
serveur (``poser_la_cle.py``) et survit aux restaurations.

    python restaurer.py

Kovex est copié dans ``kovex/`` : c'est lui que la
restauration remplit, et l'instantané doit avoir été construit pour **cette
version-là** de Kovex. Une autre version pourrait relire autrement la base de
connaissance ou les minings conservés ; la restauration refuse donc de tourner
sur une version différente, sauf ``--forcer-version``.

Kovex doit être **arrêté** : le serveur garde les espaces en mémoire, et une
restauration sous ses pieds serait écrasée par le prochain enregistrement.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import socket
import subprocess
import sys
import tarfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

ICI = Path(__file__).resolve().parent
#: Kovex, copié dans ce dépôt à la version pour laquelle l'instantané a été
#: construit (``mettre_a_jour_kovex.py``).
KOVEX = ICI / "kovex"
#: Écrit par ``mettre_a_jour_kovex.py`` : le commit de Kovex copié.
FICHIER_VERSION = ".kovex_version"

#: Un identifiant d'espace ne sort jamais du dossier des espaces.
IDENTIFIANT = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
#: Une date ISO, avec ou sans heure. Seules les valeurs qui sont entièrement
#: une date sont décalées : un libellé qui en contient une reste intact.
DATE_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(T[0-9:.+-]+)?$")
#: Les fichiers d'un espace qui portent des dates.
FICHIERS_DATES = ("knowledge_base.json", "candidats.json")


class RestaurationRefusee(RuntimeError):
    """Une restauration qui ne doit pas avoir lieu."""


def version_de_kovex(racine: Path) -> Optional[str]:
    """Le commit de Kovex installé : le fichier d'archive, sinon git, sinon rien."""
    fichier = racine / FICHIER_VERSION
    if fichier.exists():
        return fichier.read_text(encoding="utf-8").strip() or None
    # Sans dépôt git propre, `git -C` remonterait au dépôt parent et rendrait
    # son commit à lui : mieux vaut ne rien savoir que se tromper de version.
    if not (racine / ".git").exists():
        return None
    try:
        sortie = subprocess.run(["git", "-C", str(racine), "rev-parse", "HEAD"],
                                capture_output=True, text=True, timeout=30, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return sortie.stdout.strip() or None


def kovex_repond(api: str) -> bool:
    """Le serveur écoute-t-il ? Une connexion suffit, sans requête."""
    morceaux = urlsplit(api)
    try:
        with socket.create_connection((morceaux.hostname or "127.0.0.1",
                                       morceaux.port or 80), timeout=1):
            return True
    except OSError:
        return False


def decaler(valeur: Any, jours: int) -> Any:
    """Décale toutes les dates d'un document JSON du même nombre de jours."""
    if isinstance(valeur, dict):
        return {cle: decaler(v, jours) for cle, v in valeur.items()}
    if isinstance(valeur, list):
        return [decaler(v, jours) for v in valeur]
    if isinstance(valeur, str):
        trouve = DATE_ISO.match(valeur)
        if not trouve:
            return valeur
        try:
            jour = date(int(trouve.group(1)), int(trouve.group(2)), int(trouve.group(3)))
        except ValueError:
            return valeur
        return (jour + timedelta(days=jours)).isoformat() + (trouve.group(4) or "")
    return valeur


def extraire(archive: Path, destination: Path, identifiant: str) -> None:
    """Extrait une archive d'espace, sans rien écrire hors de son dossier.

    Chaque membre est vérifié avant extraction : un chemin absolu, un
    ``..``, un lien ou un fichier spécial ferait sortir l'archive du dossier
    des espaces. L'archive vient du dépôt, mais un dépôt se modifie.
    """
    with tarfile.open(archive, "r:gz") as tar:
        membres = tar.getmembers()
        for membre in membres:
            parties = Path(membre.name).parts
            if (membre.name.startswith(("/", "\\")) or ".." in parties
                    or not parties or parties[0] != identifiant):
                raise RestaurationRefusee("chemin refusé dans %s : %s" % (archive.name, membre.name))
            if not (membre.isfile() or membre.isdir()):
                raise RestaurationRefusee("membre refusé dans %s : %s" % (archive.name, membre.name))
        for membre in membres:
            cible = destination / membre.name
            if membre.isdir():
                cible.mkdir(parents=True, exist_ok=True)
                continue
            cible.parent.mkdir(parents=True, exist_ok=True)
            source = tar.extractfile(membre)
            with open(cible, "wb") as flux:
                shutil.copyfileobj(source, flux)  # type: ignore[arg-type]


def regler_le_modele(configuration: Dict[str, Any], modele: Dict[str, Any]) -> List[str]:
    """Écrit le point de terminaison et les usages, lus par le code du produit.

    Rien n'est écrit tel quel : les deux blocs passent par les lecteurs du
    produit, et le moindre avertissement arrête la restauration. Un réglage
    que le produit relirait autrement que prévu ferait croire à un usage
    ouvert — ou fermé — qui ne l'est pas.
    """
    from src.core.annotation import assistance, points_de_terminaison

    notes: List[str] = []
    prereglage = modele.get("prereglage") or {}
    if prereglage.get("adresse") and prereglage.get("modele"):
        bloc = {"prereglages": [prereglage],
                "commun": {"prereglage": prereglage.get("identifiant", "")}}
        lu = points_de_terminaison.depuis_la_configuration(
            {points_de_terminaison.CLE_POINTS_DE_TERMINAISON: bloc})
        if lu.avertissements:
            raise RestaurationRefusee("modele.json, point de terminaison : %s"
                                      % lu.avertissements)
        configuration[points_de_terminaison.CLE_POINTS_DE_TERMINAISON] = \
            points_de_terminaison.en_document(lu)
    else:
        notes.append("modèle non réglé : adresse ou nom du modèle vide dans modele.json")

    matrice = assistance.Assistance.depuis_la_configuration(
        {assistance.CLE_ASSISTANCE: modele.get("assistance") or {}})
    if matrice.avertissements:
        raise RestaurationRefusee("modele.json, usages : %s" % list(matrice.avertissements))
    configuration[assistance.CLE_ASSISTANCE] = matrice.en_document()
    return notes


def fusionner_le_registre(chemin: Path, entrees: Iterable[Dict[str, Any]],
                          actif: str) -> None:
    """Remplace les entrées des espaces restaurés ; les autres restent."""
    registre: Dict[str, Any] = {"version": "1.0", "active_workspace": None, "workspaces": []}
    if chemin.exists():
        registre = json.loads(chemin.read_text(encoding="utf-8"))
    nouvelles = {e["id"]: e for e in entrees}
    gardees = [e for e in registre.get("workspaces", []) if e.get("id") not in nouvelles]
    maintenant = datetime.now().isoformat()
    registre["workspaces"] = gardees + [dict(e, last_accessed=maintenant)
                                        for e in nouvelles.values()]
    registre["active_workspace"] = actif
    chemin.write_text(json.dumps(registre, indent=4, ensure_ascii=False), encoding="utf-8")


def restaurer(racine: Path, instantane: Path, modele: Dict[str, Any],
              actif: Optional[str], aujourd_hui: date,
              forcer_version: bool = False) -> Tuple[List[str], List[str], int]:
    index = json.loads((instantane / "index.json").read_text(encoding="utf-8"))
    attendue = index.get("kovex_version")
    installee = version_de_kovex(racine)
    if attendue and installee and attendue != installee and not forcer_version:
        raise RestaurationRefusee(
            "l'instantané a été construit pour Kovex %s, la version installée est %s. "
            "Reconstruisez l'instantané (construire_la_demo.py) ou remettez le "
            "Kovex de la version attendue (mettre_a_jour_kovex.py)." % (attendue[:12], installee[:12]))
    ecart = (aujourd_hui - date.fromisoformat(index["construit_le"])).days
    espaces = racine / "workspaces"
    espaces.mkdir(parents=True, exist_ok=True)

    restaures: List[str] = []
    notes: List[str] = []
    entrees: List[Dict[str, Any]] = []
    for entree in index["espaces"]:
        identifiant = entree["id"]
        if not IDENTIFIANT.match(identifiant):
            raise RestaurationRefusee("identifiant d'espace refusé : %r" % identifiant)
        dossier = espaces / identifiant
        if dossier.exists():
            shutil.rmtree(dossier)
        extraire(instantane / ("%s.tar.gz" % identifiant), espaces, identifiant)
        (dossier / "output").mkdir(exist_ok=True)

        for nom in FICHIERS_DATES:
            fichier = dossier / nom
            if fichier.exists():
                document = json.loads(fichier.read_text(encoding="utf-8"))
                fichier.write_text(json.dumps(decaler(document, ecart), indent=2,
                                              ensure_ascii=False), encoding="utf-8")

        chemin_configuration = dossier / "config.json"
        configuration = json.loads(chemin_configuration.read_text(encoding="utf-8"))
        for note in regler_le_modele(configuration, modele):
            if note not in notes:
                notes.append(note)
        chemin_configuration.write_text(json.dumps(configuration, indent=4, ensure_ascii=False),
                                        encoding="utf-8")
        entrees.append(decaler(entree, ecart))
        restaures.append(identifiant)

    choisi = actif or restaures[0]
    if choisi not in restaures:
        raise RestaurationRefusee("espace actif inconnu : %s" % choisi)
    fusionner_le_registre(espaces / "workspaces.json", entrees, choisi)
    return restaures, notes, ecart


def main(arguments: Optional[Sequence[str]] = None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    analyseur.add_argument("--racine", default=str(KOVEX),
                           help="dossier de Kovex ; kovex/ par défaut")
    analyseur.add_argument("--instantane", default=str(ICI / "instantane"))
    analyseur.add_argument("--modele", default=str(ICI / "modele.json"))
    analyseur.add_argument("--actif", default=None,
                           help="espace ouvert au démarrage ; le premier de l'index par défaut")
    analyseur.add_argument("--api", default="http://127.0.0.1:8000",
                           help="adresse de l'API, pour vérifier qu'elle est arrêtée")
    analyseur.add_argument("--forcer-version", action="store_true",
                           help="restaurer même si Kovex n'est pas la version de l'instantané")
    options = analyseur.parse_args(arguments)

    racine = Path(options.racine).resolve()
    sys.path.insert(0, str(racine))
    if kovex_repond(options.api):
        print("Kovex tourne sur %s : arrêtez-le avant de restaurer." % options.api,
              file=sys.stderr)
        return 2
    modele = json.loads(Path(options.modele).read_text(encoding="utf-8"))
    try:
        restaures, notes, ecart = restaurer(racine, Path(options.instantane), modele,
                                            options.actif, date.today(),
                                            options.forcer_version)
    except RestaurationRefusee as refus:
        print("Restauration refusée : %s" % refus, file=sys.stderr)
        return 1
    print("Espaces restaurés (dates décalées de %d jour(s)) : %s" % (ecart, ", ".join(restaures)))
    for note in notes:
        print("  À noter : %s" % note)
    return 0


if __name__ == "__main__":  # pragma: no cover - point d'entrée
    raise SystemExit(main())
