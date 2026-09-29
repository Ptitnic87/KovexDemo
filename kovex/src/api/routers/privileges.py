# Fichier : src/api/routers/privileges.py
"""Ce que le marqueur de comptes à privilèges marque, ici et maintenant.

Une seule route, et elle ne décide rien : elle dit ce que la déclaration du
workspace produit sur les données chargées. C'est le pendant de « les mots du
modèle, les chiffres du calcul » pour une liste que le client a pu écrire
lui-même — un fragment qui marque la moitié du référentiel se dénonce par son
nombre, et aucune phrase d'avertissement ne ferait ce travail aussi bien.

Le dénombrement est **recalculé à chaque appel** plutôt que conservé : un
identifiant renommé, une colonne disparue d'un export, une déclaration
modifiée dans l'écran voisin — tout cela change le résultat, et un chiffre mis
en cache dirait le contraire de ce que le produit applique.
"""

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from src.api.dependencies import get_data_loader
from src.core.data.loader import DataLoader
from src.core.knowledge.comptes_secondaires import Reglages, mesurer
from src.core.knowledge.population import droits_par_identite
from src.core.knowledge.privileges import denombrer
from src.core.security.auth import User, require_permission_or_dev

router = APIRouter(prefix="/privileges", tags=["Comptes à privilèges"])

#: Mesurer la convention lit les identités et les habilitations : un geste
#: d'analyste, comme la proposition du modèle qu'elle complète.
MESURE = "mining"

#: Colonnes désignant la personne. Au-delà, ce n'est plus une personne qu'on
#: désigne, c'est une ligne entière.
COLONNES_MAX = 10


@router.get("")
def denombrement(loader: DataLoader = Depends(get_data_loader)
                 ) -> Dict[str, Any]:
    """Ce que la déclaration marquerait, fragment par fragment.

    Rendu même quand rien n'est déclaré : `declare` vaut alors `false`, et
    l'écran dit qu'aucun compte n'est marqué parce que rien n'a été demandé.
    C'est une phrase différente de « aucun compte marqué », et les confondre
    laisserait croire à un référentiel sans compte d'administration.

    Aucune identité ne sort d'ici au-delà de l'échantillon, qui porte les
    valeurs de la colonne déclarée — celles-là mêmes que l'utilisateur lit
    déjà dans l'écran des identités. Le reste est du dénombrement.
    """
    resume = denombrer(loader.identities, loader.config.privileges,
                       DataLoader.COL_USER_ID)
    # La déclaration illisible se signale comme les autres du produit : la
    # lecture s'est poursuivie sans elle, et l'écran doit le dire plutôt que
    # de montrer un marqueur vide qui passerait pour un choix.
    resume["invalide"] = loader.config.privileges_invalide
    return resume


class DemandeDeMesure(BaseModel):
    """Les colonnes qui désignent la personne. Rien d'autre."""

    model_config = ConfigDict(extra="forbid")

    colonnes: List[str] = Field(..., min_length=1, max_length=COLONNES_MAX)


@router.post("/mesurer")
async def mesurer_la_convention(
    demande: DemandeDeMesure,
    loader: DataLoader = Depends(get_data_loader),
    user: User = Depends(require_permission_or_dev(MESURE)),
) -> Dict[str, Any]:
    """Les fragments qui distinguent le second compte d'une même personne.

    Les colonnes viennent de l'utilisateur : le produit ne sait pas lesquelles
    portent le nom et le prénom, et en choisir d'office regrouperait des gens
    que rien ne rapproche. Une colonne inconnue est refusée plutôt que lue
    vide — « aucune convention » se lirait comme un référentiel sans compte
    d'administration.
    """
    identites = loader.identities
    connues = [str(colonne) for colonne in identites.columns] \
        if identites is not None and not getattr(identites, "empty", True) else []
    for colonne in demande.colonnes:
        if colonne not in connues or colonne == DataLoader.COL_USER_ID:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "privileges.colonne_inconnue",
                        "params": {"colonne": colonne}})

    def _calculer() -> Dict[str, Any]:
        lignes = list(zip(identites[DataLoader.COL_USER_ID].astype(str),
                          identites[demande.colonnes].itertuples(index=False, name=None)))
        droits = droits_par_identite(loader.habilitations, DataLoader.COL_USER_ID,
                                     DataLoader.COL_RIGHT_ID)
        return mesurer(lignes, droits, Reglages.depuis_la_configuration(loader.config))

    return await run_in_threadpool(_calculer)
