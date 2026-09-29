# src/core/annotation/protocole.py
"""Obtenir une réponse exploitable d'un modèle qu'on n'a pas choisi.

Le produit s'installe chez le client, sur son serveur, avec le modèle qu'il
sert — un petit modèle local sur une machine sans accès, un moteur
d'entreprise, un service distant. Le produit ne choisit pas, ne recommande
pas, et ne doit pas dépendre de ce choix.

Il faut donc séparer deux choses, dont une seule relève du produit :

- **le jugement.** Savoir que `jobtitle` porte du métier et `last_name` non.
  Un modèle vaut ce qu'il vaut ; aucun code ne rendra bon celui qui se trompe.
  Ce n'est pas grave : le produit ne décide rien sur cette base, il propose, et
  un humain tranche.
- **le protocole.** Obtenir une réponse exploitable quelle que soit la façon
  dont le modèle la met en forme. Cela relève entièrement du produit, et
  c'était **le facteur limitant** : la lecture exigeait un objet JSON nu, alors
  qu'un modèle encadre volontiers sa réponse de ``` ou la fait précéder d'une
  phrase. Une réponse parfaitement juste était déclarée illisible.

Quatre mécanismes, du plus fort au plus tolérant. Aucun ne présume du
fournisseur ; chacun découvre à l'exécution ce que le serveur accepte.

1. **La contrainte négociée.** Le produit propose le niveau le plus fort — un
   schéma JSON — et redescend d'un cran à chaque refus du serveur, jusqu'à
   l'appel nu. Ce qu'un point de terminaison a accepté est retenu pour la durée
   du processus : on ne renégocie pas à chaque demande.
2. **L'extraction tolérante.** L'objet JSON est cherché *dans* le texte rendu,
   qu'il soit encadré, précédé d'une explication ou suivi d'un commentaire.
3. **La normalisation des formes.** Un objet sous une autre clé, une liste nue,
   un dictionnaire au lieu d'une liste d'objets, des clés en anglais : ce sont
   des écritures différentes de la même information, et elles se reconnaissent
   **de façon déterministe**. Ce module ne devine jamais : il reconnaît une
   forme, ou il n'en reconnaît aucune.
4. **La reprise guidée, une seule fois.** Si rien n'est exploitable, la demande
   repart une fois avec la réponse reçue et la forme attendue. Deux reprises
   seraient une boucle sur un modèle qui ne sait pas répondre.

Ce qui n'est pas ici : aucune tolérance sur le **contenu**. Une valeur qui
n'existe pas dans le référentiel reste écartée par l'usage qui l'a demandée.
Ce module rend lisible ce qui a été dit ; il ne rend pas vrai ce qui est faux.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# ------------------------------------------------- les niveaux de contrainte

#: Un schéma JSON imposé au moteur : la réponse ne peut pas prendre une autre
#: forme. C'est le seul niveau qui contraint aussi les **valeurs** d'un champ
#: — une classe hors de l'énumération devient impossible plutôt qu'écartée.
NIVEAU_SCHEMA = "json_schema"
#: Un objet JSON imposé, sans contrainte sur les clés. Écarte les réponses en
#: prose et les blocs encadrés.
NIVEAU_OBJET = "json_object"
#: Rien d'imposé : la consigne seule. Le niveau que tout point de terminaison
#: accepte, y compris ceux qui ne connaissent pas `response_format`.
NIVEAU_NU = "aucun"

#: Du plus contraignant au plus tolérant. La négociation descend cette liste.
NIVEAUX: Tuple[str, ...] = (NIVEAU_SCHEMA, NIVEAU_OBJET, NIVEAU_NU)

#: Ce qu'un point de terminaison a **refusé**, par adresse : le premier niveau
#: qu'il vaut encore la peine de lui proposer.
#:
#: La mémoire retient les refus et non les acceptations, et la nuance compte.
#: Qu'un serveur accepte un objet JSON ne prouve pas qu'il refuse un schéma —
#: on ne le lui a peut-être jamais demandé, parce que l'usage en cours n'en
#: avait pas. Retenir l'acceptation abaisserait définitivement la contrainte
#: sur la foi d'un essai qui n'a rien essayé.
#:
#: Mémoire de processus, jamais écrite sur disque : c'est une observation sur
#: le serveur en face, pas un réglage du client, et elle doit se refaire si
#: l'exploitant change de moteur derrière la même adresse.
_REFUSES: Dict[str, str] = {}


def niveau_connu(adresse: str) -> Optional[str]:
    """Le premier niveau encore à proposer, si ce serveur en a déjà refusé."""
    return _REFUSES.get(adresse)


def retenir_le_refus(adresse: str, niveau: str) -> None:
    """Ce niveau a été refusé : on ne le proposera plus à ce serveur."""
    rang = NIVEAUX.index(niveau) + 1
    if rang >= len(NIVEAUX):
        return
    suivant = NIVEAUX[rang]
    acquis = _REFUSES.get(adresse)
    if acquis is None or NIVEAUX.index(suivant) > NIVEAUX.index(acquis):
        _REFUSES[adresse] = suivant


#: Les points de terminaison qui n'acceptent la demande **que sans** réglage de
#: température.
#:
#: Le produit envoie `temperature: 0` pour qu'une demande rejouée rende la même
#: proposition. Plusieurs modèles récents refusent toute autre valeur que la
#: leur — constaté sur OpenAI : « 'temperature' does not support 0 with this
#: model. Only the default (1) value is supported. » Le refus arrive au niveau
#: nu, que la négociation des contraintes ne sait pas dépasser : l'annotateur
#: concluait « injoignable » sur un modèle qui répondait parfaitement à l'essai.
#:
#: On ne retient ce fait qu'après une demande **réussie** sans température :
#: un serveur qui refuse pour une autre raison — un modèle inconnu, une clé
#: sans crédit — refuserait de nouveau, et la reproductibilité ne doit pas se
#: perdre sur un malentendu.
_SANS_TEMPERATURE: set = set()


def temperature_imposee(adresse: str) -> bool:
    """Ce serveur n'accepte-t-il la demande que sans réglage de température ?"""
    return adresse in _SANS_TEMPERATURE


def retenir_la_temperature_imposee(adresse: str) -> None:
    _SANS_TEMPERATURE.add(adresse)


def oublier_les_niveaux() -> None:
    """Repart de zéro. Utile aux tests, et au changement de configuration."""
    _REFUSES.clear()
    _SANS_TEMPERATURE.clear()


def niveaux_a_tenter(adresse: str,
                     schema: Optional[Mapping[str, Any]] = None) -> Tuple[str, ...]:
    """Ce qu'il faut essayer, dans l'ordre, pour ce point de terminaison.

    Un niveau déjà refusé n'est pas reproposé : sonder à chaque demande ferait
    payer deux appels ratés à chaque proposition, sur un serveur qu'on sait
    déjà limité.

    Sans schéma, le niveau le plus fort est sauté : il ne contraindrait rien et
    coûterait un aller-retour pour rien.
    """
    depart = _REFUSES.get(adresse) or NIVEAUX[0]
    tentables = NIVEAUX[NIVEAUX.index(depart):]
    if not schema:
        tentables = tuple(niveau for niveau in tentables
                          if niveau != NIVEAU_SCHEMA)
    return tentables


def contrainte(niveau: str, schema: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Le fragment de charge utile qui exprime ce niveau de contrainte.

    La forme employée est celle de l'API la plus répandue. Un serveur qui ne la
    connaît pas répond une erreur, et la négociation redescend : le produit n'a
    pas à savoir à l'avance qui accepte quoi.
    """
    if niveau == NIVEAU_SCHEMA and schema:
        return {"response_format": {"type": "json_schema",
                                    "json_schema": {"name": "reponse",
                                                    "strict": True,
                                                    "schema": dict(schema)}}}
    if niveau == NIVEAU_OBJET:
        return {"response_format": {"type": "json_object"}}
    return {}


# ------------------------------------------------------ l'extraction du JSON

#: Un bloc encadré, avec ou sans langage annoncé. Les modèles bavards y mettent
#: leur objet et écrivent une phrase autour.
_ENCADRE = re.compile(r"```(?:json|JSON)?\s*(.+?)```", re.DOTALL)


def extraire_le_json(texte: Any) -> Any:
    """Le premier objet ou tableau JSON que ce texte contient.

    Trois lectures, dans l'ordre : le texte entier, le contenu d'un bloc
    encadré, puis le premier fragment équilibré trouvé dans la prose. La
    dernière est celle qui rattrape « Voici le classement demandé : {...}
    J'espère que cela convient. »

    Rend `None` quand il n'y a rien à lire — jamais d'exception : l'appelant
    distingue « rien de lisible » de « lisible mais inutilisable », et les deux
    ne se disent pas pareil à l'écran.
    """
    if isinstance(texte, (Mapping, list)):
        return texte
    if not isinstance(texte, str) or not texte.strip():
        return None

    for candidat in _candidats(texte):
        try:
            return json.loads(candidat)
        except (ValueError, json.JSONDecodeError):
            continue
    return None


def _candidats(texte: str) -> Iterable[str]:
    """Les fragments à tenter, du plus probable au plus laborieux."""
    yield texte.strip()
    for bloc in _ENCADRE.findall(texte):
        yield bloc.strip()
    fragment = _fragment_equilibre(texte)
    if fragment:
        yield fragment


def _fragment_equilibre(texte: str) -> str:
    """Le premier objet ou tableau équilibré du texte, chaînes comprises.

    Le comptage ignore les accolades qui vivent dans une chaîne JSON, sans quoi
    un motif comme `{service}` dans un libellé fermerait le fragment trop tôt.
    """
    ouvrants = {"{": "}", "[": "]"}
    for debut, caractere in enumerate(texte):
        if caractere not in ouvrants:
            continue
        attendu, profondeur, dans_chaine, echappe = ouvrants[caractere], 0, False, False
        for position in range(debut, len(texte)):
            courant = texte[position]
            if echappe:
                echappe = False
                continue
            if courant == "\\":
                echappe = True
                continue
            if courant == '"':
                dans_chaine = not dans_chaine
                continue
            if dans_chaine:
                continue
            if courant == caractere:
                profondeur += 1
            elif courant == attendu:
                profondeur -= 1
                if profondeur == 0:
                    return texte[debut:position + 1]
        return ""
    return ""


def contenu_de_la_reponse(charge: Mapping[str, Any]) -> Any:
    """Le texte rendu par le modèle, quelle que soit l'enveloppe.

    La forme répandue est `choices[0].message.content`. D'autres moteurs
    rendent `choices[0].text`, ou un objet déjà décodé. Aucune n'est plus
    légitime qu'une autre : le produit les lit toutes plutôt que d'imposer la
    sienne.
    """
    if not isinstance(charge, Mapping):
        return None
    choix = charge.get("choices")
    if isinstance(choix, Sequence) and not isinstance(choix, (str, bytes)) and choix:
        premier = choix[0]
        if isinstance(premier, Mapping):
            message = premier.get("message")
            if isinstance(message, Mapping) and message.get("content") is not None:
                return message["content"]
            if premier.get("text") is not None:
                return premier["text"]
    # Certains moteurs rendent directement l'objet demandé, sans enveloppe.
    for cle in ("content", "response", "output"):
        if charge.get(cle) is not None:
            return charge[cle]
    return None


# --------------------------------------------------- la forme de la réponse


def liste_sous(charge: Any, cles: Sequence[str]) -> Optional[List[Any]]:
    """La liste d'entrées d'une réponse, quelle que soit son enveloppe.

    Quatre formes reconnues, et aucune devinée :

    - `{"colonnes": [...]}` — la forme demandée ;
    - `[...]` — la liste nue, sans enveloppe ;
    - `{"columns": [...]}` — la même clé dans une autre langue, si elle figure
      parmi celles que l'usage accepte ;
    - `{...}` contenant **une seule** liste, sous une clé quelconque. Une
      enveloppe à deux listes n'est pas reconnue : choisir laquelle serait
      deviner.

    Rend `None` si aucune ne s'applique. Une liste vide, elle, est une réponse
    valide : le modèle n'a rien trouvé, et ce n'est pas la même chose.
    """
    if isinstance(charge, list):
        return charge
    if not isinstance(charge, Mapping):
        return None
    for cle in cles:
        valeur = charge.get(cle)
        if isinstance(valeur, list):
            return valeur
    listes = [valeur for valeur in charge.values() if isinstance(valeur, list)]
    if len(listes) == 1:
        return listes[0]
    return None


def champ(entree: Mapping[str, Any], noms: Sequence[str]) -> Any:
    """La valeur d'un champ, sous l'un quelconque des noms admis.

    La correspondance ignore la casse et les séparateurs : `forme_retenue`,
    `formeRetenue` et `Forme Retenue` désignent le même champ. Les noms admis
    restent déclarés par l'usage — ce module ne décide pas qu'un champ inconnu
    en vaut un autre.
    """
    index = {_cle(nom): valeur for nom, valeur in entree.items()}
    for nom in noms:
        valeur = index.get(_cle(nom))
        if valeur is not None:
            return valeur
    return None


def _cle(nom: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(nom).casefold())


def paires_du_dictionnaire(charge: Any, cle_gauche: str,
                           cle_droite: str) -> Optional[List[Dict[str, Any]]]:
    """Un dictionnaire `{gauche: droite}` relu comme une liste d'entrées.

    `{"jobtitle": "metier", "last_name": "identifiant"}` dit exactement ce que
    dit la liste d'objets demandée, en plus court — et c'est une forme que les
    modèles rendent spontanément. La reconnaître ne coûte rien et évite de
    jeter une réponse juste.

    Seul un dictionnaire dont **toutes** les valeurs sont des chaînes est lu
    ainsi : dès qu'une valeur est un objet ou une liste, la forme est autre
    chose, et la reconnaître serait deviner.
    """
    if not isinstance(charge, Mapping) or not charge:
        return None
    if not all(isinstance(valeur, str) for valeur in charge.values()):
        return None
    return [{cle_gauche: str(gauche), cle_droite: droite}
            for gauche, droite in charge.items()]
