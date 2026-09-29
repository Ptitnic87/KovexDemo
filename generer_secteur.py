#!/usr/bin/env python3
# Fichier : generer_secteur.py
"""Référentiel de démonstration d'un secteur : identités inventées, cas plantés.

Une démonstration ne se joue pas sur des données de client. Un référentiel
*aléatoire* ne convient pas non plus : il ne produit ni beaux rôles, ni couples
de séparation des tâches, ni mobilité lisible, et l'écran filmé ne montre rien.

Ce générateur écrit un référentiel dont **chaque écran a de quoi parler**. Les
cas ne sont pas espérés, ils sont plantés, puis recomptés par `verifier`. Tout
ce qui fait un secteur — organisation, applications, convention de nommage,
couples de séparation, droit tronqué, mobilité — est lu dans une **fiche**
(`secteurs/<secteur>.json`) ; aucune valeur de décor n'est écrite ici.

    python generer_secteur.py --secteur secteurs/sante.json \\
        --sortie kovex/workspaces/Demo_SANTE

Déterministe : même fiche, même référentiel, au fichier près. La fiche
d'assurance reproduit à l'octet près le référentiel de l'atelier des Assises.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Set, Tuple


class FicheInvalide(ValueError):
    """Une fiche de secteur qui ne permet pas de planter les cas."""


#: Les rubriques qu'une fiche doit porter. Une rubrique manquante se dit au
#: chargement plutôt qu'au milieu d'une génération de plusieurs minutes.
RUBRIQUES = (
    "identifiant", "libelle", "volumes", "sites", "organisation", "applications",
    "socle_application", "domaines_traine", "convention", "prenoms", "noms",
    "contrats", "socles", "part_socle", "populations", "privileges",
    "troncature", "couples_separes", "manquants_min", "couple_enfreint",
    "croisement", "mobilite", "usage", "bornes",
)


def lire_la_fiche(chemin: Path) -> Dict[str, Any]:
    fiche = json.loads(Path(chemin).read_text(encoding="utf-8"))
    manquantes = [r for r in RUBRIQUES if r not in fiche]
    if manquantes:
        raise FicheInvalide("rubriques absentes de %s : %s" % (chemin, ", ".join(manquantes)))
    fonctions = {f for liste in fiche["organisation"].values() for f in liste}
    for cle in ("origine", "arrivee"):
        if fiche["mobilite"][cle] not in fonctions:
            raise FicheInvalide("mobilité : fonction inconnue %r" % fiche["mobilite"][cle])
    if fiche["couple_enfreint"]["fonction"] not in fonctions:
        raise FicheInvalide("couple enfreint : fonction inconnue %r"
                            % fiche["couple_enfreint"]["fonction"])
    departements = set(fiche["organisation"])
    references = (list(fiche["troncature"]["departements_eligibles"])
                  + list(fiche["privileges"]["departements"])
                  + [fiche["couple_enfreint"]["departement_isoles"]]
                  + [d for cote in fiche["couple_enfreint"]["cotes"] for d in cote]
                  + [d for couple in fiche["couples_separes"] for d in couple[2] + couple[3]])
    inconnus = sorted(set(references) - departements)
    if inconnus:
        raise FicheInvalide("départements inconnus : %s" % ", ".join(inconnus))
    return fiche


class Generateur:
    """Construit le référentiel d'un secteur, puis se relit."""

    def __init__(self, fiche: Mapping[str, Any]) -> None:
        self.f = fiche
        volumes = fiche["volumes"]
        self.alea = random.Random(int(volumes["graine"]))
        self.cible_identites = int(volumes["identites"])
        self.cible_droits = int(volumes["droits"])
        self.cible_applications = int(volumes["applications"])
        self.socles = [tuple(s) for s in fiche["socles"]]
        self.nommees = [tuple(a) for a in fiche["applications"]]
        self.traine: List[str] = []
        self.identites: List[Dict[str, str]] = []
        self.applications: List[Dict[str, str]] = []
        self.droits: List[Dict[str, str]] = []
        self.habilitations: Set[Tuple[str, str]] = set()
        self.populations: List[Dict[str, object]] = []

    # -- référentiels ------------------------------------------------------

    def construire_applications(self) -> None:
        """Les applications nommées, plus une longue traîne sans nom métier."""
        for code, nom, domaine in self.nommees:
            self.applications.append(
                {"ID_application": code, "nom": nom, "domaine": domaine})
        code, nom, domaine = self.f["socle_application"]
        self.applications.append({"ID_application": code, "nom": nom, "domaine": domaine})

        consonnes = "BCDFGHJKLMNPQRSTVXZ"
        nommees = {a["ID_application"] for a in self.applications}
        domaines = list(self.f["domaines_traine"])
        while len(self.applications) < self.cible_applications:
            code = "".join(self.alea.choice(consonnes) for _ in range(3))
            if code in nommees:
                continue
            nommees.add(code)
            self.applications.append({
                "ID_application": code,
                "nom": "Application " + code,
                "domaine": self.alea.choice(domaines),
            })
        self.traine = sorted(nommees - {c for c, _, _ in self.nommees}
                             - {self.f["socle_application"][0]})

    def construire_droits(self) -> None:
        """Les droits, dont la plupart respectent la convention de nommage."""
        vus: Set[str] = set()
        codes = [code for code, _, _ in self.nommees]
        reserves: Set[str] = set()
        for gauche, droite, _, _, _ in self.f["couples_separes"]:
            reserves.update((gauche, droite))
        reserves.update(self.f["couple_enfreint"]["droits"])
        reserves.update(self.f["croisement"]["droits"])
        reserves.add(self.f["troncature"]["droit"])
        connues = {a["ID_application"] for a in self.applications}

        def ajouter(identifiant: str, libelle: str) -> None:
            if identifiant in vus:
                return
            vus.add(identifiant)
            application = identifiant.split("_")[0] if "_" in identifiant else ""
            self.droits.append({
                "ID_droit": identifiant,
                "ID_application": application if application in connues else "",
                "libelle": libelle,
            })

        for identifiant, libelle in self.socles:
            ajouter(identifiant, libelle)
        for identifiant in sorted(reserves):
            ajouter(identifiant, "Droit métier " + identifiant.split("_")[-1].lower())

        convention = self.f["convention"]
        populations = self.f["populations"]
        tirage = codes * int(populations["poids_nommees"]) + list(self.traine)
        conformes = int(self.cible_droits * float(populations["part_conformes"]))
        while len(vus) < conformes:
            code = self.alea.choice(tirage)
            identifiant = "_".join((code, self.alea.choice(convention["modules"]),
                                    self.alea.choice(convention["actions"]),
                                    self.alea.choice(convention["objets"])))
            if identifiant in vus:
                identifiant += "_%d" % self.alea.randint(2, 99)
            ajouter(identifiant, "Droit " + code)

        while len(vus) < self.cible_droits:
            forme = self.alea.choice([
                "GRP-legacy-%05d", "AD.Groupe.%05d", "old%05d", "ACL_%05d_RW",
            ])
            ajouter(forme % self.alea.randint(1, 99999), "Groupe hérité")

    # -- populations -------------------------------------------------------

    def construire_populations(self) -> None:
        """Des populations serrées, le reste plus lâche : c'est l'arbitrage."""
        reglage = self.f["populations"]
        metiers = [(dept, fonction)
                   for dept, fonctions in self.f["organisation"].items()
                   for fonction in fonctions]
        self.alea.shuffle(metiers)
        socles = dict(self.socles)
        catalogue = [d["ID_droit"] for d in self.droits
                     if d["ID_droit"] not in socles and "_" in d["ID_droit"]]

        for rang, (dept, fonction) in enumerate(metiers):
            serree = rang < int(reglage["serrees"])
            bornes = reglage["poids_serrees"] if serree else reglage["poids_laches"]
            poids = self.alea.randint(int(bornes[0]), int(bornes[1]))
            nombre = self.alea.randint(*[int(x) for x in reglage["droits_par_population"]])
            self.populations.append({
                "departement": dept, "fonction": fonction, "poids": poids,
                "droits": self.alea.sample(catalogue, nombre),
                "adherence": float(reglage["adherence_serree"] if serree
                                   else reglage["adherence_lache"]),
                "serree": serree,
            })

        total = sum(int(p["poids"]) for p in self.populations)
        vise = int(self.cible_identites / (1 + float(self.f["privileges"]["part"])))
        reste = vise
        for rang, population in enumerate(self.populations):
            if rang == len(self.populations) - 1:
                population["taille"] = max(20, reste)
            else:
                taille = max(20, round(int(population["poids"]) * vise / total))
                population["taille"] = taille
                reste -= taille

    def construire_identites(self) -> None:
        contrats = [valeur for valeur, _ in self.f["contrats"]]
        poids = [part for _, part in self.f["contrats"]]
        numero = 10000
        for population in self.populations:
            membres: List[str] = []
            for _ in range(int(population["taille"])):
                numero += 1
                identifiant = "U%06d" % numero
                self.identites.append({
                    "ID_utilisateur": identifiant,
                    "prenom": self.alea.choice(self.f["prenoms"]),
                    "nom": self.alea.choice(self.f["noms"]),
                    "departement": str(population["departement"]),
                    "fonction": str(population["fonction"]),
                    "type_contrat": self.alea.choices(contrats, weights=poids)[0],
                    "site": self.alea.choice(self.f["sites"]),
                })
                membres.append(identifiant)
            population["membres"] = membres

    def construire_comptes_a_privileges(self) -> None:
        """Le compte d'administration d'une personne, à côté du nominatif."""
        reglage = self.f["privileges"]
        nominatifs = [i for i in self.identites
                      if i["departement"] in reglage["departements"]]
        combien = max(1, int(len(self.identites) * float(reglage["part"])))
        choisis = self.alea.sample(nominatifs, min(combien, len(nominatifs)))
        prefixes = tuple(reglage["prefixes_droits"])
        for source in choisis:
            self.identites.append(dict(
                source, ID_utilisateur=source["ID_utilisateur"] + reglage["suffixe"]))
            self.identites[-1].pop("derniere_connexion", None)
            for droit in self.alea.sample(
                    [d["ID_droit"] for d in self.droits if d["ID_droit"].startswith(prefixes)],
                    self.alea.randint(*[int(x) for x in reglage["droits"]])):
                self.habilitations.add((source["ID_utilisateur"] + reglage["suffixe"], droit))

    # -- habilitations -----------------------------------------------------

    def attribuer(self) -> None:
        reglage = self.f["populations"]
        tous = [i["ID_utilisateur"] for i in self.identites]
        for identifiant in tous:
            for droit, _ in self.socles:
                if self.alea.random() < float(self.f["part_socle"]):
                    self.habilitations.add((identifiant, droit))

        catalogue = [d["ID_droit"] for d in self.droits if "_" in d["ID_droit"]]
        extras = [int(x) for x in reglage["extras"]]
        for population in self.populations:
            adherence = float(population["adherence"])
            for membre in population["membres"]:  # type: ignore[index]
                for droit in population["droits"]:  # type: ignore[index]
                    if self.alea.random() < adherence:
                        self.habilitations.add((membre, droit))
                if self.alea.random() < float(reglage["part_avec_extras"]):
                    for _ in range(self.alea.randint(*extras)):
                        self.habilitations.add((membre, self.alea.choice(catalogue)))

    # -- les cas plantés ---------------------------------------------------

    def planter_le_croisement(self) -> None:
        """Le terrain commun à deux populations, qu'aucun autre générateur ne trouve.

        Un groupe dont chaque membre porte les droits communs plus un droit qui
        n'est qu'à lui, et un groupe témoin par droit commun : seul le
        croisement de deux profils rend les droits communs ensemble.
        """
        reglage = self.f["croisement"]
        communs = list(reglage["droits"])
        taille_groupe = int(reglage["groupe"])
        tous = sorted(i["ID_utilisateur"] for i in self.identites)
        groupe = tous[:taille_groupe]
        temoins = tous[taille_groupe:taille_groupe + int(reglage["temoins"])]

        socles = {identifiant for identifiant, _ in self.socles}
        for identifiant in groupe:
            for droit in [d for u, d in self.habilitations
                          if u == identifiant and d not in socles]:
                self.habilitations.discard((identifiant, droit))

        detenus = {droit for _, droit in self.habilitations}
        propres = [d["ID_droit"] for d in self.droits
                   if d["ID_droit"] not in detenus and "_" in d["ID_droit"]]
        if len(propres) < len(groupe):
            raise SystemExit(
                "pas assez de droits inutilisés (%d) pour donner une signature "
                "unique aux %d membres du croisement" % (len(propres), len(groupe)))
        propres = propres[:len(groupe)]
        for rang, identifiant in enumerate(groupe):
            for droit in communs:
                self.habilitations.add((identifiant, droit))
            self.habilitations.add((identifiant, propres[rang]))

        taille = len(temoins) // len(communs)
        for rang, droit in enumerate(communs):
            for identifiant in temoins[rang * taille:(rang + 1) * taille]:
                self.habilitations.add((identifiant, droit))
                for autre in communs:
                    if autre != droit:
                        self.habilitations.discard((identifiant, autre))
        self.croisement_groupe = groupe

    def planter_la_separation(self) -> None:
        """Des couples que personne ne réunit, et un qu'une population réunit."""
        par_departement: Dict[str, List[str]] = defaultdict(list)
        for identite in self.identites:
            par_departement[identite["departement"]].append(identite["ID_utilisateur"])

        for gauche, droite, departements_g, departements_d, combien in self.f["couples_separes"]:
            pool_g = [u for d in departements_g for u in par_departement[d]]
            pool_d = [u for d in departements_d for u in par_departement[d]]
            communs = set(pool_g) & set(pool_d)
            if communs:
                raise SystemExit(
                    "les deux côtés du couple %s / %s partagent %d identités"
                    % (gauche, droite, len(communs)))
            for identifiant in self.alea.sample(pool_g, min(combien, len(pool_g))):
                self.habilitations.add((identifiant, gauche))
            for identifiant in self.alea.sample(pool_d, min(combien, len(pool_d))):
                self.habilitations.add((identifiant, droite))
            porteurs_g = {u for u, d in self.habilitations if d == gauche}
            for identifiant in sorted(porteurs_g):
                self.habilitations.discard((identifiant, droite))

        reglage = self.f["couple_enfreint"]
        gauche, droite = reglage["droits"]
        population = next(p for p in self.populations
                          if p["fonction"] == reglage["fonction"])
        groupe = list(population["membres"])[:int(reglage["par_role"])]  # type: ignore[arg-type]
        for identifiant in groupe:
            self.habilitations.add((identifiant, gauche))
            self.habilitations.add((identifiant, droite))
        autres = [i["ID_utilisateur"] for i in self.identites
                  if i["ID_utilisateur"] not in groupe
                  and i["departement"] == reglage["departement_isoles"]]
        for identifiant in self.alea.sample(autres, int(reglage["isoles"])):
            self.habilitations.add((identifiant, gauche))
            self.habilitations.add((identifiant, droite))

        for cote, departements in zip((gauche, droite), reglage["cotes"]):
            pool = [u for d in departements for u in par_departement[d]]
            for identifiant in self.alea.sample(
                    pool, min(int(reglage["porteurs_cotes"]), len(pool))):
                if identifiant not in groupe:
                    self.habilitations.add((identifiant, cote))
        self.enfreint_groupe = groupe

    def planter_la_troncature(self) -> None:
        """Un droit dont le compte tombe pile sur une borne d'export."""
        reglage = self.f["troncature"]
        droit, borne = reglage["droit"], int(reglage["porteurs"])
        eligibles = [i["ID_utilisateur"] for i in self.identites
                     if i["departement"] in reglage["departements_eligibles"]]
        if len(eligibles) <= borne:
            raise SystemExit(
                "population éligible (%d) trop petite pour que la borne de %d "
                "se lise comme une troncature" % (len(eligibles), borne))
        for identite in self.identites:
            self.habilitations.discard((identite["ID_utilisateur"], droit))
        for identifiant in sorted(eligibles)[:borne]:
            self.habilitations.add((identifiant, droit))
        self.eligibles_tronque = len(eligibles)

    def ecarter_les_bornes_fortuites(self) -> None:
        """Décale les comptes qui tombent sur une borne d'export par accident."""
        bornes = {int(b) for b in self.f["bornes"]}
        droit_tronque = self.f["troncature"]["droit"]
        comptes: Counter = Counter(droit for _, droit in self.habilitations)
        tous = sorted(i["ID_utilisateur"] for i in self.identites)
        for droit, compte in sorted(comptes.items()):
            if droit == droit_tronque or compte not in bornes:
                continue
            porteurs = {u for u, d in self.habilitations if d == droit}
            for identifiant in tous:
                if identifiant not in porteurs:
                    self.habilitations.add((identifiant, droit))
                    break

    def planter_les_mobilites(self) -> None:
        """Des personnes dont les droits disent l'ancien poste."""
        reglage = self.f["mobilite"]
        origine = next(p for p in self.populations if p["fonction"] == reglage["origine"])
        arrivee = next(p for p in self.populations if p["fonction"] == reglage["arrivee"])
        deplaces = list(arrivee["membres"])[:int(reglage["nombre"])]  # type: ignore[arg-type]
        for identifiant in deplaces:
            for droit in origine["droits"]:  # type: ignore[index]
                self.habilitations.add((identifiant, droit))
        self.mobilites = deplaces

    def planter_l_usage(self) -> None:
        """Dates de dernier usage et de dernière connexion, sur un aléa séparé."""
        reglage = self.f["usage"]
        date_export = date.fromisoformat(reglage["date_export"])
        seuil = int(reglage["seuil_jours"])
        alea = random.Random(int(self.f["volumes"]["graine"]) + 1)
        socles = {d for d, _ in self.socles}
        application_du_droit = {d["ID_droit"]: d["ID_application"] for d in self.droits}
        porteurs: Counter = Counter(application_du_droit.get(d, "")
                                    for _, d in self.habilitations)
        self.application_eteinte = max(self.traine, key=lambda a: (porteurs[a], a))

        suffixe = self.f["privileges"]["suffixe"]
        candidates = sorted(i["ID_utilisateur"] for i in self.identites
                            if not i["ID_utilisateur"].endswith(suffixe))
        self.identites_eteintes = set(alea.sample(candidates, int(reglage["identites_eteintes"])))

        def il_y_a(jours_min: int, jours_max: int) -> str:
            return (date_export - timedelta(days=alea.randint(jours_min, jours_max))
                    ).strftime("%d/%m/%Y")

        self.derniere_utilisation: Dict[Tuple[str, str], str] = {}
        self.dormantes_isolees = 0
        part = float(reglage["part_dormantes"])
        for utilisateur, droit in sorted(self.habilitations):
            if droit in socles:
                jours = (0, 7)
            elif utilisateur in self.identites_eteintes:
                jours = (seuil + 20, 700)
            elif application_du_droit.get(droit) == self.application_eteinte:
                jours = (seuil + 200, 900)
            elif alea.random() < part:
                jours = (seuil + 20, 700)
                self.dormantes_isolees += 1
            else:
                jours = (0, 60)
            self.derniere_utilisation[(utilisateur, droit)] = il_y_a(*jours)

        for identite in self.identites:
            identite["derniere_connexion"] = (
                il_y_a(seuil + 20, 700)
                if identite["ID_utilisateur"] in self.identites_eteintes
                else il_y_a(0, 14))

    # -- écriture ----------------------------------------------------------

    def ecrire(self, dossier: Path) -> None:
        donnees = dossier / "data"
        donnees.mkdir(parents=True, exist_ok=True)

        def csv_ecrire(nom: str, colonnes: Sequence[str], lignes) -> None:
            with open(donnees / nom, "w", encoding="utf-8", newline="") as flux:
                graveur = csv.DictWriter(flux, fieldnames=list(colonnes), delimiter=";")
                graveur.writeheader()
                for ligne in lignes:
                    graveur.writerow(ligne)

        csv_ecrire("identities.csv",
                   ["ID_utilisateur", "prenom", "nom", "departement", "fonction",
                    "type_contrat", "site", "derniere_connexion"],
                   sorted(self.identites, key=lambda i: i["ID_utilisateur"]))
        csv_ecrire("applications.csv", ["ID_application", "nom", "domaine"],
                   sorted(self.applications, key=lambda a: a["ID_application"]))
        csv_ecrire("droits.csv", ["ID_droit", "ID_application", "libelle"],
                   sorted(self.droits, key=lambda d: d["ID_droit"]))
        csv_ecrire("habilitations.csv",
                   ["ID_utilisateur", "ID_droit", "derniere_utilisation"],
                   [{"ID_utilisateur": u, "ID_droit": d,
                     "derniere_utilisation": self.derniere_utilisation[(u, d)]}
                    for u, d in sorted(self.habilitations)])

        base = "workspaces/" + dossier.name
        configuration = {
            "files": {
                "identities": {"path": base + "/data/identities.csv",
                               "delimiter": ";", "encoding": "utf-8",
                               "id_column": "ID_utilisateur"},
                "applications": {"path": base + "/data/applications.csv",
                                 "delimiter": ";", "encoding": "utf-8",
                                 "id_column": "ID_application"},
                "rights": {"path": base + "/data/droits.csv",
                           "delimiter": ";", "encoding": "utf-8",
                           "id_column": "ID_droit",
                           "app_id_column": "ID_application"},
                "habs": {"path": base + "/data/habilitations.csv",
                         "delimiter": ";", "encoding": "utf-8",
                         "user_id_column": "ID_utilisateur",
                         "right_id_column": "ID_droit"},
            },
            "mining_min_users": 5,
            "mining_min_rights": 3,
            "right_naming_column": "",
            "right_naming_separator": "_",
            "right_naming_positions": ["application", "module", "action", "objet"],
            "privileged_account_keywords": [self.f["privileges"]["suffixe"].strip(".")],
            "privileged_account_column": "",
            "privileged_account_place": "jeton",
        }
        (dossier / "config.json").write_text(
            json.dumps(configuration, indent=4, ensure_ascii=False), encoding="utf-8")

    # -- relecture ---------------------------------------------------------

    def verifier(self) -> List[Tuple[str, bool, str]]:
        """Recompte chaque cas planté. Un générateur qui ne se relit pas ment."""
        par_droit: Counter = Counter()
        par_identite: Dict[str, Set[str]] = defaultdict(set)
        for utilisateur, droit in self.habilitations:
            par_droit[droit] += 1
            par_identite[utilisateur].add(droit)

        constats: List[Tuple[str, bool, str]] = []

        def constat(nom: str, tenu: bool, detail: str) -> None:
            constats.append((nom, tenu, detail))

        effectif = len(self.identites)
        socles = [d for d, _ in self.socles if par_droit[d] >= effectif * 0.95]
        constat("Droits socles (> 95 %)", len(socles) == len(self.socles),
                "%d sur %d" % (len(socles), len(self.socles)))

        droit_tronque = self.f["troncature"]["droit"]
        borne = int(self.f["troncature"]["porteurs"])
        constat("Droit tronqué à %d pile" % borne, par_droit[droit_tronque] == borne,
                "%s : %d porteurs pour %d éligibles"
                % (droit_tronque, par_droit[droit_tronque],
                   getattr(self, "eligibles_tronque", 0)))

        bornes = {int(b) for b in self.f["bornes"]}
        ronds = [d for d, n in par_droit.items() if n in bornes and d != droit_tronque]
        constat("Aucun autre compte sur une borne", not ronds,
                "sinon : %s" % ", ".join(sorted(ronds)[:4]))

        for gauche, droite, _, _, _ in self.f["couples_separes"]:
            ensemble = sum(1 for droits in par_identite.values()
                           if gauche in droits and droite in droits)
            manquants = par_droit[gauche] * par_droit[droite] / effectif - ensemble
            constat("Couple séparé %s / %s" % (gauche, droite),
                    ensemble == 0 and manquants > float(self.f["manquants_min"]),
                    "%d et %d porteurs, %d les deux, %d cumuls manquants"
                    % (par_droit[gauche], par_droit[droite], ensemble, manquants))

        reglage = self.f["couple_enfreint"]
        gauche, droite = reglage["droits"]
        enfreignent = [u for u, droits in par_identite.items()
                       if gauche in droits and droite in droits]
        attendu = int(reglage["par_role"]) + int(reglage["isoles"])
        constat("Couple enfreint par ~%d identités" % attendu,
                int(reglage["par_role"]) <= len(enfreignent) <= int(reglage["par_role"]) + 20,
                "%d identités" % len(enfreignent))

        croisement = self.f["croisement"]
        minimum = int(croisement["minimum_verifie"])
        communs = [u for u, droits in par_identite.items()
                   if all(d in droits for d in croisement["droits"])]
        signatures_communes = len({frozenset(par_identite[u]) for u in communs})
        temoins = {droit: [u for u, droits in par_identite.items()
                           if droit in droits
                           and not all(d in droits for d in croisement["droits"])]
                   for droit in croisement["droits"]}
        constat("Terrain commun : groupe aux signatures uniques",
                len(communs) > minimum and signatures_communes == len(communs),
                "%d portent les %d, %d signatures distinctes"
                % (len(communs), len(croisement["droits"]), signatures_communes))
        constat("Terrain commun : un témoin par droit",
                all(len(v) > minimum for v in temoins.values()),
                ", ".join("%s=%d" % (k.split("_")[0], len(v))
                          for k, v in sorted(temoins.items())))

        contrats = Counter(i["type_contrat"] for i in self.identites)
        constat("Valeurs de contrat à rapprocher", len(contrats) >= 8,
                "%d écritures distinctes" % len(contrats))

        conformes = sum(1 for d in self.droits if d["ID_droit"].count("_") >= 3)
        part = 100.0 * conformes / len(self.droits)
        constat("Convention tenue par la plupart des droits", 85 <= part <= 95,
                "%.1f %%" % part)

        suffixe = self.f["privileges"]["suffixe"]
        adm = [i for i in self.identites if i["ID_utilisateur"].endswith(suffixe)]
        constat("Comptes à privilèges",
                len(adm) > int(self.f["privileges"]["minimum_verifie"]),
                "%d comptes %s" % (len(adm), suffixe))

        nombre = int(self.f["mobilite"]["nombre"])
        constat("Mobilités plantées", len(getattr(self, "mobilites", [])) == nombre,
                "%d identités" % len(getattr(self, "mobilites", [])))

        usage = self.f["usage"]
        date_export = date.fromisoformat(usage["date_export"])
        seuil = int(usage["seuil_jours"])

        def dormant(texte: str) -> bool:
            jour, mois, annee = (int(x) for x in texte.split("/"))
            return (date_export - date(annee, mois, jour)).days > seuil

        application_du_droit = {d["ID_droit"]: d["ID_application"] for d in self.droits}
        eteinte = [cle for cle in self.habilitations
                   if application_du_droit.get(cle[1]) == self.application_eteinte]
        constat("Application éteinte (%s)" % self.application_eteinte,
                bool(eteinte) and all(dormant(self.derniere_utilisation[c]) for c in eteinte),
                "%d habilitations, toutes au-delà de %d jours" % (len(eteinte), seuil))
        constat("Droits dormants isolés",
                self.dormantes_isolees > int(usage["dormantes_min"]),
                "%d habilitations" % self.dormantes_isolees)
        eteintes = [i for i in self.identites if dormant(i["derniere_connexion"])]
        constat("Identités qui ne se connectent plus",
                len(eteintes) == int(usage["identites_eteintes"]),
                "%d identités" % len(eteintes))

        signatures = len({frozenset(d) for d in par_identite.values()})
        part_distinctes = 100.0 * signatures / max(1, len(par_identite))
        constat("Signatures distinctes (réalisme)", 40 <= part_distinctes <= 90,
                "%.1f %% — un référentiel réel est autour de 70 %%" % part_distinctes)
        return constats


def generer(fiche: Mapping[str, Any]) -> Generateur:
    """Construit le référentiel dans l'ordre qui garde les comptes exacts."""
    generateur = Generateur(fiche)
    generateur.construire_applications()
    generateur.construire_droits()
    generateur.construire_populations()
    generateur.construire_identites()
    generateur.attribuer()
    generateur.planter_le_croisement()
    generateur.planter_la_separation()
    generateur.planter_les_mobilites()
    generateur.construire_comptes_a_privileges()
    # Les deux dernières passes touchent des comptes exacts : toute attribution
    # postérieure les ferait glisser.
    generateur.ecarter_les_bornes_fortuites()
    generateur.planter_la_troncature()
    # En dernier, et sur son propre aléa : les dates ne changent aucune
    # habilitation.
    generateur.planter_l_usage()
    return generateur


def main(arguments=None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    analyseur.add_argument("--secteur", required=True, help="fiche du secteur (JSON)")
    analyseur.add_argument("--sortie", required=True, help="dossier du workspace à écrire")
    options = analyseur.parse_args(arguments)

    generateur = generer(lire_la_fiche(Path(options.secteur)))
    dossier = Path(options.sortie)
    generateur.ecrire(dossier)

    print("Référentiel « %s » écrit dans %s" % (generateur.f["libelle"], dossier))
    print("  %6d identités   %6d droits   %6d applications   %6d habilitations"
          % (len(generateur.identites), len(generateur.droits),
             len(generateur.applications), len(generateur.habilitations)))
    manques = 0
    for nom, tenu, detail in generateur.verifier():
        print("  %s  %-44s %s" % ("OK  " if tenu else "RATÉ", nom, detail))
        manques += 0 if tenu else 1
    if manques:
        print("%d cas non plantés : la démonstration aurait des écrans vides." % manques,
              file=sys.stderr)
        return 1
    print("Tous les cas sont plantés.")
    return 0


if __name__ == "__main__":  # pragma: no cover - point d'entrée
    raise SystemExit(main())
