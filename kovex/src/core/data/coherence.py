# src/core/data/coherence.py
"""Rapprocher les valeurs d'une colonne qui désignent la même chose.

Le mining métier regroupe les identités par valeurs d'attributs **identiques**,
au sens de la chaîne de caractères. `Infirmier`, `infirmière`, `INF`, `Inf.` et
`Infirmier ` font cinq populations.

Sur un effectif minimal à quinze, soixante infirmiers écrits de cinq façons
donnent cinq groupes de douze. Aucun n'atteint le seuil, le rôle n'est pas
trouvé — et **rien à l'écran ne dit qu'il a été manqué**. C'est le pire mode de
défaillance d'un outil de role mining : un silence qui ressemble à un résultat.

Ce module ne met aucune intelligence artificielle dans le calcul. Il ne compare
les valeurs qu'**entre elles** : le produit ne connaît la nomenclature d'aucun
métier, et n'en connaîtra aucune. Il ne présume non plus d'aucun nom de colonne.

Il produit des **grappes** : un ensemble de valeurs candidates au regroupement,
une forme proposée, les effectifs, et les signaux qui ont motivé le
rapprochement. Un rapprochement sans signal affichable n'est pas proposé —
l'utilisateur doit pouvoir répondre à « pourquoi celles-là ensemble ».

Ce qu'il produit n'est jamais appliqué : la grappe acceptée devient une entrée
d'une table de recodage, et c'est cette table, déterministe, que le calcul
relit ensuite.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Tuple

# ------------------------------------------------------------------ signaux

#: Même forme une fois la casse, les accents et la ponctuation repliés.
SIGNAL_FORME = "forme"
#: Distance d'édition bornée : une faute de frappe.
SIGNAL_FRAPPE = "frappe"
#: Même racine une fois le pluriel retiré.
SIGNAL_PLURIEL = "pluriel"
#: L'une est l'abréviation de l'autre — préfixe court, ou initiales.
SIGNAL_ABREVIATION = "abreviation"
#: L'une est l'autre coupée : un libellé tronqué à l'export.
SIGNAL_TRONCATURE = "troncature"
#: Une valeur rare textuellement proche d'une valeur fréquente.
#:
#: Ce signal ne rapproche rien à lui seul — il **qualifie** un rapprochement
#: déjà motivé. Trois `Infimier` contre huit cent douze `Infirmier` ne prouvent
#: rien par eux-mêmes ; adossés à une distance d'édition de un, ils emportent la
#: décision. C'est l'écart qu'on montre à l'utilisateur, pas la distance.
SIGNAL_EFFECTIF = "effectif"

SIGNAUX: Tuple[str, ...] = (SIGNAL_FORME, SIGNAL_FRAPPE, SIGNAL_PLURIEL,
                            SIGNAL_ABREVIATION, SIGNAL_TRONCATURE,
                            SIGNAL_EFFECTIF)

#: Le suffixe commun n'est **pas** un signal, et c'est délibéré.
#:
#: « Secrétaire médicale » et « Assistante médicale » partagent un long suffixe
#: et ne désignent pas la même chose. Un recodage ne doit jamais fusionner deux
#: populations qui portent des droits différents ; entre manquer un
#: rapprochement et en inventer un, ce module manque.
SUFFIXE_COMMUN_EXCLU = True


@dataclass(frozen=True)
class Reglages:
    """Les seuils du repérage, tous réglables par le workspace.

    Aucun n'est écrit en dur ailleurs que dans les valeurs par défaut du
    gestionnaire de workspace : ce sont des seuils de bruit, et un référentiel
    de trois cents identités ne se disperse pas comme un de trois cent mille.
    """

    #: Distance d'édition au-delà de laquelle deux valeurs ne sont plus une
    #: faute de frappe mais deux mots.
    distance_edition_max: int = 2
    #: Longueur en deçà de laquelle une racine commune ne prouve rien : « Com »
    #: est le début de « Comptable » comme de « Commercial ».
    longueur_racine_min: int = 4
    #: Rapport d'effectif au-delà duquel une valeur est dite rare face à une
    #: autre. Sert à qualifier, jamais à rapprocher.
    ecart_effectif_significatif: float = 20.0
    #: Nombre de valeurs distinctes analysées, les plus fréquentes d'abord.
    #:
    #: Ce n'est pas un choix métier : le repérage compare les valeurs deux à
    #: deux, et une colonne à cinquante mille valeurs distinctes coûterait des
    #: minutes pour un résultat que personne ne relirait. Le dépassement est
    #: **annoncé**, jamais silencieux.
    valeurs_analysees_max: int = 2000
    #: Part de valeurs numériques ou datées au-delà de laquelle la colonne
    #: n'est pas analysée : la proximité textuelle y produit du bruit —
    #: `2024-01-01` et `2024-01-02` sont proches et n'ont rien à voir.
    part_typee_max: float = 0.5
    #: Nombre de valeurs distinctes soumises à un modèle, les plus fréquentes
    #: d'abord.
    #:
    #: Celui-ci n'est pas un seuil de bruit : c'est **combien de valeurs
    #: quittent le système d'information** à chaque demande. Il est donc plus
    #: bas que le plafond d'analyse locale, et il se règle — un client qui
    #: n'accepte d'en faire sortir que cinquante doit pouvoir le dire.
    valeurs_soumises_max: int = 300


# ------------------------------------------------------------- repliements


_PONCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_ESPACES = re.compile(r"\s+", re.UNICODE)
#: Une valeur qui ressemble à un nombre, une date, une durée, un montant.
_TYPEE = re.compile(r"^[\d\s.,:/\-+%€$]+$", re.UNICODE)


def replier(valeur: str) -> str:
    """La forme comparable d'une valeur : casse, accents, ponctuation, espaces.

    La décomposition Unicode est faite avant le retrait des accents pour que
    `é` composé et `é` précomposé se replient pareil — deux extractions du même
    référentiel peuvent les écrire différemment sans que rien ne le montre.
    """
    decompose = unicodedata.normalize("NFKD", str(valeur))
    sans_accent = "".join(c for c in decompose if not unicodedata.combining(c))
    sans_ponctuation = _PONCTUATION.sub(" ", sans_accent)
    return _ESPACES.sub(" ", sans_ponctuation).strip().casefold()


def depluraliser(forme: str) -> str:
    """Retire un pluriel simple. Heuristique, et assumée comme telle.

    Elle attrape `Cadres` / `Cadre` et `Bureaux` / `Bureau`. Elle ne prétend pas
    couvrir toutes les langues : ce module ne connaît aucune nomenclature, et il
    ne connaît pas davantage la grammaire du client. Un rapprochement manqué se
    rattrape à la main ; un rapprochement inventé se paye.
    """
    if len(forme) > 1 and forme[-1] in "sx":
        return forme[:-1]
    return forme


def est_typee(valeurs: Iterable[str]) -> float:
    """Part des valeurs qui ressemblent à un nombre ou à une date.

    Calculée sur les valeurs, jamais déduite d'un nom de colonne : le produit
    ne présume d'aucun nom.
    """
    valeurs = [str(valeur) for valeur in valeurs]
    if not valeurs:
        return 0.0
    typees = sum(1 for valeur in valeurs if _TYPEE.match(valeur.strip()))
    return typees / len(valeurs)


def distance(gauche: str, droite: str, maximum: int) -> int:
    """Distance d'édition, bornée et abandonnée dès qu'elle dépasse.

    Bornée parce que la valeur exacte ne sert à rien au-delà du seuil, et que
    l'abandon anticipé est ce qui rend le repérage tenable sur une colonne à
    deux mille valeurs distinctes.
    """
    if abs(len(gauche) - len(droite)) > maximum:
        return maximum + 1
    if gauche == droite:
        return 0

    precedente = list(range(len(droite) + 1))
    for rang, caractere in enumerate(gauche, start=1):
        courante = [rang]
        for colonne, autre in enumerate(droite, start=1):
            courante.append(min(
                precedente[colonne] + 1,
                courante[colonne - 1] + 1,
                precedente[colonne - 1] + (caractere != autre),
            ))
        if min(courante) > maximum:
            return maximum + 1
        precedente = courante
    return precedente[-1]


def initiales(forme: str) -> str:
    """Les initiales des mots d'une forme repliée.

    `responsable ressources humaines` rend `rrh`, ce qui rapproche le libellé
    de son sigle sans qu'aucun dictionnaire ne soit nécessaire.
    """
    return "".join(mot[0] for mot in forme.split() if mot)


def est_un_sigle(sigle: str, forme: str, mot_court_max: int) -> bool:
    """`sigle` est-il fait des initiales des mots de `forme`, les mots courts
    pouvant être sautés ?

    Les initiales de **tous** les mots ne suffisent pas : « contrat a duree
    indeterminee » rend `cadi`, jamais `cdi` ; « directeur des ressources
    humaines » rend `ddrh`, jamais `drh`. Un sigle ne garde pas les mots
    outils. Constaté en formation : `CDI` et `Contrat à durée indéterminée`
    n'étaient pas rapprochés, alors que la règle des initiales existe pour ça.

    Aucun dictionnaire de mots outils — ce module n'en connaît aucun, dans
    aucune langue. Un mot **plus court que `mot_court_max`** peut être sauté ;
    un mot plus long doit donner sa lettre. Le seuil est celui du workspace
    pour la racine minimale : en deçà, une suite de lettres ne porte pas de
    sens à elle seule, et c'est ce qui fait un mot outil — « à », « de »,
    « des », « of », « für » — sans avoir à les nommer.

    Les mots longs ne se sautent jamais : « chef de service » n'est pas `cs`
    par erreur, c'en est un sigle légitime ; mais « chef de service
    informatique » n'est pas `cs`, parce qu'« informatique » doit donner sa
    lettre.
    """
    mots = forme.split()
    # atteints[j] : les j premières lettres du sigle sont expliquées par les
    # mots déjà lus. Un ensemble, parce que sauter ou non un mot court ouvre
    # deux lectures.
    atteints = {0}
    for mot in mots:
        suivants = set()
        for rang in atteints:
            if rang < len(sigle) and mot[0] == sigle[rang]:
                suivants.add(rang + 1)
            if len(mot) < mot_court_max:
                suivants.add(rang)
        if not suivants:
            return False
        atteints = suivants
    return len(sigle) in atteints


# -------------------------------------------------------------- les signaux


def signaux_entre(gauche: str, droite: str, effectifs: Mapping[str, int],
                  reglages: Reglages) -> FrozenSet[str]:
    """Ce qui rapproche deux valeurs, ou rien.

    Rendu comme un ensemble : plusieurs signaux peuvent se cumuler, et c'est
    leur liste qui est montrée à l'utilisateur. Un ensemble vide signifie qu'il
    n'y a rien à dire — et donc rien à proposer.
    """
    forme_gauche, forme_droite = replier(gauche), replier(droite)
    if not forme_gauche or not forme_droite:
        # Une valeur vide ne se rapproche de rien : elle n'est pas une autre
        # écriture de quelque chose, elle est une absence.
        return frozenset()

    trouves = set()
    if forme_gauche == forme_droite:
        trouves.add(SIGNAL_FORME)
    else:
        if depluraliser(forme_gauche) == depluraliser(forme_droite):
            trouves.add(SIGNAL_PLURIEL)
        if distance(forme_gauche, forme_droite,
                    reglages.distance_edition_max) <= reglages.distance_edition_max:
            trouves.add(SIGNAL_FRAPPE)
        trouves |= _signaux_de_reduction(forme_gauche, forme_droite, reglages)

    if not trouves:
        return frozenset()

    desequilibre = _effectif_desequilibre(gauche, droite, effectifs, reglages)

    # **Une distance d'édition, seule, ne rapproche rien.**
    #
    # Le module proposait de fondre `CDI` et `CDD` : une lettre d'écart, sous
    # le seuil, donc « faute de frappe ». Les deux valeurs désignent l'exact
    # contraire l'une de l'autre. Même chose pour « à durée indéterminée » et
    # « à durée déterminée », deux caractères d'écart — et pour toute la
    # famille du préfixe privatif, `Actif` contre `Inactif`, `Validé` contre
    # `Invalidé`, où la fusion inverse le sens.
    #
    # Ce n'est pas une proposition de trop : c'est la seule sortie du module
    # qui **nourrisse un calcul**. Fondre deux valeurs change les populations,
    # donc les couvertures, donc le modèle de rôles. Acceptée une fois, elle
    # fausse tout ce qui suit sans que rien ne le signale.
    #
    # La règle qui manquait était déjà écrite, dans la docstring du signal
    # d'effectif : **une faute de frappe est rare face à la forme correcte**.
    # Trois `Infimier` contre huit cent douze `Infirmier` en sont une ; deux
    # mille quatre cent quatre-vingt-douze `CDD` contre neuf mille sept cent
    # vingt-huit `CDI` sont deux types de contrat.
    #
    # Le prix est connu et assumé, comme pour la troncature : une faute de
    # frappe systématique — la moitié d'un export mal encodé — ne sera pas
    # rapprochée. Entre manquer un rapprochement et en inventer un qui inverse
    # un sens, ce module manque.
    #
    # **Une exception, et une seule : l'interversion de deux lettres voisines.**
    #
    # C'est la faute de frappe la plus courante, et la règle ci-dessus la
    # perdait dès que la saisie fautive s'était répandue — `Comptbale` face à
    # `Comptable`, quatorze contre douze. Une interversion est sûre là où une
    # substitution ne l'est pas : elle ne change **aucune lettre**, seulement
    # leur ordre. `CDI` ne devient pas `CDD` par interversion, ni `Actif`
    # `Inactif` : il faut remplacer ou ajouter une lettre, et c'est exactement
    # ce que la règle continue de refuser.
    #
    # Deux garde-fous, parce qu'échanger des lettres ne suffit pas :
    # l'échange doit porter sur deux positions **voisines** — `INF` et `FIN`
    # ont les mêmes lettres sans être une frappe — et il doit rester du
    # contexte autour, sans quoi `OK` et `KO` se rapprocheraient alors qu'ils
    # désignent l'inverse.
    if (trouves == {SIGNAL_FRAPPE} and not desequilibre
            and not _interversion_voisine(forme_gauche, forme_droite)):
        return frozenset()

    if desequilibre:
        trouves.add(SIGNAL_EFFECTIF)
    return frozenset(trouves)


def _signaux_de_reduction(forme_gauche: str, forme_droite: str,
                          reglages: Reglages) -> FrozenSet[str]:
    """Abréviation et troncature : une valeur est le début de l'autre.

    **Un préfixe qui s'arrête sur un mot entier n'est pas une troncature.**
    C'est le point le plus délicat du module, et le banc l'a trouvé :
    « Cadre » est le début de « Cadre de santé », et les deux portent des
    droits différents. Les fusionner fabriquerait un rôle faux — ce qui est
    pire que de n'en trouver aucun.

    La distinction est nette. Une troncature coupe **au milieu d'un mot** :
    `secretaire medic` pour `secretaire medicale`, un libellé rogné à l'export.
    Un préfixe qui s'arrête sur une frontière de mot, puis que l'autre valeur
    poursuit par des mots entiers, désigne un libellé **plus précis** — une
    spécialisation, pas une écriture différente.

    Le prix de cette règle est connu et assumé : un libellé coupé pile sur un
    espace — `Secrétaire ` pour `Secrétaire médicale` — n'est pas rapproché. Il
    est indiscernable d'un libellé plus large qui existerait pour lui-même, et
    entre manquer un rapprochement et en inventer un, ce module manque.

    Le suffixe commun, lui, n'est jamais un signal : « secrétaire médicale » et
    « assistante médicale » le partagent et ne désignent pas la même chose.
    """
    courte, longue = sorted((forme_gauche, forme_droite), key=len)
    trouves = set()
    if len(courte) >= 2 and longue.startswith(courte) and len(longue) > len(courte):
        if longue[len(courte)] != " ":
            trouves.add(
                SIGNAL_ABREVIATION if len(courte) < reglages.longueur_racine_min
                else SIGNAL_TRONCATURE)
    elif (len(courte) >= 2 and " " not in courte
          and est_un_sigle(courte, longue, reglages.longueur_racine_min)):
        trouves.add(SIGNAL_ABREVIATION)
    return frozenset(trouves)


def _interversion_voisine(gauche: str, droite: str) -> bool:
    """Les deux formes ne diffèrent-elles que par deux lettres voisines échangées ?

    La faute de frappe la plus courante, et la seule dont la forme suffise à
    la reconnaître : les lettres sont identiques, seul leur ordre change. Une
    substitution — `CDI` vers `CDD` — ou une insertion — `Actif` vers
    `Inactif` — ne passent pas ce contrôle.

    Deux conditions, chacune pour un cas réel :

    - **positions voisines** : `INF` et `FIN` portent les mêmes lettres sans
      être une frappe l'un de l'autre ; il faut deux échanges pour passer de
      l'un à l'autre, ce qui n'est plus un geste mais un autre mot ;
    - **du contexte autour** : quand les deux lettres échangées sont toute la
      valeur, il ne reste rien qui soutienne l'hypothèse de la faute — `OK` et
      `KO` désignent l'inverse l'un de l'autre.
    """
    if len(gauche) != len(droite) or len(gauche) <= 2 or gauche == droite:
        return False
    differentes = [rang for rang, (un, autre) in enumerate(zip(gauche, droite))
                   if un != autre]
    if len(differentes) != 2:
        return False
    premier, second = differentes
    return (second == premier + 1
            and gauche[premier] == droite[second]
            and gauche[second] == droite[premier])


def _effectif_desequilibre(gauche: str, droite: str,
                           effectifs: Mapping[str, int],
                           reglages: Reglages) -> bool:
    rare, frequent = sorted((effectifs.get(gauche, 0), effectifs.get(droite, 0)))
    if rare <= 0:
        return False
    return frequent / rare >= reglages.ecart_effectif_significatif


# --------------------------------------------------------------- les grappes


@dataclass(frozen=True)
class Grappe:
    """Un ensemble de valeurs candidates au regroupement.

    `origine` dit d'où vient la proposition. Elle vaut `locale` ici ; un
    enrichissement par modèle en produira d'autres, et un auditeur doit pouvoir
    isoler ce qui vient d'un modèle.

    `motif` est la **raison invoquée** par le modèle, telle qu'il l'a écrite.
    Elle reste vide pour le repérage local, qui n'argumente pas : il montre des
    signaux, et un motif fabriqué ici se lirait comme une justification.

    Pour une proposition de modèle, c'est le champ décisif. Les contrôles au
    retour vérifient que les valeurs existent, qu'elles n'ont pas été refusées,
    que le groupe est assez long — aucun ne sait ce que les valeurs veulent
    dire. Un modèle a proposé `CDI`, `C.D.I.` et `CDD` ensemble en écrivant
    « toutes ces abréviations désignent un contrat à durée indéterminée » : les
    cinq contrôles passaient, et la phrase qui trahit l'erreur était jetée.
    """

    valeurs: Tuple[str, ...]
    effectifs: Tuple[int, ...]
    forme_retenue: str
    signaux: Tuple[str, ...]
    origine: str = "locale"
    motif: str = ""

    @property
    def effectif_total(self) -> int:
        return sum(self.effectifs)

    @property
    def effectif_maximal(self) -> int:
        return max(self.effectifs) if self.effectifs else 0

    def invisible_avant(self, effectif_minimal: int) -> bool:
        """La grappe fait-elle apparaître une population que le mining ratait ?

        C'est la seule mesure qui justifie l'opération, et elle doit être à
        l'écran **avant** l'acceptation : aucune valeur n'atteignait le seuil
        séparément, leur réunion l'atteint.
        """
        if effectif_minimal <= 0:
            return False
        return (self.effectif_maximal < effectif_minimal
                and self.effectif_total >= effectif_minimal)

    def en_document(self, effectif_minimal: int = 0) -> Dict[str, Any]:
        return {
            "valeurs": [{"valeur": valeur, "effectif": effectif}
                        for valeur, effectif in zip(self.valeurs, self.effectifs)],
            "forme_retenue": self.forme_retenue,
            "signaux": list(self.signaux),
            "origine": self.origine,
            "motif": self.motif,
            "effectif_total": self.effectif_total,
            "effectif_maximal": self.effectif_maximal,
            "invisible_avant": self.invisible_avant(effectif_minimal),
        }


@dataclass(frozen=True)
class Analyse:
    """Ce qu'une colonne a donné, et ce qui n'a pas été regardé."""

    referentiel: str
    colonne: str
    grappes: Tuple[Grappe, ...] = ()
    valeurs_distinctes: int = 0
    valeurs_analysees: int = 0
    #: Vraie quand la colonne porte surtout des nombres ou des dates : la
    #: proximité textuelle y produirait du bruit.
    typee: bool = False
    part_typee: float = 0.0

    def en_document(self, effectif_minimal: int = 0) -> Dict[str, Any]:
        return {
            "referentiel": self.referentiel,
            "colonne": self.colonne,
            "grappes": [grappe.en_document(effectif_minimal)
                        for grappe in self.grappes],
            "valeurs_distinctes": self.valeurs_distinctes,
            "valeurs_analysees": self.valeurs_analysees,
            "valeurs_non_analysees": max(
                0, self.valeurs_distinctes - self.valeurs_analysees),
            "typee": self.typee,
            "part_typee": round(self.part_typee, 4),
            # Le seuil est rendu avec l'analyse : l'écran annonce la
            # conséquence — « au-dessus de votre effectif minimal de 15 » — et
            # il ne doit pas aller chercher ce chiffre ailleurs, au risque
            # d'en afficher un autre que celui qui a servi au calcul.
            "effectif_minimal": effectif_minimal,
        }


def _paire(gauche: str, droite: str) -> Tuple[str, str]:
    """Une paire ordonnée de **formes repliées**.

    Deux raisons, et la seconde est la bonne. L'ordre d'abord : refuser
    (A, B) doit refuser (B, A).

    Le repliement ensuite, et il n'est pas cosmétique. Un refus porté sur la
    chaîne exacte se contourne en changeant un accent : l'utilisateur qui dit
    que `Cadre` et `Cadre de santé` sont distincts n'a rien dit de
    `Cadre de sante` — et le repérage les rapprocherait le lendemain. Un refus
    porte sur ce que les valeurs **désignent**, pas sur leur orthographe du
    jour.
    """
    un, autre = replier(gauche), replier(droite)
    return (un, autre) if un <= autre else (autre, un)


def compter(valeurs: Iterable[Any]) -> Dict[str, int]:
    """Les effectifs d'une colonne, les valeurs vides écartées.

    Une absence n'est pas une autre écriture de quelque chose : elle ne
    participe ni au repérage, ni à ce qui serait soumis à un modèle.
    """
    effectifs: Dict[str, int] = {}
    for valeur in valeurs:
        texte = "" if valeur is None else str(valeur)
        if not texte.strip():
            continue
        effectifs[texte] = effectifs.get(texte, 0) + 1
    return effectifs


def valeurs_retenues(effectifs: Mapping[str, int], maximum: int) -> List[str]:
    """Les valeurs à regarder, les plus fréquentes d'abord.

    Si une colonne dépasse le plafond, ce sont les valeurs qui pèsent sur les
    populations qu'on veut avoir regardées. L'ordre est total — effectif puis
    valeur — pour que deux lectures des mêmes données rendent la même chose.

    Écrit une fois et partagé : le repérage local et l'envoi à un modèle
    doivent porter sur les **mêmes** valeurs, sans quoi une proposition du
    modèle citerait une valeur que l'analyse n'a pas regardée et l'écran
    rapprocherait deux listes qui ne parlent pas de la même population.
    """
    ordonnees = sorted(effectifs, key=lambda valeur: (-effectifs[valeur], valeur))
    return ordonnees[:maximum] if maximum > 0 else []


def analyser(valeurs: Sequence[str], referentiel: str, colonne: str,
             reglages: Optional[Reglages] = None,
             refus: Iterable[Tuple[str, str]] = ()) -> Analyse:
    """Repère les grappes d'une colonne. Aucune sortie réseau, aucun modèle.

    Les valeurs sont celles de la colonne, telles qu'elles sont dans le
    fichier. Les vides sont écartées : une absence n'est pas une autre écriture
    de quelque chose.

    Les paires refusées une fois ne sont plus proposées — ni directement, ni
    par transitivité : une grappe ne peut pas contenir deux valeurs que
    l'utilisateur a dites distinctes.
    """
    reglages = reglages or Reglages()
    effectifs = compter(valeurs)

    part_typee = est_typee(effectifs)
    if part_typee > reglages.part_typee_max:
        return Analyse(referentiel=referentiel, colonne=colonne,
                       valeurs_distinctes=len(effectifs), valeurs_analysees=0,
                       typee=True, part_typee=part_typee)

    retenues = valeurs_retenues(effectifs, reglages.valeurs_analysees_max)

    interdites = {_paire(gauche, droite) for gauche, droite in refus}
    aretes = []
    for rang, gauche in enumerate(retenues):
        for droite in retenues[rang + 1:]:
            if _paire(gauche, droite) in interdites:
                continue
            trouves = signaux_entre(gauche, droite, effectifs, reglages)
            if trouves:
                aretes.append((gauche, droite, trouves))

    grappes = _composantes(retenues, aretes, interdites, effectifs)
    return Analyse(referentiel=referentiel, colonne=colonne,
                   grappes=tuple(grappes), valeurs_distinctes=len(effectifs),
                   valeurs_analysees=len(retenues), typee=False,
                   part_typee=part_typee)


def _composantes(valeurs: Sequence[str],
                 aretes: Sequence[Tuple[str, str, FrozenSet[str]]],
                 interdites: FrozenSet[Tuple[str, str]],
                 effectifs: Mapping[str, int]) -> List[Grappe]:
    """Réunit les valeurs liées, **sans jamais réunir une paire refusée**.

    Les arêtes sont traitées de la mieux motivée à la moins motivée, et une
    réunion qui mettrait deux valeurs refusées dans la même grappe est écartée.
    Sans cette contrainte, `Cadre` et `Cadre de santé` se retrouveraient
    ensemble par un tiers, et le refus de l'utilisateur serait sans effet.

    L'ordre de traitement est total et déterministe : deux analyses des mêmes
    données rendent les mêmes grappes.
    """
    parent = {valeur: valeur for valeur in valeurs}

    def racine(valeur: str) -> str:
        while parent[valeur] != valeur:
            parent[valeur] = parent[parent[valeur]]
            valeur = parent[valeur]
        return valeur

    membres: Dict[str, List[str]] = {valeur: [valeur] for valeur in valeurs}
    signaux: Dict[str, set] = {valeur: set() for valeur in valeurs}

    # L'identité de forme passe avant tout le reste : deux écritures de la
    # même chaîne sont la même valeur, et les séparer pour laisser une
    # troncature prendre la place n'aurait aucun sens. Vient ensuite le nombre
    # de signaux, puis l'ordre alphabétique — total et déterministe.
    ordonnees = sorted(aretes, key=lambda a: (SIGNAL_FORME not in a[2],
                                              -len(a[2]), a[0], a[1]))
    for gauche, droite, trouves in ordonnees:
        tete_gauche, tete_droite = racine(gauche), racine(droite)
        if tete_gauche == tete_droite:
            signaux[tete_gauche] |= trouves
            continue
        if any(_paire(un, autre) in interdites
               for un in membres[tete_gauche] for autre in membres[tete_droite]):
            continue
        parent[tete_droite] = tete_gauche
        membres[tete_gauche].extend(membres[tete_droite])
        signaux[tete_gauche] |= signaux[tete_droite] | trouves

    grappes = []
    for valeur in valeurs:
        if racine(valeur) != valeur or len(membres[valeur]) < 2:
            continue
        groupe = sorted(membres[valeur], key=lambda v: (-effectifs[v], v))
        grappes.append(Grappe(
            valeurs=tuple(groupe),
            effectifs=tuple(effectifs[v] for v in groupe),
            # La forme retenue est la plus fréquente — jamais un choix du
            # produit. Entre `Infirmier` et `INF`, c'est l'organisation qui
            # tranche, et elle peut corriger à l'écran.
            forme_retenue=groupe[0],
            signaux=tuple(sorted(signaux[valeur])),
        ))
    # Les grappes qui font le plus de différence en premier : c'est par là que
    # la relecture doit commencer.
    grappes.sort(key=lambda g: (-g.effectif_total, g.forme_retenue))
    return grappes
