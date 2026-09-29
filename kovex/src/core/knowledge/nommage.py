# Fichier : src/core/knowledge/nommage.py
"""Lire ce qu'un identifiant de droit dit déjà.

`D_SAP_FI_CREATE_VENDOR` porte de l'information : une application, un module,
une action, un objet. Le produit ne la lisait pas, et un client devant quarante
mille identifiants n'a aucun moyen de la lui donner à la main.

**La convention n'est pas dans ce fichier, et elle n'y sera jamais.** Le
séparateur est un souligné chez l'un, un point chez l'autre, un tiret chez le
troisième ; la position de l'application est la première ici et la deuxième
là ; et beaucoup de référentiels n'ont aucune convention du tout. L'écrire dans
le code, c'est se tromper chez la plupart des clients — et se tromper
silencieusement, ce qui est pire : une application déduite de travers vaut moins
que pas d'application.

Ce module porte donc la **mécanique**, et le client porte la **déclaration** :
où lire, avec quel séparateur, et ce que chaque position nomme.

Pourquoi déclarer plutôt que deviner
------------------------------------
Un nommage est une **convention**, pas un texte à interpréter. Une fois qu'elle
est dite, elle s'applique à cent pour cent des droits qui la respectent, de
façon reproductible, sans qu'aucun modèle n'intervienne — et le produit dit
combien ne la respectent pas plutôt que de leur inventer une valeur.

C'est ce dénombrement qui rend la déclaration possible : personne ne connaît sa
propre convention de mémoire, mais tout le monde la reconnaît en voyant
« position 2 : 61 valeurs distinctes, dont SAP 12 400 fois ».

Ce que le produit ne fait jamais
--------------------------------
**Décaler.** Un identifiant qui porte moins de segments que la convention n'en
déclare ne reçoit aucune valeur dérivée. Prendre les segments qu'on a et les
ranger dans les premières positions produirait une application crédible et
fausse.

**Écraser une colonne du client.** Les colonnes dérivées portent un nom
réservé ; si ce nom existe déjà dans le fichier, la dérivation est refusée et le
dit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import (Any, Dict, Iterable, List, Mapping, Optional, Sequence,
                    Tuple)

# ------------------------------------------------------- les rôles de position

#: L'application à laquelle le droit appartient. C'est le seul rôle dont le
#: produit **calcule** quelque chose : une règle de séparation des tâches qui
#: nomme une application se réévalue à chaque chargement, là où une règle qui
#: énumère des droits se périme.
ROLE_APPLICATION = "application"
#: Le module ou le domaine fonctionnel à l'intérieur de l'application.
ROLE_MODULE = "module"
#: Ce que le droit permet de faire — créer, valider, consulter.
ROLE_ACTION = "action"
#: Sur quoi il permet de le faire — un fournisseur, une commande, un dossier.
ROLE_OBJET = "objet"
#: L'environnement : production, recette, formation.
ROLE_ENVIRONNEMENT = "environnement"
#: L'entité juridique ou le pays, sur les référentiels de groupe.
ROLE_ENTITE = "entite"

#: Les rôles qu'une position peut prendre. Chacun est aussi une clé de
#: traduction — `nommage.role.<code>` : le serveur ne rend pas de phrase.
#:
#: La liste est **fermée**, et c'est délibéré : le produit sait quoi faire d'une
#: application, il ne saurait rien faire d'un rôle que le client aurait inventé.
#: Une position dont le contenu n'entre dans aucun de ces rôles se déclare
#: ignorée, ce qui est une information en soi.
ROLES: Tuple[str, ...] = (ROLE_APPLICATION, ROLE_MODULE, ROLE_ACTION,
                          ROLE_OBJET, ROLE_ENVIRONNEMENT, ROLE_ENTITE)

#: Position sans rôle : son contenu est lu, dénombré, et rien n'en est dérivé.
ROLE_IGNORE = ""

#: Préfixe des colonnes dérivées. Réservé : une colonne du fichier du client
#: qui le porterait ferait refuser la dérivation plutôt que d'être écrasée.
PREFIXE_DERIVEE = "kovex_"

#: Nombre de positions qu'une convention peut déclarer. Ce n'est pas une borne
#: métier : c'est la borne d'une liste qui vient de l'extérieur.
POSITIONS_MAX = 12

#: Longueur maximale du séparateur déclaré.
SEPARATEUR_MAX = 8

#: Valeurs distinctes rendues par position dans le dénombrement. Le comptage
#: porte sur tout le référentiel ; la liste sert à reconnaître la convention,
#: et vingt-cinq valeurs y suffisent.
VALEURS_PAR_POSITION_MAX = 25

#: Découpes distinctes rendues dans la distribution des longueurs.
LONGUEURS_MAX = 12


class ConventionInvalide(ValueError):
    """Une convention que le produit ne sait pas appliquer.

    Elle porte le champ fautif, sa valeur et les valeurs attendues — jamais une
    phrase : le serveur ne connaît pas la langue de l'utilisateur.
    """

    def __init__(self, champ: str, valeur: Any,
                 attendues: Sequence[str] = ()) -> None:
        super().__init__(f"{champ}={valeur!r}")
        self.champ = champ
        self.valeur = valeur
        self.attendues = tuple(attendues)

    def document(self) -> Dict[str, Any]:
        return {"champ": self.champ, "valeur": str(self.valeur),
                "attendues": list(self.attendues)}


@dataclass(frozen=True)
class Convention:
    """Ce que le client a déclaré : où lire, comment découper, quoi nommer.

    Gelée : elle se construit au chargement et se lit partout ensuite. Une
    convention qu'un écran pourrait modifier au passage ferait dire deux choses
    différentes du même droit à deux endroits du produit.
    """

    #: La colonne du référentiel des droits où lire. Vide : l'identifiant du
    #: droit, la seule colonne que le produit connaisse par construction.
    colonne: str = ""
    #: Ce qui sépare deux segments. Déclaré : le souligné chez l'un, le point
    #: chez l'autre, et parfois les deux dans le même fichier.
    separateur: str = ""
    #: Ce que chaque position nomme, dans l'ordre. `""` pour une position dont
    #: le contenu ne se range dans aucun rôle connu.
    positions: Tuple[str, ...] = ()

    @property
    def declaree(self) -> bool:
        """Y a-t-il quelque chose à découper ?

        Une convention vide n'est pas une erreur : c'est l'état de départ de
        tout workspace, et le produit doit s'y comporter comme si la fonction
        n'existait pas — aucune colonne dérivée, aucun dénombrement.
        """
        return bool(self.separateur and self.positions)

    @property
    def nommees(self) -> Tuple[Tuple[int, str], ...]:
        """Les positions qui portent un rôle, avec leur rang."""
        return tuple((rang, role)
                     for rang, role in enumerate(self.positions) if role)

    def colonne_derivee(self, role: str) -> str:
        return f"{PREFIXE_DERIVEE}{role}"


def _positions_lues(brut: Any) -> Tuple[str, ...]:
    """Les positions retenues d'une déclaration, dans l'ordre donné.

    Contrairement aux fragments d'un marqueur de comptes, un rôle inconnu
    n'est **pas** écarté en silence : écarter la position décalerait toutes
    les suivantes, et la convention nommerait alors les mauvaises. Une
    déclaration illisible est refusée entière.
    """
    if brut is None:
        return ()
    if not isinstance(brut, (list, tuple)):
        raise ConventionInvalide("positions", brut)
    if len(brut) > POSITIONS_MAX:
        raise ConventionInvalide("positions", len(brut),
                                 (str(POSITIONS_MAX),))
    lues: List[str] = []
    for valeur in brut:
        role = str(valeur or "").strip().lower()
        if role and role not in ROLES:
            raise ConventionInvalide("role", role, ROLES)
        lues.append(role)
    nommes = [role for role in lues if role]
    if len(set(nommes)) != len(nommes):
        # Deux positions du même rôle produiraient deux fois la même colonne
        # dérivée, et la seconde effacerait la première sans rien dire.
        raise ConventionInvalide("role", ", ".join(sorted(nommes)), ROLES)
    return tuple(lues)


def depuis_la_configuration(config: Mapping[str, Any]) -> Convention:
    """Lit la convention du workspace, ou refuse.

    Le refus remonte : une convention illisible relue comme une convention vide
    ferait disparaître des colonnes dérivées sans que personne ne sache
    pourquoi, et le client chercherait dans son export.
    """
    positions = _positions_lues(config.get("right_naming_positions"))
    separateur = str(config.get("right_naming_separator", "") or "")
    if len(separateur) > SEPARATEUR_MAX:
        raise ConventionInvalide("separateur", separateur)
    if positions and any(positions) and not separateur:
        # Des positions sans séparateur ne découpent rien : la déclaration est
        # à moitié écrite, et la traiter comme vide la ferait oublier.
        raise ConventionInvalide("separateur", separateur)
    return Convention(colonne=str(config.get("right_naming_column", "") or ""),
                      separateur=separateur, positions=positions)


def decouper(valeur: Any, convention: Convention) -> Tuple[str, ...]:
    """Les segments d'une valeur, sans rien interpréter."""
    if not convention.separateur:
        return ()
    texte = str(valeur if valeur is not None else "").strip()
    if not texte:
        return ()
    return tuple(segment for segment in texte.split(convention.separateur))


def deriver(valeur: Any, convention: Convention) -> Dict[str, str]:
    """Ce que cette valeur dit, rôle par rôle — ou rien.

    Une valeur qui porte **moins** de segments que la convention n'en déclare
    ne rend rien du tout : ranger les segments dont on dispose dans les
    premières positions produirait une application crédible et fausse, et une
    application fausse vaut moins que pas d'application.

    Une valeur qui en porte **plus** est acceptée, et le surplus est ignoré :
    un référentiel régulier sur ses premières positions et libre sur les
    dernières est le cas le plus fréquent, et le refuser reviendrait à ne rien
    dériver du tout.
    """
    if not convention.declaree:
        return {}
    segments = decouper(valeur, convention)
    if len(segments) < len(convention.positions):
        return {}
    return {role: segments[rang] for rang, role in convention.nommees}


def _colonne_lue(droits, convention: Convention,
                 colonne_droit: str) -> Optional[str]:
    """La colonne effectivement lue, ou `None` si elle n'est pas là.

    Une colonne déclarée puis absente du fichier chargé est un cas réel — le
    client a renommé son export. Le produit ne dérive alors rien et le dit,
    plutôt que de se rabattre sur l'identifiant : découper une autre colonne
    que celle déclarée donnerait un résultat crédible et faux.
    """
    if droits is None or getattr(droits, "empty", True):
        return None
    demandee = convention.colonne or colonne_droit
    return demandee if demandee in droits.columns else None


def collisions(droits, convention: Convention) -> Tuple[str, ...]:
    """Les colonnes dérivées dont le nom existe déjà dans le fichier du client.

    Les colonnes viennent des fichiers du client et le produit n'en connaît
    aucune : écraser celle qui porterait par hasard un nom réservé ferait
    disparaître une donnée du client au profit d'une donnée calculée.
    """
    if droits is None or getattr(droits, "empty", True):
        return ()
    presentes = set(droits.columns)
    return tuple(sorted(convention.colonne_derivee(role)
                        for _, role in convention.nommees
                        if convention.colonne_derivee(role) in presentes))


def enrichir(droits, convention: Convention, colonne_droit: str):
    """Ajoute au référentiel des droits une colonne par rôle déclaré.

    Rendu tel quel quand rien n'est déclaré, quand la colonne déclarée manque,
    ou quand un nom réservé entrerait en collision : la dérivation est un
    enrichissement, elle ne doit jamais abîmer le référentiel.
    """
    if not convention.declaree:
        return droits
    colonne = _colonne_lue(droits, convention, colonne_droit)
    if colonne is None or collisions(droits, convention):
        return droits
    enrichi = droits.copy()
    valeurs = [deriver(valeur, convention) for valeur in enrichi[colonne]]
    for _, role in convention.nommees:
        enrichi[convention.colonne_derivee(role)] = [
            derive.get(role, "") for derive in valeurs]
    return enrichi


def denombrer(droits, convention: Convention,
              colonne_droit: str) -> Dict[str, Any]:
    """Ce que la convention découperait, position par position.

    C'est la même règle que les droits sensibles et les comptes à privilèges :
    **les mots viennent du client, les chiffres viennent du calcul**. Personne
    ne connaît sa convention de mémoire ; tout le monde la reconnaît en voyant
    « position 2 : 61 valeurs distinctes, dont SAP 12 400 fois ».

    La **distribution des longueurs** est rendue avec le reste, et c'est elle
    qui dit si le référentiel a une convention du tout : trois découpes
    majoritaires sur quatre mille droits se déclarent, douze découpes
    équiprobables ne se déclarent pas.
    """
    resume: Dict[str, Any] = {
        "declaree": convention.declaree,
        "colonne": convention.colonne or colonne_droit,
        "separateur": convention.separateur,
        "positions": list(convention.positions),
        "colonne_absente": False,
        "collisions": [],
        "population": 0,
        "conformes": 0,
        "longueurs": [],
        "valeurs": [],
    }
    if droits is None or getattr(droits, "empty", True):
        return resume
    resume["population"] = int(len(droits))
    if not convention.separateur:
        return resume
    colonne = _colonne_lue(droits, convention, colonne_droit)
    if colonne is None:
        resume["colonne_absente"] = True
        return resume
    resume["collisions"] = list(collisions(droits, convention))

    longueurs: Dict[int, int] = {}
    par_position: List[Dict[str, int]] = [
        {} for _ in range(len(convention.positions))]
    conformes = 0
    for valeur in droits[colonne]:
        segments = decouper(valeur, convention)
        longueurs[len(segments)] = longueurs.get(len(segments), 0) + 1
        if len(segments) < len(convention.positions):
            continue
        conformes += 1
        for rang in range(len(convention.positions)):
            compte = par_position[rang]
            compte[segments[rang]] = compte.get(segments[rang], 0) + 1
    resume["conformes"] = conformes
    # Les découpes les plus fréquentes d'abord : c'est la forme du référentiel
    # qu'on cherche à reconnaître, pas la liste exhaustive de ses accidents.
    resume["longueurs"] = [
        {"segments": segments, "droits": compte}
        for segments, compte in sorted(longueurs.items(),
                                       key=lambda paire: (-paire[1], paire[0]))
        [:LONGUEURS_MAX]]
    resume["valeurs"] = [
        {"position": rang,
         "role": convention.positions[rang],
         "distinctes": len(compte),
         "valeurs": [{"valeur": valeur, "droits": nombre}
                     for valeur, nombre in sorted(
                         compte.items(),
                         key=lambda paire: (-paire[1], paire[0]))
                     [:VALEURS_PAR_POSITION_MAX]]}
        for rang, compte in enumerate(par_position)]
    return resume


def positions_observees(droits, convention: Convention, colonne_droit: str,
                        positions: int) -> Dict[str, Any]:
    """Le dénombrement d'une découpe **qu'on n'a pas encore déclarée**.

    C'est ce qui permet de déclarer une convention qu'on ne connaît pas par
    cœur : on donne un séparateur et un nombre de positions, le produit montre
    ce que chacune contient, et on nomme ensuite. Sans cela, il faudrait
    enregistrer une déclaration fausse pour voir ce qu'elle produit.
    """
    essai = Convention(colonne=convention.colonne,
                       separateur=convention.separateur,
                       positions=tuple(ROLE_IGNORE
                                       for _ in range(max(0, positions))))
    return denombrer(droits, essai, colonne_droit)
