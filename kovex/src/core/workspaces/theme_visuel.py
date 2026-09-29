# Fichier : src/core/workspaces/theme_visuel.py
"""Les thèmes visuels d'un workspace : format, dépôt, et refus motivé.

Un workspace est ouvert pour un client, et l'écran finit par être montré à ce
client. Le produit ne peut pas embarquer les couleurs de chacun : les marques
appartiennent à leurs titulaires, et une palette écrite dans le code est une
palette qu'il faut redéployer pour changer. Un thème est donc un **fichier
déposé**, découvert au démarrage, et l'ajout d'un client ne touche pas une
ligne de code.

Ce qui est déposé est une entrée non fiabilisée, même déposée de bonne foi.
Trois barrières :

* Les jetons redéfinissables ne sont pas une liste écrite ici mais ceux que la
  feuille de style déclare dans les deux variantes et qui s'y résolvent en une
  couleur pleine. Un thème ne peut donc pas inventer une propriété, ni glisser
  une valeur arbitraire dans une déclaration CSS : chaque valeur est un
  hexadécimal à six chiffres, posé jeton par jeton, jamais concaténé.
* Un logo est jugé sur ses octets, pas sur son nom. Le format vectoriel est
  hors de la liste des types acceptés : un SVG est un document qui peut porter
  du script, et il serait servi depuis la même origine que l'application.
* Le contrat de contraste de la palette d'origine est rejoué sur la palette
  fusionnée. C'est le point qui distingue un mécanisme de thèmes d'un
  habillage : sans lui, la première couleur de marque un peu pâle rend un
  texte illisible et rien ne le dit.

Un thème refusé n'est pas masqué. Le motif remonte à l'écran, avec la paire
fautive et son rapport de contraste, sinon le dépôt devient une devinette.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core.accessibilite.palette import (
    VARIANTES,
    defauts_de_contraste,
    jetons_colorables,
)

#: Nom du dossier, sous le workspace, où les thèmes sont déposés.
DOSSIER_DES_THEMES = "themes"

#: Où l'instance dépose les thèmes qui servent **tous** ses espaces de travail.
#:
#: Le mécanisme d'origine attachait un thème à un espace : la même marque
#: devait être recopiée dans chacun, et un espace créé ensuite l'oubliait. Un
#: cabinet qui ouvre un dossier par client dépose désormais son thème une fois.
#: Le format et les trois barrières sont les mêmes — c'est le même mécanisme,
#: avec un endroit de plus.
DOSSIER_DES_THEMES_DE_L_INSTANCE = ("config", "themes")

#: Nom du document décrivant un thème, dans son propre dossier.
NOM_DU_DOCUMENT = "theme.json"

#: Identifiant du thème livré avec le produit. Il n'a pas de fichier : il est
#: la palette d'origine, celle que la feuille de style porte déjà.
IDENTIFIANT_PAR_DEFAUT = "default"

#: Clé de traduction du libellé du thème d'origine. Les thèmes déposés, eux,
#: portent leurs propres libellés : ils sont ajoutés après la livraison, donc
#: aucun catalogue ne peut les connaître.
CLE_DU_LIBELLE_PAR_DEFAUT = "form.visual_theme.default"

MOTIF_IDENTIFIANT = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?")
MOTIF_COULEUR = re.compile(r"#[0-9a-fA-F]{6}")
MOTIF_LANGUE = re.compile(r"[a-z]{2}(?:-[A-Z]{2})?")
MOTIF_NOM_DE_FICHIER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,58}[A-Za-z0-9])?")

#: Bornes. Un document de thème est une poignée de couleurs ; un logo est une
#: image d'interface. Au-delà, c'est autre chose, et on ne l'ouvre pas.
TAILLE_MAXIMALE_DU_DOCUMENT = 64 * 1024
TAILLE_MAXIMALE_DU_LOGO = 512 * 1024
LONGUEUR_MAXIMALE_DU_LIBELLE = 60

#: Types d'image acceptés, reconnus à leur signature. La clé est l'extension,
#: la valeur la suite d'octets qui doit ouvrir le fichier.
SIGNATURES_DU_LOGO: Dict[str, Tuple[bytes, ...]] = {
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".webp": (b"RIFF",),
}

#: Type MIME servi pour chaque extension acceptée. Il n'est jamais déduit du
#: nom du fichier au moment de servir : il est choisi dans cette table.
TYPES_DU_LOGO: Dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


class ThemeInvalide(ValueError):
    """Un thème déposé ne remplit pas le contrat.

    Le motif voyage sous forme de clé de traduction : il finit affiché, et le
    produit n'écrit aucun texte en dur.
    """

    def __init__(self, cle: str, **parametres: Any) -> None:
        self.cle = cle
        self.parametres = parametres
        super().__init__(f"{cle} {parametres}" if parametres else cle)


@dataclass(frozen=True)
class ThemeVisuel:
    """Un thème utilisable : ses libellés, ses couleurs, son logo."""

    identifiant: str
    libelles: Dict[str, str] = field(default_factory=dict)
    variantes: Dict[str, Dict[str, str]] = field(default_factory=dict)
    logo: str = ""
    cle_du_libelle: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identifiant": self.identifiant,
            "libelles": dict(self.libelles),
            "cle_du_libelle": self.cle_du_libelle,
            "variantes": {variante: dict(jetons)
                          for variante, jetons in self.variantes.items()},
            "logo": bool(self.logo),
        }


#: Le thème d'origine, toujours disponible, sans fichier ni couleur propre.
THEME_PAR_DEFAUT = ThemeVisuel(
    identifiant=IDENTIFIANT_PAR_DEFAUT,
    cle_du_libelle=CLE_DU_LIBELLE_PAR_DEFAUT,
)


def dossier_des_themes(chemin_du_workspace: Path) -> Path:
    return Path(chemin_du_workspace) / DOSSIER_DES_THEMES


# --- lecture d'un thème ----------------------------------------------------

def dossier_des_themes_de_l_instance(racine_de_l_instance: Path) -> Path:
    """Le dossier des thèmes livrés avec l'instance."""
    return racine_de_l_instance.joinpath(*DOSSIER_DES_THEMES_DE_L_INSTANCE)


def _racines(chemin_du_workspace: Path,
             racine_de_l_instance: Optional[Path]) -> List[Path]:
    """Les endroits où un thème peut être déposé, **du moins précis au plus**.

    L'ordre est le sens même du mécanisme : à identifiant égal, le dépôt de
    l'espace de travail gagne. L'inverse rendrait impossible toute exception
    locale, et la surprise arriverait chez le client.
    """
    racines: List[Path] = []
    if racine_de_l_instance is not None:
        racines.append(dossier_des_themes_de_l_instance(racine_de_l_instance))
    racines.append(dossier_des_themes(chemin_du_workspace))
    return racines


def _document(dossier: Path, identifiant: str) -> Dict[str, Any]:
    chemin = dossier / NOM_DU_DOCUMENT
    if not chemin.is_file():
        raise ThemeInvalide("theme.document_missing", theme=identifiant,
                            document=NOM_DU_DOCUMENT)
    if chemin.stat().st_size > TAILLE_MAXIMALE_DU_DOCUMENT:
        raise ThemeInvalide("theme.document_too_large", theme=identifiant,
                            limit=TAILLE_MAXIMALE_DU_DOCUMENT)
    try:
        document = json.loads(chemin.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as erreur:
        raise ThemeInvalide("theme.document_unreadable", theme=identifiant,
                            reason=str(erreur)) from erreur
    if not isinstance(document, dict):
        raise ThemeInvalide("theme.document_not_an_object", theme=identifiant)
    return document


def _libelles(document: Dict[str, Any], identifiant: str) -> Dict[str, str]:
    libelles = document.get("libelles")
    if not isinstance(libelles, dict) or not libelles:
        raise ThemeInvalide("theme.labels_missing", theme=identifiant)
    for langue, libelle in libelles.items():
        if not MOTIF_LANGUE.fullmatch(str(langue)):
            raise ThemeInvalide("theme.language_invalid", theme=identifiant,
                                language=str(langue))
        if (not isinstance(libelle, str) or not libelle.strip()
                or len(libelle) > LONGUEUR_MAXIMALE_DU_LIBELLE):
            raise ThemeInvalide("theme.label_invalid", theme=identifiant,
                                language=str(langue),
                                limit=LONGUEUR_MAXIMALE_DU_LIBELLE)
    return {str(langue): libelle.strip() for langue, libelle in libelles.items()}


def _variantes(document: Dict[str, Any], identifiant: str) -> Dict[str, Dict[str, str]]:
    """Les couleurs, variante par variante.

    Les deux variantes sont exigées. Un thème qui n'habillerait que l'affichage
    sombre laisserait l'affichage clair à la palette d'origine : le client
    verrait ses couleurs ou celles du produit selon un réglage personnel, ce
    qui n'est pas un habillage mais un accident. Pour la même raison, un jeton
    redéfini d'un côté doit l'être de l'autre.
    """
    variantes = document.get("variantes")
    if not isinstance(variantes, dict):
        raise ThemeInvalide("theme.variants_missing", theme=identifiant,
                            variants=", ".join(VARIANTES))
    manquantes = [variante for variante in VARIANTES if variante not in variantes]
    if manquantes:
        raise ThemeInvalide("theme.variants_missing", theme=identifiant,
                            variants=", ".join(manquantes))
    inconnues = [str(nom) for nom in variantes if nom not in VARIANTES]
    if inconnues:
        raise ThemeInvalide("theme.variant_unknown", theme=identifiant,
                            variant=", ".join(sorted(inconnues)))

    autorises = set(jetons_colorables())
    retenues: Dict[str, Dict[str, str]] = {}
    for variante in VARIANTES:
        jetons = variantes[variante]
        if not isinstance(jetons, dict) or not jetons:
            raise ThemeInvalide("theme.variant_empty", theme=identifiant,
                                variant=variante)
        for jeton, couleur in jetons.items():
            if str(jeton) not in autorises:
                raise ThemeInvalide("theme.token_unknown", theme=identifiant,
                                    variant=variante, token=str(jeton))
            if not isinstance(couleur, str) or not MOTIF_COULEUR.fullmatch(couleur):
                raise ThemeInvalide("theme.color_invalid", theme=identifiant,
                                    variant=variante, token=str(jeton),
                                    value=str(couleur))
        retenues[variante] = {str(jeton): couleur.lower()
                              for jeton, couleur in jetons.items()}

    premiere, seconde = VARIANTES[0], VARIANTES[1]
    dissymetrie = set(retenues[premiere]) ^ set(retenues[seconde])
    if dissymetrie:
        raise ThemeInvalide("theme.variants_asymmetric", theme=identifiant,
                            tokens=", ".join(sorted(dissymetrie)))
    return retenues


def _logo(document: Dict[str, Any], dossier: Path, identifiant: str) -> str:
    nom = document.get("logo", "")
    if not nom:
        return ""
    nom = str(nom)
    if not MOTIF_NOM_DE_FICHIER.fullmatch(nom):
        raise ThemeInvalide("theme.logo_name_invalid", theme=identifiant, logo=nom)
    extension = Path(nom).suffix.lower()
    if extension not in SIGNATURES_DU_LOGO:
        raise ThemeInvalide("theme.logo_type_refused", theme=identifiant, logo=nom,
                            types=", ".join(sorted(SIGNATURES_DU_LOGO)))
    chemin = dossier / nom
    if not chemin.is_file():
        raise ThemeInvalide("theme.logo_missing", theme=identifiant, logo=nom)
    if chemin.stat().st_size > TAILLE_MAXIMALE_DU_LOGO:
        raise ThemeInvalide("theme.logo_too_large", theme=identifiant, logo=nom,
                            limit=TAILLE_MAXIMALE_DU_LOGO)
    with chemin.open("rb") as fichier:
        entete = fichier.read(16)
    if not any(entete.startswith(signature)
               for signature in SIGNATURES_DU_LOGO[extension]):
        raise ThemeInvalide("theme.logo_content_refused", theme=identifiant, logo=nom)
    return nom


def _contraste(variantes: Dict[str, Dict[str, str]], identifiant: str) -> None:
    defauts = defauts_de_contraste(variantes)
    if defauts:
        raise ThemeInvalide("theme.contrast_refused", theme=identifiant,
                            failures="\n".join(defauts), count=len(defauts))


def charger(dossier: Path, identifiant: str) -> ThemeVisuel:
    """Lit et valide un thème déposé. Lève `ThemeInvalide` au premier manquement."""
    if not MOTIF_IDENTIFIANT.fullmatch(identifiant):
        raise ThemeInvalide("theme.identifier_invalid", theme=identifiant)
    document = _document(dossier, identifiant)
    # L'ordre est celui du coût croissant : la forme du document d'abord, le
    # calcul de contraste en dernier. Un fichier mal formé n'a pas à faire
    # résoudre la palette pour être refusé.
    libelles = _libelles(document, identifiant)
    variantes = _variantes(document, identifiant)
    logo = _logo(document, dossier, identifiant)
    _contraste(variantes, identifiant)
    return ThemeVisuel(identifiant=identifiant, libelles=libelles,
                       variantes=variantes, logo=logo)


def lister(chemin_du_workspace: Path,
           racine_de_l_instance: Optional[Path] = None
           ) -> Tuple[List[ThemeVisuel], List[ThemeInvalide]]:
    """Les thèmes utilisables d'un workspace, et ceux qui ont été refusés.

    Deux dépôts sont lus : celui de l'instance, qui sert tous les espaces, et
    celui de l'espace. À identifiant égal, l'espace gagne.

    Les deux listes reviennent ensemble : un thème déposé qui n'apparaît nulle
    part et sans motif est indiscernable d'un thème oublié.
    """
    retenus: Dict[str, ThemeVisuel] = {}
    refus: List[ThemeInvalide] = []
    for racine in _racines(chemin_du_workspace, racine_de_l_instance):
        if not racine.is_dir():
            continue
        for dossier in sorted(racine.iterdir()):
            if not dossier.is_dir():
                continue
            try:
                retenus[dossier.name] = charger(dossier, dossier.name)
            except ThemeInvalide as refuse:
                refus.append(refuse)
    themes = [THEME_PAR_DEFAUT] + [retenus[nom] for nom in sorted(retenus)]
    return themes, refus


def theme_utilisable(chemin_du_workspace: Path, identifiant: str,
                     racine_de_l_instance: Optional[Path] = None
                     ) -> Optional[ThemeVisuel]:
    """Le thème demandé s'il est disponible pour ce workspace, sinon `None`."""
    themes, _ = lister(chemin_du_workspace, racine_de_l_instance)
    for theme in themes:
        if theme.identifiant == identifiant:
            return theme
    return None


def chemin_du_logo(chemin_du_workspace: Path, identifiant: str,
                   racine_de_l_instance: Optional[Path] = None) -> Path:
    """Chemin du logo d'un thème, une fois le thème validé.

    Le nom vient du thème validé, jamais de la requête : la traversée n'est pas
    filtrée ici, elle est structurellement impossible.

    Le dossier, lui, est **celui d'où le thème retenu vient** : présumer celui
    de l'espace de travail servirait un logo absent pour un thème livré avec
    l'instance. L'ordre de recherche est celui de la précédence, à l'envers.
    """
    theme = theme_utilisable(chemin_du_workspace, identifiant, racine_de_l_instance)
    if theme is None or not theme.logo:
        raise ThemeInvalide("theme.logo_missing", theme=identifiant, logo="")
    for racine in reversed(_racines(chemin_du_workspace, racine_de_l_instance)):
        chemin = racine / identifiant / theme.logo
        if chemin.is_file():
            return chemin
    raise ThemeInvalide("theme.logo_missing", theme=identifiant, logo=theme.logo)


def type_du_logo(nom: str) -> str:
    return TYPES_DU_LOGO[Path(nom).suffix.lower()]
