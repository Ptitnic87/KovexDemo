# Fichier : src/api/routers/nommage.py
"""Ce que la convention de nommage des droits découperait, ici et maintenant.

Une route, et elle ne décide rien : elle dit ce que la déclaration du workspace
produit sur les données chargées. C'est le pendant de « les mots du client, les
chiffres du calcul » pour une convention que le client a pu écrire lui-même —
une position qui rend quatre mille valeurs distinctes sur quatre mille droits
se dénonce par son nombre, et aucune phrase d'avertissement ne ferait ce
travail aussi bien.

Elle accepte un paramètre d'**essai** : un nombre de positions à dénombrer sans
rien déclarer. C'est ce qui permet de reconnaître une convention qu'on ne
connaît pas par cœur — sans lui, il faudrait enregistrer une déclaration fausse
pour voir ce qu'elle produit.

Le dénombrement est recalculé à chaque appel plutôt que conservé : un export
renommé, une colonne disparue, une déclaration modifiée dans l'écran voisin,
tout cela change le résultat.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from starlette.concurrency import run_in_threadpool

from src.api.dependencies import get_data_loader
from src.core.data.loader import DataLoader
from src.core.knowledge.nommage import (POSITIONS_MAX, ROLES, SEPARATEUR_MAX,
                                        Convention, denombrer,
                                        positions_observees)
from src.core.security.auth import User, require_permission_or_dev

router = APIRouter(prefix="/nommage", tags=["Nommage des droits"])

#: Lire le découpage est une consultation de référentiel, au même niveau que le
#: rapport de qualité : rien n'y est décidé et rien n'y est écrit.
LECTURE = "read"


@router.get("")
async def decoupage(
    positions: Optional[int] = Query(None, ge=1, le=POSITIONS_MAX),
    separateur: Optional[str] = Query(None, max_length=SEPARATEUR_MAX),
    colonne: Optional[str] = Query(None, max_length=200),
    loader: DataLoader = Depends(get_data_loader),
    user: User = Depends(require_permission_or_dev(LECTURE)),
) -> Dict[str, Any]:
    """Ce que la convention découperait, position par position.

    Sans paramètre, c'est la déclaration du workspace qui est dénombrée. Avec
    `positions` et `separateur`, c'est un **essai** : rien n'est enregistré, et
    les rôles ne sont pas demandés — on regarde d'abord ce que chaque position
    contient, on la nomme ensuite.
    """
    return await run_in_threadpool(_decoupage, loader, positions, separateur,
                                   colonne)


def _decoupage(loader: DataLoader, positions: Optional[int],
               separateur: Optional[str],
               colonne: Optional[str]) -> Dict[str, Any]:
    declaree = loader.config.naming
    essai = positions is not None
    if essai:
        convention = Convention(
            colonne=colonne if colonne is not None else declaree.colonne,
            separateur=(separateur if separateur is not None
                        else declaree.separateur),
            positions=())
        if not convention.separateur:
            # Un essai sans séparateur ne découpe rien : le dire plutôt que de
            # rendre un dénombrement vide qui passerait pour un référentiel
            # sans convention.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "nommage.separateur_manquant", "params": {}})
        resume = positions_observees(loader.rights, convention,
                                     DataLoader.COL_RIGHT_ID, positions)
    else:
        resume = denombrer(loader.rights, declaree, DataLoader.COL_RIGHT_ID)

    resume["essai"] = essai
    #: Les rôles qu'une position peut prendre. Rendus par le serveur : la liste
    #: est fermée, et une liste écrite en double dans l'écran finirait par ne
    #: plus être la même.
    resume["roles"] = list(ROLES)
    # La déclaration illisible se signale comme les autres du produit : la
    # lecture s'est poursuivie sans elle, et l'écran doit le dire plutôt que de
    # montrer une convention vide qui passerait pour un choix.
    resume["invalide"] = loader.config.naming_invalide
    # Le rattachement droit → application vient-il du nommage ? C'est le seul
    # endroit où la convention alimente un calcul, et le taire ferait chercher
    # la colonne dans l'export.
    # Relevé **au chargement** et non reconstitué ici : une fois la colonne
    # dérivée posée, plus rien ne distingue « le produit l'a calculée » de
    # « elle était dans le fichier », et l'écran dirait l'un pour l'autre.
    applique = loader.nommage_applique
    resume["application_deduite"] = applique["application_deduite"]
    if not essai:
        # Les collisions de la convention **enregistrée** viennent elles aussi
        # du chargement : recalculées ici, elles porteraient sur un référentiel
        # déjà enrichi et signaleraient les colonnes que le produit a lui-même
        # posées.
        resume["collisions"] = applique["collisions"]
    return resume


