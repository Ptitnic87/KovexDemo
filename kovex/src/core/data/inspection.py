# Fichier : src/core/data/inspection.py
"""Ce qu'il y a dans le fichier, avant de décider quoi en faire.

Le produit ne connaît pas les colonnes à l'avance : c'est une exigence, pas une
limite. La configuration d'un workspace neuf posait pourtant `ID_utilisateur`,
`ID_application`, `ID_droit` et le point-virgule. Un fichier qui ne suivait pas
cette convention se chargeait **sans erreur et sans rien dedans** — le chargeur
ne renomme que les colonnes qu'il trouve, et se tait sur les autres. L'écran
affichait alors zéro identité sur un fichier qui en contenait onze mille.

Ce module lit un extrait et dit ce qu'il voit : l'encodage qui le décode sans
perte, le séparateur qui le découpe en colonnes régulières, les noms des
colonnes, et quelques lignes pour vérifier à l'œil.

**Il ne décide rien.** Il propose, la personne confirme, et c'est la
confirmation qui est écrite dans la configuration du workspace. Un produit qui
devine en silence est un produit qui se trompe en silence.

Les noms de colonnes sont rendus **tels quels**, sans être nettoyés. Un nom
avec une espace de bord est un défaut du fichier ; le corriger ici écrirait
dans la configuration un nom que le chargeur ne retrouverait pas.
"""

from __future__ import annotations

import codecs
import csv
import io
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: Encodages essayés, dans l'ordre. Le premier qui décode sans perte gagne.
#: `latin-1` ne peut pas échouer : c'est le filet, jamais un bon résultat.
ENCODAGES: Tuple[str, ...] = ("utf-8-sig", "utf-8", "cp1252", "latin-1")

#: Séparateurs candidats. Ce sont ceux des exports de référentiels d'identité
#: qu'on rencontre : point-virgule en Europe, virgule ailleurs, tabulation dans
#: les extractions d'annuaire, barre verticale dans les sorties de mainframe.
SEPARATEURS: Tuple[str, ...] = (";", ",", "\t", "|")

#: Lignes rendues en aperçu. De quoi reconnaître ses données, pas de quoi les
#: consulter : ce n'est pas un explorateur.
LIGNES_APERCU = 5

#: Lignes examinées pour juger de la régularité d'un découpage.
LIGNES_EXAMINEES = 50


def decoder(extrait: bytes) -> Tuple[str, str]:
    """Le texte et l'encodage retenu.

    La marque d'ordre des octets est reconnue à ses octets, pas essayée en
    premier : `utf-8-sig` décode aussi un fichier qui n'en porte pas, et
    l'annoncer partout écrirait dans la configuration un encodage que le
    fichier n'a pas. La marque, elle, doit être retirée — collée au premier nom
    de colonne, elle donne un « ﻿matricule » invisible à l'œil qui ne
    correspond à rien.
    """
    if extrait.startswith(codecs.BOM_UTF8):
        return extrait.decode("utf-8-sig"), "utf-8-sig"
    candidats = ENCODAGES[1:]
    for encodage in candidats[:-1]:
        try:
            return extrait.decode(encodage), encodage
        except UnicodeDecodeError:
            continue
    # `latin-1` décode n'importe quelle suite d'octets : c'est le filet, et
    # jamais un bon résultat — un fichier qui y arrive est un fichier dont
    # personne ne connaît l'encodage.
    return extrait.decode(candidats[-1]), candidats[-1]


def _lignes_completes(texte: str) -> List[str]:
    """Lignes utilisables d'un extrait tronqué.

    L'extrait s'arrête au milieu d'une ligne : la garder ferait croire à une
    ligne courte, donc à un découpage irrégulier, donc au mauvais séparateur.
    """
    lignes = texte.splitlines()
    if lignes and not texte.endswith(("\n", "\r")):
        lignes = lignes[:-1]
    return [ligne for ligne in lignes if ligne.strip()]


def _decoupage(lignes: Sequence[str], separateur: str) -> List[List[str]]:
    return list(csv.reader(io.StringIO("\n".join(lignes)), delimiter=separateur))


def _note(lignes: Sequence[str], separateur: str) -> Tuple[float, int]:
    """Régularité du découpage, et largeur obtenue.

    Un bon séparateur donne le même nombre de colonnes à toutes les lignes. Un
    mauvais en donne un par ligne, ou un nombre qui varie — un point-virgule
    dans un libellé suffit à faire bouger le compte si le séparateur est la
    virgule.
    """
    # L'appelant garantit au moins une ligne non vide : le tableau n'est
    # jamais vide ici, et un garde-fou que rien n'atteint est un garde-fou
    # que personne ne vérifie.
    tableau = _decoupage(lignes[:LIGNES_EXAMINEES], separateur)
    largeur = len(tableau[0])
    if largeur < 2:
        return (0.0, largeur)
    conformes = sum(1 for ligne in tableau if len(ligne) == largeur)
    return (conformes / len(tableau), largeur)


def separateur_probable(lignes: Sequence[str]) -> str:
    """Le séparateur qui découpe le plus régulièrement, et le plus finement.

    Aucun candidat ne convient sur un fichier à une seule colonne — c'est un
    cas légitime, une liste d'identifiants. Le premier candidat est alors rendu
    et l'aperçu montre une colonne unique : la personne voit ce qu'il en est.
    """
    if not lignes:
        return SEPARATEURS[0]
    notes = {separateur: _note(lignes, separateur) for separateur in SEPARATEURS}
    meilleur = max(SEPARATEURS, key=lambda candidat: notes[candidat])
    return meilleur if notes[meilleur][0] else SEPARATEURS[0]


def inspecter(extrait: bytes) -> Dict[str, Any]:
    """Ce que l'extrait laisse voir du fichier.

    Rend toujours une structure complète, même sur un fichier vide ou
    illisible : l'écran doit pouvoir dire « rien à lire ici » plutôt que
    disparaître.
    """
    texte, encodage = decoder(extrait)
    lignes = _lignes_completes(texte)
    separateur = separateur_probable(lignes)
    tableau = _decoupage(lignes[:LIGNES_APERCU + 1], separateur)

    colonnes = [str(nom) for nom in tableau[0]] if tableau else []
    apercu = [[str(valeur) for valeur in ligne] for ligne in tableau[1:]]
    return {
        "encodage": encodage,
        "separateur": separateur,
        "colonnes": colonnes,
        "apercu": apercu,
        "lignes_lues": len(lignes),
    }


def colonnes_du_fichier(chemin, separateur: str, encodage: str) -> List[str]:
    """En-tête réel d'un fichier déjà écrit sur le disque.

    Sert à vérifier une correspondance déclarée **avant** de la retenir : une
    configuration qui désigne une colonne absente produit un référentiel vide
    et personne ne le voit. Seule la première ligne est lue.
    """
    try:
        with open(chemin, "r", encoding=encodage, newline="") as flux:
            premiere = flux.readline()
    except (OSError, UnicodeDecodeError, LookupError):
        return []
    if not premiere:
        return []
    return [str(nom) for nom in
            next(csv.reader(io.StringIO(premiere), delimiter=separateur), [])]


def correspondance_invalide(colonnes: Sequence[str],
                            declarees: Sequence[Optional[str]]) -> List[str]:
    """Colonnes déclarées que le fichier ne contient pas.

    Une chaîne vide n'est pas une déclaration : elle dit « ce fichier ne porte
    pas cette clé », ce qui est légitime — le fichier des habilitations n'a pas
    d'identifiant propre.
    """
    presentes = set(colonnes)
    return sorted({str(nom) for nom in declarees
                   if nom and str(nom) not in presentes})
