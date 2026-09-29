# src/core/annotation/explication.py
"""Expliquer un rôle en une phrase, sans qu'aucun chiffre ne soit inventé.

Le produit sait déjà dire *ce qu'ont ces gens en commun* : une règle
d'attributs, une population, un sur-octroi, une fiabilité. Il le dit en
grandeurs. Le responsable d'application, lui, attend une phrase — et c'est le
livrable que le consultant rédige à la main, rôle par rôle, à la fin du projet.

**Le point délicat n'est pas la rédaction, c'est le contrôle.** Un modèle à qui
l'on donne des nombres et à qui l'on demande un paragraphe en produira un qui
se lit très bien et qui annoncera, une fois sur dix, un effectif qu'il a
arrondi, additionné ou simplement inventé. Personne ne le verra : la phrase est
crédible, et c'est précisément ce qui la rend dangereuse. Un chiffre faux dans
un document de gouvernance vaut mieux ne pas exister.

D'où la règle, qui est la seule raison d'être de ce module : **tout nombre écrit
dans la phrase doit figurer parmi ceux transmis.** Le contrôle relève les
nombres du texte rendu et les confronte à la liste envoyée ; il suffit d'un
intrus pour que la phrase soit refusée — jamais corrigée, jamais tronquée. Une
phrase amputée de son chiffre faux resterait une phrase que le produit a
réécrite, et le lecteur n'aurait aucun moyen de le savoir.

Le refus n'est pas une panne : il déclenche la reprise guidée du protocole, qui
montre au modèle sa propre phrase et le nombre qu'il a inventé. Un modèle
correct se corrige au second passage ; un modèle qui recommence n'est pas bon
pour cet usage, et l'écran le dit plutôt que de publier sa phrase.

**Ce que le contrôle ne couvre pas, et il faut le savoir :** un nombre écrit en
toutes lettres — « trois cents personnes » — n'est pas un nombre pour ce
relevé. La consigne demande explicitement des chiffres, et les cas observés
écrivent des chiffres quand on leur en donne ; mais la garantie porte sur les
chiffres, pas sur la langue. C'est une limite connue, écrite ici, et non une
omission.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Mapping, Sequence, Set, Tuple

from src.core.annotation import protocole
from src.core.annotation.annotateur import (
    LONGUEUR_DESCRIPTION_MAX,
    AnnotateurIndisponible,
    Reglages,
    ReponseInexploitable,
    RienANommer,
    _nettoyer,
    demander,
)
from src.core.annotation.assistance import (
    MATIERE_LIBELLES_DE_DROITS,
    MATIERE_REGLE_METIER,
    Autorisation,
)
from src.core.annotation.propositions import composer_la_demande_de

logger = logging.getLogger(__name__)

#: Longueur maximale du paragraphe rendu. Un texte plus long qu'un paragraphe
#: n'est plus une explication : c'est un rapport, et personne ne le relira.
LONGUEUR_EXPLICATION_MAX = 1200

#: Droits nommés dans la demande. Au-delà, la phrase citerait une liste plutôt
#: que d'expliquer.
DROITS_CITES_MAX = 12

#: Les noms sous lesquels un modèle rend son paragraphe.
CHAMPS_DE_L_EXPLICATION = ("explication", "texte", "paragraphe", "text",
                           "explanation", "resume", "summary")

#: Tout groupe de chiffres, séparateurs de milliers compris — espace fine,
#: espace insécable, espace ordinaire, point ou virgule entre deux groupes de
#: trois. Les décimales aussi : « 87,5 % » doit être relevé comme 87,5 et non
#: comme 87 puis 5.
_NOMBRE = re.compile(r"\d+(?:[    .,]\d+)*")

#: Ce qui sépare les milliers. Retiré avant comparaison : le produit transmet
#: `1751`, le modèle écrit « 1 751 », et ce sont le même nombre.
_SEPARATEURS = str.maketrans({" ": "", " ": "", " ": "",
                              " ": ""})


def grandeurs_du_role(role: Mapping[str, Any],
                      explication: Mapping[str, Any] = None) -> Dict[str, float]:
    """Les nombres que le produit transmet, et les seuls qu'il acceptera en retour.

    Nommés plutôt qu'alignés : un modèle à qui l'on donne « 340, 12, 87 » écrit
    une phrase qui les emploie au hasard. Le nom porte le sens, et c'est aussi
    ce qui permet au contrôle de dire *lequel* a été inventé.

    Les absents ne sont pas transmis à zéro : un indicateur non mesuré et un
    indicateur nul ne sont pas la même chose, et un modèle à qui l'on annonce
    « sur-octroi : 0 » écrira que le rôle n'accorde rien en trop — ce qui serait
    une affirmation que personne n'a mesurée.
    """
    brut = {
        "porteurs": role.get("user_count"),
        "droits": role.get("right_count") or (
            len(role.get("rights") or ()) or None),
        "couverture_pct": role.get("coverage_pct"),
        "sur_octroi": role.get("stats_over_provisioning"),
        "redondance_pct": role.get("redondance_pct"),
    }
    if explication:
        brut["fiabilite_pct"] = explication.get("fiabilite_pct")
        brut["pouvoir_explicatif_pct"] = explication.get("pouvoir_explicatif_pct")
    grandeurs: Dict[str, float] = {}
    for nom, valeur in brut.items():
        if valeur is None:
            continue
        try:
            grandeurs[nom] = float(valeur)
        except (TypeError, ValueError):
            continue
    return grandeurs


def nombres_du_texte(texte: str) -> List[str]:
    """Tous les nombres écrits en chiffres, sous leur forme normalisée.

    « 1 751 », « 1751 » et « 1 751 » avec une espace insécable sont le même
    nombre ; « 87,5 » et « 87.5 » aussi. La normalisation retire les
    séparateurs de milliers et ramène la virgule décimale au point, pour que la
    comparaison porte sur la valeur et non sur la typographie.
    """
    releves: List[str] = []
    for brut in _NOMBRE.findall(texte or ""):
        releves.append(_normaliser(brut))
    return releves


def _normaliser(brut: str) -> str:
    """Un nombre écrit, ramené à sa valeur comparable.

    Le point et la virgule sont ambigus : `1.751` est un séparateur de milliers
    en France et un décimal ailleurs. La règle retenue est celle qui **ne crée
    pas de faux négatif** : les deux lectures sont acceptées au moment de la
    comparaison, et c'est `_valeurs_acceptables` qui les produit.
    """
    return brut.translate(_SEPARATEURS)


def _valeurs_acceptables(normalise: str) -> Set[float]:
    """Les valeurs qu'un nombre écrit peut désigner, ponctuation comprise."""
    lectures = {normalise, normalise.replace(",", "."),
                normalise.replace(".", ""), normalise.replace(",", "")}
    valeurs: Set[float] = set()
    for lecture in lectures:
        try:
            valeurs.add(float(lecture))
        except ValueError:
            continue
    return valeurs


def nombres_inventes(texte: str,
                     grandeurs: Mapping[str, float]) -> List[str]:
    """Les nombres de la phrase qui ne figurent pas parmi ceux transmis.

    La comparaison est **numérique**, pas textuelle : `87.0` transmis et « 87 »
    écrit sont le même nombre, et refuser sur la forme ferait échouer des
    phrases justes.

    Un entier tiré d'un pourcentage décimal est accepté : le produit transmet
    `87.5` et la phrase écrit « 87 % » — c'est un arrondi de ce qu'on lui a
    donné, pas une invention. Refuser l'arrondi rendrait l'usage inutilisable
    sans rien protéger : le lecteur ne peut pas être trompé par un nombre plus
    imprécis que celui d'origine.
    """
    connus = set(grandeurs.values())
    arrondis = {float(int(valeur)) for valeur in connus}
    admis = connus | arrondis
    intrus: List[str] = []
    for brut in _NOMBRE.findall(texte or ""):
        valeurs = _valeurs_acceptables(_normaliser(brut))
        if not (valeurs & admis):
            intrus.append(brut)
    return intrus


CONSIGNE_EXPLICATION = (
    "On te donne les grandeurs d'un rôle d'habilitations, déjà calculées. Tu "
    "rédiges un paragraphe court qui explique ce rôle à un responsable "
    "d'application : qui il regroupe, ce qu'il donne accès, et ce qu'il "
    "changerait.\n"
    "Règles, et la première est absolue :\n"
    "- N'écris AUCUN nombre qui ne soit pas dans les grandeurs données. Ne "
    "calcule rien, n'additionne rien, ne complète rien. Si une grandeur n'est "
    "pas donnée, n'en parle pas.\n"
    "- Écris les nombres en chiffres, jamais en toutes lettres.\n"
    "- Un paragraphe, pas de liste, pas de titre.\n"
    "- Suis la langue demandée.\n"
    "Réponds uniquement par un objet JSON avec une clé \"explication\", la "
    "valeur étant le paragraphe."
)


def lire_l_explication(charge: Mapping[str, Any],
                       grandeurs: Mapping[str, float]) -> Dict[str, Any]:
    """Lit le paragraphe, et le refuse dès qu'il porte un nombre inventé.

    Refusé, jamais corrigé. Retirer le chiffre faux laisserait une phrase que
    le produit a réécrite sans que le lecteur puisse le savoir — et c'est
    exactement la confusion que ce module existe pour empêcher.
    """
    lu = protocole.extraire_le_json(protocole.contenu_de_la_reponse(charge))
    if not isinstance(lu, Mapping):
        raise ReponseInexploitable("réponse illisible")
    texte = _nettoyer(protocole.champ(lu, CHAMPS_DE_L_EXPLICATION),
                      LONGUEUR_EXPLICATION_MAX)
    if not texte:
        raise ReponseInexploitable("réponse sans explication")

    intrus = nombres_inventes(texte, grandeurs)
    if intrus:
        logger.info("Explication refusée : nombres absents des grandeurs %s",
                    ", ".join(intrus[:5]))
        raise ReponseInexploitable(
            "nombres inventés : " + ", ".join(intrus[:5]),
            {"nombres_inventes": intrus[:5]})
    return {"explication": texte}


def expliquer_un_role(reglages: Reglages, autorisation: Autorisation,
                      role: Mapping[str, Any],
                      explication: Mapping[str, Any], langue: str,
                      envoyer) -> Dict[str, Any]:
    """Rédige l'explication d'un rôle, ou ne rend rien.

    Les grandeurs partent toujours : ce sont des comptes, ils ne désignent
    personne. La règle et les libellés de droits ne partent que si
    l'administrateur les a ouverts **pour cet usage** — et sans aucun des deux,
    la question ne se pose pas : un paragraphe rédigé à partir de deux nombres
    et de rien d'autre invente une finalité, c'est le défaut déjà observé sur
    le nommage.
    """
    if not reglages.actif:
        raise AnnotateurIndisponible("assistance désactivée")
    if not autorisation.posable:
        raise RienANommer("usage fermé ou matière non autorisée")

    grandeurs = grandeurs_du_role(role, explication)
    if not grandeurs:
        raise RienANommer("aucune grandeur à expliquer")

    faits: Dict[str, Any] = {"grandeurs": grandeurs}
    categories: List[str] = []
    if autorisation.autorise(MATIERE_REGLE_METIER) and (explication or {}).get("regle"):
        faits["regle"] = [{"attribut": str(terme.get("attribut", "")),
                           "valeur": str(terme.get("valeur", ""))}
                          for terme in explication["regle"]]
        categories.append(MATIERE_REGLE_METIER)
    if autorisation.autorise(MATIERE_LIBELLES_DE_DROITS):
        droits = [str(droit) for droit in (role.get("rights") or ())]
        if droits:
            faits["droits"] = droits[:DROITS_CITES_MAX]
            categories.append(MATIERE_LIBELLES_DE_DROITS)
    if not categories:
        raise RienANommer("aucune matière disponible")

    charge = composer_la_demande_de(CONSIGNE_EXPLICATION, faits, reglages, langue)
    rendu = demander(charge, reglages,
                     lambda reponse: lire_l_explication(reponse, grandeurs),
                     SCHEMA_DE_L_EXPLICATION, envoyer)
    return {
        "explication": rendu["explication"],
        "grandeurs": grandeurs,
        "modele": reglages.modele,
        "usage": autorisation.usage.code,
        "categories_transmises": sorted(categories),
    }


#: Le schéma imposé au moteur quand il sait l'imposer. Il ne contraint que la
#: forme : aucun schéma ne peut interdire un nombre inventé dans une phrase,
#: et c'est le contrôle qui s'en charge.
SCHEMA_DE_L_EXPLICATION: Dict[str, Any] = {
    "type": "object",
    "properties": {"explication": {"type": "string"}},
    "required": ["explication"],
    "additionalProperties": False,
}
