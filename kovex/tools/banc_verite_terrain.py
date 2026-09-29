#!/usr/bin/env python3
"""Banc de mesure du mining : restitution de rôles connus, et jeux publics.

Deux modes, tous deux hors ligne :

``synthetique``
    Génère des référentiels dont les rôles sont décidés à l'avance, les dégrade
    avec du bruit, et mesure ce que le moteur retrouve. C'est la mesure de
    justesse : rappel, précision et reconstitution des populations.

``public``
    Rejoue un jeu de données public au format matriciel (un fichier ``UPA.txt``
    par jeu : une ligne par utilisateur, une colonne par droit, 0/1 séparés par
    des espaces). Le jeu doit être présent sur le poste : le banc ne télécharge
    rien. Il mesure le nombre de rôles nécessaires pour couvrir 100 % des
    habilitations sans aucun sur-octroi, ce qui est directement comparable aux
    résultats publiés sur ces jeux.

    ``--format paires`` lit le format « une habilitation par ligne » des jeux
    HP distribués par ConstrainedRM (MIT). ``--references`` donne les nombres
    de rôles publiés, et le banc écrit l'écart — le seul chiffre opposable :
    « N rôles contre un optimum de M ».

Aucune valeur n'est figée : toutes les dimensions, tous les seuils et tous les
chemins sont des arguments.

Exemples :
    python tools/banc_verite_terrain.py synthetique --seuils 1.0 0.9 0.8 0.7
    python tools/banc_verite_terrain.py public --racine /chemin/vers/jeux
    python tools/banc_verite_terrain.py public --racine ConstrainedRM/datasets/realWorld \
        --motif "*.txt" --format paires --selection exacte \
        --references tools/references/hp_optima.json
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.data.loader import create_data_loader  # noqa: E402
from src.core.mining.approximate_miner import (GENERATEURS,  # noqa: E402
                                               GENERATEURS_PAR_DEFAUT,
                                               TREILLIS_MAX,
                                               ApproximateRoleMiner)
from src.core.mining.selection_exacte import (DELAI_PAR_DEFAUT_S, EFFORT_PAR_DEFAUT,  # noqa: E402
                                              SELECTION_PAR_DEFAUT, SELECTIONS)
from src.core.role.miner import RoleMinerEngine  # noqa: E402
from tests.rbac_verite_terrain import apparier, generer_referentiel  # noqa: E402


def _charger(racine: Path, config: Dict):
    """Instancie le DataLoader ; ses chemins sont relatifs à la racine du workspace."""
    precedent = os.getcwd()
    os.chdir(racine)
    try:
        return create_data_loader(config)
    finally:
        os.chdir(precedent)


# ------------------------------------------------------------------ synthétique


def executer_synthetique(arguments) -> List[Dict]:
    lignes: List[Dict] = []
    for omission, exception in zip(arguments.omissions, arguments.exceptions):
        racine = Path(tempfile.mkdtemp(prefix="banc_"))
        referentiel = generer_referentiel(
            racine,
            nb_utilisateurs=arguments.utilisateurs,
            nb_droits=arguments.droits,
            nb_roles=arguments.roles,
            taille_role=(arguments.taille_role_min, arguments.taille_role_max),
            roles_par_utilisateur=(arguments.roles_par_utilisateur_min, arguments.roles_par_utilisateur_max),
            taux_omission=omission,
            taux_exception=exception,
            graine=arguments.graine,
            nom_colonne_utilisateur=arguments.colonne_utilisateur,
            nom_colonne_droit=arguments.colonne_droit,
            nom_colonne_application=arguments.colonne_application,
        )
        loader = _charger(racine, referentiel.config)

        moteur = RoleMinerEngine(loader)
        moteur.min_users, moteur.min_rights = arguments.min_utilisateurs, arguments.min_droits
        mesure = apparier(referentiel.roles_verite, moteur.mine_roles_exact([]))
        mesure.pop("detail")
        lignes.append({"bruit": referentiel.taux_bruit_reel, "mode": "EXACT", **mesure})

        for seuil in arguments.seuils:
            debut = time.perf_counter()
            resultat = ApproximateRoleMiner(loader).mine(
                similarity_threshold=seuil,
                min_users=arguments.min_utilisateurs,
                min_rights=arguments.min_droits,
                excluded_rights=[],
                max_roles=arguments.max_roles,
                generateurs=arguments.generateurs,
                treillis_max=arguments.treillis_max,
            )
            duree = time.perf_counter() - debut
            roles = resultat["roles"]
            mesure = apparier(referentiel.roles_verite, roles)
            mesure.pop("detail")
            tete = apparier(referentiel.roles_verite, roles[: arguments.roles])
            tete.pop("detail")
            lignes.append({
                "bruit": referentiel.taux_bruit_reel,
                "mode": f"APPROX@{seuil}",
                **mesure,
                "rappel_droits_tete": tete["rappel_droits"],
                "precision_droits_tete": tete["precision_droits"],
                "couverture_pct": resultat["stats"]["coverage_pct"],
                "sur_octroi_pct": resultat["stats"]["over_granted_pct"],
                "secondes": round(duree, 3),
            })
    return lignes


# ----------------------------------------------------------------------- public


def _lire_paires(chemin: Path) -> List[List[int]]:
    """Un jeu au format « une habilitation par ligne » : `utilisateur droit`.

    C'est le format des jeux HP tels que les distribue ConstrainedRM
    (`datasets/realWorld/*.txt`). Les identifiants sont renumérotés d'un seul
    tenant, dans l'ordre croissant : le jeu garde ses dimensions exactes, et
    une ligne répétée ne compte qu'une fois.
    """
    paires = set()
    for numero, ligne in enumerate(chemin.read_text().splitlines(), start=1):
        champs = ligne.split()
        if not champs:
            continue
        if len(champs) != 2:
            raise ValueError(f"{chemin}:{numero} : deux entiers attendus, lu « {ligne.strip()} »")
        paires.add((int(champs[0]), int(champs[1])))
    if not paires:
        raise ValueError(f"{chemin} est vide")
    utilisateurs = {u: i for i, u in enumerate(sorted({u for u, _ in paires}))}
    droits = {d: j for j, d in enumerate(sorted({d for _, d in paires}))}
    matrice = [[0] * len(droits) for _ in utilisateurs]
    for utilisateur, droit in paires:
        matrice[utilisateurs[utilisateur]][droits[droit]] = 1
    return matrice


def _lire_references(chemin: Optional[str]) -> Dict[str, int]:
    """Les nombres de rôles publiés, par nom de jeu, s'ils sont fournis.

    Un fichier JSON `{"jeu": nombre}` — les valeurs viennent d'une
    publication, pas du produit, et le banc ne les invente pas : sans fichier,
    la colonne n'apparaît pas.
    """
    if not chemin:
        return {}
    references = json.loads(Path(chemin).expanduser().read_text(encoding="utf-8"))
    return {str(jeu): int(nombre) for jeu, nombre in references.get("optima", {}).items()}


def complexites(roles: Sequence[Dict]) -> Dict[str, int]:
    """La complexité structurelle d'un modèle, à plat et avec la hiérarchie.

    À plat : rôles + liens rôle→droit + liens identité→rôle. Avec la
    hiérarchie : droits propres, porteurs rattachés au seul rôle le plus
    large, et liens d'héritage — la WSC des publications.
    """
    from src.core.mining.role_quality import hierarchiser

    plat = len(roles) + sum(len(role["rights"]) for role in roles) \
        + sum(len(role["users"]) for role in roles)
    avec = hierarchiser([dict(role, id=str(rang)) for rang, role in enumerate(roles)])
    return {"wsc_plat": plat, "wsc_hierarchique": avec["stats"]["wsc_hierarchique"]}


def _lire_decomposition(chemin: Path) -> List[Dict]:
    """Une décomposition de référence de ConstrainedRM : blocs
    `role:` / `permissions:` / `users:`."""
    roles: List[Dict] = []
    courant: Dict = {}
    for ligne in chemin.read_text().splitlines():
        cle, _, valeur = ligne.partition(":")
        cle = cle.strip()
        elements = [element for element in valeur.replace(",", " ").split() if element]
        if cle == "role":
            courant = {"rights": [], "users": []}
            roles.append(courant)
        elif cle == "permissions" and courant is not None:
            courant["rights"] = elements
        elif cle == "users" and courant is not None:
            courant["users"] = elements
    return roles


def _meilleure_reference(repertoire: Optional[str], jeu: str) -> Dict:
    """La plus basse complexité hiérarchisée parmi les décompositions du jeu."""
    if not repertoire:
        return {}
    meilleure: Dict = {}
    for chemin in sorted(Path(repertoire).expanduser().glob(f"{jeu}_*.txt")):
        mesure = complexites(_lire_decomposition(chemin))
        if not meilleure or mesure["wsc_hierarchique"] < meilleure["reference_wsc_hierarchique"]:
            meilleure = {"reference": chemin.stem[len(jeu) + 1:],
                         "reference_wsc_hierarchique": mesure["wsc_hierarchique"]}
    return meilleure


def _lire_matrice(chemin: Path) -> List[List[int]]:
    matrice = [[int(valeur) for valeur in ligne.split()] for ligne in chemin.read_text().splitlines() if ligne.strip()]
    if not matrice:
        raise ValueError(f"{chemin} est vide")
    largeurs = {len(ligne) for ligne in matrice}
    if len(largeurs) != 1:
        raise ValueError(f"{chemin} : lignes de longueurs différentes {sorted(largeurs)}")
    return matrice


def _workspace_depuis_matrice(matrice, racine: Path, separateur: str) -> Dict:
    donnees = racine / "workspaces" / "BANC" / "data"
    donnees.mkdir(parents=True, exist_ok=True)
    (racine / "workspaces" / "BANC" / "output").mkdir(parents=True, exist_ok=True)
    (racine / "config").mkdir(parents=True, exist_ok=True)

    nb_droits = len(matrice[0])

    def ecrire(nom, entete, lignes):
        with open(donnees / nom, "w", newline="", encoding="utf-8") as flux:
            graveur = csv.writer(flux, delimiter=separateur)
            graveur.writerow(entete)
            graveur.writerows(lignes)

    ecrire("identites.csv", ["utilisateur"], [[f"U{i}"] for i in range(len(matrice))])
    ecrire("droits.csv", ["droit", "application"], [[f"P{j}", "A0"] for j in range(nb_droits)])
    ecrire("applications.csv", ["application"], [["A0"]])
    ecrire(
        "habilitations.csv",
        ["utilisateur", "droit"],
        [[f"U{i}", f"P{j}"] for i, ligne in enumerate(matrice) for j, valeur in enumerate(ligne) if valeur],
    )

    def fichier(chemin, **colonnes):
        return {
            "path": chemin, "delimiter": separateur, "encoding": "utf-8",
            "id_column": colonnes.get("id", ""), "app_id_column": colonnes.get("app", ""),
            "user_id_column": colonnes.get("utilisateur", ""), "right_id_column": colonnes.get("droit", ""),
        }

    base = "workspaces/BANC/data"
    config = {
        "files": {
            "identities": fichier(f"{base}/identites.csv", id="utilisateur"),
            "applications": fichier(f"{base}/applications.csv", id="application"),
            "rights": fichier(f"{base}/droits.csv", id="droit", app="application"),
            "habs": fichier(f"{base}/habilitations.csv", utilisateur="utilisateur", droit="droit"),
        },
        "mining_min_users": 1,
        "mining_min_rights": 1,
    }
    (racine / "workspaces" / "BANC" / "config.json").write_text(json.dumps(config, indent=4))
    (racine / "config" / "config.json").write_text(json.dumps(config, indent=4))
    (racine / "workspaces" / "workspaces.json").write_text(json.dumps({
        "version": "1.0", "active_workspace": "BANC",
        "workspaces": [{
            "id": "BANC", "name": "BANC", "client": "BANC", "environment": "TEST",
            "created_at": "2026-01-01T00:00:00", "last_accessed": "2026-01-01T00:00:00",
            "theme": "default", "data_stats": {},
        }],
    }, indent=4))
    return config


def executer_public(arguments) -> List[Dict]:
    racine_jeux = Path(arguments.racine).expanduser()
    if not racine_jeux.is_dir():
        raise SystemExit(f"Répertoire introuvable : {racine_jeux}")

    fichiers = sorted(racine_jeux.rglob(arguments.motif))
    if not fichiers:
        raise SystemExit(f"Aucun fichier « {arguments.motif} » sous {racine_jeux}")

    lecteur = _lire_paires if arguments.format == "paires" else _lire_matrice
    references = _lire_references(arguments.references)
    lignes: List[Dict] = []
    for chemin in fichiers:
        matrice = lecteur(chemin)
        total = sum(sum(ligne) for ligne in matrice)
        racine = Path(tempfile.mkdtemp(prefix="banc_pub_"))
        config = _workspace_depuis_matrice(matrice, racine, arguments.separateur)
        loader = _charger(racine, config)

        debut = time.perf_counter()
        resultat = ApproximateRoleMiner(loader).mine(
            similarity_threshold=arguments.seuil,
            min_users=arguments.min_utilisateurs,
            min_rights=arguments.min_droits,
            excluded_rights=[],
            max_roles=arguments.max_roles,
            selection=arguments.selection,
            selection_effort=arguments.effort,
            selection_delai_s=arguments.delai,
            generateurs=arguments.generateurs,
            treillis_max=arguments.treillis_max,
        )
        duree = time.perf_counter() - debut

        cumul, roles_pour_couvrir = 0, None
        for rang, role in enumerate(resultat["roles"], start=1):
            cumul += role["new_assignments_covered"]
            if cumul >= total:
                roles_pour_couvrir = rang
                break

        lignes.append({
            "jeu": str(chemin.relative_to(racine_jeux)),
            "utilisateurs": len(matrice),
            "droits": len(matrice[0]),
            "habilitations": total,
            "seuil": arguments.seuil,
            "roles_emis": len(resultat["roles"]),
            "roles_pour_100pct": roles_pour_couvrir,
            "couverture_pct": resultat["stats"]["coverage_pct"],
            "sur_octroi": resultat["stats"]["over_granted"],
            "selection": arguments.selection,
            "roles_glouton": resultat["stats"]["selection_roles_glouton"],
            "borne_sur_candidats": resultat["stats"]["selection_borne"],
            "arret": resultat["stats"]["selection_arret"],
            "generateurs": "+".join(resultat["stats"]["generateurs"]),
            "treillis_borne": resultat["stats"]["treillis_borne"],
            "secondes": round(duree, 3),
            **complexites(resultat["roles"]),
            **_meilleure_reference(arguments.decompositions, chemin.stem),
        })
        optimum = references.get(chemin.stem)
        if optimum is not None:
            lignes[-1]["optimum_publie"] = optimum
            lignes[-1]["ecart"] = (None if roles_pour_couvrir is None
                                   else roles_pour_couvrir - optimum)
    return lignes


# ------------------------------------------------------------------------- CLI


def _generateurs(valeur: str) -> List[str]:
    """`cloture,signature` → la liste, refusée si un nom est inconnu."""
    noms = [nom.strip() for nom in valeur.split(",") if nom.strip()]
    inconnus = [nom for nom in noms if nom not in GENERATEURS]
    if inconnus:
        raise argparse.ArgumentTypeError(
            f"générateur inconnu : {', '.join(inconnus)} (connus : {', '.join(GENERATEURS)})")
    return noms


def _options_de_generation(analyseur: argparse.ArgumentParser) -> None:
    """Les deux options qui décident du vivier, communes aux deux bancs."""
    analyseur.add_argument("--generateurs", type=_generateurs,
                           default=list(GENERATEURS_PAR_DEFAUT),
                           help="façons d'amorcer un candidat, séparées par des virgules")
    analyseur.add_argument("--treillis-max", type=int, default=TREILLIS_MAX,
                           help="candidats que le treillis peut ajouter")


def construire_analyseur() -> argparse.ArgumentParser:
    analyseur = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    analyseur.add_argument("--json", action="store_true", help="sortie JSON plutôt que tableau lisible")
    sous = analyseur.add_subparsers(dest="mode", required=True)

    synthetique = sous.add_parser("synthetique", help="restitution de rôles connus, sous bruit croissant")
    synthetique.add_argument("--utilisateurs", type=int, default=600)
    synthetique.add_argument("--droits", type=int, default=120)
    synthetique.add_argument("--roles", type=int, default=15)
    synthetique.add_argument("--taille-role-min", type=int, default=4)
    synthetique.add_argument("--taille-role-max", type=int, default=9)
    synthetique.add_argument("--roles-par-utilisateur-min", type=int, default=1)
    synthetique.add_argument("--roles-par-utilisateur-max", type=int, default=3)
    synthetique.add_argument("--omissions", type=float, nargs="+", default=[0.0, 0.05, 0.10, 0.20])
    synthetique.add_argument("--exceptions", type=float, nargs="+", default=[0.0, 0.02, 0.05, 0.10])
    synthetique.add_argument("--seuils", type=float, nargs="+", default=[1.0, 0.9, 0.8, 0.7])
    synthetique.add_argument("--graine", type=int, default=11)
    synthetique.add_argument("--colonne-utilisateur", default="matricule")
    synthetique.add_argument("--colonne-droit", default="code_droit")
    synthetique.add_argument("--colonne-application", default="code_appli")
    synthetique.add_argument("--min-utilisateurs", type=int, default=2)
    synthetique.add_argument("--min-droits", type=int, default=2)
    synthetique.add_argument("--max-roles", type=int, default=200)
    _options_de_generation(synthetique)

    public = sous.add_parser("public", help="jeux publics au format matriciel, présents sur le poste")
    public.add_argument("--racine", required=True, help="répertoire contenant les jeux")
    public.add_argument("--motif", default="UPA.txt", help="motif des fichiers de matrice")
    public.add_argument("--separateur", default=";", help="séparateur des CSV intermédiaires")
    public.add_argument("--seuil", type=float, default=1.0)
    public.add_argument("--min-utilisateurs", type=int, default=1)
    public.add_argument("--min-droits", type=int, default=1)
    public.add_argument("--max-roles", type=int, default=5000)
    public.add_argument("--format", choices=("matrice", "paires"), default="matrice",
                        help="matrice 0/1 (UPA.txt) ou une habilitation par ligne (jeux HP de ConstrainedRM)")
    public.add_argument("--selection", choices=SELECTIONS, default=SELECTION_PAR_DEFAUT,
                        help="choix des rôles parmi les candidats")
    public.add_argument("--effort", type=int, default=EFFORT_PAR_DEFAUT,
                        help="nœuds accordés à la sélection exacte")
    public.add_argument("--delai", type=float, default=DELAI_PAR_DEFAUT_S,
                        help="délai de protection de la sélection exacte, en secondes")
    public.add_argument("--references", default=None,
                        help="fichier JSON des nombres de rôles publiés, par jeu")
    public.add_argument("--decompositions", default=None,
                        help="répertoire des décompositions de référence (ConstrainedRM)")
    _options_de_generation(public)
    return analyseur


def main(argv: Sequence[str] | None = None) -> int:
    arguments = construire_analyseur().parse_args(argv)

    if arguments.mode == "synthetique":
        if len(arguments.omissions) != len(arguments.exceptions):
            raise SystemExit("--omissions et --exceptions doivent avoir le même nombre de valeurs")
        lignes = executer_synthetique(arguments)
    else:
        lignes = executer_public(arguments)

    if arguments.json:
        print(json.dumps(lignes, indent=2, ensure_ascii=False))
        return 0

    for ligne in lignes:
        print(" | ".join(f"{cle}={valeur}" for cle, valeur in ligne.items()))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
