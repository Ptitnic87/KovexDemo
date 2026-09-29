#!/usr/bin/env python3
"""Construit la page autonome depuis le produit, et rien d'autre.

La page est le produit : mêmes écrans, même backend, mêmes chiffres. Elle ne
peut donc pas être un dossier tenu à la main — un fichier oublié, et l'écran
publié n'est plus celui qui est testé. Cette construction est la seule façon de
le garantir : elle part de `frontend/`, de `src/` et de la configuration
livrée, et n'invente rien.

Trois garanties, et chacune répond à un incident :

**Rien ne diverge.** Les feuilles, les scripts et les gabarits sont copiés tels
quels. `index.html` reçoit deux balises — le runtime Python et le pont — posées
**avant** le premier script du produit, pour que l'interface ne voie jamais le
`fetch` d'origine. Aucun autre écart.

**Rien qui ne doive sortir ne sort.** L'archive du code est composée par une
liste blanche, et tout chemin ignoré par git y est refusé. `config/users.json`
— des empreintes de mots de passe, délibérément hors du dépôt — s'était
retrouvé dans l'archive publiée : c'est ce refus qui l'en écarte.

**La construction est reproductible.** L'archive est écrite triée et à date
fixe : deux constructions des mêmes sources donnent les mêmes octets, et une
relecture de diff montre ce qui a changé dans le produit, pas l'heure qu'il
était.

Le runtime — Pyodide, les roues, le pont — n'est pas reconstruit : ce sont des
binaires que le dépôt porte déjà. Ils sont laissés en place, et leur présence
est vérifiée.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Iterable, List, Sequence

#: Ce que la page sert depuis `frontend/`, tel quel.
DOSSIERS_DU_FRONTEND = ("css", "js", "vendor")
FICHIERS_DU_FRONTEND = ("favicon.ico",)

#: Les deux balises que la page ajoute, et leur place : avant le premier script
#: du produit. Après, l'interface aurait déjà pu émettre une requête.
#:
#: Elles portent une empreinte du moteur. Sans elle, un navigateur qui a déjà
#: ouvert la page garde le pont en cache et peut exécuter **l'ancien pont avec
#: la nouvelle archive** — un mélange que personne n'a testé. L'empreinte
#: change dès qu'un octet du moteur change, donc l'adresse change, donc le
#: cache ne répond plus à sa place.
GABARIT_DES_BALISES = (
    "        <!-- Le pont se pose AVANT tout script du produit :"
    " l interface ne doit jamais voir le fetch d origine. -->\n"
    '    <script src="moteur/pyodide.js?v={empreinte}"></script>\n'
    '    <script src="moteur/pont.js?v={empreinte}"></script>\n'
)
MARQUE_DU_PONT = "moteur/pont.js"
PREMIER_SCRIPT = '<script src="vendor/chartjs/chart.umd.js'

#: Ce que l'archive du code contient. Liste blanche : ajouter un fichier à
#: l'archive est une décision, jamais un effet de bord d'un nouveau dossier.
#: Chaque entrée est (dossier, motif, obligatoire). Un dossier obligatoire
#: absent fait refuser la construction — le produit ne se livre pas amputé. Un
#: dossier facultatif absent est simplement vide : personne n'a déposé de
#: thème, et ce n'est pas une anomalie.
ARCHIVE = (
    ("src", "**/*.py", True),
    ("config", "config.json", True),
    ("config/locales", "*.json", True),
    # Les thèmes livrés avec l'installation : la page les porte comme un poste
    # les porterait. Un logo est une image — l'archive ne normalise donc que
    # les fichiers texte, sinon elle corromprait ses octets.
    ("config/themes", "**/*", False),
    # La feuille des jetons n'est pas là pour être servie au navigateur — elle
    # l'est déjà, à côté de la page. Le validateur de palette la lit **côté
    # Python** pour savoir ce qu'un thème a le droit de colorer : sans elle,
    # toute la fenêtre du thème tombe, y compris sur « défaut ».
    ("frontend/css", "variables.css", True),
    # Le manuel est servi par l'API, pas par le serveur de fichiers : sans
    # lui, l'écran Documentation rend 503 et toutes ses sections se disent non
    # traduites.
    ("docs/manuel", "**/*.md", True),
)

#: Le socle du runtime : ce dont l'absence empêche tout, et qui ne se déduit
#: d'aucune liste.
RUNTIME_ATTENDU = ("pyodide.js", "pyodide.asm.wasm", "python_stdlib.zip",
                   "pyodide-lock.json", "pont.js")

#: Extensions dont les fins de ligne sont normalisées à la copie. Le reste —
#: polices, images, binaires — est recopié octet pour octet.
SUFFIXES_TEXTE = (".js", ".mjs", ".css", ".html", ".json", ".svg", ".md", ".txt",
                  ".py")

#: Date figée dans l'archive. Une date d'exécution rendrait chaque
#: construction différente, et le dépôt porterait un binaire qui change sans
#: qu'une ligne de code ait bougé.
DATE_FIGEE = (1980, 1, 1, 0, 0, 0)


class ConstructionRefusee(RuntimeError):
    """La construction s'arrête plutôt que de publier ce qu'elle ne sait pas."""


def chemins_ignores(racine: Path, chemins: Sequence[Path]) -> List[Path]:
    """Ceux que git ignore — donc ceux qui n'ont pas à être publiés.

    Le dépôt est l'endroit où se décide ce qui est public. Un fichier tenu hors
    du dépôt l'est pour une raison, et la construction n'a pas à la deviner.

    Sans git — une archive téléchargée, un poste sans l'outil — la vérification
    ne peut pas avoir lieu : on refuse alors la construction plutôt que de la
    faire sans son garde-fou.
    """
    if not chemins:
        return []
    try:
        rendu = subprocess.run(
            ["git", "check-ignore", "--no-index", "--stdin"],
            cwd=str(racine), input="\n".join(str(c) for c in chemins),
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as erreur:
        raise ConstructionRefusee(
            "git indisponible : la construction ne peut pas vérifier ce qui "
            "doit rester hors du dépôt (%s)" % erreur)
    if rendu.returncode not in (0, 1):
        raise ConstructionRefusee(
            "git check-ignore a refusé de répondre : %s" % rendu.stderr.strip())
    return [Path(ligne) for ligne in rendu.stdout.splitlines() if ligne.strip()]


def fichiers_de_l_archive(racine: Path) -> List[Path]:
    """Les chemins, relatifs à la racine, que l'archive doit porter."""
    retenus: List[Path] = []
    for dossier, motif, obligatoire in ARCHIVE:
        base = racine / dossier
        if not base.is_dir():
            if obligatoire:
                raise ConstructionRefusee("dossier absent : %s" % dossier)
            continue
        for chemin in sorted(base.glob(motif)):
            if chemin.is_file():
                relatif = chemin.relative_to(racine)
                # `config/locales/*.json` et `config/config.json` se
                # recouvriraient si les motifs s'élargissaient un jour.
                if relatif not in retenus:
                    retenus.append(relatif)
    ignores = chemins_ignores(racine, retenus)
    if ignores:
        raise ConstructionRefusee(
            "ces fichiers sont ignorés par git et ne peuvent pas être "
            "publiés : %s" % ", ".join(sorted(str(c) for c in ignores)))
    return retenus


def contenu_normalise(chemin: Path) -> bytes:
    """Le contenu du fichier, fins de ligne ramenées à `\n`.

    Le dépôt est cloné sur des postes qui n'écrivent pas les fins de ligne de
    la même façon : un clone Windows rend `\r\n`, un clone Linux `\n`.
    Archiver les octets tels quels ferait une archive différente selon le poste
    qui construit — et la campagne, qui reconstruit pour comparer, refuserait
    une page pourtant juste.

    La normalisation ne change rien à ce que le code fait : Python lit les deux.
    """
    return chemin.read_bytes().replace(b"\r\n", b"\n")


def ecrire_l_archive(racine: Path, destination: Path) -> List[Path]:
    """Écrit `kovex-src.zip`, trié, à date fixe et à fins de ligne normalisées."""
    fichiers = fichiers_de_l_archive(racine)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for relatif in fichiers:
            information = zipfile.ZipInfo(relatif.as_posix(), DATE_FIGEE)
            information.compress_type = zipfile.ZIP_DEFLATED
            information.external_attr = 0o644 << 16
            source = racine / relatif
            archive.writestr(information,
                             contenu_normalise(source)
                             if source.suffix in SUFFIXES_TEXTE
                             else source.read_bytes())
    return fichiers


def empreinte_du_moteur(moteur: Path) -> str:
    """Une empreinte courte de ce que le moteur charge.

    Elle couvre le pont, l'archive du code et les roues qu'il réclame : tout ce
    dont une version périmée, servie depuis le cache du navigateur, produirait
    un mélange que personne n'a testé.

    Les fichiers sont lus dans l'ordre de leur nom, et l'empreinte ne dépend de
    rien d'autre : deux constructions des mêmes sources donnent la même.

    Les fichiers texte sont lus fins de ligne normalisées, comme l'archive :
    lu tel quel, `pont.js` donnait une empreinte sur un clone Windows (`\r\n`)
    et une autre sur la campagne (`\n`), et la campagne refusait une page
    construite sur le poste alors que rien n'avait changé.
    """
    condensat = hashlib.sha256()
    noms = ["pont.js", "kovex-src.zip"] + roues_reclamees(moteur / "pont.js")
    for nom in sorted(set(noms)):
        chemin = moteur / nom
        if chemin.is_file():
            condensat.update(nom.encode("utf-8"))
            condensat.update(contenu_normalise(chemin)
                             if chemin.suffix in SUFFIXES_TEXTE
                             else chemin.read_bytes())
    return condensat.hexdigest()[:12]


def page_html(source: Path, empreinte: str) -> str:
    """`index.html` du produit, avec les deux balises de la page."""
    texte = source.read_text(encoding="utf-8")
    if MARQUE_DU_PONT in texte:
        raise ConstructionRefusee(
            "le gabarit du produit porte déjà les balises de la page : "
            "la page se construit depuis frontend/, jamais depuis elle-même")
    position = texte.find(PREMIER_SCRIPT)
    if position == -1:
        raise ConstructionRefusee(
            "premier script du produit introuvable dans le gabarit : la place "
            "du pont ne peut pas être décidée au hasard")
    debut = texte.rfind("\n", 0, position) + 1
    balises = GABARIT_DES_BALISES.format(empreinte=empreinte)
    return texte[:debut] + balises + texte[debut:]


def copier_le_frontend(racine: Path, destination: Path) -> None:
    """Recopie les dossiers servis, en place, sans rien supprimer.

    L'écriture est faite par-dessus plutôt qu'après un effacement : un dossier
    partagé — un volume monté, un poste qui interdit la suppression — ne permet
    pas de remplacer un fichier en le retirant d'abord. Et un effacement qui
    échoue à mi-chemin laisserait une page amputée.

    Ce qui traîne dans la destination sans exister dans le produit n'est pas
    supprimé pour autant : il est **nommé**, et la construction refuse. Un
    script publié que plus rien ne référence est au mieux du poids mort, au
    pire un écran d'une version précédente.
    """
    orphelins: List[str] = []
    for dossier in DOSSIERS_DU_FRONTEND:
        source = racine / "frontend" / dossier
        if not source.is_dir():
            raise ConstructionRefusee("dossier absent : frontend/%s" % dossier)
        cible = destination / dossier

        attendus = set()
        for fichier in source.rglob("*"):
            if not fichier.is_file():
                continue
            relatif = fichier.relative_to(source)
            attendus.add(relatif)
            arrivee = cible / relatif
            arrivee.parent.mkdir(parents=True, exist_ok=True)
            # Même raison que pour l'archive : un fichier servi qui porterait
            # les fins de ligne du poste ferait diverger la comparaison de la
            # campagne d'un poste à l'autre. Seuls les fichiers texte sont
            # touchés ; une police ou une image passent tels quels.
            arrivee.write_bytes(contenu_normalise(fichier)
                                if fichier.suffix in SUFFIXES_TEXTE
                                else fichier.read_bytes())

        if cible.is_dir():
            orphelins.extend(
                (dossier + "/" + present.relative_to(cible).as_posix())
                for present in cible.rglob("*")
                if present.is_file() and present.relative_to(cible) not in attendus)

    for fichier in FICHIERS_DU_FRONTEND:
        source = racine / "frontend" / fichier
        if source.is_file():
            (destination / fichier).write_bytes(source.read_bytes())


    if orphelins:
        raise ConstructionRefusee(
            "ces fichiers sont dans la page sans exister dans le produit : %s. "
            "Retirez-les avant de reconstruire : la page ne doit servir que ce "
            "qui est testé." % ", ".join(sorted(orphelins)))


def roues_reclamees(pont: Path) -> List[str]:
    """Les archives que le pont demande, lues dans le pont lui-même.

    Écrire cette liste ici en ferait une deuxième source de vérité, qui
    divergerait à la première version de bibliothèque changée. Le pont nomme
    ses archives ; la construction lui demande lesquelles.
    """
    texte = pont.read_text(encoding="utf-8")
    return sorted(set(re.findall(r'"([A-Za-z0-9_.+-]+\.whl)"', texte)))


def _segments_du_chemin(noeud: ast.AST):
    """Les segments littéraux d'une expression de chemin, ou `None`.

    Seules les expressions entièrement écrites en clair sont lues :
    `RACINE_PROJET / "docs" / "manuel"`, `Path("frontend") / "css"`. Un chemin
    qui vient d'une variable désigne une donnée de l'utilisateur, pas une
    ressource livrée, et n'a rien à faire dans l'archive.
    """
    if isinstance(noeud, ast.Constant) and isinstance(noeud.value, str):
        return [noeud.value]
    if isinstance(noeud, ast.Name):
        return [] if noeud.id == "RACINE_PROJET" else None
    if isinstance(noeud, ast.Call):
        appele = noeud.func
        nom = (appele.attr if isinstance(appele, ast.Attribute)
               else getattr(appele, "id", ""))
        if nom == "Path" and len(noeud.args) == 1:
            return _segments_du_chemin(noeud.args[0])
        return None
    if isinstance(noeud, ast.BinOp) and isinstance(noeud.op, ast.Div):
        gauche = _segments_du_chemin(noeud.left)
        droite = _segments_du_chemin(noeud.right)
        if gauche is None or droite is None:
            return None
        return gauche + droite
    return None


def ressources_reclamees(racine: Path) -> List[Path]:
    """Les chemins du dépôt que le backend lit à l'exécution.

    Lus dans le code lui-même, jamais tenus à la main : toute expression
    ancrée sur `RACINE_PROJET` ou passée à `depuis_la_racine()` avec des
    segments écrits en clair désigne un fichier livré avec le produit.

    Le défaut réel, et il se voyait sur la page publiée : le validateur de
    palette lit `frontend/css/variables.css` pour savoir quels jetons un thème
    a le droit de colorer, et le manuel est servi depuis `docs/manuel/`. Ni
    l'un ni l'autre n'était dans l'archive — la liste blanche portait `src/` et
    `config/`. La fenêtre du thème tombait en erreur pour **tous** les thèmes,
    et l'écran Documentation rendait 503, sur une page qui démarrait sans rien
    signaler.
    """
    reclamees: List[Path] = []
    for source in sorted((racine / "src").rglob("*.py")):
        arbre = ast.parse(source.read_text(encoding="utf-8"))
        # Une sous-expression d'un chemin plus long n'est pas une ressource :
        # `RACINE_PROJET / "frontend"` n'existe que pour porter `css`.
        partielles = {id(noeud.left) for noeud in ast.walk(arbre)
                      if isinstance(noeud, ast.BinOp) and isinstance(noeud.op, ast.Div)}
        for noeud in ast.walk(arbre):
            segments = None
            if (isinstance(noeud, ast.BinOp) and isinstance(noeud.op, ast.Div)
                    and id(noeud) not in partielles
                    and any(isinstance(fils, ast.Name) and fils.id == "RACINE_PROJET"
                            for fils in ast.walk(noeud))):
                segments = _segments_du_chemin(noeud)
            elif isinstance(noeud, ast.Call):
                appele = noeud.func
                nom = (appele.attr if isinstance(appele, ast.Attribute)
                       else getattr(appele, "id", ""))
                if nom == "depuis_la_racine" and len(noeud.args) == 1:
                    segments = _segments_du_chemin(noeud.args[0])
            if not segments:
                continue
            chemin = Path(*segments)
            if chemin not in reclamees:
                reclamees.append(chemin)
    return reclamees


def verifier_les_ressources(racine: Path, fichiers: Sequence[Path]) -> None:
    """Refuse une archive qui n'emporte pas ce que le backend lit.

    Un fichier absent ne se voit pas au démarrage : la page se charge, et
    l'écran qui en dépend tombe le jour où on l'ouvre.
    """
    portes = {chemin.as_posix() for chemin in fichiers}
    manquants: List[str] = []
    for reclamee in ressources_reclamees(racine):
        sur_le_disque = racine / reclamee
        if sur_le_disque.is_file():
            attendus = [reclamee]
        elif sur_le_disque.is_dir():
            attendus = sorted(chemin.relative_to(racine)
                              for chemin in sur_le_disque.rglob("*")
                              if chemin.is_file())
        else:
            continue
        for chemin in attendus:
            if chemin.as_posix() not in portes:
                manquants.append(chemin.as_posix())
    if manquants:
        raise ConstructionRefusee(
            "le code lit des fichiers du dépôt que l'archive n'emporte pas : "
            "%s. L'écran qui en dépend tombe sur la page publiée sans que le "
            "démarrage n'ait rien signalé." % ", ".join(sorted(set(manquants))))


def verifier_le_runtime(destination: Path) -> None:
    """Refuse une page dont le runtime ne porte pas tout ce que le pont réclame.

    Le socle ne suffit pas à vérifier. Le défaut réel : six archives — dont
    celles du classeur et du PDF — n'avaient jamais été déposées à côté de la
    page publiée. Elle répondait `404`, Pyodide recevait une page d'erreur à la
    place d'une archive, l'application échouait à démarrer, et l'interface
    bouclait : déconnexion, rechargement, recommencer. Rien dans le dépôt ne le
    disait, parce que rien ne comparait ce que le pont demande à ce qui est là.
    """
    moteur = destination / "moteur"
    manquants = [nom for nom in RUNTIME_ATTENDU if not (moteur / nom).is_file()]
    if manquants:
        raise ConstructionRefusee(
            "socle du runtime incomplet dans %s : %s" % (moteur, ", ".join(manquants)))

    absentes = [nom for nom in roues_reclamees(moteur / "pont.js")
                if not (moteur / nom).is_file()]
    if absentes:
        raise ConstructionRefusee(
            "le pont réclame des archives qui ne sont pas dans %s : %s. Une "
            "archive absente répond 404, et la page ne démarre pas."
            % (moteur, ", ".join(absentes)))


def construire(racine: Path, destination: Path) -> dict:
    """Construit la page et rend ce qu'elle porte."""
    destination.mkdir(parents=True, exist_ok=True)
    copier_le_frontend(racine, destination)
    # L'archive est écrite **avant** le gabarit : son contenu entre dans
    # l'empreinte que les balises portent.
    fichiers = ecrire_l_archive(racine, destination / "moteur" / "kovex-src.zip")
    verifier_les_ressources(racine, fichiers)
    verifier_le_runtime(destination)
    empreinte = empreinte_du_moteur(destination / "moteur")
    # `write_text` traduirait `\n` en fin de ligne du poste : on écrit les
    # octets, pour que le gabarit publié soit le même partout.
    (destination / "index.html").write_bytes(
        page_html(racine / "frontend" / "index.html", empreinte)
        .replace("\r\n", "\n").encode("utf-8"))
    # GitHub Pages passe le dossier dans Jekyll sans ce marqueur, et tout
    # dossier commençant par un souligné disparaît.
    (destination / ".nojekyll").write_text("", encoding="utf-8")
    return {"archive": len(fichiers), "destination": str(destination),
            "empreinte": empreinte}


def principal(arguments: Iterable[str] = ()) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--racine", default=".",
                           help="racine du dépôt (défaut : le dossier courant)")
    analyseur.add_argument("--destination", default="pages",
                           help="dossier de la page (défaut : pages/)")
    options = analyseur.parse_args(list(arguments) or None)
    try:
        rendu = construire(Path(options.racine).resolve(),
                           Path(options.destination).resolve())
    except ConstructionRefusee as refus:
        print("construction refusée : %s" % refus, file=sys.stderr)
        return 1
    print("page construite dans %s — %d fichiers dans l'archive, moteur %s"
          % (rendu["destination"], rendu["archive"], rendu["empreinte"]))
    return 0


if __name__ == "__main__":
    sys.exit(principal())
