# src/core/annotation/annotateur.py
"""Proposer un nom et une description de rôle, sans rien décider.

Un rôle nommé « Rôle applicatif exact trouvé pour 7 droits » ne sera validé
par personne. C'est le premier obstacle à l'adoption, et il n'a **aucun
substitut algorithmique** : fabriquer un libellé à partir des attributs
produirait un texte généré, non traduisible, qui donnerait à une corrélation
l'apparence d'une décision. Un modèle de langage, lui, peut proposer une
formulation — qu'un humain valide.

Trois principes gouvernent ce module, et chacun répond à un risque précis.

**Désactivé par défaut.** Sans adresse configurée dans l'environnement du
serveur, il n'existe pas. Ouvrir une sortie réseau depuis un serveur
d'habilitations est une décision d'infrastructure, pas un réglage applicatif.

**Rien ne sort qui n'ait été autorisé pour cet usage.** L'administrateur du
workspace décide, usage par usage, quelles catégories ont le droit de quitter
le système ; la matrice est tenue par `assistance.py`, et ce module n'en reçoit
que l'intersection qui le concerne. Une autorisation donnée au nommage
n'autorise aucune autre question. Les identités, elles, ne sortent jamais —
ce n'est pas un réglage.

**La réponse est du texte hostile.** Elle est bornée, nettoyée, et remplit un
champ que quelqu'un valide. Un modèle qui rendrait des instructions au lieu
d'un nom n'a aucun effet.

Le module n'ajoute aucune dépendance : le protocole visé est celui, très
répandu, de `POST /chat/completions`, et `urllib` de la bibliothèque standard
suffit à le parler. Un serveur isolé n'a rien à installer de plus.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib.parse import urlsplit

from src.core.annotation import protocole
from src.core.annotation.assistance import (
    MATIERE_LIBELLES_DE_DROITS,
    MATIERE_NOMS_VALIDES,
    MATIERE_REGLE_METIER,
    USAGE_NOMMAGE_DE_ROLE,
    Autorisation,
)

logger = logging.getLogger(__name__)

#: Bornes de sécurité, et non des choix métier : elles protègent l'affichage
#: et la taille de la demande, quelle que soit la configuration.
LONGUEUR_NOM_MAX = 120
LONGUEUR_DESCRIPTION_MAX = 600
DROITS_ENVOYES_MAX = 40
#: Exemples de nommage joints à la demande. Une demande qui grossirait avec le
#: catalogue finirait par dépasser ce que le modèle accepte — et la panne
#: arriverait chez le client qui a le plus de rôles validés, c'est-à-dire le
#: plus avancé.
EXEMPLES_MAX = 8
REPONSE_MAX_OCTETS = 64 * 1024
#: Longueur de la réponse recopiée dans la reprise. Assez pour que le modèle
#: reconnaisse ce qu'il a écrit, pas assez pour qu'une réponse bavarde fasse
#: déborder la demande.
LONGUEUR_REPRISE_MAX = 2000

#: Délai d'attente d'une réponse, quand l'exploitant n'en fixe aucun.
DELAI_PAR_DEFAUT_S = 20.0

#: Hôtes considérés comme locaux. Un envoi à l'un d'eux ne quitte pas la
#: machine ; tout le reste est une sortie du système d'information, et
#: l'administrateur doit le voir avant d'autoriser quoi que ce soit.
HOTES_LOCAUX = ("127.0.0.1", "localhost", "::1", "[::1]")


class AnnotateurIndisponible(RuntimeError):
    """L'annotateur n'a pas pu répondre. Jamais fatal : rien n'en dépend."""


class ReponseInexploitable(AnnotateurIndisponible):
    """Le modèle a répondu, et rien de sa réponse n'a pu être employé.

    Plus précise que `AnnotateurIndisponible`, dont elle hérite : pour le reste
    du produit, les deux disent « pas de proposition », et l'appelant qui ne
    fait pas la différence n'a rien à changer. La différence sert ici : celle-ci
    déclenche une reprise guidée, l'autre non — il n'y a rien à reprendre quand
    le modèle n'a pas répondu.

    Elle porte ce que la lecture a compris malgré tout — les comptes de ce
    qu'elle a écarté, et les mots qu'elle n'a pas su employer. Un usage peut
    ainsi rendre un résultat vide **et** dire pourquoi, plutôt qu'une panne.
    """

    def __init__(self, message: str, details: Optional[Mapping[str, Any]] = None):
        super().__init__(message)
        self.details: Dict[str, Any] = dict(details or {})


class RienANommer(RuntimeError):
    """Aucune matière n'a le droit de sortir : il n'y a rien à nommer.

    Distinct d'une panne. Le modèle répondrait — et c'est le problème : privé
    de tout, il invente une finalité. Observé sur un rôle réel avec les trois
    matières fermées, mistral a proposé « Garde des Droits », un intitulé
    qui a l'air d'un métier et ne désigne rien.

    Demander à la consigne d'être plus prudente ne suffit pas : un modèle de
    cette taille ne tient pas ce genre d'instruction. Le produit refuse donc
    la question, et dit ce qu'il faudrait autoriser pour la poser.
    """


@dataclass(frozen=True)
class Reglages:
    """Ce que l'infrastructure a configuré. Rien ici ne s'exporte.

    La clé n'est ni rendue, ni journalisée, ni comparée : elle ne sert qu'à
    composer l'en-tête d'autorisation.
    """

    adresse: str = ""
    modele: str = ""
    cle: str = ""
    delai_s: float = DELAI_PAR_DEFAUT_S

    @property
    def actif(self) -> bool:
        """Sans adresse ni modèle, l'annotateur n'existe pas."""
        return bool(self.adresse and self.modele)

    @property
    def locale(self) -> bool:
        """L'envoi reste-t-il sur la machine ?"""
        return urlsplit(self.adresse).hostname in HOTES_LOCAUX


def depuis_l_environnement(environnement: Mapping[str, str],
                           usage: str = "") -> Reglages:
    """Lit les réglages du serveur, éventuellement propres à un usage.

    Aucune valeur par défaut d'adresse : un défaut ferait d'un oubli de
    configuration un appel réseau silencieux depuis un serveur
    d'habilitations.

    **Un point de terminaison par usage, facultatif.** `KOVEX_ANNOTATEUR_URL`
    reste le réglage commun ; `KOVEX_ANNOTATEUR_URL_<USAGE>` le remplace pour
    un usage donné. Un client peut ainsi faire tourner le nommage sur un petit
    modèle local et n'ouvrir aucune autre sortie — ou l'inverse. Le trajet se
    décide comme la matière : usage par usage.

    **Le groupe se prend entier ou pas du tout.** Dès qu'une adresse propre à
    l'usage est définie, le modèle, la clé et le délai sont lus sur le même
    suffixe, et jamais complétés par les valeurs communes. Mélanger les deux
    enverrait la clé configurée pour un point de terminaison à un autre : ce
    n'est pas une commodité qu'on accorde à une variable d'environnement.
    """
    suffixe = f"_{usage.upper()}" if usage else ""
    if suffixe and not environnement.get(f"KOVEX_ANNOTATEUR_URL{suffixe}", "").strip():
        suffixe = ""

    def lire(nom: str) -> str:
        return environnement.get(f"KOVEX_ANNOTATEUR_{nom}{suffixe}", "").strip()

    delai = lire("DELAI_S")
    return Reglages(
        adresse=lire("URL").rstrip("/"),
        modele=lire("MODELE"),
        cle=lire("CLE"),
        delai_s=float(delai) if delai else DELAI_PAR_DEFAUT_S,
    )


# ------------------------------------------------------- ce qui est envoyé


#: Champs qu'aucune autorisation ne peut ouvrir. Ce ne sont pas des réglages : la
#: liste des porteurs d'un rôle est une donnée personnelle, et elle n'a aucune
#: utilité pour proposer un libellé.
JAMAIS_ENVOYE = ("users", "user_ids", "identities", "porteurs")


def exemples_de_nommage(roles_valides: Sequence[Mapping[str, Any]],
                        role: Mapping[str, Any],
                        maximum: int = EXEMPLES_MAX) -> List[Dict[str, str]]:
    """Les rôles déjà validés qui montrent la convention de la maison.

    Un catalogue de rôles vaut par sa cohérence. Montrer au modèle les noms
    que cette organisation a réellement retenus lui fait adopter sa
    convention, là où aucun exemple ne produirait un libellé plausible mais
    étranger au reste du catalogue.

    Les exemples sont choisis par **proximité applicative** — les rôles
    partageant des droits avec le candidat — et non par auteur. Renvoyer à
    chaque valideur ses propres habitudes renforcerait les divergences : le
    but est un catalogue lisible d'un bout à l'autre, pas trois styles.

    Ce classement est un point important : il s'appuie sur les droits, qui
    **ne quittent jamais la machine pour cet usage**. Seuls les noms retenus
    sont transmis, et seulement si la matrice l'autorise pour cet usage.
    """
    droits_du_candidat = set(role.get("rights") or ())
    retenus: List[Dict[str, str]] = []
    vus = set()

    def rang(valide: Mapping[str, Any]) -> tuple:
        communs = len(droits_du_candidat & set(valide.get("rights") or ()))
        # À proximité égale, le plus récemment validé : c'est la convention en
        # vigueur, pas celle qu'on a abandonnée. Le tri décroissant sur les
        # deux, et l'ordre d'entrée pour départager le reste — un classement
        # qui bougerait d'un appel à l'autre rendrait l'audit irrejouable.
        return (communs, valide.get("validated_at") or "")

    for valide in sorted(roles_valides, key=rang, reverse=True):
        nom = _nettoyer(valide.get("name"), LONGUEUR_NOM_MAX)
        if not nom or nom.casefold() in vus:
            continue
        vus.add(nom.casefold())
        retenus.append({
            "nom": nom,
            "description": _nettoyer(valide.get("description"),
                                     LONGUEUR_DESCRIPTION_MAX),
        })
        if len(retenus) == maximum:
            break
    return retenus


def faits_du_role(role: Mapping[str, Any],
                  explication: Optional[Mapping[str, Any]],
                  autorisation: Autorisation,
                  exemples: Sequence[Mapping[str, str]] = (),
                  applications: Sequence[str] = ()) -> Dict[str, Any]:
    """Ce que l'annotateur a le droit de voir de ce rôle.

    Construit **par ajout** et non par retrait : on part de rien et on ajoute
    ce que l'autorisation ouvre. Un filtre par exclusion laisserait passer
    tout champ nouveau que personne n'aurait pensé à interdire ; ici, un champ
    nouveau ne sort pas tant que quelqu'un ne l'a pas explicitement ajouté.

    Les comptes sortent toujours : ils ne désignent personne.
    """
    faits: Dict[str, Any] = {
        "nombre_de_droits": int(role.get("right_count")
                                or len(role.get("rights") or ())),
        "nombre_de_porteurs": int(role.get("user_count") or 0),
    }

    if autorisation.autorise(MATIERE_LIBELLES_DE_DROITS):
        droits = [str(droit) for droit in (role.get("rights") or ())]
        faits["droits"] = droits[:DROITS_ENVOYES_MAX]
        if len(droits) > DROITS_ENVOYES_MAX:
            faits["droits_non_transmis"] = len(droits) - DROITS_ENVOYES_MAX
        # Les applications relèvent de la même autorisation : sur un
        # référentiel réel, le libellé d'un droit porte déjà le nom de son
        # application. Les séparer donnerait un réglage de plus sans rien
        # protéger de plus. Elles sont pourtant la meilleure matière : un
        # modèle nomme mieux un rôle en sachant de quelles applications il
        # ouvre l'accès qu'en lisant des identifiants techniques.
        noms = sorted({str(nom).strip() for nom in applications
                       if str(nom).strip()})
        # Un champ vide se lirait comme « ce rôle n'ouvre aucune application »,
        # alors qu'il veut dire « le référentiel ne porte pas l'information ».
        if noms:
            faits["applications"] = noms

    if (autorisation.autorise(MATIERE_REGLE_METIER)
            and explication and explication.get("regle")):
        faits["regle"] = [
            {"attribut": str(terme.get("attribut", "")),
             "valeur": str(terme.get("valeur", ""))}
            for terme in explication["regle"]
        ]

    if autorisation.autorise(MATIERE_NOMS_VALIDES) and exemples:
        faits["exemples"] = [dict(exemple) for exemple in exemples]

    return faits


#: Consigne envoyée au modèle. Elle demande un objet JSON pour que la réponse
#: soit vérifiable : une phrase libre obligerait à deviner où s'arrête le nom.
CONSIGNE = (
    "Tu nommes des rôles d'habilitation. On te donne des faits sur un rôle : "
    "les libellés de ses droits, les applications concernées, une règle sur "
    "les attributs de ses porteurs, des exemples de rôles déjà nommés par "
    "cette organisation. Certains de ces éléments peuvent manquer.\n"
    "Règles :\n"
    "- Nomme le rôle d'après ce que les libellés et les applications "
    "désignent : le service, l'activité, le niveau d'accès. C'est là qu'est "
    "le sens.\n"
    "- N'emploie jamais le nombre de droits ni le nombre de porteurs dans le "
    "nom ni dans la description : ce sont des mesures, pas une identité, et "
    "elles sont déjà affichées ailleurs.\n"
    "- N'invente aucune finalité que les faits ne portent pas.\n"
    "- Si aucun élément ne porte de sens, rends un nom ouvertement technique "
    "plutôt qu'un intitulé qui aurait l'air d'un métier.\n"
    "- Suis la convention des exemples quand elle est nette, sans recopier un "
    "de ces noms.\n"
    "Réponds uniquement par un objet JSON avec deux clés : \"nom\" (un "
    "intitulé court, sans guillemets ni ponctuation finale) et "
    "\"description\" (une phrase)."
)


def composer_la_demande(faits: Mapping[str, Any], reglages: Reglages,
                        langue: str) -> Dict[str, Any]:
    """La charge utile, au format le plus répandu.

    `temperature` à zéro : deux demandes identiques doivent rendre la même
    proposition, sans quoi rejouer un audit donnerait un autre résultat.
    """
    return {
        "model": reglages.modele,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": CONSIGNE},
            {"role": "user", "content": json.dumps(
                {"langue": langue, "faits": dict(faits)}, ensure_ascii=False)},
        ],
    }


# --------------------------------------------------- ce qui revient, et l'appel


#: Caractères de commande et retours à la ligne : un nom qui en contient
#: casse un tableau, un export CSV et un rapport PDF.
_INDESIRABLES = re.compile(r"[\x00-\x1f\x7f]+")


def _nettoyer(texte: Any, longueur_max: int) -> str:
    """Ramène une réponse de modèle à un texte affichable et borné."""
    if not isinstance(texte, str):
        return ""
    propre = _INDESIRABLES.sub(" ", texte).strip()
    return propre[:longueur_max].strip()


#: Les noms sous lesquels un modèle rend le nom et la description d'un rôle.
#: Déclarés par l'usage, jamais devinés : c'est ici qu'on décide que `name`
#: vaut `nom`, et nulle part ailleurs.
CHAMPS_DU_NOM = ("nom", "name", "titre", "title", "libelle", "label")
CHAMPS_DE_LA_DESCRIPTION = ("description", "resume", "summary", "explication")

#: Le schéma imposé au moteur quand il sait l'imposer. Il dit la même chose que
#: la consigne — un objet, deux chaînes — dans le langage que comprend un
#: générateur contraint.
SCHEMA_DU_NOMMAGE: Dict[str, Any] = {
    "type": "object",
    "properties": {"nom": {"type": "string"},
                   "description": {"type": "string"}},
    "required": ["nom", "description"],
    "additionalProperties": False,
}


def lire_la_proposition(charge: Mapping[str, Any]) -> Dict[str, str]:
    """Extrait le nom et la description, ou refuse.

    Une réponse illisible est une absence de proposition, pas une proposition
    vide : afficher un champ vide laisserait croire que le modèle n'a rien
    trouvé, alors qu'il a répondu autre chose que ce qui était demandé.

    La lecture ne présume ni de l'enveloppe — un bloc encadré, une phrase avant
    l'objet — ni du nom exact des deux champs. Ce qu'elle exige reste entier :
    il faut un nom, et il est borné et nettoyé comme tout texte venu d'un
    modèle.
    """
    propose = protocole.extraire_le_json(
        protocole.contenu_de_la_reponse(charge))
    if not isinstance(propose, Mapping):
        raise ReponseInexploitable("réponse illisible")
    nom = _nettoyer(protocole.champ(propose, CHAMPS_DU_NOM), LONGUEUR_NOM_MAX)
    if not nom:
        raise ReponseInexploitable("réponse sans nom")
    return {
        "nom": nom,
        "description": _nettoyer(
            protocole.champ(propose, CHAMPS_DE_LA_DESCRIPTION),
            LONGUEUR_DESCRIPTION_MAX),
    }


class Annotateur:
    """Client d'un point de terminaison compatible OpenAI.

    L'échec est un cas normal : le modèle peut être arrêté, lent, ou absent.
    Rien du produit n'en dépend, et l'appelant traduit l'échec en message.
    """

    def __init__(self, reglages: Reglages,
                 autorisation: Autorisation) -> None:
        self.reglages = reglages
        self.autorisation = autorisation

    def proposer(self, role: Mapping[str, Any],
                 explication: Optional[Mapping[str, Any]],
                 langue: str,
                 roles_valides: Sequence[Mapping[str, Any]] = (),
                 applications: Sequence[str] = ()) -> Dict[str, Any]:
        if not self.reglages.actif:
            raise AnnotateurIndisponible("annotateur désactivé")
        # L'usage lui-même peut être fermé alors que l'infrastructure est en
        # place : c'est une décision de l'administrateur applicatif, et elle
        # se lit comme une absence de matière, pas comme une panne.
        if not self.autorisation.actif:
            raise RienANommer("usage fermé")

        exemples = (exemples_de_nommage(roles_valides, role)
                    if self.autorisation.autorise(MATIERE_NOMS_VALIDES) else ())
        faits = faits_du_role(role, explication, self.autorisation, exemples,
                              applications)

        # Deux contrôles, et non un seul : ils ne disent pas la même chose.
        #
        # La matrice dit ce qui **peut** sortir. Elle répond sans regarder les
        # données, et c'est ce qui permet à l'écran de paramétrage d'annoncer
        # ce qui manque avant que quiconque ait cliqué.
        if not self.autorisation.posable:
            raise RienANommer("aucune matière autorisée")
        # La composition dit ce qui **existe**. Une matière ouverte reste une
        # porte, pas une matière : un rôle sans règle métier, ou un catalogue
        # sans rôle validé, laisse la demande vide malgré l'autorisation. Deux
        # nombres ne nomment rien, et le modèle privé de tout invente une
        # finalité — c'est ce défaut-là qu'on a observé.
        if not any(cle in faits for cle in ("droits", "regle", "exemples")):
            raise RienANommer("aucune matière disponible")
        charge = composer_la_demande(faits, self.reglages, langue)
        # `demander` porte la reprise guidée : une réponse dont rien n'est
        # lisible repart une fois, avec sa propre sortie sous les yeux du
        # modèle. Ce qui reste inexploitable après cela est une absence de
        # proposition, et se dit comme telle.
        try:
            proposition = demander(charge, self.reglages, lire_la_proposition,
                                   SCHEMA_DU_NOMMAGE, self._envoyer)
        except ReponseInexploitable as refus:
            raise AnnotateurIndisponible(str(refus))

        # Ce qui a été envoyé est rendu à l'appelant pour que la piste d'audit
        # dise quelles catégories ont quitté le système — sans le contenu.
        proposition["categories_transmises"] = sorted(
            cle for cle in faits
            if cle in ("droits", "applications", "regle", "exemples"))
        proposition["modele"] = self.reglages.modele
        # L'usage devient une donnée de la proposition, et de là une donnée de
        # la piste d'audit : « pour quoi le modèle a-t-il été interrogé » est
        # une question qu'un lecteur de la piste doit pouvoir poser sans
        # ouvrir les données.
        proposition["usage"] = self.autorisation.usage.code
        return proposition

    def _envoyer(self, charge: Mapping[str, Any]) -> Dict[str, Any]:
        return envoyer(charge, self.reglages, SCHEMA_DU_NOMMAGE)


def entetes(reglages: Reglages) -> Dict[str, str]:
    """En-têtes de la demande. La clé ne sort pas de l'en-tête d'autorisation."""
    entetes = {"Content-Type": "application/json"}
    if reglages.cle:
        entetes["Authorization"] = f"Bearer {reglages.cle}"
    return entetes


def _poster(charge: Mapping[str, Any], reglages: Reglages) -> Dict[str, Any]:
    """Un aller-retour, sans négociation ni interprétation."""
    requete = urllib.request.Request(
        f"{reglages.adresse}/chat/completions",
        data=json.dumps(charge).encode("utf-8"),
        headers=entetes(reglages),
        method="POST",
    )
    with urllib.request.urlopen(requete, timeout=reglages.delai_s) as flux:
        brut = flux.read(REPONSE_MAX_OCTETS)
    return json.loads(brut.decode("utf-8"))


def _lister(reglages: Reglages) -> Dict[str, Any]:
    """Un aller-retour de lecture vers `GET /models`.

    Fonction distincte de `_poster`, et c'est délibéré : le transport de
    l'envoi est déjà remplacé par le pont de la page, et il ne parle que
    `POST /chat/completions`. Une fonction à part se remplace à part, sans
    toucher au chemin par lequel passent les vraies questions.
    """
    requete = urllib.request.Request(
        f"{reglages.adresse}/models", headers=entetes(reglages), method="GET")
    with urllib.request.urlopen(requete, timeout=reglages.delai_s) as flux:
        brut = flux.read(REPONSE_MAX_OCTETS)
    return json.loads(brut.decode("utf-8"))


def catalogue_des_modeles(reglages: Reglages) -> List[str]:
    """Les modèles que ce point de terminaison déclare servir.

    Lire la liste chez le fournisseur supprime une classe entière de fautes :
    un nom de modèle saisi à la main ne se trompe qu'une fois, mais il se
    trompe en silence — l'appel échoue plus tard, dans un écran qui parle
    d'autre chose.

    La forme attendue est celle, très répandue, de `GET /models` : un objet
    portant `data`, chaque entrée portant `id`. Un serveur qui rend autre chose
    ne fait pas échouer l'écran : il rend une liste vide, et l'utilisateur
    saisit le nom lui-même.
    """
    document = _lister(reglages)
    entrees = document.get("data") if isinstance(document, Mapping) else None
    if not isinstance(entrees, (list, tuple)):
        return []
    noms = []
    for entree in entrees:
        identifiant = ""
        if isinstance(entree, Mapping):
            identifiant = str(entree.get("id", "")).strip()
        elif isinstance(entree, str):
            identifiant = entree.strip()
        if identifiant and identifiant not in noms:
            noms.append(identifiant)
    return sorted(noms)


def _sans_temperature(demande: Mapping[str, Any], reglages: Reglages,
                      refus: urllib.error.HTTPError) -> Dict[str, Any]:
    """Rejoue la demande nue sans réglage de température, une seule fois.

    La reproductibilité s'y perd — deux demandes identiques pourront rendre
    deux propositions différentes — et c'est dit dans le journal plutôt que
    tu : c'est le prix d'un modèle qui n'accepte que sa propre température,
    et la proposition reste un brouillon qu'un humain relit.
    """
    allegee = {cle: valeur for cle, valeur in demande.items()
               if cle != "temperature"}
    try:
        reponse = _poster(allegee, reglages)
    except (urllib.error.URLError, OSError, ValueError):
        # L'autre cause du refus reste la vraie : c'est elle qu'on rapporte.
        logger.warning("Modèle injoignable (%s, modèle %s) : %s",
                       reglages.adresse, reglages.modele, refus)
        raise AnnotateurIndisponible(str(refus))
    protocole.retenir_la_temperature_imposee(reglages.adresse)
    logger.info("%s (modèle %s) impose sa propre température : les "
                "propositions de ce point de terminaison ne seront pas "
                "reproductibles à l'identique.",
                reglages.adresse, reglages.modele)
    return reponse


def envoyer(charge: Mapping[str, Any], reglages: Reglages,
            schema: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Pose la demande, en contraignant la réponse autant que le serveur l'accepte.

    Fonction et non méthode : tous les usages passent par le même protocole, et
    chacun n'a pas à réimplémenter l'appel — un deuxième client HTTP serait un
    deuxième endroit où la clé pourrait fuiter dans un journal.

    **La contrainte est négociée, jamais présumée.** Le produit s'installe chez
    le client avec le moteur que le client sert : OpenAI, vLLM, llama.cpp,
    Ollama, un proxy d'entreprise. Certains imposent un schéma JSON à la
    génération, d'autres seulement un objet JSON, d'autres rien. Écrire en dur
    lequel fait quoi serait faux le jour où le client change de version.

    Le produit propose donc le niveau le plus fort, et redescend d'un cran à
    chaque refus **du serveur** — une erreur HTTP de la famille 4xx, qui dit
    « je ne sais pas faire ça », et non une panne, qui dit « je ne réponds
    pas ». Ce que le point de terminaison a **refusé** est retenu pour la durée
    du processus : on ne repaie pas deux appels ratés à chaque demande. Ce sont
    bien les refus qu'on retient, et non les acceptations — qu'un serveur
    accepte un objet JSON ne prouve pas qu'il refuse un schéma, puisque la
    demande en cours n'en avait peut-être pas.

    L'échec, lui, reste un cas normal : le modèle peut être arrêté, lent, ou
    absent. Rien du produit n'en dépend.
    """
    dernier = None
    for niveau in protocole.niveaux_a_tenter(reglages.adresse, schema):
        demande = dict(charge)
        demande.update(protocole.contrainte(niveau, schema))
        if protocole.temperature_imposee(reglages.adresse):
            demande.pop("temperature", None)
        try:
            reponse = _poster(demande, reglages)
        except urllib.error.HTTPError as erreur:
            if (400 <= erreur.code < 500 and niveau == protocole.NIVEAU_NU
                    and "temperature" in demande):
                # Dernier cran, et seulement celui-là : le modèle impose peut-
                # être sa propre température. Si la demande passe sans elle,
                # c'est retenu ; sinon le refus avait une autre cause, et il
                # remonte tel quel.
                return _sans_temperature(demande, reglages, erreur)
            if 400 <= erreur.code < 500 and niveau != protocole.NIVEAU_NU:
                # Le serveur dit qu'il ne sait pas faire : on redescend.
                logger.info("Contrainte %s refusée par %s (HTTP %s) : "
                            "essai du niveau suivant.",
                            niveau, reglages.adresse, erreur.code)
                protocole.retenir_le_refus(reglages.adresse, niveau)
                dernier = erreur
                continue
            logger.warning("Modèle injoignable (%s, modèle %s) : %s",
                           reglages.adresse, reglages.modele, erreur)
            raise AnnotateurIndisponible(str(erreur))
        except (urllib.error.URLError, OSError, ValueError) as erreur:
            # L'adresse et le modèle sont journalisés, jamais la clé.
            logger.warning("Modèle injoignable (%s, modèle %s) : %s",
                           reglages.adresse, reglages.modele, erreur)
            raise AnnotateurIndisponible(str(erreur))
        return reponse
    # Inatteignable : le niveau nu termine toujours la liste des niveaux à
    # tenter, et il ne redescend pas. La garde reste pour que l'ajout d'un
    # niveau ne transforme pas un oubli en boucle silencieuse.
    raise AnnotateurIndisponible(str(dernier))  # pragma: no cover


def demander(charge: Mapping[str, Any], reglages: Reglages, lire,
             schema: Optional[Mapping[str, Any]] = None, envoi=None):
    """Demande, lit, et **reprend une fois** si rien n'était exploitable.

    `envoi` est l'appel lui-même, injecté : c'est l'appelant qui sait à quel
    point de terminaison et sous quelle contrainte la demande part. Quand il
    n'est pas fourni, `schema` sert à le construire ici.

    `lire` reçoit la réponse brute et rend ce que l'usage en tire, ou lève
    `ReponseInexploitable` s'il n'en tire rien. La distinction est la clef :
    une liste vide est une réponse — le modèle n'a rien trouvé — tandis qu'une
    réponse dont pas une entrée n'a pu être lue est un défaut de forme.

    La reprise montre au modèle **sa propre réponse** et lui rappelle la forme
    attendue. C'est ce qui rattrape un petit modèle qui a répondu en prose ou
    interverti deux champs : il se corrige souvent au second passage.

    Une seule reprise. Deux seraient une boucle sur un modèle qui ne sait pas
    répondre, payée en secondes par l'utilisateur qui attend.
    """
    envoi = envoi or (lambda demande: envoyer(demande, reglages, schema))
    reponse = envoi(charge)
    try:
        return lire(reponse)
    except ReponseInexploitable as inexploitable:
        # `except ... as` efface le nom en sortant du bloc : on le retient.
        refus = inexploitable
        logger.info("Réponse inexploitable (%s) : reprise guidée.", refus)

    reprise = _charge_de_reprise(charge, reponse, refus)
    return lire(envoi(reprise))


#: Ce que la reprise rappelle au modèle. Volontairement court : un petit modèle
#: perd le fil d'une consigne longue, et l'essentiel est qu'il voie sa propre
#: réponse à côté de ce qui était demandé.
CONSIGNE_DE_REPRISE = (
    "Ta réponse précédente n'a pas la forme demandée et n'a pas pu être "
    "utilisée. Relis la consigne du premier message et réponds de nouveau, "
    "uniquement par l'objet JSON demandé, sans texte autour."
)


def _charge_de_reprise(charge: Mapping[str, Any], reponse: Any,
                       refus: Exception) -> Dict[str, Any]:
    """La même demande, plus la réponse reçue et le rappel de la forme."""
    reprise = dict(charge)
    messages = list(charge.get("messages") or [])
    rendu = protocole.contenu_de_la_reponse(reponse)
    if not isinstance(rendu, str):
        rendu = json.dumps(rendu, ensure_ascii=False) if rendu is not None else ""
    messages.append({"role": "assistant",
                     "content": rendu[:LONGUEUR_REPRISE_MAX]})
    messages.append({"role": "user", "content": CONSIGNE_DE_REPRISE})
    reprise["messages"] = messages
    return reprise
