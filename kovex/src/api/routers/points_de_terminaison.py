"""Configurer où part chaque question, depuis l'écran et non depuis le serveur.

L'adresse, le modèle et le délai se posaient dans l'environnement du serveur.
Sur un poste, c'est la bonne règle. Dans la page, **il n'y a pas
d'environnement** : aucune variable ne peut y être posée, donc aucun des sept
usages d'IA n'y était joignable — pas en erreur, absent.

Ce routeur ajoute la seconde source sans toucher à la première. Ce qui est posé
dans l'environnement le reste, et gagne ; l'écran dit alors que la valeur est
imposée par l'installation, plutôt que de laisser croire qu'on peut la changer
ici.

Trois refus tiennent ce module :

**La clé ne revient jamais.** Elle se pose, elle se retire, et la lecture ne
dit que si elle est posée. Une API qui rend un secret le rend à tout ce qui
sait l'appeler.

**L'adresse imposée par l'installation ne revient pas non plus** — seul son
hôte. Un chemin d'infrastructure peut porter un jeton ; celui que l'utilisateur
a écrit lui-même dans sa configuration lui est rendu tel quel, sans quoi il ne
pourrait pas le corriger.

**Changer de point de terminaison laisse une trace.** Décider *où* part une
question est une décision de gouvernance, au même titre que décider *ce qui*
part : les deux se relisent côte à côte dans la piste d'audit.
"""

import json
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from src.api.dependencies import clear_all_caches
from src.api.journal import Journal, get_journal
from src.api.routers.settings import chemin_de_configuration, lire_la_configuration
from src.core.annotation.annotateur import catalogue_des_modeles
from src.core.annotation.assistance import USAGES_DE_MODELE as USAGES
from src.core.annotation.points_de_terminaison import (
    CLE_POINTS_DE_TERMINAISON, ORIGINE_ENVIRONNEMENT, Configuration,
    depuis_la_configuration, en_document, resoudre)
from src.core.annotation.porte_cles import PorteCles, dans_un_navigateur, get_porte_cles
from src.core.audit.piste_audit import Action
from src.core.security.auth import User, require_permission_or_dev

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/points-de-terminaison")

#: Administration : la carte des sorties possibles d'un système
#: d'habilitations n'a pas à circuler plus largement que la décision qu'elle
#: décrit. Même raisonnement que la matrice d'assistance.
PERMISSION = "admin"


def _environnement() -> Dict[str, str]:
    import os

    return dict(os.environ)


def _lue() -> Configuration:
    return depuis_la_configuration(lire_la_configuration(chemin_de_configuration()))


def _vue_du_prereglage(configuration: Configuration, identifiant: str,
                       anneau: PorteCles) -> Dict[str, Any]:
    prereglage = configuration.prereglage(identifiant)
    return {
        "identifiant": identifiant,
        "libelle": prereglage.libelle if prereglage else "",
        # Rendue telle quelle : c'est l'utilisateur qui l'a écrite, et il ne
        # pourrait pas la corriger sans la relire.
        "adresse": prereglage.adresse if prereglage else "",
        "modele": prereglage.modele if prereglage else "",
        "locale": (urlsplit(prereglage.adresse).hostname in ("127.0.0.1", "localhost")
                   if prereglage else False),
        # Posée ou non : c'est tout ce qu'un écran peut savoir d'une clé.
        "cle_posee": identifiant in anneau,
    }


def _vue_de_l_usage(configuration: Configuration, code: str,
                    anneau: PorteCles) -> Dict[str, Any]:
    environnement = _environnement()
    reglages, source = resoudre(environnement, configuration, anneau, code)
    impose = source == ORIGINE_ENVIRONNEMENT
    return {
        "code": code,
        "origine": source,
        "actif": reglages.actif,
        # Imposé par l'installation : seul l'hôte sort, jamais le chemin.
        "hote": urlsplit(reglages.adresse).hostname or "",
        "modele": reglages.modele,
        "locale": reglages.locale,
        "delai_s": reglages.delai_s,
        "prereglage": "" if impose else (configuration.par_usage.get(code)
                                         or configuration.commun),
        "propre": bool(configuration.par_usage.get(code)),
    }


def _reponse(configuration: Configuration, anneau: PorteCles) -> Dict[str, Any]:
    return {
        "prereglages": [_vue_du_prereglage(configuration, prereglage.identifiant,
                                           anneau)
                        for prereglage in configuration.prereglages],
        "commun": configuration.commun,
        "delai_commun": configuration.delais.get(""),
        "usages": [_vue_de_l_usage(configuration, usage.code, anneau)
                   for usage in USAGES],
        "avertissements": list(configuration.avertissements),
        # Dans la page, la clé vit en mémoire et meurt avec l'onglet. L'écran
        # le dit : une clé qu'on croit enregistrée et qui disparaît au
        # rechargement se paie en confiance.
        "cles_volatiles": dans_un_navigateur(),
    }


@router.get("/")
def lire(user: User = Depends(require_permission_or_dev(PERMISSION))
         ) -> Dict[str, Any]:
    """Les points de terminaison configurés, et qui les a décidés."""
    return _reponse(_lue(), get_porte_cles())


class PrereglageDemande(BaseModel):
    """Un point de terminaison nommé. La clé ne passe pas par ici."""

    model_config = ConfigDict(extra="forbid")

    identifiant: str = Field(min_length=1, max_length=64)
    libelle: str = Field(default="", max_length=120)
    adresse: str = Field(default="", max_length=2048)
    modele: str = Field(default="", max_length=200)


class ChoixDemande(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prereglage: str = Field(default="", max_length=64)
    delai_s: Optional[float] = Field(default=None, gt=0, le=3600)


class PointsDemandes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prereglages: List[PrereglageDemande] = []
    commun: ChoixDemande = ChoixDemande()
    usages: Dict[str, ChoixDemande] = {}


@router.put("/")
def ecrire(demande: PointsDemandes,
           journal: Journal = Depends(get_journal),
           user: User = Depends(require_permission_or_dev(PERMISSION))
           ) -> Dict[str, Any]:
    """Réécrit le bloc dans la configuration du workspace actif."""
    codes = {usage.code for usage in USAGES}
    inconnus = sorted(set(demande.usages) - codes)
    if inconnus:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "endpoints.unknown_usage",
                    "params": {"usage": inconnus[0]}})

    identifiants = [prereglage.identifiant for prereglage in demande.prereglages]
    doublons = sorted({nom for nom in identifiants if identifiants.count(nom) > 1})
    if doublons:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "endpoints.duplicate_preset",
                    "params": {"prereglage": doublons[0]}})

    connus = set(identifiants)
    references = [demande.commun.prereglage] + [
        choix.prereglage for choix in demande.usages.values()]
    manquants = sorted({nom for nom in references if nom and nom not in connus})
    if manquants:
        # Refusé à l'écriture plutôt qu'écarté à la lecture : ici, quelqu'un
        # est devant l'écran pour corriger.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "endpoints.unknown_preset",
                    "params": {"prereglage": manquants[0]}})

    document: Dict[str, Any] = {
        "prereglages": [{"identifiant": prereglage.identifiant,
                         "libelle": prereglage.libelle,
                         "adresse": prereglage.adresse.strip().rstrip("/"),
                         "modele": prereglage.modele.strip()}
                        for prereglage in demande.prereglages],
        "commun": {"prereglage": demande.commun.prereglage},
    }
    if demande.commun.delai_s is not None:
        document["commun"]["delai_s"] = demande.commun.delai_s
    usages: Dict[str, Any] = {}
    for usage in USAGES:
        choix = demande.usages.get(usage.code)
        if choix is None:
            continue
        entree: Dict[str, Any] = {}
        if choix.prereglage:
            entree["prereglage"] = choix.prereglage
        if choix.delai_s is not None:
            entree["delai_s"] = choix.delai_s
        if entree:
            usages[usage.code] = entree
    if usages:
        document["usages"] = usages

    chemin = chemin_de_configuration()
    configuration = lire_la_configuration(chemin)
    configuration[CLE_POINTS_DE_TERMINAISON] = document
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(
            json.dumps(configuration, indent=4, ensure_ascii=False),
            encoding="utf-8")
    except OSError as erreur:
        logger.error("Points de terminaison non enregistrés (%s) : %s",
                     chemin, erreur)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "settings.not_saved"})

    clear_all_caches()

    lue = depuis_la_configuration(configuration)
    for usage in USAGES:
        reglages = lue.reglages(usage.code)
        journal.consigner(
            Action.POINT_DE_TERMINAISON_MODIFIE, "point_de_terminaison",
            usage.code,
            # L'hôte, jamais le chemin ni la clé : la trace dit où part la
            # question, pas comment on s'y authentifie.
            {"hote": urlsplit(reglages.adresse).hostname or "",
             "modele": reglages.modele,
             "locale": reglages.locale})
    return _reponse(lue, get_porte_cles())


class CleDemandee(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cle: str = Field(min_length=1, max_length=512)


def _prereglage_connu(configuration: Configuration, identifiant: str) -> None:
    if configuration.prereglage(identifiant) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "endpoints.unknown_preset",
                    "params": {"prereglage": identifiant}})


@router.put("/prereglages/{identifiant}/cle")
def poser_la_cle(identifiant: str, demande: CleDemandee,
                 user: User = Depends(require_permission_or_dev(PERMISSION))
                 ) -> Dict[str, Any]:
    """Pose la clé d'un préréglage. Elle n'est jamais rendue ensuite."""
    configuration = _lue()
    _prereglage_connu(configuration, identifiant)
    anneau = get_porte_cles()
    anneau.poser(identifiant, demande.cle)
    # Aucune trace de la valeur, ni ici, ni dans le journal : seule la pose
    # d'une clé sur un point de terminaison est un fait consignable, et elle
    # se déduit déjà du changement de point de terminaison.
    logger.info("Clé posée pour le préréglage %s.", identifiant)
    return _reponse(configuration, anneau)


@router.delete("/prereglages/{identifiant}/cle")
def retirer_la_cle(identifiant: str,
                   user: User = Depends(require_permission_or_dev(PERMISSION))
                   ) -> Dict[str, Any]:
    """Retire la clé d'un préréglage."""
    configuration = _lue()
    _prereglage_connu(configuration, identifiant)
    anneau = get_porte_cles()
    anneau.retirer(identifiant)
    return _reponse(configuration, anneau)


def _refus_du_fournisseur(erreur: Exception, adresse: str, code_par_defaut: str,
                          **parametres: Any) -> Dict[str, Any]:
    """Ce que le fournisseur a réellement dit, et non un seul « injoignable ».

    Tout finissait en « n'a pas répondu ». C'était faux dans deux cas sur
    trois, et le faux le plus coûteux est celui de la clé : un fournisseur qui
    répond 401 a parfaitement répondu, et l'utilisateur à qui l'on dit
    « vérifiez l'adresse » vérifie la mauvaise chose.

    Trois familles, qu'on sépare parce qu'elles appellent trois gestes :

    - le fournisseur refuse la clé (401, 403) — la poser ou la changer ;
    - il refuse la demande pour une autre raison — le code le dit ;
    - il a répondu, mais rien de lisible — l'adresse vise autre chose ;
    - il n'a pas répondu du tout — adresse, réseau, ou origine refusée.

    `HTTPError` hérite de `URLError` : l'ordre des tests n'est pas un détail.
    """
    import urllib.error

    hote = urlsplit(adresse).hostname or ""
    if isinstance(erreur, urllib.error.HTTPError):
        if erreur.code in (401, 403):
            return {"code": "endpoints.key_refused",
                    "params": {"hote": hote, "statut": erreur.code}}
        return {"code": code_par_defaut,
                "params": dict(parametres, hote=hote, statut=erreur.code)}
    if isinstance(erreur, ValueError):
        return {"code": "endpoints.provider_unreadable", "params": {"hote": hote}}
    return {"code": "endpoints.provider_unreachable", "params": {"hote": hote}}


@router.get("/prereglages/{identifiant}/modeles")
async def lister_les_modeles(identifiant: str,
                             user: User = Depends(require_permission_or_dev(PERMISSION))
                             ) -> Dict[str, Any]:
    """Les modèles que ce point de terminaison déclare servir.

    Un serveur qui ne sait pas répondre ne fait pas échouer l'écran : la liste
    revient vide et le nom se saisit à la main. Un serveur injoignable, lui,
    est un fait que l'utilisateur doit connaître avant d'enregistrer.
    """
    configuration = _lue()
    _prereglage_connu(configuration, identifiant)
    prereglage = configuration.prereglage(identifiant)
    if not prereglage.adresse:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "endpoints.preset_without_address",
                    "params": {"prereglage": identifiant}})

    from src.core.annotation.annotateur import Reglages

    reglages = Reglages(adresse=prereglage.adresse.rstrip("/"),
                        modele=prereglage.modele or "-",
                        cle=get_porte_cles().get(identifiant),
                        delai_s=configuration.delais.get("", 30.0))
    try:
        modeles = await run_in_threadpool(catalogue_des_modeles, reglages)
    except Exception as erreur:  # réseau, refus d'origine, clé, serveur muet
        logger.info("Catalogue des modèles indisponible (%s) : %s",
                    prereglage.adresse, type(erreur).__name__)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_refus_du_fournisseur(erreur, prereglage.adresse,
                                         "endpoints.provider_refused"))
    return {"prereglage": identifiant, "modeles": modeles}


#: Ce que l'essai envoie : le strict minimum du protocole, et rien d'autre.
#:
#: Il portait `max_tokens` et `temperature`. C'était une préférence, pas une
#: nécessité, et elle se retournait contre l'essai : plusieurs fournisseurs
#: refusent ces paramètres sur leurs modèles récents — `temperature` sur les
#: modèles à raisonnement, `max_tokens` remplacé par `max_completion_tokens`.
#: L'essai échouait alors sur un point de terminaison parfaitement utilisable,
#: ce qui est le pire résultat possible pour un bouton dont le seul travail
#: est de dire si ça marche.
CHARGE_D_ESSAI = {"messages": [{"role": "user", "content": "ping"}]}


@router.post("/prereglages/{identifiant}/essai")
async def essayer(identifiant: str,
                  user: User = Depends(require_permission_or_dev(PERMISSION))
                  ) -> Dict[str, Any]:
    """Un vrai aller-retour, et ce qu'il a coûté en temps.

    Ce que l'essai prouve : l'adresse répond, le modèle existe, la clé est
    acceptée. Ce qu'il ne prouve pas : que la réponse sera utile. Il est dit
    ainsi à l'écran plutôt qu'affiché comme une pastille verte.

    Aucune donnée du client ne part : la charge est fixe et ne contient qu'un
    mot.
    """
    import time

    from src.core.annotation.annotateur import Reglages, _poster

    configuration = _lue()
    _prereglage_connu(configuration, identifiant)
    prereglage = configuration.prereglage(identifiant)
    if not prereglage.complet:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "endpoints.preset_incomplete",
                    "params": {"prereglage": identifiant}})

    reglages = Reglages(adresse=prereglage.adresse.rstrip("/"),
                        modele=prereglage.modele,
                        cle=get_porte_cles().get(identifiant),
                        delai_s=configuration.delais.get("", 30.0))
    charge = dict(CHARGE_D_ESSAI, model=reglages.modele)
    debut = time.monotonic()
    try:
        await run_in_threadpool(_poster, charge, reglages)
    except Exception as erreur:  # réseau, refus d'origine, clé, modèle inconnu
        logger.info("Essai refusé par %s : %s", reglages.adresse,
                    type(erreur).__name__)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_refus_du_fournisseur(erreur, reglages.adresse,
                                         "endpoints.trial_refused",
                                         modele=reglages.modele))
    return {"prereglage": identifiant,
            "millisecondes": round((time.monotonic() - debut) * 1000),
            "locale": reglages.locale}
