# Fichier : src/core/knowledge/derogations.py
"""L'exception assumée : ce qu'on a regardé, accepté, et jusqu'à quand.

Un outil de gouvernance produit des constats. Le premier chargement les fait
tous découvrir ; le deuxième les refait tous apparaître, y compris ceux qu'on a
déjà examinés et tranchés. L'écran se remplit alors de ce qu'on a déjà lu, et
**on cesse de le lire**. C'est ainsi que meurent les outils de gouvernance : pas
en se trompant, en devenant du bruit.

La dérogation est la réponse, et elle tient en une phrase : *ce constat-là est
connu, accepté par quelqu'un, pour cette raison, jusqu'à cette date.*

Trois refus font toute la conception :

1. **aucune dérogation sans motif.** Une exception sans raison écrite est
   indiscernable d'un oubli, et six mois plus tard personne ne sait si la
   décision a été prise ou subie ;
2. **aucune dérogation sans échéance.** Une dérogation perpétuelle n'est pas une
   exception, c'est une **suppression silencieuse de la règle** — avec le
   désavantage supplémentaire que la règle continue d'exister à l'écran, et
   qu'on la croit appliquée. L'échéance est obligatoire, bornée, et jamais
   reconduite d'elle-même ;
3. **aucune dérogation ne cache le constat.** Un conflit couvert reste compté et
   reste affiché ; il est seulement rangé à part. Un auditeur doit pouvoir voir
   ce qui a été accepté — c'est même la première chose qu'il demande.

Et une expiration ne supprime rien : la dérogation périmée est **conservée et
montrée comme telle**. Ce qui disparaît sans laisser de trace, c'est une
décision perdue.

Le module est **générique par construction** : une dérogation porte une famille
et une cible, et chaque famille déclare les clés que sa cible doit porter. La
séparation des tâches est la première, l'écart au pair justifié la deuxième ;
le sur-octroi accepté et le compte dormant assumé entreront sans toucher au
mécanisme.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import (Any, Callable, Dict, FrozenSet, Iterable, List, Mapping,
                    Optional, Sequence, Tuple)

logger = logging.getLogger(__name__)

#: Un conflit de séparation des tâches, chez une identité donnée.
#:
#: La cible porte la règle **et** l'identité : accepter une règle pour tout le
#: monde n'est pas une dérogation, c'est une suspension — et elle existe déjà.
FAMILLE_SEPARATION = "separation"

#: Un droit qu'une personne détient et que ses pairs n'ont pas, justifié.
#:
#: La cible porte l'identité **et** le droit : justifier une personne entière
#: ferait taire aussi les droits qu'elle recevra demain, et justifier un droit
#: pour tout le monde reviendrait à le déclarer normal — ce que le catalogue
#: des rôles sait déjà faire.
FAMILLE_ECART_AU_PAIR = "ecart_au_pair"

#: Ce que la cible de chaque famille doit nommer. Déclaré dans le code et non
#: dans la configuration : c'est une propriété du constat couvert, pas un
#: réglage — et l'écran doit pouvoir dire pourquoi une saisie est refusée.
CIBLES: Mapping[str, Tuple[str, ...]] = {
    FAMILLE_SEPARATION: ("regle", "identite"),
    FAMILLE_ECART_AU_PAIR: ("identite", "droit"),
}

FAMILLES: Tuple[str, ...] = tuple(sorted(CIBLES))

#: Longueur du motif. Il est rendu tel quel à l'écran et dans les exports : il
#: est écrit par l'utilisateur, et le produit ne le traduit pas.
MOTIF_MAX = 500

#: Longueur d'un identifiant de cible, et forme admise. Une cible vient du
#: produit — un identifiant de règle, un identifiant d'identité — et non d'une
#: saisie libre.
VALEUR_MAX = 200

#: Durée maximale par défaut, en jours. Réglable par workspace : une
#: organisation qui revoit ses exceptions chaque trimestre et une autre qui les
#: revoit chaque année ne veulent pas la même borne. Mais une borne existe
#: toujours — sans elle, « jusqu'au 31 décembre 2099 » redevient une dérogation
#: perpétuelle, écrite autrement.
DUREE_MAX_JOURS = 365

#: Délai à partir duquel une dérogation est dite « bientôt échue ». C'est du
#: travail qui arrive, et le dire tard revient à ne pas le dire.
PREAVIS_JOURS = 30

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: Où en est une dérogation. Liste fermée ; chaque code est aussi une clé de
#: traduction — `derogation.statut.<code>`.
#:
#: Sans approbation exigée, une dérogation est accordée dès qu'on la demande :
#: c'est le comportement d'avant, et une dérogation écrite avant ce lot, sans
#: statut, se relit accordée. Avec approbation, elle naît **demandée** et ne
#: couvre rien tant qu'une autre personne ne l'a pas approuvée.
DEMANDEE = "demandee"
ACCORDEE = "accordee"
REFUSEE = "refusee"
STATUTS: Tuple[str, ...] = (DEMANDEE, ACCORDEE, REFUSEE)


class DerogationInvalide(ValueError):
    """Une dérogation que le produit refuse d'enregistrer.

    Refusée à la saisie, jamais rangée pour être ignorée : une dérogation qu'on
    croit accordée et qui ne couvre rien laisse un conflit remonter sans que
    personne comprenne pourquoi.
    """


@dataclass(frozen=True)
class Reglages:
    """Les bornes, réglables par workspace."""

    duree_max_jours: int = DUREE_MAX_JOURS
    preavis_jours: int = PREAVIS_JOURS
    #: Une dérogation doit-elle citer un contrôle compensatoire pour couvrir
    #: son constat ? Non par défaut : c'est le comportement d'avant, et exiger
    #: un contrôle qu'aucun workspace n'a encore décrit ferait réapparaître
    #: d'un coup toutes les exceptions déjà accordées.
    controle_exige: bool = False
    #: Une dérogation doit-elle être approuvée par une autre personne que
    #: celle qui la demande ? Non par défaut, pour la même raison.
    approbation_exigee: bool = False

    @classmethod
    def depuis_la_configuration(cls, config: Mapping[str, Any]) -> "Reglages":
        return cls(
            duree_max_jours=int(config.get("derogation_duree_max_jours",
                                           DUREE_MAX_JOURS)),
            preavis_jours=int(config.get("derogation_preavis_jours",
                                         PREAVIS_JOURS)),
            controle_exige=bool(config.get("derogation_controle_exige", False)),
            approbation_exigee=bool(config.get("derogation_approbation_exigee",
                                               False)),
        )


def _jour(valeur: Any, champ: str) -> date:
    """Lit une date ISO, et refuse tout le reste.

    Pas d'heure, pas de fuseau : une dérogation court jusqu'à la fin de son
    jour, et introduire un instant précis ferait dépendre une décision de
    gouvernance du fuseau du serveur.
    """
    texte = str(valeur or "").strip()
    if not _ISO.match(texte):
        raise DerogationInvalide(
            f"{champ} n'est pas une date au format AAAA-MM-JJ : {texte!r}")
    try:
        return date.fromisoformat(texte)
    except ValueError as erreur:
        raise DerogationInvalide(f"{champ} n'est pas une date : {texte!r}") from erreur


def _valeur(brut: Any, champ: str) -> str:
    texte = str(brut or "").strip()[:VALEUR_MAX]
    if not texte:
        raise DerogationInvalide(f"{champ} est vide")
    return texte


@dataclass(frozen=True)
class Derogation:
    """Une exception assumée, et tout ce qu'il faut pour la relire plus tard.

    Gelée : elle se construit à la lecture et se consulte partout ensuite. Une
    dérogation qu'un écran pourrait modifier au passage ferait dire deux choses
    différentes du même constat à deux endroits du produit.
    """

    identifiant: str
    famille: str
    cible: Mapping[str, str]
    motif: str
    auteur: str
    accordee_le: date
    echeance: date
    #: Le contrôle compensatoire que la dérogation cite, ou rien. Il est
    #: vérifié au calcul et non à la saisie : un contrôle qui cesse d'être
    #: exécuté fait perdre la couverture sans qu'on touche à la dérogation.
    controle: str = ""
    #: Où en est la dérogation. Seule une dérogation accordée couvre.
    statut: str = ACCORDEE
    #: Qui a tranché, quand, et pourquoi en cas de refus. Viennent du serveur.
    decidee_par: str = ""
    decidee_le: Optional[date] = None
    motif_de_refus: str = ""

    @property
    def cle(self) -> Tuple[str, Tuple[Tuple[str, str], ...]]:
        """Ce que la dérogation couvre, sous une forme comparable.

        C'est par cette clé que le calcul retrouve la dérogation d'un constat —
        jamais par une chaîne composée à la main, qui se casserait le jour où un
        identifiant porte le séparateur choisi.
        """
        return (self.famille, tuple(sorted(self.cible.items())))

    def expiree(self, aujourdhui: date) -> bool:
        """Une dérogation court **jusqu'à la fin** de son échéance.

        « Jusqu'au 31 décembre » couvre le 31 décembre : c'est ce que la phrase
        veut dire, et l'arithmétique du produit doit dire la même chose que la
        personne qui l'a écrite.
        """
        return aujourdhui > self.echeance

    def jours_restants(self, aujourdhui: date) -> int:
        return (self.echeance - aujourdhui).days

    def bientot_echue(self, aujourdhui: date, reglages: Reglages) -> bool:
        return (not self.expiree(aujourdhui)
                and self.jours_restants(aujourdhui) <= reglages.preavis_jours)

    @classmethod
    def depuis_dict(cls, brut: Mapping[str, Any],
                    reglages: Optional[Reglages] = None) -> "Derogation":
        """Construit une dérogation depuis sa forme stockée, en la validant.

        Raises:
            DerogationInvalide: famille inconnue, cible incomplète, motif
                absent, échéance absente, antérieure à l'octroi, ou au-delà de
                la durée maximale du workspace.
        """
        reglages = reglages or Reglages()
        identifiant = _valeur(brut.get("id"), "l'identifiant")
        famille = str(brut.get("famille") or "").strip()
        if famille not in CIBLES:
            raise DerogationInvalide(
                f"famille inconnue : {famille!r} "
                f"(attendu : {', '.join(FAMILLES)})")

        brute = brut.get("cible")
        if not isinstance(brute, Mapping):
            raise DerogationInvalide(
                f"la dérogation {identifiant} ne désigne aucune cible")
        attendues = CIBLES[famille]
        cible = {cle: _valeur(brute.get(cle), f"la cible « {cle} »")
                 for cle in attendues}
        # Une clé en trop est une faute de frappe sur une clé attendue : la
        # garder ferait une dérogation qui ne retrouve jamais son constat.
        inconnues = sorted(set(brute) - set(attendues))
        if inconnues:
            raise DerogationInvalide(
                f"la dérogation {identifiant} nomme des cibles inconnues : "
                f"{', '.join(inconnues)} (attendu : {', '.join(attendues)})")

        motif = str(brut.get("motif") or "").strip()[:MOTIF_MAX]
        if not motif:
            raise DerogationInvalide(
                f"la dérogation {identifiant} n'a pas de motif : une exception "
                "sans raison écrite est indiscernable d'un oubli")

        accordee_le = _jour(brut.get("accordee_le"), "la date d'octroi")
        echeance = _jour(brut.get("echeance"), "l'échéance")
        if echeance < accordee_le:
            raise DerogationInvalide(
                f"la dérogation {identifiant} expire avant d'avoir commencé")
        duree = (echeance - accordee_le).days
        if duree > reglages.duree_max_jours:
            raise DerogationInvalide(
                f"la dérogation {identifiant} court sur {duree} jours : "
                f"au-delà de {reglages.duree_max_jours}, ce n'est plus une "
                "exception")
        statut = str(brut.get("statut") or ACCORDEE).strip()
        if statut not in STATUTS:
            raise DerogationInvalide(
                f"la dérogation {identifiant} porte un statut inconnu : {statut!r}")
        decidee_le = (_jour(brut.get("decidee_le"), "la date de décision")
                      if brut.get("decidee_le") else None)
        return cls(identifiant=identifiant, famille=famille, cible=cible,
                   motif=motif, auteur=str(brut.get("auteur") or "").strip(),
                   accordee_le=accordee_le, echeance=echeance,
                   controle=str(brut.get("controle") or "").strip()[:VALEUR_MAX],
                   statut=statut,
                   decidee_par=str(brut.get("decidee_par") or "").strip(),
                   decidee_le=decidee_le,
                   motif_de_refus=str(brut.get("motif_de_refus") or "").strip()[:MOTIF_MAX])

    def en_dict(self) -> Dict[str, Any]:
        """La forme stockée. Les dates sont des chaînes ISO : un document de
        gouvernance se relit avec un éditeur de texte."""
        return {"id": self.identifiant, "famille": self.famille,
                "cible": dict(sorted(self.cible.items())), "motif": self.motif,
                "auteur": self.auteur,
                "accordee_le": self.accordee_le.isoformat(),
                "echeance": self.echeance.isoformat(),
                "controle": self.controle, "statut": self.statut,
                "decidee_par": self.decidee_par,
                "decidee_le": self.decidee_le.isoformat() if self.decidee_le else "",
                "motif_de_refus": self.motif_de_refus}

    def en_document(self, aujourdhui: date,
                    reglages: Optional[Reglages] = None) -> Dict[str, Any]:
        """Ce qu'un écran affiche : la dérogation, et où elle en est.

        L'état est **calculé à l'affichage** et non conservé : une dérogation
        rangée comme « active » resterait active le lendemain de son échéance,
        et c'est précisément ce que ce lot existe pour empêcher.
        """
        reglages = reglages or Reglages()
        return {**self.en_dict(),
                "expiree": self.expiree(aujourdhui),
                "jours_restants": self.jours_restants(aujourdhui),
                "bientot_echue": self.bientot_echue(aujourdhui, reglages)}


def derogations_valides(brutes: Sequence[Mapping[str, Any]],
                        reglages: Optional[Reglages] = None) -> List[Derogation]:
    """Les dérogations lisibles ; les autres sont signalées et écartées.

    Symétrique du périmètre et des règles de séparation : un document devenu
    illisible ne fait pas échouer chaque écran. Mais ici l'enjeu est inverse de
    d'habitude — une dérogation écartée fait **réapparaître** un conflit, ce qui
    est le défaut sûr : on remontre quelque chose de déjà tranché, on ne cache
    rien.
    """
    valides: List[Derogation] = []
    for brut in brutes:
        try:
            valides.append(Derogation.depuis_dict(brut, reglages))
        except DerogationInvalide as erreur:
            logger.warning("Dérogation ignorée : %s", erreur)
    return valides


def couvertures(derogations: Sequence[Derogation], famille: str,
                aujourdhui: date,
                raisons: Optional[Callable[[Derogation], Sequence[Any]]] = None,
                ) -> Dict[Tuple[Tuple[str, str], ...], Derogation]:
    """Ce qui est couvert **aujourd'hui**, indexé par cible.

    Les dérogations expirées n'y figurent pas : c'est tout le sens de
    l'échéance. Elles restent lisibles ailleurs, dans la liste des dérogations,
    où elles racontent ce qui a été décidé et quand cela a cessé de valoir.

    Celles qui portent une raison de ne plus couvrir — un contrôle
    compensatoire périmé, non conforme, relu par son exécutant — n'y figurent
    pas non plus : le conflit revient à traiter, et l'écran dit pourquoi.

    À cible égale, la **plus lointaine** l'emporte. Deux dérogations sur le même
    constat arrivent quand quelqu'un prolonge sans retirer la précédente ; faire
    gagner la plus courte annulerait la prolongation.
    """
    retenues: Dict[Tuple[Tuple[str, str], ...], Derogation] = {}
    for derogation in derogations:
        if derogation.famille != famille or derogation.expiree(aujourdhui):
            continue
        if derogation.statut != ACCORDEE:
            # Demandée, elle attend une décision ; refusée, elle en a reçu
            # une. Ni l'une ni l'autre ne fait taire le conflit.
            continue
        if raisons is not None and raisons(derogation):
            continue
        cle = derogation.cle[1]
        deja = retenues.get(cle)
        if deja is None or derogation.echeance > deja.echeance:
            retenues[cle] = derogation
    return retenues


def cible_d_ecart(identite: str, droit: str) -> Tuple[Tuple[str, str], ...]:
    """La clé d'un écart au pair : une personne, un droit."""
    return tuple(sorted({"identite": str(identite), "droit": str(droit)}.items()))


def cible_de_separation(regle: str, identite: str
                        ) -> Tuple[Tuple[str, str], ...]:
    """La clé d'un conflit de séparation, construite une seule fois.

    Une clé composée à deux endroits finit par l'être de deux façons, et la
    dérogation cesse alors de couvrir le constat qu'elle nomme.
    """
    return tuple(sorted({"regle": str(regle), "identite": str(identite)}.items()))
