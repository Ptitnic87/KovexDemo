# Fichier : src/core/knowledge/privileges.py
"""Reconnaître un compte à privilèges dans un référentiel qu'on ne connaît pas.

Une personne porte souvent deux comptes : son compte nominatif, et un compte
d'administration. Pour un auditeur, ce n'est pas un détail de nommage — c'est
la différence entre « Franck consulte » et « Franck peut tout faire ». Le
produit rendait les deux comptes côte à côte sans jamais dire lequel était
lequel, et c'est l'utilisateur qui lisait `ADM` dans l'identifiant.

**La règle n'est pas dans ce fichier, et elle n'y sera jamais.** `ADM` signale
un compte d'administration chez un client et l'abréviation d'« administratif »
chez un autre ; `_A` est une convention chez un troisième et un numéro d'ordre
chez un quatrième. Écrire la convention dans le code, c'est se tromper chez la
moitié des clients — et se tromper silencieusement, ce qui est pire : un compte
à privilèges non signalé passe la revue.

Ce module porte donc la **mécanique**, et le client porte la **déclaration** :
quels fragments, dans quelle colonne, à quelle place. Rien n'est marqué tant
que rien n'est déclaré, et un marquage qui ne marque personne est dit tel quel
plutôt que rendu comme un résultat.

Le repérage lui-même reste local : il ne lit que les valeurs déjà chargées, ne
sort d'aucune machine, et se recalcule à chaque chargement — un compte renommé
cesse d'être marqué sans qu'on ait à toucher à quoi que ce soit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Tuple

# ------------------------------------------------------------------ la place

#: Le fragment est un **jeton** de l'identifiant : il occupe un morceau entier,
#: entre deux séparateurs ou à un bout. `ADM` marque `ADM_FRANCK` et
#: `franck.adm`, et ne marque pas `ADMINISTRATIF`.
PLACE_JETON = "jeton"
#: Le fragment **commence** la valeur. `ADM` marque `ADMFRANCK`.
PLACE_DEBUT = "debut"
#: Le fragment **termine** la valeur. `ADM` marque `FRANCKADM`.
PLACE_FIN = "fin"
#: Le fragment est **quelque part** dans la valeur. Le plus large, et le plus
#: bruyant : c'est celui qui marque `ADMINISTRATIF`. Offert parce qu'un
#: référentiel sans séparateur ni position stable n'a rien d'autre.
PLACE_PARTOUT = "partout"

#: Les places qu'une déclaration peut prendre. Chacune est aussi une clé de
#: traduction — `privileges.place.<code>` : le serveur ne rend pas de phrase.
PLACES: Tuple[str, ...] = (PLACE_JETON, PLACE_DEBUT, PLACE_FIN, PLACE_PARTOUT)

#: Ce qui sépare deux jetons dans un identifiant de compte. Tout ce qui n'est
#: ni lettre ni chiffre : les référentiels usent du point, du tiret, du
#: souligné, de l'espace, et parfois des quatre dans le même fichier.
SEPARATEUR = re.compile(r"[^0-9A-Za-z]+")

#: Bornes d'un fragment déclaré. Un fragment d'un caractère marquerait une
#: identité sur deux ; un fragment très long n'est plus un fragment de nommage.
#: Les mêmes bornes que les droits sensibles, pour la même raison.
FRAGMENT_LONGUEUR_MIN = 2
FRAGMENT_LONGUEUR_MAX = 40
FRAGMENTS_MAX = 30

#: Valeurs distinctes conservées dans un échantillon rendu à l'écran. Le
#: dénombrement porte sur tout le référentiel ; l'échantillon sert à répondre
#: à « montre-moi », et vingt-cinq lignes y suffisent.
ECHANTILLON_MAX = 25


class DeclarationInvalide(ValueError):
    """Une déclaration que le produit ne sait pas appliquer.

    Elle porte le champ fautif, sa valeur et les valeurs attendues — jamais une
    phrase : le serveur ne connaît pas la langue de l'utilisateur.
    """

    def __init__(self, champ: str, valeur: Any,
                 attendues: Sequence[str] = ()) -> None:
        super().__init__(f"{champ}={valeur!r}")
        self.champ = champ
        self.valeur = valeur
        self.attendues: Tuple[str, ...] = tuple(attendues)

    def document(self) -> Dict[str, Any]:
        return {"field": self.champ, "value": str(self.valeur),
                "expected": list(self.attendues)}


# ------------------------------------------------------------- la déclaration


@dataclass(frozen=True)
class Marqueur:
    """Ce que le client a déclaré : où chercher, quoi chercher, à quelle place.

    Gelé : il se construit au chargement et se lit partout ensuite. Un marqueur
    qu'un écran pourrait modifier au passage ferait dire deux choses différentes
    du même compte à deux endroits du produit, et c'est exactement le défaut que
    la règle « un chiffre, une définition » existe pour empêcher.
    """

    #: Les fragments déclarés, repliés une fois pour toutes.
    fragments: Tuple[str, ...] = ()
    #: La colonne d'identités où les chercher. Vide : l'identifiant du compte,
    #: qui est la seule colonne que le produit connaisse par construction.
    colonne: str = ""
    #: Où le fragment doit se trouver dans la valeur.
    place: str = PLACE_JETON

    @property
    def declare(self) -> bool:
        """Y a-t-il quelque chose à chercher ?

        Un marqueur vide n'est pas une erreur : c'est l'état de départ de tout
        workspace, et le produit doit s'y comporter comme si la fonction
        n'existait pas — aucune colonne, aucun badge, aucune phrase.
        """
        return bool(self.fragments)


def _replier(valeur: Any) -> str:
    """La forme sur laquelle la comparaison se fait : sans casse, sans bords."""
    return str(valeur).strip().upper()


def _fragments_lus(brut: Any) -> Tuple[str, ...]:
    """Les fragments retenus d'une déclaration, dans l'ordre donné.

    Les rebuts sont **écartés sans faire échouer le chargement** : un fragment
    vide laissé par une virgule en trop ne doit pas empêcher un workspace de
    s'ouvrir. Ce qui ferait échouer, en revanche, c'est une déclaration qui
    n'est pas une liste — là, le client a écrit autre chose que ce qu'il croit.
    """
    if brut is None:
        return ()
    if isinstance(brut, str) or not isinstance(brut, Iterable):
        raise DeclarationInvalide("privileged_account_keywords", brut,
                                  ("array",))
    retenus: List[str] = []
    for element in brut:
        fragment = _replier(element)
        if not FRAGMENT_LONGUEUR_MIN <= len(fragment) <= FRAGMENT_LONGUEUR_MAX:
            continue
        if fragment not in retenus:
            retenus.append(fragment)
        if len(retenus) >= FRAGMENTS_MAX:
            break
    return tuple(retenus)


def depuis_la_configuration(config: Mapping[str, Any]) -> Marqueur:
    """Lit le marqueur du document de workspace.

    Une place inconnue **arrête** la lecture au lieu d'être remplacée par une
    place de repli : `debbut` mal orthographié qui se lirait silencieusement
    « partout » marquerait dix fois plus de comptes que ce que le client a
    demandé, et il ne le saurait qu'en comptant.
    """
    place = str(config.get("privileged_account_place") or PLACE_JETON)
    if place not in PLACES:
        raise DeclarationInvalide("privileged_account_place", place, PLACES)
    return Marqueur(
        fragments=_fragments_lus(config.get("privileged_account_keywords")),
        colonne=str(config.get("privileged_account_column") or ""),
        place=place,
    )


# --------------------------------------------------------------- le repérage


def _jetons(valeur: str) -> FrozenSet[str]:
    return frozenset(jeton for jeton in SEPARATEUR.split(valeur) if jeton)


def porte_le_fragment(valeur: Any, fragment: str, place: str) -> bool:
    """Cette valeur porte-t-elle ce fragment, à cette place ?

    Sortie de la boucle pour être éprouvée seule : c'est la seule ligne du lot
    dont une erreur serait invisible — un compte de plus ou de moins marqué ne
    fait pas planter, il fait mentir.
    """
    repliee = _replier(valeur)
    if not repliee or not fragment:
        return False
    if place == PLACE_JETON:
        return fragment in _jetons(repliee)
    if place == PLACE_DEBUT:
        return repliee.startswith(fragment)
    if place == PLACE_FIN:
        return repliee.endswith(fragment)
    return fragment in repliee


def fragments_portes(valeur: Any, marqueur: Marqueur) -> Tuple[str, ...]:
    """Les fragments que porte cette valeur.

    Rendus **tous**, pas seulement le premier : l'écran des paramètres montre
    ce que chaque fragment marque, et un compte marqué par deux fragments doit
    compter dans les deux — sans quoi l'ordre de la liste déclarée changerait
    les chiffres affichés.
    """
    if not marqueur.declare:
        return ()
    return tuple(fragment for fragment in marqueur.fragments
                 if porte_le_fragment(valeur, fragment, marqueur.place))


def est_a_privileges(valeur: Any, marqueur: Marqueur) -> bool:
    """Cette valeur désigne-t-elle un compte à privilèges ?"""
    return bool(fragments_portes(valeur, marqueur))


def _colonne_lue(identites, marqueur: Marqueur,
                 colonne_identite: str) -> Optional[str]:
    """La colonne effectivement lue, ou `None` si elle n'est pas là.

    Une colonne déclarée puis absente du fichier chargé est un cas réel — le
    client a renommé son export. Le produit ne marque alors personne et le dit,
    plutôt que de se rabattre sur l'identifiant : marquer d'après une autre
    colonne que celle déclarée donnerait un résultat crédible et faux.
    """
    if identites is None or getattr(identites, "empty", True):
        return None
    demandee = marqueur.colonne or colonne_identite
    return demandee if demandee in identites.columns else None


def comptes_a_privileges(identites, marqueur: Marqueur,
                         colonne_identite: str) -> FrozenSet[str]:
    """Les identifiants des comptes marqués, sur les identités chargées."""
    if not marqueur.declare:
        return frozenset()
    colonne = _colonne_lue(identites, marqueur, colonne_identite)
    if colonne is None or colonne_identite not in identites.columns:
        return frozenset()
    marques = identites[colonne].map(
        lambda valeur: est_a_privileges(valeur, marqueur))
    return frozenset(
        str(identifiant)
        for identifiant in identites.loc[marques, colonne_identite])


def marques_parmi_les_comptes(identites, marqueur: Marqueur,
                              colonne_identite: str,
                              identifiants: Iterable[Any]) -> FrozenSet[str]:
    """Lesquels de ces comptes la déclaration marque, dans le référentiel.

    Passer par le référentiel plutôt que par les identifiants eux-mêmes n'est
    pas un détour : la colonne où chercher est **déclarée**, et ce peut être
    une autre colonne que l'identifiant. Marquer sur l'identifiant tel qu'un
    appelant l'a écrit donnerait un résultat différent de celui que l'écran des
    paramètres a dénombré — deux chiffres pour la même question, ce que le
    produit refuse partout ailleurs.

    C'est la porte d'entrée des écrans qui tiennent une **liste d'identités**
    sans tenir leurs lignes : les conflits de séparation, le détail d'une
    population, l'agent. Ceux qui tiennent déjà les lignes passent par
    `marques_parmi`, qui ne relit rien.
    """
    demandes = {str(identifiant) for identifiant in identifiants}
    if not marqueur.declare or not demandes:
        return frozenset()
    if identites is None or getattr(identites, "empty", True):
        return frozenset()
    if colonne_identite not in identites.columns:
        return frozenset()
    restreintes = identites[
        identites[colonne_identite].astype(str).isin(demandes)]
    return comptes_a_privileges(restreintes, marqueur, colonne_identite)


def marques_parmi(lignes: Iterable[Mapping[str, Any]], marqueur: Marqueur,
                  colonne_identite: str,
                  colonnes: Iterable[str]) -> List[str]:
    """Ceux de ces enregistrements qui portent la marque.

    C'est la porte d'entrée des **tableaux**. Elle prend des lignes déjà
    choisies — une page, pas un référentiel — plutôt que le fichier entier :
    marquer une page de cinquante lignes en relisant trois cent mille identités
    coûterait le prix d'un mining pour décorer un tableau.

    Elle ne se rabat jamais sur l'identifiant quand la colonne déclarée manque.
    Marquer d'après une autre colonne que celle déclarée donnerait un résultat
    crédible et faux — et un résultat faux sur cette question-là passe la revue.

    Les colonnes disponibles sont passées à part : une page vide n'en porte
    aucune, et lire les clés de la première ligne ferait dépendre le marquage
    de ce que la page contient.
    """
    if not marqueur.declare:
        return []
    disponibles = set(colonnes)
    demandee = marqueur.colonne or colonne_identite
    if demandee not in disponibles or colonne_identite not in disponibles:
        return []
    return [str(ligne.get(colonne_identite, ""))
            for ligne in lignes
            if est_a_privileges(ligne.get(demandee), marqueur)]


def denombrer(identites, marqueur: Marqueur, colonne_identite: str
              ) -> Dict[str, Any]:
    """Ce que la déclaration marquerait, fragment par fragment.

    C'est la même règle que les droits sensibles : **les mots viennent du
    client ou du modèle, les chiffres viennent du calcul**. Un fragment `ADM`
    qui marque mille deux cents identités sur trois mille se dénonce tout seul
    à l'écran — c'est `ADMINISTRATIF` —, et aucune phrase d'avertissement ne
    ferait ce travail aussi bien qu'un nombre.

    `colonne_absente` distingue les deux façons de ne rien marquer : la
    déclaration ne correspond à rien, ou la colonne déclarée n'existe pas. Les
    confondre laisserait le client refaire sa liste alors que c'est son export
    qui a changé.
    """
    resume: Dict[str, Any] = {
        "declare": marqueur.declare,
        "colonne": marqueur.colonne or colonne_identite,
        "place": marqueur.place,
        "colonne_absente": False,
        "population": 0,
        "marques": 0,
        "fragments": [],
        "echantillon": [],
    }
    if identites is None or getattr(identites, "empty", True):
        return resume
    resume["population"] = int(len(identites))
    if not marqueur.declare:
        return resume
    colonne = _colonne_lue(identites, marqueur, colonne_identite)
    if colonne is None:
        resume["colonne_absente"] = True
        return resume

    valeurs = identites[colonne]
    comptes: Dict[str, int] = {fragment: 0 for fragment in marqueur.fragments}
    marques = 0
    echantillon: List[str] = []
    for valeur in valeurs:
        portes = fragments_portes(valeur, marqueur)
        if not portes:
            continue
        marques += 1
        for fragment in portes:
            comptes[fragment] += 1
        if len(echantillon) < ECHANTILLON_MAX:
            echantillon.append(str(valeur))
    resume["marques"] = marques
    resume["fragments"] = [{"fragment": fragment, "marques": comptes[fragment]}
                           for fragment in marqueur.fragments]
    resume["echantillon"] = echantillon
    return resume
