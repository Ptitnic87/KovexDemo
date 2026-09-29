# Fichier : src/core/annotation/redaction.py
"""Faire rédiger une réponse sans lui donner ni chiffre ni identité.

L'assistant du lot 59 répondait par des phrases du catalogue de traduction,
remplies avec les nombres du produit. C'était vérifiable, et cela se lisait
comme un moteur de recherche déguisé : « 12 identités portent le rôle
Comptable. » Personne ne converse avec un gabarit.

Le faire rédiger par un modèle pose deux problèmes que ce module résout d'un
seul geste.

**Le chiffre.** Un modèle à qui l'on donne des nombres et à qui l'on demande une
phrase en invente un de temps en temps. Le lot 53 le contrôle après coup : il
relève les nombres du texte et refuse la phrase s'il en trouve un qui n'a pas
été transmis. Le contrôle est réel, mais il est faillible par construction — un
nombre écrit en toutes lettres lui échappe.

**L'identité.** Rédiger « Franck a deux comptes » demanderait d'envoyer Franck.
Or la règle du produit est qu'aucune case à cocher ne fait sortir les identités.

La réponse aux deux : **le modèle écrit un gabarit, le produit le remplit.** Il
ne reçoit pas « 12 », il reçoit le nom d'un emplacement — `porteurs` — et il
écrit « {porteurs} personnes portent ce rôle ». Il ne reçoit pas `fkciadm1`, il
reçoit `compte_2`. Le produit substitue ensuite, localement.

Ce que cela rend possible, et qui n'existait pas :

- **tout chiffre écrit en clair fait refuser la phrase**, pas seulement les
  chiffres inconnus. Un modèle n'a aucune raison d'écrire un nombre : on ne lui
  en a donné aucun. « Trois cents personnes » tombe aussi, puisque la phrase
  n'a pas à contenir de quantité du tout ;
- **aucune identité ne sort**, et la règle n'a pas eu besoin d'être assouplie ;
- **un emplacement inventé fait refuser la phrase** : le modèle ne peut pas
  inventer une grandeur qu'on ne lui a pas proposée, puisqu'il ne peut employer
  que les noms de la liste.

Ce que cela ne garantit pas, et il faut le savoir : le modèle reste libre du
**commentaire**. Il peut écrire « c'est beaucoup » là où ce n'est pas beaucoup.
La consigne le lui interdit, la température est à zéro, et la phrase est
refusée si elle est manifestement hors sujet — mais la garantie porte sur les
faits, pas sur le ton. C'est une limite connue, écrite ici, et non une omission.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Mapping, Sequence, Set, Tuple

from src.core.annotation import protocole
from src.core.annotation.annotateur import (
    AnnotateurIndisponible,
    Reglages,
    ReponseInexploitable,
    RienANommer,
    _nettoyer,
    demander,
)
from src.core.annotation.assistance import Autorisation
from src.core.annotation.propositions import composer_la_demande_de

logger = logging.getLogger(__name__)

#: Longueur maximale d'une réponse rédigée. Au-delà, ce n'est plus une réponse
#: à une question : c'est un rapport, et personne ne le lira dans un panneau.
LONGUEUR_REPONSE_MAX = 900

#: Les noms sous lesquels un modèle rend son gabarit.
CHAMPS_DE_LA_REPONSE = ("reponse", "phrase", "texte", "answer", "response",
                        "text")

#: Un emplacement : `{nom}`. Les noms sont ceux que le produit propose, et
#: aucun autre.
EMPLACEMENT = re.compile(r"\{([a-z0-9_]+)\}")

#: Tout groupe de chiffres. Le modèle n'en reçoit aucun : il n'a donc aucune
#: raison d'en écrire, et un seul suffit à refuser la phrase.
CHIFFRES = re.compile(r"\d")

#: Accolade ouvrante ou fermante restée seule — « {porteurs » ou « porteurs} ».
#: Substituée, elle laisserait une accolade à l'écran.
ACCOLADE_ISOLEE = re.compile(r"\{(?![a-z0-9_]+\})|(?<![a-z0-9_])\}")


class ReponseRefusee(ReponseInexploitable):
    """La phrase rendue ne respecte pas le contrat du gabarit.

    Distinguée d'une panne : le modèle a répondu, et ce qu'il a répondu ne peut
    pas être publié. L'écran doit pouvoir dire lequel des deux s'est produit —
    chercher un serveur injoignable là où un modèle a écrit un chiffre fait
    perdre une journée.
    """


def emplacements_du_texte(texte: str) -> List[str]:
    """Les emplacements employés par le gabarit, dans l'ordre d'apparition."""
    return EMPLACEMENT.findall(texte or "")


def controler_le_gabarit(texte: str, proposes: Mapping[str, Any]) -> None:
    """Refuse un gabarit qui sort du contrat. Jamais de correction.

    Retirer le chiffre fautif laisserait une phrase que le produit a réécrite
    sans que le lecteur puisse le savoir — c'est exactement la confusion que ce
    module existe pour empêcher.
    """
    # Les chiffres se cherchent **hors des emplacements** : un nom d'emplacement
    # en porte légitimement — `compte_1`, `droits_2` — quand la réponse parle
    # de plusieurs comptes d'une même personne. Les compter comme des chiffres
    # écrits ferait refuser toutes ces réponses-là.
    hors_emplacements = EMPLACEMENT.sub(" ", texte)
    if CHIFFRES.search(hors_emplacements):
        intrus = sorted(set(re.findall(r"\d+(?:[.,]\d+)?", hors_emplacements)))
        raise ReponseRefusee(
            "chiffres écrits en clair : " + ", ".join(intrus[:5]),
            {"chiffres_ecrits": intrus[:5]})

    employes = emplacements_du_texte(texte)
    inconnus = sorted({nom for nom in employes if nom not in proposes})
    if inconnus:
        raise ReponseRefusee(
            "emplacements inventés : " + ", ".join(inconnus[:5]),
            {"emplacements_inventes": inconnus[:5]})

    if ACCOLADE_ISOLEE.search(texte):
        raise ReponseRefusee("accolade restée seule", {"accolade": True})

    if not employes:
        # Une réponse qui n'emploie aucune grandeur ne répond à rien : elle
        # commente. C'est le cas où le modèle a compris la consigne de forme et
        # pas la question.
        raise ReponseRefusee("réponse sans aucune grandeur",
                             {"sans_grandeur": True})


def remplir(texte: str, valeurs: Mapping[str, Any]) -> str:
    """Substitue les emplacements par les valeurs du produit.

    La substitution est faite **ici**, après le contrôle : c'est la seule
    étape où les chiffres et les identités rencontrent la phrase, et elle ne
    passe par aucun modèle.
    """
    return EMPLACEMENT.sub(
        lambda trouve: str(valeurs.get(trouve.group(1), trouve.group(0))), texte)


CONSIGNE_REDACTION = (
    "Tu réponds à un analyste dans un outil de gouvernance des habilitations. "
    "Tu connais le métier : un rôle regroupe des droits, un droit est une "
    "autorisation dans une application, une identité porte des rôles et des "
    "droits, le sur-octroi est ce qu'un rôle accorde et que ses porteurs ne "
    "détiennent pas, le socle est ce que tout le monde reçoit en arrivant, et "
    "un compte à privilèges est le compte d'administration d'une personne, "
    "distinct de son compte nominatif.\n"
    "On te donne : la question posée, ce que l'outil a calculé pour y répondre, "
    "et la liste des EMPLACEMENTS disponibles avec ce que chacun désigne.\n"
    "Tu rédiges la réponse en deux ou trois phrases, dans la langue demandée.\n"
    "Règles, et les deux premières sont absolues :\n"
    "- N'écris AUCUN chiffre. Pas un seul. Pour citer une quantité, écris son "
    "emplacement entre accolades, par exemple {porteurs}.\n"
    "- N'emploie QUE les emplacements de la liste. N'en invente aucun, ne les "
    "renomme pas.\n"
    "- Ne nomme aucune personne, aucun compte, aucun droit : ils ont leur "
    "emplacement.\n"
    "- Dis ce que les chiffres veulent dire pour la gouvernance, sans les "
    "qualifier de gros ou de petits : tu ne les connais pas.\n"
    "- Pas de liste, pas de titre, pas de formule de politesse.\n"
    "Réponds uniquement par un objet JSON avec une clé \"reponse\", la valeur "
    "étant le texte."
)

SCHEMA_DE_LA_REPONSE: Dict[str, Any] = {
    "type": "object",
    "properties": {"reponse": {"type": "string"}},
    "required": ["reponse"],
    "additionalProperties": False,
}


def lire_le_gabarit(charge: Mapping[str, Any],
                    proposes: Mapping[str, Any]) -> Dict[str, Any]:
    """Lit le gabarit rendu et le confronte au contrat."""
    lu = protocole.extraire_le_json(protocole.contenu_de_la_reponse(charge))
    if not isinstance(lu, Mapping):
        raise ReponseInexploitable("réponse illisible")
    texte = _nettoyer(protocole.champ(lu, CHAMPS_DE_LA_REPONSE),
                      LONGUEUR_REPONSE_MAX)
    if not texte:
        raise ReponseInexploitable("réponse vide")
    controler_le_gabarit(texte, proposes)
    return {"gabarit": texte}


def rediger(reglages: Reglages, autorisation: Autorisation, question: str,
            sujet: str, emplacements: Mapping[str, Any], langue: str,
            envoyer) -> Dict[str, Any]:
    """Fait rédiger la réponse, ou n'en rend aucune.

    `emplacements` associe un nom à sa valeur — un compte, un nombre, un nom de
    rôle. Seuls les **noms** partent ; les valeurs restent ici et ne
    rencontrent la phrase qu'à la substitution.
    """
    if not reglages.actif:
        raise AnnotateurIndisponible("assistance désactivée")
    if not autorisation.posable:
        raise RienANommer("usage fermé ou question non autorisée")
    if not emplacements:
        raise RienANommer("aucune grandeur à rédiger")

    faits = {
        "question": question,
        "sujet": sujet,
        # Ce qui part : des noms et ce qu'ils désignent. Aucune valeur.
        "emplacements": sorted(emplacements),
    }
    charge = composer_la_demande_de(CONSIGNE_REDACTION, faits, reglages, langue)
    rendu = demander(charge, reglages,
                     lambda reponse: lire_le_gabarit(reponse, emplacements),
                     SCHEMA_DE_LA_REPONSE, envoyer)
    return {
        "gabarit": rendu["gabarit"],
        "reponse": remplir(rendu["gabarit"], emplacements),
        "modele": reglages.modele,
    }
