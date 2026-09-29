# src/api/routers/mining.py
"""
Routeur du mining applicatif.

Découvre des rôles applicatifs à partir de la matrice utilisateurs x droits,
puis confronte les candidats à la Knowledge Base du workspace actif :
- les droits socles (droits socles) sont exclus automatiquement,
- les rôles déjà validés et les rôles rejetés sont écartés,
- chaque exécution est historisée.

L'identité d'un rôle est le SHA-256 de ses droits triés : elle reste stable
quel que soit son nom, ce qui permet de retrouver un rôle rejeté d'une
exécution à l'autre. Le frontend applique exactement le même calcul.
"""

import logging

import numpy as np
from typing import Any, Dict, List, Optional, Sequence

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.concurrency import run_in_threadpool

from src.api.dependencies import get_data_loader, get_kb
from src.core.data.loader import DataLoader
from src.core.knowledge.knowledge_base import KnowledgeBase
from src.core.knowledge.perimetre import perimetre_effectif
from src.core.mining.approximate_miner import GENERATEURS, MAX_ROLES_PLAFOND
from src.core.mining.selection_exacte import SELECTIONS
from src.core.role.identite import identifiant_applicatif
from src.api.journal import Journal, get_journal
from src.core.audit import Action
from src.core.security.auth import User, require_permission_or_dev

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mining", tags=["Mining Applicatif"])

#: Permission exigée sur les routes de ce module.
MINING_PERMISSION = "mining"


class MiningMode:
    """Modes de mining applicatif exposés par l'API."""

    EXACT = "EXACT"
    APPROX = "APPROX"
    ALL = (EXACT, APPROX)



class RoleAExpliquer(BaseModel):
    """Un rôle réduit à ce que l'explication exige : son identité, sa population."""

    id: str = Field(...)
    users: List[str] = Field(...)


class ExplainRolesRequest(BaseModel):
    """Les quatre contraintes sont exprimées par l'appelant, sans valeur par défaut.

    Elles ne sont pas interchangeables : la couverture et le lift disent ce
    qu'on juge *utile*, la p-valeur ce qu'on juge *réel*, la profondeur ce
    qu'on juge *lisible*, la fiabilité attendue ce qu'on juge *défendable*
    devant un responsable d'application. Aucune ne se déduit des autres, et
    aucune ne relève du produit.
    """

    roles: List[RoleAExpliquer] = Field(...)
    attributes: List[str] = Field(...)
    min_coverage: float = Field(..., gt=0.0, le=1.0)
    min_reliability: float = Field(..., gt=0.0, le=1.0)
    min_lift: float = Field(..., ge=1.0)
    max_depth: int = Field(..., ge=1, le=6)
    max_p_value: float = Field(..., gt=0.0, le=1.0)


def _generateurs_connus(valeur):
    """Refusé plutôt qu'ignoré.

    Un générateur mal orthographié, silencieusement écarté, ferait rendre
    moins de rôles sans que personne ne sache pourquoi — et la couverture se
    lirait comme un défaut du référentiel.

    Écrit une seule fois, parce que la demande de mining et la demande
    d'exploration portent le même champ : deux copies auraient divergé, et la
    courbe aurait fini par accepter ce que le mining refuse.
    """
    if valeur is None:
        return valeur
    inconnus = [nom for nom in valeur if nom not in GENERATEURS]
    if inconnus:
        raise ValueError(
            f"générateur inconnu : {', '.join(inconnus)} "
            f"(attendu : {', '.join(GENERATEURS)})")
    return valeur


def _selection_connue(valeur):
    """Refusée plutôt qu'ignorée : une faute de frappe ferait tourner le
    glouton sans que l'utilisateur sache que son choix n'a pas été appliqué."""
    if valeur is not None and valeur not in SELECTIONS:
        raise ValueError(
            f"sélection inconnue : {valeur} (attendu : {', '.join(SELECTIONS)})")
    return valeur


def _reglages_de_selection(loader: DataLoader, selection: Optional[str]) -> Dict[str, Any]:
    """La sélection de l'appelant, sinon celle du workspace, avec son effort.

    Écrit une fois pour le mining et la courbe des seuils : deux copies
    auraient fini par ne plus décrire le même calcul.
    """
    return {
        "selection": selection if selection is not None else loader.config.mining_selection,
        "selection_effort": loader.config.mining_selection_effort,
        "selection_delai_s": loader.config.mining_selection_delai_s,
    }


class MiningRequest(BaseModel):
    """Paramètres d'une exécution de mining applicatif.

    Aucune valeur métier n'est figée dans le code : les seuils viennent de la
    requête, donc de choix explicites de l'utilisateur.
    """

    min_users: int = Field(..., ge=2, description="Nombre minimal d'utilisateurs pour retenir un rôle")
    min_rights: int = Field(..., ge=1, description="Nombre minimal de droits pour retenir un rôle")
    excluded_rights: List[str] = Field(default_factory=list)
    mining_mode: str = Field(default=MiningMode.EXACT)

    # Mode APPROX uniquement. θ = 1.0 correspond à une clôture exacte (aucun
    # droit octroyé en trop) ; en dessous on accepte des rôles approchés.
    similarity_threshold: Optional[float] = Field(default=None, gt=0.0, le=1.0)
    # Le mining approché produit un très grand nombre de candidats : on borne
    # ce qui remonte à l'IHM. La valeur est un choix de l'appelant, et sa
    # borne haute est un réglage du workspace, contrôlé plus bas : cinq
    # mille écrits ici rendaient indélébile l'avertissement « plafond
    # atteint » sur tout référentiel qui porte plus de rôles candidats.
    max_roles: Optional[int] = Field(default=None, ge=1)

    # Ce qu'un rôle doit **expliquer** pour être retenu, en habilitations non
    # encore couvertes. Absent, le réglage du workspace s'applique — et son
    # repli est un, c'est-à-dire aucun plancher, donc le comportement d'avant.
    apport_minimal: Optional[int] = Field(default=None, ge=1)

    # Façons d'amorcer un candidat. Aucune n'est meilleure en soi : chacune
    # trouve des rôles que les autres ne trouvent pas, et le croisement des
    # profils coûte un calcul quadratique. Le choix appartient donc à
    # l'utilisateur. Vide, les trois sont employées.
    generateurs: Optional[List[str]] = Field(default=None)

    _valider_generateurs = field_validator("generateurs")(
        classmethod(lambda cls, valeur: _generateurs_connus(valeur)))

    # Comment les rôles sont choisis parmi les candidats. Absent, le réglage
    # du workspace s'applique. La sélection exacte ne joue qu'à θ = 1 ; en
    # dessous, le glouton est gardé et le compte rendu le dit.
    selection: Optional[str] = Field(default=None)

    _valider_selection = field_validator("selection")(
        classmethod(lambda cls, valeur: _selection_connue(valeur)))

    # Consolidation : deux rôles dont les droits atteignent ce seuil de
    # similarité sont considérés comme le même rôle, et seul le mieux classé
    # est conservé. Absent, aucune consolidation n'est appliquée — supprimer
    # des candidats est une décision, elle ne se prend pas par défaut.
    consolidation_threshold: Optional[float] = Field(default=None, gt=0.0, le=1.0)


class ThresholdScanRequest(BaseModel):
    """Paramètres d'une exploration du seuil de similarité.

    Les seuils à évaluer sont fournis par l'appelant : le serveur ne propose
    aucune grille par défaut, le compromis couverture / sur-octroi restant une
    décision de gouvernance.
    """

    thresholds: List[float] = Field(..., description="Seuils θ à évaluer, dans ]0, 1]")
    min_users: int = Field(..., ge=2)
    min_rights: int = Field(..., ge=1)
    #: Même grandeur, même plafond que pour un mining : deux bornes
    #: différentes feraient qu'un point de la courbe ne serait pas
    #: rejouable.
    max_roles: int = Field(..., ge=1)
    excluded_rights: List[str] = Field(default_factory=list)
    #: Les mêmes leviers qu'un mining. Sans eux, la courbe ne décrivait pas
    #: l'exécution qui la suivrait : l'utilisateur choisissait un point, puis
    #: obtenait un autre résultat en lançant son mining.
    generateurs: Optional[List[str]] = Field(default=None)
    apport_minimal: Optional[int] = Field(default=None, ge=1)
    selection: Optional[str] = Field(default=None)

    _valider_generateurs = field_validator("generateurs")(
        classmethod(lambda cls, valeur: _generateurs_connus(valeur)))
    _valider_selection = field_validator("selection")(
        classmethod(lambda cls, valeur: _selection_connue(valeur)))
    # Contrainte facultative de l'utilisateur. Sans elle, aucun point n'est
    # désigné : la courbe est rendue telle quelle.
    max_over_granted_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0)


class ConsolidationScanRequest(MiningRequest):
    """Paramètres d'une exploration du seuil de consolidation.

    Le mining n'est exécuté qu'une fois : la consolidation est rejouée sur son
    résultat à chaque seuil. Les paramètres de mining sont donc ceux d'une
    exécution ordinaire, et la courbe décrit exactement les rôles que cette
    exécution produirait.
    """

    consolidation_thresholds: List[float] = Field(
        ..., description="Seuils de consolidation à évaluer, dans ]0, 1]"
    )
    # Contrainte facultative de l'utilisateur : part des couples accordés qu'il
    # accepte de perdre en simplifiant. Sans elle, aucun point n'est désigné.
    max_granted_loss_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0)


#: Nombre maximal de seuils évalués en une requête. Ce n'est pas une valeur
#: métier mais une borne de protection : chaque seuil est un mining complet.
MAX_THRESHOLDS_PER_SCAN = 20

#: Nombre maximal de rôles expliqués en un appel. L'explication est linéaire
#: en nombre de rôles, mais la charge utile transporte la liste des porteurs :
#: c'est elle, et non le calcul, qui borne l'appel.
MAX_ROLES_PER_EXPLANATION = 500


def generate_unique_role_name(base_name: str, existing_names: List[str]) -> str:
    """Retourne un nom non encore utilisé, suffixé si nécessaire."""
    if base_name not in existing_names:
        return base_name

    counter = 1
    while f"{base_name} ({counter})" in existing_names:
        counter += 1
    return f"{base_name} ({counter})"




def _build_right_to_application(loader: DataLoader) -> Dict[str, str]:
    """Associe chaque droit à son application via le référentiel des droits.

    Le rattachement vient de la donnée, jamais d'une convention de nommage :
    les identifiants de droits sont propres à chaque client.
    Retourne un dictionnaire vide si le référentiel ne porte pas l'information.
    """
    rights_df = loader.rights
    if rights_df.empty:
        return {}
    if DataLoader.COL_RIGHT_ID not in rights_df.columns:
        return {}
    if DataLoader.COL_APP_ID not in rights_df.columns:
        logger.info(
            "Référentiel des droits sans colonne application : "
            "la couverture applicative ne sera pas calculée."
        )
        return {}

    pairs = rights_df[[DataLoader.COL_RIGHT_ID, DataLoader.COL_APP_ID]].dropna()
    return dict(zip(pairs[DataLoader.COL_RIGHT_ID], pairs[DataLoader.COL_APP_ID]))


#: Au-delà de cette part de la population, un droit ne distingue plus personne.
#: Réglable par workspace ; la valeur par défaut est celle de la détection des
#: droits socles, pour que les deux écrans parlent du même seuil.
SEUIL_DROIT_SOCLE_DEFAUT = 90.0


def _droits_universels_non_exclus(loader: DataLoader, exclus: List[str],
                                  seuil_pct: float) -> List[str]:
    """Droits détenus par presque tout le monde et laissés dans le calcul.

    Un tel droit n'apporte aucune information de regroupement — tout le monde
    l'a — mais il coûte une incrémentation **par identité et par candidat**.
    Mesuré sur un jeu calibré : 15,5 s contre 1,8 s pour 20 000 identités, soit
    **8,6 fois plus lent**, pour un résultat de moins bonne qualité — les
    signatures gonflées par ces droits se ressemblent toutes.

    Le produit sait les détecter et les exclut automatiquement dès qu'ils sont
    enregistrés. Rien n'obligeait en revanche à lancer la détection : le mining
    partait alors handicapé, sans que rien ne le signale.
    """
    matrice = loader.matrix
    if matrice is None or matrice.shape[0] == 0:
        return []

    exclus_encodes = {loader.right_encoder.get(droit) for droit in exclus}
    population = matrice.shape[0]
    minimum = population * seuil_pct / 100.0

    detenteurs = np.asarray(matrice.sum(axis=0)).ravel()
    decodeur = {index: nom for nom, index in loader.right_encoder.items()}

    return sorted(
        decodeur[index] for index in np.flatnonzero(detenteurs >= minimum)
        if index not in exclus_encodes and index in decodeur
    )


def _run_engine(
    loader: DataLoader,
    request: MiningRequest,
    excluded_rights: List[str],
    excluded_users: Optional[List[str]] = None,
    roles_valides: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Exécute le moteur demandé. Appelé hors de la boucle d'événements.

    Retourne un dictionnaire {"roles": [...], "engine_stats": {...}} pour que
    les deux moteurs se présentent de la même façon à l'appelant.
    """
    # Les identités exclues sont retirées du périmètre avant tout calcul, au
    # même titre que les droits socles côté droits.
    from src.core.knowledge.perimetre import restreindre

    loader = restreindre(loader, excluded_users)

    if request.mining_mode == MiningMode.APPROX:
        from src.core.mining.approximate_miner import ApproximateRoleMiner

        result = ApproximateRoleMiner(loader).mine(
            similarity_threshold=request.similarity_threshold,
            min_users=request.min_users,
            min_rights=request.min_rights,
            excluded_rights=excluded_rights,
            max_roles=request.max_roles,
            roles_valides=roles_valides,
            generateurs=request.generateurs,
            profils_croises_max=loader.config.mining_profils_croises_max,
            treillis_max=loader.config.mining_treillis_max,
            # Le choix de l'appelant prime ; sans lui, celui du workspace.
            # Aucun nombre n'est écrit ici : un plancher posé par le code
            # écarterait des rôles sans que personne ne l'ait décidé.
            apport_minimal=(request.apport_minimal
                            if request.apport_minimal is not None
                            else loader.config.mining_apport_minimal),
            **_reglages_de_selection(loader, request.selection),
        )
        roles, engine_stats = result["roles"], result["stats"]
    else:
        from src.core.role.miner import RoleMinerEngine

        miner = RoleMinerEngine(loader)
        miner.min_users = request.min_users
        miner.min_rights = request.min_rights
        roles, engine_stats = miner.mine_roles_exact(excluded_rights=excluded_rights), {}

    consolidation_stats: Dict[str, Any] = {}
    if request.consolidation_threshold is not None:
        from src.core.mining.role_quality import consolider

        consolidation = consolider(roles, seuil_similarite=request.consolidation_threshold)
        roles, consolidation_stats = consolidation["roles"], consolidation["stats"]

    return {
        "roles": roles,
        "engine_stats": engine_stats,
        "consolidation_stats": consolidation_stats,
    }


def _droits_par_identite(loader: DataLoader) -> Dict[str, Any]:
    """Droits réellement détenus par identité, pour une mesure exacte.

    La consolidation rend caducs les compteurs du moteur : la couverture et le
    sur-octroi du modèle final sont recalculés sur les habilitations réelles
    plutôt qu'approchés.
    """
    habilitations = loader.habilitations
    if habilitations.empty or DataLoader.COL_USER_ID not in habilitations.columns:
        return {}
    return (
        habilitations.groupby(DataLoader.COL_USER_ID)[DataLoader.COL_RIGHT_ID]
        .apply(set)
        .to_dict()
    )


def restreindre_perimetre(loader: DataLoader, identites_exclues) -> Any:
    """Raccourci local : le périmètre d'analyse privé des identités exclues."""
    from src.core.knowledge.perimetre import restreindre

    return restreindre(loader, identites_exclues)


def _evaluer_modele(loader, roles: List[Dict[str, Any]],
                    catalogue: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """Hiérarchise puis mesure le modèle final. Appelé hors de la boucle d'événements.

    Les métriques portent sur le **périmètre d'analyse** : compter des
    habilitations d'identités exclues fausserait la couverture annoncée.

    Le catalogue validé entre dans la hiérarchie : un candidat qui contient un
    rôle déjà validé doit le **composer**, et non recopier ses droits à plat.
    """
    from src.core.mining.role_quality import hierarchiser, mesurer

    hierarchie = hierarchiser(roles, catalogue)
    qualite = mesurer(hierarchie["roles"], len(loader.habilitations), _droits_par_identite(loader))
    return {
        "roles": qualite["roles"],
        "quality": qualite["metrics"],
        "hierarchy": hierarchie["stats"],
    }


@router.post("/launch")
async def launch_mining(
    request: MiningRequest,
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    user: User = Depends(require_permission_or_dev(MINING_PERMISSION)),
    journal: Journal = Depends(get_journal),
) -> Dict[str, Any]:
    """Lance le mining applicatif et retourne les rôles candidats."""

    # Les paramètres sont consignés avec le lancement : sans eux, un rôle
    # validé six mois plus tôt n'est pas reproductible, donc pas justifiable.
    journal.consigner(
        Action.MINING_LANCE, "mining", "",
        {cle: valeur for cle, valeur in request.dict().items()
         if isinstance(valeur, (str, int, float, bool))},
    )

    if request.mining_mode not in MiningMode.ALL:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "mining.unknown_mode", "params": {"mode": request.mining_mode}},
        )

    if request.mining_mode == MiningMode.APPROX and (
        request.similarity_threshold is None or request.max_roles is None
    ):
        # Aucune valeur par défaut côté serveur : le compromis couverture /
        # sur-octroi est une décision de gouvernance, elle appartient à
        # l'utilisateur.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "mining.approx_parameters_required"},
        )

    _verifier_le_plafond_de_roles(request.max_roles, loader)

    if loader.matrix is None or loader.matrix.shape[0] == 0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "mining.no_data_loaded"},
        )

    birth_rights = kb.get_birth_rights()
    all_excluded_rights = sorted(set(request.excluded_rights) | set(birth_rights))
    excluded_users = perimetre_effectif(loader, kb)

    seuil_universel = float(getattr(loader.config, "birth_rights_alert_pct",
                                    SEUIL_DROIT_SOCLE_DEFAUT))
    droits_universels = _droits_universels_non_exclus(
        loader, all_excluded_rights, seuil_universel)
    if droits_universels:
        logger.warning(
            "%d droit(s) détenus par au moins %.0f %% de la population ne sont "
            "pas exclus : le mining sera nettement plus lent et ses regroupements "
            "moins nets. Lancer la détection des droits socles.",
            len(droits_universels), seuil_universel,
        )

    validated_roles = kb.get_validated_roles(role_type="APPLICATIF")
    validated_right_sets = [set(r["rights"]) for r in validated_roles]
    rejected_role_ids = set(kb.get_rejected_roles())
    existing_names = [r["name"] for r in validated_roles]

    logger.info(
        "Mining applicatif : mode=%s min_users=%d min_rights=%d "
        "droits exclus=%d (dont %d droits socles) identités exclues=%d "
        "rôles rejetés connus=%d",
        request.mining_mode, request.min_users, request.min_rights,
        len(all_excluded_rights), len(birth_rights), len(excluded_users),
        len(rejected_role_ids),
    )

    try:
        engine_result = await run_in_threadpool(
            _run_engine, loader, request, all_excluded_rights, excluded_users,
            validated_roles
        )
        results = engine_result["roles"]
        engine_stats = engine_result["engine_stats"]
        consolidation_stats = engine_result["consolidation_stats"]
    except ValueError as exc:
        logger.warning("Paramètres de mining invalides : %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "mining.invalid_parameters"},
        )
    except Exception:
        logger.exception("Échec du moteur de mining applicatif")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "mining.engine_failure"},
        )

    right_to_app = _build_right_to_application(loader)

    filtered_results: List[Dict[str, Any]] = []
    roles_rejected_filtered = 0
    roles_already_validated = 0
    all_users: set = set()
    all_rights: set = set()
    all_apps: set = set()

    for role in results:
        role_rights_set = set(role.get("rights", []))
        role_id = identifiant_applicatif(role_rights_set)

        if role_id in rejected_role_ids:
            roles_rejected_filtered += 1
            continue

        # Le filtre par ensemble exact reste ici, contrairement au mining
        # métier où il a été retiré. Ce n'est pas une incohérence : un rôle
        # **applicatif** est défini par ses droits, et rien d'autre. Deux
        # candidats de mêmes droits sont le même rôle, avec la même population
        # — celle qui les détient tous. Côté métier, la règle d'attributs
        # définit la population indépendamment des droits, et deux règles
        # distinctes peuvent accorder les mêmes droits à deux populations
        # différentes : le filtre y écartait à tort.
        if role_rights_set in validated_right_sets:
            roles_already_validated += 1
            continue

        role["id"] = role_id
        role["name"] = generate_unique_role_name(role.get("name", role_id), existing_names)
        existing_names.append(role["name"])

        all_users.update(role.get("users", []))
        all_rights.update(role_rights_set)
        if right_to_app:
            all_apps.update(
                right_to_app[right] for right in role_rights_set if right in right_to_app
            )

        filtered_results.append(role)

    roles_filtered_count = roles_rejected_filtered + roles_already_validated

    # Hiérarchie et qualité portent sur le modèle **final**, celui que
    # l'utilisateur verra : après consolidation et après filtrage par la
    # Knowledge Base. Les mesurer plus tôt décrirait un modèle qui n'existe pas.
    evaluation = await run_in_threadpool(
        _evaluer_modele, restreindre_perimetre(loader, excluded_users),
        filtered_results, validated_roles
    )
    filtered_results = evaluation["roles"]

    logger.info(
        "Mining applicatif terminé : %d rôles retenus, %d filtrés "
        "(%d rejetés, %d déjà validés), %d utilisateurs, %d droits, %d applications",
        len(filtered_results), roles_filtered_count, roles_rejected_filtered,
        roles_already_validated, len(all_users), len(all_rights), len(all_apps),
    )

    kb.add_mining_run({
        "type": "applicatif",
        "params": {
            "min_users": request.min_users,
            "min_rights": request.min_rights,
            "mining_mode": request.mining_mode,
            "similarity_threshold": request.similarity_threshold,
            "max_roles": request.max_roles,
            "consolidation_threshold": request.consolidation_threshold,
            "birth_rights_auto_excluded": len(birth_rights),
            "excluded_users": len(excluded_users),
        },
        "results_count": len(filtered_results),
        "roles_filtered": roles_filtered_count,
        "launched_by": user.username,
    })

    global_stats = {
        "total_roles_found": len(filtered_results),
        "roles_filtered": roles_filtered_count,
        "users_impacted": len(all_users),
        "rights_covered": len(all_rights),
        "apps_covered": len(all_apps),
        "apps_resolved": bool(right_to_app),
        # Métriques propres au moteur approché : couverture des habilitations
        # et sur-octroi induit. Vide en mode exact.
        "engine": engine_stats,
        # Qualité du modèle final : compression, redondance, sous-affectation,
        # complexité structurelle. Le sur-octroi qui y figure compte des
        # couples distincts, là où celui du moteur additionne le sur-octroi de
        # chaque rôle, un même couple pouvant être octroyé par plusieurs.
        "quality": evaluation["quality"],
        "hierarchy": evaluation["hierarchy"],
        # Vide quand aucun seuil de consolidation n'a été demandé.
        "consolidation": consolidation_stats,
        "kb_integration": {
            "birth_rights_excluded": len(birth_rights),
            "rejected_roles_filtered": roles_rejected_filtered,
            "already_validated_filtered": roles_already_validated,
            "excluded_users": len(excluded_users),
        },
    }

    # Les candidats sont conservés dans la base du workspace. Jusqu'ici ils
    # n'existaient que dans la mémoire du navigateur : un rechargement de page
    # effaçait le résultat d'un calcul de plusieurs minutes, et le graphe ne
    # pouvait pas montrer l'« après » d'une revue.
    #
    # Les indicateurs sont conservés avec eux : un résultat repris doit
    # s'afficher entier, et non amputé de ce qui permet de le juger.
    await run_in_threadpool(
        kb.set_candidate_roles,
        "APPLICATIF", filtered_results, request.dict(),
        loader.empreinte_donnees(), global_stats,
    )

    # Ce qu'un candidat est déjà devenu, et les noms que le catalogue porte
    # déjà. Un candidat validé revenait identique à chaque calcul, et la
    # collision de nom se découvrait au moment d'enregistrer. Voir
    # `decisions_par_candidat` dans la Knowledge Base.
    tranches = kb.decisions_par_candidat()
    for role in filtered_results:
        decision = tranches.get(str(role.get("id")))
        if decision:
            role["decision"] = decision

    return {
        "top_roles": filtered_results,
        "global_stats": global_stats,
        "noms_du_catalogue": kb.noms_des_roles_valides(role_type="APPLICATIF"),
        # Le serveur nomme le constat et donne les chiffres ; la phrase est
        # composée par le client, dans sa langue.
        "warnings": ([{
            "code": "mining.universal_rights_not_excluded",
            "params": {"count": len(droits_universels),
                       "seuil": round(seuil_universel),
                       "exemples": ", ".join(droits_universels[:5])},
        }] if droits_universels else []),
    }


def _verifier_le_plafond_de_roles(demande_max_roles, loader) -> None:
    """Le nombre de rôles réclamé tient-il sous le plafond du workspace ?

    Le plafond protège le serveur d'une demande absurde. Il n'est pas écrit
    dans le code : sur un référentiel qui porte plus de rôles candidats que la
    borne, l'écran affichait un « plafond atteint » que rien ne permettait de
    lever — l'avertissement parlait du produit en se faisant passer pour un
    fait sur la donnée de l'utilisateur.

    Le refus nomme le plafond **et** dit où il se règle : un message qui donne
    la limite sans dire comment la changer laisse au même point.
    """
    if demande_max_roles is None:
        return
    plafond = int(getattr(loader.config, "mining_max_roles_plafond",
                          MAX_ROLES_PLAFOND))
    if demande_max_roles > plafond:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "mining.max_roles_plafond",
                    "params": {"plafond": plafond,
                               "demande": demande_max_roles}},
        )


@router.post("/threshold-scan")
async def scan_similarity_threshold(
    request: ThresholdScanRequest,
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    user: User = Depends(require_permission_or_dev(MINING_PERMISSION)),
) -> Dict[str, Any]:
    """Évalue plusieurs seuils θ et retourne la courbe couverture / sur-octroi.

    Chaque seuil est un mining approché complet, exécuté avec les mêmes bornes
    que celles qui serviront à l'exécution réelle : la courbe est donc
    comparable au résultat que l'utilisateur obtiendra.
    """
    if not request.thresholds:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "mining.thresholds_required"},
        )

    _verifier_le_plafond_de_roles(request.max_roles, loader)

    if len(request.thresholds) > MAX_THRESHOLDS_PER_SCAN:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "mining.too_many_thresholds",
                "params": {"maximum": MAX_THRESHOLDS_PER_SCAN, "given": len(request.thresholds)},
            },
        )

    if loader.matrix is None or loader.matrix.shape[0] == 0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "mining.no_data_loaded"},
        )

    birth_rights = kb.get_birth_rights()
    all_excluded_rights = sorted(set(request.excluded_rights) | set(birth_rights))

    logger.info(
        "Exploration du seuil : %d seuils, min_users=%d min_rights=%d "
        "max_roles=%d droits exclus=%d",
        len(request.thresholds), request.min_users, request.min_rights,
        request.max_roles, len(all_excluded_rights),
    )

    from src.core.mining.threshold_explorer import ThresholdExplorer

    from src.core.knowledge.perimetre import restreindre

    # La courbe doit décrire ce que produira l'exécution réelle : elle est
    # calculée sur le même périmètre, identités exclues comprises.
    perimetre = restreindre(loader, perimetre_effectif(loader, kb))

    try:
        resultat = await run_in_threadpool(
            ThresholdExplorer(perimetre).scan,
            request.thresholds,
            request.min_users,
            request.min_rights,
            request.max_roles,
            all_excluded_rights,
            request.max_over_granted_pct,
            request.generateurs,
            loader.config.mining_profils_croises_max,
            (request.apport_minimal if request.apport_minimal is not None
             else loader.config.mining_apport_minimal),
            **_reglages_de_selection(loader, request.selection),
            treillis_max=loader.config.mining_treillis_max,
        )
    except ValueError as exc:
        logger.warning("Seuils invalides : %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "mining.invalid_parameters"},
        )
    except Exception:
        logger.exception("Échec de l'exploration du seuil")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "mining.engine_failure"},
        )

    resultat["birth_rights_excluded"] = len(birth_rights)
    return resultat


@router.post("/consolidation-scan")
async def scan_consolidation_threshold(
    request: ConsolidationScanRequest,
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    user: User = Depends(require_permission_or_dev(MINING_PERMISSION)),
) -> Dict[str, Any]:
    """Évalue plusieurs seuils de consolidation et retourne la courbe.

    Le mining est exécuté une seule fois ; seule la consolidation est rejouée
    à chaque seuil. Un balayage coûte donc à peine plus qu'un mining, là où
    l'exploration de θ refait un mining par point.
    """
    if not request.consolidation_thresholds:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "mining.thresholds_required"},
        )

    if len(request.consolidation_thresholds) > MAX_THRESHOLDS_PER_SCAN:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "mining.too_many_thresholds",
                "params": {
                    "maximum": MAX_THRESHOLDS_PER_SCAN,
                    "given": len(request.consolidation_thresholds),
                },
            },
        )

    if request.mining_mode not in MiningMode.ALL:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "mining.unknown_mode", "params": {"mode": request.mining_mode}},
        )

    if request.mining_mode == MiningMode.APPROX and (
        request.similarity_threshold is None or request.max_roles is None
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "mining.approx_parameters_required"},
        )

    if loader.matrix is None or loader.matrix.shape[0] == 0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "mining.no_data_loaded"},
        )

    birth_rights = kb.get_birth_rights()
    all_excluded_rights = sorted(set(request.excluded_rights) | set(birth_rights))

    logger.info(
        "Exploration de la consolidation : %d seuils, mode=%s min_users=%d min_rights=%d",
        len(request.consolidation_thresholds), request.mining_mode,
        request.min_users, request.min_rights,
    )

    try:
        resultat = await run_in_threadpool(
            _scanner_consolidation, loader, request, all_excluded_rights,
            perimetre_effectif(loader, kb),
        )
    except ValueError as exc:
        logger.warning("Seuils de consolidation invalides : %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "mining.invalid_parameters"},
        )
    except Exception:
        logger.exception("Échec de l'exploration de la consolidation")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "mining.engine_failure"},
        )

    resultat["birth_rights_excluded"] = len(birth_rights)
    return resultat


def _scanner_consolidation(
    loader: DataLoader,
    request: "ConsolidationScanRequest",
    excluded_rights: List[str],
    excluded_users: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Exécute le mining une fois, puis balaie les seuils de consolidation."""
    from src.core.knowledge.perimetre import restreindre
    from src.core.mining.consolidation_explorer import ConsolidationExplorer

    # Le champ hérité de MiningRequest n'a pas de sens ici : la consolidation
    # est justement ce qu'on explore, elle ne doit pas être appliquée d'avance.
    request.consolidation_threshold = None
    roles = _run_engine(loader, request, excluded_rights, excluded_users)["roles"]
    loader = restreindre(loader, excluded_users)

    explorateur = ConsolidationExplorer(
        roles, len(loader.habilitations), _droits_par_identite(loader)
    )
    return explorateur.scan(
        thresholds=request.consolidation_thresholds,
        max_granted_loss_pct=request.max_granted_loss_pct,
    )


@router.get("/stats")
async def get_mining_stats(
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    user: User = Depends(require_permission_or_dev("read")),
) -> Dict[str, Any]:
    """Compteurs de synthèse du mining pour le workspace actif."""
    return {
        "validated_roles_count": len(kb.get_validated_roles(role_type="APPLICATIF")),
        "rejected_roles_count": len(kb.get_rejected_roles()),
        "total_users": len(loader.identities),
        "total_rights": len(loader.rights),
    }


@router.post("/explain")
async def explain_roles(
    request: ExplainRolesRequest,
    loader: DataLoader = Depends(get_data_loader),
    user: User = Depends(require_permission_or_dev(MINING_PERMISSION)),
) -> Dict[str, Any]:
    """Explique des rôles par les attributs de leurs porteurs.

    Le mining rend des droits et une population ; il ne dit pas ce que ces
    personnes ont en commun. C'est pourtant la question que pose un
    responsable d'application avant de signer, et sans réponse un modèle
    parfaitement compact reste invalidable.

    L'appel est stateless : les rôles à expliquer sont fournis par l'appelant,
    qui vient de les obtenir du mining. Le serveur ne conserve aucun résultat
    de mining entre deux requêtes, et ce n'est pas le moment de commencer.
    """
    if len(request.roles) > MAX_ROLES_PER_EXPLANATION:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "mining.too_many_roles_to_explain",
                "params": {"maximum": MAX_ROLES_PER_EXPLANATION,
                           "given": len(request.roles)},
            },
        )

    identities = loader.identities
    if identities is None or identities.empty:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "mining.no_identities_loaded"},
        )

    # Les colonnes ne sont pas connues à l'avance : une demande portant sur un
    # attribut absent est une erreur de l'appelant, et elle doit nommer
    # lesquels — un refus qui ne dit pas quoi corriger ne sert à rien.
    inconnus = [nom for nom in request.attributes
                if nom not in identities.columns]
    if inconnus:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "mining.unknown_attributes",
                    "params": {"attributes": ", ".join(sorted(inconnus))}},
        )

    from src.core.mining.pertinence_metier import (
        ReferentielDAttributs,
        expliquer_les_roles,
    )

    referentiel = ReferentielDAttributs(
        identities, DataLoader.COL_USER_ID, request.attributes)

    roles = [{"id": role.id, "users": role.users} for role in request.roles]
    resultat = await run_in_threadpool(
        expliquer_les_roles,
        roles,
        referentiel,
        couverture_minimale=request.min_coverage,
        fiabilite_attendue=request.min_reliability,
        lift_minimal=request.min_lift,
        profondeur=request.max_depth,
        signification_maximale=request.max_p_value,
    )
    resultat["attributes_used"] = referentiel.attributs
    return resultat


class RoleAAnnoter(BaseModel):
    """Le rôle réduit à ce qu'un annotateur peut avoir le droit de voir.

    Le modèle **interdit tout champ inconnu**, et ne déclare aucun champ
    d'identités. La liste des porteurs ne peut donc pas être transmise, même
    par erreur d'un appelant : la garantie tient à la frontière de l'API, pas
    seulement dans le module qui compose la demande.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(...)
    right_count: int = Field(..., ge=0)
    user_count: int = Field(..., ge=0)
    rights: List[str] = Field(default_factory=list)


class TermeDeRegle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attribut: str = Field(...)
    valeur: str = Field(...)


class SuggestNameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: RoleAAnnoter = Field(...)
    #: La règle métier trouvée, quand elle a été demandée. Elle ne sort que si
    #: la matrice du workspace l'autorise pour cet usage.
    regle: List[TermeDeRegle] = Field(default_factory=list)
    locale: str = Field(..., min_length=2, max_length=8)


def _annotateur(loader: DataLoader):
    """Assemble les réglages du serveur et l'autorisation de cet usage.

    Les deux viennent d'endroits différents parce qu'ils relèvent de
    responsables différents : ouvrir une sortie réseau est une décision
    d'infrastructure, autoriser une catégorie de données à l'emprunter pour
    **une question donnée** est une décision de l'administrateur applicatif.

    L'usage est nommé ici, et non deviné : c'est lui qui choisit à la fois la
    ligne de la matrice et, le cas échéant, le point de terminaison propre à
    cette question.
    """
    import os

    from src.api.reglages_du_modele import reglages_pour
    from src.core.annotation.annotateur import Annotateur
    from src.core.annotation.assistance import USAGE_NOMMAGE_DE_ROLE

    usage = USAGE_NOMMAGE_DE_ROLE.code
    return Annotateur(reglages_pour(usage),
                      loader.config.assistance.pour(usage))


@router.get("/annotator")
async def annotator_status(
    loader: DataLoader = Depends(get_data_loader),
    user: User = Depends(require_permission_or_dev(MINING_PERMISSION)),
) -> Dict[str, Any]:
    """État de l'annotateur, et ce qui quitterait le système s'il était utilisé.

    L'adresse n'est pas rendue : seul son hôte l'est. Il suffit à dire si
    l'envoi reste sur la machine, et il ne peut pas transporter de secret
    glissé dans un chemin ou un paramètre.
    """
    from urllib.parse import urlsplit

    from src.core.annotation.assistance import (
        MATIERE_LIBELLES_DE_DROITS, MATIERE_NOMS_VALIDES, MATIERE_REGLE_METIER)

    annotateur = _annotateur(loader)
    reglages, autorisation = annotateur.reglages, annotateur.autorisation
    return {
        # « Actif » vaut ici pour l'écran de nommage : l'infrastructure est en
        # place *et* l'usage est ouvert. Un des deux fermé donne le même
        # résultat pour l'utilisateur — la question ne se pose pas — et
        # l'écran de paramétrage dit lequel des deux il faut ouvrir.
        "actif": reglages.actif and autorisation.actif,
        # Les deux conditions, séparément : l'écran disait « un administrateur
        # peut l'activer sur le serveur » dans les deux cas, ce qui était faux
        # dans la page — il n'y a pas de serveur — et inutile sur un poste,
        # puisque les deux se règlent dans deux cartes différentes.
        "point_de_terminaison": reglages.actif,
        "usage_ouvert": autorisation.actif,
        "usage": autorisation.usage.code,
        "locale": reglages.locale,
        "hote": urlsplit(reglages.adresse).hostname or "",
        "modele": reglages.modele,
        "envoie_libelles_de_droits": autorisation.autorise(MATIERE_LIBELLES_DE_DROITS),
        "envoie_regle_metier": autorisation.autorise(MATIERE_REGLE_METIER),
        "envoie_noms_valides": autorisation.autorise(MATIERE_NOMS_VALIDES),
        # L'explication rédigée est un **autre** usage, avec sa propre
        # autorisation : elle peut être ouverte quand le nommage est fermé, et
        # l'inverse. L'écran porte les deux boutons et doit savoir lequel peut
        # servir — sans quoi il en affiche un qui ne peut rien faire.
        "explication": _etat_de_l_explication(loader),
    }


def _etat_de_l_explication(loader: DataLoader) -> Dict[str, Any]:
    """Ce que l'écran doit savoir de l'usage « explication de rôle »."""
    import os

    from src.api.reglages_du_modele import reglages_pour
    from src.core.annotation.assistance import USAGE_EXPLICATION_DE_ROLE

    code = USAGE_EXPLICATION_DE_ROLE.code
    reglages = reglages_pour(code)
    autorisation = loader.config.assistance.pour(code)
    return {"actif": reglages.actif and autorisation.posable,
            "usage": code,
            "modele": reglages.modele,
            "locale": reglages.locale}


@router.post("/suggest-name")
async def suggest_role_name(
    request: SuggestNameRequest,
    loader: DataLoader = Depends(get_data_loader),
    kb: KnowledgeBase = Depends(get_kb),
    journal: Journal = Depends(get_journal),
    user: User = Depends(require_permission_or_dev(MINING_PERMISSION)),
) -> Dict[str, Any]:
    """Demande une proposition de nom. Elle ne s'applique jamais seule.

    Le résultat remplit un champ que quelqu'un valide. La piste d'audit
    consigne qu'une proposition a été demandée et **quelles catégories de
    données ont quitté le système** — sans leur contenu, qui est déjà dans le
    référentiel.
    """
    from src.core.annotation.annotateur import AnnotateurIndisponible, RienANommer

    annotateur = _annotateur(loader)
    explication = {"regle": [terme.dict() for terme in request.regle]}
    try:
        # Les rôles déjà validés servent d'exemples de nommage. Le classement
        # par proximité se fait ici, sur des droits qui ne quittent pas la
        # machine : seuls les noms retenus sont transmis, et seulement si la
        # matrice du workspace l'autorise pour cet usage.
        # Les applications du rôle sont retrouvées ici, dans le référentiel :
        # le rattachement vient de la donnée, jamais d'une convention de
        # nommage. Elles ne sortent que sous la même autorisation que les
        # libellés de droits.
        rattachement = _build_right_to_application(loader)
        applications = [rattachement[droit] for droit in request.role.rights
                        if droit in rattachement]
        proposition = await run_in_threadpool(
            annotateur.proposer, request.role.dict(), explication,
            request.locale, kb.get_validated_roles(), applications)
    except RienANommer:
        # Ce n'est pas une panne : le modèle répondrait, et c'est le problème.
        # Privé de toute matière, il invente une finalité métier.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "annotator.nothing_to_name"},
        )
    except AnnotateurIndisponible as erreur:
        logger.info("Aucune proposition de nom : %s", erreur)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "annotator.unavailable"},
        )

    journal.consigner(
        Action.ROLE_ANNOTE, "role", request.role.id,
        {"usage": proposition["usage"],
         "modele": proposition["modele"],
         "categories": ", ".join(proposition["categories_transmises"]),
         "hors_du_poste": not annotateur.reglages.locale},
    )
    return proposition
