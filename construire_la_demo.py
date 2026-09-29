#!/usr/bin/env python3
# Fichier : construire_la_demo.py
"""Construit les espaces de démonstration, par l'API du produit, et les fige.

Une démonstration ne doit ni attendre un mining de plusieurs minutes, ni
construire six mois de gouvernance devant un client. Ce script le fait **une
fois**, comme l'écran le ferait, par les mêmes routes :

- un espace par fiche de ``secteurs/`` : le référentiel généré, les droits
  socles, les règles de séparation, un contrôle compensatoire exécuté, une
  dérogation qui le cite, un rôle fait main, une cinquantaine de décisions
  (validations et refus, avec leurs chiffres), puis un mining applicatif et un
  mining métier **conservés** — l'écran les reprend d'un clic, sans recalcul ;
- un espace brut, rien de décidé, pour l'atelier en direct.

Puis il fige chaque espace dans ``instantane/`` : c'est ce que
``restaurer.py`` remet en place à chaque lancement.

    python construire_la_demo.py

Kovex doit tourner. Aucune donnée de client n'est lue, aucune clé n'est
écrite : le point de terminaison du modèle et son usage se règlent à la
restauration (``modele.json``), la clé se dépose une fois sur le serveur.
"""

from __future__ import annotations

import argparse
import csv
import getpass
import importlib.util
import json
import sys
import tarfile
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))

from restaurer import KOVEX, version_de_kovex  # noqa: E402

#: L'environnement des espaces gouvernés et celui de l'espace brut. Le client
#: vient de la fiche : ``Alvea_DEMO``, ``Tilleuls_DEMO``…
ENVIRONNEMENT = "DEMO"
ENVIRONNEMENT_BRUT = "ATELIER"
LIBELLE_BRUT = "Atelier — référentiel brut"

#: Les réglages du mining conservé. Ce sont ceux de l'atelier : seuil 1 — aucun
#: droit accordé en trop — et les trois façons de chercher par défaut.
MINING_CONSERVE = {
    "mining_mode": "APPROX", "similarity_threshold": 1.0, "min_users": 5,
    "min_rights": 3, "max_roles": 200, "apport_minimal": 1,
    "selection": "gloutonne",
    "generateurs": ["cloture", "signature", "intersection"],
}
#: Le mining rapide dont sortent les décisions : deux façons de chercher.
MINING_DES_DECISIONS = dict(MINING_CONSERVE, generateurs=["cloture", "signature"])


class Kovex:
    """Un client HTTP minimal : la bibliothèque standard, rien d'autre."""

    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/") + "/api/v1"
        self.jeton: Optional[str] = None

    def appeler(self, methode: str, chemin: str, corps: Any = None) -> Any:
        donnees = None if corps is None else json.dumps(corps).encode("utf-8")
        requete = urllib.request.Request(self.base + chemin, data=donnees, method=methode)
        requete.add_header("Content-Type", "application/json")
        if self.jeton:
            requete.add_header("Authorization", "Bearer " + self.jeton)
        try:
            with urllib.request.urlopen(requete, timeout=3600) as reponse:
                texte = reponse.read().decode("utf-8")
        except urllib.error.HTTPError as erreur:
            detail = erreur.read().decode("utf-8", errors="replace")
            raise SystemExit("%s %s → %d : %s" % (methode, chemin, erreur.code, detail[:400]))
        return json.loads(texte) if texte else None

    def connecter(self, utilisateur: str, mot_de_passe: str) -> None:
        reponse = self.appeler("POST", "/auth/login",
                               {"username": utilisateur, "password": mot_de_passe})
        self.jeton = reponse.get("access_token") or reponse.get("token")
        if not self.jeton:
            raise SystemExit("Connexion refusée : aucun jeton rendu.")


def charger(nom: str, chemin: Path):
    specification = importlib.util.spec_from_file_location(nom, chemin)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def lire(dossier: Path, nom: str) -> List[Dict[str, str]]:
    with open(dossier / "data" / nom, encoding="utf-8", newline="") as flux:
        return list(csv.DictReader(flux, delimiter=";"))


def creer_l_espace(kovex: Kovex, generateur, racine: Path, fiche: Dict[str, Any],
                   environnement: str, libelle: str) -> str:
    """Crée l'espace par le produit, puis y écrit le référentiel généré."""
    identifiant = "%s_%s" % (fiche["client"], environnement)
    existants = {e["id"] for e in kovex.appeler("GET", "/workspaces/").get("workspaces", [])}
    if identifiant in existants:
        raise SystemExit(
            "L'espace %s existe déjà : ce script ne remplace jamais un espace. "
            "Construisez la démonstration sur une installation vierge." % identifiant)
    kovex.appeler("POST", "/workspaces/", {"name": libelle, "client": fiche["client"],
                                           "environment": environnement})
    dossier = racine / "workspaces" / identifiant
    constructeur = generateur.generer(fiche)
    constructeur.ecrire(dossier)
    rates = [nom for nom, tenu, _ in constructeur.verifier() if not tenu]
    if rates:
        raise SystemExit("%s : cas non plantés (%s)." % (identifiant, ", ".join(rates)))
    kovex.appeler("POST", "/workspaces/switch/" + identifiant)
    # Le rechargement met à jour les volumes que l'écran des espaces affiche :
    # sans lui, un espace jamais rechargé s'annonce vide dans la liste.
    kovex.appeler("POST", "/workspaces/reload-data")
    return identifiant


def indicateurs(role: Dict[str, Any]) -> Dict[str, Any]:
    cles = ("right_count", "user_count", "over_granted", "fit_pct", "redundancy_pct")
    return {c: role[c] for c in cles if isinstance(role.get(c), (int, float))}


def gouverner(kovex: Kovex, dossier: Path, identifiant: str,
              fiche: Dict[str, Any]) -> Dict[str, Any]:
    """Six mois de gouvernance, posés comme l'écran les poserait."""
    gouvernance = fiche["gouvernance"]
    compte: Dict[str, Any] = {}

    configuration = kovex.appeler("GET", "/workspaces/%s/config" % identifiant)
    configuration["sod_severites"] = gouvernance["severites"]
    # Sans cette exigence, une exception couvrirait son constat même quand son
    # contrôle compensatoire a cessé de tourner.
    configuration["derogation_controle_exige"] = True
    kovex.appeler("PUT", "/workspaces/%s/config" % identifiant, configuration)
    kovex.appeler("POST", "/workspaces/reload-data")

    socles = [droit for droit, _ in fiche["socles"]]
    kovex.appeler("POST", "/kb/birth-rights",
                  {"rights": socles, "threshold": 90,
                   "name": fiche["socle_application"][1]})
    regles = [{"id": r["id"], "libelle": r["libelle"],
               "gauche": [{"type": "droit", "id": r["gauche"]}],
               "droite": [{"type": "droit", "id": r["droite"]}],
               "active": True, "severite": r["severite"],
               "processus": r["processus"], "proprietaire": r["proprietaire"]}
              for r in gouvernance["regles"]]
    kovex.appeler("PUT", "/separation/regles", {"regles": regles})

    controle = dict(gouvernance["controle"], actif=True)
    preuve = controle.pop("preuve")
    kovex.appeler("PUT", "/controles", {"controles": [controle]})
    kovex.appeler("POST", "/controles/%s/executions" % controle["id"], {
        "executant": controle["executant"], "relecteur": controle["relecteur"],
        "resultat": "conforme", "preuve": preuve,
        "execute_le": (date.today() - timedelta(
            days=int(gouvernance["execution_il_y_a_jours"]))).isoformat()})

    identites = {i["ID_utilisateur"]: i for i in lire(dossier, "identities.csv")}
    droits_de: Dict[str, Set[str]] = defaultdict(set)
    for ligne in lire(dossier, "habilitations.csv"):
        droits_de[ligne["ID_utilisateur"]].add(ligne["ID_droit"])
    enfreint = fiche["couple_enfreint"]
    gauche, droite = enfreint["droits"]
    cumulent = sorted(u for u, d in droits_de.items() if gauche in d and droite in d)
    du_role = [u for u in cumulent if identites[u]["fonction"] == enfreint["fonction"]]
    isoles = [u for u in cumulent if identites[u]["fonction"] != enfreint["fonction"]]
    if not du_role or not isoles:
        raise SystemExit("%s : le cumul attendu n'est pas dans le référentiel." % identifiant)

    communs = set.intersection(*(droits_de[u] for u in du_role)) - set(socles)
    fait_main = gouvernance["role_fait_main"]
    kovex.appeler("POST", "/roles/create", {
        "name": fait_main["nom"], "description": fait_main["description"],
        "role_type": "APPLICATIF", "rights": sorted(communs),
        "sub_role_ids": [], "additional_rights": []})
    compte["droits du rôle fait main"] = len(communs)

    kovex.appeler("POST", "/derogations", {
        "famille": "separation",
        "cible": {"regle": gouvernance["regles"][0]["id"], "identite": isoles[0]},
        "motif": gouvernance["derogation"],
        "echeance": (date.today() + timedelta(
            days=int(gouvernance["derogation_dans_jours"]))).isoformat(),
        "controle": controle["id"]})
    compte["en cumul"] = len(cumulent)

    # Des décisions comme l'écran les prendrait : les rôles portés par une
    # vraie population sont validés, les plus petits refusés, chacun avec ses
    # chiffres — c'est d'eux que le score apprend.
    decisions = gouvernance["decisions"]
    resultat = kovex.appeler("POST", "/mining/launch",
                             dict(MINING_DES_DECISIONS, excluded_rights=socles))
    candidats = [r for r in resultat.get("top_roles", []) if r.get("id")]
    par_population = sorted(candidats, key=lambda r: (-r.get("user_count", 0), r["id"]))
    voulus = int(decisions["validations"]) + int(decisions["refus"])
    if len(par_population) < voulus:
        raise SystemExit("%s : %d candidats pour %d décisions."
                         % (identifiant, len(par_population), voulus))
    applications = {a["ID_application"]: a["nom"] for a in lire(dossier, "applications.csv")}
    noms_pris: Counter = Counter()
    for role in par_population[:int(decisions["validations"])]:
        dominante = Counter(d.split("_")[0] for d in role["rights"]).most_common(1)[0][0]
        base = applications.get(dominante, dominante)
        noms_pris[base] += 1
        nom = base if noms_pris[base] == 1 else "%s (%d)" % (base, noms_pris[base])
        kovex.appeler("POST", "/roles/create", {
            "name": nom, "description": "", "role_type": "APPLICATIF",
            "rights": role["rights"], "sub_role_ids": [], "additional_rights": [],
            "candidate_id": role["id"], "indicateurs": indicateurs(role)})
    for role in par_population[-int(decisions["refus"]):]:
        kovex.appeler("POST", "/kb/reject-role", {
            "role_id": role["id"], "reason": decisions["motif_refus"],
            "indicateurs": indicateurs(role)})
    compte["validations"] = int(decisions["validations"])
    compte["refus"] = int(decisions["refus"])
    return compte


def conserver_les_minings(kovex: Kovex, fiche: Dict[str, Any]) -> Dict[str, Any]:
    """Les deux résultats que l'écran reprendra d'un clic, sans recalcul."""
    socles = [droit for droit, _ in fiche["socles"]]
    debut = time.monotonic()
    applicatif = kovex.appeler("POST", "/mining/launch",
                               dict(MINING_CONSERVE, excluded_rights=socles))
    duree_applicatif = time.monotonic() - debut
    debut = time.monotonic()
    metier = kovex.appeler("POST", "/mining-metiers/find-roles-business",
                           fiche["gouvernance"]["mining_metier"])
    duree_metier = time.monotonic() - debut
    return {
        "rôles applicatifs conservés": len(applicatif.get("top_roles", [])),
        "mining applicatif (s)": round(duree_applicatif, 1),
        "rôles métier conservés": len(metier.get("top_roles", metier.get("roles", []))),
        "mining métier (s)": round(duree_metier, 1),
    }


def figer(racine: Path, identifiants: Sequence[str], sortie: Path) -> None:
    """Chaque espace en une archive, et l'index qui dit comment les remettre.

    Le dossier ``output/`` n'est pas figé : il ne contient que des exports,
    et la démonstration les refait.
    """
    sortie.mkdir(parents=True, exist_ok=True)
    registre = json.loads((racine / "workspaces" / "workspaces.json").read_text(encoding="utf-8"))
    entrees = {e["id"]: e for e in registre.get("workspaces", [])}
    # La version de Kovex est figée avec l'instantané : restaurer.py refuse de
    # le remettre sous une autre.
    index = {"construit_le": date.today().isoformat(),
             "kovex_version": version_de_kovex(racine), "espaces": []}
    for identifiant in identifiants:
        dossier = racine / "workspaces" / identifiant
        archive = sortie / ("%s.tar.gz" % identifiant)

        def sans_sorties(info: tarfile.TarInfo) -> Optional[tarfile.TarInfo]:
            parties = Path(info.name).parts
            if len(parties) > 1 and parties[1] == "output":
                return None
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            return info

        with tarfile.open(archive, "w:gz") as tar:
            tar.add(dossier, arcname=identifiant, filter=sans_sorties)
        entree = dict(entrees[identifiant])
        entree.pop("last_accessed", None)
        index["espaces"].append(entree)
    (sortie / "index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(arguments: Optional[Sequence[str]] = None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    analyseur.add_argument("--api", default="http://127.0.0.1:8000")
    analyseur.add_argument("--racine", default=str(KOVEX),
                           help="dossier de Kovex ; kovex/ par défaut")
    analyseur.add_argument("--secteurs", nargs="*", default=None,
                           help="fiches à construire ; toutes par défaut")
    analyseur.add_argument("--sortie", default=str(ICI / "instantane"))
    analyseur.add_argument("--utilisateur", default="",
                           help="compte Kovex ; vide si l'authentification est désactivée")
    options = analyseur.parse_args(arguments)

    racine = Path(options.racine).resolve()
    generateur = charger("generer_secteur", ICI / "generer_secteur.py")
    fiches = [Path(f) for f in options.secteurs] if options.secteurs else \
        sorted((ICI / "secteurs").glob("*.json"))
    kovex = Kovex(options.api)
    if options.utilisateur:
        kovex.connecter(options.utilisateur,
                        getpass.getpass("Mot de passe de %s : " % options.utilisateur))

    construits: List[str] = []
    for chemin in fiches:
        fiche = generateur.lire_la_fiche(chemin)
        debut = time.monotonic()
        identifiant = creer_l_espace(kovex, generateur, racine, fiche,
                                     ENVIRONNEMENT, fiche["espace"])
        compte = gouverner(kovex, racine / "workspaces" / identifiant, identifiant, fiche)
        compte.update(conserver_les_minings(kovex, fiche))
        construits.append(identifiant)
        print("%s — %s (%.0f s)" % (identifiant, fiche["libelle"], time.monotonic() - debut))
        for cle, valeur in compte.items():
            print("  %-30s %s" % (cle, valeur))
        sys.stdout.flush()

    # L'espace brut de l'atelier : la fiche d'assurance, rien de décidé.
    assurance = generateur.lire_la_fiche(ICI / "secteurs" / "assurance.json")
    brut = creer_l_espace(kovex, generateur, racine, assurance,
                          ENVIRONNEMENT_BRUT, LIBELLE_BRUT)
    construits.append(brut)

    figer(racine, construits, Path(options.sortie))
    # Chaque espace aux couleurs et au logo de son client fictif.
    from habiller import habiller
    habiller(Path(options.sortie))
    print("Instantané écrit dans %s : %s" % (options.sortie, ", ".join(construits)))
    return 0


if __name__ == "__main__":  # pragma: no cover - point d'entrée
    raise SystemExit(main())
