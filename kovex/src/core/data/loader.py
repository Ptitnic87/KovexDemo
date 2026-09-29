# src/core/data/loader.py
"""
DataLoader refactorisé avec injection de dépendances propre.
- Plus de singleton global
- Thread-safe
- Testable
- Configuration explicite
"""

import pandas as pd
import numpy as np
from scipy.sparse import csr_matrix
from typing import Dict, Any, Optional, List, Tuple, Sequence
from pathlib import Path
import hashlib
import math
import logging
import threading

from src.core.data.transformations import (
    Pipeline,
    RapportRegle,
    RegleInvalide,
)
from src.core.data.politique_cles import (
    MOTIF_CLE_VIDE,
    REFERENTIELS,
    PolitiqueQualite,
    RapportPolitique,
    ValeurDePolitiqueInconnue,
)
from src.core.data.politique_cles import appliquer as appliquer_politique
from src.core.annotation.assistance import Assistance
from src.core.data.coherence import Reglages as CoherenceReglages
from src.core.data.transformations import appliquer as appliquer_transformations
from src.core.knowledge.nommage import (
    ROLE_APPLICATION,
    Convention,
    ConventionInvalide,
    collisions as collisions_de_nommage,
    depuis_la_configuration as convention_depuis_la_configuration,
    enrichir as enrichir_par_le_nommage,
)
from src.core.knowledge.privileges import (
    DeclarationInvalide,
    Marqueur,
    depuis_la_configuration as marqueur_depuis_la_configuration,
)
# La borne du croisement des profils est définie là où le croisement est
# écrit — un seul endroit du produit porte ce nombre. Le gestionnaire de
# workspaces l'importe déjà de la même façon.
from src.core.mining.approximate_miner import (APPORT_MINIMAL,
                                               MAX_ROLES_PLAFOND,
                                               PROFILS_CROISES_MAX,
                                               TREILLIS_MAX)
from src.core.mining.selection_exacte import (DELAI_PAR_DEFAUT_S,
                                              EFFORT_PAR_DEFAUT, SELECTIONS,
                                              SELECTION_PAR_DEFAUT)
from src.core.data.troncature import BORNES_USUELLES


logger = logging.getLogger(__name__)


class DataLoaderConfig:
    """Configuration du DataLoader - remplace le dict informe."""
    
    def __init__(
        self,
        files_config: Dict[str, Dict[str, Any]],
        mining_min_users: int = 5,
        mining_min_rights: int = 2,
        mining_attribute_max_cardinality_ratio: float = 0.5,
        health_threshold_alert: float = 10.0,
        health_threshold_critical: float = 50.0,
        birth_rights_alert_pct: float = 90.0,
        mining_profils_croises_max: int = PROFILS_CROISES_MAX,
        mining_treillis_max: int = TREILLIS_MAX,
        mining_max_roles_plafond: int = MAX_ROLES_PLAFOND,
        mining_apport_minimal: int = APPORT_MINIMAL,
        mining_selection: str = SELECTION_PAR_DEFAUT,
        mining_selection_effort: int = EFFORT_PAR_DEFAUT,
        mining_selection_delai_s: float = DELAI_PAR_DEFAUT_S,
        troncature_bornes: Optional[Sequence[int]] = None,
        sod_severites: Optional[Sequence[str]] = None,
        assistance: Optional[Assistance] = None,
        coherence: Optional[CoherenceReglages] = None,
        base_autorisee: Optional[str] = None,
        politique_qualite: Optional[PolitiqueQualite] = None,
        politique_invalide: Optional[Dict[str, Any]] = None,
        pipeline: Optional[Pipeline] = None,
        pipeline_invalide: Optional[Dict[str, Any]] = None,
        privileges: Optional[Marqueur] = None,
        privileges_invalide: Optional[Dict[str, Any]] = None,
        naming: Optional[Convention] = None,
        naming_invalide: Optional[Dict[str, Any]] = None,
    ):
        self.files = files_config
        # Dossier hors duquel aucun fichier source ne peut être lu.
        #
        # Les chemins des fichiers viennent de la configuration du workspace,
        # que l'API laisse écrire. Sans cette borne, y placer `.env` puis
        # consulter l'explorateur rendait le contenu du fichier — donc la clé
        # de signature des jetons — par une réponse d'API parfaitement normale.
        #
        # `None` signifie « aucune borne » : c'est le cas des tests et du banc
        # en ligne de commande, qui construisent leurs jeux hors des
        # workspaces. Toute configuration venant d'un workspace en pose une.
        self.base_autorisee = base_autorisee
        self.mining_min_users = mining_min_users
        self.mining_min_rights = mining_min_rights
        # Au-dela de ce ratio (valeurs distinctes / lignes), un attribut est trop
        # discriminant pour porter un role metier (ex : un nom de famille).
        # Reglable par workspace dans config.json.
        self.mining_attribute_max_cardinality_ratio = mining_attribute_max_cardinality_ratio
        self.health_threshold_alert = health_threshold_alert
        self.health_threshold_critical = health_threshold_critical
        # Part de la population au-delà de laquelle un droit ne distingue plus
        # personne. Sert à signaler qu'un mining part handicapé, pas à exclure
        # d'autorité : le choix reste à l'utilisateur.
        self.birth_rights_alert_pct = birth_rights_alert_pct
        # Nombre de profils distincts au-delà duquel le croisement des
        # profils n'est pas tenté dans le mining approché. Ce n'est pas un
        # choix métier : le croisement est quadratique, et c'est la limite
        # au-delà de laquelle l'écran cesserait de répondre. Réglable par
        # workspace : vingt mille identités ne portent pas le même nombre de
        # profils distincts que trois cents.
        self.mining_profils_croises_max = mining_profils_croises_max
        # Candidats que le treillis — les croisements successifs — peut
        # ajouter. Même nature que la borne précédente : le temps et la
        # mémoire qu'on accepte de payer, annoncés quand ils mordent.
        self.mining_treillis_max = mining_treillis_max
        # Nombre de rôles maximal qu'une demande peut réclamer. Borne
        # d'exploitation, pas choix métier : elle protège le serveur d'une
        # demande absurde. Réglable, parce qu'un référentiel qui porte plus
        # de rôles candidats que la borne affiche sinon un « plafond
        # atteint » que rien ne permet de lever — et l'avertissement parle
        # alors du produit en se faisant passer pour un fait sur la donnée.
        self.mining_max_roles_plafond = mining_max_roles_plafond
        # Ce qu'un rôle doit **expliquer** pour exister, en
        # habilitations non encore couvertes. `mining_min_users` et
        # `mining_min_rights` disent quelle taille il doit avoir ;
        # rien ne disait ce qu'il doit apporter, et le glouton
        # retenait donc un rôle expliquant une seule habilitation.
        self.mining_apport_minimal = mining_apport_minimal
        # Comment les rôles sont choisis parmi les candidats : le glouton, ou
        # le plus petit ensemble qui explique autant. Aucune n'est meilleure
        # en soi — la plus courte perd les rôles réels sur une donnée
        # bruitée —, le choix appartient donc au workspace. Une valeur
        # inconnue retombe sur le repli plutôt que de faire échouer le
        # chargement : le schéma du workspace la refuse déjà à l'écriture.
        self.mining_selection = (mining_selection if mining_selection in SELECTIONS
                                 else SELECTION_PAR_DEFAUT)
        self.mining_selection_effort = mining_selection_effort
        self.mining_selection_delai_s = mining_selection_delai_s
        # Comptes tombant exactement sur une borne d'export connue. Ce sont
        # les plafonds des **systèmes sources du client**, pas une propriété du
        # produit : mille pour une pagination d'annuaire, cinq mille pour un
        # seuil de vue de liste. Une liste vide éteint le contrôle, et c'est un
        # choix légitime sur un référentiel exporté sans plafond.
        # Les niveaux de sévérité des règles de séparation, du plus grave au
        # moins grave. Ils appartiennent au client : le produit ne sait pas ce
        # qu'est un risque « critique » chez lui, et n'en livre aucun. Une
        # liste vide laisse les règles sans sévérité — et l'écran le dit.
        self.sod_severites = tuple(str(niveau) for niveau in (sod_severites or ())
                                   if str(niveau).strip())
        self.troncature_bornes = (
            tuple(troncature_bornes) if troncature_bornes is not None
            else BORNES_USUELLES)
        # Ce que le produit a le droit de demander à un modèle pour ce
        # workspace, usage par usage. Une matrice absente n'ouvre rien : un
        # oubli de configuration ne divulgue pas, et il ne se devine pas.
        self.assistance = assistance or Assistance()
        # Seuils du repérage de cohérence des valeurs. Réglables par workspace :
        # ce sont des seuils de bruit, et ils ne valent pas la même chose sur
        # trois cents identités et sur trois cent mille.
        self.coherence = coherence or CoherenceReglages()
        # Ce que l'utilisateur a déclaré vouloir faire d'une clé vide et d'un
        # doublon, par référentiel. Une politique absente vaut la politique par
        # défaut : écarter les lignes sans clé, garder la première occurrence.
        self.politique_qualite = politique_qualite or PolitiqueQualite()
        # Message d'une politique illisible, conservé pour être signalé dans le
        # rapport de qualité. Un réglage mal orthographié dans `config.json` ne
        # doit pas empêcher l'application de démarrer, mais il ne doit pas non
        # plus passer pour un réglage actif.
        self.politique_invalide = politique_invalide
        # Transformations à appliquer aux fichiers sources avant toute chose.
        # Un pipeline vide est le cas normal : le produit ne présume aucune
        # correction à faire sur le référentiel d'un client.
        self.pipeline = pipeline or Pipeline()
        # Message d'une règle illisible, signalé comme l'est une politique
        # illisible : le chargement se poursuit sans elle, et le rapport le dit.
        self.pipeline_invalide = pipeline_invalide
        # Ce qui, dans un identifiant de compte, signale un compte à
        # privilèges. Un marqueur vide est le cas normal : le produit ne
        # présume aucune convention de nommage, et ne marque rien tant que le
        # client n'a rien déclaré.
        self.privileges = privileges or Marqueur()
        # Message d'une déclaration illisible, signalé comme le sont les deux
        # précédentes. Le silence serait ici le plus coûteux des trois : une
        # place mal orthographiée qui ne marquerait plus personne laisserait
        # croire qu'il n'y a pas de compte à privilèges.
        self.privileges_invalide = privileges_invalide
        #: La convention de nommage des droits, telle que le client l'a
        #: déclarée. Vide par défaut : le produit ne présume aucune convention.
        self.naming = naming or Convention()
        self.naming_invalide = naming_invalide
        #: Le document du workspace, pour les réglages sans attribut. Vide
        #: quand la configuration est construite directement.
        self.document: Dict[str, Any] = {}
    
    def get(self, key: str, default: Any = None) -> Any:
        """Un réglage : l'attribut normalisé s'il existe, sinon le document.

        `get` ne rendait que les attributs. Trois familles de réglages — les
        bornes de l'exception assumée, les seuils des droits conservés, la
        borne des couples candidats — se lisaient par lui sans avoir
        d'attribut : la valeur écrite dans le workspace était ignorée, le
        repli du code s'appliquait partout, et rien ne le disait. Le document
        du workspace est donc relu en second.
        """
        if hasattr(self, key):
            return getattr(self, key)
        return self.document.get(key, default)
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any],
                  base_autorisee: Optional[str] = None) -> 'DataLoaderConfig':
        """Construit la configuration à partir du document du workspace.

        `base_autorisee` est un paramètre d'appel, pas une clé du document :
        le périmètre de lecture est imposé par l'appelant, il ne se règle pas
        depuis un fichier que l'API laisse écrire.
        """
        pipeline_invalide = None
        try:
            pipeline = Pipeline.depuis_document(config_dict.get('transformations'))
        except RegleInvalide as erreur:
            pipeline = Pipeline()
            pipeline_invalide = {
                "reason": erreur.motif,
                "field": erreur.champ,
                "value": str(erreur.valeur),
                "expected": list(erreur.attendues),
            }
            logger.error(
                "Transformation illisible, aucune règle appliquée : %s", erreur)

        politique_invalide = None
        try:
            politique = PolitiqueQualite.depuis_document(
                config_dict.get('data_quality'))
        except ValeurDePolitiqueInconnue as erreur:
            politique = PolitiqueQualite()
            # Structuré, jamais une phrase : le serveur ne connaît pas la
            # langue de l'utilisateur. Le client compose le message à partir
            # du champ fautif, de sa valeur et des valeurs attendues.
            politique_invalide = {
                "field": erreur.champ,
                "value": str(erreur.valeur),
                "expected": list(erreur.attendues),
            }
            logger.error(
                "Politique de qualité des clés illisible, défaut appliqué : %s",
                erreur)

        privileges_invalide = None
        try:
            privileges = marqueur_depuis_la_configuration(config_dict)
        except DeclarationInvalide as erreur:
            privileges = Marqueur()
            privileges_invalide = erreur.document()
            logger.error(
                "Marqueur de comptes à privilèges illisible, aucun compte "
                "marqué : %s", erreur)

        naming_invalide = None
        try:
            naming = convention_depuis_la_configuration(config_dict)
        except ConventionInvalide as erreur:
            naming = Convention()
            naming_invalide = erreur.document()
            logger.error(
                "Convention de nommage des droits illisible, aucune colonne "
                "dérivée : %s", erreur)

        config = cls(
            files_config=config_dict.get('files', {}),
            mining_min_users=config_dict.get('mining_min_users', 5),
            mining_min_rights=config_dict.get('mining_min_rights', 2),
            mining_attribute_max_cardinality_ratio=config_dict.get(
                'mining_attribute_max_cardinality_ratio', 0.5
            ),
            health_threshold_alert=config_dict.get('health_threshold_alert', 10.0),
            health_threshold_critical=config_dict.get('health_threshold_critical', 50.0),
            birth_rights_alert_pct=config_dict.get('birth_rights_alert_pct', 90.0),
            mining_profils_croises_max=config_dict.get(
                'mining_profils_croises_max', PROFILS_CROISES_MAX),
            mining_treillis_max=config_dict.get(
                'mining_treillis_max', TREILLIS_MAX),
            mining_max_roles_plafond=config_dict.get(
                'mining_max_roles_plafond', MAX_ROLES_PLAFOND),
            mining_apport_minimal=config_dict.get(
                'mining_apport_minimal', APPORT_MINIMAL),
            mining_selection=config_dict.get(
                'mining_selection', SELECTION_PAR_DEFAUT),
            mining_selection_effort=config_dict.get(
                'mining_selection_effort', EFFORT_PAR_DEFAUT),
            mining_selection_delai_s=config_dict.get(
                'mining_selection_delai_s', DELAI_PAR_DEFAUT_S),
            troncature_bornes=config_dict.get(
                'troncature_bornes', BORNES_USUELLES),
            sod_severites=config_dict.get('sod_severites', ()),
            assistance=Assistance.depuis_la_configuration(config_dict),
            coherence=CoherenceReglages(
                distance_edition_max=int(config_dict.get(
                    'coherence_distance_edition_max', 2)),
                longueur_racine_min=int(config_dict.get(
                    'coherence_longueur_racine_min', 4)),
                ecart_effectif_significatif=float(config_dict.get(
                    'coherence_ecart_effectif_significatif', 20.0)),
                valeurs_analysees_max=int(config_dict.get(
                    'coherence_valeurs_analysees_max', 2000)),
                part_typee_max=float(config_dict.get(
                    'coherence_part_typee_max', 0.5)),
                valeurs_soumises_max=int(config_dict.get(
                    'coherence_valeurs_soumises_max', 300)),
            ),
            base_autorisee=base_autorisee,
            politique_qualite=politique,
            politique_invalide=politique_invalide,
            pipeline=pipeline,
            pipeline_invalide=pipeline_invalide,
            privileges=privileges,
            privileges_invalide=privileges_invalide,
            naming=naming,
            naming_invalide=naming_invalide,
        )
        # Le document tel qu'il est écrit, relu par `get` pour les réglages
        # qui n'ont pas d'attribut. Une copie : la configuration chargée ne
        # doit pas changer parce que l'appelant modifie son dictionnaire.
        config.document = dict(config_dict)
        return config


class DataLoader:
    """
    Chargeur de données refactorisé.
    
    Changements par rapport à l'ancienne version:
    - Configuration typée (DataLoaderConfig)
    - Thread-safe avec verrou
    - Cleaner intégré (pas d'injection externe complexe)
    - Méthodes de chargement séparées et testables
    """
    
    # Noms de colonnes standardisés
    COL_USER_ID = 'ID_utilisateur'
    COL_RIGHT_ID = 'ID_droit'
    COL_APP_ID = 'ID_application'
    
    def __init__(self, config: DataLoaderConfig):
        """
        Initialise le DataLoader avec une configuration typée.
        
        Args:
            config: Configuration du loader
        """
        self.config = config
        self._lock = threading.RLock()
        
        # DataFrames
        self._identities: pd.DataFrame = pd.DataFrame()
        self._applications: pd.DataFrame = pd.DataFrame()
        self._rights: pd.DataFrame = pd.DataFrame()
        #: Ce que la convention de nommage a effectivement produit. Relevé au
        #: chargement et non reconstitué après coup : une fois la colonne
        #: dérivée posée, plus rien ne distingue « le produit l'a calculée » de
        #: « elle était dans le fichier », et l'écran dirait l'un pour l'autre.
        self._nommage: Dict[str, Any] = {"colonnes": [], "collisions": [],
                                         "application_deduite": False}
        self._habilitations: pd.DataFrame = pd.DataFrame()
        
        # Matrice sparse et encodeurs
        self._matrix: Optional[csr_matrix] = None
        self._user_encoder: Dict[str, int] = {}
        self._right_encoder: Dict[str, int] = {}
        
        # Cache du rapport de nettoyage
        self._cleaning_report: Optional[Dict[str, Any]] = None

        # Ce que les transformations ont fait, règle par règle.
        self._rapports_transformation: List[RapportRegle] = []
        # Couples (valeurs d'origine, valeurs transformées) des colonnes
        # touchées, par référentiel. Les deux sont conservées **au moment de la
        # transformation** : la standardisation renomme ensuite les colonnes de
        # clé — précisément celles qui comptent — et un diagnostic qui irait
        # relire le référentiel courant ne les retrouverait plus.
        #
        # Un seul dictionnaire portant les deux plutôt que deux dictionnaires
        # parallèles : deux tables remplies au même endroit ne peuvent pas
        # diverger, mais le code qui les relit doit quand même le vérifier, et
        # cette vérification est un chemin que rien ne peut exercer.
        self._valeurs_transformation: Dict[str, Tuple[pd.DataFrame, pd.DataFrame]] = {}

        # Ce que la politique de qualité des clés a fait de chaque référentiel.
        self._rapports_politique: Dict[str, RapportPolitique] = {}
        # Référentiel qui a fait refuser le chargement, et pour quel motif.
        self._refus_politique: Optional[Dict[str, Any]] = None
        
        # Charger les données
        self._load_all()
    
    # === Propriétés publiques (lecture seule) ===
    
    @property
    def identities(self) -> pd.DataFrame:
        with self._lock:
            return self._identities.copy()
    
    @property
    def applications(self) -> pd.DataFrame:
        with self._lock:
            return self._applications.copy()
    
    @property
    def rights(self) -> pd.DataFrame:
        with self._lock:
            return self._rights.copy()
    
    @property
    def habilitations(self) -> pd.DataFrame:
        with self._lock:
            return self._habilitations.copy()
    
    @property
    def matrix(self) -> Optional[csr_matrix]:
        with self._lock:
            return self._matrix
    
    @property
    def user_encoder(self) -> Dict[str, int]:
        with self._lock:
            return self._user_encoder.copy()
    
    @property
    def right_encoder(self) -> Dict[str, int]:
        with self._lock:
            return self._right_encoder.copy()
    
    # === Méthodes de chargement ===
    
    def _load_all(self) -> None:
        """Charge tous les fichiers de données."""
        logger.info("DataLoader: Démarrage du chargement...")
        
        with self._lock:
            self._rapports_transformation = []
            self._valeurs_transformation = {}
            self._rapports_politique = {}
            self._refus_politique = None
            self._incomplete_habs_count = 0
            self._nommage = {"colonnes": [], "collisions": [],
                             "application_deduite": False}

            # 1. Charger les fichiers bruts
            self._identities = self._load_csv('identities')
            self._applications = self._load_csv('applications')
            self._rights = self._load_csv('rights')
            self._habilitations = self._load_csv('habs')
            
            # 2. Transformer les valeurs, si l'utilisateur a déclaré des règles.
            #
            # Avant la standardisation : les règles portent sur les noms de
            # colonnes du fichier de l'utilisateur, les seuls qu'il connaisse.
            # Et avant la politique de qualité des clés : c'est sur la valeur
            # transformée que les doublons se comptent, sans quoi deux
            # écritures du même identifiant resteraient deux identifiants
            # jusque dans la matrice.
            self._transformer()

            # 3. Standardiser les colonnes
            self._standardize_columns()

            # Les référentiels tels qu'ils ont été lus, avant que la
            # politique n'en retire quoi que ce soit. L'écran de qualité
            # décrit **les fichiers de l'utilisateur** ; la politique dit ce
            # que le produit en a retenu. Confondre les deux ferait
            # disparaître une anomalie au moment où on décide de la traiter :
            # déclarer « garder la première occurrence » effacerait le
            # compteur de doublons, et l'écran afficherait « aucun doublon »
            # sur un fichier qui en est plein.
            sources = {
                "identities": self._identities,
                "applications": self._applications,
                "rights": self._rights,
                "habs": self._habilitations,
            }

            # 4. Appliquer la politique de qualité des clés.
            #
            # Après la standardisation, jamais avant : la politique porte sur
            # les clés, et le nom de la colonne qui les porte n'est connu
            # qu'une fois l'association faite par l'utilisateur appliquée.
            self._appliquer_politique_cles()
            
            # 5. Dériver ce que le nommage des droits dit déjà.
            #
            # Après la standardisation — la convention peut porter sur
            # l'identifiant du droit, dont le nom n'est connu qu'ici — et
            # **avant** la consolidation des applications : une application
            # déduite du nommage doit pouvoir peupler la liste des
            # applications comme le ferait une colonne du fichier.
            self._appliquer_le_nommage()

            # 6. Consolider les applications si nécessaire
            self._consolidate_applications()
            
            # 7. Construire la matrice
            self._build_matrix()
            
            # 8. Analyser la qualité des données
            self._analyze_data_quality(sources)
        
        logger.info("DataLoader: Chargement terminé.")
    
    #: Colonnes composant la clé de chaque référentiel, une fois les noms
    #: standardisés. Les habilitations ont une clé composée : une même paire
    #: (utilisateur, droit) présente deux fois est un doublon, la même
    #: personne sur deux droits ne l'est pas.
    CLES_REFERENTIELS = (
        ("identities", (COL_USER_ID,)),
        ("applications", (COL_APP_ID,)),
        ("rights", (COL_RIGHT_ID,)),
        ("habs", (COL_USER_ID, COL_RIGHT_ID)),
    )

    #: Attribut portant chaque référentiel. Nommé une fois : deux tables de
    #: correspondance divergeraient au premier référentiel ajouté.
    CADRES_REFERENTIELS = {
        "identities": "_identities",
        "applications": "_applications",
        "rights": "_rights",
        "habs": "_habilitations",
    }

    def _transformer(self) -> None:
        """Applique les règles déclarées, référentiel par référentiel.

        Les valeurs d'origine sont conservées à part — pas dans les tableaux
        affichés. Ajouter une colonne jumelle à chaque colonne transformée
        doublerait l'explorateur et les exports sans rien apprendre à qui ne
        cherche pas ; la structure parallèle sert le diagnostic, qui a son
        écran.
        """
        if self.config.pipeline.vide:
            return

        for referentiel, attribut in self.CADRES_REFERENTIELS.items():
            regles = self.config.pipeline.pour(referentiel)
            if not regles:
                continue
            transforme, origines, rapports = appliquer_transformations(
                getattr(self, attribut), regles, referentiel)
            setattr(self, attribut, transforme)
            if not origines.columns.empty:
                self._valeurs_transformation[referentiel] = (
                    origines, transforme[list(origines.columns)].copy())
            self._rapports_transformation.extend(rapports)

            modifiees = sum(r.valeurs_modifiees for r in rapports)
            if modifiees:
                logger.info("%s : %d valeur(s) transformée(s)",
                            referentiel, modifiees)
            for rapport in rapports:
                if not rapport.applicable:
                    logger.warning(
                        "%s : la colonne %r n'existe pas, règle %s ignorée",
                        referentiel, rapport.regle.colonne,
                        rapport.regle.operation.value)

    def differences_transformation(self, referentiel: str) -> pd.DataFrame:
        """Valeurs que les transformations ont réellement changées.

        Trois colonnes — `column`, `before`, `after` — et une ligne par valeur
        changée. C'est la forme utile au diagnostic : quand un rapprochement
        échoue, la question est « qu'est-ce que le produit a fait de mon
        identifiant », pas « à quoi ressemble mon fichier ».

        Les noms de colonnes rendus sont neutres : le serveur ne fabrique
        aucun libellé, l'interface les traduit.
        """
        with self._lock:
            couple = self._valeurs_transformation.get(referentiel)
            if couple is None:
                return pd.DataFrame(columns=["column", "before", "after"])

            origines, courant = couple
            morceaux = []
            for colonne in origines.columns:
                avant = origines[colonne]
                apres = courant[colonne]
                change = (avant != apres) & ~(avant.isna() & apres.isna())
                if not change.any():
                    continue
                morceaux.append(pd.DataFrame({
                    "column": colonne,
                    "before": avant[change].astype(object),
                    "after": apres[change].astype(object),
                }))

            if not morceaux:
                return pd.DataFrame(columns=["column", "before", "after"])
            return pd.concat(morceaux, ignore_index=True)

    def valeurs_origine(self, referentiel: str) -> pd.DataFrame:
        """Valeurs d'avant transformation, pour les colonnes transformées.

        Rendue vide si le référentiel n'a subi aucune transformation : c'est
        une absence de règle, pas une erreur.
        """
        with self._lock:
            couple = self._valeurs_transformation.get(referentiel)
            return pd.DataFrame() if couple is None else couple[0].copy()

    def _appliquer_politique_cles(self) -> None:
        """Applique au chargement ce que l'utilisateur a déclaré vouloir.

        Un refus vide **tous** les référentiels, pas seulement celui qui l'a
        provoqué. Ne vider que le fautif produirait une avalanche d'anomalies
        dérivées — des milliers d'orphelins, un score de santé effondré — qui
        masquerait la seule information utile : le chargement a été refusé, et
        pour ce motif-là.
        """
        for referentiel, colonnes in self.CLES_REFERENTIELS:
            attribut = self.CADRES_REFERENTIELS[referentiel]
            retenu, rapport = appliquer_politique(
                getattr(self, attribut),
                colonnes,
                self.config.politique_qualite.pour(referentiel),
                referentiel,
            )
            self._rapports_politique[referentiel] = rapport
            if rapport.refus:
                self._refus_politique = {
                    "referential": referentiel,
                    "reason": rapport.refus,
                    "count": (rapport.cles_vides if rapport.refus == MOTIF_CLE_VIDE
                              else rapport.cles_dupliquees),
                }
                logger.error(
                    "Chargement refusé : %s porte des clés en défaut (%s)",
                    referentiel, rapport.refus)
                break
            setattr(self, attribut, retenu)
            if rapport.lignes_ecartees:
                logger.warning(
                    "%s : %d ligne(s) écartée(s) par la politique de qualité "
                    "des clés", referentiel, rapport.lignes_ecartees)

        if self._refus_politique:
            self._identities = pd.DataFrame()
            self._applications = pd.DataFrame()
            self._rights = pd.DataFrame()
            self._habilitations = pd.DataFrame()
            return

        # Les habilitations sans identifiant sont désormais écartées ici. Le
        # compteur historique garde son sens — c'est le même chiffre, produit
        # par le mécanisme déclaré au lieu d'une règle figée dans le code.
        rapport_habs = self._rapports_politique.get("habs")
        if rapport_habs is not None and rapport_habs.applicable:
            self._incomplete_habs_count += rapport_habs.cles_vides

    def _load_csv(self, file_key: str) -> pd.DataFrame:
        """
        Charge un fichier CSV de manière sécurisée.
        
        Args:
            file_key: Clé du fichier dans la config (identities, applications, rights, habs)
        
        Returns:
            DataFrame chargé ou DataFrame vide si erreur
        """
        file_config = self.config.files.get(file_key, {})
        
        # Deux formats acceptés : dictionnaire ou objet Pydantic. Tout autre
        # chose — un `config.json` modifié à la main, un import mal formé —
        # était pris pour un dictionnaire et faisait lever le chargeur au
        # démarrage. Un fichier mal déclaré est un fichier non configuré :
        # l'écran de qualité le signale, l'application démarre.
        if hasattr(file_config, 'path'):
            path = file_config.path
            delimiter = getattr(file_config, 'delimiter', ';')
            encoding = getattr(file_config, 'encoding', 'utf-8')
        elif isinstance(file_config, dict):
            path = file_config.get('path', '')
            delimiter = file_config.get('delimiter', ';')
            encoding = file_config.get('encoding', 'utf-8')
        else:
            logger.warning(
                "Configuration de %s inexploitable (%s) : fichier ignoré.",
                file_key, type(file_config).__name__)
            return pd.DataFrame()
        
        if not path:
            logger.warning(f"Pas de chemin configuré pour {file_key}")
            return pd.DataFrame()
        
        # Un chemin relatif est résolu contre le répertoire de travail du
        # processus, et non contre l'emplacement du code : les fichiers de
        # données appartiennent au déploiement, pas au produit, et rien
        # n'impose qu'ils vivent sous l'arborescence des sources. C'est au
        # lanceur de fixer le répertoire de travail — `START_KOVEX.bat` le
        # fait explicitement.
        file_path = Path(path)

        # Seconde barrière, après celle du point d'entrée qui écrit la
        # configuration : un `config.json` peut aussi arriver par l'import d'un
        # workspace, ou être modifié à la main sur le serveur. Le chargeur ne
        # fait donc jamais confiance au chemin qu'on lui donne.
        if self.config.base_autorisee:
            try:
                resolu = file_path.resolve()
                base = Path(self.config.base_autorisee).resolve()
                resolu.relative_to(base)
            except (ValueError, OSError):
                logger.error(
                    "Chemin refusé pour %s : %s sort du périmètre autorisé (%s)",
                    file_key, path, self.config.base_autorisee,
                )
                return pd.DataFrame()

        if not file_path.exists():
            logger.warning(f"Fichier non trouvé: {path}")
            return pd.DataFrame()
        
        try:
            df = pd.read_csv(
                file_path,
                sep=delimiter,
                dtype=str,
                encoding=encoding,
                on_bad_lines='skip'
            )
            # Nettoyer les colonnes vides
            df.dropna(axis=1, how='all', inplace=True)
            
            logger.info(f"Chargé {file_key}: {len(df)} lignes, {len(df.columns)} colonnes")
            return df
            
        except Exception as e:
            logger.error(f"Erreur lecture {file_key} ({path}): {e}")
            return pd.DataFrame()
    
    def _standardize_columns(self) -> None:
        """Standardise les noms de colonnes selon la configuration."""
        
        # Identités
        id_col = self._get_config_value('identities', 'id_column')
        if id_col and id_col in self._identities.columns:
            self._identities.rename(columns={id_col: self.COL_USER_ID}, inplace=True)
        
        # Applications
        app_col = self._get_config_value('applications', 'id_column')
        if app_col and app_col in self._applications.columns:
            self._applications.rename(columns={app_col: self.COL_APP_ID}, inplace=True)
        
        # Droits : identifiant du droit, et application de rattachement.
        # Cette derniere n'etait pas configurable : seule une colonne deja
        # nommee ID_application etait reconnue, ce qui presupposait une
        # convention de nommage cote client.
        right_col = self._get_config_value('rights', 'id_column')
        if right_col and right_col in self._rights.columns:
            self._rights.rename(columns={right_col: self.COL_RIGHT_ID}, inplace=True)

        right_app_col = self._get_config_value('rights', 'app_id_column')
        if right_app_col and right_app_col in self._rights.columns:
            self._rights.rename(columns={right_app_col: self.COL_APP_ID}, inplace=True)
        
        # Habilitations (2 colonnes)
        hab_user_col = self._get_config_value('habs', 'user_id_column')
        hab_right_col = self._get_config_value('habs', 'right_id_column')
        
        if hab_user_col and hab_user_col in self._habilitations.columns:
            self._habilitations.rename(columns={hab_user_col: self.COL_USER_ID}, inplace=True)
        if hab_right_col and hab_right_col in self._habilitations.columns:
            self._habilitations.rename(columns={hab_right_col: self.COL_RIGHT_ID}, inplace=True)
    
    def _get_config_value(self, file_key: str, attr: str) -> Optional[str]:
        """Récupère une valeur de config pour un fichier."""
        file_config = self.config.files.get(file_key, {})
        
        if hasattr(file_config, attr):
            return getattr(file_config, attr, None)
        elif isinstance(file_config, dict):
            return file_config.get(attr)
        return None
    
    @property
    def nommage_applique(self) -> Dict[str, Any]:
        """Ce que la convention de nommage a produit au dernier chargement."""
        return dict(self._nommage)

    def _appliquer_le_nommage(self) -> None:
        """Ajoute au référentiel des droits ce que leur nommage dit déjà.

        Une colonne dérivée est un **enrichissement**, jamais un remplacement :
        elle porte un nom réservé, et si ce nom existe déjà dans le fichier du
        client la dérivation est abandonnée entière plutôt que d'écraser une
        donnée qu'il a fournie.

        Un seul endroit où la convention alimente un calcul plutôt qu'un
        affichage : si elle nomme une position `application` et que le
        référentiel des droits **n'a pas** de colonne de rattachement, la
        colonne dérivée en tient lieu. Elle ne prend jamais la place d'une
        colonne déclarée — deux sources pour le même rattachement finiraient
        par ne pas dire la même chose du même droit.
        """
        convention = self.config.naming
        if not convention.declaree or self._rights.empty:
            return
        self._nommage["collisions"] = list(
            collisions_de_nommage(self._rights, convention))
        enrichi = enrichir_par_le_nommage(self._rights, convention,
                                          self.COL_RIGHT_ID)
        if enrichi is self._rights:
            return
        self._rights = enrichi
        self._nommage["colonnes"] = [convention.colonne_derivee(role)
                                     for _, role in convention.nommees]
        derivee = convention.colonne_derivee(ROLE_APPLICATION)
        if (derivee in self._nommage["colonnes"]
                and self.COL_APP_ID not in self._rights.columns):
            self._rights[self.COL_APP_ID] = self._rights[derivee]
            self._nommage["application_deduite"] = True
            logger.info(
                "Rattachement droit → application déduit du nommage : %s",
                derivee)

    def _consolidate_applications(self) -> None:
        """Consolide la liste des applications si le fichier est vide."""
        if not self._applications.empty:
            return
        
        if self.COL_APP_ID not in self._rights.columns:
            return
        
        # Extraire les applications uniques des droits
        apps = self._rights[self.COL_APP_ID].dropna().unique()
        self._applications = pd.DataFrame({self.COL_APP_ID: apps})
        logger.info(f"Applications consolidées depuis les droits: {len(apps)}")
    
    def _build_matrix(self) -> None:
        """Construit la matrice sparse utilisateurs x droits."""
        if self._habilitations.empty:
            logger.warning("Pas d'habilitations - matrice non construite")
            return
        
        if self.COL_USER_ID not in self._habilitations.columns:
            logger.error(f"Colonne {self.COL_USER_ID} manquante dans habilitations")
            return
        
        if self.COL_RIGHT_ID not in self._habilitations.columns:
            logger.error(f"Colonne {self.COL_RIGHT_ID} manquante dans habilitations")
            return
        
        # Une habilitation n'existe que si ses DEUX identifiants sont
        # renseignés. Les lignes incomplètes sont écartées **ensemble**, et une
        # seule fois.
        #
        # La version précédente appliquait `dropna()` séparément à la colonne
        # des utilisateurs et à celle des droits, puis appariait les deux séries
        # par position : une ligne sans droit se retrouvait appariée au droit de
        # la ligne suivante. Sur quatre lignes dont deux incomplètes, la matrice
        # contenait une habilitation qui n'existait nulle part. Quand le nombre
        # de valeurs manquantes différait d'une colonne à l'autre, la
        # construction levait à la place une exception, et toute l'application
        # répondait 500.
        # Le `dropna` reste, comme filet : il ne compte plus rien, il garantit
        # seulement qu'aucune valeur manquante n'entre dans la matrice si le
        # chemin de chargement venait à changer. Le comptage, lui, est fait par
        # la politique de qualité des clés — elle écarte aussi les cellules ne
        # contenant que des espaces, que `dropna` laisse passer — et le
        # compteur `incomplete_habs_count` en vient.
        paires = self._habilitations[[self.COL_USER_ID, self.COL_RIGHT_ID]].dropna()

        # Les doublons d'une même habilitation ne doivent compter qu'une fois :
        # sans cela la matrice porte des valeurs 2, 3… là où elle décrit une
        # relation booléenne.
        paires = paires.drop_duplicates()

        users = paires[self.COL_USER_ID].unique()
        rights = paires[self.COL_RIGHT_ID].unique()

        self._user_encoder = {u: i for i, u in enumerate(users)}
        self._right_encoder = {r: i for i, r in enumerate(rights)}

        rows = paires[self.COL_USER_ID].map(self._user_encoder).astype(int)
        cols = paires[self.COL_RIGHT_ID].map(self._right_encoder).astype(int)

        self._matrix = csr_matrix(
            (np.ones(len(paires)), (rows.values, cols.values)),
            shape=(len(users), len(rights)),
        )

        logger.info(
            "Matrice construite : %d utilisateurs x %d droits, %d habilitations",
            self._matrix.shape[0], self._matrix.shape[1], self._matrix.nnz,
        )
    
    # === Analyse de qualité ===
    
    @staticmethod
    def _identifiants(dataframe: pd.DataFrame, colonne: str) -> set:
        """Identifiants distincts et renseignés d'une colonne.

        Le `dropna()` est indispensable : sans lui, une valeur manquante entre
        dans les ensembles, ressort comme un « orphelin » fantôme, et se
        retrouve dans les listes rendues par l'API — où elle n'est pas
        sérialisable en JSON, donc 500.
        """
        if colonne not in dataframe.columns:
            return set()
        return set(dataframe[colonne].dropna())

    def _doublons_referentiels(
        self,
        identities: pd.DataFrame,
        applications: pd.DataFrame,
        rights: pd.DataFrame,
    ) -> Dict[str, List[str]]:
        """Identifiants présents plusieurs fois dans un même référentiel.

        Le schéma d'API déclarait `duplicate_users_count` et
        `duplicate_rights_count` depuis l'origine, mais rien ne les calculait :
        l'API rendait 0, ce qui se lit « aucun doublon » alors que le contrôle
        n'avait pas lieu. Un identifiant en double fausse tout comptage par
        référentiel et fait apparaître deux fois la même application dans une
        campagne de revue.
        """
        resultat: Dict[str, List[str]] = {}
        for nom, dataframe, colonne in (
            ("duplicate_users", identities, self.COL_USER_ID),
            ("duplicate_rights", rights, self.COL_RIGHT_ID),
            ("duplicate_applications", applications, self.COL_APP_ID),
        ):
            if colonne not in dataframe.columns:
                resultat[nom] = []
                continue
            valeurs = dataframe[colonne].dropna()
            resultat[nom] = sorted(set(valeurs[valeurs.duplicated()]))
        return resultat

    def _integrite_referentielle(
        self,
        right_ids: set,
        hab_right_ids: set,
        applications: pd.DataFrame,
        rights: pd.DataFrame,
    ) -> Dict[str, Any]:
        """Cohérence entre le référentiel des droits et celui des applications.

        Les anomalies « orphelins » historiques ne regardaient que le couple
        (identité, habilitation). Elles laissent passer des situations qu'une
        revue de gouvernance doit voir : un droit rattaché à aucune
        application ne peut pas être recertifié par un propriétaire
        applicatif, un droit que personne ne détient est un candidat au
        décommissionnement, une application sans droit ni détenteur est du
        référentiel mort.

        Chaque contrôle n'est calculé que si les colonnes qu'il exige ont été
        associées par l'utilisateur. Un contrôle non calculable est signalé
        comme tel (`checks_available`) plutôt que rendu à zéro : un zéro
        affiché se lit « aucune anomalie », ce qui serait faux.
        """
        droits_avec_id = self.COL_RIGHT_ID in rights.columns
        droits_avec_app = self.COL_APP_ID in rights.columns
        apps_avec_id = self.COL_APP_ID in applications.columns

        # Droits du référentiel que personne ne détient.
        unused_rights = (right_ids - hab_right_ids) if droits_avec_id else set()

        # Droits dont l'application de rattachement n'est pas renseignée.
        rights_without_app = set()
        if droits_avec_id and droits_avec_app:
            colonnes = rights[[self.COL_RIGHT_ID, self.COL_APP_ID]]
            colonnes = colonnes.dropna(subset=[self.COL_RIGHT_ID])
            sans_app = colonnes[colonnes[self.COL_APP_ID].isna()]
            rights_without_app = set(sans_app[self.COL_RIGHT_ID])

        app_refs = (
            self._identifiants(rights, self.COL_APP_ID)
            if droits_avec_app else set()
        )
        app_ids = (
            self._identifiants(applications, self.COL_APP_ID)
            if apps_avec_id else set()
        )

        comparable = droits_avec_app and apps_avec_id
        # Applications citées par un droit mais absentes du référentiel.
        unknown_app_refs = (app_refs - app_ids) if comparable else set()
        # Applications du référentiel qu'aucun droit ne rattache.
        empty_applications = (app_ids - app_refs) if comparable else set()

        # Applications qui portent des droits, mais dont aucun n'est attribué.
        unused_applications = set()
        if droits_avec_id and comparable:
            couples = rights[[self.COL_RIGHT_ID, self.COL_APP_ID]].dropna()
            if not couples.empty:
                attribues = couples[self.COL_RIGHT_ID].isin(hab_right_ids)
                vivantes = set(couples.loc[attribues, self.COL_APP_ID])
                porteuses = set(couples[self.COL_APP_ID]) & app_ids
                unused_applications = porteuses - vivantes

        return {
            "unused_rights": unused_rights,
            "rights_without_app": rights_without_app,
            "unknown_app_refs": unknown_app_refs,
            "empty_applications": empty_applications,
            "unused_applications": unused_applications,
            "checks_available": {
                "unused_rights": droits_avec_id,
                "rights_without_app": droits_avec_id and droits_avec_app,
                "unknown_app_refs": comparable,
                "empty_applications": comparable,
                "unused_applications": droits_avec_id and comparable,
            },
        }

    def _comptes_tronques(self, habilitations: pd.DataFrame,
                          sources: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        """Les comptes qui tombent exactement sur une borne d'export connue.

        Deux comptes sont examinés, parce que deux troncatures existent et
        qu'elles ne se voient pas au même endroit :

        - **par droit**, le nombre de porteurs distincts. C'est la troncature
          d'un export d'appartenances — le groupe rendu s'arrête au plafond du
          connecteur, et le droit paraît moins porté qu'il ne l'est ;
        - **par référentiel**, le nombre de lignes lues. C'est la troncature du
          fichier entier, plus grave et plus facile à manquer : rien dans le
          contenu ne dit qu'il s'arrête au milieu.

        Les porteurs sont comptés **distincts** : un référentiel qui répète une
        ligne donnerait un compte plus élevé que la réalité, et manquerait
        justement la borne qu'il faut voir.
        """
        from src.core.data.troncature import (
            bornes_depuis_la_configuration, comptes_suspects)

        bornes = bornes_depuis_la_configuration(
            {"troncature_bornes": self.config.troncature_bornes})
        if not bornes:
            return {"bornes": [], "rights": [], "referentiels": []}

        porteurs: Dict[str, int] = {}
        if (not habilitations.empty
                and self.COL_USER_ID in habilitations.columns
                and self.COL_RIGHT_ID in habilitations.columns):
            couples = habilitations[[self.COL_USER_ID, self.COL_RIGHT_ID]].dropna()
            couples = couples.drop_duplicates()
            comptes = couples.groupby(self.COL_RIGHT_ID)[self.COL_USER_ID].size()
            porteurs = {str(cle): int(valeur) for cle, valeur in comptes.items()}

        lignes = {nom: int(len(cadre)) for nom, cadre in sources.items()
                  if cadre is not None}
        return {
            "bornes": list(bornes),
            "rights": comptes_suspects(porteurs, bornes),
            "referentiels": comptes_suspects(lignes, bornes),
        }

    def _analyze_data_quality(
        self, sources: Optional[Dict[str, pd.DataFrame]] = None
    ) -> None:
        """Analyse la qualité des données et génère le rapport.

        `sources` porte les référentiels **tels qu'ils ont été lus**, avant
        application de la politique de qualité des clés. L'analyse décrit les
        fichiers de l'utilisateur, pas ce qu'il en reste : un doublon traité
        selon la politique déclarée doit rester visible dans le rapport, sans
        quoi choisir de le traiter reviendrait à l'effacer.

        En son absence — recalcul tardif d'un rapport invalidé — l'analyse se
        rabat sur les référentiels courants. C'est le comportement d'avant la
        politique, et il reste juste tant qu'aucune ligne n'a été écartée.
        """
        sources = sources or {}
        identities = sources.get("identities", self._identities)
        applications = sources.get("applications", self._applications)
        rights = sources.get("rights", self._rights)
        habilitations = sources.get("habs", self._habilitations)

        user_ids = self._identifiants(identities, self.COL_USER_ID)
        right_ids = self._identifiants(rights, self.COL_RIGHT_ID)
        hab_user_ids = self._identifiants(habilitations, self.COL_USER_ID)
        hab_right_ids = self._identifiants(habilitations, self.COL_RIGHT_ID)

        orphan_users = hab_user_ids - user_ids
        orphan_rights = hab_right_ids - right_ids
        forest_users = user_ids - hab_user_ids

        referentiel = self._integrite_referentielle(
            right_ids, hab_right_ids, applications, rights)
        doublons = self._doublons_referentiels(identities, applications, rights)

        # Comptes tombant exactement sur une borne d'export connue. C'est une
        # suspicion de troncature à la source, et elle vaut d'être dite avant
        # tout le reste : un export tronqué se charge sans erreur, s'affiche
        # sans anomalie, et fausse ensuite chaque chiffre qui s'en déduit —
        # effectifs des rôles, couverture du mining, cumuls attendus d'une
        # règle de séparation des tâches.
        suspects = self._comptes_tronques(habilitations, sources)

        # Habilitations réellement inexploitables : les LIGNES dont l'un des
        # deux identifiants ne se rattache à rien. L'ancien calcul additionnait
        # le nombre d'identifiants orphelins distincts, ce qui comptait deux
        # fois une ligne doublement orpheline et une seule fois cinq cents
        # lignes pointant le même droit inexistant — alors que le libellé
        # affiché, « habilitations brisées », annonce des lignes.
        broken_habs = 0
        if not habilitations.empty:
            colonnes = habilitations.columns
            manquant = pd.Series(False, index=habilitations.index)
            if self.COL_USER_ID in colonnes:
                colonne = habilitations[self.COL_USER_ID]
                manquant |= colonne.isna() | ~colonne.isin(user_ids)
            if self.COL_RIGHT_ID in colonnes:
                colonne = habilitations[self.COL_RIGHT_ID]
                manquant |= colonne.isna() | ~colonne.isin(right_ids)
            broken_habs = int(manquant.sum())

        self._cleaning_report = {
            "orphan_users_count": len(orphan_users),
            "orphan_rights_count": len(orphan_rights),
            "forest_users_count": len(forest_users),
            "broken_habs_count": broken_habs,
            # Lignes écartées de la matrice faute d'identifiant : elles ne
            # participent à aucun mining, l'utilisateur doit le savoir.
            "incomplete_habs_count": getattr(self, "_incomplete_habs_count", 0),

            # Triées : deux exports du même jeu de données doivent contenir le
            # même échantillon, sans quoi un rapport d'audit n'est pas
            # reproductible.
            "orphan_users_list": sorted(orphan_users),
            "orphan_rights_list": sorted(orphan_rights),
            "forest_users_list": sorted(forest_users),

            "last_cleaned": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
            "issues_summary": []
        }

        # Le détail porte la borne atteinte, que la liste d'identifiants ne
        # peut pas dire : « exactement 5 000 » et « exactement 1 000 » ne
        # désignent pas le même système source.
        self._cleaning_report["truncation"] = suspects
        self._cleaning_report["truncated_rights_list"] = [
            suspect["identifiant"] for suspect in suspects["rights"]]
        self._cleaning_report["truncated_rights_count"] = len(suspects["rights"])

        for nom in (
            "unused_rights",
            "rights_without_app",
            "unknown_app_refs",
            "empty_applications",
            "unused_applications",
        ):
            valeurs = referentiel[nom]
            self._cleaning_report[f"{nom}_count"] = len(valeurs)
            self._cleaning_report[f"{nom}_list"] = sorted(valeurs)
        self._cleaning_report["checks_available"] = referentiel["checks_available"]

        for nom, valeurs in doublons.items():
            self._cleaning_report[f"{nom}_count"] = len(valeurs)
            self._cleaning_report[f"{nom}_list"] = valeurs

        # Ce que les transformations déclarées ont changé, règle par règle.
        # Une règle dont la colonne n'existe pas est comptée à part : c'est la
        # panne silencieuse de ce mécanisme — une correction qu'on croit active
        # et qui ne l'est pas laisse exactement le défaut qu'elle devait
        # réparer.
        regles_sans_effet = sum(
            1 for rapport in self._rapports_transformation
            if not rapport.applicable)
        self._cleaning_report["transformations"] = {
            "invalid": self.config.pipeline_invalide,
            "values_changed": sum(r.valeurs_modifiees
                                  for r in self._rapports_transformation),
            "rows_produced": sum(r.lignes_produites
                                 for r in self._rapports_transformation),
            "not_applicable": regles_sans_effet,
            "rules": [rapport.en_document()
                      for rapport in self._rapports_transformation],
        }

        # Ce que la politique de qualité des clés a fait, référentiel par
        # référentiel. Rendu en entier plutôt que résumé : l'utilisateur qui a
        # déclaré « garder la dernière occurrence » doit pouvoir vérifier que
        # c'est bien ce qui s'est passé, et sur combien de lignes.
        lignes_ecartees = sum(
            rapport.lignes_ecartees
            for rapport in self._rapports_politique.values()
        )
        self._cleaning_report["key_policy"] = {
            "refused": self._refus_politique,
            "invalid": self.config.politique_invalide,
            "rows_discarded": lignes_ecartees,
            "referentials": [
                self._rapports_politique[nom].en_document()
                for nom, _ in self.CLES_REFERENTIELS
                if nom in self._rapports_politique
            ],
        }

        # Le serveur ne construit aucune phrase : il rend une clé et ses
        # paramètres, le client traduit. Ces libellés étaient les derniers
        # textes français fabriqués côté serveur et affichés tels quels — une
        # session en anglais ou en allemand voyait du français.
        #
        # La sévérité est portée par le serveur parce qu'elle dépend de la
        # nature de l'anomalie, pas de son affichage : un droit inconnu casse
        # une habilitation, une application vide ne fait que du bruit.
        anomalies = (
            ("OrphanUser", "quality.issue.orphan_users", "critical",
             len(orphan_users), "orphan_users_list"),
            ("OrphanRight", "quality.issue.orphan_rights", "critical",
             len(orphan_rights), "orphan_rights_list"),
            ("IncompleteHab", "quality.issue.incomplete_habs", "critical",
             self._cleaning_report["incomplete_habs_count"], None),
            ("UnknownApplication", "quality.issue.unknown_app_refs", "critical",
             len(referentiel["unknown_app_refs"]), "unknown_app_refs_list"),
            ("RightWithoutApp", "quality.issue.rights_without_app", "warning",
             len(referentiel["rights_without_app"]), "rights_without_app_list"),
            ("UnusedRight", "quality.issue.unused_rights", "warning",
             len(referentiel["unused_rights"]), "unused_rights_list"),
            ("UnusedApplication", "quality.issue.unused_applications", "warning",
             len(referentiel["unused_applications"]), "unused_applications_list"),
            ("DuplicateUser", "quality.issue.duplicate_users", "warning",
             len(doublons["duplicate_users"]), "duplicate_users_list"),
            ("DuplicateRight", "quality.issue.duplicate_rights", "warning",
             len(doublons["duplicate_rights"]), "duplicate_rights_list"),
            ("DuplicateApplication", "quality.issue.duplicate_applications", "warning",
             len(doublons["duplicate_applications"]), "duplicate_applications_list"),
            ("EmptyApplication", "quality.issue.empty_applications", "info",
             len(referentiel["empty_applications"]), "empty_applications_list"),
            ("ForestUser", "quality.issue.forest_users", "info",
             len(forest_users), "forest_users_list"),

            # Politique de qualité des clés. Le détail par référentiel vit
            # dans `key_policy` : ces trois lignes ne sont que l'entrée dans
            # la liste des anomalies, pour qu'un chargement refusé ou amputé
            # ne soit pas visible sur un seul écran.
            ("KeyPolicyRefused", "quality.issue.key_policy_refused", "critical",
             (self._refus_politique or {}).get("count", 0), None),
            ("KeyPolicyInvalid", "quality.issue.key_policy_invalid", "critical",
             1 if self.config.politique_invalide else 0, None),
            ("KeyPolicyDiscarded", "quality.issue.key_policy_discarded", "warning",
             lignes_ecartees, None),

            # Transformations. Le détail par règle vit dans `transformations`.
            ("TransformationInvalid", "quality.issue.transformation_invalid",
             "critical", 1 if self.config.pipeline_invalide else 0, None),
            ("TransformationNotApplicable",
             "quality.issue.transformation_not_applicable", "warning",
             regles_sans_effet, None),

            # Suspicion de troncature à la source. `warning` et jamais
            # `critical` : un groupe peut compter exactement mille personnes,
            # c'est improbable et ce n'est pas impossible. Une alerte critique
            # sur une coïncidence apprendrait à ignorer les alertes critiques.
            ("TruncatedRight", "quality.issue.truncated_rights", "warning",
             len(suspects["rights"]), "truncated_rights_list"),
            ("TruncatedReferential", "quality.issue.truncated_referentials",
             "warning", len(suspects["referentiels"]), None),
        )
        for type_anomalie, cle, severite, nombre, cle_liste in anomalies:
            if nombre:
                self._cleaning_report["issues_summary"].append({
                    "type": type_anomalie,
                    "description_key": cle,
                    "description_params": {"count": nombre},
                    "count": nombre,
                    "severity": severite,
                    # Le client n'a pas à connaître la correspondance entre un
                    # type d'anomalie et le champ qui porte ses identifiants.
                    "list_key": cle_liste,
                })

    def empreinte_donnees(self) -> str:
        """Empreinte exacte du contenu de la matrice utilisateurs × droits.

        Sert à savoir si un mining conservé porte encore sur les données
        courantes. Un simple comptage ne suffirait pas : remplacer une
        habilitation par une autre laisse les volumes inchangés alors que le
        résultat du mining change.

        L'empreinte est calculée sur la structure creuse elle-même — les
        positions non nulles — et sur l'ordre des identifiants encodés. Sur
        234 000 habilitations cela représente environ un mégaoctet à hacher,
        soit quelques millisecondes : assez peu pour être recalculé à chaque
        consultation du graphe.
        """
        empreinte = hashlib.sha256()
        with self._lock:
            if self._matrix is None:
                empreinte.update(b"matrice-absente")
            else:
                empreinte.update(self._matrix.indptr.tobytes())
                empreinte.update(self._matrix.indices.tobytes())
            # Les encodeurs donnent le sens des indices : deux matrices
            # identiques portant sur d'autres identifiants sont deux jeux
            # différents.
            for encodeur in (self._user_encoder, self._right_encoder):
                for identifiant in encodeur:
                    empreinte.update(str(identifiant).encode("utf-8"))
                    empreinte.update(b"\x00")
        return empreinte.hexdigest()

    def get_cleaning_status(self) -> Dict[str, Any]:
        """Retourne le rapport de nettoyage."""
        with self._lock:
            if self._cleaning_report is None:
                self._analyze_data_quality()
            return self._cleaning_report.copy()
    
    def get_health_score(self) -> Dict[str, Any]:
        """Calcule le score de santé des données."""
        report = self.get_cleaning_status()
        
        total_issues = (
            report.get("orphan_rights_count", 0) +
            report.get("orphan_users_count", 0) +
            report.get("forest_users_count", 0)
        )
        
        total_users = len(self._identities) if not self._identities.empty else 1
        issue_rate = (total_issues / total_users) * 100 if total_users > 0 else 100
        
        # Arrondi par défaut : trois anomalies sur 2 620 identités donnaient
        # 99,89, arrondi à 100 — un score parfait affiché sur un jeu qui ne
        # l'est pas. 100 est réservé au jeu sans aucune anomalie comptée.
        score = math.floor(max(0.0, 100.0 - issue_rate) * 10) / 10

        # Anomalies que le serveur classe critiques, quelle que soit leur
        # part dans le jeu : une habilitation incomplète ou une application
        # inconnue n'entrent pas dans le taux par identité, et l'écran de
        # qualité les affiche pourtant « Critique ».
        critiques = sum(
            anomalie.get("count", 0)
            for anomalie in report.get("issues_summary", [])
            if anomalie.get("severity") == "critical")

        # Clé de traduction, jamais un libellé : le serveur ne connaît pas la
        # langue de l'utilisateur, et un libellé français rendrait l'indicateur
        # intraduisible côté client.
        if issue_rate > self.config.health_threshold_critical:
            status_key = "health.status.critical"
        elif issue_rate > self.config.health_threshold_alert or critiques:
            # Une anomalie critique interdit « Sain » : le tableau de bord
            # ne peut pas contredire l'écran de qualité. Elle ne suffit pas
            # à déclarer le jeu critique — ce seuil-là reste le réglage de
            # l'utilisateur, exprimé en part des identités.
            status_key = "health.status.alert"
        else:
            status_key = "health.status.healthy"

        return {
            "score": score,
            "status_key": status_key,
            "total_issues": total_issues,
            "critical_issues": critiques,
        }
    
    def reload(self) -> None:
        """Recharge toutes les données."""
        logger.info("DataLoader: Rechargement des données...")
        self._cleaning_report = None
        self._load_all()


# === Factory et gestion d'instance ===

class DataLoaderManager:
    """
    Gestionnaire du DataLoader - remplace le singleton global.
    Permet de gérer le cycle de vie de manière explicite.
    """
    
    _instance: Optional[DataLoader] = None
    _lock = threading.Lock()
    
    @classmethod
    def initialize(cls, config: DataLoaderConfig) -> DataLoader:
        """
        Initialise le DataLoader avec la configuration donnée.
        
        Args:
            config: Configuration du loader
        
        Returns:
            Instance du DataLoader
        """
        with cls._lock:
            cls._instance = DataLoader(config)
            logger.info("DataLoaderManager: Instance initialisée")
            return cls._instance
    
    @classmethod
    def get_instance(cls) -> Optional[DataLoader]:
        """
        Récupère l'instance actuelle du DataLoader.
        
        Returns:
            Instance ou None si pas initialisé
        """
        return cls._instance
    
    @classmethod
    def reset(cls) -> None:
        """Réinitialise le manager (utile pour les tests)."""
        with cls._lock:
            cls._instance = None
            logger.info("DataLoaderManager: Instance réinitialisée")


def create_data_loader(config_dict: Dict[str, Any]) -> DataLoader:
    """
    Factory function pour créer un DataLoader.
    
    Args:
        config_dict: Dictionnaire de configuration
    
    Returns:
        DataLoader configuré
    """
    config = DataLoaderConfig.from_dict(config_dict)
    return DataLoader(config)
