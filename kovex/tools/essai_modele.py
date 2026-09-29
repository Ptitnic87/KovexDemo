#!/usr/bin/env python3
# Fichier : tools/essai_modele.py
"""Ce que le modèle répond vraiment, avant tout contrôle du produit.

L'écran dit ce qu'il a retenu et pourquoi il a écarté le reste. Il ne montre
pas la réponse brute — et c'est volontaire : ce que le produit affiche doit
être ce qu'il a vérifié. Mais quand une proposition attendue n'arrive pas, la
question devient « le modèle ne l'a pas proposée » ou « le produit l'a
écartée », et ces deux-là ne se corrigent pas au même endroit.

    python tools/essai_modele.py --colonne type_contrat
    python tools/essai_modele.py --valeurs "CDI,C.D.I.,Contrat à durée indéterminée"

Rien n'est enregistré, aucun réglage n'est lu depuis le workspace : c'est un
outil de diagnostic, et il envoie exactement la consigne du produit.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

# Le `.env` du répertoire de travail, celui de la racine pour repli — la même
# convention que le lanceur du serveur. Sans cela, cet outil ne voit pas les
# réglages que le produit voit, et annonce « adresse non définie » à quelqu'un
# qui l'a parfaitement définie : le diagnostic se met alors à diagnostiquer
# lui-même.
try:
    from dotenv import load_dotenv

    for candidat in (Path.cwd() / ".env", RACINE / ".env"):
        if candidat.is_file():
            load_dotenv(candidat)
            break
except ImportError:  # pragma: no cover - python-dotenv est dans requirements
    pass

from src.core.annotation.annotateur import (  # noqa: E402
    AnnotateurIndisponible, depuis_l_environnement, envoyer)
from src.core.annotation.propositions import composer_la_demande_de  # noqa: E402
from src.core.annotation.regroupeur import CONSIGNE_REGROUPEMENT  # noqa: E402
from src.core.data import coherence  # noqa: E402


def _valeurs_du_workspace(colonne: str, workspace: str) -> list:
    """Les valeurs distinctes d'une colonne, les plus fréquentes d'abord."""
    import csv

    config = json.loads(
        (RACINE / "workspaces" / workspace / "config.json").read_text(encoding="utf-8"))
    chemin = RACINE / config["files"]["identities"]["path"]
    separateur = config["files"]["identities"].get("delimiter", ";")
    with open(chemin, encoding=config["files"]["identities"].get("encoding", "utf-8"),
              newline="") as flux:
        lignes = list(csv.DictReader(flux, delimiter=separateur))
    if lignes and colonne not in lignes[0]:
        raise SystemExit("colonne absente : %s (colonnes : %s)"
                         % (colonne, ", ".join(sorted(lignes[0]))))
    effectifs = coherence.compter(ligne.get(colonne, "") for ligne in lignes)
    return coherence.valeurs_retenues(effectifs, 300)


def main(arguments=None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    analyseur.add_argument("--colonne", default="")
    analyseur.add_argument("--workspace", default="DEMO")
    analyseur.add_argument("--valeurs", default="",
                           help="valeurs séparées par des virgules, au lieu d'une colonne")
    analyseur.add_argument("--langue", default="fr")
    options = analyseur.parse_args(arguments)

    if options.valeurs:
        valeurs = [v.strip() for v in options.valeurs.split(",") if v.strip()]
    elif options.colonne:
        valeurs = _valeurs_du_workspace(options.colonne, options.workspace)
    else:
        raise SystemExit("donner --colonne ou --valeurs")

    reglages = depuis_l_environnement(os.environ, "coherence_des_valeurs")
    if not reglages.adresse:
        vus = [str(c) for c in (Path.cwd() / ".env", RACINE / ".env") if c.is_file()]
        raise SystemExit(
            "KOVEX_ANNOTATEUR_URL n'est pas défini : le produit ne connaît "
            "aucune adresse par défaut, et c'est délibéré.\n"
            "Fichiers .env trouvés : %s\n"
            "Sinon, définir la variable dans le shell :\n"
            "    set KOVEX_ANNOTATEUR_URL=http://127.0.0.1:11434"
            % (", ".join(vus) or "aucun"))

    print("modèle   :", reglages.modele or "(non défini)")
    print("adresse  :", reglages.adresse)
    print("valeurs  :", json.dumps(valeurs, ensure_ascii=False))
    print()

    try:
        reponse = envoyer(
            composer_la_demande_de(CONSIGNE_REGROUPEMENT, {"valeurs": valeurs},
                                   reglages, options.langue),
            reglages)
    except AnnotateurIndisponible as erreur:
        raise SystemExit("modèle injoignable : %s" % erreur)

    print("--- réponse brute du modèle ---")
    print(reponse if isinstance(reponse, str)
          else json.dumps(reponse, ensure_ascii=False, indent=2))
    print()

    # Le même contrôle que le produit, pour voir ce qui passerait.
    from src.core.annotation.regroupeur import groupes_lus, grappes_verifiees
    effectifs = {valeur: 1 for valeur in valeurs}
    grappes, ecartees = grappes_verifiees(groupes_lus(reponse), effectifs, valeurs)
    print("--- ce que le produit retiendrait ---")
    for grappe in grappes:
        print("   %s  ->  %s" % (" + ".join(grappe.valeurs), grappe.forme_retenue))
        # Le motif est ce qui trahit un regroupement faux : aucun contrôle ne
        # sait ce que les valeurs veulent dire, et c'est la phrase du modèle
        # qui a permis de voir qu'il tenait « CDD » pour un contrat à durée
        # indéterminée. L'écran l'affiche ; le diagnostic aussi.
        if grappe.motif:
            print("      motif : %s" % grappe.motif)
    if not grappes:
        print("   (aucune)")
    print()
    print("--- pourquoi le reste est écarté ---")
    for cle, compte in sorted(ecartees.items()):
        if compte:
            print("   %-24s %d" % (cle, compte))
    return 0


if __name__ == "__main__":  # pragma: no cover - point d'entrée
    raise SystemExit(main())
