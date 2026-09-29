# Fichier : src/core/knowledge/separation.py
"""Séparation des tâches : ce que la même personne ne doit pas pouvoir faire.

Créer un fournisseur **et** payer une facture. Saisir une commande **et** la
valider. Ouvrir un compte **et** en modifier le plafond. Ce sont les règles que
tout auditeur cherche en premier, et elles sont la seule chose qu'un outil de
gouvernance peut dire d'une habilitation sans rien savoir du métier : que deux
pouvoirs, réunis chez une personne, valent plus que leur somme.

Trois principes, et les trois sont des refus :

1. **aucune règle n'est livrée.** Le produit ne connaît ni le plan comptable
   d'un client, ni son organisation. Une bibliothèque de règles toutes faites
   se tromperait partout, et — pire — donnerait à croire que le sujet est
   couvert. La règle appartient à qui répond de son contrôle interne ;
2. **le conflit se calcule, il ne se suppose pas.** Une identité est en conflit
   parce qu'elle détient effectivement un droit de chaque côté, d'après les
   habilitations chargées. Aucune extrapolation depuis un intitulé de poste ;
3. **le produit dit d'où vient le conflit.** Deux droits réunis par hasard chez
   une personne et deux droits réunis **par un rôle** ne se corrigent pas de la
   même façon : le premier est une exception à traiter, le second est un défaut
   du modèle, qui redonnera le conflit à chaque nouveau porteur.

**Une règle ne nomme pas des droits, elle nomme des pouvoirs.** Un côté est une
liste de **références typées** — un droit, une application, un rôle du catalogue
— que le produit résout en droits au moment du calcul. Ce n'est pas une commodité
de saisie : c'est ce qui donne à la règle une durée de vie. Un droit ajouté demain
à l'application de paiement est couvert d'office par une règle qui nomme cette
application, et invisible pour une règle qui énumère des droits. C'est
exactement l'argument des règles de périmètre contre la liste nominative.

Une règle qui nomme un rôle porte sur **les droits de ce rôle, pas sur son
port** : quelqu'un qui détient le droit directement, sans le rôle, a le même
pouvoir — et c'est précisément le cas que la gouvernance veut voir. Le contraire
laisserait un conflit se cacher derrière une attribution directe.

Ce module ne décide rien. Il ne retire aucun droit, ne rejette aucun rôle : il
rend ce qui est, et le produit le montre. La règle du reste du produit vaut ici
comme ailleurs — le choix reste à l'utilisateur —, mais avec une nuance que le
sujet impose : un conflit de séparation des tâches n'est pas un signalement de
qualité de données, c'est un constat d'audit. Il se rend **entier**, sans seuil
qui en cacherait la queue.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import (Any, Dict, FrozenSet, Iterable, List, Mapping, Optional,
                    Sequence, Set, Tuple)

logger = logging.getLogger(__name__)

#: Le conflit n'est pas porté par un rôle : l'identité détient le droit sans
#: qu'aucun rôle validé ne l'explique. C'est une exception, à traiter identité
#: par identité.
ORIGINE_HORS_ROLE = "hors_role"

#: Ce qu'un côté de règle peut nommer.
#:
#: `droit` est la référence élémentaire ; `application` et `role` en désignent un
#: ensemble, et c'est ce qui donne à la règle sa durée de vie — l'ensemble est
#: relu à chaque calcul, sur les données du jour.
TYPE_DROIT = "droit"
TYPE_APPLICATION = "application"
TYPE_ROLE = "role"
TYPES: Tuple[str, ...] = (TYPE_DROIT, TYPE_APPLICATION, TYPE_ROLE)

#: Types déclarables **avant** qu'un catalogue existe.
#:
#: Une règle qui nomme un rôle ne peut pas se déclarer avant le premier mining :
#: le rôle n'existe pas encore. Les deux autres, si — et c'est ce qui permet de
#: déclarer ses règles de séparation avant de miner, là où elles servent.
TYPES_SANS_CATALOGUE: Tuple[str, ...] = (TYPE_DROIT, TYPE_APPLICATION)

#: Bornes d'une règle. Un côté sans référence ne désigne rien ; une règle à cent
#: références par côté n'est plus une règle, c'est un périmètre.
REFERENCES_PAR_COTE_MAX = 100

#: Bornes d'un côté **résolu**. Une application peut porter des milliers de
#: droits ; au-delà de ce plafond la règle coûterait à chaque calcul le prix du
#: référentiel entier, et le dépassement est **annoncé** plutôt que subi.
DROITS_PAR_COTE_MAX = 5000

#: Longueur du libellé d'une règle. Il est rendu tel quel à l'écran et dans les
#: exports : il est écrit par l'utilisateur, et le produit ne le traduit pas.
LIBELLE_MAX = 200

#: Identités nommées dans le détail d'un conflit. Le **compte** porte sur la
#: population entière ; la liste sert à commencer le travail, et un écran qui
#: rendrait quarante mille lignes ne sert personne.
IDENTITES_DETAILLEES_MAX = 500


class RegleInvalide(ValueError):
    """Une règle que le produit ne sait pas appliquer.

    Refusée à la saisie, jamais rangée pour être ignorée plus tard : une règle
    de séparation des tâches qu'on croit active et qui ne calcule rien est le
    pire état possible de cette fonction — l'auditeur lit « aucun conflit » et
    conclut que tout va bien.
    """


@dataclass(frozen=True)
class Reference:
    """Ce qu'un côté de règle nomme : un droit, une application, ou un rôle.

    Le type n'est pas une commodité de saisie. `droit` désigne un droit et rien
    d'autre ; `application` et `role` désignent un **ensemble relu à chaque
    calcul**, et c'est ce qui donne à la règle sa durée de vie : un droit ajouté
    demain à l'application de paiement est couvert d'office par la première
    forme, et invisible pour une règle qui énumère des droits.
    """

    type: str
    identifiant: str

    @classmethod
    def depuis(cls, brut: Any, regle: str, cote: str) -> "Reference":
        """Lit une référence, sous sa forme typée ou sous sa forme héritée.

        Une chaîne nue se lit comme un droit. C'est la forme qu'écrivait le lot
        précédent, et un workspace qui la porte doit continuer de fonctionner :
        une décision de gouvernance ne se perd pas parce que le produit a
        changé d'avis sur sa représentation.
        """
        if isinstance(brut, str):
            brut = {"type": TYPE_DROIT, "id": brut}
        if not isinstance(brut, Mapping):
            raise RegleInvalide(
                f"le côté {cote} de la règle {regle} porte une référence "
                "illisible")
        type_ = str(brut.get("type") or TYPE_DROIT).strip()
        if type_ not in TYPES:
            raise RegleInvalide(
                f"la règle {regle} nomme un type inconnu : {type_!r} "
                f"(attendu : {', '.join(TYPES)})")
        identifiant = str(brut.get("id") or "").strip()
        if not identifiant:
            raise RegleInvalide(
                f"le côté {cote} de la règle {regle} porte une référence sans "
                "identifiant")
        return cls(type=type_, identifiant=identifiant)

    def en_dict(self) -> Dict[str, str]:
        return {"type": self.type, "id": self.identifiant}


@dataclass(frozen=True)
class Regle:
    """Deux ensembles de pouvoirs que la même identité ne doit pas réunir.

    Attributes:
        identifiant: la clé de la règle, stable, choisie par le produit.
        libelle: ce que la règle interdit, dans les mots de l'utilisateur.
            Rendu tel quel : le produit ne sait pas nommer le contrôle interne
            d'un client.
        gauche: les références d'un côté.
        droite: les références de l'autre.
        active: une règle peut être suspendue sans être supprimée — le temps
            d'une remédiation, ou d'une réorganisation. La supprimer ferait
            perdre son libellé et son historique.
        severite: un niveau pris dans la liste du workspace, ou rien. Sans
            lui, quarante conflits se lisent tous pareil. La liste appartient
            au client : le produit ne sait pas ce qu'est un risque « critique »
            chez lui.
        processus: le processus métier que la règle protège — achats,
            paie, trésorerie —, dans les mots du client.
        proprietaire: qui répond du risque. C'est lui qu'une campagne
            interroge, et une règle sans propriétaire est un constat en soi.

    Une fois résolue, la règle se déclenche dès qu'une identité détient au moins
    un droit de chaque côté : c'est la lecture d'un auditeur — « saisir une
    commande » est un pouvoir, quel que soit le droit technique qui le porte, et
    un client en a souvent plusieurs.
    """

    identifiant: str
    libelle: str
    gauche: Tuple[Reference, ...]
    droite: Tuple[Reference, ...]
    active: bool = True
    severite: str = ""
    processus: str = ""
    proprietaire: str = ""

    @property
    def sans_catalogue(self) -> bool:
        """La règle se déclare-t-elle avant le premier mining ?

        Une règle qui nomme un rôle ne le peut pas : le rôle n'existe pas
        encore. L'écran s'en sert pour dire pourquoi une règle ne figure pas là
        où on la cherche.
        """
        return all(reference.type in TYPES_SANS_CATALOGUE
                   for reference in self.gauche + self.droite)

    @classmethod
    def depuis_dict(cls, brut: Mapping[str, Any]) -> "Regle":
        """Construit une règle depuis sa forme stockée, en la validant.

        Le chevauchement des deux côtés n'est plus contrôlé ici : deux
        références distinctes — une application et un rôle — peuvent se
        recouvrir une fois **résolues**, et ce recouvrement dépend des données
        du jour, pas de la saisie. Il est donc constaté à la résolution, où il
        rend la règle inapplicable et le dit.

        Raises:
            RegleInvalide: un côté vide, une référence de type inconnu, un
                libellé absent, ou un côté démesuré.
        """
        identifiant = str(brut.get("id") or "").strip()
        if not identifiant:
            raise RegleInvalide("une règle de séparation porte un identifiant")
        libelle = str(brut.get("libelle") or "").strip()[:LIBELLE_MAX]
        if not libelle:
            raise RegleInvalide(
                f"la règle {identifiant} n'est pas nommée : personne ne saura "
                "ce qu'elle interdit")
        gauche = _cote(brut.get("gauche"), identifiant, "gauche")
        droite = _cote(brut.get("droite"), identifiant, "droite")
        communes = set(gauche) & set(droite)
        if communes:
            # La **même** référence des deux côtés est une faute de saisie, et
            # elle se voit sans regarder les données : elle mettrait en conflit
            # quiconque détient un seul de ses droits.
            raise RegleInvalide(
                f"la règle {identifiant} place {len(communes)} référence(s) "
                "des deux côtés : elle signalerait quiconque en détient un "
                "seul droit")
        return cls(identifiant=identifiant, libelle=libelle, gauche=gauche,
                   droite=droite, active=bool(brut.get("active", True)),
                   severite=_texte(brut.get("severite")),
                   processus=_texte(brut.get("processus")),
                   proprietaire=_texte(brut.get("proprietaire")))

    def en_dict(self) -> Dict[str, Any]:
        """La forme stockée. Les côtés sont triés : deux enregistrements de la
        même règle donnent le même document, et un journal des modifications ne
        se remplit pas de différences qui n'en sont pas."""
        return {"id": self.identifiant, "libelle": self.libelle,
                "gauche": [reference.en_dict() for reference in self.gauche],
                "droite": [reference.en_dict() for reference in self.droite],
                "active": self.active, "severite": self.severite,
                "processus": self.processus, "proprietaire": self.proprietaire}


def _texte(brut: Any) -> str:
    """Un champ libre de la règle, rogné à la longueur d'un libellé.

    Absent d'une règle écrite avant ce lot, il vaut rien : une règle ancienne
    se relit sans erreur.
    """
    return str(brut or "").strip()[:LIBELLE_MAX]


def _cote(brut: Any, identifiant: str, nom: str) -> Tuple[Reference, ...]:
    if brut is None or isinstance(brut, (str, bytes)) or not isinstance(brut, Iterable):
        raise RegleInvalide(
            f"le côté {nom} de la règle {identifiant} n'est pas une liste de "
            "références")
    retenues: List[Reference] = []
    for element in brut:
        # Une entrée vide ne porte aucune information et ne peut pas être
        # voulue — une virgule en trop, une ligne blanche dans un document
        # recopié. L'écarter n'est pas la même chose que d'accepter une
        # référence mal formée, qui, elle, est refusée : le client croit avoir
        # nommé quelque chose.
        if element is None or (isinstance(element, (str, Mapping))
                               and not element):
            continue
        reference = Reference.depuis(element, identifiant, nom)
        if reference not in retenues:
            retenues.append(reference)
    if not retenues:
        raise RegleInvalide(
            f"le côté {nom} de la règle {identifiant} ne vise rien")
    if len(retenues) > REFERENCES_PAR_COTE_MAX:
        raise RegleInvalide(
            f"le côté {nom} de la règle {identifiant} vise {len(retenues)} "
            f"références : au-delà de {REFERENCES_PAR_COTE_MAX}, ce n'est plus "
            "une règle")
    # Trié : deux saisies du même côté, dans deux ordres, sont la même règle.
    return tuple(sorted(retenues, key=lambda r: (r.type, r.identifiant)))


# ------------------------------------------------------------- la résolution


@dataclass(frozen=True)
class RegleResolue:
    """Une règle ramenée aux droits qu'elle vise, sur les données du jour.

    C'est cet objet que le calcul manipule. La règle déclarée, elle, ne connaît
    que des références — et c'est voulu : le jour où une application gagne un
    droit, c'est la résolution qui change, jamais la décision de gouvernance.
    """

    identifiant: str
    libelle: str
    gauche: FrozenSet[str]
    droite: FrozenSet[str]
    active: bool = True
    severite: str = ""
    processus: str = ""
    proprietaire: str = ""
    #: Références qui ne désignent aucun droit aujourd'hui : une application
    #: absente du référentiel, un rôle dévalidé, un droit disparu.
    introuvables: Tuple[Reference, ...] = ()
    #: Droits visés par les deux côtés une fois les références résolues.
    #: Non nul, la règle est inapplicable : elle signalerait quiconque en
    #: détient un seul.
    chevauchement: FrozenSet[str] = frozenset()
    #: Vrai quand un côté a dû être tronqué pour rester calculable.
    tronquee: bool = False

    @property
    def applicable(self) -> bool:
        """La règle peut-elle produire un constat qui veuille dire quelque chose ?

        Trois façons de ne pas pouvoir, et l'écran doit les distinguer : elle
        est suspendue, un de ses côtés ne désigne plus rien, ou ses deux côtés
        se recouvrent. Les confondre ferait chercher l'erreur au mauvais endroit.
        """
        return (self.active and bool(self.gauche) and bool(self.droite)
                and not self.chevauchement)

    def en_dict(self) -> Dict[str, Any]:
        return {
            "regle": self.identifiant,
            "libelle": self.libelle,
            "active": self.active,
            "severite": self.severite,
            "processus": self.processus,
            "proprietaire": self.proprietaire,
            "applicable": self.applicable,
            "droits_gauche": len(self.gauche),
            "droits_droite": len(self.droite),
            "introuvables": [reference.en_dict()
                             for reference in self.introuvables],
            "chevauchement": sorted(self.chevauchement),
            "tronquee": self.tronquee,
        }


def resoudre(regle: Regle,
             droits_par_application: Mapping[str, Set[str]] = None,
             droits_par_role: Mapping[str, Set[str]] = None) -> RegleResolue:
    """Ramène une règle aux droits qu'elle vise, sur les données du jour.

    Une référence qui ne désigne rien n'est pas une erreur de saisie : c'est une
    application retirée du référentiel, un rôle dévalidé, un droit disparu d'un
    export. Elle est **nommée** dans `introuvables` plutôt que passée sous
    silence — sans quoi une règle continuerait d'afficher « aucun conflit » pour
    la seule raison qu'elle ne vise plus rien.
    """
    droits_par_application = droits_par_application or {}
    droits_par_role = droits_par_role or {}
    introuvables: List[Reference] = []
    tronquee = False

    def _resoudre(cote: Sequence[Reference]) -> FrozenSet[str]:
        nonlocal tronquee
        vises: Set[str] = set()
        for reference in cote:
            if reference.type == TYPE_DROIT:
                trouves = {reference.identifiant}
            elif reference.type == TYPE_APPLICATION:
                trouves = set(droits_par_application.get(
                    reference.identifiant, ()))
            else:
                trouves = set(droits_par_role.get(reference.identifiant, ()))
            if not trouves:
                introuvables.append(reference)
                continue
            vises |= trouves
        if len(vises) > DROITS_PAR_COTE_MAX:
            # Tronqué de façon déterministe : deux lectures des mêmes données
            # rendent le même constat, et c'est la condition pour qu'un
            # auditeur s'en serve.
            tronquee = True
            vises = set(sorted(vises)[:DROITS_PAR_COTE_MAX])
        return frozenset(vises)

    gauche = _resoudre(regle.gauche)
    droite = _resoudre(regle.droite)
    return RegleResolue(
        identifiant=regle.identifiant, libelle=regle.libelle,
        gauche=gauche, droite=droite, active=regle.active,
        severite=regle.severite, processus=regle.processus,
        proprietaire=regle.proprietaire,
        introuvables=tuple(introuvables), chevauchement=gauche & droite,
        tronquee=tronquee)


def regles_valides(brutes: Sequence[Mapping[str, Any]]) -> List[Regle]:
    """Les règles applicables, les autres étant signalées et écartées.

    Symétrique du périmètre : une règle devenue illisible ne fait pas échouer
    chaque calcul, elle est ignorée et journalisée. La saisie, elle, refuse —
    c'est là que l'erreur doit revenir à celui qui l'a faite.
    """
    valides: List[Regle] = []
    for brut in brutes:
        try:
            valides.append(Regle.depuis_dict(brut))
        except RegleInvalide as erreur:
            logger.warning("Règle de séparation ignorée : %s", erreur)
    return valides


# ------------------------------------------------------------- les conflits


@dataclass(frozen=True)
class Conflit:
    """Ce qu'une identité réunit, et par quoi.

    `par_role` n'est pas un ornement : c'est ce qui distingue une exception
    d'un défaut du modèle. Un rôle qui figure des deux côtés donne le conflit à
    tous ses porteurs, présents et futurs.
    """

    identite: str
    regle: str
    gauche: FrozenSet[str]
    droite: FrozenSet[str]
    #: Rôles validés du porteur qui apportent des droits, côté par côté.
    #: `ORIGINE_HORS_ROLE` y figure quand aucun rôle n'explique le droit.
    origines_gauche: FrozenSet[str] = frozenset()
    origines_droite: FrozenSet[str] = frozenset()

    @property
    def roles_des_deux_cotes(self) -> FrozenSet[str]:
        """Les rôles qui portent, à eux seuls, les deux côtés de la règle."""
        return (self.origines_gauche & self.origines_droite) - {ORIGINE_HORS_ROLE}

    def en_dict(self) -> Dict[str, Any]:
        return {
            "identite": self.identite,
            "regle": self.regle,
            "gauche": sorted(self.gauche),
            "droite": sorted(self.droite),
            "origines_gauche": sorted(self.origines_gauche),
            "origines_droite": sorted(self.origines_droite),
            "roles_des_deux_cotes": sorted(self.roles_des_deux_cotes),
        }


def _origines(droits: FrozenSet[str],
              roles_du_porteur: Mapping[str, FrozenSet[str]]) -> FrozenSet[str]:
    """Par quoi ces droits arrivent chez ce porteur.

    Un droit peut venir de plusieurs rôles à la fois, et un même droit peut
    venir d'un rôle **et** être détenu hors de tout rôle — le produit ne sait
    pas lequel des deux l'a « vraiment » donné, et ne prétend pas le savoir. Il
    rend les rôles qui l'expliquent, et `hors_role` s'il n'y en a aucun.
    """
    origines: Set[str] = set()
    for droit in droits:
        porteurs = [role for role, accordes in roles_du_porteur.items()
                    if droit in accordes]
        origines.update(porteurs or [ORIGINE_HORS_ROLE])
    return frozenset(origines)


def conflits(regle: RegleResolue, droits_par_identite: Mapping[str, Set[str]],
             roles_par_identite: Optional[Mapping[str, Mapping[str, FrozenSet[str]]]] = None
             ) -> List[Conflit]:
    """Les identités qui réunissent les deux côtés de la règle.

    Le calcul porte sur les **droits détenus**, c'est-à-dire les habilitations
    chargées : un droit reçu par un rôle y figure comme un droit reçu
    directement, puisque c'est ainsi que le système d'origine l'a écrit. Le
    cumul « à travers les rôles » n'est donc pas un cas particulier à traiter —
    il est déjà dans les données, et c'est l'origine du conflit, non sa
    détection, qui demande de connaître les rôles.

    Une règle inapplicable ne calcule rien — suspendue, ou dont un côté ne vise
    plus aucun droit, ou dont les deux côtés se recouvrent. Rendre ses conflits
    « pour information » reviendrait à ne pas l'avoir suspendue dans le premier
    cas, et à rendre un constat faux dans les deux autres.
    """
    if not regle.applicable:
        return []
    roles_par_identite = roles_par_identite or {}
    trouves: List[Conflit] = []
    for identite, detenus in droits_par_identite.items():
        gauche = regle.gauche & detenus
        if not gauche:
            continue
        droite = regle.droite & detenus
        if not droite:
            continue
        roles = roles_par_identite.get(identite, {})
        trouves.append(Conflit(
            identite=str(identite), regle=regle.identifiant,
            gauche=frozenset(gauche), droite=frozenset(droite),
            origines_gauche=_origines(frozenset(gauche), roles),
            origines_droite=_origines(frozenset(droite), roles)))
    trouves.sort(key=lambda conflit: conflit.identite)
    return trouves


def roles_en_conflit(regle: RegleResolue,
                     roles: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Les rôles qui portent à eux seuls les deux côtés de la règle.

    C'est le constat le plus lourd que ce module produise, et il ne dépend
    d'aucune identité : un rôle qui accorde les deux côtés donne le conflit à
    quiconque le reçoit, y compris à ceux qui ne l'ont pas encore. Le corriger
    corrige tous les porteurs d'un coup ; corriger les porteurs un à un laisse
    le rôle le redonner.

    Rendu même quand le rôle n'a aucun porteur : un rôle validé sans population
    aujourd'hui est un rôle qui attend la sienne.
    """
    if not regle.applicable:
        return []
    trouves = []
    for role in roles:
        accordes = {str(droit) for droit in (role.get("rights") or ())}
        gauche = regle.gauche & accordes
        droite = regle.droite & accordes
        if gauche and droite:
            trouves.append({
                "role_id": str(role.get("id") or ""),
                "role": str(role.get("name") or ""),
                "gauche": sorted(gauche),
                "droite": sorted(droite),
            })
    trouves.sort(key=lambda trouve: trouve["role_id"])
    return trouves


def roles_du_porteur(identite: str, roles: Sequence[Mapping[str, Any]],
                     porteurs_par_role: Mapping[str, Set[str]]
                     ) -> Dict[str, FrozenSet[str]]:
    """Les rôles que porte cette identité, et ce que chacun lui accorde."""
    portes: Dict[str, FrozenSet[str]] = {}
    for role in roles:
        identifiant = str(role.get("id") or "")
        if identite in porteurs_par_role.get(identifiant, set()):
            portes[identifiant] = frozenset(
                str(droit) for droit in (role.get("rights") or ()))
    return portes


def synthese(regle: RegleResolue, trouves: Sequence[Conflit],
             toxiques: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Ce qu'un écran affiche d'une règle : le compte, et ce qui l'explique.

    `par_les_roles` compte les identités dont le conflit est **entièrement**
    porté par un rôle qui figure des deux côtés. C'est la part du conflit que
    corriger le modèle ferait disparaître, et la distinguer change la décision :
    quarante conflits dont trente-huit viennent d'un rôle ne se traitent pas
    comme quarante exceptions.
    """
    par_les_roles = sum(1 for conflit in trouves if conflit.roles_des_deux_cotes)
    return {
        **regle.en_dict(),
        "identites": len(trouves),
        "par_les_roles": par_les_roles,
        "hors_role": len(trouves) - par_les_roles,
        "roles_en_conflit": len(toxiques),
    }


def rang_de_severite(severite: str, severites: Sequence[str]) -> int:
    """Le rang d'une sévérité dans la liste du workspace, la plus grave d'abord.

    Une règle sans sévérité, ou dont la sévérité a disparu de la liste, vient
    après toutes les autres : elle n'est pas moins grave, elle n'est pas
    qualifiée — et l'écran le dit.
    """
    try:
        return list(severites).index(severite)
    except ValueError:
        return len(severites)


def verifier_les_severites(regles: Sequence[Mapping[str, Any]],
                           severites: Sequence[str]) -> None:
    """Refuse une sévérité hors de la liste du workspace.

    Refusée à la saisie plutôt que rangée : une sévérité inconnue trierait la
    règle au fond de l'écran sans que personne ne sache pourquoi.

    Raises:
        SeveriteInconnue: une règle porte un niveau que la liste ne connaît pas.
    """
    connues = set(severites)
    for regle in regles:
        severite = str(regle.get("severite") or "").strip()
        if severite and severite not in connues:
            raise SeveriteInconnue(str(regle.get("id") or ""), severite)


class SeveriteInconnue(ValueError):
    """Une règle porte une sévérité que le workspace ne déclare pas."""

    def __init__(self, regle: str, severite: str):
        super().__init__(f"la règle {regle} porte la sévérité {severite!r}, "
                         "que le workspace ne déclare pas")
        self.regle = regle
        self.severite = severite
