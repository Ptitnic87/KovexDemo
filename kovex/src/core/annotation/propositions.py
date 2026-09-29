# src/core/annotation/propositions.py
"""Deux réglages que le client seul peut remplir, et qu'il ne remplit pas.

Le produit porte deux listes que personne n'écrit :

- **les droits sensibles** — les fragments de nom qui signalent un droit à
  regarder de près. La liste appartient au client, qui seul connaît son
  référentiel ; elle reste vide chez la plupart, faute de savoir quoi y mettre.
  Un réglage vide est une fonctionnalité morte.
- **les attributs pertinents** — parmi quarante colonnes, lesquelles portent du
  métier. L'analyste les trouve par essais successifs, à plusieurs minutes la
  tentative.

Un modèle de langage est utile ici pour la même raison que pour le nommage :
la question porte sur des **mots**. Distinguer `matricule` de `service`, ou
reconnaître que `PAIE` désigne quelque chose de sensible, ne se calcule pas.

**Mais les mots seuls sortent du modèle ; les chiffres viennent du calcul.**
Un fragment proposé est vérifié sur le référentiel : s'il ne correspond à
aucun droit, il est écarté ; s'il correspond, le produit compte lui-même
combien de droits il signalerait. Sans ce contrôle, on obtiendrait une liste
crédible qui annonce des volumes inventés — le pire des cas pour ce produit.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from src.core.annotation.annotateur import (
    LONGUEUR_DESCRIPTION_MAX,
    AnnotateurIndisponible,
    Reglages,
    ReponseInexploitable,
    RienANommer,
    _nettoyer,
    composer_la_demande,
    demander,
)
from src.core.annotation import protocole
from src.core.data.coherence import replier
from src.core.annotation.assistance import (
    MATIERE_LIBELLES_DE_DROITS,
    MATIERE_NOMS_DE_COLONNES,
    Autorisation,
)

logger = logging.getLogger(__name__)

#: Libellés de droits joints à la demande. Un référentiel réel en compte des
#: dizaines de milliers : les envoyer tous ferait déborder ce que le modèle
#: accepte, et la panne arriverait chez le client qui a le plus de droits.
LIBELLES_ENVOYES_MAX = 200

#: Colonnes jointes à la demande. Un référentiel d'identités qui en porterait
#: davantage n'est plus un référentiel d'identités.
COLONNES_ENVOYEES_MAX = 100

#: Bornes d'un fragment retenu. Un fragment d'un caractère signalerait la
#: moitié du référentiel ; un fragment très long n'est plus un fragment.
FRAGMENT_LONGUEUR_MIN = 3
FRAGMENT_LONGUEUR_MAX = 40
FRAGMENTS_MAX = 30

#: Classes qu'une colonne peut recevoir. Chacune est aussi une clé de
#: traduction — `attributs.classe.<code>` : le serveur ne connaît pas la langue
#: de l'utilisateur, et ne rend donc jamais de phrase.
CLASSE_METIER = "metier"
CLASSE_IDENTIFIANT = "identifiant"
CLASSE_BRUIT = "bruit"
CLASSES = (CLASSE_METIER, CLASSE_IDENTIFIANT, CLASSE_BRUIT)

#: Ce qu'une réponse peut écrire pour désigner ces trois classes.
#:
#: La comparaison se faisait sur la chaîne exacte, et la consigne est en
#: français : un modèle qui répond `"métier"` — l'orthographe correcte du mot
#: qu'on lui a demandé d'employer — voyait sa réponse relue comme une classe
#: inconnue, donc ramenée à `bruit`. **Tout le classement devenait du bruit, et
#: l'écran annonçait qu'aucune colonne n'était porteuse de métier** : un défaut
#: silencieux qui ressemblait à un avis du modèle.
#:
#: La correspondance porte donc sur la forme repliée — casse, accents et
#: ponctuation — et accepte les quelques mots qu'un modèle emploie pour la même
#: idée. Un mot hors de cette table n'est plus ramené à `bruit` en silence : il
#: est compté et rendu à l'écran.
SYNONYMES_DE_CLASSE: Mapping[str, str] = {
    "metier": CLASSE_METIER,
    "business": CLASSE_METIER,
    "fonctionnel": CLASSE_METIER,
    "identifiant": CLASSE_IDENTIFIANT,
    "identifier": CLASSE_IDENTIFIANT,
    "identite": CLASSE_IDENTIFIANT,
    "id": CLASSE_IDENTIFIANT,
    "bruit": CLASSE_BRUIT,
    "noise": CLASSE_BRUIT,
    "autre": CLASSE_BRUIT,
    "other": CLASSE_BRUIT,
    "technique": CLASSE_BRUIT,
}

#: Les clés sous lesquelles un modèle enveloppe sa liste, et les noms qu'il
#: donne aux champs. Déclarés ici, jamais devinés : c'est l'usage qui décide
#: que `column` vaut `colonne`, et il le décide une fois.
CLES_DES_FRAGMENTS = ("fragments", "fragment", "mots", "keywords", "resultats")
CLES_DU_CLASSEMENT = ("colonnes", "columns", "attributs", "attributes",
                      "resultats", "results")
CHAMPS_DU_FRAGMENT = ("fragment", "mot", "keyword", "terme", "valeur")
CHAMPS_DE_LA_COLONNE = ("colonne", "column", "nom", "name", "attribut")
CHAMPS_DE_LA_CLASSE = ("classe", "class", "categorie", "category", "type")
CHAMPS_DU_MOTIF = ("motif", "raison", "reason", "justification", "why",
                   "explication")

#: Le schéma imposé au moteur quand il sait l'imposer. L'énumération des trois
#: classes y est déclarée : au niveau le plus fort, une classe hors liste
#: devient impossible à produire plutôt qu'à écarter.
SCHEMA_DES_FRAGMENTS: Dict[str, Any] = {
    "type": "object",
    "properties": {"fragments": {"type": "array", "items": {
        "type": "object",
        "properties": {"fragment": {"type": "string"},
                       "motif": {"type": "string"}},
        "required": ["fragment", "motif"],
        "additionalProperties": False}}},
    "required": ["fragments"],
    "additionalProperties": False,
}

SCHEMA_DU_CLASSEMENT: Dict[str, Any] = {
    "type": "object",
    "properties": {"colonnes": {"type": "array", "items": {
        "type": "object",
        "properties": {"colonne": {"type": "string"},
                       "classe": {"type": "string",
                                  "enum": list(CLASSES)},
                       "motif": {"type": "string"}},
        "required": ["colonne", "classe", "motif"],
        "additionalProperties": False}}},
    "required": ["colonnes"],
    "additionalProperties": False,
}

#: Caractères admis dans un fragment. Un fragment qui porterait une espace ou
#: une ponctuation ne correspondrait à rien dans un identifiant technique, et
#: une expression régulière glissée là serait exécutée par la recherche.
_FRAGMENT_ADMIS = re.compile(r"^[\w\-.]+$", re.UNICODE)


# ------------------------------------------------------ ce qui est échantillonné


def echantillon(valeurs: Sequence[str], maximum: int) -> List[str]:
    """Un échantillon **déterministe** et étalé sur l'ensemble trié.

    Les premiers éléments d'une liste triée se ressemblent : un plafond posé
    sur la tête du référentiel ne montrerait qu'une famille de préfixes, et le
    modèle ne proposerait que des fragments de cette famille. L'échantillon est
    donc prélevé à pas régulier sur l'ensemble trié — il couvre l'alphabet.

    Déterministe parce qu'un audit doit pouvoir être rejoué : deux demandes
    identiques partent avec les mêmes libellés.
    """
    distinctes = sorted({str(valeur).strip() for valeur in valeurs
                         if str(valeur).strip()})
    if len(distinctes) <= maximum:
        return distinctes
    pas = len(distinctes) / maximum
    return [distinctes[int(rang * pas)] for rang in range(maximum)]


# ------------------------------------------------------------ les droits sensibles


CONSIGNE_DROITS_SENSIBLES = (
    "On te donne un échantillon de libellés de droits d'un système "
    "d'habilitations. Tu proposes les fragments de nom qui signalent un droit "
    "à regarder de près : administration, suppression, accès à des données "
    "personnelles ou financières, privilèges élevés.\n"
    "Règles :\n"
    "- Un fragment est un morceau de nom présent tel quel dans les libellés "
    "donnés, sans espace ni ponctuation. N'invente aucun fragment que les "
    "libellés ne portent pas.\n"
    "- Ne propose pas de fragment si court qu'il signalerait la moitié du "
    "référentiel.\n"
    "- Suis la langue et la convention des libellés donnés : ne traduis pas.\n"
    "- S'il n'y a rien de sensible, rends une liste vide plutôt qu'un "
    "fragment approximatif.\n"
    "Réponds uniquement par un objet JSON avec une clé \"fragments\", un "
    "tableau d'objets ayant \"fragment\" (le morceau de nom) et \"motif\" "
    "(une phrase courte disant pourquoi)."
)


def fragments_retenus(charge: Mapping[str, Any]) -> List[Dict[str, str]]:
    """Lit la réponse, et n'en garde que ce qui a la forme d'un fragment.

    Ce qui est écarté ici l'est sans discussion : le modèle est du texte
    hostile, et un fragment est destiné à une recherche dans des noms de
    droits.
    """
    bruts = protocole.liste_sous(
        protocole.extraire_le_json(protocole.contenu_de_la_reponse(charge)),
        CLES_DES_FRAGMENTS)
    if bruts is None:
        raise ReponseInexploitable("réponse illisible")

    retenus: List[Dict[str, str]] = []
    vus = set()
    for brut in bruts:
        if isinstance(brut, str):
            # Une liste de chaînes dit la même chose qu'une liste d'objets sans
            # motif : c'est une forme, pas une réponse différente.
            brut = {"fragment": brut}
        if not isinstance(brut, Mapping):
            continue
        fragment = _nettoyer(protocole.champ(brut, CHAMPS_DU_FRAGMENT),
                             FRAGMENT_LONGUEUR_MAX)
        if not _FRAGMENT_ADMIS.match(fragment or "x x"):
            continue
        if len(fragment) < FRAGMENT_LONGUEUR_MIN:
            continue
        if fragment.casefold() in vus:
            continue
        vus.add(fragment.casefold())
        retenus.append({
            "fragment": fragment,
            "motif": _nettoyer(protocole.champ(brut, CHAMPS_DU_MOTIF),
                               LONGUEUR_DESCRIPTION_MAX),
        })
        if len(retenus) == FRAGMENTS_MAX:
            break
    return retenus


def compter_les_droits(fragments: Sequence[Mapping[str, str]],
                       libelles: Sequence[str]) -> List[Dict[str, Any]]:
    """Le contrôle qui rend la proposition utilisable.

    **Les mots viennent du modèle, les chiffres du calcul.** Chaque fragment
    est cherché dans le référentiel entier — et non dans l'échantillon
    transmis : un fragment qui ne correspond à rien est écarté plutôt
    qu'affiché, et le nombre montré à l'utilisateur est compté ici.

    Sans ce contrôle, on obtiendrait une liste crédible annonçant des volumes
    inventés, et l'utilisateur retiendrait des fragments qui ne signalent rien.
    """
    connus = [str(libelle) for libelle in libelles]
    comptes = []
    for propose in fragments:
        fragment = propose["fragment"]
        aiguille = fragment.casefold()
        droits = [libelle for libelle in connus if aiguille in libelle.casefold()]
        if not droits:
            # Un fragment que le référentiel ne porte pas ne signalerait rien.
            logger.info("Fragment écarté, absent du référentiel : %s", fragment)
            continue
        comptes.append({
            "fragment": fragment,
            "motif": propose["motif"],
            "droits": len(droits),
            # Quelques exemples, pour que la décision se prenne sur des cas et
            # non sur un nombre. Triés : deux lectures donnent la même liste.
            "exemples": sorted(droits)[:5],
        })
    return comptes


def proposer_les_droits_sensibles(
        reglages: Reglages, autorisation: Autorisation,
        libelles: Sequence[str], langue: str,
        envoyer) -> Dict[str, Any]:
    """Demande les fragments, puis les vérifie sur le référentiel entier."""
    if not reglages.actif:
        raise AnnotateurIndisponible("assistance désactivée")
    if not autorisation.posable:
        raise RienANommer("usage fermé ou matière non autorisée")
    # Deux contrôles, et le second n'est pas redondant : `posable` dit que la
    # question peut être posée, cette ligne dit que **cette matière-là** a le
    # droit de partir. Les deux coïncident tant que la matière est déclarée
    # nécessaire ; le jour où elle deviendrait facultative, seul ce contrôle
    # empêcherait l'envoi.
    if not autorisation.autorise(MATIERE_LIBELLES_DE_DROITS):
        raise RienANommer("libellés de droits non autorisés")

    transmis = echantillon(libelles, LIBELLES_ENVOYES_MAX)
    if not transmis:
        raise RienANommer("référentiel des droits vide")

    faits = {"libelles": transmis}
    if len(set(libelles)) > len(transmis):
        # Dit au modèle qu'il ne voit pas tout : sans cela il conclurait que le
        # référentiel est petit et proposerait des fragments trop spécifiques.
        faits["libelles_non_transmis"] = len(set(libelles)) - len(transmis)

    fragments = compter_les_droits(
        demander(composer_la_demande_de(CONSIGNE_DROITS_SENSIBLES, faits,
                                        reglages, langue),
                 reglages, fragments_retenus, SCHEMA_DES_FRAGMENTS, envoyer),
        libelles)
    return {
        "fragments": fragments,
        "modele": reglages.modele,
        "usage": autorisation.usage.code,
        "categories_transmises": [MATIERE_LIBELLES_DE_DROITS],
        "libelles_transmis": len(transmis),
    }


# ------------------------------------------------------ les attributs pertinents


#: La consigne du classement, avec un exemple complet.
#:
#: L'exemple n'est pas un ornement. Un modèle de sept milliards de paramètres
#: tenu par une description en prose rend du plausible : sur un poste réel,
#: `mistral:latest` a répondu `{"colonne": "metier", "classe": "jobtitle"}` —
#: les deux champs intervertis — et `{"colonne": "first_name", "classe":
#: "nom"}`, où la classe est une description au lieu d'un des trois mots
#: attendus. Le classement entier était perdu.
#:
#: Un exemple résolu montre la forme au lieu de la décrire, et il coûte
#: quelques dizaines de mots par demande. Les trois valeurs admises y sont
#: répétées deux fois, parce que c'est le point sur lequel les petits modèles
#: se trompent.
CONSIGNE_ATTRIBUTS = (
    "On te donne les noms des colonnes d'un référentiel d'identités. Tu dis, "
    "pour chacune, ce qu'elle est. La clé \"classe\" vaut exactement l'un de "
    "ces trois mots, et rien d'autre :\n"
    "- \"metier\" : elle décrit la place d'une personne dans l'organisation "
    "— service, fonction, site, type de contrat. C'est sur elle qu'un rôle "
    "métier peut se construire.\n"
    "- \"identifiant\" : elle désigne une personne en particulier — matricule, "
    "nom, courriel, identifiant de connexion.\n"
    "- \"bruit\" : ni l'un ni l'autre — horodatage, commentaire libre, "
    "colonne technique.\n"
    "Règles :\n"
    "- \"colonne\" reprend le nom donné, caractère pour caractère. Ne le "
    "traduis pas, ne le corrige pas, n'en invente aucun.\n"
    "- \"classe\" vaut \"metier\", \"identifiant\" ou \"bruit\". Jamais un "
    "nom de colonne, jamais une description.\n"
    "- Si un nom ne te dit rien, rends \"bruit\" plutôt que de deviner.\n"
    "- Ne demande pas les valeurs : tu n'en auras pas, et tu n'en as pas "
    "besoin.\n"
    "Exemple. Pour les colonnes [\"first_name\", \"jobtitle\", \"created_at\"], "
    "tu réponds exactement :\n"
    "{\"colonnes\": ["
    "{\"colonne\": \"first_name\", \"classe\": \"identifiant\", "
    "\"motif\": \"désigne une personne\"}, "
    "{\"colonne\": \"jobtitle\", \"classe\": \"metier\", "
    "\"motif\": \"fonction dans l'organisation\"}, "
    "{\"colonne\": \"created_at\", \"classe\": \"bruit\", "
    "\"motif\": \"horodatage technique\"}]}\n"
    "Réponds uniquement par un objet JSON de cette forme, sans texte autour."
)


def classement_retenu(
        charge: Mapping[str, Any],
        colonnes: Sequence[str]) -> Tuple[List[Dict[str, str]], Dict[str, int]]:
    """Lit la réponse, et n'en garde que des colonnes qui existent.

    Une colonne que le modèle aurait inventée s'afficherait comme un attribut
    proposé, et l'utilisateur chercherait en vain à la cocher.

    Rend aussi ce qui a été écarté, et pourquoi. Ce compte s'affiche : sans
    lui, une réponse entièrement illisible et une réponse qui ne trouve rien
    donnent le même écran.
    """
    lu = protocole.extraire_le_json(protocole.contenu_de_la_reponse(charge))
    bruts = protocole.liste_sous(lu, CLES_DU_CLASSEMENT)
    if bruts is None:
        # `{"jobtitle": "metier", "last_name": "identifiant"}` dit exactement ce
        # que dit la liste d'objets demandée, et c'est une forme que les
        # modèles rendent spontanément.
        bruts = protocole.paires_du_dictionnaire(lu, "colonne", "classe")
    if bruts is None:
        raise ReponseInexploitable("réponse illisible")

    attendues, repliees = _index_des_colonnes(colonnes)
    retenues: List[Dict[str, str]] = []
    ecartees: Dict[str, Any] = {"colonnes_inconnues": 0, "classes_inconnues": 0,
                                "champs_intervertis": 0, "exemples": []}
    vues = set()
    for brut in bruts:
        if not isinstance(brut, Mapping):
            continue
        nom, classe, interversion = _lire_une_entree(brut, attendues, repliees)
        if interversion:
            ecartees["champs_intervertis"] += 1
        if nom is None:
            ecartees["colonnes_inconnues"] += 1
            _noter(ecartees, protocole.champ(brut, CHAMPS_DE_LA_COLONNE))
            continue
        if nom in vues:
            continue
        if classe is None:
            # Plus ramenée à « bruit » en silence : une classe qu'on ne sait
            # pas lire est un défaut de lecture, pas un avis du modèle, et les
            # confondre a déjà fait passer un classement entier pour un refus.
            brut_classe = protocole.champ(brut, CHAMPS_DE_LA_CLASSE)
            logger.info("Classe non reconnue pour %s : %r", nom,
                        str(brut_classe or "")[:40])
            ecartees["classes_inconnues"] += 1
            _noter(ecartees, brut_classe)
            continue
        vues.add(nom)
        retenues.append({
            "colonne": nom,
            "classe": classe,
            "motif": _nettoyer(protocole.champ(brut, CHAMPS_DU_MOTIF),
                               LONGUEUR_DESCRIPTION_MAX),
        })
    if not retenues and (ecartees["colonnes_inconnues"]
                         + ecartees["classes_inconnues"]) and bruts:
        # Le modèle a répondu, et pas une entrée n'a pu être employée : c'est
        # un défaut de forme, et il vaut une reprise guidée. Une liste vide,
        # elle, est une réponse — il n'a rien trouvé.
        raise ReponseInexploitable("aucune entrée exploitable", ecartees)
    return retenues, ecartees


#: Mots du modèle rendus à l'écran quand la lecture n'a pas su les employer.
#: Assez pour reconnaître le défaut, pas assez pour recopier une réponse.
EXEMPLES_ECARTES_MAX = 5


def _noter(ecartees: Dict[str, Any], valeur: Any) -> None:
    """Garde quelques-uns des mots qu'on n'a pas su lire, pour les montrer.

    Sans eux, l'utilisateur lit « six réponses n'ont pas pu être rattachées »
    et doit ouvrir le journal du serveur pour savoir lesquelles. Avec eux, il
    voit que son modèle répond `nom` là où trois mots étaient admis, et il sait
    que c'est le modèle qu'il faut changer, pas son référentiel.
    """
    mot = _nettoyer(valeur, 40)
    if mot and len(ecartees["exemples"]) < EXEMPLES_ECARTES_MAX \
            and mot not in ecartees["exemples"]:
        ecartees["exemples"].append(mot)


def _lire_une_entree(brut: Mapping[str, Any], attendues: Mapping[str, str],
                     repliees: Mapping[str, Any]):
    """La colonne et la classe d'une entrée, les deux champs remis d'aplomb.

    Un modèle observé sur poste — `mistral:latest` servi par Ollama — rend
    `{"colonne": "metier", "classe": "jobtitle"}` : les deux champs
    intervertis. La lecture les remet en place, et sans rien deviner : elle ne
    le fait que si **les deux** valeurs sont reconnaissables à leur place
    inverse — l'une dans la liste fermée de trois classes, l'autre parmi les
    colonnes réellement transmises. Une entrée à moitié compréhensible reste
    écartée.

    Le redressement est compté et rendu à l'écran. Il rattrape une réponse,
    il ne rend pas bon un modèle qui ne suit pas la consigne : la seule
    correction durable est d'en servir un autre.
    """
    brut_colonne = protocole.champ(brut, CHAMPS_DE_LA_COLONNE)
    brut_classe = protocole.champ(brut, CHAMPS_DE_LA_CLASSE)
    nom = _colonne_reconnue(brut_colonne, attendues, repliees)
    classe = SYNONYMES_DE_CLASSE.get(replier(str(brut_classe or "")))
    if nom is not None and classe is not None:
        return nom, classe, False

    croise_nom = _colonne_reconnue(brut_classe, attendues, repliees,
                                   silencieux=True)
    croise_classe = SYNONYMES_DE_CLASSE.get(replier(str(brut_colonne or "")))
    if croise_nom is not None and croise_classe is not None:
        return croise_nom, croise_classe, True
    return nom, classe, False


def _index_des_colonnes(
        colonnes: Sequence[str]) -> Tuple[Dict[str, str], Dict[str, Any]]:
    """Les colonnes attendues, à l'exact et à la forme repliée.

    La forme repliée rattrape ce qu'un modèle fait couramment : rendre
    `Date_Entrée` pour `date_entree`. Quand deux colonnes distinctes se
    replient pareil, la forme repliée ne désigne plus rien — elle est mise à
    `None` et seule la correspondance exacte vaut. Deviner entre deux colonnes
    reviendrait à classer l'une pour l'autre.
    """
    attendues = {str(colonne): str(colonne) for colonne in colonnes}
    repliees: Dict[str, Any] = {}
    for colonne in attendues:
        cle = replier(colonne)
        repliees[cle] = None if cle in repliees else colonne
    return attendues, repliees


def _colonne_reconnue(brut: Any, attendues: Mapping[str, str],
                      repliees: Mapping[str, Any], silencieux: bool = False):
    """La colonne visée, à l'exact d'abord, à la forme repliée ensuite."""
    propose = str(brut if brut is not None else "").strip()
    if propose in attendues:
        return attendues[propose]
    reconnue = repliees.get(replier(propose)) if propose else None
    if reconnue is None and propose and not silencieux:
        logger.info("Colonne proposée inconnue du référentiel : %s", propose[:80])
    return reconnue


def proposer_les_attributs(reglages: Reglages, autorisation: Autorisation,
                           colonnes: Sequence[str], langue: str,
                           envoyer) -> Dict[str, Any]:
    """Demande une classe par colonne. Aucune valeur ne sort."""
    if not reglages.actif:
        raise AnnotateurIndisponible("assistance désactivée")
    if not autorisation.posable:
        raise RienANommer("usage fermé ou matière non autorisée")
    # Même raison que pour les droits sensibles : c'est l'autorisation de la
    # matière qui commande l'envoi, pas la possibilité de poser la question.
    if not autorisation.autorise(MATIERE_NOMS_DE_COLONNES):
        raise RienANommer("noms de colonnes non autorisés")

    transmises = [str(colonne) for colonne in colonnes][:COLONNES_ENVOYEES_MAX]
    if not transmises:
        raise RienANommer("aucune colonne à juger")

    try:
        colonnes_lues, ecartees = demander(
            composer_la_demande_de(CONSIGNE_ATTRIBUTS,
                                   {"colonnes": transmises}, reglages, langue),
            reglages, lambda reponse: classement_retenu(reponse, transmises),
            SCHEMA_DU_CLASSEMENT, envoyer)
    except ReponseInexploitable as refus:
        # Le modèle a répondu deux fois sans forme utilisable. Ce n'est pas une
        # panne — l'écran doit pouvoir dire ce qu'il a employé à la place des
        # mots attendus, faute de quoi l'utilisateur cherche le défaut du côté
        # de son référentiel.
        colonnes_lues, ecartees = [], dict(refus.details)
    return {
        "colonnes": colonnes_lues,
        # Ce que la lecture n'a pas su relier au référentiel. Rendu à l'écran :
        # « le modèle a répondu, mais rien n'a pu être rattaché à vos colonnes »
        # et « le modèle n'a jugé aucune colonne porteuse de métier » ne sont
        # pas la même chose, et les confondre envoie chercher au mauvais
        # endroit.
        "ecartees": ecartees,
        "reponses_lues": len(colonnes_lues) + ecartees["colonnes_inconnues"]
                         + ecartees["classes_inconnues"],
        "modele": reglages.modele,
        "usage": autorisation.usage.code,
        "categories_transmises": [MATIERE_NOMS_DE_COLONNES],
    }


# ------------------------------------------------------------------- la demande


def composer_la_demande_de(consigne: str, faits: Mapping[str, Any],
                           reglages: Reglages, langue: str) -> Dict[str, Any]:
    """La charge utile, avec la consigne de l'usage.

    `composer_la_demande` de l'annotateur porte la consigne du nommage ; elle
    est reprise ici pour la forme du message et le `temperature` à zéro, qui
    garantit qu'une demande rejouée rend la même proposition.
    """
    charge = composer_la_demande(faits, reglages, langue)
    charge["messages"][0]["content"] = consigne
    return charge


# ------------------------------------------------- les comptes à privilèges


#: La consigne des conventions de nommage de comptes à privilèges.
#:
#: Elle ne contient **aucun fait** : ni identifiant, ni colonne, ni échantillon.
#: C'est la seule demande du produit dans ce cas, et c'est voulu — la question
#: porte sur ce que fait le métier, pas sur ce que contient ce référentiel-ci.
#:
#: Le modèle est donc prié de répondre large : une convention absente d'un
#: référentiel ne coûte rien, puisqu'elle sera écartée au dénombrement. Une
#: convention manquante, en revanche, laisse un compte d'administration
#: invisible — l'asymétrie va toute entière dans le même sens, et la consigne
#: le dit plutôt que de laisser le modèle arbitrer seul.
CONSIGNE_COMPTES_A_PRIVILEGES = (
    "Tu connais les systèmes de gestion des identités et des habilitations. "
    "Dans ces systèmes, une personne porte souvent plusieurs comptes : un "
    "compte nominatif ordinaire, et un ou plusieurs comptes à privilèges "
    "(administration, service, compte technique, compte de secours).\n"
    "Question : quels fragments d'identifiant signalent usuellement un compte "
    "à privilèges ?\n"
    "Règles :\n"
    "- Un fragment est un morceau d'identifiant, sans espace ni ponctuation — "
    "un préfixe, un suffixe ou un mot entier.\n"
    "- On ne te donne aucune donnée : réponds d'après les conventions "
    "courantes du métier, pas d'après un référentiel particulier.\n"
    "- Propose large : les fragments absents du référentiel seront écartés "
    "automatiquement, tandis qu'un fragment oublié laisse un compte à "
    "privilèges non signalé.\n"
    "- Couvre plusieurs langues et plusieurs conventions d'écriture.\n"
    "Réponds uniquement par un objet JSON avec une clé \"fragments\", un "
    "tableau d'objets ayant \"fragment\" (le morceau d'identifiant) et "
    "\"motif\" (une phrase courte disant ce qu'il désigne)."
)


def compter_les_comptes(fragments: Sequence[Mapping[str, str]],
                        valeurs: Sequence[str], place: str
                        ) -> List[Dict[str, Any]]:
    """Le contrôle qui transforme du savoir général en liste locale.

    Le modèle n'a rien vu de ce référentiel : il rend des conventions, dont la
    plupart n'y figurent pas. Les garder toutes donnerait une liste de trente
    fragments dont trois servent, et l'utilisateur enregistrerait les trente —
    c'est-à-dire une règle qu'il n'a pas lue.

    Chaque fragment est donc éprouvé **ici**, à la place déclarée, sur les
    valeurs réellement chargées. Celui qui ne marque personne est écarté ; les
    autres sortent avec le nombre de comptes qu'ils marqueraient et quelques
    exemples, pour que la décision se prenne sur des cas et pas sur un nombre.
    """
    from src.core.knowledge.privileges import porte_le_fragment

    connues = [str(valeur) for valeur in valeurs]
    comptes: List[Dict[str, Any]] = []
    for propose in fragments:
        fragment = propose["fragment"].strip().upper()
        marques = [valeur for valeur in connues
                   if porte_le_fragment(valeur, fragment, place)]
        if not marques:
            # Une convention que ce référentiel n'emploie pas. L'écarter n'est
            # pas la juger fausse : elle ne marquerait simplement personne ici.
            logger.info("Fragment écarté, aucun compte marqué : %s", fragment)
            continue
        comptes.append({
            "fragment": fragment,
            "motif": propose["motif"],
            "comptes": len(marques),
            "exemples": sorted(marques)[:5],
        })
    return comptes


def proposer_les_comptes_a_privileges(
        reglages: Reglages, autorisation: Autorisation,
        identifiants: Sequence[str], place: str, langue: str,
        envoyer) -> Dict[str, Any]:
    """Demande les conventions usuelles, puis les éprouve sur le référentiel.

    `identifiants` ne part pas : il sert au dénombrement, ici, après la
    réponse. C'est la différence de fond avec les autres propositions du
    produit — celles-ci arbitrent ce qui a le droit de sortir, celle-ci n'a
    rien à faire sortir.
    """
    if not reglages.actif:
        raise AnnotateurIndisponible("assistance désactivée")
    if not autorisation.posable:
        raise RienANommer("usage fermé")
    if not identifiants:
        raise RienANommer("référentiel des identités vide")

    fragments = compter_les_comptes(
        demander(composer_la_demande_de(CONSIGNE_COMPTES_A_PRIVILEGES, {},
                                        reglages, langue),
                 reglages, fragments_retenus, SCHEMA_DES_FRAGMENTS, envoyer),
        identifiants, place)
    return {
        "fragments": fragments,
        "modele": reglages.modele,
        "usage": autorisation.usage.code,
        # Vide, et rendu tel quel : l'écran affiche ce qui est parti, et il
        # doit pouvoir afficher « rien ».
        "categories_transmises": [],
        "comptes_examines": len(set(identifiants)),
    }
