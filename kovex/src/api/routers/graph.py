# src/api/routers/graph.py
"""
Graphe des accès, présenté en colonnes successives.

    Identités → Rôles métier → Rôles applicatifs → Droits → Applications

Chaque colonne est servie par une requête distincte, filtrée par la sélection
faite dans la colonne précédente et paginée. Rien n'est chargé d'avance : sur
un référentiel de 20 000 identités et 8 000 droits, un graphe complet n'est ni
calculable ni lisible. On descend la chaîne d'accès en la déroulant.

Historique des corrections portées par ce module
------------------------------------------------
- Les rôles étaient lus dans un fichier ``business_roles.json`` localisé via
  ``sys.path[0]`` : ceux que l'utilisateur venait de valider n'apparaissaient
  jamais. Ils viennent de la Knowledge Base du workspace.
- Le rattachement identité → rôle se faisait par test de sous-chaîne : un
  utilisateur dont l'attribut était absent recevait la chaîne vide, contenue
  dans n'importe quoi, et se retrouvait rattaché à **tous** les rôles.
  L'égalité est stricte, et un attribut manquant ne correspond à rien.
- L'application d'un droit était devinée en découpant son identifiant après
  retrait de préfixes propres à un client. Elle est lue dans le référentiel.

Ce module ne produit ni couleur ni libellé d'interface : il renvoie des
identifiants et des compteurs. La mise en forme appartient au client.
"""

import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from fastapi import APIRouter, Depends, HTTPException, Query, status
from starlette.concurrency import run_in_threadpool

from src.api.dependencies import get_data_loader, get_kb
from src.core.data.loader import DataLoader
from src.core.knowledge.knowledge_base import KnowledgeBase
from src.core.knowledge.travail_en_attente import (
    EN_ATTENTE as VERDICT_EN_ATTENTE,
    REJETE as VERDICT_REJETE,
    VALIDE as VERDICT_VALIDE,
    Referentiel,
    etat_des_candidats,
    verdict as verdict_du_candidat,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/graph", tags=["Graph"])

# --- Colonnes ------------------------------------------------------------
IDENTITE = "identity"
ROLE_METIER = "business_role"
ROLE_APPLICATIF = "application_role"
DROIT = "right"
APPLICATION = "application"

#: Ordre d'affichage des colonnes.
COLONNES = (IDENTITE, ROLE_METIER, ROLE_APPLICATIF, DROIT, APPLICATION)

#: Enchaînements autorisés : n'importe quelle colonne peut piloter n'importe
#: quelle autre, dans les deux sens. Sélectionner un rôle métier doit montrer
#: ses identités à gauche autant que ses applications à droite ; une chaîne
#: d'accès se lit dans les deux directions.
TRANSITIONS: Dict[str, Set[str]] = {
    cible: {source for source in COLONNES if source != cible} for cible in COLONNES
}

TYPE_ROLE_PAR_COLONNE = {ROLE_METIER: "METIER", ROLE_APPLICATIF: "APPLICATIF"}

# --- Origines d'un rôle --------------------------------------------------
# Ce sont les verdicts du module partagé, sous les noms du graphe : l'origine
# affichée d'un rôle *est* ce que le candidat est devenu. Les redéclarer ici
# ferait diverger l'étiquette du comptage à la première retouche.
#: Rôle accepté : il fait partie du modèle.
VALIDE = VERDICT_VALIDE
#: Candidat du dernier mining, ni accepté ni refusé. C'est l'« après » d'une
#: revue : ce que deviendrait le modèle si on l'acceptait.
SUGGERE = VERDICT_EN_ATTENTE
#: Candidat écarté. Utile pour justifier une revue — montrer qu'une piste a
#: été examinée et refusée, pas oubliée.
REJETE = VERDICT_REJETE

ORIGINES = (VALIDE, SUGGERE, REJETE)

#: Origine affichée par défaut : le comportement d'avant cette évolution.
ORIGINES_PAR_DEFAUT = (VALIDE,)


# --- Utilitaires de lecture des données ----------------------------------

def _application_par_droit(loader: DataLoader) -> Dict[str, str]:
    """Rattachement droit → application, lu dans le référentiel des droits."""
    referentiel = loader.rights
    if referentiel.empty:
        return {}
    if DataLoader.COL_RIGHT_ID not in referentiel.columns:
        return {}
    if DataLoader.COL_APP_ID not in referentiel.columns:
        logger.info("Référentiel des droits sans colonne application : "
                    "la colonne Applications restera vide.")
        return {}
    paires = referentiel[[DataLoader.COL_RIGHT_ID, DataLoader.COL_APP_ID]].dropna()
    return {str(d): str(a) for d, a in paires.itertuples(index=False)}


def _valeur_attribut(identite: Dict[str, Any], attribut: str) -> Optional[str]:
    """Valeur d'un attribut d'identité, ou None si absente ou vide.

    Retourner None plutôt qu'une chaîne vide est ce qui empêche une identité
    incomplète de correspondre à tous les rôles.
    """
    if attribut not in identite:
        return None
    valeur = identite[attribut]
    if valeur is None:
        return None
    texte = str(valeur).strip()
    if not texte or texte.lower() in ("nan", "none"):
        return None
    return texte


def _identite_correspond(identite: Dict[str, Any], criteres: Dict[str, Any]) -> bool:
    """Égalité stricte sur chaque critère du rôle, insensible à la casse."""
    for attribut, attendu in criteres.items():
        valeur = _valeur_attribut(identite, attribut)
        if valeur is None or valeur.casefold() != str(attendu).strip().casefold():
            return False
    return True


def _membres_par_regle_rh(role: Dict[str, Any],
                          identites: List[Dict[str, Any]]) -> Set[str]:
    """Identités satisfaisant la règle RH d'un rôle métier."""
    criteres = role.get("source_attributes") or {}
    membres = set()
    for identite in identites:
        if _identite_correspond(identite, criteres):
            identifiant = _valeur_attribut(identite, DataLoader.COL_USER_ID)
            if identifiant:
                membres.add(identifiant)
    return membres


def _droits_du_role(role: Dict[str, Any]) -> Set[str]:
    return {str(d) for d in (role.get("rights") or [])}


def _roles_applicatifs_du_role_metier(
    role_metier: Dict[str, Any], roles_applicatifs: List[Dict[str, Any]]
) -> Set[str]:
    """Rôles applicatifs composant un rôle métier.

    Les sous-rôles explicites sont pris en compte, et, à défaut, tout rôle
    applicatif dont les droits sont inclus dans ceux du rôle métier : c'est la
    hiérarchie que le mining ne renseigne pas encore, reconstituée à la lecture.
    """
    explicites = {str(s) for s in (role_metier.get("sub_roles") or [])}
    droits_metier = _droits_du_role(role_metier)

    composants = set()
    for role in roles_applicatifs:
        identifiant = str(role.get("id"))
        droits = _droits_du_role(role)
        if identifiant in explicites or (droits and droits <= droits_metier):
            composants.add(identifiant)
    return composants


def _habilitations_par_utilisateur(loader: DataLoader,
                                   utilisateurs: Optional[Set[str]]) -> Dict[str, Set[str]]:
    """Droits réellement détenus, éventuellement restreints à des identités."""
    habilitations = loader.habilitations
    if habilitations.empty:
        return {}
    colonnes = [DataLoader.COL_USER_ID, DataLoader.COL_RIGHT_ID]
    if any(c not in habilitations.columns for c in colonnes):
        return {}

    liens = habilitations[colonnes].dropna()
    if utilisateurs is not None:
        liens = liens[liens[DataLoader.COL_USER_ID].astype(str).isin(utilisateurs)]

    resultat: Dict[str, Set[str]] = {}
    for utilisateur, droit in liens.itertuples(index=False):
        resultat.setdefault(str(utilisateur), set()).add(str(droit))
    return resultat


# --- Construction d'une colonne ------------------------------------------

def _filtrer(elements: List[Dict[str, Any]], recherche: Optional[str]) -> List[Dict[str, Any]]:
    """Filtre une colonne sur son libellé et, pour les identités, sur leurs attributs.

    Chercher « Ropraz » doit trouver l'identité correspondante : sur un
    référentiel réel, personne ne connaît les identifiants techniques par cœur.
    """
    if not recherche:
        return elements

    motif = recherche.strip().casefold()

    def correspond(element: Dict[str, Any]) -> bool:
        if motif in element["label"].casefold():
            return True
        for attribut in element.get("meta", {}).get("attributes") or ():
            valeur = attribut.get("value")
            if valeur and motif in str(valeur).casefold():
                return True
        return False

    return [e for e in elements if correspond(e)]


def _origines_demandees(origins: Optional[List[str]]) -> Sequence[str]:
    """Valide les origines demandées.

    Une origine inconnue est refusée plutôt qu'ignorée : silencieusement
    écartée, elle produirait un graphe qui ne montre pas ce qu'on croit
    regarder, et rien ne le signalerait.
    """
    if not origins:
        return ORIGINES_PAR_DEFAUT

    demandees = [o for valeur in origins for o in str(valeur).split(",") if o]
    inconnues = sorted(set(demandees) - set(ORIGINES))
    if inconnues:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "graph.unknown_origin",
                    "params": {"origines": ", ".join(inconnues)}},
        )
    return tuple(dict.fromkeys(demandees))


def contexte_du_modele(loader: DataLoader, kb: KnowledgeBase, identites_df,
                       origines: Sequence[str] = ORIGINES) -> "_Contexte":
    """Contexte de lecture du modèle de rôles, réutilisable hors du graphe.

    L'export du modèle doit calculer les membres d'un rôle **exactement** comme
    le graphe : un rôle est une règle, pas une liste figée, et deux écrans qui
    appliqueraient deux règles différentes se contrediraient sur le nombre de
    porteurs. Plutôt que de recopier la règle, on expose le contexte qui la
    porte.
    """
    return _Contexte(loader, kb, identites_df, origines)


def _paginer(elements: List[Dict[str, Any]], offset: int, limit: int):
    return elements[offset:offset + limit], len(elements)


@router.get("/columns")
async def get_columns() -> Dict[str, Any]:
    """Ordre des colonnes et enchaînements autorisés.

    Exposé pour que le client n'ait pas à dupliquer le modèle : c'est le
    backend qui décrit la chaîne d'accès.
    """
    return {
        "columns": list(COLONNES),
        "transitions": {cible: sorted(sources) for cible, sources in TRANSITIONS.items()},
    }


@router.get("/roles-status")
async def get_roles_status(
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
) -> Dict[str, Any]:
    """État des rôles disponibles, par type et par origine.

    Sert au client à savoir ce qu'il peut afficher, et surtout **sur quoi**
    portent les candidats conservés : un mining calculé avant une modification
    des données reste consultable, mais comparer sans savoir sur quoi porte la
    comparaison est le piège à éviter sur un produit de gouvernance.
    """
    empreinte = await run_in_threadpool(loader.empreinte_donnees)
    etat: Dict[str, Any] = {"types": {}}

    for colonne, type_role in TYPE_ROLE_PAR_COLONNE.items():
        # Le verdict porté sur un candidat est celui du module partagé : le
        # graphe et l'indicateur de travail en attente doivent compter la même
        # chose. Comparé aux identifiants des rôles validés, comme ici
        # auparavant, un candidat accepté n'était jamais reconnu — l'identité
        # d'un rôle validé se dérive de ses droits *après* modification, et ne
        # coïncide donc avec celle du candidat que par accident.
        run = kb.get_candidate_run(type_role)
        etat_type = etat_des_candidats(kb, type_role, empreinte)

        etat["types"][colonne] = {
            "validated": len(kb.get_validated_roles(role_type=type_role)),
            "suggested": etat_type.en_attente,
            "rejected": etat_type.refuses,
            "computed_at": etat_type.calcule_le,
            "params": run.get("params") if run else {},
            # Un mining conservé peut porter sur des données depuis modifiées.
            # On le dit ; on ne masque pas, et on ne se tait pas non plus.
            "stale": etat_type.obsolete,
        }

    return etat


@router.get("/layer")
async def get_layer(
    layer: str = Query(..., description="Colonne demandée"),
    limit: int = Query(..., ge=1, le=500, description="Nombre d'éléments par page"),
    offset: int = Query(0, ge=0),
    parent_layer: Optional[str] = Query(None, description="Colonne de la sélection amont"),
    parents: Optional[List[str]] = Query(None, description="Identifiants sélectionnés en amont"),
    search: Optional[str] = Query(None, description="Filtre sur le libellé"),
    origins: Optional[List[str]] = Query(
        None,
        description="Origines des rôles à inclure : validated, suggested, rejected. "
                    "Par défaut, les rôles validés seuls.",
    ),
    uncovered_only: bool = Query(
        False,
        description="Colonne des droits : ne rendre que les droits qu'aucun rôle "
                    "des origines demandées n'explique.",
    ),
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
) -> Dict[str, Any]:
    """Retourne une colonne du graphe, filtrée par la sélection amont.

    `links` porte les liaisons entre les éléments sélectionnés en amont et ceux
    de la colonne retournée : le client dessine les connecteurs sans avoir à
    refaire le calcul.
    """
    if layer not in COLONNES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "graph.unknown_layer", "params": {"layer": layer}},
        )
    if (parent_layer is None) != (not parents):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "graph.incomplete_selection"},
        )
    if parent_layer is not None and parent_layer not in TRANSITIONS.get(layer, set()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "graph.invalid_transition",
                    "params": {"from": parent_layer, "to": layer}},
        )

    identites_df = loader.identities
    if identites_df.empty and loader.habilitations.empty:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "mining.no_data_loaded"},
        )

    origines = _origines_demandees(origins)
    contexte = _Contexte(loader, kb, identites_df, origines)
    selection = set(parents or ())

    elements, liens = contexte.construire(layer, parent_layer, selection)
    if uncovered_only:
        if layer != DROIT:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "graph.uncovered_only_rights"},
            )
        elements = contexte.droits_non_couverts(elements)
    elements = _filtrer(elements, search)
    elements.sort(key=lambda e: e["label"])
    page, total = _paginer(elements, offset, limit)

    identifiants_page = {e["id"] for e in page}
    liens_page = [l for l in liens if l["to"] in identifiants_page]

    logger.debug("Colonne %s : %d éléments (page %d-%d sur %d), %d liaisons",
                 layer, len(page), offset, offset + len(page), total, len(liens_page))

    return {
        "layer": layer,
        "items": page,
        "links": sorted(liens_page, key=lambda l: (l["from"], l["to"])),
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(page) < total,
    }


class _Perimetre:
    """Identités et droits désignés par une sélection, quelle que soit sa colonne.

    Les droits se comptent en deux tas, et les confondre serait le pire défaut
    que cet écran puisse avoir :

    - `droits` : ce qui est **détenu**, lu dans les habilitations ;
    - `droits_du_modele` : ce que les rôles du périmètre **accorderaient** à ces
      identités sans qu'elles le détiennent aujourd'hui.

    Sélectionner une personne ne montrait que le premier tas. Un rôle métier qui
    la désigne mais dont il lui manque des droits n'apparaissait donc qu'à
    moitié : la règle était là, ce qu'elle lui donnerait n'y était pas. C'est
    pourtant la question d'une revue d'accès — non pas « qu'a-t-elle ? », mais
    « qu'aurait-elle si l'on appliquait ce modèle ? ».
    """

    __slots__ = ("identites", "droits", "droits_du_modele")

    def __init__(self, identites: Set[str], droits: Set[str],
                 droits_du_modele: Optional[Set[str]] = None):
        self.identites = identites
        self.droits = droits
        #: Jamais mêlés aux détenus : c'est la marque portée par l'élément qui
        #: dit lequel des deux on regarde.
        self.droits_du_modele = (droits_du_modele or set()) - droits

    @property
    def tous_les_droits(self) -> Set[str]:
        return self.droits | self.droits_du_modele


class _Contexte:
    """Accès paresseux aux données nécessaires à une colonne."""

    def __init__(self, loader: DataLoader, kb: KnowledgeBase, identites_df,
                 origines: Sequence[str] = ORIGINES_PAR_DEFAUT):
        self.loader = loader
        self.kb = kb
        # Origines demandées pour toute la requête. Les porter sur le contexte
        # plutôt que de les passer aux sept endroits qui lisent les rôles
        # évite qu'un de ces endroits les oublie et rende un graphe
        # partiellement filtré, ce qui serait indétectable à l'œil.
        self.origines = tuple(origines)
        self._identites_df = identites_df
        self._identites: Optional[List[Dict[str, Any]]] = None
        self._roles: Dict[str, List[Dict[str, Any]]] = {}
        self._applications: Optional[Dict[str, str]] = None
        self._detenteurs: Optional[Dict[str, Set[str]]] = None
        self._socles: Optional[Set[str]] = None

    # -- Données de base --------------------------------------------------

    @property
    def socles(self) -> Set[str]:
        """Droits socles du workspace.

        Le graphe les ignorait entièrement — aucune occurrence dans ce module.
        Il en résultait deux dénominateurs pour la même personne : sur le
        chemin identité → droits ils apparaissaient mêlés aux autres, sur le
        chemin rôle → droits ils étaient absents, puisqu'ils sont exclus du
        mining. La même identité semblait donc détenir des droits que « son »
        rôle n'expliquait pas, sans qu'un mot ne dise pourquoi.

        Les marquer ne les retire pas : le client décide de les replier, de les
        compter à part ou de les montrer.
        """
        if self._socles is None:
            self._socles = {str(d) for d in (self.kb.get_birth_rights() or ())}
        return self._socles

    @property
    def identites(self) -> List[Dict[str, Any]]:
        if self._identites is None:
            self._identites = (
                self._identites_df.to_dict("records") if not self._identites_df.empty else []
            )
        return self._identites

    def roles(self, colonne: str,
              origines: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        """Rôles d'une colonne, pour les origines demandées.

        Chaque rôle est marqué de son origine : le client peut ainsi
        distinguer visuellement l'existant du proposé sans refaire le tri.

        Un rôle validé n'est jamais aussi rendu comme suggéré : une fois
        accepté, il fait partie du modèle, il n'est plus une proposition.
        """
        origines = tuple(origines) if origines is not None else self.origines
        cle = (colonne, tuple(sorted(origines)))
        if cle in self._roles:
            return self._roles[cle]

        type_role = TYPE_ROLE_PAR_COLONNE[colonne]
        valides = self.kb.get_validated_roles(role_type=type_role)

        resultat: List[Dict[str, Any]] = []
        if VALIDE in origines:
            resultat += [{**r, "_origine": VALIDE} for r in valides]

        if SUGGERE in origines or REJETE in origines:
            referentiel = Referentiel.depuis(self.kb, type_role)
            for candidat in self.kb.get_candidate_roles(type_role):
                origine = verdict_du_candidat(candidat, referentiel)
                # Un candidat accepté est déjà présent sous son rôle validé :
                # le rajouter le compterait deux fois.
                if origine == VALIDE:
                    continue
                if origine in origines:
                    resultat.append({**candidat, "_origine": origine})

        self._roles[cle] = resultat
        return resultat

    @property
    def detenteurs_par_droit(self) -> Dict[str, Set[str]]:
        """Index droit → identités qui le détiennent, construit une seule fois."""
        if self._detenteurs is None:
            self._detenteurs = {}
            for utilisateur, droits in _habilitations_par_utilisateur(self.loader, None).items():
                for droit in droits:
                    self._detenteurs.setdefault(droit, set()).add(utilisateur)
        return self._detenteurs

    def membres(self, role: Dict[str, Any]) -> Set[str]:
        """Identités relevant d'un rôle.

        Un rôle est une **règle**, pas une liste figée, et ses membres se
        déduisent des données du moment :

        - rôle métier : la règle porte sur les attributs RH (`source_attributes`) ;
        - rôle applicatif : la règle porte sur les droits — en relèvent les
          identités qui détiennent l'intégralité des droits du rôle.

        Le second cas est ce qui manquait. La liste des membres produite par le
        mining n'était pas persistée à la validation (le modèle `RoleCreate`
        ne déclare pas de champ `users`, le frontend l'envoyait et il était
        écarté sans bruit) : les rôles applicatifs validés ne portaient qu'un
        compteur. Les recalculer les relie de nouveau à leurs identités, y
        compris pour les rôles déjà enregistrés, et sans risque de péremption
        quand l'annuaire évolue. C'est la même définition que celle utilisée
        pour calculer `user_count`.
        """
        if role.get("source_attributes"):
            return _membres_par_regle_rh(role, self.identites)

        explicites = {str(u) for u in (role.get("users") or [])}
        if explicites:
            return explicites

        droits = _droits_du_role(role)
        if not droits:
            return set()

        index = self.detenteurs_par_droit
        membres = index.get(next(iter(droits)), set())
        for droit in droits:
            membres = membres & index.get(droit, set())
            if not membres:
                break
        return set(membres)

    @property
    def applications(self) -> Dict[str, str]:
        if self._applications is None:
            self._applications = _application_par_droit(self.loader)
        return self._applications

    # -- Construction d'une colonne ---------------------------------------

    def construire(self, layer, parent_layer, selection):
        """Retourne les éléments d'une colonne et leurs liaisons avec l'amont.

        La sélection est d'abord traduite en un périmètre — les identités et
        les droits qu'elle désigne — puis ce périmètre est projeté sur la
        colonne demandée. C'est ce qui permet de piloter n'importe quelle
        colonne depuis n'importe quelle autre : sélectionner un rôle métier
        remonte ses identités comme il descend ses applications.
        """
        if parent_layer is None:
            return self._catalogue(layer), []

        perimetre = self._perimetre(parent_layer, selection)
        return self._projeter(layer, parent_layer, selection, perimetre)

    # -- Catalogue complet d'une colonne ----------------------------------

    def _catalogue(self, layer) -> List[Dict[str, Any]]:
        if layer == IDENTITE:
            return self._identites_colonne()
        if layer in TYPE_ROLE_PAR_COLONNE:
            return [self._element_role(r) for r in self.roles(layer)]
        if layer == DROIT:
            return [self._element_droit(d) for d in self._tous_les_droits()]
        return [{"id": a, "label": a, "meta": {}} for a in set(self.applications.values())]

    def _identites_colonne(self) -> List[Dict[str, Any]]:
        """Colonne des identités, chacune accompagnée de ses attributs.

        Les colonnes du référentiel ne sont pas connues à l'avance : on les
        transmet toutes, dans l'ordre du fichier, sans en présumer aucune. Un
        attribut vide est renvoyé à `None` plutôt qu'omis — savoir qu'un champ
        n'est pas renseigné est une information à part entière dans une revue
        d'accès.
        """
        attributs = [c for c in self._identites_df.columns if c != DataLoader.COL_USER_ID]

        elements = []
        for identite in self.identites:
            identifiant = _valeur_attribut(identite, DataLoader.COL_USER_ID)
            if identifiant is None:
                continue
            elements.append({
                "id": identifiant,
                "label": identifiant,
                "meta": {
                    "attributes": [
                        {"name": attribut, "value": _valeur_attribut(identite, attribut)}
                        for attribut in attributs
                    ]
                },
            })
        return elements

    def _element_role(self, role: Dict[str, Any]) -> Dict[str, Any]:
        identifiant = str(role.get("id"))
        return {
            "id": identifiant,
            "label": str(role.get("name") or identifiant),
            "meta": {
                "role_type": role.get("role_type"),
                "right_count": len(role.get("rights") or []),
                "user_count": role.get("user_count"),
                # Le client distingue l'existant du proposé sur cette seule
                # valeur : il n'a pas à deviner d'où vient un rôle.
                "origin": role.get("_origine", VALIDE),
                # Détenu sauf mention contraire — voir `_element_droit`. Le
                # faux est réservé à ce que le modèle apporterait.
                "detenu": True,
            },
        }

    def droits_non_couverts(self, elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Droits qu'aucun rôle des origines demandées n'explique.

        C'est la mesure directe de ce qui reste à faire — ce que ni l'avant ni
        l'après d'une revue ne montrent : un modèle peut paraître complet parce
        qu'on ne regarde que les rôles, et laisser des milliers d'habilitations
        sans explication.
        """
        couverts: Set[str] = set()
        for colonne in TYPE_ROLE_PAR_COLONNE:
            for role in self.roles(colonne):
                couverts |= {str(d) for d in (role.get("rights") or [])}
        return [e for e in elements if e["id"] not in couverts]

    def _element_droit(self, droit: str, detenu: bool = True) -> Dict[str, Any]:
        return {"id": droit, "label": droit,
                # Détenu sauf mention contraire : c'est le cas de tous les
                # droits que le graphe rendait jusqu'ici, et l'absence de marque
                # ne doit pas se lire comme une incertitude.
                "meta": {"detenu": detenu,
                         "application": self.applications.get(droit),
                         # Un droit socle est détenu par la quasi-totalité de
                         # la population : il est exclu du mining, donc absent
                         # des rôles, mais bien présent sur les identités.
                         "socle": droit in self.socles}}

    def _tous_les_droits(self) -> Set[str]:
        droits = set(self.applications)
        habilitations = self.loader.habilitations
        if DataLoader.COL_RIGHT_ID in habilitations.columns:
            droits |= {str(d) for d in habilitations[DataLoader.COL_RIGHT_ID].dropna().unique()}
        return droits

    # -- Périmètre désigné par une sélection --------------------------------

    def _perimetre(self, parent_layer, selection) -> "_Perimetre":
        """Traduit une sélection en identités et en droits concernés."""
        if parent_layer == IDENTITE:
            identites = set(selection)
            droits = set()
            for ses_droits in _habilitations_par_utilisateur(self.loader, identites).values():
                droits |= ses_droits
            return _Perimetre(identites, droits, self._droits_accordes(identites))

        if parent_layer in TYPE_ROLE_PAR_COLONNE:
            identites, droits = set(), set()
            for role in self.roles(parent_layer):
                if str(role.get("id")) not in selection:
                    continue
                identites |= self.membres(role)
                droits |= _droits_du_role(role)
            return _Perimetre(identites, droits)

        if parent_layer == DROIT:
            droits = set(selection)
        else:
            droits = {d for d, a in self.applications.items() if a in selection}

        identites = {
            utilisateur
            for utilisateur, ses_droits in _habilitations_par_utilisateur(self.loader, None).items()
            if ses_droits & droits
        }
        return _Perimetre(identites, droits)

    def _roles_qui_designent(self, identites: Set[str]) -> List[Dict[str, Any]]:
        """Rôles du modèle qui s'appliquent à ces identités.

        « S'applique » n'est pas « est détenu ». Un rôle métier désigne une
        personne dès que sa règle RH la vise, qu'elle en détienne les droits ou
        non — c'est même le cas intéressant. Un rôle applicatif la concerne s'il
        la compte parmi ses porteurs **ou** s'il compose l'un de ses rôles
        métier : appliquer le rôle métier lui apporterait ce rôle-là aussi.

        Seules les origines cochées entrent dans le calcul. Sans cela,
        sélectionner une personne ferait apparaître ce que mille sept cent
        cinquante candidats non décidés lui donneraient, ce qui n'est le modèle
        de personne.
        """
        metiers = [role for role in self.roles(ROLE_METIER)
                   if self.membres(role) & identites]
        applicatifs = self.roles(ROLE_APPLICATIF)

        composants: Set[str] = set()
        for metier in metiers:
            composants |= _roles_applicatifs_du_role_metier(metier, applicatifs)

        concernes = [role for role in applicatifs
                     if str(role.get("id")) in composants
                     or self.membres(role) & identites]
        return metiers + concernes

    def _droits_accordes(self, identites: Set[str]) -> Set[str]:
        """Droits que les rôles désignant ces identités leur accorderaient."""
        droits: Set[str] = set()
        for role in self._roles_qui_designent(identites):
            droits |= _droits_du_role(role)
        return droits

    # -- Projection du périmètre sur la colonne demandée --------------------

    def _projeter(self, layer, parent_layer, selection, perimetre):
        if layer == IDENTITE:
            return self._projeter_identites(parent_layer, selection, perimetre)
        if layer in TYPE_ROLE_PAR_COLONNE:
            return self._projeter_roles(layer, parent_layer, selection, perimetre)
        if layer == DROIT:
            return self._projeter_droits(parent_layer, selection, perimetre)
        return self._projeter_applications(parent_layer, selection, perimetre)

    def _projeter_identites(self, parent_layer, selection, perimetre):
        elements = [{"id": u, "label": u, "meta": {}} for u in perimetre.identites]
        liens = self._liens_vers_identites(parent_layer, selection, perimetre)
        return elements, liens

    def _liens_vers_identites(self, parent_layer, selection, perimetre):
        """Liaisons amont → identité, orientées de la sélection vers la colonne."""
        if parent_layer in TYPE_ROLE_PAR_COLONNE:
            liens = []
            for role in self.roles(parent_layer):
                identifiant = str(role.get("id"))
                if identifiant not in selection:
                    continue
                membres = self.membres(role)
                detenus = _habilitations_par_utilisateur(self.loader, membres)
                droits = _droits_du_role(role)
                # Ce que le rôle ajouterait à cette personne-là. C'est la même
                # question que sur le lien vers les droits, posée par identité
                # plutôt que par droit : « à qui ce rôle donne-t-il quelque
                # chose de nouveau, et combien ».
                liens.extend({
                    "from": identifiant, "to": membre,
                    "meta": {"nouveaux": len(droits - detenus.get(membre, set()))},
                } for membre in membres)
            return liens

        # Sélection de droits ou d'applications : le lien passe par les
        # habilitations réellement détenues.
        droits_selection = perimetre.droits
        liens = []
        for utilisateur, ses_droits in _habilitations_par_utilisateur(
            self.loader, perimetre.identites
        ).items():
            # Le périmètre ne retient que les détenteurs des droits
            # sélectionnés : l'intersection n'est jamais vide ici.
            concernes = ses_droits & droits_selection
            if parent_layer == DROIT:
                liens.extend({"from": d, "to": utilisateur} for d in concernes & set(selection))
            else:
                liens.extend({"from": a, "to": utilisateur}
                             for a in {self.applications.get(d) for d in concernes} & set(selection))
        return liens

    def _projeter_roles(self, layer, parent_layer, selection, perimetre):
        roles = self.roles(layer)
        elements, liens = [], []

        # Rôles applicatifs que les rôles métier du périmètre apporteraient,
        # calculés une fois : la boucle qui suit les interroge par rôle.
        portes_par_le_modele: Set[str] = set()
        if layer == ROLE_APPLICATIF and parent_layer == IDENTITE:
            for metier in self.roles(ROLE_METIER):
                if self.membres(metier) & perimetre.identites:
                    portes_par_le_modele |= _roles_applicatifs_du_role_metier(
                        metier, roles)

        for role in roles:
            identifiant = str(role.get("id"))
            membres = self.membres(role)
            droits = _droits_du_role(role)

            if parent_layer == IDENTITE:
                communs = membres & perimetre.identites
                if not communs:
                    # Un rôle applicatif dont ces identités ne détiennent pas
                    # tous les droits n'en compte aucune parmi ses porteurs. Il
                    # les concerne pourtant s'il compose l'un de leurs rôles
                    # métier : appliquer ce rôle métier le leur apporterait.
                    # C'est le maillon qui manquait à la chaîne « identité →
                    # rôle métier → rôle applicatif → droits ».
                    if identifiant not in portes_par_le_modele:
                        continue
                    liens.extend({"from": m, "to": identifiant,
                                  "meta": {"detenu": False}}
                                 for m in sorted(perimetre.identites))
                else:
                    liens.extend({"from": m, "to": identifiant} for m in communs)
            elif parent_layer in TYPE_ROLE_PAR_COLONNE:
                origines = self._roles_lies(parent_layer, selection, role, layer)
                if not origines:
                    continue
                liens.extend({"from": o, "to": identifiant} for o in origines)
            elif parent_layer == DROIT:
                communs = droits & perimetre.droits & set(selection)
                if not communs:
                    continue
                liens.extend({"from": d, "to": identifiant} for d in communs)
            else:
                applications = {self.applications.get(d) for d in droits} & set(selection)
                if not applications:
                    continue
                liens.extend({"from": a, "to": identifiant} for a in applications)

            element = self._element_role(role)
            if layer == ROLE_APPLICATIF and parent_layer == IDENTITE \
                    and not (membres & perimetre.identites):
                element["meta"]["detenu"] = False
            elements.append(element)

        return elements, liens

    def _roles_lies(self, parent_layer, selection, role, layer) -> Set[str]:
        """Rôles sélectionnés liés au rôle candidat, dans un sens ou dans l'autre.

        Un rôle applicatif compose un rôle métier lorsqu'il figure dans ses
        sous-rôles ou que ses droits y sont inclus — la hiérarchie que le
        mining ne renseigne pas encore, reconstituée à la lecture.
        """
        identifiant = str(role.get("id"))
        origines = set()
        for origine in self.roles(parent_layer):
            identifiant_origine = str(origine.get("id"))
            if identifiant_origine not in selection:
                continue
            if parent_layer == ROLE_METIER:
                composants = _roles_applicatifs_du_role_metier(origine, [role])
                if identifiant in composants:
                    origines.add(identifiant_origine)
            else:
                composants = _roles_applicatifs_du_role_metier(role, [origine])
                if identifiant_origine in composants:
                    origines.add(identifiant_origine)
        return origines

    def _projeter_droits(self, parent_layer, selection, perimetre):
        elements = [self._element_droit(d) for d in perimetre.droits]
        # Ce que le modèle accorderait en plus. Marqué, jamais fondu dans les
        # droits détenus : la question d'une revue d'accès n'est pas
        # « qu'a-t-elle ? » mais « qu'aurait-elle si l'on appliquait ce
        # modèle ? », et les deux réponses ne se lisent pas de la même façon.
        elements += [self._element_droit(d, detenu=False)
                     for d in perimetre.droits_du_modele]
        liens = []

        if parent_layer == IDENTITE:
            detenus = _habilitations_par_utilisateur(self.loader, perimetre.identites)
            for utilisateur, ses_droits in detenus.items():
                liens.extend({"from": utilisateur, "to": d} for d in ses_droits)
            # Un droit non détenu reste rattaché à qui le recevrait : sans
            # lien, l'élément flotterait dans la colonne sans qu'on sache de
            # quelle personne il relève. Le compte porté par le lien est celui
            # que la colonne annonce déjà — « recevraient ».
            for utilisateur in sorted(perimetre.identites):
                siens = detenus.get(utilisateur, set())
                liens.extend({"from": utilisateur, "to": droit,
                              "meta": {"detenteurs": 0, "nouveaux": 1}}
                             for droit in sorted(perimetre.droits_du_modele)
                             if droit not in siens)
        elif parent_layer in TYPE_ROLE_PAR_COLONNE:
            for role in self.roles(parent_layer):
                identifiant = str(role.get("id"))
                if identifiant in selection:
                    liens.extend(self._liens_du_role_vers_ses_droits(role))
        elif parent_layer == APPLICATION:
            liens = [{"from": self.applications[d], "to": d}
                     for d in perimetre.droits if d in self.applications]

        return elements, liens

    def _liens_du_role_vers_ses_droits(self, role) -> List[Dict[str, Any]]:
        """Liens rôle → droit, chacun portant ce qu'il apporte et ce qu'il coûte.

        Le graphe construisait des couples `{from, to}` nus. Il montrait donc
        ce qu'un rôle apporte sans montrer ce qu'il accorde **en trop** — sur
        l'écran le plus visuel du produit, celui qu'un comité regarde en
        réunion. Afficher le gain sans son coût est précisément le reproche que
        ce produit adresse aux outils du marché.

        Deux nombres par lien, et rien de plus :

        - `detenteurs` : membres du rôle qui possèdent déjà ce droit ;
        - `nouveaux` : membres qui le recevraient.

        Le produit ne juge pas. Un droit accordé à trois personnes qui ne
        l'avaient pas corrige peut-être un sous-provisionnement ; c'est au
        valideur de le dire. Le rôle du graphe est de rendre le nombre
        visible, pas de le colorer en rouge.

        Le calcul n'est fait que pour les rôles **sélectionnés** : il coûte
        `membres × droits`, ce qui est négligeable pour quelques rôles et
        ruineux pour une colonne entière.
        """
        membres = self.membres(role)
        detenus = _habilitations_par_utilisateur(self.loader, membres)
        effectif = len(membres)

        liens = []
        for droit in sorted(_droits_du_role(role)):
            porteurs = sum(1 for identite in membres
                           if droit in detenus.get(identite, ()))
            liens.append({
                "from": str(role.get("id")), "to": droit,
                "meta": {"detenteurs": porteurs, "nouveaux": effectif - porteurs},
            })
        return liens

    def _projeter_applications(self, parent_layer, selection, perimetre):
        applications = self.applications
        retenues = {applications[d] for d in perimetre.tous_les_droits
                    if d in applications}
        elements = [{"id": a, "label": a, "meta": {}} for a in retenues]
        liens = []

        if parent_layer == DROIT:
            liens = [{"from": d, "to": applications[d]}
                     for d in selection if d in applications]
        elif parent_layer in TYPE_ROLE_PAR_COLONNE:
            for role in self.roles(parent_layer):
                identifiant = str(role.get("id"))
                if identifiant not in selection:
                    continue
                liens.extend({"from": identifiant, "to": applications[d]}
                             for d in _droits_du_role(role) if d in applications)
        elif parent_layer == IDENTITE:
            for utilisateur, ses_droits in _habilitations_par_utilisateur(
                self.loader, perimetre.identites
            ).items():
                liens.extend({"from": utilisateur, "to": applications[d]}
                             for d in ses_droits if d in applications)

        return elements, liens
