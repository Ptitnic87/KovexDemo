# Fichier : src/api/lignes.py
"""Les lignes d'un référentiel, restreintes à un ensemble d'identifiants.

Un rôle ne contient que des identifiants : `U0042`, `D_FIN_0042`. C'est la
seule colonne que le produit connaisse par construction, et c'est justement
celle qui ne dit rien. Tout écran qui montre le contenu d'un rôle doit donc
aller chercher les *autres* colonnes — celles du fichier du client, dont le
code ne connaît aucun nom — et les paginer.

Ce module porte cette opération une fois pour toutes. Elle servait la fenêtre
de validation ; elle sert aussi la fenêtre de détail d'un rôle du catalogue,
qui affichait ses porteurs sous forme de liste d'identifiants — « 100 porteurs
affichés sur 6 269 », sans recherche, sans tri, et sans la moindre colonne
permettant de reconnaître quelqu'un.

La règle qui justifie de partager le code plutôt que de le recopier : **un
identifiant inconnu du référentiel est rendu quand même**, avec ce seul champ
rempli. Deux écrans qui traiteraient différemment un porteur orphelin
diraient deux choses différentes sur le même rôle.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from src.core.data.loader import DataLoader
from src.core.knowledge.privileges import Marqueur, marques_parmi

#: Plafond du nombre d'identifiants d'une demande. Ce n'est pas une borne
#: métier — un rôle peut légitimement compter des milliers de porteurs — mais
#: une borne sur la taille d'une requête que l'API accepte.
IDENTIFIANTS_MAX = 100_000

#: Bornes de pagination. Une page sans plafond rendrait le tableau aussi lent
#: que la liste qu'il remplace.
TAILLE_DE_PAGE_MAX = 500

#: Référentiels dont on sait extraire des lignes par identifiant, et la
#: colonne qui porte cet identifiant après normalisation.
#:
#: Les *autres* colonnes ne figurent pas ici, et c'est la règle du produit :
#: elles viennent des fichiers du client, le code n'en connaît aucune.
REFERENTIELS_DE_LIGNES: Dict[str, Tuple[Callable[[DataLoader], Any], str]] = {
    "identities": (lambda loader: loader.identities, DataLoader.COL_USER_ID),
    "rights": (lambda loader: loader.rights, DataLoader.COL_RIGHT_ID),
}


class PaginatedResponse(BaseModel):
    total_items: int
    total_pages: int
    current_page: int
    page_size: int
    data: List[Dict[str, Any]]
    #: Colonne qui porte l'identifiant. Le client s'en sert pour rattacher une
    #: ligne à la sélection et pour savoir quelle cellule nomme l'identité ;
    #: la deviner serait présumer un nom de colonne.
    colonne_identifiant: str = ""
    #: Ceux des identifiants **de cette page** qui portent la marque de compte
    #: à privilèges. Rendus à part, et non ajoutés comme une colonne aux
    #: lignes : les colonnes viennent du fichier du client, et en inventer une
    #: écraserait celle qui porterait ce nom chez lui.
    #:
    #: Vide quand rien n'est déclaré, et vide sur un référentiel qui n'est pas
    #: celui des identités — un droit n'est pas un compte.
    comptes_a_privileges: List[str] = []


class Pagination(BaseModel):
    """Ce que demande un tableau : une page, un tri, une recherche.

    Les écrans qui montrent le contenu d'un rôle envoient tous cela, et rien
    d'autre. Le corps de requête est fermé (`extra="forbid"`) : un champ mal
    orthographié doit être refusé, pas ignoré — un tri silencieusement perdu
    se lit comme un défaut du tri, pas comme une faute d'appel.
    """

    model_config = ConfigDict(extra="forbid")

    page: int = Field(1, ge=1)
    size: int = Field(50, ge=1, le=TAILLE_DE_PAGE_MAX)
    search: Optional[str] = Field(None, max_length=200)
    sort_col: Optional[str] = Field(None, max_length=200)
    sort_desc: bool = False


class LignesDemandees(Pagination):
    """Une demande **sans état** : les identifiants viennent du client.

    Il vient de les obtenir du mining, et le serveur ne garde aucun résultat
    d'une requête à l'autre — même principe que l'explication d'un rôle.

    Ils passent par le corps et non par l'adresse : un rôle de trois mille
    porteurs ne tient pas dans une chaîne de requête.
    """

    identifiants: List[str] = Field(default_factory=list,
                                    max_length=IDENTIFIANTS_MAX)


class LignesRendues(PaginatedResponse):
    """Les lignes, et ce qu'il faut pour les afficher sans rien présumer."""

    #: Colonnes du référentiel, dans leur ordre. Rendues même quand la page
    #: est vide : sans elles, un tableau filtré à zéro ligne perdrait ses
    #: en-têtes, et l'utilisateur ne saurait plus sur quoi il cherche.
    colonnes: List[str] = []
    #: Identifiants demandés que le référentiel ne connaît pas. Ils sont rendus
    #: quand même, avec ce seul champ rempli.
    inconnus: List[str] = []


def process_dataframe(df: pd.DataFrame, page: int, size: int, search: str = None,
                      sort_col: str = None, sort_asc: bool = True,
                      colonne: str = "",
                      marqueur: Optional[Marqueur] = None) -> PaginatedResponse:
    """Filtre, trie puis pagine un tableau de données.

    `marqueur` n'est passé que par les routes qui rendent des **identités** :
    le marquage se fait donc à un seul endroit, après la pagination et sur la
    seule page rendue. Le faire dans chaque route l'aurait fait diverger — et
    deux tableaux qui diraient deux choses du même compte sont exactement ce
    que la règle « un chiffre, une définition » existe pour empêcher.
    """
    if df.empty:
        return PaginatedResponse(total_items=0, total_pages=0, current_page=1,
                                 page_size=size, data=[],
                                 colonne_identifiant=colonne)

    df = df.copy()

    # 1. FILTRAGE (RECHERCHE GLOBALE)
    if search:
        search = search.lower()
        mask = df.astype(str).apply(
            lambda x: x.str.lower().str.contains(search, na=False)).any(axis=1)
        df = df[mask]

    # 2. TRI
    if sort_col and sort_col in df.columns:
        try:
            df = df.sort_values(by=sort_col, ascending=sort_asc,
                                key=lambda x: pd.to_numeric(x, errors='ignore'))
        except Exception:
            df = df.sort_values(by=sort_col, ascending=sort_asc)

    # 3. PAGINATION
    total_items = len(df)
    total_pages = (total_items + size - 1) // size

    if page < 1:
        page = 1
    if page > total_pages and total_pages > 0:
        page = total_pages

    start = (page - 1) * size
    chunk = df.iloc[start:start + size].fillna("")

    lignes = chunk.to_dict(orient="records")
    return PaginatedResponse(
        total_items=total_items,
        total_pages=total_pages,
        current_page=page,
        page_size=size,
        data=lignes,
        colonne_identifiant=colonne,
        comptes_a_privileges=(
            marques_parmi(lignes, marqueur, colonne, df.columns)
            if marqueur is not None and colonne else []),
    )


def restreindre_puis_paginer(df: pd.DataFrame, colonne: str,
                             identifiants: Sequence[str],
                             demande: Pagination,
                             marqueur: Optional[Marqueur] = None
                             ) -> LignesRendues:
    """Les lignes du référentiel qui portent ces identifiants.

    **Un identifiant inconnu est rendu quand même**, avec sa seule colonne
    d'identifiant. C'est le point délicat : dans la fenêtre de validation,
    cette liste décide de ce qui sera validé, et un droit orphelin — présent
    dans les habilitations, absent du référentiel des droits — disparaîtrait
    silencieusement du rôle. Dans la fenêtre de détail, il change le compte de
    porteurs affiché : le taire ferait mentir un chiffre.
    """
    colonnes = list(df.columns) if not df.empty else [colonne]
    if colonne not in colonnes:
        # Un référentiel chargé sans sa colonne d'identifiant ne permet aucun
        # rapprochement. Le dire plutôt que de rendre des lignes vides.
        colonnes = [colonne] + colonnes

    demandes = list(dict.fromkeys(str(identifiant) for identifiant in identifiants))
    connues = pd.DataFrame(columns=colonnes)
    if not df.empty and colonne in df.columns:
        cles = df[colonne].astype(str)
        connues = df[cles.isin(demandes)].copy()
        connues[colonne] = cles[cles.isin(demandes)]

    trouves = set(connues[colonne].astype(str)) if not connues.empty else set()
    inconnus = [identifiant for identifiant in demandes if identifiant not in trouves]
    if inconnus:
        # Reconstruites ligne à ligne plutôt que par concaténation d'un
        # DataFrame vide : `concat` sur un cadre sans colonnes typées rend des
        # colonnes flottantes, et les identifiants s'afficheraient en nombres.
        manquantes = pd.DataFrame([{**{col: "" for col in colonnes},
                                    colonne: identifiant}
                                   for identifiant in inconnus])
        connues = pd.concat([connues, manquantes], ignore_index=True) \
            if not connues.empty else manquantes

    rendu = process_dataframe(connues.reindex(columns=colonnes), demande.page,
                              demande.size, demande.search, demande.sort_col,
                              not demande.sort_desc, colonne, marqueur)
    return LignesRendues(**rendu.dict(), colonnes=colonnes, inconnus=inconnus)
