# Fichier : src/api/routers/agent.py
"""L'agent de navigation : une question, une réponse calculée.

Le trajet habituel pour répondre à « qui porte ce rôle » est : ouvrir le
catalogue, trouver le rôle, ouvrir son détail, lire le tableau des porteurs.
Trois écrans et deux filtres pour une question d'une ligne. Cet agent
raccourcit ce trajet ; il n'invente aucune mesure et n'ouvre aucune donnée
nouvelle.

Trois règles, qui sont toute la conception :

1. **le modèle ne choisit qu'un mot.** Le routage local par mots-clés répond
   d'abord ; le modèle n'est appelé que s'il hésite, et rend un code
   d'intention pris dans une liste fermée. Aucun chiffre, aucune phrase, aucun
   nom ne passe par lui ;
2. **les entités sont reconnues dans les données**, localement, par
   comparaison de chaînes. Un rôle que la question ne nomme pas ne se devine
   pas : l'agent demande de quoi on parle ;
3. **la réponse est calculée**. La phrase vient du catalogue de traduction, les
   chiffres du même calcul que l'écran correspondant. Deux réponses
   différentes sur le même objet, c'est le défaut que ce produit passe son
   temps à corriger.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import (Any, Callable, Dict, FrozenSet, List, Mapping, Optional,
                    Sequence, Tuple)

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from src.api.dependencies import get_data_loader, get_kb
from src.api.journal import Journal, get_journal
from src.core.annotation.annotateur import (
    AnnotateurIndisponible,
    ReponseInexploitable,
    depuis_l_environnement,
    envoyer,
)
from src.core.annotation.annotateur import RienANommer
from src.core.annotation.assistance import USAGE_AGENT_DE_NAVIGATION
from src.core.annotation.redaction import (SCHEMA_DE_LA_REPONSE, ReponseRefusee,
                                           rediger)
from src.core.annotation.navigateur import (
    CANDIDATS_MAX,
    PAR_CODE,
    ENTITE_DROIT,
    ENTITE_IDENTITE,
    ENTITE_ROLE,
    INTENTIONS,
    LONGUEUR_QUESTION_MAX,
    ORIGINE_LOCALE,
    SCHEMA_DU_ROUTAGE,
    Candidat,
    Routage,
    reconnaitre,
    router_localement,
    router_par_le_modele,
)
from src.core.audit.piste_audit import Action
from src.core.data.loader import DataLoader
from src.core.knowledge.knowledge_base import KnowledgeBase
from src.core.knowledge.population import (detenteurs_par_droit,
                                            droits_par_identite,
                                            porteurs_du_role)
from src.core.knowledge.privileges import marques_parmi_les_comptes
from src.core.knowledge.socle import (IDENTIFIANT_SOCLE, membres_du_socle,
                                      socle_du_workspace)
from src.core.security.auth import User, require_permission_or_dev
from src.infrastructure.i18n_manager import i18n

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["Agent de navigation"])

#: Poser une question est un geste d'analyste, comme lancer un mining.
PERMISSION = "mining"

#: Lignes rendues avec une réponse. Le tableau qui les affiche pagine, mais la
#: réponse elle-même n'a pas à transporter un référentiel entier : au-delà, on
#: renvoie vers l'écran, qui est fait pour ça.
LIGNES_MAX = 500

#: Au-delà, les identités ne sont reconnues que par leur identifiant.
#:
#: Reconnaître « Jean Dupont » demande de parcourir toutes les colonnes de
#: toutes les lignes — le produit ne sait pas laquelle porte un nom, il n'en
#: connaît aucune à l'avance. Sur un référentiel de cette taille, le parcours
#: coûterait plus que la question ne vaut, et l'agent le dit plutôt que de
#: faire attendre.
IDENTITES_PARCOURUES_MAX = 200_000


class Question(BaseModel):
    """Une question, et la langue dans laquelle y répondre."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field("", max_length=LONGUEUR_QUESTION_MAX)
    locale: str = Field("fr", max_length=10)
    #: Intention imposée par l'utilisateur, quand l'écran lui a fait choisir.
    intention: Optional[str] = Field(None, max_length=100)
    #: Entité imposée, même raison : la question citait deux rôles.
    entite: Optional[str] = Field(None, max_length=200)
    #: Ce dont parlait l'échange précédent. C'est ce qui permet d'écrire
    #: « et ses rôles ? » au lieu de répéter le matricule à chaque question :
    #: sans sujet nommé, la question porte sur le précédent.
    contexte: Optional[Dict[str, str]] = None


def _traducteur(langue: str) -> Callable[[str], str]:
    def traduire(cle: str) -> str:
        return i18n.t(cle, locale=langue)
    return traduire


def _roles_connus(kb: KnowledgeBase) -> List[Tuple[str, str]]:
    """Les rôles du catalogue, socle compris, sous forme (identifiant, nom)."""
    entites = [(str(role.get("id") or ""), str(role.get("name") or ""))
               for role in kb.get_validated_roles()]
    socle = socle_du_workspace(kb)
    if socle.existe:
        entites.append((IDENTIFIANT_SOCLE, socle.nom))
    return [couple for couple in entites if couple[0]]


def _droits_connus(loader: DataLoader) -> List[Tuple[str, str]]:
    cadre = loader.rights
    if cadre is None or cadre.empty or DataLoader.COL_RIGHT_ID not in cadre.columns:
        return []
    return [(str(valeur), "") for valeur in
            cadre[DataLoader.COL_RIGHT_ID].dropna().astype(str).unique()]


def _identites_connues(loader: DataLoader) -> List[Tuple[str, str]]:
    """Les identités, avec ce qui pourrait servir à les nommer.

    Le libellé est la ligne entière, colonnes accolées : le produit ne sait pas
    laquelle porte un nom — il n'en connaît aucune à l'avance — et c'est la
    seule façon de reconnaître « Jean Dupont » sans présumer d'une colonne
    `nom`.
    """
    cadre = loader.identities
    if cadre is None or cadre.empty or DataLoader.COL_USER_ID not in cadre.columns:
        return []
    if len(cadre) > IDENTITES_PARCOURUES_MAX:
        return [(str(valeur), "") for valeur in
                cadre[DataLoader.COL_USER_ID].astype(str)]
    autres = [colonne for colonne in cadre.columns
              if colonne != DataLoader.COL_USER_ID]
    entites: List[Tuple[str, str]] = []
    for ligne in cadre.to_dict("records"):
        identifiant = str(ligne.get(DataLoader.COL_USER_ID, "") or "")
        if not identifiant:
            continue
        libelle = " ".join(str(ligne.get(colonne, "") or "") for colonne in autres)
        entites.append((identifiant, libelle.strip()))
    return entites


ENTITES: Dict[str, Callable[[DataLoader, KnowledgeBase], List[Tuple[str, str]]]] = {
    ENTITE_ROLE: lambda loader, kb: _roles_connus(kb),
    ENTITE_DROIT: lambda loader, kb: _droits_connus(loader),
    ENTITE_IDENTITE: lambda loader, kb: _identites_connues(loader),
}


@dataclass
class Reponse:
    """Ce que l'agent rend : une phrase à remplir, et de quoi la vérifier.

    `params` sont les valeurs de la phrase traduite — des comptes, jamais du
    texte rédigé. `lignes` désigne les données à montrer sous la phrase, et
    `ecran` la page où les voir en grand : une réponse qui ne ramène pas à
    l'écran concerné laisse l'utilisateur dans une impasse à la question
    suivante.
    """

    params: Dict[str, Any] = field(default_factory=dict)
    referentiel: str = ""
    identifiants: List[str] = field(default_factory=list)
    ecran: Dict[str, Any] = field(default_factory=dict)
    #: Ce que le tableau montre, en une clé de traduction. Un tableau sans
    #: légende sous une phrase qui parle d'autre chose se lit comme un
    #: tableau faux : « 2 droits qu'aucun rôle n'explique » au-dessus des
    #: cinquante droits de la personne, personne ne fait le rapprochement.
    legende: str = ""


# ------------------------------------------------------- les dix réponses


def _role_ou_rien(kb: KnowledgeBase, identifiant: str) -> Dict[str, Any]:
    role = kb.get_role_by_id(identifiant)
    return role or {}


def _porteurs_du_role(loader: DataLoader, kb: KnowledgeBase,
                      identifiant: str) -> Reponse:
    if identifiant == IDENTIFIANT_SOCLE:
        membres = membres_du_socle(loader, kb, DataLoader.COL_USER_ID)
        nom = socle_du_workspace(kb).nom
    else:
        role = _role_ou_rien(kb, identifiant)
        membres = porteurs_du_role(role, loader.identities,
                                   DataLoader.COL_USER_ID, loader.habilitations,
                                   DataLoader.COL_RIGHT_ID)
        nom = str(role.get("name") or identifiant)
    return Reponse(params={"role": nom, "porteurs": len(membres)},
                   referentiel="identities", identifiants=membres[:LIGNES_MAX],
                   legende="agent.tableau.porteurs",
                   ecran={"role_id": identifiant, "filtre": nom})


def _droits_du_role(loader: DataLoader, kb: KnowledgeBase,
                    identifiant: str) -> Reponse:
    if identifiant == IDENTIFIANT_SOCLE:
        socle = socle_du_workspace(kb)
        droits, nom = list(socle.droits), socle.nom
    else:
        role = _role_ou_rien(kb, identifiant)
        droits = [str(droit) for droit in (role.get("rights") or ())]
        nom = str(role.get("name") or identifiant)
    return Reponse(params={"role": nom, "droits": len(droits)},
                   referentiel="rights", identifiants=sorted(droits)[:LIGNES_MAX],
                   legende="agent.tableau.droits_du_role",
                   ecran={"role_id": identifiant, "filtre": nom})


def _detenteurs_du_droit(loader: DataLoader, kb: KnowledgeBase,
                         identifiant: str) -> Reponse:
    detenteurs = detenteurs_par_droit(
        loader.habilitations, DataLoader.COL_USER_ID, DataLoader.COL_RIGHT_ID,
        {identifiant}).get(identifiant, set())
    total = 0
    if loader.identities is not None and not loader.identities.empty:
        total = len(loader.identities)
    porteurs = sorted(detenteurs)
    part = round(100.0 * len(porteurs) / total, 1) if total else 0.0
    return Reponse(params={"droit": identifiant, "detenteurs": len(porteurs),
                           "part_pct": part},
                   referentiel="identities", identifiants=porteurs[:LIGNES_MAX],
                   legende="agent.tableau.detenteurs",
                   ecran={"droit_id": identifiant, "filtre": identifiant})


def _roles_de_l_identite(loader: DataLoader, kb: KnowledgeBase,
                         identifiant: str) -> Reponse:
    porteurs: List[str] = []
    for role in kb.get_validated_roles():
        membres = porteurs_du_role(role, loader.identities,
                                   DataLoader.COL_USER_ID, loader.habilitations,
                                   DataLoader.COL_RIGHT_ID)
        if identifiant in membres:
            porteurs.append(str(role.get("id") or ""))
    socle = socle_du_workspace(kb)
    if socle.existe and identifiant in membres_du_socle(
            loader, kb, DataLoader.COL_USER_ID):
        porteurs.insert(0, IDENTIFIANT_SOCLE)
    return Reponse(params={"identite": identifiant, "roles": len(porteurs)},
                   referentiel="", identifiants=porteurs[:LIGNES_MAX],
                   ecran={"identite_id": identifiant, "filtre": identifiant})


def _droits_de_l_identite(loader: DataLoader, kb: KnowledgeBase,
                          identifiant: str) -> Reponse:
    detenus = droits_par_identite(loader.habilitations, DataLoader.COL_USER_ID,
                                  DataLoader.COL_RIGHT_ID).get(identifiant, set())
    # Ce qu'un rôle du catalogue explique déjà : le reste est ce que cette
    # personne détient sans qu'aucun rôle ne le justifie, et c'est la seule
    # partie intéressante de la réponse.
    expliques: set = set()
    for role in kb.get_validated_roles():
        membres = porteurs_du_role(role, loader.identities,
                                   DataLoader.COL_USER_ID, loader.habilitations,
                                   DataLoader.COL_RIGHT_ID)
        if identifiant in membres:
            expliques |= {str(droit) for droit in (role.get("rights") or ())}
    socle = socle_du_workspace(kb)
    if socle.existe:
        expliques |= set(socle.droits)
    hors_role = sorted(detenus - expliques)
    # Le tableau montre ce dont la phrase parle : les droits qu'aucun rôle
    # n'explique quand il y en a, et c'est la seule partie sur laquelle il y a
    # quelque chose à décider. Les cinquante droits d'une personne sous une
    # phrase qui en annonce deux, personne ne fait le rapprochement.
    montres = hors_role or sorted(detenus)
    return Reponse(params={"identite": identifiant, "droits": len(detenus),
                           "hors_role": len(hors_role)},
                   referentiel="rights", identifiants=montres[:LIGNES_MAX],
                   legende=("agent.tableau.droits_hors_role" if hors_role
                            else "agent.tableau.droits_detenus"),
                   ecran={"identite_id": identifiant, "filtre": identifiant})


def _roles_en_sur_octroi(loader: DataLoader, kb: KnowledgeBase,
                         _: str = "") -> Reponse:
    """Les rôles qui accordent le plus de droits que leurs porteurs n'ont pas.

    La mesure vient de la revue du modèle, pas d'un calcul refait ici : c'est
    le même chiffre que la carte du rôle et que sa fenêtre de détail.
    """
    from src.api.routers.knowledge import _revue_du_modele

    revue = _revue_du_modele(loader, kb)
    classes = sorted(
        (entree for entree in revue["roles"]
         if (entree.get("apres") or {}).get("over_granted")),
        key=lambda entree: -(entree["apres"]["over_granted"]))
    total = sum(entree["apres"]["over_granted"] for entree in classes)
    return Reponse(params={"roles": len(classes), "sur_octroi": total},
                   identifiants=[entree["role_id"] for entree in classes][:LIGNES_MAX],
                   ecran={})


def _roles_sans_reference(loader: DataLoader, kb: KnowledgeBase,
                          _: str = "") -> Reponse:
    """Ceux dont la revue ne peut rien dire, faute de point de comparaison."""
    from src.api.routers.knowledge import _revue_du_modele

    revue = _revue_du_modele(loader, kb)
    sans = [entree["role_id"] for entree in revue["roles"]
            if not entree.get("compare")]
    return Reponse(params={"roles": len(sans),
                           "total": len(revue["roles"])},
                   identifiants=sans[:LIGNES_MAX], ecran={})


def _le_socle(loader: DataLoader, kb: KnowledgeBase, _: str = "") -> Reponse:
    from src.api.routers.knowledge import _detail_du_socle

    detail = _detail_du_socle(loader, kb)
    if detail is None:
        return Reponse(params={"droits": 0, "porteurs": 0, "adherence_pct": 0.0},
                       identifiants=[], ecran={})
    mesures = detail["mesures"]
    return Reponse(
        params={"droits": mesures["right_count"], "porteurs": mesures["user_count"],
                "adherence_pct": mesures["fit_pct"]},
        referentiel="rights",
        identifiants=[entree["droit"] for entree in detail["droits"]][:LIGNES_MAX],
        legende="agent.tableau.droits_du_socle",
        ecran={"role_id": IDENTIFIANT_SOCLE})


def _compte_du_catalogue(loader: DataLoader, kb: KnowledgeBase,
                         _: str = "") -> Reponse:
    roles = kb.get_validated_roles()
    metiers = sum(1 for role in roles if str(role.get("role_type")) == "METIER")
    socle = socle_du_workspace(kb)
    return Reponse(params={"roles": len(roles), "metiers": metiers,
                           "applicatifs": len(roles) - metiers,
                           "socle": 1 if socle.existe else 0},
                   identifiants=[str(role.get("id") or "") for role in roles][:LIGNES_MAX],
                   ecran={})


def _travail_en_attente(loader: DataLoader, kb: KnowledgeBase,
                        _: str = "") -> Reponse:
    from src.core.knowledge.travail_en_attente import travail_en_attente
    from src.core.role.identite import TYPES_DE_ROLE

    etat = travail_en_attente(kb, TYPES_DE_ROLE, loader.empreinte_donnees())
    return Reponse(params={"candidats": etat["total"],
                           "obsolete": 1 if etat["stale"] else 0},
                   identifiants=[], ecran={})


#: Le calcul de chaque intention. Une intention sans entrée ici ne peut pas
#: être proposée : le routage la reconnaîtrait et la réponse serait vide.
CALCULS: Dict[str, Callable[[DataLoader, KnowledgeBase, str], Reponse]] = {
    "porteurs_du_role": _porteurs_du_role,
    "droits_du_role": _droits_du_role,
    "detenteurs_du_droit": _detenteurs_du_droit,
    "roles_de_l_identite": _roles_de_l_identite,
    "droits_de_l_identite": _droits_de_l_identite,
    "roles_en_sur_octroi": _roles_en_sur_octroi,
    "roles_sans_reference": _roles_sans_reference,
    "le_socle": _le_socle,
    "compte_du_catalogue": _compte_du_catalogue,
    "travail_en_attente": _travail_en_attente,
}




# ------------------------------------------------- plusieurs comptes, une personne

#: Comptes d'une même personne traités ensemble. Au-delà, la question était
#: trop vague pour être levée autrement qu'en demandant.
COMPTES_MAX = 5

#: Entités pour lesquelles plusieurs correspondances se répondent **ensemble**.
#:
#: Deux rôles différents sont deux objets différents : demander lequel est la
#: seule réponse juste. Deux comptes qui portent le même nom de personne sont
#: le plus souvent la même personne — un compte nominatif et un compte
#: d'administration — et la question posée porte sur elle, pas sur l'un de ses
#: comptes. Lui faire choisir, c'est lui faire poser deux fois sa question et
#: additionner lui-même.
ENSEMBLE: Tuple[str, ...] = (ENTITE_IDENTITE,)


def _emplacements(sujets: Sequence[Dict[str, Any]],
                  marques: FrozenSet[str] = frozenset()) -> Dict[str, Any]:
    """Les grandeurs offertes à la rédaction, nommées.

    Un seul sujet : les noms tels quels — `porteurs`, `role`. Plusieurs : le
    même nom suffixé du rang, plus leur nombre. Le modèle ne reçoit que ces
    noms ; les valeurs restent ici.

    Un compte marqué reçoit **un emplacement de plus**, `a_privileges_<rang>`,
    qui porte son identifiant. Le nom de l'emplacement dit ce qu'il est, la
    valeur reste ici : c'est ainsi que le modèle peut écrire « le compte
    {a_privileges_2} est un compte d'administration » sans jamais avoir lu un
    identifiant. Sans cet emplacement, il n'avait aucun moyen de distinguer
    deux comptes d'une même personne — et il ne le supposait pas, ce qui était
    juste, mais laissait l'analyste le lire lui-même.
    """
    if len(sujets) == 1:
        emplacements = dict(sujets[0]["reponse"]["params"])
        if sujets[0]["identifiant"] in marques:
            emplacements["a_privileges"] = sujets[0]["identifiant"]
        return emplacements
    emplacements: Dict[str, Any] = {"comptes": len(sujets)}
    for rang, sujet in enumerate(sujets, start=1):
        for nom, valeur in sujet["reponse"]["params"].items():
            emplacements[f"{nom}_{rang}"] = valeur
        emplacements[f"compte_{rang}"] = sujet["identifiant"]
        if sujet["identifiant"] in marques:
            emplacements[f"a_privileges_{rang}"] = sujet["identifiant"]
    return emplacements


def _recoupement_des_comptes(loader: DataLoader,
                             identifiants: Sequence[str],
                             marques: FrozenSet[str] = frozenset()
                             ) -> Dict[str, Any]:
    """Ce que plusieurs comptes d'une même personne ont en commun.

    Le produit ne suppose toujours rien de ce que ces comptes sont : `adm`
    signale un compte d'administration chez l'un et l'abréviation
    d'« administratif » chez l'autre, et la règle n'est écrite nulle part dans
    le code. Elle est **déclarée par le client**, dans les paramètres du
    workspace, et `marques` en est le résultat sur ces comptes-ci. Rien n'est
    marqué tant que rien n'est déclaré, et la réponse est alors celle d'avant.

    Le reste se calcule comme avant : combien de droits ces comptes partagent.
    Zéro droit commun entre deux comptes d'une même personne est le
    signalement qui compte pour un auditeur — ce sont deux accès distincts, qui
    s'additionnent. Adossé au marquage, il dit quelque chose de plus précis
    encore : l'un de ces deux accès disjoints est un accès d'administration.
    """
    detenus = droits_par_identite(loader.habilitations, DataLoader.COL_USER_ID,
                                  DataLoader.COL_RIGHT_ID)
    jeux = [detenus.get(identifiant, set()) for identifiant in identifiants]
    communs = set.intersection(*jeux) if jeux else set()
    return {"comptes": len(identifiants), "communs": len(communs),
            "cumul": len(set().union(*jeux)) if jeux else 0,
            "a_privileges": sum(1 for identifiant in identifiants
                                if identifiant in marques)}


def _marques(loader: DataLoader, identifiants: Sequence[str]
             ) -> FrozenSet[str]:
    """Lesquels de ces comptes la déclaration du workspace marque.

    Le marquage se fait sur la valeur portée par les identités chargées, et
    non sur l'identifiant tel que la question l'a écrit : la colonne où
    chercher est déclarée, et ce peut être une autre colonne que
    l'identifiant. Passer par le référentiel garantit que l'agent marque
    exactement ce que l'écran des paramètres a dénombré.
    """
    return marques_parmi_les_comptes(loader.identities,
                                     loader.config.privileges,
                                     DataLoader.COL_USER_ID, identifiants)


def _sujet(loader: DataLoader, kb: KnowledgeBase, intention, identifiant: str
           ) -> Dict[str, Any]:
    reponse = CALCULS[intention.code](loader, kb, identifiant)
    return {
        "identifiant": identifiant,
        "reponse": {"cle": intention.cle_reponse, "params": reponse.params},
        "lignes": {"referentiel": reponse.referentiel,
                   "identifiants": reponse.identifiants,
                   "legende": reponse.legende}
                  if reponse.referentiel else {},
        "ecran": {"page": intention.ecran, **reponse.ecran},
    }


# ----------------------------------------------------------------- la route


def _choix(cle: str, options: Sequence[Dict[str, str]]) -> Dict[str, Any]:
    """Ce que l'agent rend quand il ne peut pas trancher seul.

    Il ne devine pas : répondre sur un rôle voisin de celui demandé est pire
    que demander lequel.
    """
    return {"cle": cle, "options": list(options)}


def _vide(question: str, **reste) -> Dict[str, Any]:
    """La forme de réponse commune, pour qu'un appelant n'ait jamais à
    vérifier la présence d'une clé."""
    socle = {"question": question, "intention": "", "origine": "",
             "sujets": [], "entite": {}, "reponse": {"cle": "", "params": {}},
             "entete": {}, "redaction": {}, "choix": {},
             "contexte": {}, "lignes": {}, "ecran": {}}
    socle.update(reste)
    return socle


def _router(loader: DataLoader, kb: KnowledgeBase, demande: Question,
            question: str, traduire: Callable[[str], str]) -> Routage:
    """L'intention, par les mots puis par les données.

    Le modèle n'intervient pas ici : il est appelé par `_repondre`, qui sait
    aussi quoi faire de son silence.
    """
    if demande.intention:
        intention = PAR_CODE.get(demande.intention)
        if intention is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "agent.intention_inconnue",
                        "params": {"intention": demande.intention}})
        return Routage(intention=intention, origine="utilisateur")

    routage = router_localement(question, traduire)
    if routage.intention is None and routage.candidates:
        # Départage par les données : à mots égaux, la question qui trouve son
        # objet l'emporte sur celle qui ne le trouve pas. Le sujet de l'échange
        # précédent compte comme un objet trouvé — « et ses droits ? » après une
        # question sur un rôle porte sur ce rôle, et le demander serait faire
        # répéter ce qui vient d'être dit.
        type_precedent = (demande.contexte or {}).get("type") or ""
        retenues = [intention for intention in routage.candidates
                    if not intention.entite
                    or intention.entite == type_precedent
                    or reconnaitre(question, ENTITES[intention.entite](loader, kb))]
        if len(retenues) == 1:
            return Routage(intention=retenues[0], origine=ORIGINE_LOCALE)
        if retenues:
            return Routage(candidates=tuple(retenues))
    return routage


def _entites_de_la_question(loader: DataLoader, kb: KnowledgeBase,
                            intention, question: str,
                            demande: Question) -> List[str]:
    """Les entités sur lesquelles porter la réponse, dans l'ordre de la
    reconnaissance.

    L'entité imposée par l'écran l'emporte : elle vient d'un choix. À défaut,
    celle de l'échange précédent sert de sujet tant que la question n'en nomme
    pas d'autre — c'est ce qui permet d'écrire « et ses rôles ? » au lieu de
    répéter le matricule à chaque question.
    """
    if demande.entite:
        return [demande.entite]
    trouves = [candidat.identifiant
               for candidat in reconnaitre(question,
                                           ENTITES[intention.entite](loader, kb))]
    if trouves:
        return trouves
    contexte = demande.contexte or {}
    if (contexte.get("entite") and contexte.get("type") == intention.entite):
        return [str(contexte["entite"])]
    return []


def _redigee(loader: DataLoader, demande: Question, question: str,
             intention, sujets: Sequence[Dict[str, Any]],
             traduire: Callable[[str], str],
             recoupement: Mapping[str, Any] = None,
             marques: FrozenSet[str] = frozenset()) -> Dict[str, Any]:
    """La réponse rédigée, quand l'administrateur l'a ouverte.

    Un refus n'interrompt rien : la phrase calculée reste, et l'écran affiche
    la réponse du produit plutôt que rien. C'est la même règle que partout
    ailleurs — l'assistance dégrade, elle ne casse pas.
    """
    from src.api.reglages_du_modele import reglages_pour

    reglages = reglages_pour(USAGE_AGENT_DE_NAVIGATION.code)
    autorisation = loader.config.assistance.pour(USAGE_AGENT_DE_NAVIGATION.code)
    emplacements = _emplacements(sujets, marques)
    emplacements.update(recoupement or {})
    try:
        rendu = rediger(reglages, autorisation, question,
                        traduire(intention.cle_libelle), emplacements,
                        demande.locale,
                        lambda charge: envoyer(charge, reglages,
                                               SCHEMA_DE_LA_REPONSE))
    except ReponseRefusee as refus:
        # Ce n'est pas une panne : c'est le contrôle qui a fait son travail.
        logger.info("Réponse rédigée refusée : %s", refus)
        return {}
    except (AnnotateurIndisponible, RienANommer, ReponseInexploitable) as refus:
        logger.info("Aucune rédaction : %s", refus)
        return {}
    return {"texte": rendu["reponse"], "modele": rendu["modele"]}


def _repondre(loader: DataLoader, kb: KnowledgeBase, demande: Question,
              traduire: Callable[[str], str]) -> Dict[str, Any]:
    """Route la question, résout les entités, calcule, puis fait rédiger.

    L'ordre n'est pas indifférent : le routage local d'abord, parce qu'il ne
    fait rien sortir ; le modèle ensuite, et seulement si l'administrateur l'a
    ouvert. Un produit installé sur un serveur sans accès répond quand même.
    """
    question = str(demande.question or "").strip()
    if not question:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "agent.question_vide", "params": {}})

    routage = _router(loader, kb, demande, question, traduire)

    modele_consulte: Dict[str, Any] = {}
    if routage.intention is None:
        from src.api.reglages_du_modele import reglages_pour

        reglages = reglages_pour(USAGE_AGENT_DE_NAVIGATION.code)
        autorisation = loader.config.assistance.pour(USAGE_AGENT_DE_NAVIGATION.code)
        try:
            routage = router_par_le_modele(
                question, reglages, autorisation, demande.locale, traduire,
                lambda charge: envoyer(charge, reglages, SCHEMA_DU_ROUTAGE),
                routage.candidates)
            if routage.intention is not None:
                modele_consulte = {"modele": reglages.modele,
                                   "hors_du_poste": not reglages.locale}
        except (AnnotateurIndisponible, ReponseInexploitable) as refus:
            # Ni une panne ni un échec : le produit n'a pas compris, et il le
            # dit avec les questions qu'il sait poser.
            logger.info("Agent : routage sans modèle (%s)", refus)
            routage = Routage(candidates=routage.candidates)

    if routage.intention is None:
        options = [{"valeur": intention.code,
                    "libelle": traduire(intention.cle_libelle)}
                   for intention in (routage.candidates or INTENTIONS)]
        return _vide(question,
                     choix=_choix("agent.choix.intention", options),
                     reponse={"cle": "agent.reponse.incomprise", "params": {}})

    intention = routage.intention
    identifiants: List[str] = []
    if intention.entite:
        identifiants = _entites_de_la_question(loader, kb, intention, question,
                                               demande)
        if not identifiants:
            return _vide(question, intention=intention.code,
                         origine=routage.origine,
                         reponse={"cle": f"agent.manque.{intention.entite}",
                                  "params": {}},
                         choix=_choix(f"agent.choix.{intention.entite}", []),
                         **modele_consulte)
        if len(identifiants) > 1 and intention.entite not in ENSEMBLE:
            candidats = reconnaitre(question,
                                    ENTITES[intention.entite](loader, kb))
            return _vide(question, intention=intention.code,
                         origine=routage.origine,
                         reponse={"cle": f"agent.ambigu.{intention.entite}",
                                  "params": {"nombre": len(candidats)}},
                         choix=_choix(f"agent.choix.{intention.entite}",
                                      [c.en_document() for c in candidats]),
                         **modele_consulte)
        identifiants = identifiants[:COMPTES_MAX]

    sujets = [_sujet(loader, kb, intention, identifiant)
              for identifiant in (identifiants or [""])]
    premier = sujets[0]

    # Le marquage porte sur les comptes de la réponse, et sur eux seuls : le
    # calculer sur le référentiel entier coûterait un parcours complet des
    # identités pour décorer deux lignes.
    marques = _marques(loader, identifiants)

    entete: Dict[str, Any] = {}
    recoupement: Dict[str, Any] = {}
    if len(sujets) > 1:
        recoupement = _recoupement_des_comptes(loader, identifiants, marques)
        # Deux phrases, et non une phrase qui dirait « dont 0 à privilèges » :
        # un zéro affiché se lit comme un constat, alors qu'il signifie le plus
        # souvent que rien n'est déclaré. Le repli est la phrase d'avant.
        entete = {"cle": "agent.reponse.plusieurs_comptes_prives"
                         if recoupement["a_privileges"]
                         else "agent.reponse.plusieurs_comptes",
                  "params": recoupement}
    rendu = _vide(
        question,
        intention=intention.code,
        origine=routage.origine,
        sujets=sujets,
        entite={"type": intention.entite, "identifiant": identifiants[0]}
               if identifiants else {},
        # La phrase calculée du premier sujet reste le repli de tout l'écran :
        # une réponse doit exister même sans modèle, et même si la rédaction
        # est refusée.
        reponse=premier["reponse"],
        entete=entete,
        lignes=premier["lignes"],
        ecran=premier["ecran"],
        contexte={"intention": intention.code, "type": intention.entite,
                  "entite": identifiants[0] if identifiants else ""},
        **modele_consulte)

    for sujet in sujets:
        # Rendu sur chaque sujet et non déduit à l'écran : le client ne connaît
        # pas la déclaration du workspace, et deux endroits qui décideraient
        # séparément qu'un compte est à privilèges finiraient par ne pas dire
        # la même chose du même compte.
        sujet["a_privileges"] = sujet["identifiant"] in marques

    redigee = _redigee(loader, demande, question, intention, sujets, traduire,
                       recoupement, marques)
    if redigee:
        rendu["redaction"] = redigee
    return rendu


@router.get("/intentions")
async def lister_les_intentions(
    locale: str = "fr",
    user: User = Depends(require_permission_or_dev(PERMISSION)),
) -> Dict[str, Any]:
    """Les questions que le produit sait calculer, dans la langue demandée.

    Rendues au client pour qu'il les propose : un champ de saisie libre sans
    exemples se lit comme une boîte noire, et l'utilisateur y écrit des
    questions auxquelles rien ne répond.
    """
    traduire = _traducteur(locale)
    return {"intentions": [
        {"code": intention.code, "libelle": traduire(intention.cle_libelle),
         "entite": intention.entite, "ecran": intention.ecran}
        for intention in INTENTIONS]}


@router.post("/question")
async def poser_une_question(
    demande: Question,
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
    user: User = Depends(require_permission_or_dev(PERMISSION)),
) -> Dict[str, Any]:
    """Répond à une question posée en français.

    Deux réponses coexistent dans la charge rendue : celle du produit — une
    clé de traduction et des nombres — et, quand l'administrateur l'a ouverte,
    celle que le modèle a rédigée à partir des mêmes grandeurs. L'écran
    affiche la seconde quand elle existe, la première sinon. Aucune des deux
    ne contient un chiffre que le produit n'a pas calculé.
    """
    rendu = await run_in_threadpool(_repondre, loader, kb, demande,
                                    _traducteur(demande.locale))
    modele = rendu.get("modele") or (rendu.get("redaction") or {}).get("modele")
    if modele:
        # La trace dit ce qui est sorti : la question, et rien d'autre. Son
        # contenu n'y figure pas — une piste d'audit qui recopierait les
        # questions deviendrait elle-même une donnée à protéger.
        journal.consigner(
            Action.ASSISTANCE_CONSULTEE, "assistance",
            USAGE_AGENT_DE_NAVIGATION.code,
            {"usage": USAGE_AGENT_DE_NAVIGATION.code, "modele": modele,
             "categories": "question_libre",
             "hors_du_poste": bool(rendu.get("hors_du_poste"))})
    return rendu
