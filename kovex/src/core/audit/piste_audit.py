"""Piste d'audit : qui a décidé quoi, quand, et sur quel objet.

Ce n'est pas un journal technique. Un journal technique sert à diagnostiquer
une panne ; il peut être verbeux, tourner, être purgé. Une piste d'audit sert
à répondre, six mois plus tard et devant un auditeur, à la question « qui a
validé ce rôle qui donne accès au dossier patient ? ». Les deux n'ont ni le
même contenu, ni la même durée de vie, ni les mêmes garanties.

Trois choix structurent ce module.

**Un fichier par instance, pas par workspace.** Un workspace se supprime ; son
historique de décisions, non. Rattacher la piste au workspace la ferait
disparaître avec lui, exactement au moment où elle a le plus de valeur. Le
workspace est donc un champ de l'entrée, pas son emplacement.

**Des lignes JSON ajoutées une à une** (JSON Lines) plutôt qu'un document
réécrit. Un document JSON impose de tout relire, modifier en mémoire et tout
réécrire à chaque décision : une interruption au mauvais moment perd
l'historique entier, et deux écritures simultanées s'écrasent. Ici chaque
décision est une ligne ajoutée en fin de fichier ; rien de ce qui est déjà
écrit n'est jamais rouvert en écriture.

**Un chaînage par empreinte.** Chaque entrée porte l'empreinte de la
précédente. Modifier ou retirer une ligne rompt la chaîne, et la vérification
le signale en désignant la ligne fautive. Cela n'empêche pas la falsification
— rien ne l'empêche sur un fichier accessible — mais cela la rend
**détectable**, ce qui est la propriété qu'un auditeur exige. Sans cela, une
piste d'audit modifiable sans trace ne vaut rien comme preuve.

Aucun libellé n'est construit ici : une entrée porte un code d'action et ses
paramètres, le client traduit.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)


class Action:
    """Codes d'action. Ce sont aussi des clés de traduction (`audit.action.*`).

    Un code, jamais une phrase : le serveur ne connaît pas la langue de celui
    qui relira la piste, et une piste d'audit se relit longtemps après.
    """

    # Cycle de vie des rôles
    ROLE_VALIDE = "role.validated"
    ROLE_REJETE = "role.rejected"
    ROLE_CREE = "role.created"
    ROLE_MODIFIE = "role.updated"
    ROLE_SUPPRIME = "role.deleted"
    #: Un rôle validé est sorti du catalogue. Ce n'est pas une suppression :
    #: le rôle reste consultable avec son motif, et le candidat dont il venait
    #: redevient à décider.
    ROLE_DEVALIDE = "role.unvalidated"
    #: Un rôle validé a été modifié à la suite d'un constat de la revue du
    #: modèle. L'entrée porte le code du constat et la date de l'état des
    #: données : « pourquoi ce rôle a-t-il changé le 3 mars » doit se répondre
    #: sans rouvrir les données.
    ROLE_MODIFIE_APRES_CONSTAT = "role.updated_after_finding"
    #: Les mesures du jour ont été retenues comme point de comparaison d'un
    #: rôle qui n'en avait pas — un rôle composé à la main n'est passé par
    #: aucune validation de candidat, donc aucun chiffre n'a été consigné à sa
    #: création. L'entrée porte ces chiffres : « par rapport à quoi ce rôle
    #: a-t-il dérivé » doit se répondre sans rouvrir les données.
    ROLE_ANCRE = "role.anchored"

    # Analyses
    MINING_LANCE = "mining.launched"
    #: Les candidats conservés d'un mining ont été écartés de l'écran. Ce n'est
    #: pas une décision de gouvernance — rien n'est ni validé ni refusé — mais
    #: la trace explique pourquoi un travail annoncé la veille a disparu.
    CANDIDATS_OUBLIES = "mining.candidates_cleared"
    RECERTIFICATION_LANCEE = "recertification.launched"

    # Sorties de données
    EXPORT_PRODUIT = "export.generated"
    #: Une proposition de nom a été demandée à un modèle externe. L'entrée dit
    #: quelles catégories de données ont quitté le système, et si elles sont
    #: sorties du poste — jamais leur contenu, qui est déjà dans le référentiel.
    ROLE_ANNOTE = "role.annotated"
    #: Une proposition a été demandée à un modèle pour un usage autre que le
    #: nommage. L'entrée porte l'usage, ce qui est sorti, et si c'est sorti du
    #: poste — jamais le contenu, qui est déjà dans le référentiel.
    ASSISTANCE_CONSULTEE = "assistance.consulted"

    #: Une décision a été retirée de l'apprentissage, ou y a été remise ; ou
    #: tout l'historique a été oublié d'un coup. Ce que le produit apprend se
    #: gouverne : qui l'a désappris, et quand, doit se lire ici.
    APPRENTISSAGE_MODIFIE = "learning.updated"

    #: Les valeurs d'une colonne ont été analysées localement. Aucune donnée
    #: n'a quitté le système : l'entrée sert à dater l'analyse, pas à tracer
    #: une sortie.
    VALEURS_ANALYSEES = "values.analyzed"
    #: Une table de recodage a été modifiée : la colonne, le nombre d'entrées
    #: touchées, et l'origine des grappes acceptées. C'est une décision de
    #: gouvernance — elle change les populations de tous les calculs suivants.
    VALEURS_RECODEES = "values.recoded"
    #: Un rapprochement a été refusé. Mémorisé, donc traçable au même titre.
    VALEURS_REFUSEES = "values.refused"
    #: Les valeurs d'une colonne ont été **soumises à un modèle**.
    #:
    #: La seule entrée de cette piste qui trace une sortie de données
    #: d'attributs hors du système. Elle nomme la colonne, compte combien de
    #: valeurs sont parties, et dit si elles ont quitté le poste — jamais les
    #: valeurs elles-mêmes : une piste d'audit qui recopierait la colonne
    #: `service` d'un hôpital deviendrait la donnée qu'elle est censée
    #: protéger.
    VALEURS_SOUMISES = "values.submitted"

    # Configuration et périmètre
    CONFIG_MODIFIEE = "config.updated"
    #: Ce que le produit a le droit de demander à un modèle a changé. L'entrée
    #: dit quel usage a été ouvert ou fermé et quelles catégories de données
    #: l'accompagnent : autoriser une sortie de données est une décision de
    #: gouvernance, au même titre qu'écarter une identité de l'analyse.
    ASSISTANCE_MODIFIEE = "assistance.updated"
    #: Le point de terminaison d'un modèle a changé. L'entrée dit l'usage et
    #: l'hôte visé — jamais la clé, jamais le chemin complet : décider **où**
    #: part une question est une décision de gouvernance au même titre que
    #: décider **ce qui** part, et les deux se relisent côte à côte.
    POINT_DE_TERMINAISON_MODIFIE = "endpoint.updated"
    #: Qui entre dans l'analyse a changé — une identité écartée nommément, ou
    #: une règle de périmètre posée. Ces décisions déplacent la couverture, le
    #: sur-octroi et les effectifs de toutes les analyses suivantes : deux
    #: minings aux résultats différents sur les mêmes données resteraient
    #: inexplicables sans cette trace.
    PERIMETRE_MODIFIE = "perimeter.updated"
    #: Les règles de séparation des tâches ont été réécrites. Déclarer ce que
    #: la même personne ne doit pas pouvoir faire est une décision de contrôle
    #: interne : elle laisse une trace, comme écarter une identité de l'analyse.
    SOD_REGLES_MODIFIEES = "sod.rules_updated"
    #: Une exception a été assumée : ce constat est accepté, pour cette raison,
    #: jusqu'à cette date. C'est la décision de gouvernance la plus sensible du
    #: produit — celle qui fait taire un signalement — et elle laisse une trace
    #: qui porte son motif et son échéance.
    DEROGATION_ACCORDEE = "derogation.granted"
    #: Une dérogation a été retirée avant son terme, et le constat revient.
    DEROGATION_RETIREE = "derogation.revoked"
    #: Une dérogation demandée a été approuvée, ou refusée, par une autre
    #: personne que celle qui l'avait demandée.
    DEROGATION_APPROUVEE = "derogation.approved"
    DEROGATION_REFUSEE = "derogation.refused"
    #: Le catalogue des contrôles compensatoires a été réécrit.
    CONTROLES_MODIFIES = "control.catalogue_updated"
    #: Une exécution de contrôle a été consignée : ce qui décide si les
    #: dérogations qui le citent couvrent encore leur constat.
    CONTROLE_EXECUTE = "control.executed"
    WORKSPACE_CREE = "workspace.created"
    WORKSPACE_SUPPRIME = "workspace.deleted"
    WORKSPACE_ACTIVE = "workspace.activated"
    DONNEES_IMPORTEES = "workspace.data_imported"

    # Accès
    CONNEXION = "auth.login"
    CONNEXION_REFUSEE = "auth.login_failed"
    MOT_DE_PASSE_CHANGE = "auth.password_changed"

    @classmethod
    def toutes(cls) -> List[str]:
        return sorted(
            valeur for nom, valeur in vars(cls).items()
            if not nom.startswith("_") and isinstance(valeur, str)
        )


class RuptureDeChaine(Exception):
    """La chaîne d'empreintes ne se referme pas : la piste a été altérée."""


@dataclass(frozen=True)
class EntreeAudit:
    """Une décision, telle qu'elle est écrite sur disque."""

    sequence: int
    horodatage: str
    acteur: str
    action: str
    objet_type: str
    objet_id: str
    workspace: str
    details: Dict[str, Any] = field(default_factory=dict)
    precedent: str = ""
    empreinte: str = ""

    def charge_utile(self) -> Dict[str, Any]:
        """L'entrée sans son empreinte : ce sur quoi l'empreinte est calculée."""
        donnees = asdict(self)
        donnees.pop("empreinte")
        return donnees

    def calculer_empreinte(self) -> str:
        # `sort_keys` et des séparateurs sans espace donnent une forme
        # canonique : deux exécutions produisent le même octet, donc la même
        # empreinte. Sans cela, une simple différence d'espacement ferait
        # échouer la vérification sur une piste pourtant intacte.
        canonique = json.dumps(
            self.charge_utile(), sort_keys=True, ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonique.encode("utf-8")).hexdigest()


def _horodatage() -> str:
    """Instant présent en UTC, à la microseconde.

    UTC et non l'heure locale : une piste d'audit relue depuis un autre fuseau,
    ou après un changement d'heure, doit rester ordonnable sans ambiguïté.
    """
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class PisteAudit:
    """Piste d'audit d'une instance, adossée à un fichier JSON Lines."""

    def __init__(self, chemin: Path):
        self.chemin = Path(chemin)
        self._verrou = threading.RLock()
        self.chemin.parent.mkdir(parents=True, exist_ok=True)

    # --- écriture ---------------------------------------------------------

    def consigner(
        self,
        acteur: str,
        action: str,
        objet_type: str = "",
        objet_id: str = "",
        workspace: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> EntreeAudit:
        """Ajoute une décision à la piste et rend l'entrée écrite.

        L'écriture est synchrone et suivie d'un `fsync` : une décision confirmée
        à l'utilisateur mais perdue au premier arrêt brutal serait un trou dans
        la piste, et un trou non signalé est pire qu'une absence de piste.
        """
        with self._verrou:
            derniere = self._derniere_entree()
            entree = EntreeAudit(
                sequence=(derniere.sequence + 1) if derniere else 1,
                horodatage=_horodatage(),
                acteur=acteur or "inconnu",
                action=action,
                objet_type=objet_type,
                objet_id=str(objet_id),
                workspace=workspace,
                details=details or {},
                precedent=derniere.empreinte if derniere else "",
            )
            entree = EntreeAudit(**{**entree.charge_utile(),
                                    "empreinte": entree.calculer_empreinte()})

            ligne = json.dumps(asdict(entree), ensure_ascii=False,
                               separators=(",", ":"))
            with open(self.chemin, "a", encoding="utf-8") as flux:
                flux.write(ligne + "\n")
                flux.flush()
                os.fsync(flux.fileno())
            return entree

    # --- lecture ----------------------------------------------------------

    def _lignes(self) -> Iterator[Dict[str, Any]]:
        if not self.chemin.exists():
            return
        with open(self.chemin, "r", encoding="utf-8") as flux:
            for numero, ligne in enumerate(flux, start=1):
                ligne = ligne.strip()
                if not ligne:
                    continue
                try:
                    yield json.loads(ligne)
                except json.JSONDecodeError:
                    # Une ligne illisible est signalée mais n'interrompt pas la
                    # lecture : le reste de la piste garde sa valeur.
                    logger.error("Piste d'audit : ligne %d illisible", numero)

    def _derniere_entree(self) -> Optional[EntreeAudit]:
        derniere = None
        for donnees in self._lignes():
            try:
                derniere = EntreeAudit(**donnees)
            except TypeError:
                logger.error("Piste d'audit : entrée de forme inattendue ignorée")
        return derniere

    def lire(
        self,
        acteur: Optional[str] = None,
        action: Optional[str] = None,
        workspace: Optional[str] = None,
        depuis: Optional[str] = None,
        jusqu_a: Optional[str] = None,
        recherche: Optional[str] = None,
    ) -> List[EntreeAudit]:
        """Entrées correspondant aux filtres, de la plus récente à la plus ancienne."""
        with self._verrou:
            entrees = []
            for donnees in self._lignes():
                try:
                    entree = EntreeAudit(**donnees)
                except TypeError:
                    continue
                if acteur and entree.acteur != acteur:
                    continue
                if action and entree.action != action:
                    continue
                if workspace and entree.workspace != workspace:
                    continue
                if depuis and entree.horodatage < depuis:
                    continue
                if jusqu_a and entree.horodatage > jusqu_a:
                    continue
                if recherche:
                    motif = recherche.casefold()
                    corpus = " ".join([
                        entree.acteur, entree.action, entree.objet_type,
                        entree.objet_id, entree.workspace,
                        json.dumps(entree.details, ensure_ascii=False),
                    ]).casefold()
                    if motif not in corpus:
                        continue
                entrees.append(entree)
            entrees.reverse()
            return entrees

    def acteurs(self) -> List[str]:
        """Comptes apparaissant dans la piste, pour alimenter un filtre."""
        with self._verrou:
            return sorted({d.get("acteur", "") for d in self._lignes() if d.get("acteur")})

    # --- intégrité --------------------------------------------------------

    def verifier(self) -> Dict[str, Any]:
        """Recalcule la chaîne d'empreintes et rend un constat.

        Ne lève pas : une piste rompue est une information à afficher, pas une
        panne. Le constat désigne la première entrée fautive, ce qui borne la
        période sur laquelle l'historique n'est plus opposable.
        """
        with self._verrou:
            precedente = ""
            sequence_attendue = 1
            total = 0
            for donnees in self._lignes():
                total += 1
                try:
                    entree = EntreeAudit(**donnees)
                except TypeError:
                    return self._constat(False, total, "audit.integrity.malformed",
                                         {"sequence": sequence_attendue})
                if entree.sequence != sequence_attendue:
                    return self._constat(False, total, "audit.integrity.sequence",
                                         {"attendue": sequence_attendue,
                                          "trouvee": entree.sequence})
                if entree.precedent != precedente:
                    return self._constat(False, total, "audit.integrity.broken_link",
                                         {"sequence": entree.sequence})
                if entree.calculer_empreinte() != entree.empreinte:
                    return self._constat(False, total, "audit.integrity.altered",
                                         {"sequence": entree.sequence})
                precedente = entree.empreinte
                sequence_attendue += 1
            return self._constat(True, total, "audit.integrity.intact", {})

    @staticmethod
    def _constat(intacte: bool, entrees: int, cle: str,
                 params: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "intacte": intacte,
            "entrees": entrees,
            "constat_key": cle,
            "constat_params": params,
        }


#: Chemin par défaut de la piste. Hors des workspaces, pour survivre à la
#: suppression de l'un d'eux ; surchargeable pour une installation qui range
#: ses données ailleurs.
CHEMIN_PAR_DEFAUT = Path("audit") / "audit.jsonl"

_piste: Optional[PisteAudit] = None
_verrou_instance = threading.Lock()


def get_piste_audit(chemin: Optional[Path] = None) -> PisteAudit:
    """Piste d'audit de l'instance."""
    global _piste
    with _verrou_instance:
        if chemin is not None:
            _piste = PisteAudit(chemin)
        elif _piste is None:
            configure = os.environ.get("PYGIA_AUDIT_FILE", "")
            _piste = PisteAudit(Path(configure) if configure else CHEMIN_PAR_DEFAUT)
        return _piste
