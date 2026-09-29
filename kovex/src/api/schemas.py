from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Any, Dict, List, Literal, Optional
from src.core.data.politique_cles import (
    REFERENTIELS,
    ActionCleVide,
    ActionDoublon,
    PolitiqueCles,
)
from src.core.data.transformations import OPERATIONS_AVEC_VALEUR, Operation
from src.core.knowledge.privileges import PLACE_JETON, PLACES
from src.core.mining.approximate_miner import (APPORT_MINIMAL,
                                               MAX_ROLES_PLAFOND,
                                               PROFILS_CROISES_MAX,
                                               TREILLIS_MAX)
from src.core.knowledge.derogations import DUREE_MAX_JOURS, PREAVIS_JOURS
from src.core.knowledge.apprentissage import (DECISIONS_MIN, PAR_VERDICT_MIN,
                                              REGULARISATION)
from src.core.mining.selection_exacte import (DELAI_PAR_DEFAUT_S,
                                              EFFORT_PAR_DEFAUT, SELECTIONS,
                                              SELECTION_PAR_DEFAUT)
from src.core.data.troncature import BORNES_USUELLES
from src.infrastructure.branding import NOM_PRODUIT


# --- MODÈLES DE CONFIGURATION PAR FICHIER ---

class PerFileConfig(BaseModel):
    """Configuration pour un fichier de données individuel."""
    path: str
    delimiter: str = ";"
    encoding: str = "utf-8"
    # Colonne ID principale (utilisée par Identities, Apps, Rights)
    id_column: str = "" 
    # Colonne de rattachement applicatif dans le référentiel des droits
    app_id_column: str = ""
    # Colonnes spécifiques à Habilitations
    user_id_column: str = "" 
    right_id_column: str = "" 


class CorrespondanceDUnFichier(BaseModel):
    """Ce que la personne déclare d'un fichier au moment de le charger.

    Le produit ne connaît pas les colonnes à l'avance. Il les propose, lues
    dans le fichier ; c'est cette déclaration-ci qui fait foi, et c'est elle
    qui est écrite dans la configuration du workspace.

    **Aucun champ inconnu n'est accepté** : une correspondance qui porterait un
    chemin de fichier ferait écrire n'importe où par une route d'import.

    Une chaîne vide est une déclaration valide et veut dire « ce fichier ne
    porte pas cette clé » — le fichier des habilitations n'a pas d'identifiant
    propre.
    """

    model_config = ConfigDict(extra="forbid")

    separateur: str = Field(min_length=1, max_length=1)
    encodage: str = Field(min_length=1, max_length=32)
    id_column: str = ""
    app_id_column: str = ""
    user_id_column: str = ""
    right_id_column: str = ""

    @field_validator("separateur")
    @classmethod
    def _separateur_connu(cls, valeur: str) -> str:
        from src.core.data.inspection import SEPARATEURS

        if valeur not in SEPARATEURS:
            raise ValueError("séparateur non pris en charge")
        return valeur

    @field_validator("encodage")
    @classmethod
    def _encodage_connu(cls, valeur: str) -> str:
        from src.core.data.inspection import ENCODAGES

        if valeur not in ENCODAGES:
            raise ValueError("encodage non pris en charge")
        return valeur


class CorrespondanceDesFichiers(BaseModel):
    """La correspondance déclarée, référentiel par référentiel.

    Les clés sont celles des référentiels du produit, et rien d'autre : un
    référentiel inconnu écrirait une section parasite dans la configuration.
    """

    model_config = ConfigDict(extra="forbid")

    identities: Optional[CorrespondanceDUnFichier] = None
    applications: Optional[CorrespondanceDUnFichier] = None
    rights: Optional[CorrespondanceDUnFichier] = None
    habs: Optional[CorrespondanceDUnFichier] = None


class FileGroupConfig(BaseModel):
    """Groupe de configuration pour tous les fichiers sources."""
    identities: PerFileConfig = PerFileConfig(
        path="data/identities.csv", 
        id_column="ID_utilisateur"
    )
    applications: PerFileConfig = PerFileConfig(
        path="data/applications.csv", 
        id_column="ID_application"
    )
    rights: PerFileConfig = PerFileConfig(
        path="data/droits.csv", 
        id_column="ID_droit"
    )
    # Valeurs par défaut pour les deux IDs d'Habilitation
    habs: PerFileConfig = PerFileConfig(
        path="data/habilitations.csv", 
        user_id_column="ID_utilisateur", 
        right_id_column="ID_droit"
    )


# Alias pour compatibilité avec l'ancien code
FileConfig = PerFileConfig


class KeyPolicyModel(BaseModel):
    """Ce que l'utilisateur veut faire d'une clé vide et d'un doublon.

    Les valeurs acceptées viennent des énumérations du noyau : le schéma d'API
    et le chargeur ne peuvent pas diverger sur ce qu'est une action valide.
    Les valeurs de départ aussi — elles sont portées par `PolitiqueCles`, et
    non recopiées ici, pour qu'un changement de défaut n'ait qu'un seul
    endroit où être fait.
    """
    empty_key: ActionCleVide = PolitiqueCles().cle_vide
    duplicate_key: ActionDoublon = PolitiqueCles().doublon


class KeyPolicyOverrideModel(BaseModel):
    """Surcharge d'un référentiel : ce qui n'est pas dit hérite du défaut.

    Les champs sont facultatifs, et c'est le point : avec des valeurs de
    départ, déclarer « pour les habilitations, garder la dernière occurrence »
    figerait au passage le traitement des clés vides sur la valeur du modèle
    plutôt que sur le défaut du workspace. L'utilisateur croirait n'avoir
    changé qu'une chose.
    """
    empty_key: Optional[ActionCleVide] = None
    duplicate_key: Optional[ActionDoublon] = None


class PerimeterRuleModel(BaseModel):
    """Une règle de périmètre, telle que l'écran l'envoie.

    Le sort des identités sans valeur est **obligatoire** : sur un référentiel
    réel la colonne est incomplète, et un défaut trancherait à la place de
    l'utilisateur du sort d'une population qu'il n'a pas regardée.
    """

    attribut: str = Field(..., min_length=1)
    sens: Literal["keep", "discard"]
    valeurs: List[str] = Field(..., min_length=1)
    sans_valeur: Literal["keep", "discard"]


class UsersExclusion(BaseModel):
    """Écartement de plusieurs identités, avec le motif de la décision."""

    user_ids: List[str] = Field(..., min_length=1)
    reason: Optional[str] = ""


class PerimeterRules(BaseModel):
    """L'état complet des règles. Un remplacement, jamais un ajout."""

    rules: List[PerimeterRuleModel] = Field(default_factory=list)


class DataQualityModel(BaseModel):
    """Politique du workspace : un défaut, et des surcharges par référentiel."""
    default: KeyPolicyModel = KeyPolicyModel()
    files: Dict[str, KeyPolicyOverrideModel] = {}

    @field_validator("files")
    @classmethod
    def _referentiels_connus(cls, valeur: Dict[str, KeyPolicyOverrideModel]):
        """Refuse une surcharge portant sur un référentiel inexistant.

        Sans ce contrôle, une faute de frappe — « habs » écrit « hab » —
        s'enregistrait, s'affichait, et n'était jamais appliquée.
        """
        inconnus = sorted(set(valeur) - set(REFERENTIELS))
        if inconnus:
            raise ValueError(
                f"référentiel inconnu : {', '.join(inconnus)} "
                f"(attendu : {', '.join(REFERENTIELS)})"
            )
        return valeur


class TransformationRuleModel(BaseModel):
    """Une transformation appliquée à une colonne d'un fichier source.

    Le nom de colonne est celui du **fichier de l'utilisateur**, pas le nom
    standardisé : les règles s'appliquent avant la standardisation, et c'est
    l'en-tête qu'il a sous les yeux qu'il saisit ici.
    """
    column: str
    operation: Operation
    value: str = ""

    @field_validator("column")
    @classmethod
    def _colonne_renseignee(cls, valeur: str) -> str:
        if not valeur.strip():
            raise ValueError("le nom de colonne est obligatoire")
        return valeur

    @model_validator(mode="after")
    def _valeur_coherente(self) -> "TransformationRuleModel":
        """Une valeur exigée doit être là ; une valeur inutile est refusée.

        Accepter un séparateur sur un « passer en majuscules » enregistrerait
        un réglage que rien n'applique — et l'utilisateur croirait l'avoir posé.
        """
        exige = self.operation in OPERATIONS_AVEC_VALEUR
        if exige and not self.value:
            raise ValueError(
                f"l'opération {self.operation.value} exige une valeur")
        if not exige and self.value:
            raise ValueError(
                f"l'opération {self.operation.value} n'accepte pas de valeur")
        return self


class AppConfigModel(BaseModel):
    """
    Modèle principal de configuration de l'application.
    
    CORRECTION: Suppression du doublon 'files: Dict[str, FileConfig] = {}'
    qui causait une erreur de définition Pydantic.
    """
    # Configuration des fichiers sources (UN SEUL champ 'files')
    files: FileGroupConfig = FileGroupConfig()
    
    # Bornes de mining du workspace.
    #
    # `mining_gamma_min` et `mining_max_depth` ont été retirés : vestiges du
    # mode « fuzzy » supprimé, ils figuraient ici, dans la configuration et
    # dans l'écran de paramétrage, mais aucun moteur ne les lisait — et leurs
    # valeurs livrées se contredisaient d'un fichier à l'autre (0,5 contre 75).
    # La profondeur de croisement du mining métier vient de la requête.
    mining_min_users: int = 3
    mining_min_rights: int = 2
    #: Au-delà de ce rapport (valeurs distinctes / identités), un attribut est
    #: signalé comme trop discriminant pour porter un rôle métier.
    mining_attribute_max_cardinality_ratio: float = 0.5
    
    # Seuils de santé des données
    health_threshold_alert: float = 10.0
    health_threshold_critical: float = 50.0

    #: Fragments de nom qui signalent un droit sensible dans les écrans de
    #: validation. Vide par défaut, et c'est délibéré : l'interface décidait
    #: jusqu'ici qu'un droit était sensible si son nom contenait « ADMIN » ou
    #: « SUPPRESSION ». Cette règle est écrite en français, suppose une
    #: convention de nommage, et se trompe dans les deux sens — un droit
    #: « ADMINistratif » était signalé, un droit « DELETE_ALL » ne l'était pas.
    #: La liste appartient au client, qui seul connaît son référentiel.
    sensitive_right_keywords: List[str] = []

    #: Fragments d'identifiant qui signalent un compte à privilèges — le
    #: compte d'administration d'une personne, à côté de son compte nominatif.
    #: Vide par défaut, pour la raison qui vaut ci-dessus et une de plus : ici,
    #: se tromper ne produit pas un badge en trop, il produit une revue qui
    #: passe à côté du compte qui pouvait tout faire.
    privileged_account_keywords: List[str] = []
    #: La colonne d'identités où chercher ces fragments. Vide : l'identifiant
    #: du compte, seule colonne que le produit connaisse par construction. Un
    #: référentiel qui porte un `type_compte` explicite se déclare ici plutôt
    #: que de se deviner dans un identifiant.
    privileged_account_column: str = ""
    #: Où le fragment doit se trouver dans la valeur. Voir `PLACES` : un
    #: fragment cherché n'importe où marque `ADMINISTRATIF`, cherché comme
    #: jeton il ne marque que `ADM_X` et `X.ADM`.
    privileged_account_place: str = PLACE_JETON

    @field_validator("privileged_account_place")
    @classmethod
    def _place_connue(cls, valeur):
        if valeur not in PLACES:
            raise ValueError(
                f"place inconnue : {valeur!r} (attendu : {', '.join(PLACES)})")
        return valeur
    
    #: Politique de qualité des clés, déclarée par l'utilisateur. Le défaut
    #: — écarter les lignes sans clé, garder la première occurrence d'un
    #: doublon — n'est pas une règle du produit : c'est la valeur de départ
    #: d'un réglage, et l'écran de paramétrage la montre comme telle.
    data_quality: DataQualityModel = DataQualityModel()

    #: Transformations appliquées aux fichiers sources, par référentiel, dans
    #: l'ordre déclaré. Vide par défaut : le produit ne présume aucune
    #: correction à faire sur le référentiel d'un client.
    transformations: Dict[str, List[TransformationRuleModel]] = {}

    @field_validator("transformations")
    @classmethod
    def _referentiels_de_transformation_connus(cls, valeur):
        inconnus = sorted(set(valeur) - set(REFERENTIELS))
        if inconnus:
            raise ValueError(
                f"référentiel inconnu : {', '.join(inconnus)} "
                f"(attendu : {', '.join(REFERENTIELS)})")
        return valeur

    #: La convention de nommage des droits, telle que l'utilisateur la
    #: déclare : la colonne à découper, le séparateur, et le rôle de chaque
    #: segment. Ces trois champs manquaient au modèle. L'écran les envoyait,
    #: Pydantic les ignorait — un champ inconnu est écarté sans bruit — et la
    #: convention disparaissait entre la requête et l'écriture. Relu, l'écran
    #: montrait des champs vides, que le produit traite comme « aucune
    #: convention », le seul état qu'il tient pour une décision.
    right_naming_column: str = ""
    right_naming_separator: str = ""
    #: Un rôle par segment, dans l'ordre du découpage ; une chaîne vide pour un
    #: segment que le client ne veut pas nommer. Voir `nommage.ROLES`.
    right_naming_positions: List[str] = []

    # La convention n'est pas validée ici, mais à l'enregistrement. Ce modèle
    # sert aussi à **relire** la configuration : y refuser une convention
    # illisible rendrait l'écran de paramétrage inaccessible sur le seul
    # workspace où il faut aller la corriger. Le chargeur a déjà cette
    # position — il signale et n'applique rien plutôt que de refuser le
    # workspace entier.

    #: Nombre de profils distincts au-delà duquel le croisement des profils
    #: n'est pas tenté dans le mining approché. Le croisement compare les
    #: profils deux à deux : son coût croît comme le carré de leur nombre.
    #: Zéro est un choix — ne jamais croiser ; un nombre négatif n'en est pas
    #: un. Pas de valeur écrite ici : elle vient du schéma du workspace, seul
    #: endroit du produit où ce nombre est défini.
    mining_profils_croises_max: int = Field(default=PROFILS_CROISES_MAX, ge=0)

    #: Candidats que le treillis — recroiser les terrains communs jusqu'à ce
    #: que plus rien de nouveau n'apparaisse — peut ajouter. Zéro est un
    #: choix : ne jamais recroiser, même la case cochée.
    mining_treillis_max: int = Field(default=TREILLIS_MAX, ge=0)

    #: Nombre de rôles maximal qu'une demande de mining peut réclamer.
    #:
    #: Borne d'exploitation, pas choix métier : elle protège le serveur d'une
    #: demande absurde. Un plafond de zéro n'aurait aucun sens — il
    #: interdirait tout mining — d'où `ge=1`. Aucune borne haute : c'est celui
    #: qui exploite le serveur qui sait ce que sa machine encaisse, et une
    #: borne haute écrite ici reproduirait exactement le défaut corrigé.
    mining_max_roles_plafond: int = Field(default=MAX_ROLES_PLAFOND, ge=1)

    #: Nombre d'habilitations non encore couvertes qu'un rôle doit apporter
    #: pour être retenu. `mining_min_users` et `mining_min_rights` disent
    #: quelle **taille** un rôle doit avoir ; celui-ci dit ce qu'il doit
    #: **expliquer**. Un vaut le comportement historique : aucun plancher.
    mining_apport_minimal: int = Field(default=APPORT_MINIMAL, ge=1)

    #: Comment les rôles sont choisis parmi les candidats, parmi `SELECTIONS`.
    #: `gloutonne` retient à chaque pas le candidat qui explique le plus ;
    #: `exacte` cherche, à θ = 1, le plus petit ensemble qui explique autant.
    mining_selection: str = Field(default=SELECTION_PAR_DEFAUT)
    #: Nœuds de branchement accordés à la sélection exacte. Une borne en
    #: nœuds, et non en temps, garde le résultat reproductible.
    mining_selection_effort: int = Field(default=EFFORT_PAR_DEFAUT, ge=1)
    #: Délai de protection de la sélection exacte, en secondes.
    mining_selection_delai_s: float = Field(default=DELAI_PAR_DEFAUT_S, gt=0)

    @field_validator("mining_selection")
    @classmethod
    def _selection_connue(cls, valeur: str) -> str:
        if valeur not in SELECTIONS:
            raise ValueError(f"sélection inconnue : {valeur}")
        return valeur

    #: Comptes qui, tombant exactement dessus, font soupçonner un export
    #: tronqué à la source. Ce sont les plafonds des **systèmes sources du
    #: client** — pagination d'annuaire, seuil de vue de liste, limite de
    #: lignes d'un tableur — et non une propriété du produit. Une liste vide
    #: éteint le contrôle, ce qui est un choix légitime sur un référentiel
    #: exporté sans plafond.
    troncature_bornes: List[int] = Field(default_factory=lambda: list(BORNES_USUELLES))

    #: Les bornes de l'exception assumée. Déclarées ici pour que l'écran des
    #: paramètres les montre et les écrive : elles existaient dans le document
    #: du workspace sans que personne puisse les voir.
    derogation_duree_max_jours: int = Field(default=DUREE_MAX_JOURS, ge=1)
    derogation_preavis_jours: int = Field(default=PREAVIS_JOURS, ge=0)
    #: Une dérogation doit-elle citer un contrôle compensatoire qui tourne
    #: pour couvrir son constat ?
    derogation_controle_exige: bool = False
    #: Une dérogation doit-elle être approuvée par une autre personne que
    #: celle qui la demande ?
    derogation_approbation_exigee: bool = False

    #: Ce que l'apprentissage des décisions exige avant de rendre un score, et
    #: la force qui resserre ses coefficients. Un score appris sur six
    #: décisions se lirait comme un avis.
    apprentissage_decisions_min: int = Field(default=DECISIONS_MIN, ge=2)
    apprentissage_par_verdict_min: int = Field(default=PAR_VERDICT_MIN, ge=1)
    apprentissage_regularisation: float = Field(default=REGULARISATION, ge=0)

    #: Niveaux de sévérité des règles de séparation, du plus grave au moins
    #: grave. Écrits par le client, dans ses mots : aucun n'est livré.
    sod_severites: List[str] = Field(default_factory=list)

    @field_validator("sod_severites")
    @classmethod
    def _severites_lisibles(cls, valeur):
        """Des niveaux nommés, distincts, d'une longueur de libellé.

        Un doublon rendrait l'ordre ambigu — lequel des deux « élevé » est le
        plus grave ? — et un niveau vide ne se choisit pas.
        """
        from src.core.knowledge.separation import LIBELLE_MAX

        niveaux = [str(niveau).strip() for niveau in valeur]
        if any(not niveau or len(niveau) > LIBELLE_MAX for niveau in niveaux):
            raise ValueError("un niveau de sévérité est vide ou trop long")
        if len(set(niveaux)) != len(niveaux):
            raise ValueError("deux niveaux de sévérité portent le même nom")
        return niveaux

    @field_validator("troncature_bornes")
    @classmethod
    def _bornes_positives(cls, valeur):
        """Une borne nulle ou négative ne peut être le plafond de rien.

        Refusée plutôt qu'écartée en silence : une liste à moitié acceptée
        éteindrait une partie du contrôle sans que l'écran ne le montre.
        """
        fautives = [borne for borne in valeur if borne <= 0]
        if fautives:
            raise ValueError(
                "borne d'export invalide : "
                + ", ".join(str(borne) for borne in fautives))
        return sorted(set(valeur))

    # Titre de l'application
    app_title: str = NOM_PRODUIT


# --- RESTE DES SCHEMAS ---

class CleaningReport(BaseModel):
    """
    Rapport de nettoyage des données (Schéma complet pour Pydantic).
    """
    
    # --- Métriques de Cohérence Relationnelle ---
    orphan_rights_count: int
    orphan_users_count: int
    forest_users_count: int
    broken_habs_count: int
    
    # --- Doublons d'identifiants dans un référentiel ---
    # Calculées par le DataLoader. Elles restent optionnelles : un rapport
    # produit par un autre chemin (cleaner.py) ne les porte pas, et les
    # déclarer obligatoires faisait échouer la validation à chaque appel de
    # /reports/cleaning.
    duplicate_users_count: int = 0
    duplicate_rights_count: int = 0
    duplicate_applications_count: int = 0
    null_issues_count: int = 0
    
    # --- Intégrité du référentiel droits / applications ---
    # Ces contrôles n'ont de sens que si l'utilisateur a associé les colonnes
    # correspondantes. `checks_available` dit lesquels ont pu être calculés :
    # un compteur à zéro pour un contrôle indisponible se lirait « aucune
    # anomalie », ce qui serait faux.
    unused_rights_count: int = 0
    rights_without_app_count: int = 0
    unknown_app_refs_count: int = 0
    empty_applications_count: int = 0
    unused_applications_count: int = 0
    checks_available: Dict[str, bool] = {}

    # --- Détails des IDs (CRITICAL pour l'affichage du lien) ---
    orphan_users_list: List[str] = []
    orphan_rights_list: List[str] = []
    forest_users_list: List[str] = []
    unused_rights_list: List[str] = []
    rights_without_app_list: List[str] = []
    unknown_app_refs_list: List[str] = []
    empty_applications_list: List[str] = []
    unused_applications_list: List[str] = []
    duplicate_users_list: List[str] = []
    duplicate_rights_list: List[str] = []
    duplicate_applications_list: List[str] = []

    # --- Politique de qualité des clés ---
    # Ce que le chargeur a fait des clés vides et des doublons, référentiel par
    # référentiel, selon ce que l'utilisateur a déclaré. Optionnel : un rapport
    # produit par un autre chemin que le chargeur ne le porte pas, et le
    # déclarer obligatoire ferait échouer la validation de /reports/cleaning.
    key_policy: Dict[str, Any] = {}

    # --- Transformations appliquées au chargement ---
    transformations: Dict[str, Any] = {}

    # --- Résumé et Temps ---
    last_cleaned: str
    issues_summary: List[Dict[str, Any]]


class GlobalStats(BaseModel):
    """Statistiques globales du tableau de bord."""
    total_users: int
    total_applications: int
    total_rights: int
    total_habilitations: int
    top_applications: Dict[str, int]
    avg_rights_per_user: float
    health_score: Optional[float] = None
    #: Clé i18n de l'état de santé, traduite par le client.
    health_status_key: Optional[str] = None
    #: Écart entre les deux derniers relevés du référentiel, ou None quand il
    #: n'y en a qu'un. Un produit qui ne peut pas comparer n'affiche pas de
    #: tendance : il n'a rien à dire, il se tait.
    evolution: Optional[Dict[str, Any]] = None


class MiningStats(BaseModel):
    """Statistiques de la matrice de mining."""
    matrix_users: int
    matrix_rights: int
    total_links: int
    density_percent: float


class MiningResult(BaseModel):
    """Résultat d'une opération de mining."""
    total_roles_found: int
    top_roles: List[Dict[str, Any]]


class RoleCreate(BaseModel):
    """Schéma pour la création d'un rôle."""
    name: str
    description: str
    role_type: str = "APPLICATIF"
    rights: List[str] = []
    sub_role_ids: List[str] = []
    additional_rights: List[str] = []


class RoleRBAC(BaseModel):
    """Représentation complète d'un rôle RBAC."""
    id: str
    name: str
    description: str
    role_type: str
    rights: List[str]
    sub_roles: List[str]
    additional_rights: List[str]
    user_count_potential: int


class MiningRequest(BaseModel):
    """Requête pour lancer une opération de mining."""
    min_users: int = 3
    excluded_rights: List[str] = []
    excluded_users: List[str] = []
    mining_mode: str = "EXACT"



# Schémas pour le Mining Métier
class IdentityAttribute(BaseModel):
    """Colonne d'identite proposee comme critere de mining metier.

    Le libelle n'est pas construit cote serveur : on expose une cle i18n et
    ses parametres, le frontend se charge de la traduction.
    """
    name: str
    description_key: Optional[str] = None
    description_params: Dict[str, Any] = {}
    distinct_count: int = 0
    total_count: int = 0
    cardinality_ratio: float = 0.0
    recommended: bool = True
    is_mandatory: bool = False

class IdentityAttributesResponse(BaseModel):
    attributes: List[IdentityAttribute]


class IndicateursDeDecision(BaseModel):
    """Ce que la personne avait sous les yeux au moment de décider d'un candidat.

    Tous les champs sont facultatifs — un rôle peut être décidé sans que son
    explication métier ait été demandée — mais **aucun champ inconnu n'est
    accepté**. Un dictionnaire libre finirait par transporter la liste des
    porteurs ou des valeurs d'attributs RH, c'est-à-dire des données
    personnelles, dans un fichier qui s'exporte avec le workspace.

    La présence de cet objet est aussi ce qui distingue une **décision sur un
    candidat du mining** d'une composition manuelle : un rôle bâti à la main
    n'a pas d'indicateurs, n'est l'exemple de rien, et n'entre pas dans
    l'historique.

    Rien ici n'est un jugement : ce sont les chiffres du rôle, tels qu'affichés.
    """

    model_config = ConfigDict(extra="forbid")

    #: Le rôle tel que le mining l'a rendu.
    right_count: Optional[int] = None
    user_count: Optional[int] = None
    over_granted: Optional[int] = None
    fit_pct: Optional[float] = None
    redundancy_pct: Optional[float] = None
    sub_roles: Optional[int] = None
    absorbs: Optional[int] = None

    #: Son explication métier, quand elle a été demandée. `termes_de_regle`
    #: compte les critères de la règle et ne recopie pas leurs valeurs.
    explicable: Optional[bool] = None
    termes_de_regle: Optional[int] = None
    purete: Optional[float] = None
    couverture: Optional[float] = None
    lift: Optional[float] = None
    p_valeur: Optional[float] = None
    exceptions: Optional[int] = None
    sur_octroi: Optional[int] = None
