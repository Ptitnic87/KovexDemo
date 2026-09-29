#!/usr/bin/env python3
# Fichier : poser_la_cle.py
"""Pose, une fois, la clé du modèle de démonstration sur ce serveur.

La clé ne va ni dans le dépôt, ni dans ``modele.json``, ni dans un
espace : elle va dans le porte-clés du serveur (``config/cles_annotateur.json``,
hors dépôt), par la route du produit, comme l'écran « Points de terminaison des
modèles » la poserait. Les restaurations ne touchent pas ``config/`` : posée
une fois, elle sert à chaque lancement.

    python poser_la_cle.py --utilisateur admin

Kovex doit tourner, restauré (le préréglage doit exister). Le mot de passe et
la clé sont saisis au terminal, sans écho, et ne sont ni affichés ni écrits
ailleurs que dans le porte-clés.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))

from construire_la_demo import Kovex  # noqa: E402


def main(arguments: Optional[Sequence[str]] = None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    analyseur.add_argument("--api", default="http://127.0.0.1:8000")
    analyseur.add_argument("--modele", default=str(ICI / "modele.json"))
    analyseur.add_argument("--utilisateur", default="",
                           help="compte administrateur ; vide si l'authentification est désactivée")
    options = analyseur.parse_args(arguments)

    identifiant = json.loads(Path(options.modele).read_text(encoding="utf-8")
                             )["prereglage"]["identifiant"]
    kovex = Kovex(options.api)
    if options.utilisateur:
        kovex.connecter(options.utilisateur,
                        getpass.getpass("Mot de passe de %s : " % options.utilisateur))
    cle = getpass.getpass("Clé du fournisseur pour « %s » : " % identifiant)
    if not cle.strip():
        print("Aucune clé saisie : rien n'est posé.", file=sys.stderr)
        return 1
    reponse = kovex.appeler("PUT", "/points-de-terminaison/prereglages/%s/cle" % identifiant,
                            {"cle": cle.strip()})
    posees = [p["identifiant"] for p in reponse.get("prereglages", []) if p.get("cle_posee")]
    print("Clé posée pour %s." % identifiant if identifiant in posees
          else "Le serveur ne confirme pas la clé : vérifiez l'écran des points de terminaison.")
    return 0 if identifiant in posees else 1


if __name__ == "__main__":  # pragma: no cover - point d'entrée
    raise SystemExit(main())
