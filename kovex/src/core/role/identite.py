"""Identité d'un rôle : ce qui fait qu'un rôle proposé deux fois est le même.

Un rôle proposé par le mining n'existe nulle part : il naît d'un calcul et
disparaît au calcul suivant. Pourtant l'utilisateur décide sur lui — il le
refuse, il le valide —, et la décision doit survivre au recalcul. Il faut donc
que deux exécutions du mining donnent au même rôle le même identifiant, sans
rien stocker entre les deux.

L'identifiant est une empreinte de ce qui *définit* le rôle, jamais de ce qui
le décrit. Le nom n'entre pas dans le calcul : renommer un rôle ne doit pas le
faire réapparaître après un refus. L'ordre n'y entre pas non plus : les droits
sont triés avant l'empreinte.

Ce que « définit » veut dire dépend de la nature du rôle, et c'est la seule
différence entre les deux constructeurs ci-dessous :

- un rôle **applicatif** est un ensemble de droits, et rien d'autre. Deux rôles
  applicatifs de mêmes droits sont le même rôle ;
- un rôle **métier** est une règle — « qui a ces valeurs d'attributs reçoit ces
  droits ». Deux règles distinctes peuvent accorder exactement les mêmes
  droits à deux populations différentes : ce sont deux rôles. La signature de
  la règle entre donc dans l'empreinte, faute de quoi refuser l'un ferait
  disparaître l'autre.

Les valeurs d'attributs sont des données du client : elles sont hachées, jamais
recopiées dans l'identifiant, qui circule dans les URL et les journaux.
"""

import hashlib
from typing import Iterable, Mapping

#: Longueur de l'empreinte conservée. 12 caractères hexadécimaux, soit 48 bits :
#: la probabilité d'une collision reste négligeable devant le nombre de rôles
#: qu'un référentiel peut produire, et l'identifiant reste lisible dans un
#: journal.
LONGUEUR_EMPREINTE = 12

#: Séparateur des éléments avant hachage. Il ne peut pas apparaître dans un
#: identifiant de droit ni dans une valeur d'attribut sans être échappé, sans
#: quoi deux ensembles distincts pourraient donner la même chaîne.
SEPARATEUR = "|"

#: Les deux natures de rôle. Ce n'est pas un choix métier réglable : le produit
#: ne sait traiter que celles-ci. Déclarée ici parce que la nature d'un rôle
#: détermine ce qui fait son identité.
TYPES_DE_ROLE = ("APPLICATIF", "METIER")

#: Préfixes des identifiants. Ils ne portent aucune information — l'empreinte
#: suffit — mais ils rendent un identifiant lisible dans un journal ou une URL.
PREFIXE_APPLICATIF = "role_app"
PREFIXE_METIER = "role_biz"


def _echapper(element: str) -> str:
    """Rend un élément insensible au séparateur.

    Sans cela, les droits ``{"a|b"}`` et ``{"a", "b"}`` auraient la même
    empreinte, et refuser le premier ferait disparaître le second.
    """
    return str(element).replace("\\", "\\\\").replace(SEPARATEUR, "\\p")


def empreinte(elements: Iterable[str]) -> str:
    """Empreinte stable d'une suite d'éléments, dans l'ordre reçu."""
    canonique = SEPARATEUR.join(_echapper(element) for element in elements)
    return hashlib.sha256(canonique.encode("utf-8")).hexdigest()[:LONGUEUR_EMPREINTE]


def identifiant_applicatif(droits: Iterable[str],
                           prefixe: str = PREFIXE_APPLICATIF) -> str:
    """Identifiant d'un rôle défini par son seul ensemble de droits."""
    return f"{prefixe}_{empreinte(sorted(set(str(droit) for droit in droits)))}"


def identifiant_metier(signature: Mapping[str, object], droits: Iterable[str],
                       prefixe: str = PREFIXE_METIER) -> str:
    """Identifiant d'un rôle métier : sa règle RH *et* ses droits.

    La signature est la règle elle-même — les couples attribut / valeur qui
    désignent la population. Elle est triée par nom d'attribut : l'ordre des
    colonnes choisies par l'utilisateur ne doit pas changer l'identité du rôle.
    """
    regle = [f"{attribut}={signature[attribut]}" for attribut in sorted(signature)]
    droits_tries = sorted(set(str(droit) for droit in droits))
    return f"{prefixe}_{empreinte(regle + [''] + droits_tries)}"
