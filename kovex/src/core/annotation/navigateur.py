# Fichier : src/core/annotation/navigateur.py
"""L'agent de navigation : une question en français, une réponse calculée.

Le produit sait répondre à des dizaines de questions — qui porte ce rôle, à qui
manque ce droit, quels rôles ont dérivé — mais chacune demande de savoir sur
quel écran aller, quel filtre poser et quelle colonne lire. C'est ce trajet que
cet agent raccourcit : on écrit la question, le produit y répond.

**Le modèle ne choisit qu'un mot.** Il reçoit la question et la liste fermée
des intentions que le produit sait calculer ; il rend le code de l'une d'elles,
et rien d'autre. Il n'écrit aucune phrase, ne voit aucun chiffre, et ne nomme
aucune entité.

C'est une réponse au défaut que le lot 53 a dû contrôler après coup : un modèle
à qui l'on demande de rédiger écrit un nombre inventé une fois sur dix, et il
faut alors relever les chiffres de sa phrase pour le prendre en faute. Ici, il
n'y a rien à contrôler — un chiffre inventé est *structurellement* impossible,
puisque aucun chiffre ne passe par le modèle. Les mots de la réponse viennent
du catalogue de traduction, les chiffres du calcul.

**Les entités sont résolues localement.** Le nom d'un rôle, un identifiant de
droit ou d'identité sont retrouvés dans les données du workspace par
comparaison de chaînes — jamais proposés par le modèle, qui ne les voit pas.
Une question ambiguë rend les candidats plutôt qu'un choix arbitraire : c'est à
l'utilisateur de dire duquel il parle.

**Il fonctionne sans modèle.** Le routage commence par les mots : chaque
intention déclare, dans les catalogues de traduction, les mots qui la
désignent — donc dans les trois langues, et modifiables sans toucher au code.
Le modèle n'est sollicité que lorsque ce routage hésite, et seulement si
l'administrateur a ouvert l'usage. Sur un serveur sans accès, l'agent répond
quand même.

**La question est une matière.** Le texte libre d'un utilisateur peut contenir
le nom d'une personne. L'envoyer à un modèle est donc une décision
d'administration, prise dans la matrice d'assistance comme toutes les autres,
et non un effet de bord du fait d'avoir activé l'assistance.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from src.core.annotation import protocole
from src.core.annotation.annotateur import (
    AnnotateurIndisponible,
    Reglages,
    ReponseInexploitable,
    demander,
)
from src.core.annotation.assistance import Autorisation
from src.core.annotation.propositions import composer_la_demande_de

logger = logging.getLogger(__name__)

#: Longueur maximale d'une question. Au-delà, ce n'est plus une question : la
#: borne protège le routage local autant que ce qui pourrait partir.
LONGUEUR_QUESTION_MAX = 500

#: Nombre de candidats rendus quand une entité est ambiguë. Au-delà, la liste
#: ne se lit plus et la question était trop vague pour être levée par un choix.
CANDIDATS_MAX = 10

#: Longueur minimale d'un mot du référentiel pour qu'il serve à reconnaître une
#: entité dans une question. « RH » désigne un rôle ; « de » n'en désigne
#: aucun, et le laisser passer ferait reconnaître un rôle dans chaque phrase.
LONGUEUR_TERME_MIN = 2

#: Ce qui sépare les mots d'une question. Tout ce qui n'est ni lettre ni
#: chiffre : les identifiants du client portent des tirets et des points, qu'on
#: ne peut donc pas traiter comme des séparateurs sans les couper en morceaux.
_SEPARATEURS = re.compile(r"[^\w.\-_]+", re.UNICODE)


def plier(texte: str) -> str:
    """La forme comparable d'un mot : sans accent, sans casse.

    Le même pliage que le rapprochement des valeurs : « Médecin » et
    « MEDECIN » désignent la même chose, et une question ne s'écrit pas avec
    les accents du référentiel.
    """
    decompose = unicodedata.normalize("NFKD", str(texte or ""))
    sans_accent = "".join(c for c in decompose if not unicodedata.combining(c))
    return sans_accent.casefold().strip()


def mots(texte: str) -> List[str]:
    """Les mots d'une question, pliés."""
    return [plier(mot) for mot in _SEPARATEURS.split(str(texte or "")) if mot]


# ------------------------------------------------------------- les intentions


@dataclass(frozen=True)
class Intention:
    """Une question que le produit sait calculer.

    `entite` dit ce qu'il faut identifier dans les données pour répondre :
    un rôle, un droit, une identité — ou rien, pour une question qui porte sur
    l'ensemble du modèle. Une intention qui réclame une entité et n'en trouve
    aucune ne se déclenche pas : mieux vaut demander de quoi on parle que de
    répondre sur autre chose.

    `ecran` est la page à ouvrir pour voir la même chose en grand. Une réponse
    qui ne ramène pas à l'écran concerné laisse l'utilisateur dans une impasse
    dès que sa question suivante sort du catalogue.
    """

    code: str
    entite: str = ""
    ecran: str = ""

    @property
    def cle_libelle(self) -> str:
        return f"agent.intention.{self.code}"

    @property
    def cle_mots(self) -> str:
        """Clé des mots qui désignent cette intention, dans chaque langue."""
        return f"agent.intention.{self.code}.mots"

    @property
    def cle_reponse(self) -> str:
        return f"agent.reponse.{self.code}"


ENTITE_ROLE = "role"
ENTITE_DROIT = "droit"
ENTITE_IDENTITE = "identite"

#: Les questions que cet agent sait poser au produit.
#:
#: Chacune correspond à un calcul qui existe déjà et qui est affiché quelque
#: part : l'agent ne crée aucune mesure, il en raccourcit l'accès. Une
#: intention ne s'ajoute ici qu'avec sa réponse, sa phrase traduite et ses mots
#: dans les trois langues — listée sans traitement, elle se lirait comme une
#: question à laquelle le produit refuse de répondre.
INTENTIONS: Tuple[Intention, ...] = (
    Intention(code="porteurs_du_role", entite=ENTITE_ROLE, ecran="roles-catalog"),
    Intention(code="droits_du_role", entite=ENTITE_ROLE, ecran="roles-catalog"),
    Intention(code="detenteurs_du_droit", entite=ENTITE_DROIT, ecran="rights"),
    Intention(code="roles_de_l_identite", entite=ENTITE_IDENTITE, ecran="users"),
    Intention(code="droits_de_l_identite", entite=ENTITE_IDENTITE, ecran="users"),
    Intention(code="roles_en_sur_octroi", ecran="roles-catalog"),
    Intention(code="roles_sans_reference", ecran="roles-catalog"),
    Intention(code="le_socle", ecran="birth-rights"),
    Intention(code="compte_du_catalogue", ecran="roles-catalog"),
    Intention(code="travail_en_attente", ecran="dashboard"),
)

PAR_CODE: Mapping[str, Intention] = {i.code: i for i in INTENTIONS}


# --------------------------------------------------------- le routage local


def _mots_declares(intention: Intention, traduire: Callable[[str], str]) -> List[str]:
    """Les mots qui désignent l'intention, tels que le catalogue les écrit.

    Ils vivent dans les catalogues de traduction et non dans le code : « qui
    porte » se dit autrement en allemand, et un client peut vouloir ajouter le
    vocabulaire de sa maison sans qu'on recompile quoi que ce soit.
    """
    brut = traduire(intention.cle_mots)
    if not brut or brut == intention.cle_mots:
        return []
    return [plier(mot) for mot in brut.split(",") if plier(mot)]


def poids_des_mots(traduire: Callable[[str], str]) -> Dict[str, float]:
    """Ce que vaut chaque mot pour désigner une question.

    Un mot que plusieurs questions revendiquent ne départage rien : « qui »
    ouvre aussi bien « qui porte ce rôle » que « qui détient ce droit ». Il
    compte donc pour moins qu'un mot propre à une seule — « socle », « sur
    octroi », « référence ».

    Sans cette pondération, la question « que contient le socle » se partageait
    entre deux intentions à égalité, et l'agent demandait laquelle alors que la
    réponse était évidente.
    """
    revendications: Dict[str, int] = {}
    for intention in INTENTIONS:
        for mot in set(_mots_declares(intention, traduire)):
            revendications[mot] = revendications.get(mot, 0) + 1
    return {mot: 1.0 / nombre for mot, nombre in revendications.items()}


def score_local(intention: Intention, question: str,
                traduire: Callable[[str], str],
                poids: Optional[Mapping[str, float]] = None) -> float:
    """Ce que la question doit à cette intention, mot par mot.

    Deux intentions à égalité ne se départagent pas ici : c'est le cas où l'on
    regarde si l'entité attendue est présente, puis, à défaut, où l'on demande
    au modèle ou à l'utilisateur.
    """
    poids = poids if poids is not None else poids_des_mots(traduire)
    presents = set(mots(question))
    plie = plier(question)
    total = 0.0
    for mot in _mots_declares(intention, traduire):
        # Un mot composé — « sur octroi » — ne se retrouve pas dans la liste
        # des mots : on le cherche alors dans la phrase entière.
        reconnu = mot in plie if " " in mot else mot in presents
        if reconnu:
            total += poids.get(mot, 1.0)
    return round(total, 6)


@dataclass(frozen=True)
class Routage:
    """Ce que le routage a conclu, et comment."""

    intention: Optional[Intention] = None
    origine: str = ""
    #: Intentions à égalité, quand le routage local n'a pas su trancher.
    candidates: Tuple[Intention, ...] = ()


ORIGINE_LOCALE = "locale"
ORIGINE_MODELE = "modele"


def router_localement(question: str,
                      traduire: Callable[[str], str]) -> Routage:
    """L'intention désignée par les mots de la question, s'il y en a une."""
    poids = poids_des_mots(traduire)
    scores = [(score_local(intention, question, traduire, poids), intention)
              for intention in INTENTIONS]
    meilleurs = max((score for score, _ in scores), default=0.0)
    if meilleurs <= 0:
        return Routage()
    retenues = tuple(intention for score, intention in scores if score == meilleurs)
    if len(retenues) == 1:
        return Routage(intention=retenues[0], origine=ORIGINE_LOCALE)
    return Routage(candidates=retenues)


# ---------------------------------------------- la résolution des entités


@dataclass(frozen=True)
class Candidat:
    """Une entité du workspace reconnue dans la question."""

    identifiant: str
    libelle: str = ""

    def en_document(self) -> Dict[str, str]:
        return {"identifiant": self.identifiant, "libelle": self.libelle}


def _termes(valeur: str) -> List[str]:
    """Les formes sous lesquelles une entité peut être citée."""
    plie = plier(valeur)
    formes = {plie}
    formes.update(mot for mot in mots(valeur) if len(mot) >= LONGUEUR_TERME_MIN)
    return [forme for forme in formes if len(forme) >= LONGUEUR_TERME_MIN]


def reconnaitre(question: str,
                entites: Sequence[Tuple[str, str]]) -> List[Candidat]:
    """Les entités du workspace citées dans la question.

    La comparaison est locale et littérale : un identifiant ou un nom doit
    apparaître dans la question. Aucune approximation — proposer « APP_ROLE_12 »
    à qui a écrit « APP_ROLE_2 » serait répondre sur un autre rôle que celui
    demandé, ce qui est pire que ne pas répondre.

    Les candidats sont classés du plus long au plus court : « Médecin chef » et
    « Médecin » peuvent se reconnaître dans la même phrase, et c'est le plus
    précis qui répond à la question posée.
    """
    plie = plier(question)
    presents = set(mots(question))
    trouves: List[Tuple[int, Candidat]] = []
    for identifiant, libelle in entites:
        for valeur in (identifiant, libelle):
            if not valeur:
                continue
            formes = _termes(valeur)
            reconnu = any(forme in presents or (" " in forme and forme in plie)
                          or (len(forme) >= 4 and forme in plie)
                          for forme in formes)
            if reconnu:
                trouves.append((len(plier(valeur)),
                                Candidat(identifiant=str(identifiant),
                                         libelle=str(libelle or ""))))
                break
    trouves.sort(key=lambda couple: (-couple[0], couple[1].identifiant))
    vus: Dict[str, Candidat] = {}
    for _, candidat in trouves:
        vus.setdefault(candidat.identifiant, candidat)
    return list(vus.values())[:CANDIDATS_MAX]


# ------------------------------------------------- le recours au modèle


CONSIGNE_ROUTAGE = (
    "On te donne une question posée par un analyste dans un outil de "
    "gouvernance des habilitations, et la liste fermée des questions que "
    "l'outil sait calculer.\n"
    "Ta seule tâche : dire laquelle de ces questions correspond.\n"
    "Règles :\n"
    "- Réponds par un code de la liste, jamais par autre chose.\n"
    "- Si aucune ne correspond, réponds par une chaîne vide.\n"
    "- N'écris aucune phrase, aucun chiffre, aucun nom.\n"
    "Réponds uniquement par un objet JSON avec une clé \"intention\", la "
    "valeur étant le code retenu."
)

#: Les noms sous lesquels un modèle rend son choix.
CHAMPS_DE_L_INTENTION = ("intention", "code", "question", "intent")

SCHEMA_DU_ROUTAGE: Dict[str, Any] = {
    "type": "object",
    "properties": {"intention": {"type": "string"}},
    "required": ["intention"],
    "additionalProperties": False,
}


def lire_l_intention(charge: Mapping[str, Any],
                     connues: Sequence[str]) -> Dict[str, Any]:
    """Lit le code rendu, et refuse tout ce qui n'est pas dans la liste.

    Un modèle qui répond « porteurs_du_role_applicatif » n'a pas choisi dans la
    liste : il a inventé un code voisin. L'accepter reviendrait à exécuter une
    question que le produit n'a pas définie — le refus déclenche la reprise
    guidée, qui lui montre sa réponse et la liste.
    """
    lu = protocole.extraire_le_json(protocole.contenu_de_la_reponse(charge))
    if not isinstance(lu, Mapping):
        raise ReponseInexploitable("réponse illisible")
    code = str(protocole.champ(lu, CHAMPS_DE_L_INTENTION) or "").strip()
    if not code:
        # Une intention vide est une réponse valable : le modèle dit qu'aucune
        # question de la liste ne correspond, et c'est mieux qu'un choix au
        # hasard.
        return {"intention": ""}
    if code not in connues:
        raise ReponseInexploitable(
            f"intention hors liste : {code}", {"intention_inconnue": code})
    return {"intention": code}


def router_par_le_modele(question: str, reglages: Reglages,
                         autorisation: Autorisation, langue: str,
                         traduire: Callable[[str], str],
                         envoyer, candidates: Sequence[Intention] = ()
                         ) -> Routage:
    """Demande au modèle laquelle des questions connues correspond.

    La question part **telle quelle** : c'est la seule façon de la router, et
    c'est pourquoi elle est déclarée comme matière. Sans cette autorisation,
    l'agent s'en tient à ce que le routage local a compris.

    Ce qui part avec elle : les codes des intentions et leurs libellés
    traduits. Aucun nom de rôle, aucun droit, aucune identité — le modèle
    choisit une question, il ne désigne pas un objet du référentiel.
    """
    if not reglages.actif:
        raise AnnotateurIndisponible("assistance désactivée")
    # `posable` couvre la question elle-même : elle est déclarée *nécessaire*
    # à cet usage, donc un usage posable est un usage dont la question a le
    # droit de sortir. Un second contrôle ici serait du code que rien ne peut
    # atteindre — et donc du code que rien ne vérifie.
    if not autorisation.posable:
        raise AnnotateurIndisponible("usage fermé ou question non autorisée")

    proposees = tuple(candidates) or INTENTIONS
    faits = {
        "question": str(question or "")[:LONGUEUR_QUESTION_MAX],
        "questions_possibles": [
            {"code": intention.code, "libelle": traduire(intention.cle_libelle)}
            for intention in proposees
        ],
    }
    connues = [intention.code for intention in proposees]
    charge = composer_la_demande_de(CONSIGNE_ROUTAGE, faits, reglages, langue)
    rendu = demander(charge, reglages,
                     lambda reponse: lire_l_intention(reponse, connues),
                     SCHEMA_DU_ROUTAGE, envoyer)
    code = rendu["intention"]
    if not code:
        return Routage()
    return Routage(intention=PAR_CODE[code], origine=ORIGINE_MODELE)
