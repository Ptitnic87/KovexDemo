# src/core/role/business_miner.py
"""
Mining métier : découverte de rôles à partir des attributs RH des identités.

Pour chaque groupe d'identités partageant les mêmes valeurs d'attributs
(service, fonction, entité…), on retient les droits détenus par au moins
`min_coverage_pct` % du groupe. Le rôle produit est la règle RH « qui est dans
ce groupe reçoit ces droits », accompagnée de son coût : le sur-provisionnement,
c'est-à-dire les droits que la règle accorderait à des membres qui ne les ont
pas aujourd'hui.

Les colonnes d'attributs ne sont pas connues à l'avance : elles sont choisies
par l'appelant parmi les colonnes du référentiel d'identités.

La scission d'un groupe
-----------------------

La couverture moyenne d'un rôle ne dit pas comment son groupe se partage. « 85 %
de couverture » recouvre deux objets sans rapport :

- **une règle à exceptions** — chacun manque un droit sur sept, et ce n'est pas
  le même droit pour tout le monde. C'est le bruit ordinaire d'un référentiel :
  provisionnements en retard, départs, oublis ;
- **un groupe scindé** — un membre sur cinq ne détient *aucun* des droits, et
  les quatre autres les détiennent tous. Ce n'est pas une règle avec des
  exceptions : c'est une population que l'attribut choisi ne décrit pas. Une
  équipe projet recrutée dans un même service en produit exactement la forme.

`scission_pct` mesure cela : parmi les membres que la règle laisserait de côté,
la part qui ne détient aucun des droits du rôle. Elle vaut 0 pour une règle
bruitée, et tend vers 100 pour un groupe scindé.

Ce que l'indicateur **ne** dit pas. Un membre mal rattaché — mutation non
répercutée, mission temporaire — produit la même trace qu'un non-membre d'équipe
projet : il porte les attributs du groupe et n'en détient aucun droit. La mesure
est donc exploitable sur un référentiel d'identités exact, et cesse de l'être
dès quelques pour cent d'erreur de rattachement ; `tests/test_scission.py` en
relève la frontière. C'est pourquoi le produit expose ce chiffre et le
diagnostique, mais n'écarte aucun candidat sur cette base.

Note d'implémentation. Le calcul est entièrement vectorisé (groupby / merge).
La version précédente rebalayait les DataFrames complets à l'intérieur de la
boucle sur les groupes — deux masques booléens sur toutes les lignes par
groupe — ce qui coûtait plusieurs minutes en profondeur 2 sur un référentiel
de 20 000 identités, pendant lesquelles l'API ne répondait plus.
"""

import logging
from itertools import combinations
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from src.core.role.identite import identifiant_metier
from src.core.role.modele_acquis import ModeleAcquis

logger = logging.getLogger(__name__)

COL_USER_ID = 'ID_utilisateur'
COL_RIGHT_ID = 'ID_droit'


class BusinessRoleMiner:
    """Découvre des rôles métier par croisement d'attributs RH et d'habilitations."""

    def __init__(self, loader):
        self.loader = loader

        # Les propriétés du DataLoader renvoient déjà une copie : une seule
        # lecture, stockée en local, plutôt qu'un appel dans chaque boucle.
        identities = loader.identities
        habilitations = loader.habilitations

        self.identities = identities if identities is not None else pd.DataFrame()
        habs = habilitations if habilitations is not None else pd.DataFrame()

        if habs.empty or self.identities.empty:
            self.merged_data = pd.DataFrame()
            return

        self.merged_data = pd.merge(habs, self.identities, on=COL_USER_ID, how='inner')
        # Identifiant de ligne stable, pour mesurer quelles habilitations du
        # périmètre sont effectivement couvertes par au moins un rôle.
        self.merged_data['global_index'] = self.merged_data.index

        # Identités que le référentiel connaît mais qui ne détiennent aucun
        # droit. Le produit ne peut pas savoir si ce sont des arrivants — qui
        # recevront bien les rôles — ou des partants dont les accès ont été
        # révoqués : sans statut ni date dans les données, les deux se
        # ressemblent. C'est donc un choix de l'utilisateur, et ce compte est
        # rendu dans tous les cas pour qu'il soit éclairé.
        self.identites_sans_droit = (
            set(self.identities[COL_USER_ID]) - set(self.merged_data[COL_USER_ID]))

        # Codage des couples (identité, droit) en entiers.
        #
        # La sélection a besoin de comparer, d'un rôle à l'autre, les couples
        # qu'ils accorderaient en trop — pour ne pas compter deux fois le même.
        # Des ensembles de tuples de chaînes coûteraient plusieurs dizaines de
        # mégaoctets sur un référentiel réel et rendraient chaque différence
        # d'ensembles lente. Un entier par couple tient ce rôle exactement, et
        # la table de correspondance ne sert qu'ici.
        # La table couvre **toutes** les identités du référentiel, pas seulement
        # celles qui détiennent un droit : quand l'utilisateur déclare que les
        # identités sans droit font partie de son périmètre, les rôles leur
        # accordent des droits, et ces couples doivent pouvoir être codés.
        self._utilisateurs = pd.Index(
            pd.concat([self.merged_data[COL_USER_ID],
                       self.identities[COL_USER_ID]]).unique())
        self._droits = pd.Index(self.merged_data[COL_RIGHT_ID].unique())
        self._nb_droits = max(1, len(self._droits))
        self._code_utilisateur = {u: i for i, u in enumerate(self._utilisateurs)}
        self._code_droit = {d: i for i, d in enumerate(self._droits)}

        codes_lignes = (
            self.merged_data[COL_USER_ID].map(self._code_utilisateur).to_numpy()
            * self._nb_droits
            + self.merged_data[COL_RIGHT_ID].map(self._code_droit).to_numpy()
        )
        # Indexée par `global_index`, qui est le rang de la ligne : un accès
        # direct, sans dictionnaire intermédiaire.
        self._code_par_ligne = np.asarray(codes_lignes, dtype=np.int64)

        # Populations RH par combinaison d'attributs, construites à la demande.
        # Un rôle désigne ses membres par une conjonction d'attributs ; la même
        # combinaison revient pour des centaines de rôles, le regroupement n'est
        # donc fait qu'une fois par combinaison.
        self._populations_rh: Dict[Tuple[str, ...], Dict[Tuple[Any, ...], set]] = {}
        self._cache_codes_detenus: Optional[set] = None

    def lignes_deja_expliquees(self, acquis) -> set:
        """Habilitations que le catalogue validé explique déjà.

        Une habilitation est un couple (identité, droit). Elle est expliquée
        quand un rôle validé désigne cette identité **et** porte ce droit.

        Le calcul passe par le codage entier déjà en place — un couple vaut
        `code_utilisateur * nombre_de_droits + code_droit` — pour comparer des
        entiers plutôt que des paires de chaînes. Sur un référentiel réel, la
        différence se mesure en secondes.

        C'est le point de départ du glouton. Sans lui, le classement des
        candidats se fait entre eux, sans tenir compte de ce que le catalogue
        couvre déjà : valider dans l'ordre de l'écran donne un modèle, valider
        le septième puis le douzième en donne un autre, moins bon, sans que
        rien ne l'annonce.
        """
        if acquis is None or acquis.vide or self.merged_data.empty:
            return set()

        codes_acquis = set()
        for role in acquis.roles:
            codes_droits = [self._code_droit[droit] for droit in role.droits
                            if droit in self._code_droit]
            if not codes_droits:
                continue
            for membre in role.membres:
                code_membre = self._code_utilisateur.get(membre)
                if code_membre is None:
                    continue
                base = code_membre * self._nb_droits
                codes_acquis.update(base + code for code in codes_droits)
        if not codes_acquis:
            return set()

        appartient = np.isin(self._code_par_ligne,
                             np.fromiter(codes_acquis, dtype=np.int64,
                                         count=len(codes_acquis)))
        return set(np.flatnonzero(appartient).tolist())

    def _membres_rh(self, signature: Dict[str, Any]) -> set:
        """Identités que la règle RH d'un rôle désigne, droits ou pas.

        La règle est une conjonction : toutes les conditions doivent tenir. On
        interroge le référentiel des identités, et non le périmètre miné, parce
        que c'est bien lui qui décidera qui reçoit le rôle une fois le modèle
        appliqué.
        """
        noms = tuple(signature)
        groupes = self._populations_rh.get(noms)
        if groupes is None:
            groupes = {
                (cle if isinstance(cle, tuple) else (cle,)): set(membres)
                for cle, membres in self.identities.groupby(
                    list(noms), dropna=False, observed=True,
                    sort=False)[COL_USER_ID].unique().items()
            }
            self._populations_rh[noms] = groupes
        return groupes.get(tuple(signature.values()), set())

    # ------------------------------------------------------------------ API

    def mine_roles(
        self,
        attributes: List[str],
        min_coverage_pct: float = 70.0,
        min_users: int = 5,
        min_rights: int = 2,
        mining_depth: int = 1,
        excluded_rights: Optional[Sequence[str]] = None,
        arbitrage: float = 0.0,
        couverture_visee: Optional[float] = None,
        inclure_sans_droit: bool = False,
        parcimonie_pct: float = 0.0,
        modele_acquis: Optional["ModeleAcquis"] = None,
    ) -> Dict[str, Any]:
        """Découvre les rôles métier pour les attributs demandés.

        Args:
            attributes: colonnes du référentiel d'identités servant à grouper.
            min_coverage_pct: part minimale du groupe devant détenir un droit
                pour que ce droit entre dans le rôle.
            min_users: effectif minimal d'un groupe.
            min_rights: nombre minimal de droits retenus pour former un rôle.
            mining_depth: nombre maximal d'attributs croisés (1 = un seul
                attribut, 2 = toutes les paires, etc.).
            excluded_rights: droits qui ne doivent composer aucun rôle — droits
                socles, exclusions manuelles.
            arbitrage: poids du sur-octroi face à la couverture dans la
                sélection. 0 — le défaut — maximise la couverture et reproduit
                exactement le comportement d'avant ce réglage.
            inclure_sans_droit: les identités que le référentiel connaît mais
                qui ne détiennent aucun droit font-elles partie des groupes ?
                Faux par défaut — le comportement historique. Le produit ne
                peut pas trancher seul : sans statut ni date dans les données,
                un arrivant qui recevra bien le rôle et un partant dont les
                accès ont été révoqués se ressemblent exactement.
            couverture_visee: part des habilitations à expliquer, en pourcentage,
                au-delà de laquelle la sélection s'arrête. `None` retient tout
                candidat qui apporte quelque chose — le comportement historique.
                L'arbitrage n'a d'effet qu'avec un objectif : sans point
                d'arrêt, il ne change que l'ordre des rôles.
            modele_acquis: le catalogue déjà validé, évalué sur les données du
                jour. Les droits qu'il octroie à **tous** les membres d'un
                candidat sont retirés de ce candidat, et le rôle validé qui
                couvre toute sa population devient son parent. Sans catalogue —
                un espace de travail neuf — le calcul est exactement celui
                d'avant.
            parcimonie_pct: part, en pourcentage, de ce qu'explique son ancêtre
                qu'un rôle doit expliquer pour être retenu à côté de lui. 0
                retient toute stratification qui apporte quelque chose — le
                comportement historique, mesuré à onze fois plus de
                stratifications que le référentiel n'en contient.

        Les droits exclus le sont **du calcul**, pas du résultat. L'appelant
        les retirait auparavant des rôles rendus, sans recalculer ni la
        couverture, ni le sur-octroi, ni le score : les chiffres affichés
        décrivaient alors un rôle qui n'était plus celui qu'on proposait.

        L'exclusion ne touche pas l'effectif des groupes. Un groupe est défini
        par des valeurs d'attributs, et sa population est celle des identités
        qui les portent — qu'elles détiennent ou non un droit socle. Retirer
        ces lignes du périmètre ferait disparaître du groupe une identité qui
        ne détient *que* des droits socles, et fausserait toutes les
        couvertures. Seul le numérateur est concerné, jamais le dénominateur.

        Returns:
            {"roles": [...], "stats": {...}}
        """
        empty = {
            "roles": [],
            "stats": {
                "covered_habs_count": 0,
                "total_habs_in_scope": 0,
                "habs_coverage_pct": 0.0,
                "unique_users_covered": 0,
            },
        }

        if self.merged_data.empty or not attributes:
            logger.warning("Mining métier : aucune donnée fusionnée ou aucun attribut demandé")
            return empty

        valid_attributes = [a for a in attributes if a in self.identities.columns]
        if not valid_attributes:
            logger.warning("Mining métier : aucun attribut valide parmi %s", attributes)
            return empty

        scope = self.merged_data
        total_habs_in_scope = len(scope)

        covered_indices: set = set()
        impacted_users: set = set()
        exclus = set(excluded_rights or ())
        #: Groupes qui auraient produit un rôle sans l'exclusion, et qui
        #: retombent sous `min_rights` une fois les droits exclus retirés.
        #: L'appelant l'affiche : un rôle qui disparaît doit s'expliquer.
        compteurs = {"ecartes_par_exclusion": 0, "vides_par_acquis": 0}

        roles = self._candidats(
            valid_attributes, min_coverage_pct, min_users, min_rights,
            mining_depth, exclus, compteurs, impacted_users,
            inclure_sans_droit, modele_acquis)

        lignes_visees = (
            None if couverture_visee is None
            else int(total_habs_in_scope * couverture_visee / 100.0))
        # L'objectif de couverture porte sur le référentiel, catalogue compris :
        # « expliquer 80 % » veut dire quatre-vingts pour cent en tout, et non
        # quatre-vingts de plus que ce qui l'est déjà.
        lignes_acquises = self.lignes_deja_expliquees(modele_acquis)
        roles = self._couvrir(roles, arbitrage, lignes_visees, parcimonie_pct,
                              lignes_acquises)

        # Ce que ce modèle coûterait vraiment s'il était attribué, et combien
        # d'identités sans droit il toucherait. Rendus quel que soit le choix
        # de population : une omission silencieuse est précisément ce que ce
        # produit corrige partout ailleurs.
        population = self.mesurer_population(roles)

        covered_indices = set()
        # Couples sur-octroyés par le modèle, dédupliqués. Deux rôles peuvent
        # accorder le même droit à la même personne : la somme des sur-octrois
        # individuels le compte deux fois, l'union non.
        sur_octroi_distinct: set = set()
        for role in roles:
            lignes = role.pop("_lignes")
            # Part de ce qu'explique ce rôle que le catalogue explique déjà.
            # Le filtre par ensemble exact ne voyait qu'un cas — la redondance
            # totale — et écartait le candidat en silence. Une grandeur
            # continue, affichée, laisse l'utilisateur décider : à quatre-vingt
            # pour cent, un rôle qui recouvre un rôle validé se discute, il ne
            # se supprime pas.
            role["redondance_pct"] = (
                round(100.0 * len(lignes & lignes_acquises) / len(lignes), 1)
                if lignes and lignes_acquises else 0.0)
            covered_indices |= lignes
            sur_octroi_distinct |= role.pop("_sur_octroi")
        covered_count = len(covered_indices)
        coverage_pct = (covered_count / total_habs_in_scope * 100) if total_habs_in_scope else 0.0

        logger.info(
            "Mining métier terminé : %d rôles, %.1f %% des habilitations du périmètre couvertes",
            len(roles), coverage_pct,
        )

        # Coût du modèle proposé. La couverture était rendue seule : un écran
        # qui annonce ce qu'un modèle explique sans annoncer ce qu'il donne en
        # trop cache la moitié de l'arbitrage — c'est précisément le reproche
        # que ce produit fait aux outils du marché.
        #
        octroye = sum(int(role["user_count"]) * int(role["right_count"])
                      for role in roles)

        return {
            "roles": roles,
            "stats": {
                "covered_habs_count": int(covered_count),
                "total_habs_in_scope": int(total_habs_in_scope),
                "habs_coverage_pct": round(coverage_pct, 1),
                # Le modèle **complet** : ce que le catalogue explique déjà, ce
                # que l'ensemble explique une fois les candidats retenus, et
                # l'écart entre les deux — l'apport de ce calcul.
                #
                # La couverture rendue jusqu'ici ne décrivait que les
                # candidats. Après avoir validé la moitié de son catalogue,
                # l'utilisateur lisait encore un chiffre calculé comme s'il
                # n'avait rien décidé. C'est l'indicateur central du produit.
                "acquired_habs_count": int(len(lignes_acquises)),
                "acquired_coverage_pct": (
                    round(100.0 * len(lignes_acquises) / total_habs_in_scope, 1)
                    if total_habs_in_scope else 0.0),
                "model_habs_count": int(len(covered_indices | lignes_acquises)),
                "model_coverage_pct": (
                    round(100.0 * len(covered_indices | lignes_acquises)
                          / total_habs_in_scope, 1)
                    if total_habs_in_scope else 0.0),
                "unique_users_covered": int(len({identite for role in roles
                                                   for identite in role["users"]})),
                # Ce que le modèle crée réellement, une fois les doublons
                # entre rôles retirés. La somme rôle par rôle était rendue à
                # côté, sous un nom voisin : elle valait 17 % de plus sur un
                # référentiel réel, parce que deux rôles peuvent sur-octroyer
                # le même couple. Deux grandeurs presque homonymes pour une
                # même question préparent l'erreur chez l'utilisateur — elle
                # s'est produite deux fois ici en une semaine. Il n'en reste
                # qu'une.
                "over_provisioning_distinct": len(sur_octroi_distinct),
                "arbitrage": arbitrage,
                "couverture_visee": couverture_visee,
                "parcimonie_pct": parcimonie_pct,
                "inclure_sans_droit": inclure_sans_droit,
                # Identités sans aucun droit dans le référentiel, et celles que
                # les rôles proposés toucheraient. Le second chiffre est le seul
                # qui compte pour décider : les autres ne changent rien.
                "identities_without_rights": len(self.identites_sans_droit),
                "identities_without_rights_in_roles":
                    population["identities_without_rights_in_roles"],
                # Coût réel d'une attribution : le sur-octroi du modèle, plus
                # ce que les rôles accorderaient aux membres que le calcul n'a
                # pas comptés. Égal au précédent quand la population inclut
                # tout le monde ; supérieur sinon, et l'écart est la mesure de
                # ce que le chiffre affiché tait.
                "over_provisioning_if_applied":
                    population["over_provisioning_if_applied"],
                "granted_by_roles": octroye,
                "excluded_rights_count": len(exclus),
                "dropped_by_exclusion": compteurs["ecartes_par_exclusion"],
                # Candidats dont le catalogue octroyait déjà tous les droits à
                # toute la population. Ils n'apportaient rien ; le dire est une
                # information de gouvernance, les taire serait une disparition
                # de plus à expliquer.
                "dropped_already_granted": compteurs["vides_par_acquis"],
            },
        }

    def mesurer_population(self, roles: Sequence[Dict[str, Any]]) -> Dict[str, int]:
        """Ce qu'un modèle coûterait s'il était réellement attribué.

        Le sur-octroi rendu par le mining porte sur la population **calculée** :
        les identités que le référentiel connaît sans qu'elles détiennent le
        moindre droit en sont exclues par défaut, parce que rien dans les
        données ne dit si ce sont des arrivants — qui recevront bien les rôles
        — ou des partants dont les accès ont été révoqués.

        Le jour où le modèle est appliqué, cette distinction n'existe plus : la
        règle RH d'un rôle désigne tous ceux qui la vérifient, et une identité
        sans aucun droit se voit accorder l'intégralité du rôle. Cette méthode
        mesure ce coût-là, sur le modèle qu'on affiche.

        Elle est appelée aussi bien par le mining que par la route, qui retire
        ensuite des rôles : un chiffre relevé avant ce filtrage décrirait un
        modèle qui n'est plus celui qu'on montre.

        Returns:
            dict: `identities_without_rights` (le référentiel),
            `identities_without_rights_in_roles` (celles qu'un rôle touche) et
            `over_provisioning_if_applied` (couples accordés en trop, une seule
            fois chacun).
        """
        detenus = self._codes_detenus()
        concernees: set = set()
        accordes: set = set()
        for role in roles:
            codes_droits = [self._code_droit[droit] for droit in role["rights"]
                            if droit in self._code_droit]
            if not codes_droits:
                continue
            # La règle RH d'un rôle est une conjonction — « fonction = X ET
            # service = Y ». Prendre les membres attribut par attribut
            # désignerait une population bien plus large que celle que le rôle
            # vise, et gonflerait le coût d'autant.
            membres = self._membres_rh(role["attributes"])
            concernees |= membres & self.identites_sans_droit
            for utilisateur in membres:
                code = self._code_utilisateur.get(utilisateur)
                if code is None:
                    continue
                base = code * self._nb_droits
                accordes.update(base + droit for droit in codes_droits)
        return {
            "identities_without_rights": len(self.identites_sans_droit),
            "identities_without_rights_in_roles": len(concernees),
            "over_provisioning_if_applied": len(accordes - detenus),
        }

    def detail_population(self, roles: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Le détail, groupe par groupe, de ce que `mesurer_population` totalise.

        Le total répond à « combien » ; il ne répond pas à « lesquels », et une
        décision se prend sur le second. Un écran qui annonce 1 166 identités
        concernées sans donner le moyen de les regarder fait exactement ce que
        ce produit reproche aux outils du marché.

        Le tri est fait par **ce que le groupe coûterait**, et non par son
        effectif : dix identités qui recevraient chacune vingt droits pèsent
        plus que cent qui en recevraient deux. C'est ce coût qui décide, et le
        classement doit le refléter — sinon la première ligne de l'écran n'est
        pas la première décision à prendre.

        Mesuré sur un référentiel réel : 1 166 identités concernées se
        répartissent en 222 règles, dont les dix premières couvrent 63 % du
        problème et dont 131 ne concernent qu'une seule personne. C'est ce qui
        rend l'écran praticable — et c'est aussi pourquoi une liste identité par
        identité ne le serait pas.

        Args:
            roles: le modèle affiché, après tout filtrage. Un détail relevé sur
                un autre jeu décrirait des règles que l'utilisateur n'a pas
                sous les yeux.

        Returns:
            list: une entrée par règle RH concernée, du plus coûteux au moins
            coûteux. Chaque entrée porte les critères de la règle, l'effectif
            du groupe, le nombre d'identités sans droit qu'il contient, la part
            qu'elles y représentent, le nombre de droits que le rôle
            accorderait, et le total des couples que cela créerait.
        """
        detenus = self._codes_detenus()
        groupes: Dict[tuple, Dict[str, Any]] = {}
        for role in roles:
            codes_droits = [self._code_droit[droit] for droit in role["rights"]
                            if droit in self._code_droit]
            if not codes_droits:
                continue
            membres = self._membres_rh(role["attributes"])
            oublies = membres & self.identites_sans_droit
            if not oublies:
                continue

            cle = tuple(sorted(role["attributes"].items()))
            groupe = groupes.setdefault(cle, {
                "criteria": dict(role["attributes"]),
                "group_size": len(membres),
                "identities": sorted(oublies),
                "rights": set(),
                "_paires": set(),
            })
            groupe["rights"].update(role["rights"])
            # Les couples, et non un produit : deux rôles sur la même règle RH
            # peuvent accorder le même droit, et le compter deux fois gonflerait
            # le classement des groupes les plus fragmentés.
            for utilisateur in oublies:
                code = self._code_utilisateur.get(utilisateur)
                if code is None:
                    continue
                base = code * self._nb_droits
                groupe["_paires"].update(base + droit for droit in codes_droits)

        detail = []
        for groupe in groupes.values():
            effectif = groupe["group_size"] or 1
            concernees = len(groupe["identities"])
            detail.append({
                "criteria": groupe["criteria"],
                "group_size": groupe["group_size"],
                "without_rights": concernees,
                "share_pct": round(100 * concernees / effectif, 1),
                "rights_count": len(groupe["rights"]),
                "over_provisioning": len(groupe["_paires"] - detenus),
                "identities": groupe["identities"],
            })
        # À coût égal, le groupe le plus nombreux d'abord : c'est celui dont une
        # seule décision règle le plus de cas.
        detail.sort(key=lambda entree: (-entree["over_provisioning"],
                                        -entree["without_rights"]))
        return detail

    def _codes_detenus(self) -> set:
        """Couples (identité, droit) réellement détenus, codés en entiers.

        Construit à la première demande : la mesure de population est le seul
        endroit qui en a besoin, et le mining ordinaire ne doit pas payer sa
        construction.
        """
        if self._cache_codes_detenus is None:
            self._cache_codes_detenus = set(self._code_par_ligne.tolist())
        return self._cache_codes_detenus

    #: Points d'arbitrage proposés. Ce ne sont pas des réglages : ce sont les
    #: positions du curseur que l'écran donne à essayer. Le premier reproduit
    #: le comportement historique — couverture maximale, coût non regardé.
    ARBITRAGES = (0.0, 0.25, 0.5, 1.0, 2.0, 4.0)

    def front_arbitrage(
        self,
        attributes: List[str],
        min_coverage_pct: float = 70.0,
        min_users: int = 5,
        min_rights: int = 2,
        mining_depth: int = 1,
        excluded_rights: Optional[Sequence[str]] = None,
        arbitrages: Optional[Sequence[float]] = None,
        couverture_visee: Optional[float] = None,
        inclure_sans_droit: bool = False,
        parcimonie_pct: float = 0.0,
        modele_acquis: Optional["ModeleAcquis"] = None,
    ) -> Dict[str, Any]:
        """Ce que chaque position du curseur d'arbitrage donnerait.

        Rend, pour chaque valeur d'arbitrage, le nombre de rôles nécessaires
        pour atteindre l'objectif de couverture et le sur-octroi que cela
        crée. L'écran en fait des points à choisir : l'utilisateur ne saisit pas
        un nombre dont il ignore le sens, il lit « 785 rôles pour 13 248
        sur-octrois » ou « 909 rôles pour 11 330 » et désigne celui qui lui
        convient.

        Sans objectif de couverture, la courbe est plate — mesuré, et c'est la
        raison d'être du paramètre : le glouton épuise alors ses candidats quel
        que soit l'arbitrage, et seul l'ordre change. `couverture_visee` à
        `None` rend donc les points d'épuisement, tous équivalents ou presque,
        et l'écran doit le dire plutôt que de laisser croire à un choix.

        Les candidats sont énumérés **une fois** ; seule la sélection est
        rejouée. C'est ce qui rend la courbe calculable en ligne.

        La courbe part de la couverture **acquise**, comme le calcul lui-même.
        Elle traçait depuis zéro : les paliers annonçaient donc un nombre de
        rôles qui ignorait ceux déjà validés, et ils mentaient d'autant plus
        que le client avait avancé.

        Elle applique la **parcimonie**, pour la même raison. Elle ne la
        recevait pas : l'utilisateur réglait son curseur de parcimonie, puis
        choisissait sa position d'arbitrage sur une courbe calculée sans elle.
        Mesuré sur un référentiel construit pour cela : quatre rôles annoncés à
        chaque position, deux produits. Ce n'est pas un rôle faux, c'est une
        **décision** faussée — et c'est précisément ce que ce produit reproche
        aux outils du marché.
        """
        vide = {"points": [], "total_habs_in_scope": 0,
                "couverture_visee": couverture_visee,
                "parcimonie_pct": parcimonie_pct}
        if self.merged_data.empty or not attributes:
            return vide
        valid_attributes = [a for a in attributes if a in self.identities.columns]
        if not valid_attributes:
            return vide

        exclus = set(excluded_rights or ())
        compteurs = {"ecartes_par_exclusion": 0, "vides_par_acquis": 0}
        candidats = self._candidats(
            valid_attributes, min_coverage_pct, min_users, min_rights,
            mining_depth, exclus, compteurs, set(), inclure_sans_droit,
            modele_acquis)
        lignes_acquises = self.lignes_deja_expliquees(modele_acquis)
        total = len(self.merged_data)
        lignes_visees = (
            None if couverture_visee is None
            else int(total * couverture_visee / 100.0))

        points = []
        for valeur in (arbitrages if arbitrages is not None else self.ARBITRAGES):
            retenus = self._couvrir(candidats, valeur, lignes_visees,
                                    parcimonie_pct,
                                    lignes_acquises=lignes_acquises)
            couvert: set = set(lignes_acquises)
            sur_octroi: set = set()
            for role in retenus:
                couvert |= role["_lignes"]
                sur_octroi |= role["_sur_octroi"]
            points.append({
                "arbitrage": valeur,
                "roles": len(retenus),
                "covered_habs_count": len(couvert),
                "habs_coverage_pct": round(100 * len(couvert) / total, 2) if total else 0.0,
                "over_provisioning_distinct": len(sur_octroi),
                # Comparer deux positions du curseur sur un chiffre qui tait une
                # partie du coût conduirait à retenir la mauvaise : chaque point
                # porte donc aussi le coût d'une attribution réelle.
                **{cle: valeur_mesuree for cle, valeur_mesuree
                   in self.mesurer_population(retenus).items()
                   if cle != "identities_without_rights"},
                # Un objectif que les candidats ne permettent pas d'atteindre
                # doit se voir : sans cela, deux points identiques passeraient
                # pour un choix qui n'en est pas un.
                "objectif_atteint": (lignes_visees is None
                                     or len(couvert) >= lignes_visees),
            })

        return {"points": points, "total_habs_in_scope": total,
                "couverture_visee": couverture_visee,
                # Le réglage sous lequel la courbe a été calculée part avec
                # elle : un point qui le tait ne peut pas être rapproché du
                # mining qui suivra.
                "parcimonie_pct": parcimonie_pct}

    #: Paramètres dont on sait mesurer l'effet. Ce sont ceux qui changent les
    #: candidats — le reste de la liste change la sélection, et se lit sur la
    #: courbe d'arbitrage.
    PARAMETRES_MESURABLES = ("min_coverage_pct", "min_users", "min_rights",
                             "mining_depth", "parcimonie_pct")

    def impact(self, parametre: str, valeurs: Sequence[Any],
               **reglages: Any) -> Dict[str, Any]:
        """Ce que chaque valeur d'un paramètre donnerait, sur ces données-ci.

        Un consultant sait ce que « couverture minimale » veut dire ; il ne
        sait pas ce que 70 % plutôt que 80 % change sur le référentiel qu'il a
        sous les yeux. Une définition ne le lui dira jamais, une mesure oui.

        Chaque valeur exige un mining complet — ces paramètres décident des
        candidats, pas de leur sélection — d'où un appel explicite et un
        nombre de valeurs volontairement petit.

        Args:
            parametre: nom du paramètre à faire varier, parmi
                `PARAMETRES_MESURABLES`.
            valeurs: valeurs à essayer.
            **reglages: les autres paramètres du mining, inchangés.

        Raises:
            ValueError: le paramètre n'est pas mesurable. Refuser plutôt que
                d'ignorer : un bouton qui ne mesure rien est pire qu'un bouton
                absent.
        """
        if parametre not in self.PARAMETRES_MESURABLES:
            raise ValueError(parametre)

        points = []
        for valeur in valeurs:
            resultat = self.mine_roles(**{**reglages, parametre: valeur})
            stats = resultat["stats"]
            points.append({
                "value": valeur,
                "roles": len(resultat["roles"]),
                "covered_habs_count": stats["covered_habs_count"],
                "habs_coverage_pct": stats["habs_coverage_pct"],
                "over_provisioning_distinct": stats["over_provisioning_distinct"],
                # Le coût réel d'une attribution, à côté de celui du calcul :
                # comparer deux valeurs d'un paramètre sur un chiffre qui tait
                # une partie du coût conduirait à choisir la mauvaise.
                "over_provisioning_if_applied":
                    stats["over_provisioning_if_applied"],
                "identities_without_rights_in_roles":
                    stats["identities_without_rights_in_roles"],
                # Rôles qui en raffinent un autre, lui aussi retenu. C'est le
                # chiffre que la parcimonie fait bouger, et il ne se déduit
                # d'aucun des autres : un modèle peut perdre des rôles sans
                # perdre une seule stratification.
                "stratifications": BusinessRoleMiner._compter_stratifications(
                    resultat["roles"]),
            })
        return {"parameter": parametre, "points": points}

    @staticmethod
    def _compter_stratifications(roles: Sequence[Dict[str, Any]]) -> int:
        """Rôles dont un autre rôle retenu énonce la règle en moins précis.

        « Fonction = infirmier » et « fonction = infirmier ET service =
        cardiologie » retenus ensemble : le second est une stratification du
        premier. Mesuré sur le banc, le moteur en gardait onze fois plus que
        le référentiel n'en contenait.
        """
        signatures = {frozenset(role["attributes"].items()) for role in roles}
        return sum(1 for role in roles
                   if any(autre < frozenset(role["attributes"].items())
                          for autre in signatures))

    # -------------------------------------------------------------- interne

    def _candidats(
        self, attributs, min_coverage_pct, min_users, min_rights,
        mining_depth, exclus, compteurs, impacted_users,
        inclure_sans_droit=False, acquis=None,
    ) -> List[Dict[str, Any]]:
        """Tous les rôles possibles, avant toute sélection.

        Séparée de la sélection parce que la courbe d'arbitrage rejoue la
        seconde sans refaire la première : sur un référentiel réel,
        l'énumération des candidats coûte l'essentiel du temps de calcul, et la
        recalculer pour chaque point de la courbe rendrait l'écran inutilisable.
        """
        scope = self.merged_data
        roles: List[Dict[str, Any]] = []
        covered_indices: set = set()
        max_depth = min(mining_depth, len(attributs))
        for depth in range(1, max_depth + 1):
            for combo in combinations(attributs, depth):
                roles.extend(
                    self._mine_combo(
                        scope, list(combo), min_coverage_pct, min_users, min_rights,
                        covered_indices, impacted_users, exclus, compteurs,
                        inclure_sans_droit, acquis,
                    )
                )
        return roles

    @staticmethod
    def _ancetres_par_candidat(
            roles: List[Dict[str, Any]]) -> Dict[int, List[int]]:
        """Pour chaque candidat, les candidats dont la règle est la sienne en
        moins précis.

        « Fonction = infirmier » est un ancêtre de « fonction = infirmier ET
        service = cardiologie » : mêmes attributs, mêmes valeurs, un critère de
        moins. C'est la relation qu'il faut connaître pour dire qu'un rôle
        *stratifie* un autre plutôt que d'énoncer autre chose.

        Le calcul énumère les sous-ensembles stricts de chaque signature. La
        profondeur du mining les borne — trois attributs font six
        sous-ensembles — donc ce parcours reste linéaire en nombre de
        candidats, là où comparer chaque paire serait quadratique.
        """
        par_signature: Dict[frozenset, int] = {}
        for index, role in enumerate(roles):
            par_signature.setdefault(frozenset(role["attributes"].items()), index)

        ancetres: Dict[int, List[int]] = {}
        for index, role in enumerate(roles):
            paires = list(role["attributes"].items())
            trouves = []
            for taille in range(1, len(paires)):
                for sous_ensemble in combinations(paires, taille):
                    candidat = par_signature.get(frozenset(sous_ensemble))
                    if candidat is not None:
                        trouves.append(candidat)
            ancetres[index] = trouves
        return ancetres

    @staticmethod
    def _couvrir(roles: List[Dict[str, Any]],
                 arbitrage: float = 0.0,
                 lignes_visees: Optional[int] = None,
                 parcimonie_pct: float = 0.0,
                 lignes_acquises: Optional[set] = None) -> List[Dict[str, Any]]:
        """Retient les rôles par apport marginal décroissant, écarte le reste.

        C'est l'étape qui manquait. Le moteur énumérait toutes les combinaisons
        d'attributs jusqu'à la profondeur demandée et les proposait toutes,
        triées par taille. Un croisement « fonction × service » reproduisant la
        règle « fonction » était proposé à côté d'elle, sans rien expliquer de
        plus. Sur un référentiel de vérité terrain **sans aucun bruit**, où la
        bonne réponse est connue exactement, le moteur rendait 62 rôles pour 12
        règles réelles, dont 50 sans le moindre apport.

        Le glouton est l'approximation de référence d'un problème de couverture
        d'ensembles : sa solution vaut au plus ln(n) fois l'optimum, et aucun
        algorithme polynomial ne fait mieux sauf si P = NP. Le moteur applicatif
        approché l'applique depuis toujours ; le moteur métier ne l'appliquait
        pas.

        **Départage.** À apport égal, le rôle le moins profond gagne : « qui est
        infirmier reçoit ces droits » est une règle plus simple à expliquer, à
        maintenir et à défendre que « qui est infirmier en cardiologie reçoit
        ces droits », et elle couvre plus de monde. Le score puis le nom
        départagent ensuite, pour que deux exécutions rendent le même modèle.

        Un rôle sans apport marginal n'est pas faux : il énonce une régularité
        vraie. Il est seulement inutile — un autre explique déjà les mêmes
        habilitations. Le proposer à la validation, c'est faire relire deux
        fois la même chose.

        **L'arbitrage.** Maximiser la seule couverture privilégie les gros
        groupes, qui expliquent beaucoup d'un coup — et sur-octroient beaucoup.
        Mesuré face à WaRuM sur un référentiel réel : à couverture égale, ce
        glouton demandait 785 rôles là où l'autre outil en demandait 1 192,
        mais sur-octroyait 8 % de plus.

        `arbitrage` déduit du gain le coût marginal — les couples que ce rôle
        accorderait en trop et qu'aucun rôle déjà retenu n'accorde déjà. À 0,
        le comportement est exactement celui d'avant, coût non calculé compris.
        Au-delà, le glouton accepte de retenir un rôle de plus pour accorder
        moins : à 1, il passe devant WaRuM sur les deux axes à la fois.

        Ce nombre n'a pas vocation à être saisi. L'écran montre les points
        d'arbitrage — *tant de rôles pour tant de sur-octroi* — et l'utilisateur
        choisit un point ; la valeur s'en déduit.

        **L'arbitrage n'a de sens qu'avec un objectif.** Mesuré : laissé courir
        jusqu'à épuisement, le glouton retient de toute façon tout candidat qui
        apporte quelque chose, et l'arbitrage ne change que l'ordre — le
        sur-octroi final passe de 14 738 à 14 679 sur un référentiel réel, soit
        rien. L'écart apparaît quand on **s'arrête** : à 34,46 % de couverture,
        le même arbitrage fait passer de 785 rôles à 909, et le sur-octroi de
        13 248 à 11 330. Choisir de sur-octroyer moins, c'est choisir d'en
        expliquer autant avec des rôles plus petits — et il faut donc dire
        jusqu'où on veut expliquer.

        Args:
            roles: candidats produits par le mining.
            arbitrage: poids du coût face au gain. 0 = couverture maximale.
            lignes_visees: nombre d'habilitations à expliquer avant de
                s'arrêter. `None` épuise les candidats, ce qui est le
                comportement historique.
            parcimonie_pct: part, en pourcentage, de ce qu'explique son
                ancêtre qu'un rôle doit expliquer en plus pour être retenu.
                0 = comportement historique.
            lignes_acquises: habilitations que le catalogue validé explique
                déjà. Le glouton les tient pour couvertes avant de commencer.
                Vide — un espace de travail neuf — le calcul est celui d'avant.

        **La parcimonie.** Mesuré sur le banc à toutes hypothèses levées : le
        moteur retenait **78 stratifications pour 7 réelles**, un facteur onze.
        Il gardait « fonction = X » *et* « fonction = X ET service = A » *et*
        « ET service = B »… là où la vérité n'en contient qu'une poignée. Sur
        cent onze rôles proposés, cinq pour cent seulement étaient sans rapport
        avec une règle réelle : le moteur n'invente pas, il découpe trop fin.

        Le départage à apport égal, plus haut, ne suffisait pas : sous bruit,
        un raffinement capte presque toujours quelques lignes que son parent
        n'explique pas. La condition d'égalité stricte ne se déclenchait donc
        jamais, et rien ne mettait un prix sur la complexité.

        `parcimonie_pct` exige qu'un raffinement batte son ancêtre d'une marge
        et non d'un cheveu : il n'est retenu que s'il explique au moins cette
        part de ce que son ancêtre explique. La part se transporte d'un
        référentiel de trois mille identités à un de trois cent mille, ce qu'un
        nombre d'attributions ne ferait pas.

        Ce n'est pas gratuit et ce n'est pas au produit d'en décider : les
        enfants dont le parent est déjà retenu apportent **43 % de la
        couverture marginale** du modèle. C'est un arbitrage entre simplicité
        et couverture, de la même forme que celui entre couverture et
        sur-octroi — et présenté de la même façon, en montrant ce que chaque
        position coûte.
        """
        if not roles:
            return []

        restants = {index: role for index, role in enumerate(roles)}
        # Le glouton part de ce que le catalogue explique déjà, et non de rien.
        #
        # C'est l'inversion de ce lot : un candidat est classé par ce qu'il
        # ajoute au **modèle réel**, pas par ce qu'il ajoute aux autres
        # candidats. Sans cela, valider dans l'ordre de l'écran donne un
        # modèle, valider le septième puis le douzième en donne un autre —
        # moins bon, sans que rien ne l'annonce.
        #
        # Le coût part du même endroit : un couple que le catalogue accorde
        # déjà ne coûte rien de plus au rôle qui le réaccorde.
        couvert: set = set(lignes_acquises or ())
        accorde: set = set()
        retenus: List[Dict[str, Any]] = []
        # À parcimonie nulle, la relation d'ancêtre n'est pas même calculée :
        # le comportement et le temps de calcul restent ceux d'avant, comme
        # pour l'arbitrage.
        ancetres = (BusinessRoleMiner._ancetres_par_candidat(roles)
                    if parcimonie_pct else {})
        indices_retenus: set = set()

        while restants:
            # Apport marginal de chaque candidat. Un candidat sans apport ne
            # peut plus en gagner : il sort définitivement.
            apports = {index: role["_lignes"] - couvert
                       for index, role in restants.items()}
            apports = {index: apport for index, apport in apports.items() if apport}

            if parcimonie_pct:
                # Un raffinement dont l'ancêtre est déjà retenu doit expliquer
                # une part de ce que cet ancêtre explique. L'ancêtre le plus
                # large commande : satisfaire celui-là satisfait les autres.
                apports = {
                    index: apport for index, apport in apports.items()
                    if len(apport) * 100.0 >= parcimonie_pct * max(
                        (len(roles[aieul]["_lignes"])
                         for aieul in ancetres[index] if aieul in indices_retenus),
                        default=0)
                }

            if not apports:
                break

            if arbitrage:
                couts = {index: len(restants[index]["_sur_octroi"] - accorde)
                         for index in apports}
            else:
                # À arbitrage nul, le coût n'est pas calculé du tout : le
                # comportement et le temps de calcul sont ceux d'avant ce lot,
                # au bit près. C'est ce qui rend le réglage sans risque.
                couts = None

            def cle(index):
                role = restants[index]
                gain = len(apports[index])
                score = gain if couts is None else gain - arbitrage * couts[index]
                return (
                    -score,                    # meilleur arbitrage
                    len(role["attributes"]),   # règle la plus simple
                    -role["score"],
                    role["name"],
                    # Départage **total**. Le nom ne suffit pas : deux règles
                    # peuvent le partager, et `min()` retombait alors sur
                    # l'ordre d'insertion des candidats — donc sur l'ordre dans
                    # lequel l'utilisateur a saisi ses attributs. L'identifiant
                    # est unique par construction ; deux exécutions rendent
                    # ainsi le même modèle, dans le même ordre.
                    role["id"],
                )

            index = min(apports, key=cle)
            role = restants[index]
            apport = apports[index]

            couvert |= apport
            role["marginal_gain"] = len(apport)
            role["marginal_cost"] = (len(role["_sur_octroi"] - accorde)
                                     if couts is None else couts[index])
            accorde |= role["_sur_octroi"]
            role["rank"] = len(retenus) + 1
            retenus.append(role)
            indices_retenus.add(index)
            del restants[index]

            if lignes_visees is not None and len(couvert) >= lignes_visees:
                break

        return retenus

    def _mine_combo(
        self, scope, combo, min_coverage_pct, min_users, min_rights,
        covered_indices, impacted_users, exclus, compteurs,
        inclure_sans_droit=False, acquis=None,
    ) -> List[Dict[str, Any]]:
        """Découvre les rôles pour une combinaison d'attributs donnée.

        `inclure_sans_droit` décide de la population des groupes. Sans lui, un
        groupe est fait des seules identités qui détiennent au moins un droit :
        celles qui n'en ont aucun n'entrent ni dans l'effectif, ni dans le
        calcul de la part détentrice, ni dans le coût — alors que la règle RH
        les désigne et qu'elles recevraient bien les droits du rôle.
        """
        try:
            # Effectif de chaque groupe, et utilisateurs qui le composent.
            # La source décide de qui appartient au groupe : le référentiel
            # d'identités entier, ou les seules identités équipées.
            source = self.identities if inclure_sans_droit else scope
            populations = source.groupby(combo, observed=True)[COL_USER_ID].agg(['nunique', 'unique'])
        except KeyError as exc:
            logger.warning("Mining métier : colonne absente pour %s (%s)", combo, exc)
            return []

        populations = populations[populations['nunique'] >= min_users]
        if populations.empty:
            return []

        # Détenteurs de chaque droit dans chaque groupe. Le tri par droit issu
        # du groupby fixe l'ordre des égalités de couverture, et rend donc le
        # résultat reproductible.
        rights = scope.groupby(combo + [COL_RIGHT_ID], observed=True).agg(
            holders=(COL_USER_ID, 'nunique'),
            rows=('global_index', list),
        ).reset_index()

        rights = rights.merge(
            populations['nunique'].rename('population'),
            left_on=combo[0] if len(combo) == 1 else combo,
            right_index=True,
        )

        rights['coverage'] = rights['holders'] / rights['population'] * 100
        selected = rights[rights['coverage'] >= min_coverage_pct]
        if selected.empty:
            return []

        # Droits les mieux couverts en tête, à couverture égale ordre du groupby.
        selected = selected.sort_values('coverage', ascending=False, kind='stable')

        # Accès O(1) aux membres d'un groupe : un .loc par groupe coûte cher
        # dès quelques milliers de groupes. Les clés sont normalisées en
        # tuples, car un groupby sur une seule colonne indexe par scalaire.
        members_by_group = {
            (index if isinstance(index, tuple) else (index,)): members
            for index, members in populations['unique'].items()
        }

        produced: List[Dict[str, Any]] = []
        for key, group in selected.groupby(combo, observed=True, sort=False):
            values = key if isinstance(key, tuple) else (key,)
            signature = dict(zip(combo, values))
            members = members_by_group[values]

            # Ce que le catalogue octroie déjà à **tous** les membres de ce
            # groupe n'a rien à faire dans le rôle. Le retrait se fait ici,
            # avec les droits socles, et non sur le résultat : la couverture,
            # le sur-octroi et le score doivent décrire le rôle qu'on propose,
            # pas celui qu'on aurait proposé sans le catalogue.
            #
            # C'est le défaut remonté du terrain : deux rôles validés couvrant
            # ensemble toute la population, tous deux porteurs du même droit,
            # et un mining qui le remettait dans chaque nouveau candidat.
            droits_du_groupe = group[COL_RIGHT_ID].tolist()
            deja_octroyes = acquis.deja_octroyes(members) if acquis else set()
            deja_octroyes = {droit for droit in deja_octroyes
                             if droit in set(droits_du_groupe)}
            a_retirer = exclus | deja_octroyes

            retenus = group[~group[COL_RIGHT_ID].isin(a_retirer)] if a_retirer else group
            rights_list = retenus[COL_RIGHT_ID].tolist()
            if len(rights_list) < min_rights:
                # Le groupe passait le seuil avant retrait : c'est bien le
                # retrait qui lui enlève son rôle, et non sa maigreur. Les deux
                # causes sont comptées séparément — « ce candidat n'apporte
                # rien, tout est déjà octroyé » est une information de
                # gouvernance, pas un déchet.
                if len(group) >= min_rights:
                    if deja_octroyes and len(
                            [d for d in droits_du_groupe if d not in exclus]) >= min_rights:
                        compteurs["vides_par_acquis"] += 1
                    else:
                        compteurs["ecartes_par_exclusion"] += 1
                continue

            # Les parents se cherchent sur les droits **d'avant** le retrait :
            # ce sont eux qui viennent d'être retirés.
            parents = (acquis.parents(members, droits_du_groupe)
                       if acquis and deja_octroyes else [])

            population = int(retenus['population'].iloc[0])
            avg_coverage = float(retenus['coverage'].mean())
            held = int(retenus['holders'].sum())
            granted = population * len(rights_list)

            # Les habilitations portant un droit exclu ne sont couvertes par
            # aucun rôle : les compter comme telles gonflerait la couverture
            # du modèle de tout ce qu'il n'explique pas.
            lignes_du_role: set = set()
            for rows in retenus['rows']:
                lignes_du_role.update(rows)
            impacted_users.update(members)

            # Couples que ce rôle accorderait sans qu'ils existent aujourd'hui.
            # Conservés en extension — et non comme un simple compte — parce
            # que deux rôles peuvent sur-octroyer le même couple : la sélection
            # doit pouvoir ne le facturer qu'une fois.
            codes_membres = np.fromiter(
                (self._code_utilisateur[u] for u in members),
                dtype=np.int64, count=len(members))
            codes_droits = np.fromiter(
                (self._code_droit[d] for d in rights_list),
                dtype=np.int64, count=len(rights_list))
            accordes = (codes_membres[:, None] * self._nb_droits
                        + codes_droits[None, :]).ravel()
            detenus_du_role = self._code_par_ligne[
                np.fromiter(lignes_du_role, dtype=np.int64,
                            count=len(lignes_du_role))]
            sur_octroi_du_role = set(
                np.setdiff1d(accordes, detenus_du_role, assume_unique=False).tolist())

            # Comment le groupe se partage devant ces droits. La couverture
            # moyenne n'en dit rien : 85 % peut vouloir dire « chacun manque un
            # droit sur sept » ou « un sur cinq n'en détient aucun ». Ce ne sont
            # pas les mêmes objets, et seule la seconde forme est suspecte.
            # Codes dédoublonnés : une habilitation présente deux fois dans le
            # fichier compterait sinon pour deux droits, et un membre paraîtrait
            # détenir le rôle entier sans l'avoir.
            detenus_par_membre = np.bincount(
                np.unique(detenus_du_role) // self._nb_droits)
            noyau = int(np.count_nonzero(detenus_par_membre == len(rights_list)))
            avec_au_moins_un = int(np.count_nonzero(detenus_par_membre))
            sans_aucun = population - avec_au_moins_un
            hors_noyau = population - noyau

            produced.append({
                # L'identité d'un rôle métier est sa règle et ses droits, non
                # un tirage : un candidat refusé doit rester refusé au mining
                # suivant, et une décision doit pouvoir être rattachée au
                # candidat sur lequel elle a été prise. Un identifiant tiré au
                # hasard rendait l'un et l'autre impossibles.
                "id": identifiant_metier(signature, rights_list),
                # Nom technique ; le libellé lisible est construit par le client
                # à partir de la clé i18n ci-dessous.
                #
                # L'attribut y figure autant que sa valeur. Sans lui, deux
                # règles distinctes portant la même valeur — `service = Lyon` et
                # `site = Lyon` — sortaient sous le même nom : deux populations
                # différentes, deux ensembles de droits différents, un seul nom
                # dans le catalogue. Mesuré.
                "name": "BIZ_" + "_".join(
                    f"{attribut}-{signature[attribut]}"
                    for attribut in sorted(signature)),
                "description_key": "mining.role.business_description",
                "description_params": {
                    "criteria": ", ".join(f"{k} = {v}" for k, v in signature.items()),
                    "users": population,
                    "rights": len(rights_list),
                },
                "role_type": "METIER",
                "rights": rights_list,
                # Couple droit / couverture : la mise en forme appartient au client.
                "rights_display": [
                    {"right": right, "coverage_pct": int(coverage)}
                    for right, coverage in zip(rights_list, retenus['coverage'])
                ],
                # Droits socles retires de ce role : l'ecart entre ce que le
                # groupe partageait et ce que le role accorde.
                "birth_rights_excluded": len(group) - len(rights_list),
                # Droits que le catalogue octroie déjà à tous les membres, et
                # qui ont donc été retirés du candidat. Rendus en extension et
                # non en compte : un droit qui disparaît sans qu'on puisse dire
                # lequel est pire que le droit en trop.
                "droits_deja_octroyes": sorted(deja_octroyes),
                # Rôles validés dont ce candidat hérite : ils couvrent toute sa
                # population et leurs droits sont inclus dans les siens. C'est
                # la forme normale d'un modèle de rôles — « hérite de X, plus
                # ces droits-ci » — et ce que le client attend dans son IGA.
                "parent_roles": [parent.identifiant for parent in parents],
                "parent_role_names": [parent.nom for parent in parents],
                "users": list(members),
                "user_count": population,
                "right_count": len(rights_list),
                "coverage_pct": round(avg_coverage, 1),
                # Part du groupe qui détient l'intégralité des droits du rôle.
                # La population d'un groupe est au moins de un — un `groupby`
                # ne rend pas de groupe vide —, la division est donc sûre.
                "noyau_pct": round(100.0 * noyau / population, 1),
                # Part de ceux que la règle laisse de côté qui n'en détiennent
                # **aucun**. Voir `scission` dans la documentation du module :
                # c'est ce qui distingue une règle à exceptions d'un groupe qui
                # se scinde en deux.
                "scission_pct": (round(100.0 * sans_aucun / hors_noyau, 1)
                                 if hors_noyau else 0.0),
                "stats_covered_rights": held,
                # Droits que la règle accorderait à des membres qui ne les
                # détiennent pas aujourd'hui : le coût du rôle.
                "stats_over_provisioning": granted - held,
                "score": int(population * len(rights_list) * (avg_coverage / 100)),
                "attributes": signature,
                # Lignes d'habilitation que ce rôle explique. Conservées par
                # rôle — et non fondues dans un ensemble global — parce que la
                # sélection gloutonne a besoin de les comparer entre elles.
                "_lignes": lignes_du_role,
                # Couples (identité, droit) sur-octroyés, codés en entiers.
                "_sur_octroi": sur_octroi_du_role,
            })

        return produced
