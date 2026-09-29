# src/api/routers/mining_metiers.py
"""
Routeur du mining métier.

Découvre des rôles à partir des attributs RH des identités : pour un groupe
d'identités partageant les mêmes valeurs d'attributs, on retient les droits
détenus par au moins `min_coverage` % du groupe.

Comme pour le mining applicatif, la Knowledge Base du workspace filtre les
droits socles et les rôles déjà validés, et chaque exécution est historisée.
"""

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from src.api import schemas
from src.api.dependencies import get_data_loader, get_kb
from src.api.journal import Journal, get_journal
from src.api.routers.roles import consigner_la_creation
from src.core.data.loader import DataLoader
from src.core.knowledge.knowledge_base import KnowledgeBase
from src.core.knowledge.perimetre import (perimetre_effectif,
                                          rapport_perimetre)
from src.core.role.forme_du_modele import forme as forme_du_modele
from src.core.security.auth import User, require_permission_or_dev

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mining-metiers", tags=["Mining Métier"])

MINING_PERMISSION = "mining"


class BusinessMiningRequest(BaseModel):
    """Paramètres d'une exécution de mining métier.

    Tous les seuils sont fournis par l'appelant : aucun choix métier n'est
    figé côté serveur.
    """

    attributes: List[str] = Field(...)
    min_coverage: float = Field(..., gt=0.0, le=100.0)
    min_users: int = Field(..., ge=2)
    min_rights: int = Field(..., ge=1)
    mining_depth: int = Field(..., ge=1, le=6)
    #: Poids du sur-octroi face à la couverture dans la sélection des rôles.
    #: 0 maximise la couverture — c'est le comportement historique, et le
    #: défaut. Cette valeur n'est pas destinée à être saisie : l'écran propose
    #: des points d'arbitrage calculés et l'utilisateur en désigne un.
    arbitrage: float = Field(0.0, ge=0.0, le=100.0)
    #: Part des habilitations à expliquer avant que la sélection s'arrête.
    #: Sans objectif, le glouton épuise ses candidats et l'arbitrage ne change
    #: que l'ordre : c'est mesuré, et c'est pourquoi les deux vont ensemble.
    couverture_visee: Optional[float] = Field(None, gt=0.0, le=100.0)
    #: Part de ce qu'explique son ancêtre qu'un rôle doit expliquer pour être
    #: retenu à côté de lui. 0 retient toute stratification qui apporte
    #: quelque chose — le comportement historique, mesuré à onze fois plus de
    #: stratifications que le référentiel n'en contient. C'est un arbitrage
    #: entre simplicité et couverture, donc un choix de l'utilisateur.
    parcimonie: float = Field(0.0, ge=0.0, le=100.0)
    #: Faut-il compter les identités qui ne détiennent aucun droit ?
    #: Le référentiel ne dit pas si ce sont des arrivants ou des partants dont
    #: les accès ont été révoqués — sans statut ni date, les deux se
    #: ressemblent. Le choix revient donc à l'utilisateur, et le défaut
    #: reproduit le comportement historique.
    inclure_sans_droit: bool = Field(False)


class ArbitrageRequest(BusinessMiningRequest):
    """Demande de courbe d'arbitrage.

    Reprend les paramètres du mining — la courbe se calcule sur les mêmes
    candidats — et ignore `arbitrage`, qui est justement ce qu'elle fait varier.
    """

    #: Valeurs à essayer. Vide, le moteur propose les siennes.
    arbitrages: List[float] = Field(default_factory=list)


class ImpactRequest(BusinessMiningRequest):
    """Demande de mesure de l'effet d'un paramètre sur ces données-ci.

    Une définition dit ce qu'un paramètre signifie ; elle ne dira jamais ce que
    70 % plutôt que 80 % change sur le référentiel qu'on a sous les yeux.
    """

    #: Paramètre à faire varier, dans le vocabulaire du moteur.
    parameter: str = Field(...)
    #: Valeurs à essayer. Bornées : chacune coûte un mining complet.
    values: List[float] = Field(..., min_length=1, max_length=5)


class SaveBusinessRoleRequest(BaseModel):
    name: str = Field(...)
    description: str = ""
    rights: List[str] = Field(...)
    rh_rule: str = ""
    source_attributes: Dict[str, Any] = Field(default_factory=dict)
    user_count: int = 0
    #: Chiffres affichés au moment de la décision. Leur présence distingue une
    #: décision sur un candidat d'une composition manuelle.
    indicateurs: Optional[schemas.IndicateursDeDecision] = None
    #: Candidat du mining dont ce rôle est issu, s'il en vient.
    candidate_id: Optional[str] = None


@router.get("/attributes/identity/business", response_model=schemas.IdentityAttributesResponse)
async def get_identity_attributes(
    loader: DataLoader = Depends(get_data_loader),
    user: User = Depends(require_permission_or_dev("read")),
):
    """Liste les colonnes d'identité utilisables comme critères de mining métier.

    Les colonnes ne sont pas connues à l'avance : on ne présume donc d'aucun
    nom. On expose la cardinalité de chaque colonne et un drapeau
    `recommended`, calculé à partir du seuil du workspace
    (`mining_attribute_max_cardinality_ratio`), et c'est l'utilisateur qui
    tranche. Seules les colonnes inexploitables par construction sont
    écartées : identifiant technique (une valeur par ligne) et colonne
    constante (une seule valeur).
    """
    identities = loader.identities
    if identities.empty:
        return {"attributes": []}

    total = len(identities)
    max_ratio = loader.config.get("mining_attribute_max_cardinality_ratio", 0.5)

    attributes = []
    for column in identities.columns:
        if column == DataLoader.COL_USER_ID:
            continue

        distinct = int(identities[column].nunique(dropna=True))
        if distinct < 2 or distinct == total:
            # Colonne constante ou identifiant : aucun regroupement possible.
            continue

        ratio = distinct / total
        attributes.append({
            "name": column,
            "description_key": "mining.attribute.distinct_values",
            "description_params": {"count": distinct, "ratio": round(ratio * 100, 1)},
            "distinct_count": distinct,
            "total_count": total,
            "cardinality_ratio": round(ratio, 4),
            "recommended": ratio <= max_ratio,
            "is_mandatory": False,
        })

    attributes.sort(key=lambda a: a["cardinality_ratio"])
    return {"attributes": attributes}


def construire_le_modele_acquis(loader: DataLoader,
                                roles_valides: List[Dict[str, Any]]):
    """Le catalogue validé, évalué sur les données du jour.

    Les membres sont recalculés et non relus : un rôle est une règle, et sa
    population est celle d'aujourd'hui. Le complément se calculerait sinon
    contre un fantôme — celui du jour de la validation.
    """
    from src.core.role.modele_acquis import construire

    # Détenteurs par droit, pour les rôles que ni une règle ni une liste
    # enregistrée ne rattache à des identités — un rôle composé à la main, par
    # exemple. C'est la troisième voie du graphe, dans le même ordre, pour que
    # les deux écrans ne puissent pas se contredire sur qui relève de quoi.
    detenteurs: Dict[str, set] = {}
    habilitations = loader.habilitations
    if habilitations is not None and not habilitations.empty:
        for droit, groupe in habilitations.groupby(
                DataLoader.COL_RIGHT_ID, observed=True)[DataLoader.COL_USER_ID]:
            detenteurs[str(droit)] = {str(membre) for membre in groupe.unique()}

    return construire(roles_valides, loader.identities, DataLoader.COL_USER_ID,
                      detenteurs_par_droit=detenteurs)


def _run_engine(
    loader: DataLoader,
    request: BusinessMiningRequest,
    excluded_users: Optional[List[str]] = None,
    excluded_rights: Optional[List[str]] = None,
    modele_acquis=None,
) -> Dict[str, Any]:
    """Exécute le moteur métier. Appelé hors de la boucle d'événements.

    Les identités exclues sont retirées du périmètre avant le calcul : leurs
    attributs RH ne doivent ni former de groupe, ni peser sur la couverture
    d'un droit dans un groupe.

    Les droits socles sont passés au moteur, et non retirés des rôles après
    coup : retirés après, ils laissaient derrière eux une couverture, un
    sur-octroi et un score calculés sur un rôle qui n'était plus celui qu'on
    affichait.
    """
    from src.core.knowledge.perimetre import restreindre
    from src.core.role.business_miner import BusinessRoleMiner

    return BusinessRoleMiner(restreindre(loader, excluded_users)).mine_roles(
        modele_acquis=modele_acquis,
        attributes=request.attributes,
        min_coverage_pct=request.min_coverage,
        min_users=request.min_users,
        min_rights=request.min_rights,
        mining_depth=request.mining_depth,
        excluded_rights=excluded_rights,
        arbitrage=request.arbitrage,
        couverture_visee=request.couverture_visee,
        inclure_sans_droit=request.inclure_sans_droit,
        parcimonie_pct=request.parcimonie,
    )


def _run_front(loader, request, excluded_users, excluded_rights,
               modele_acquis=None):
    """Calcule la courbe d'arbitrage. Appelé hors de la boucle d'événements."""
    from src.core.knowledge.perimetre import restreindre
    from src.core.role.business_miner import BusinessRoleMiner

    return BusinessRoleMiner(restreindre(loader, excluded_users)).front_arbitrage(
        modele_acquis=modele_acquis,
        attributes=request.attributes,
        min_coverage_pct=request.min_coverage,
        min_users=request.min_users,
        min_rights=request.min_rights,
        mining_depth=request.mining_depth,
        excluded_rights=excluded_rights,
        arbitrages=request.arbitrages or None,
        couverture_visee=request.couverture_visee,
        inclure_sans_droit=request.inclure_sans_droit,
        # La courbe doit décrire le modèle que le mining produira, et le mining
        # applique la parcimonie. Sans ce paramètre, l'utilisateur choisissait
        # sa position d'arbitrage sur une courbe qui décrivait autre chose.
        parcimonie_pct=request.parcimonie,
    )


@router.post("/arbitrage")
async def courbe_arbitrage(
    request: ArbitrageRequest,
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    user: User = Depends(require_permission_or_dev(MINING_PERMISSION)),
) -> Dict[str, Any]:
    """Ce que coûterait chaque position du curseur d'arbitrage.

    Cet écran existe parce qu'un utilisateur ne peut pas choisir un nombre dont
    il ignore le sens. Il lit « 784 rôles pour 13 251 sur-octrois » ou « 908
    rôles pour 11 338 », et désigne. Le paramètre se déduit du choix.

    Le calcul rejoue la sélection sans réénumérer les candidats. Il reste
    coûteux — de l'ordre de la demi-minute sur un référentiel de 230 000
    habilitations pour six points — d'où un appel explicite, et non un calcul
    imposé à chaque mining.
    """
    if not request.attributes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "mining.no_attribute_selected"},
        )

    identities = loader.identities
    if identities.empty:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "mining.no_data_loaded"},
        )

    unknown = [attr for attr in request.attributes if attr not in identities.columns]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "mining.unknown_attributes", "params": {"attributes": unknown}},
        )

    try:
        return await run_in_threadpool(
            _run_front, loader, request, perimetre_effectif(loader, kb),
            sorted(set(kb.get_birth_rights())),
            construire_le_modele_acquis(
                loader, kb.get_validated_roles(role_type="METIER")),
        )
    except Exception:
        logger.exception("Échec du calcul de la courbe d'arbitrage")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "mining.engine_failure"},
        )


def _run_impact(loader, request, excluded_users, excluded_rights):
    """Mesure l'effet d'un paramètre. Appelé hors de la boucle d'événements."""
    from src.core.knowledge.perimetre import restreindre
    from src.core.role.business_miner import BusinessRoleMiner

    entiers = {"min_users", "min_rights", "mining_depth"}
    valeurs = ([int(v) for v in request.values]
               if request.parameter in entiers else list(request.values))

    return BusinessRoleMiner(restreindre(loader, excluded_users)).impact(
        request.parameter,
        valeurs,
        attributes=request.attributes,
        min_coverage_pct=request.min_coverage,
        min_users=request.min_users,
        min_rights=request.min_rights,
        mining_depth=request.mining_depth,
        excluded_rights=excluded_rights,
        arbitrage=request.arbitrage,
        couverture_visee=request.couverture_visee,
        inclure_sans_droit=request.inclure_sans_droit,
    )


@router.post("/impact")
async def impact_parametre(
    request: ImpactRequest,
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    user: User = Depends(require_permission_or_dev(MINING_PERMISSION)),
) -> Dict[str, Any]:
    """Ce que chaque valeur d'un paramètre donnerait sur le référentiel chargé.

    Chaque valeur exige un mining complet : ces paramètres décident des
    candidats, pas de leur sélection. D'où un appel explicite, un nombre de
    valeurs borné, et un écran qui prévient que le calcul prend du temps.
    """
    from src.core.role.business_miner import BusinessRoleMiner

    if request.parameter not in BusinessRoleMiner.PARAMETRES_MESURABLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "mining.unknown_parameter",
                    "params": {"parameter": request.parameter}},
        )

    if not request.attributes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "mining.no_attribute_selected"},
        )

    identities = loader.identities
    if identities.empty:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "mining.no_data_loaded"},
        )

    unknown = [attr for attr in request.attributes if attr not in identities.columns]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "mining.unknown_attributes", "params": {"attributes": unknown}},
        )

    try:
        return await run_in_threadpool(
            _run_impact, loader, request, perimetre_effectif(loader, kb),
            sorted(set(kb.get_birth_rights())),
        )
    except Exception:
        logger.exception("Échec de la mesure d'impact")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "mining.engine_failure"},
        )


@router.post("/find-roles-business")
async def find_roles_business(
    request: BusinessMiningRequest,
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    user: User = Depends(require_permission_or_dev(MINING_PERMISSION)),
) -> Dict[str, Any]:
    """Lance le mining métier et retourne les rôles candidats."""

    if not request.attributes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "mining.no_attribute_selected"},
        )

    identities = loader.identities
    if identities.empty:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "mining.no_data_loaded"},
        )

    unknown = [attr for attr in request.attributes if attr not in identities.columns]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "mining.unknown_attributes", "params": {"attributes": unknown}},
        )

    logger.info(
        "Mining métier : attributs=%s profondeur=%d min_users=%d min_rights=%d couverture>=%.1f%%",
        request.attributes, request.mining_depth, request.min_users,
        request.min_rights, request.min_coverage,
    )
    # Ce que chaque étape coûte. Sans cette décomposition, « le mining est plus
    # lent qu'avant » reste une impression : on ne sait pas si le temps part
    # dans le moteur, dans la préparation du catalogue, ou dans l'écran qui
    # dessine le résultat.
    durees_ms: Dict[str, float] = {}
    debut_total = time.perf_counter()

    def _chronometrer(etape: str, depart: float) -> None:
        durees_ms[etape] = round((time.perf_counter() - depart) * 1000, 1)

    depart = time.perf_counter()
    # Calculé une fois : les règles de périmètre se réévaluent sur le
    # référentiel entier, et cette route s'en sert quatre fois.
    hors_perimetre = perimetre_effectif(loader, kb)
    if hors_perimetre:
        logger.info("%d identités hors périmètre", len(hors_perimetre))

    _chronometrer("perimetre", depart)

    birth_rights = set(kb.get_birth_rights())
    depart = time.perf_counter()
    # Le catalogue entre dans le calcul, il n'en est plus retiré après coup.
    #
    # La route écartait les candidats dont l'ensemble de droits était
    # **exactement** celui d'un rôle validé. Deux défauts en un : un candidat
    # recouvrant le même terrain à quatre-vingt-dix pour cent passait au
    # travers, et un candidat de même contenu mais de population différente
    # était écarté à tort — le rôle validé ne couvrait pourtant pas ses
    # membres. Le moteur retire désormais, candidat par candidat, ce que le
    # catalogue octroie déjà à *tous* ses membres, et le compte de ceux qui
    # n'apportaient plus rien remonte avec les autres.
    #
    # Seuls les rôles métier entrent ici. Un rôle applicatif est une brique
    # assemblée dans un rôle métier : compter comme « octroyés » les droits que
    # ses détenteurs possèdent aujourd'hui confondrait ce que le modèle donne
    # avec ce que le référentiel constate.
    modele_acquis = construire_le_modele_acquis(
        loader, kb.get_validated_roles(role_type="METIER"))
    _chronometrer("modele_acquis", depart)
    # Un candidat refusé ne doit pas revenir au calcul suivant. Le mining
    # applicatif écartait déjà les refus ; le mining métier ne le faisait pas,
    # faute d'identifiant reproductible côté moteur. Il en a un désormais.
    refuses = set(kb.get_rejected_roles())

    depart = time.perf_counter()
    try:
        result = await run_in_threadpool(
            _run_engine, loader, request, hors_perimetre, sorted(birth_rights),
            modele_acquis
        )
    except Exception:
        logger.exception("Échec du moteur de mining métier")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "mining.engine_failure"},
        )

    _chronometrer("moteur", depart)
    depart = time.perf_counter()

    roles = result.get("roles", [])
    filtered_roles: List[Dict[str, Any]] = []
    # Les rôles vidés par les droits socles ne parviennent plus jusqu'ici : le
    # moteur ne les produit pas. Il rend leur compte, pour que la disparition
    # reste explicable.
    dropped_empty = int(result.get("stats", {}).get("dropped_by_exclusion", 0))
    # Candidats que le catalogue vidait entièrement : tous leurs droits étaient
    # déjà octroyés à toute leur population. Le moteur les compte, la route ne
    # les cherche plus.
    dropped_already_validated = int(
        result.get("stats", {}).get("dropped_already_granted", 0))
    dropped_rejected = 0

    for role in roles:
        if str(role.get("id")) in refuses:
            dropped_rejected += 1
            continue

        filtered_roles.append(role)

    logger.info(
        "Mining métier terminé : %d rôles retenus sur %d candidats "
        "(%d sous le seuil après retrait des droits socles, %d déjà validés, "
        "%d refusés)",
        len(filtered_roles), len(roles), dropped_empty, dropped_already_validated,
        dropped_rejected,
    )

    kb.add_mining_run({
        "type": "metier",
        "params": {
            "attributes": request.attributes,
            "min_coverage": request.min_coverage,
            "min_users": request.min_users,
            "min_rights": request.min_rights,
            "mining_depth": request.mining_depth,
            "birth_rights_auto_excluded": len(birth_rights),
        },
        "results_count": len(filtered_roles),
        "validated_roles_filtered": dropped_already_validated,
        "launched_by": user.username,
    })

    # Le diagnostic accompagne chaque candidat : il est bâti sur ses propres
    # chiffres et sur la couverture que l'appelant a exigée au lancement. Un
    # rôle métier est déjà une règle ; lui chercher une explication par les
    # attributs retournerait celle qui a servi à le construire.
    from src.core.mining.pertinence_metier import diagnostiquer_un_role_metier

    # Ce qu'un candidat est déjà devenu. Un candidat validé revenait identique
    # à chaque calcul, sans que rien ne le dise : on le revalidait, et la
    # collision de nom se découvrait au moment d'enregistrer. Il n'est pas
    # retiré de la liste — une ligne qui disparaît sans explication est le
    # défaut que ce produit s'interdit ailleurs — il est **annoncé**.
    tranches = kb.decisions_par_candidat()

    for role in filtered_roles:
        role["diagnostic"] = diagnostiquer_un_role_metier(
            role, couverture_attendue=request.min_coverage / 100.0)
        decision = tranches.get(str(role.get("id")))
        if decision:
            role["decision"] = decision

    # Ce que vaut le modèle proposé, mesuré sur le modèle **final** — après
    # sélection et après filtrage par la Knowledge Base. Le mesurer plus tôt
    # décrirait un modèle qui n'existe pas. Le module est celui du mining
    # applicatif : les deux écrans doivent parler des mêmes grandeurs.
    _chronometrer("tri_du_resultat", depart)
    depart = time.perf_counter()
    qualite = await run_in_threadpool(_evaluer_modele, loader, filtered_roles,
                                      hors_perimetre)

    # Coût d'une attribution réelle, relevé sur le modèle **final**. Le mineur
    # le calcule sur ce qu'il produit ; la route en retire ensuite des rôles, et
    # le chiffre du mineur décrirait alors un modèle qu'on n'affiche plus.
    population = await run_in_threadpool(_mesurer_population, loader,
                                         filtered_roles, hors_perimetre)

    # Sur quelle population portent tous les chiffres ci-dessus. Écarter des
    # identités change le dénominateur de la couverture, du sur-octroi et des
    # effectifs : un total sans sa population n'est pas une mesure. C'est le
    # défaut que le lot 6b a corrigé pour les identités sans droit ; le filtre
    # de périmètre le ferait revenir par une autre porte.
    perimetre = rapport_perimetre(loader, kb.get_excluded_users(),
                                  kb.regles_perimetre())
    _chronometrer("mesures", depart)
    durees_ms["total"] = round((time.perf_counter() - debut_total) * 1000, 1)
    logger.info("Mining métier : %s", ", ".join(
        f"{etape} {valeur:.0f} ms" for etape, valeur in durees_ms.items()))

    global_stats = {
        **result.get("stats", {}),
        **_agregats(filtered_roles),
        **population,
        "perimeter": perimetre,
        # Le sur-octroi du modèle **affiché**, et non celui que le moteur a
        # relevé avant que la route retire des rôles. Les deux étaient rendus
        # côte à côte — l'un sous `over_provisioning_distinct`, l'autre sous
        # `quality.over_granted` —, calculés par deux codes, sur deux jeux de
        # rôles. Même définition, deux noms, deux moments : c'est exactement
        # l'ambiguïté que ce lot supprime. Une seule mesure, celle du modèle
        # qu'on montre.
        "over_provisioning_distinct": qualite["over_granted"],
        "quality": qualite,
        # La forme de ce que le mining vient de rendre. Sur un référentiel
        # hospitalier, il rend 1 751 rôles : un compte que personne ne peut
        # traiter, et dont l'écran ne disait rien d'autre que sa taille.
        # Ce que chaque étape a coûté. L'écran y ajoute son propre temps
        # d'affichage : les deux ensemble disent où part l'attente.
        "durees_ms": durees_ms,
        "forme": forme_du_modele(
            filtered_roles,
            int(result.get("stats", {}).get("total_habs_in_scope") or 0)),
        "kb_integration": {
            "birth_rights_excluded": len(birth_rights),
            "rejected_roles_filtered": dropped_rejected,
            "validated_roles_filtered": dropped_already_validated,
            "below_threshold_after_birth_rights": dropped_empty,
            "total_roles_after_filter": len(filtered_roles),
        },
    }

    # Voir `mining.py` : les candidats et leurs indicateurs sont conservés pour
    # survivre au rechargement, alimenter la vue « avant / après » du graphe, et
    # permettre de reprendre une revue là où elle a été laissée.
    await run_in_threadpool(
        kb.set_candidate_roles,
        "METIER", filtered_roles, request.dict(),
        loader.empreinte_donnees(), global_stats,
    )

    return {
        "top_roles": filtered_roles,
        "global_stats": global_stats,
        # Les noms déjà pris dans le catalogue. L'écran s'en sert pour
        # prévenir **avant** que quelqu'un relise des centaines d'identités,
        # pas pour décider : le serveur reste seul juge, et refuse un nom pris
        # même si l'écran ne l'avait pas vu venir.
        "noms_du_catalogue": kb.noms_des_roles_valides(role_type="METIER"),
    }


def _detail_population(loader: DataLoader, roles: list, identites_exclues) -> list:
    """Le détail par règle RH du coût d'une attribution. Hors boucle d'événements."""
    from src.core.knowledge.perimetre import restreindre
    from src.core.role.business_miner import BusinessRoleMiner

    return BusinessRoleMiner(restreindre(loader, identites_exclues)).detail_population(roles)


def _mesurer_population(loader: DataLoader, roles: list, identites_exclues) -> dict:
    """Coût d'une attribution réelle du modèle. Hors boucle d'événements.

    Le périmètre est le même que partout ailleurs : compter les identités
    exclues de l'analyse fausserait le chiffre dans l'autre sens.
    """
    from src.core.knowledge.perimetre import restreindre
    from src.core.role.business_miner import BusinessRoleMiner

    return BusinessRoleMiner(restreindre(loader, identites_exclues)).mesurer_population(roles)


def _evaluer_modele(loader: DataLoader, roles: list, identites_exclues) -> dict:
    """Mesure le modèle métier final. Appelé hors de la boucle d'événements.

    Les mesures portent sur le **périmètre d'analyse** : compter des
    habilitations d'identités exclues fausserait la couverture annoncée.

    `mesurer` rend la couverture et le sur-octroi **dédupliqués** — ce que le
    modèle reprend d'existant, et ce qu'il créerait. C'est la réponse à
    l'objectif du produit, et elle n'était calculée que du côté applicatif. Les
    agrégats voisins, eux, additionnent rôle par rôle : sur un référentiel réel
    la somme dépassait l'union de plus de 25 %.
    """
    from src.api.routers.mining import _droits_par_identite
    from src.core.knowledge.perimetre import restreindre
    from src.core.mining.role_quality import mesurer

    perimetre = restreindre(loader, identites_exclues)
    return mesurer(roles, len(perimetre.habilitations),
                   _droits_par_identite(perimetre))["metrics"]


def _agregats(roles: list) -> dict:
    """Indicateurs du modèle, relevés après filtrage.

    Le mineur les calcule sur ce qu'il produit ; la route en retire ensuite les
    rôles dont les droits socles ont vidé le contenu, et ceux déjà validés. Les
    chiffres du mineur décrivent alors un modèle qui n'est plus celui qu'on
    affiche.

    Ils étaient jusqu'ici recalculés **par le navigateur**, à partir des rôles
    reçus, avec une couverture qui était la moyenne non pondérée des
    couvertures de chaque rôle — ce qui n'est pas la couverture du modèle. Un
    indicateur de gouvernance ne se calcule pas dans la page.
    """
    utilisateurs = {identite for role in roles for identite in role.get("users", [])}
    droits = {droit for role in roles for droit in role.get("rights", [])}
    octroye = sum(int(role.get("user_count", 0)) * int(role.get("right_count", 0))
                  for role in roles)
    couvertures = [float(role.get("coverage_pct", 0.0)) for role in roles]

    return {
        "total_roles_found": len(roles),
        "total_users": len(utilisateurs),
        "total_rights": len(droits),
        "avg_coverage": round(sum(couvertures) / len(couvertures), 1) if couvertures else 0.0,
        "granted_by_roles": octroye,
    }


@router.get("/population-detail")
async def detail_population(
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    user: User = Depends(require_permission_or_dev("mining")),
):
    """Quelles règles toucheraient les identités qui ne détiennent aucun droit.

    L'écran de mining annonce un nombre — « 1 166 identités recevraient un rôle
    proposé ». Un nombre sans le moyen de le regarder est exactement ce que ce
    produit reproche aux outils du marché : la décision se prend sur *lesquels*,
    pas sur *combien*.

    Le détail porte sur les candidats **conservés**, pas sur un nouveau calcul :
    il doit décrire le modèle que l'utilisateur a sous les yeux, et un mining
    relancé rendrait autre chose dès qu'un paramètre a bougé. Sans candidat
    conservé, la réponse est vide — l'écran invite alors à lancer une analyse
    plutôt que d'afficher un tableau qui ne décrit rien.
    """
    run = kb.get_candidate_run("METIER")
    roles = list(run.get("roles") or []) if run else []
    if not roles:
        return {"groups": [], "computed_at": None, "stale": False}

    detail = await run_in_threadpool(_detail_population, loader, roles,
                                     perimetre_effectif(loader, kb))
    empreinte = await run_in_threadpool(loader.empreinte_donnees)
    return {
        "groups": detail,
        "computed_at": run.get("computed_at"),
        # Les données ont-elles changé depuis ce calcul ? Un tableau qui décrit
        # un référentiel qu'on a rechargé depuis induirait en erreur au moment
        # précis où il sert à décider.
        "stale": bool(run.get("data_fingerprint")) and \
            run.get("data_fingerprint") != empreinte,
    }


@router.post("/create-role-business", status_code=status.HTTP_201_CREATED)
async def create_role_business(
    request: SaveBusinessRoleRequest,
    kb: KnowledgeBase = Depends(get_kb),
    user: User = Depends(require_permission_or_dev("roles")),
    journal: Journal = Depends(get_journal),
):
    """Enregistre un rôle métier validé dans la Knowledge Base du workspace."""

    if not request.name.strip() or not request.rights:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "role.name_and_rights_required"},
        )

    for existing in kb.get_validated_roles(role_type="METIER"):
        if existing.get("name") == request.name:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "role.name_already_used", "params": {"name": request.name}},
            )

    new_role = {
        "id": str(uuid.uuid4()),
        "name": request.name,
        "description": request.description,
        "role_type": "METIER",
        "rights": request.rights,
        "user_count": request.user_count,
        "rh_rule": request.rh_rule,
        "source_attributes": request.source_attributes,
        "sub_roles": [],
        "additional_rights": [],
        "created_by": user.username,
    }

    kb.add_validated_role(new_role)
    if request.indicateurs is not None:
        kb.enregistrer_decision(new_role["id"], "validee",
                                request.indicateurs.dict(),
                                candidate_id=request.candidate_id or "")
    consigner_la_creation(journal, new_role, request.candidate_id)
    logger.info("Rôle métier '%s' enregistré (id=%s) par %s", request.name, new_role["id"], user.username)

    return {"code": "role.created", "id": new_role["id"], "name": new_role["name"]}
