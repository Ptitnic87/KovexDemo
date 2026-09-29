"""Où Kovex va chercher un modèle, et qui l'a décidé.

L'adresse, le modèle et le délai étaient lus dans l'environnement du serveur,
et nulle part ailleurs. C'est la bonne règle sur un poste — ouvrir une sortie
réseau depuis un serveur d'habilitations est une décision d'infrastructure —
mais elle a une conséquence que la page publiée a rendue visible : **dans un
navigateur, il n'y a pas d'environnement**. Aucune variable ne peut y être
posée, donc aucun des sept usages d'IA n'y est joignable. Pas en erreur :
absent.

Ce module ajoute une seconde source, sans toucher à la première.

**L'environnement reste prioritaire, et il n'est pas modifié.** Une
installation qui pose `KOVEX_ANNOTATEUR_URL` se comporte exactement comme
avant, à l'octet près. La configuration n'est lue que là où l'environnement ne
dit rien. L'écran, lui, doit montrer d'où vient la valeur : un champ imposé par
l'installation ne se présente pas comme un champ qu'on peut remplir.

**Un préréglage est le groupe entier.** Adresse et modèle vont ensemble, et la
clé appartient au préréglage — jamais à l'usage. C'est la même règle que celle
déjà tenue par l'environnement, où un suffixe d'usage se prend entier ou pas
du tout : mélanger deux groupes reviendrait à envoyer à un point de
terminaison la clé configurée pour un autre.

**La clé n'est pas ici.** Ce document est celui du workspace : il est exporté,
relu, comparé. Un secret n'y a pas sa place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from src.core.annotation.annotateur import DELAI_PAR_DEFAUT_S, Reglages
from src.core.annotation.assistance import PAR_CODE
from src.core.annotation.assistance import USAGES_DE_MODELE as USAGES

#: Clé du bloc dans le `config.json` du workspace.
CLE_POINTS_DE_TERMINAISON = "points_de_terminaison"

#: D'où vient un réglage. L'écran s'en sert pour dire ce qui est modifiable.
ORIGINE_ENVIRONNEMENT = "environnement"
ORIGINE_CONFIGURATION = "configuration"
ORIGINE_ABSENTE = "absent"


@dataclass(frozen=True)
class Prereglage:
    """Un point de terminaison nommé, réutilisable par plusieurs usages.

    L'identifiant est ce que la configuration référence ; le libellé est ce que
    l'utilisateur lit. Les deux lui appartiennent : le produit ne livre aucune
    liste de fournisseurs, parce qu'une liste livrée vieillit et qu'un client
    qui héberge son propre modèle n'y figurerait jamais.
    """

    identifiant: str
    libelle: str = ""
    adresse: str = ""
    modele: str = ""

    @property
    def complet(self) -> bool:
        """Sans adresse ni modèle, le préréglage ne peut rien servir."""
        return bool(self.adresse and self.modele)


@dataclass(frozen=True)
class Configuration:
    """Le bloc lu, et ce qu'il a fallu écarter pour le lire.

    Les avertissements sont des codes de traduction et leurs paramètres, comme
    partout ailleurs : un réglage écarté en silence est un réglage que son
    auteur croit encore actif.
    """

    prereglages: Tuple[Prereglage, ...] = ()
    commun: str = ""
    par_usage: Mapping[str, str] = field(default_factory=dict)
    delais: Mapping[str, float] = field(default_factory=dict)
    avertissements: Tuple[Dict[str, Any], ...] = ()

    def prereglage(self, identifiant: str) -> Optional[Prereglage]:
        for candidat in self.prereglages:
            if candidat.identifiant == identifiant:
                return candidat
        return None

    def reglages(self, usage: str = "") -> Reglages:
        """Les réglages d'un usage : le sien s'il en a un, sinon le commun.

        Sans clé : elle ne vit pas dans ce document. L'appelant la complète
        depuis le porte-clés de l'instance ou de la session.
        """
        choisi = self.par_usage.get(usage) or self.commun
        reference = self.prereglage(choisi) if choisi else None
        if reference is None or not reference.complet:
            return Reglages()
        delai = self.delais.get(usage) or self.delais.get("", DELAI_PAR_DEFAUT_S)
        return Reglages(adresse=reference.adresse.rstrip("/"),
                        modele=reference.modele, cle="", delai_s=float(delai))


def _prereglages_lus(brut: Any, avertissements: List[Dict[str, Any]]
                     ) -> Tuple[Prereglage, ...]:
    if brut is None:
        return ()
    if not isinstance(brut, (list, tuple)):
        avertissements.append({"code": "endpoints.warning.unreadable_presets",
                               "params": {}})
        return ()
    lus: List[Prereglage] = []
    vus = set()
    for entree in brut:
        if not isinstance(entree, Mapping):
            avertissements.append({"code": "endpoints.warning.unreadable_preset",
                                   "params": {"entree": str(entree)[:60]}})
            continue
        identifiant = str(entree.get("identifiant", "")).strip()
        if not identifiant:
            avertissements.append({"code": "endpoints.warning.preset_without_id",
                                   "params": {}})
            continue
        if identifiant in vus:
            # Deux préréglages du même nom : le second ne serait jamais
            # atteint, et son auteur croirait l'avoir posé.
            avertissements.append({"code": "endpoints.warning.duplicate_preset",
                                   "params": {"prereglage": identifiant}})
            continue
        vus.add(identifiant)
        lus.append(Prereglage(
            identifiant=identifiant,
            libelle=str(entree.get("libelle", "")).strip(),
            adresse=str(entree.get("adresse", "")).strip(),
            modele=str(entree.get("modele", "")).strip()))
    return tuple(lus)


def _delai_lu(entree: Mapping[str, Any], cle: str,
              avertissements: List[Dict[str, Any]]) -> Optional[float]:
    if "delai_s" not in entree:
        return None
    try:
        delai = float(entree["delai_s"])
    except (TypeError, ValueError):
        avertissements.append({"code": "endpoints.warning.unreadable_timeout",
                               "params": {"usage": cle}})
        return None
    if delai <= 0:
        avertissements.append({"code": "endpoints.warning.timeout_not_positive",
                               "params": {"usage": cle}})
        return None
    return delai


def depuis_la_configuration(configuration: Mapping[str, Any]) -> Configuration:
    """Lit le bloc des points de terminaison du `config.json` du workspace."""
    brut = configuration.get(CLE_POINTS_DE_TERMINAISON)
    if not isinstance(brut, Mapping):
        return Configuration()

    avertissements: List[Dict[str, Any]] = []
    prereglages = _prereglages_lus(brut.get("prereglages"), avertissements)
    connus = {prereglage.identifiant for prereglage in prereglages}

    def reference(entree: Mapping[str, Any], cle: str) -> str:
        nom = str(entree.get("prereglage", "")).strip()
        if nom and nom not in connus:
            # Le cas qui trompe le plus : le préréglage a été renommé, et
            # l'usage pointe dans le vide. Sans ce mot, il paraît configuré.
            avertissements.append({"code": "endpoints.warning.unknown_preset",
                                   "params": {"usage": cle, "prereglage": nom}})
            return ""
        return nom

    delais: Dict[str, float] = {}
    commun_brut = brut.get("commun")
    commun = ""
    if isinstance(commun_brut, Mapping):
        commun = reference(commun_brut, "")
        delai = _delai_lu(commun_brut, "", avertissements)
        if delai is not None:
            delais[""] = delai
    elif commun_brut is not None:
        avertissements.append({"code": "endpoints.warning.unreadable_common",
                               "params": {}})

    par_usage: Dict[str, str] = {}
    usages_bruts = brut.get("usages")
    if isinstance(usages_bruts, Mapping):
        for code, entree in usages_bruts.items():
            if code not in PAR_CODE:
                avertissements.append({"code": "endpoints.warning.unknown_usage",
                                       "params": {"usage": str(code)}})
                continue
            if not isinstance(entree, Mapping):
                avertissements.append({"code": "endpoints.warning.unreadable_usage",
                                       "params": {"usage": code}})
                continue
            choisi = reference(entree, code)
            if choisi:
                par_usage[code] = choisi
            delai = _delai_lu(entree, code, avertissements)
            if delai is not None:
                delais[code] = delai
    elif usages_bruts is not None:
        avertissements.append({"code": "endpoints.warning.unreadable_usages",
                               "params": {}})

    return Configuration(prereglages=prereglages, commun=commun,
                         par_usage=par_usage, delais=delais,
                         avertissements=tuple(avertissements))


def en_document(configuration: Configuration) -> Dict[str, Any]:
    """Le bloc tel qu'il s'écrit dans le `config.json`.

    Les usages sans choix propre ne sont pas écrits : une entrée vide se
    relirait comme un choix fait, alors que c'est l'absence de choix qui fait
    retomber l'usage sur le réglage commun.
    """
    document: Dict[str, Any] = {
        "prereglages": [
            {"identifiant": prereglage.identifiant,
             "libelle": prereglage.libelle,
             "adresse": prereglage.adresse,
             "modele": prereglage.modele}
            for prereglage in configuration.prereglages],
        "commun": {"prereglage": configuration.commun},
    }
    if "" in configuration.delais:
        document["commun"]["delai_s"] = configuration.delais[""]
    usages: Dict[str, Any] = {}
    for usage in USAGES:
        entree: Dict[str, Any] = {}
        if configuration.par_usage.get(usage.code):
            entree["prereglage"] = configuration.par_usage[usage.code]
        if usage.code in configuration.delais:
            entree["delai_s"] = configuration.delais[usage.code]
        if entree:
            usages[usage.code] = entree
    if usages:
        document["usages"] = usages
    return document


def origine(environnement: Mapping[str, str], configuration: Configuration,
            usage: str = "") -> str:
    """Qui décide, pour cet usage : l'installation, l'utilisateur, ou personne."""
    from src.core.annotation.annotateur import depuis_l_environnement

    if depuis_l_environnement(environnement, usage).actif:
        return ORIGINE_ENVIRONNEMENT
    if configuration.reglages(usage).actif:
        return ORIGINE_CONFIGURATION
    return ORIGINE_ABSENTE


def resoudre(environnement: Mapping[str, str], configuration: Configuration,
             cles: Mapping[str, str], usage: str = "") -> Tuple[Reglages, str]:
    """Les réglages effectifs d'un usage, et d'où ils viennent.

    L'environnement gagne quand il dit quelque chose : une installation qui le
    pose aujourd'hui doit se comporter demain exactement comme aujourd'hui.

    `cles` est le porte-clés — fichier d'instance sur un poste, mémoire de
    session dans la page — indexé par identifiant de préréglage. Il ne complète
    jamais un réglage venu de l'environnement : celui-ci porte déjà la sienne,
    et emprunter la clé d'un autre point de terminaison est exactement ce que
    la règle du groupe entier interdit.
    """
    from src.core.annotation.annotateur import depuis_l_environnement

    depuis_l_env = depuis_l_environnement(environnement, usage)
    if depuis_l_env.actif:
        return depuis_l_env, ORIGINE_ENVIRONNEMENT

    reglages = configuration.reglages(usage)
    if not reglages.actif:
        return Reglages(), ORIGINE_ABSENTE

    reference = configuration.par_usage.get(usage) or configuration.commun
    cle = str(cles.get(reference, "")) if reference else ""
    return (Reglages(adresse=reglages.adresse, modele=reglages.modele,
                     cle=cle, delai_s=reglages.delai_s),
            ORIGINE_CONFIGURATION)
