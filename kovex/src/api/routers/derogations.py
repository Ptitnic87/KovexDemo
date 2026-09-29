# Fichier : src/api/routers/derogations.py
"""Accorder, lister et retirer une exception assumée.

Trois routes, et leur asymétrie dit la conception.

Accorder est un **ajout**, pas un remplacement : une dérogation est un acte
daté, pas un état d'écran. Les remplacer en bloc ferait perdre celles qu'un
autre poste vient d'accorder — et c'est précisément sur ce genre d'objet que
deux personnes travaillent en même temps.

Lister rend **tout**, y compris ce qui a expiré. Une dérogation périmée n'est
pas un déchet : elle raconte ce qui a été décidé et quand cela a cessé de valoir,
et c'est la première chose qu'un auditeur demande.

Retirer est le seul cas où une dérogation disparaît du document. Retirer est une
décision — on rend le constat à la liste des choses à traiter — là où expirer est
le cours normal des choses.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.api.dependencies import get_data_loader, get_kb
from src.api.journal import Journal, get_journal
from src.core.audit.piste_audit import Action
from src.core.data.loader import DataLoader
from src.core.knowledge.derogations import (ACCORDEE, CIBLES, DEMANDEE,
                                            FAMILLES, MOTIF_MAX, REFUSEE,
                                            VALEUR_MAX, DerogationInvalide,
                                            Reglages, couvertures)
from src.core.knowledge.knowledge_base import KnowledgeBase
from src.core.security.auth import User, require_permission_or_dev

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/derogations", tags=["Dérogations"])

#: Assumer une exception est une décision de gouvernance, au même titre que
#: déclarer une règle ou écarter une identité de l'analyse : celui qui conduit
#: l'étude en répond.
PERMISSION = "mining"


class DerogationDemandee(BaseModel):
    """Ce que l'écran envoie pour accorder une exception.

    Ni identifiant, ni date d'octroi, ni auteur : ils viennent du serveur.
    Laisser l'appelant écrire sa propre date d'octroi permettrait d'antidater
    une décision, et laisser écrire l'auteur permettrait de l'attribuer à
    quelqu'un d'autre — sur l'objet qui fait taire un signalement, ce sont les
    deux champs qu'il ne faut surtout pas accepter de l'extérieur.
    """

    model_config = ConfigDict(extra="forbid")

    famille: str = Field(..., min_length=1, max_length=32)
    cible: Dict[str, str] = Field(default_factory=dict)
    motif: str = Field(..., min_length=1, max_length=MOTIF_MAX)
    echeance: str = Field(..., min_length=10, max_length=10)
    #: Le contrôle compensatoire que la dérogation cite. Facultatif, sauf si
    #: le workspace l'exige — et alors une dérogation sans contrôle s'accorde,
    #: mais ne couvre rien, et l'écran dit pourquoi.
    controle: str = Field(default="", max_length=64)

    @field_validator("famille")
    @classmethod
    def _famille_connue(cls, valeur):
        if valeur not in CIBLES:
            raise ValueError(
                f"famille inconnue : {valeur!r} (attendu : {', '.join(FAMILLES)})")
        return valeur

    @field_validator("cible")
    @classmethod
    def _cible_bornee(cls, valeur):
        for cle, contenu in valeur.items():
            if len(str(cle)) > VALEUR_MAX or len(str(contenu)) > VALEUR_MAX:
                raise ValueError("cible trop longue")
        return valeur


def _reglages(loader: DataLoader) -> Reglages:
    return Reglages.depuis_la_configuration(loader.config)


def raisons_de_statut(derogation) -> List[Dict[str, Any]]:
    """Pourquoi une dérogation non accordée ne couvre rien : elle attend, ou
    elle a été refusée. Nommé comme les raisons d'un contrôle, pour que
    l'écran les dise de la même façon."""
    if derogation.statut == DEMANDEE:
        return [{"code": "demandee",
                 "params": {"auteur": derogation.auteur,
                            "date": derogation.accordee_le.isoformat()}}]
    if derogation.statut == REFUSEE:
        return [{"code": "refusee",
                 "params": {"par": derogation.decidee_par,
                            "date": derogation.decidee_le.isoformat()
                            if derogation.decidee_le else "",
                            "motif": derogation.motif_de_refus}}]
    return []


class Refus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    motif: str = Field(..., min_length=1, max_length=MOTIF_MAX)


def evaluateur(kb: KnowledgeBase, reglages: Reglages, aujourdhui: date):
    """Ce qui dit, pour une dérogation, pourquoi elle ne couvre plus rien.

    Le catalogue et les exécutions sont lus une fois : l'évaluateur sert pour
    chaque constat d'un écran, et les relire à chaque fois referait le même
    parcours autant de fois qu'il y a de conflits.
    """
    from src.core.knowledge.controles import raisons

    controles = kb.controles()
    executions = kb.executions_de_controle()
    return lambda derogation: raisons(derogation.controle, controles, executions,
                                      aujourdhui, reglages.controle_exige)


def etat_des_derogations(loader: DataLoader, kb: KnowledgeBase, famille: str):
    """Ce qui couvre aujourd'hui, et ce qui ne couvre plus avec ses raisons.

    Deux index par cible, pour une famille : les dérogations qui font taire
    leur constat, et celles qui existent, courent encore, et ne le font plus
    taire — demandées, refusées, ou privées de leur contrôle. Un constat qui
    revient alors qu'on l'avait accepté doit dire pourquoi.

    Lu une fois par écran, pour toutes les cibles : relire par constat
    referait le même parcours autant de fois qu'il y en a.
    """
    reglages = _reglages(loader)
    aujourdhui = _aujourdhui()
    evaluer = evaluateur(kb, reglages, aujourdhui)
    derogations = kb.derogations(reglages)
    couvertes = couvertures(derogations, famille, aujourdhui, evaluer)
    inoperantes = {}
    for derogation in derogations:
        if derogation.famille != famille or derogation.expiree(aujourdhui):
            continue
        motifs = raisons_de_statut(derogation) + evaluer(derogation)
        if motifs:
            inoperantes[derogation.cle[1]] = {**derogation.en_dict(), "raisons": motifs}
    return couvertes, inoperantes


def _aujourdhui() -> date:
    """Le jour, isolé pour que les tests puissent le fixer.

    Une échéance se juge contre une date réelle : c'est un fait de calendrier,
    pas un réglage. Mais un test qui dépendrait du jour où il tourne cesserait
    de dire quelque chose au bout de quelques mois.
    """
    return date.today()


@router.get("")
async def lister(
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    user: User = Depends(require_permission_or_dev(PERMISSION)),
) -> Dict[str, Any]:
    """Toutes les dérogations, avec où chacune en est.

    L'état — expirée, bientôt échue, nombre de jours restants — est **calculé à
    l'affichage** et non conservé : une dérogation rangée comme « active »
    resterait active le lendemain de son échéance, et c'est exactement ce que
    cet objet existe pour empêcher.
    """
    reglages = _reglages(loader)
    aujourdhui = _aujourdhui()
    evaluer = evaluateur(kb, reglages, aujourdhui)
    rendues = []
    for derogation in kb.derogations(reglages):
        document = derogation.en_document(aujourdhui, reglages)
        # Pourquoi elle ne couvre plus son constat — chaque raison. Une
        # dérogation qui en porte une seule ne couvre rien, et c'est ici qu'un
        # auditeur le lit.
        document["raisons"] = raisons_de_statut(derogation) + evaluer(derogation)
        document["couvre"] = not document["expiree"] and not document["raisons"]
        rendues.append(document)
    # Les plus urgentes d'abord : ce qui expire bientôt est du travail qui
    # arrive, et le ranger en bas revient à ne pas l'annoncer.
    rendues.sort(key=lambda une: (une["expiree"], une["jours_restants"],
                                  une["id"]))
    return {"derogations": rendues,
            "duree_max_jours": reglages.duree_max_jours,
            "preavis_jours": reglages.preavis_jours,
            "controle_exige": reglages.controle_exige,
            "approbation_exigee": reglages.approbation_exigee,
            # Ce qui attend une décision : du travail pour quelqu'un d'autre
            # que celui qui a demandé, et le premier chiffre d'un tableau de
            # bord de la séparation des tâches.
            "en_attente": sum(1 for une in rendues
                              if une["statut"] == DEMANDEE and not une["expiree"]),
            "aujourdhui": aujourdhui.isoformat()}


@router.post("")
async def accorder(
    demande: DerogationDemandee,
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
    user: User = Depends(require_permission_or_dev(PERMISSION)),
) -> Dict[str, Any]:
    """Accorde une exception, datée du jour et signée de celui qui la demande."""
    reglages = _reglages(loader)
    aujourdhui = _aujourdhui()
    if demande.controle and demande.controle not in kb.controles():
        # Refusé à la saisie : une dérogation qui cite un contrôle inexistant
        # ne couvrirait jamais rien, et personne ne saurait pourquoi.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "derogation.controle_inconnu",
                    "params": {"controle": demande.controle}})
    brute = {
        "id": str(uuid.uuid4()),
        "famille": demande.famille,
        "cible": demande.cible,
        "motif": demande.motif,
        "auteur": getattr(user, "username", "") or "",
        "accordee_le": aujourdhui.isoformat(),
        "echeance": demande.echeance,
        "controle": demande.controle,
        # Avec approbation exigée, la dérogation naît demandée et ne couvre
        # rien tant qu'une autre personne ne l'a pas approuvée.
        "statut": DEMANDEE if reglages.approbation_exigee else ACCORDEE,
    }
    try:
        accordee = kb.accorder_une_derogation(brute, reglages)
    except DerogationInvalide as erreur:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "derogation.invalide",
                    "params": {"motif": str(erreur)}})

    # La trace porte le motif et l'échéance : c'est la décision qui fait taire
    # un signalement, et « pourquoi ce conflit n'était-il pas remonté » doit se
    # répondre sans rouvrir les données.
    journal.consigner(Action.DEROGATION_ACCORDEE, "derogation",
                      accordee["id"],
                      {"famille": accordee["famille"],
                       "motif": accordee["motif"],
                       "echeance": accordee["echeance"]})
    return accordee


def _trancher(identifiant: str, accorder: bool, motif: str, loader: DataLoader,
              kb: KnowledgeBase, journal: Journal, user: User) -> Dict[str, Any]:
    par = getattr(user, "username", "") or ""
    try:
        tranchee = kb.trancher_une_derogation(identifiant, accorder, par,
                                              _aujourdhui(), motif, _reglages(loader))
    except DerogationInvalide as erreur:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "derogation.invalide", "params": {"motif": str(erreur)}})
    if tranchee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "derogation.inconnue", "params": {"derogation": identifiant}})
    journal.consigner(Action.DEROGATION_APPROUVEE if accorder else Action.DEROGATION_REFUSEE,
                      "derogation", identifiant,
                      {"par": par, "motif_de_refus": tranchee["motif_de_refus"]})
    return tranchee


@router.post("/{identifiant}/approuver")
async def approuver(
    identifiant: str,
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
    user: User = Depends(require_permission_or_dev(PERMISSION)),
) -> Dict[str, Any]:
    """Approuve une dérogation demandée — par une autre personne que le demandeur."""
    return _trancher(identifiant, True, "", loader, kb, journal, user)


@router.post("/{identifiant}/refuser")
async def refuser(
    identifiant: str,
    refus: Refus,
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
    user: User = Depends(require_permission_or_dev(PERMISSION)),
) -> Dict[str, Any]:
    """Refuse une dérogation demandée, avec un motif. Elle reste lisible."""
    return _trancher(identifiant, False, refus.motif, loader, kb, journal, user)


@router.delete("/{identifiant}")
async def retirer(
    identifiant: str,
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
    user: User = Depends(require_permission_or_dev(PERMISSION)),
) -> Dict[str, Any]:
    """Retire une dérogation avant son terme : le constat revient."""
    if not kb.retirer_une_derogation(identifiant):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "derogation.inconnue",
                    "params": {"derogation": identifiant}})
    journal.consigner(Action.DEROGATION_RETIREE, "derogation", identifiant, {})
    return {"retiree": identifiant}
