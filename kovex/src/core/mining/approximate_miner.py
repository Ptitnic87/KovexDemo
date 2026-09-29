# src/core/mining/approximate_miner.py
"""
Mining approché de rôles applicatifs.

Le mining exact regroupe les utilisateurs ayant exactement la même signature
de droits. C'est le critère le plus restrictif possible : sur un référentiel
réel, la majorité des utilisateurs ont une signature unique et ne sont donc
jamais regroupés.

Ce moteur relâche la contrainte au moyen d'un seuil de similarité θ, choisi
par l'utilisateur :

1. Génération de candidats par clôture. Pour chaque droit r, on prend
   l'ensemble U(r) de ses détenteurs, puis on retient les droits partagés par
   au moins θ · |U(r)| d'entre eux. Cet ensemble R est le rôle candidat.
   À θ = 1 on retrouve une clôture exacte (aucun droit octroyé en trop) ;
   en dessous, on accepte qu'une minorité de membres ne détienne pas encore
   tous les droits du rôle.

2. Extension des membres. Un utilisateur rejoint le rôle dès qu'il détient au
   moins θ · |R| des droits de R, même s'il ne détient pas le droit d'amorce.

3. Couverture gloutonne paresseuse. Les rôles sont retenus dans l'ordre du
   gain marginal : le nombre d'habilitations réelles qu'ils couvrent et que
   les rôles déjà retenus ne couvraient pas. Deux exécutions sur les mêmes
   données produisent strictement le même résultat.

Chaque rôle porte ses métriques réelles, dont le sur-octroi — les couples
(utilisateur, droit) que le rôle accorderait sans qu'ils existent aujourd'hui.
C'est la contrepartie du gain de couverture, et elle doit rester visible.

Le moteur ne dépend que de numpy et de la structure CSR de la matrice.
"""

from __future__ import annotations

import heapq
import logging
from fractions import Fraction
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from src.core.mining.selection_exacte import (ARRET_NON_APPLICABLE,
                                              ARRET_PLANCHER,
                                              DELAI_PAR_DEFAUT_S,
                                              EFFORT_PAR_DEFAUT,
                                              SELECTION_GLOUTONNE,
                                              SELECTION_PAR_DEFAUT,
                                              selectionner,
                                              valider_selection)

logger = logging.getLogger(__name__)


#: Les quatre façons d'amorcer un candidat. Ce ne sont pas des variantes d'un
#: même calcul : chacune trouve des rôles que les autres ne trouvent pas.
#:
#: - `cloture` part d'un droit et prend ce que ses détenteurs ont en commun.
#:   Elle trouve les rôles dont au moins un droit est caractéristique ;
#: - `signature` part de l'ensemble exact des droits d'une identité. Elle
#:   trouve ce que le mining exact trouve, et garantit que le mode approché ne
#:   rende jamais moins ;
#: - `intersection` croise les profils deux à deux. Elle trouve les rôles
#:   formés du terrain commun à deux populations, **dont aucun droit n'est
#:   propre au groupe** — que ni l'une ni l'autre des deux premières
#:   n'atteint ;
#: - `treillis` recroise ces terrains communs avec les profils, jusqu'à ce que
#:   plus rien de nouveau n'apparaisse. Il trouve le terrain commun à **trois
#:   populations ou plus**, que le croisement deux à deux n'atteint pas.
GENERATEUR_CLOTURE = "cloture"
GENERATEUR_SIGNATURE = "signature"
GENERATEUR_INTERSECTION = "intersection"
GENERATEUR_TREILLIS = "treillis"

#: Ordre d'exécution, et liste fermée : le produit ne sait amorcer que de ces
#: quatre façons, et chacune est aussi une clé de traduction —
#: `mining.generateur.<code>`.
GENERATEURS: tuple = (GENERATEUR_CLOTURE, GENERATEUR_SIGNATURE,
                      GENERATEUR_INTERSECTION, GENERATEUR_TREILLIS)

#: Ce qui tourne quand l'appelant ne choisit pas : les trois premières.
#:
#: Le treillis n'en fait pas partie, et c'est mesuré. Sur les huit jeux HP
#: dont l'optimum est publié, il ne change le résultat que sur un seul
#: (Americas small : 179 → 178 rôles, l'optimum) ; il y multiplie le calcul
#: par trois sur Customer et par six sur Americas large, où le résultat était
#: déjà optimal. Il sert là où la donnée est propre et où l'on veut le plus
#: petit modèle — c'est un choix, pas un défaut.
GENERATEURS_PAR_DEFAUT: tuple = (GENERATEUR_CLOTURE, GENERATEUR_SIGNATURE,
                                 GENERATEUR_INTERSECTION)

#: Profils distincts au-delà desquels le croisement deux à deux n'est pas
#: tenté.
#:
#: Le croisement est **quadratique** : mille profils font un demi-million de
#: paires, vingt mille en font deux cents millions. La borne n'est pas un choix
#: métier, c'est la limite au-delà de laquelle l'écran cesserait de répondre —
#: et elle est **annoncée** quand elle mord, plutôt que de faire disparaître
#: des candidats en silence.
PROFILS_CROISES_MAX = 20000

#: Candidats que le treillis peut ajouter, au plus. Repli quand le workspace
#: n'en déclare pas.
#:
#: Le nombre d'ensembles qu'on obtient en recroisant les profils jusqu'au
#: point fixe n'a pas de borne utile : 2 762 sur Americas small (1,6 s), mais
#: plus que la mémoire d'un poste sur Americas large. La borne n'est donc pas
#: un choix métier, c'est la protection du serveur ; elle est **annoncée**
#: quand elle mord (`treillis_borne`), pour qu'un résultat obtenu sur un
#: treillis partiel ne se lise pas comme celui du treillis complet. Vingt
#: mille couvre, avec de la marge, les 920 ajouts qu'il faut à Americas small
#: pour atteindre son optimum.
TREILLIS_MAX = 20000

#: Plafond de repli du nombre de rôles qu'une demande peut réclamer.
#:
#: Ce n'est **pas** une limite métier : c'est la borne qui protège le serveur
#: d'une demande absurde. Elle était écrite en dur à cinq mille dans deux
#: déclarations de champ, et sur un référentiel qui porte plus de rôles
#: candidats que cela, l'avertissement « plafond atteint » de la courbe ne
#: pouvait plus jamais disparaître : la seule réponse — monter la borne —
#: était interdite. Elle se règle donc par workspace, et cette valeur n'est
#: que ce qui s'applique quand rien n'a été réglé.
MAX_ROLES_PLAFOND = 5000

#: Apport minimal de repli : un. C'est-à-dire aucun plancher effectif — tout
#: candidat qui explique au moins une habilitation non couverte est retenu.
#:
#: Ce n'est pas une valeur choisie pour sa qualité, c'est le comportement
#: historique, gardé par défaut pour qu'aucun référentiel ne change de résultat
#: à la mise à jour. Le bon réglage se lit sur la courbe des apports du
#: référentiel : sur le banc de six mille identités, les rôles plantés
#: apportent cent quarante à cent cinquante habilitations et les fragments six
#: ou moins — n'importe quelle valeur dans cet intervalle sépare les deux.
APPORT_MINIMAL = 1


def porteurs_requis(theta: float, effectif: int) -> int:
    """Combien d'éléments sur `effectif` pour atteindre la part `theta`.

    Compté en **entiers**, jamais en flottants. `math.ceil(0.07 * 100)` vaut
    huit et non sept, parce que 0,07 n'a pas d'écriture binaire exacte : un
    droit sortait alors de la clôture, ou un membre du rôle, sans que rien ne
    le signale. La fraction reconstruit la décimale que l'utilisateur a
    écrite, et la division au plafond se fait sur des entiers.

    Jamais zéro : un rôle sans membre n'est pas un rôle, et un ensemble de
    droits qu'aucun droit ne compose non plus.
    """
    if effectif <= 0:
        return 1
    part = Fraction(str(theta))
    plafond = -((-part.numerator * effectif) // part.denominator)
    return max(1, int(plafond))


class ApproximateRoleMiner:
    """Découvre des rôles applicatifs approchés dans la matrice utilisateurs x droits."""

    def __init__(self, loader):
        self.loader = loader
        matrix = loader.matrix

        if matrix is None or matrix.shape[0] == 0 or matrix.nnz == 0:
            self._empty = True
            return

        self._empty = False
        csr = matrix.tocsr() if hasattr(matrix, "tocsr") else matrix
        # `np.intp` et non `np.int64` : c'est le type dont numpy se sert pour
        # indexer, et il suit la plateforme — 64 bits sur un poste ordinaire,
        # 32 bits sur une plateforme 32 bits, WebAssembly comprise. Forcer 64
        # bits partout faisait échouer `np.repeat` et `np.searchsorted` sur ces
        # plateformes, qui refusent de rétrécir un entier sans qu'on le demande.
        self._indptr = np.asarray(csr.indptr, dtype=np.intp)
        self._indices = np.asarray(csr.indices, dtype=np.intp)
        self._n_users, self._n_rights = csr.shape

        self._user_decoder = {v: k for k, v in loader.user_encoder.items()}
        self._right_decoder = {v: k for k, v in loader.right_encoder.items()}

    # ------------------------------------------------------------------ utils

    def _rights_of(self, user: int) -> np.ndarray:
        return self._indices[self._indptr[user]:self._indptr[user + 1]]

    def _build_transpose(self, allowed_rights: np.ndarray):
        """Construit l'index droit -> utilisateurs, restreint aux droits autorisés."""
        degrees = np.diff(self._indptr)
        rows = np.repeat(np.arange(self._n_users, dtype=np.intp), degrees)
        cols = self._indices

        if allowed_rights is not None:
            keep = allowed_rights[cols]
            rows, cols = rows[keep], cols[keep]

        order = np.argsort(cols, kind="stable")
        # Le type est **explicite**, jamais celui de la plateforme. `np.arange`
        # rend un entier 64 bits sur un poste ordinaire et un entier 32 bits sur
        # une plateforme 32 bits — WebAssembly en est une —, et numpy refuse
        # alors la comparaison avec `cols`, qui est en 64 bits. Le calcul
        # s'arrêtait donc là, uniquement sur ces plateformes, avec un message
        # qui ne parlait que de types.
        bornes = np.arange(self._n_rights + 1, dtype=np.intp)
        return rows[order], np.searchsorted(cols[order], bornes)

    # ------------------------------------------------------------------ mining

    def mine(
        self,
        similarity_threshold: float,
        min_users: int,
        min_rights: int,
        excluded_rights: Optional[Sequence[str]] = None,
        max_roles: int = 500,
        roles_valides: Optional[Sequence[Dict[str, Any]]] = None,
        generateurs: Optional[Sequence[str]] = None,
        profils_croises_max: int = PROFILS_CROISES_MAX,
        apport_minimal: int = 1,
        treillis_max: int = TREILLIS_MAX,
        selection: str = SELECTION_PAR_DEFAUT,
        selection_effort: int = EFFORT_PAR_DEFAUT,
        selection_delai_s: float = DELAI_PAR_DEFAUT_S,
    ) -> Dict[str, Any]:
        """Exécute le mining approché.

        Args:
            similarity_threshold: θ dans ]0, 1]. 1.0 = clôture exacte, sans
                sur-octroi. En dessous, on accepte des rôles approchés.
            min_users: effectif minimal d'un rôle.
            min_rights: nombre minimal de droits d'un rôle.
            excluded_rights: droits à ignorer (droits socles, exclusions
                manuelles). Ils ne peuvent ni amorcer ni composer un rôle.
            max_roles: nombre maximal de rôles retournés.
            generateurs: façons d'amorcer un candidat, parmi `GENERATEURS`.
                Aucune n'est meilleure en soi : chacune trouve des rôles que
                les autres ne trouvent pas, et les trois premières ensemble
                coûtent le croisement quadratique des profils. Le choix
                appartient donc à l'utilisateur ; par défaut,
                `GENERATEURS_PAR_DEFAUT`.
            profils_croises_max: borne du croisement. Au-delà, il porte sur un
                échantillon régulier et `croisement_borne` le dit.
            treillis_max: candidats que le treillis peut ajouter. Atteinte
                avant le point fixe, `treillis_borne` le dit.
            apport_minimal: nombre d'habilitations non encore couvertes qu'un
                candidat doit apporter pour être retenu. `min_users` et
                `min_rights` disent quelle **taille** un rôle doit avoir ;
                celui-ci dit ce qu'il doit **expliquer**. Un vaut le
                comportement d'avant — tout candidat apportant au moins une
                habilitation est retenu — et c'est délibéré : un réglage qui
                change le résultat sans qu'on l'ait touché n'est pas un
                réglage.
            roles_valides: rôles déjà validés du catalogue. Les habilitations
                qu'ils expliquent sont tenues pour couvertes avant que le
                glouton ne commence : un candidat est ainsi classé par ce qu'il
                ajoute au **modèle réel**, et non par ce qu'il ajoute aux
                autres candidats. Sans catalogue, le calcul est celui d'avant.
            selection: comment les rôles sont choisis parmi les candidats, parmi
                `SELECTIONS`. `gloutonne` retient à chaque pas le candidat qui
                explique le plus ; `exacte` repart de ce que le glouton explique
                et cherche le plus petit ensemble de candidats qui l'explique
                aussi, sans plus de sur-octroi. Elle ne rend jamais pire.
            selection_effort: nœuds de branchement accordés à la sélection
                exacte. Une borne en nœuds, et non en temps, garde le résultat
                reproductible d'une machine à l'autre.
            selection_delai_s: délai de protection de la sélection exacte.

        Returns:
            {"roles": [...], "stats": {...}}
        """
        if not 0.0 < similarity_threshold <= 1.0:
            raise ValueError("similarity_threshold doit appartenir à ]0, 1]")
        valider_selection(selection)

        def vide(generateurs_employes=(), croisement_borne=False,
                 treillis_borne=False):
            """Un résultat sans rôle, qui dit quand même ce qui a été tenté.

            Ces deux champs étaient écrits en dur à faux dans le résultat
            vide. Un croisement borné qui ne produit aucun candidat rendait
            donc « rien trouvé, croisement tenté » — exactement la lecture que
            ce champ existe pour empêcher : une couverture nulle prise pour un
            référentiel sans structure, alors que c'est le calcul qui s'est
            arrêté avant de chercher.
            """
            return {
                "roles": [],
                "stats": {
                    "total_assignments": 0,
                    "covered_assignments": 0,
                    "assignments_uncovered": 0,
                    "coverage_pct": 0.0,
                    "over_granted": 0,
                    "over_granted_pct": 0.0,
                    "users_covered": 0,
                    "rights_covered": 0,
                    "candidates_generated": 0,
                    "candidats_sous_apport": 0,
                    "tronquee": False,
                    "generateurs": list(generateurs_employes),
                    "croisement_borne": croisement_borne,
                    "treillis_borne": treillis_borne,
                    **self._compte_rendu_de_selection(selection),
                    "selection_roles": 0,
                },
            }

        if self._empty:
            return vide()

        theta = float(similarity_threshold)
        excluded = set(excluded_rights or ())
        allowed = np.ones(self._n_rights, dtype=bool)
        for right in excluded:
            index = self.loader.right_encoder.get(right)
            if index is not None:
                allowed[index] = False

        users_by_right, right_ptr = self._build_transpose(allowed)
        if users_by_right.size == 0:
            return vide()

        choisis = (tuple(generateurs) if generateurs is not None
                   else GENERATEURS_PAR_DEFAUT)
        inconnus = [nom for nom in choisis if nom not in GENERATEURS]
        if inconnus:
            # Refusé plutôt qu'ignoré : un générateur mal orthographié
            # silencieusement écarté ferait rendre moins de rôles sans que
            # personne ne sache pourquoi.
            raise ValueError(f"générateur inconnu : {', '.join(inconnus)}")

        candidates: List[Dict[str, np.ndarray]] = []
        vus: set = set()
        if GENERATEUR_CLOTURE in choisis:
            candidates += self._generate_candidates(
                theta, min_users, min_rights, allowed, users_by_right, right_ptr)
            vus = {c["rights"].tobytes() for c in candidates}
        if GENERATEUR_SIGNATURE in choisis:
            candidates += self._signature_candidates(
                theta, min_users, min_rights, allowed, users_by_right,
                right_ptr, seen_rights=vus)
        croisement_borne = False
        if GENERATEUR_INTERSECTION in choisis or GENERATEUR_TREILLIS in choisis:
            # Le comptage se faisait ici, en parcourant les profils une seconde
            # fois pour rien. La restriction a lieu dans le générateur : c'est
            # lui qui la rend.
            croisement_borne = self._profils_restreints(
                min_rights, allowed, profils_croises_max)
        if GENERATEUR_INTERSECTION in choisis:
            candidates += self._intersection_candidates(
                theta, min_users, min_rights, allowed, users_by_right,
                right_ptr, seen_rights=vus, profils_max=profils_croises_max)
        treillis_borne = False
        if GENERATEUR_TREILLIS in choisis:
            ajouts, treillis_borne = self._treillis_candidates(
                theta, min_users, min_rights, allowed, users_by_right,
                right_ptr, seen_rights=vus, profils_max=profils_croises_max,
                budget=treillis_max)
            candidates += ajouts
        logger.info("Mining approché : %d candidats générés (θ=%.2f, %s)",
                    len(candidates), theta, ", ".join(choisis))
        if not candidates:
            return vide(choisis, croisement_borne, treillis_borne)

        acquis = self._positions_acquises(roles_valides, allowed)
        rendu = self._greedy_cover(candidates, max_roles, allowed, theta,
                                   acquis, apport_minimal)
        if selection != SELECTION_GLOUTONNE:
            rendu = self._reselectionner(
                selection, rendu, candidates, allowed, theta, acquis,
                apport_minimal, selection_effort, selection_delai_s)
        else:
            rendu["stats"].update(self._compte_rendu_de_selection(selection))
        rendu.pop("_retenus")
        rendu.pop("_couvert")
        # Le nombre de rôles que la sélection a retenus, avant tout filtre de
        # l'appelant : c'est lui que « au lieu de » compare au glouton.
        rendu["stats"]["selection_roles"] = len(rendu["roles"])
        rendu["stats"]["generateurs"] = list(choisis)
        # Le croisement n'a pas été tenté : le taire ferait lire une couverture
        # basse comme un référentiel sans structure, alors que c'est le calcul
        # qui s'est arrêté.
        rendu["stats"]["croisement_borne"] = croisement_borne
        # Le treillis s'est arrêté sur son budget : le résultat est celui d'un
        # treillis partiel, et le taire ferait lire le nombre de rôles comme
        # le plus petit que ces données admettent.
        rendu["stats"]["treillis_borne"] = treillis_borne
        return rendu

    # ------------------------------------------------- génération de candidats

    def _generate_candidates(
        self, theta, min_users, min_rights, allowed, users_by_right, right_ptr
    ) -> List[Dict[str, np.ndarray]]:
        """Un candidat par clôture de droit, dédoublonné sur l'ensemble de droits."""
        right_counter = np.zeros(self._n_rights, dtype=np.int32)
        user_counter = np.zeros(self._n_users, dtype=np.int32)
        seen: set = set()
        candidates: List[Dict[str, np.ndarray]] = []

        for right in range(self._n_rights):
            if not allowed[right]:
                continue

            seed_users = users_by_right[right_ptr[right]:right_ptr[right + 1]]
            if seed_users.size < min_users:
                continue

            # Fréquence de chaque droit parmi les détenteurs du droit d'amorce.
            touched: List[np.ndarray] = []
            for user in seed_users:
                user_rights = self._rights_of(user)
                right_counter[user_rights] += 1
                touched.append(user_rights)

            required = porteurs_requis(theta, seed_users.size)
            closure = np.flatnonzero((right_counter >= required) & allowed)

            for user_rights in touched:
                right_counter[user_rights] = 0

            if closure.size < min_rights:
                continue

            key = closure.tobytes()
            if key in seen:
                continue
            seen.add(key)

            members = self._expand_members(
                closure, theta, user_counter, users_by_right, right_ptr
            )
            if members.size < min_users:
                continue

            candidates.append({"rights": closure, "users": members})

        return candidates

    def _profils_distincts(self, min_rights, allowed) -> List[np.ndarray]:
        """Les ensembles de droits distincts portés par au moins une identité.

        Deux identités de même profil n'ont pas à être croisées deux fois : ce
        qui compte est l'ensemble, pas qui le porte. Sur un référentiel réel le
        nombre de profils distincts est très inférieur au nombre d'identités,
        et c'est ce qui rend le croisement abordable.
        """
        vus: Dict[bytes, np.ndarray] = {}
        for utilisateur in range(self._n_users):
            droits = self._rights_of(utilisateur)
            retenus = np.sort(droits[allowed[droits]])
            if retenus.size < min_rights:
                continue
            vus.setdefault(retenus.tobytes(), retenus)
        # Ordonnés par contenu : deux lectures des mêmes données rendent la
        # même liste, dans le même ordre. C'est ce que suppose la restriction
        # ci-dessous, et c'est ce qu'un auditeur attend d'un calcul.
        return [vus[cle] for cle in sorted(vus)]

    def _profils_restreints(self, min_rights, allowed, profils_max) -> bool:
        """La borne va-t-elle restreindre le croisement ?

        Rendu à part parce que l'écran doit le savoir **avec** le résultat : une
        couverture obtenue sur un croisement partiel n'est pas celle qu'on
        aurait eue, et le taire la ferait lire comme un plafond du référentiel.
        """
        return len(self._profils_distincts(min_rights, allowed)) > profils_max

    def _profils_croisables(self, min_rights, allowed,
                            profils_max) -> List[np.ndarray]:
        """Les profils que le croisement compare : tous, ou un échantillon
        régulier quand ils dépassent la borne.

        Écrit une fois pour le croisement deux à deux et pour le treillis : les
        deux doivent porter sur les mêmes profils, sans quoi le treillis
        recroiserait des terrains communs avec des profils que le premier
        croisement n'a jamais vus.
        """
        profils = self._profils_distincts(min_rights, allowed)
        if len(profils) > profils_max:
            pas = -(-len(profils) // max(1, profils_max))
            logger.info(
                "Croisement des profils restreint : %d profils sur %d, un sur "
                "%d", profils_max, len(profils), pas)
            profils = profils[::pas][:profils_max]
        return profils

    def _intersection_candidates(
        self, theta, min_users, min_rights, allowed, users_by_right, right_ptr,
        seen_rights, profils_max=PROFILS_CROISES_MAX
    ) -> List[Dict[str, np.ndarray]]:
        """Candidats formés du terrain commun à deux profils.

        C'est ce que les deux autres générateurs ne peuvent pas trouver : un
        rôle dont **aucun droit n'est caractéristique** de sa population. La
        clôture part d'un droit et ne voit que les rôles qu'un droit désigne ;
        les signatures ne voient que les profils exacts. Le terrain commun à
        deux populations n'est ni l'un ni l'autre.

        Ce que ça change, mesuré sur le référentiel de validation : à θ = 1 —
        donc **sans aucun sur-octroi** — la couverture passe de 79,91 % à
        95,16 % pour le même nombre de rôles que θ = 0,8 en produisait avec
        4 306 habilitations en trop. Le sur-octroi n'était pas le prix de la
        couverture : c'était le prix d'une génération trop pauvre, payé avec le
        seul levier disponible.

        Un candidat construit comme une intersection est un ensemble que ses
        deux profils détiennent entièrement. À θ = 1 ses membres sont exactement
        ses détenteurs, et il n'accorde donc rien à personne qui ne l'ait déjà.

        Le croisement est quadratique, et `profils_max` le borne. **Il
        restreint, il n'annule pas** — et c'est une correction, pas un réglage.

        Au-delà de la borne, le générateur abandonnait. Mesuré sur un
        référentiel de vingt et un mille identités : 11 534 profils distincts
        contre une borne livrée à 2 000. Il ne tournait donc jamais sur un
        référentiel réel, et les chiffres ci-dessus — obtenus sur un jeu de
        validation de quatre cents identités — décrivaient une capacité hors
        d'atteinte. Laissé tourner sur les vingt et un mille, il rend 711 rôles
        au lieu de 1 362, pour une couverture supérieure et toujours aucun
        sur-octroi.

        Abandonner était le mauvais réflexe : croiser une partie des profils
        trouve une partie des rôles, et zéro rôle n'est jamais le meilleur des
        deux. La borne dit donc **combien de profils on croise**.

        Lesquels ? Un **échantillon régulier**, et non les plus portés. C'est
        délibéré, et c'est un test qui l'a imposé : on aurait pu croire que les
        profils les plus portés forment les meilleurs rôles, mais le terrain
        commun de deux populations est justement porté par des profils que
        chacun ne partage avec personne — chaque membre y ajoute un droit qui
        n'est qu'à lui. Trier par porteurs écarte donc exactement les profils
        que ce générateur existe pour croiser.

        Aucun critère bon marché ne prédit qu'une paire produira un rôle : le
        nombre de membres du candidat ne dépend pas de qui portait les profils
        d'origine, il se recalcule. L'échantillon régulier est donc assumé comme
        **arbitraire** — c'est un contrôle de coût, pas une sélection éclairée —
        et l'appelant apprend que le croisement fut partiel, pour que personne
        ne lise la couverture obtenue comme celle d'un croisement complet.
        """
        profils = self._profils_croisables(min_rights, allowed, profils_max)
        if profils_max <= 0 or len(profils) < 2:
            return []

        # Les paires qui ne partagent aucun droit — l'immense majorité sur un
        # référentiel creux — ne produisent rien : leur intersection est vide.
        # Un index droit → profils compte, pour chaque profil, ce qu'il
        # partage avec chacun des suivants, et seules les paires qui atteignent
        # la taille minimale sont croisées. Mêmes candidats, dans le même
        # ordre : mesuré sur Amazon (9 298 identités, 3 droits en moyenne),
        # 23 millions de croisements tombaient à quelques dizaines de milliers.
        index: Dict[int, List[int]] = {}
        for rang, profil in enumerate(profils):
            for droit in profil.tolist():
                index.setdefault(droit, []).append(rang)
        voisins = {droit: np.asarray(rangs, dtype=np.int64)
                   for droit, rangs in index.items()}
        besoin = max(1, min_rights)
        partages = np.zeros(len(profils), dtype=np.int32)
        # L'intersection se lit dans un masque des droits du profil de gauche,
        # posé une fois par profil : le profil de droite est trié, son filtre
        # l'est aussi — le même résultat qu'`intersect1d`, sans le tri de la
        # concaténation à chaque paire.
        masque = np.zeros(self._n_rights, dtype=bool)

        candidats: List[Dict[str, np.ndarray]] = []
        for rang, gauche in enumerate(profils):
            partages[:] = 0
            for droit in gauche.tolist():
                partages[voisins[droit]] += 1
            suivants = np.flatnonzero(partages[rang + 1:] >= besoin) + rang + 1
            masque[gauche] = True
            for suivant in suivants.tolist():
                droite = profils[suivant]
                commun = droite[masque[droite]]
                cle = commun.tobytes()
                if cle in seen_rights:
                    continue
                seen_rights.add(cle)
                membres = self._expand_members(
                    commun, theta, np.zeros(self._n_users, dtype=np.int32),
                    users_by_right, right_ptr)
                if membres.size < min_users:
                    continue
                candidats.append({"rights": commun, "users": membres})
            masque[gauche] = False
        return candidats

    def _treillis_candidates(
        self, theta, min_users, min_rights, allowed, users_by_right, right_ptr,
        seen_rights, profils_max, budget
    ):
        """Le terrain commun à trois populations ou plus.

        Le croisement deux à deux rend l'intersection de deux profils. Le
        terrain commun à trois profils est l'intersection de cette
        intersection avec le troisième — et ainsi de suite. Le treillis
        recroise donc chaque ensemble nouveau avec tous les profils, jusqu'à ce
        qu'aucun ensemble nouveau n'apparaisse : c'est alors l'ensemble de
        toutes les intersections de profils, c'est-à-dire tous les ensembles
        de droits que leurs détenteurs sont seuls à partager.

        Pourquoi c'est utile, mesuré : sur Americas small, dix des rôles de la
        décomposition optimale publiée ne sont ni une clôture, ni un profil,
        ni l'intersection de deux profils. Sans eux, le meilleur choix parmi
        les candidats est de 179 rôles ; avec eux, 178 — l'optimum.

        Un ensemble ainsi formé est une intersection de profils : à θ = 1 ses
        membres sont exactement ses détenteurs, et il n'accorde rien à personne
        qui ne l'ait déjà.

        Le calcul d'un tour est vectorisé : l'ensemble de gauche est croisé
        avec **tous** les profils d'un coup par la matrice creuse droits ×
        profils, et chaque intersection reçoit une empreinte (deux sommes de
        poids aléatoires tirés d'une graine fixe) qui fait tomber les
        doublons sans les construire. Écrit profil par profil, il faisait 136
        millions de comparaisons redondantes sur Customer.

        L'exploration tient **son propre** registre des ensembles déjà
        recroisés, distinct de `seen_rights`. `seen_rights` dit ce qui est
        déjà un candidat — une clôture, une signature, un terrain commun de
        deux profils — et décide seulement si un ensemble est rendu. S'il
        décidait aussi de ce qu'on recroise, un terrain commun déjà trouvé par
        la clôture ne serait jamais recroisé, et les ensembles qu'on n'atteint
        qu'à travers lui manqueraient au treillis sans que rien ne le dise.

        Le premier tour part donc toujours des profils : il refait le
        croisement deux à deux, ce qui coûte, mais c'est la seule façon
        d'atteindre tout ce qu'on atteint par lui.

        Ce qu'un ensemble écarté faute de membres ou de droits ne fait pas
        perdre : tout ensemble plus petit auquel il mènerait s'atteint aussi
        par un autre ordre de croisement, dont chaque étape a au moins autant
        de détenteurs et de droits que lui. L'écarter ne retire donc rien.

        Args:
            budget: candidats ajoutés, au plus.

        Returns:
            (candidats, borne) — `borne` vaut vrai quand le budget est épuisé
            avant le point fixe.
        """
        from scipy.sparse import csr_matrix

        profils = self._profils_croisables(min_rights, allowed, profils_max)
        if budget <= 0 or profils_max <= 0 or len(profils) < 2:
            return [], False

        nombre = len(profils)
        effectifs = np.fromiter((p.size for p in profils), dtype=np.intp,
                                count=nombre)
        droits_par_profil = csr_matrix(
            (np.ones(int(effectifs.sum()), dtype=np.int32),
             (np.repeat(np.arange(nombre, dtype=np.intp), effectifs),
              np.concatenate(profils))),
            shape=(nombre, self._n_rights))
        profils_par_droit = droits_par_profil.T.tocsr()
        # Deux empreintes indépendantes de 64 bits : deux intersections
        # distinctes ne se confondent qu'avec une probabilité de l'ordre de
        # 2^-128. La graine est fixe — deux exécutions rendent le même modèle.
        tirage = np.random.default_rng(0)
        poids = tirage.integers(1, np.iinfo(np.int64).max,
                                size=(2, self._n_rights), dtype=np.int64
                                ).astype(np.uint64)
        besoin = max(1, min_rights)
        compteur = np.zeros(self._n_users, dtype=np.int32)

        explores = {profil.tobytes() for profil in profils}
        front = list(profils)
        candidats: List[Dict[str, np.ndarray]] = []
        while front:
            suivant: List[np.ndarray] = []
            for gauche in front:
                colonnes = profils_par_droit[gauche]
                partages = np.asarray(colonnes.sum(axis=0)).ravel()
                # Un profil qui contient tout `gauche` ne produit que `gauche`.
                cibles = np.flatnonzero((partages >= besoin)
                                        & (partages < gauche.size))
                if cibles.size == 0:
                    continue
                par_cible = colonnes[:, cibles].tocsc()
                cible_de = np.repeat(np.arange(cibles.size, dtype=np.intp),
                                     np.diff(par_cible.indptr))
                droit_de = gauche[par_cible.indices]
                empreintes = np.zeros((cibles.size, 2), dtype=np.uint64)
                np.add.at(empreintes[:, 0], cible_de, poids[0, droit_de])
                np.add.at(empreintes[:, 1], cible_de, poids[1, droit_de])
                _, premiers = np.unique(empreintes, axis=0, return_index=True)
                for rang in np.sort(premiers).tolist():
                    commun = np.sort(droit_de[
                        par_cible.indptr[rang]:par_cible.indptr[rang + 1]])
                    cle = commun.tobytes()
                    if cle in explores:
                        continue
                    explores.add(cle)
                    membres = self._expand_members(
                        commun, theta, compteur, users_by_right, right_ptr)
                    if membres.size < min_users:
                        continue
                    suivant.append(commun)
                    if cle in seen_rights:
                        # Déjà un candidat : recroisé, pas rendu deux fois.
                        continue
                    seen_rights.add(cle)
                    candidats.append({"rights": commun, "users": membres})
                    if len(candidats) >= budget:
                        logger.info("Treillis borné à %d candidats", budget)
                        return candidats, True
            front = suivant
        return candidats, False

    def _signature_candidates(
        self, theta, min_users, min_rights, allowed, users_by_right, right_ptr, seen_rights
    ) -> List[Dict[str, np.ndarray]]:
        """Candidats amorcés par les signatures de droits des utilisateurs.

        La clôture par droit peut manquer un ensemble de droits que plusieurs
        utilisateurs détiennent exactement, sans qu'aucun de ces droits ne soit
        propre au groupe. Ces signatures sont précisément ce que trouve le
        mining exact : les ajouter garantit que le mode approché ne restitue
        jamais moins que le mode exact.
        """
        user_counter = np.zeros(self._n_users, dtype=np.int32)
        groups: Dict[bytes, np.ndarray] = {}

        for user in range(self._n_users):
            user_rights = self._rights_of(user)
            kept = user_rights[allowed[user_rights]]
            if kept.size < min_rights:
                continue
            groups.setdefault(np.sort(kept).tobytes(), kept)

        candidates: List[Dict[str, np.ndarray]] = []
        for key, rights in groups.items():
            if key in seen_rights:
                continue
            closure = np.sort(rights)
            members = self._expand_members(
                closure, theta, user_counter, users_by_right, right_ptr
            )
            if members.size < min_users:
                continue
            seen_rights.add(key)
            candidates.append({"rights": closure, "users": members})

        return candidates

    def _expand_members(self, closure, theta, user_counter, users_by_right, right_ptr) -> np.ndarray:
        """Membres du rôle : identités détenant au moins θ·|R| de ses droits.

        `np.flatnonzero` parcourt tout l'effectif à chaque appel, ce qui semble
        gaspilleur : le coût d'un rôle de trois droits dépend alors du nombre
        total d'identités, y compris celles qui n'en détiennent aucune.

        Une version restreignant la recherche aux seuls membres possibles a été
        écrite et mesurée — un membre détenant `required` droits sur `|R|` doit
        figurer dans l'union des `|R| - required + 1` listes de porteurs les
        plus courtes. Elle s'est révélée **plus lente** : 0,44 s contre 0,33 s
        sur 5 000 identités, 1,75 s contre 1,40 s sur 20 000. Le tri, la
        concaténation et la déduplication coûtent davantage que le balayage
        vectorisé qu'ils évitent.

        Le vrai coût est ailleurs : ce sont les droits détenus par la
        quasi-totalité de la population — un `+= 1` par identité, par candidat.
        Les exclure avant le mining, ce que fait la détection des droits
        socles, divise le temps total par sept. Voir `docs/04-validation.md`.
        """
        touched: List[np.ndarray] = []
        for right in closure:
            holders = users_by_right[right_ptr[right]:right_ptr[right + 1]]
            user_counter[holders] += 1
            touched.append(holders)

        required = porteurs_requis(theta, closure.size)
        members = np.flatnonzero(user_counter >= required)

        for holders in touched:
            user_counter[holders] = 0

        return members

    def _positions_acquises(self, roles_valides,
                            allowed: np.ndarray) -> Optional[np.ndarray]:
        """Positions, dans la matrice, des habilitations qu'explique le catalogue.

        Un rôle applicatif est défini par ses droits : en relèvent les identités
        qui les détiennent **tous**. Les couples qu'il explique sont donc des
        habilitations réelles, et chacun a sa position dans la matrice creuse —
        c'est ce qui permet de les marquer couverts sans rien recalculer.
        """
        if not roles_valides:
            return None

        acquis = np.zeros(self._indices.size, dtype=bool)
        marque = False
        for role in roles_valides:
            codes = [self.loader.right_encoder[droit]
                     for droit in (role.get("rights") or ())
                     if droit in self.loader.right_encoder]
            if not codes:
                continue
            appartient = np.zeros(self._n_rights, dtype=bool)
            appartient[codes] = True
            for utilisateur in range(self._n_users):
                debut, fin = self._indptr[utilisateur], self._indptr[utilisateur + 1]
                detenus = appartient[self._indices[debut:fin]]
                # Le rôle ne relève de cette identité que si elle détient
                # **tous** ses droits. Sinon elle ne le porte pas, et il
                # n'explique rien chez elle.
                if int(np.count_nonzero(detenus)) != len(codes):
                    continue
                # Marqué sur les seuls droits **autorisés**. Le dénominateur du
                # taux de couverture les exclut ; compter au numérateur des
                # positions qu'il ne compte pas rendait un taux au-dessus de
                # cent — c'est-à-dire un modèle qui explique plus
                # d'habilitations qu'il n'en existe.
                acquis[debut:fin] |= detenus & allowed[self._indices[debut:fin]]
                marque = True
        return acquis if marque else None

    # ------------------------------------------------------- couverture greedy

    def _greedy_cover(self, candidates, max_roles, allowed, theta,
                      acquis=None, apport_minimal: int = 1) -> Dict[str, Any]:
        """Sélection gloutonne paresseuse maximisant les habilitations couvertes.

        Le gain d'un candidat ne peut que décroître quand d'autres rôles sont
        retenus : on peut donc réévaluer un candidat uniquement lorsqu'il
        remonte en tête du tas (lazy greedy). Le résultat est identique à un
        glouton naïf, pour un coût très inférieur.
        """
        # Position de chaque couple (utilisateur, droit) dans la matrice, pour
        # marquer ce qui est déjà couvert. Le catalogue validé est marqué
        # d'emblée : un candidat qu'un rôle déjà validé explique entièrement
        # n'apporte rien, et passait pourtant devant un candidat qui apportait.
        covered = (np.zeros(self._indices.size, dtype=bool)
                   if acquis is None else acquis.copy())
        total_assignments = int(np.count_nonzero(allowed[self._indices]))

        def gain_and_slots(candidate):
            """Habilitations réelles non encore couvertes, et sur-octroi induit."""
            rights = candidate["rights"]
            rights_set = np.zeros(self._n_rights, dtype=bool)
            rights_set[rights] = True

            slots: List[int] = []
            over = 0
            for user in candidate["users"]:
                start, end = self._indptr[user], self._indptr[user + 1]
                user_rights = self._indices[start:end]
                held = rights_set[user_rights]
                held_count = int(np.count_nonzero(held))
                over += rights.size - held_count
                positions = np.flatnonzero(held) + start
                slots.extend(int(p) for p in positions if not covered[p])
            return len(slots), slots, over

        heap: List[tuple] = []
        for index, candidate in enumerate(candidates):
            # Borne supérieure initiale : toutes les habilitations du rôle.
            upper = candidate["users"].size * candidate["rights"].size
            heap.append((-upper, index, -1))
        heapq.heapify(heap)

        chosen: List[Dict[str, Any]] = []
        retenus: List[int] = []
        total_over = 0
        rank = 0
        #: Candidats écartés parce qu'ils n'expliquaient pas assez. Comptés,
        #: parce qu'un modèle de cent trente-sept rôles là où le moteur en a
        #: trouvé trois cent quatre-vingt-dix se lirait autrement comme un
        #: référentiel qui ne porte que cela.
        sous_apport = 0

        #: Le plancher d'apport. Un candidat qui n'atteint pas ce nombre
        #: d'habilitations non encore couvertes n'est pas retenu — et il est
        #: écarté **définitivement**, non repoussé : le gain d'un candidat ne
        #: peut que décroître à mesure que d'autres rôles sont pris, donc ce
        #: qui est sous le plancher maintenant y restera.
        plancher = max(1, int(apport_minimal))

        while heap and len(chosen) < max_roles:
            neg_bound, index, stamp = heapq.heappop(heap)
            candidate = candidates[index]
            gain, slots, over = gain_and_slots(candidate)

            if gain <= 0:
                continue
            if gain < plancher:
                sous_apport += 1
                continue

            # Le gain recalculé est-il toujours le meilleur du tas ?
            if heap and -gain > heap[0][0] and stamp != rank:
                heapq.heappush(heap, (-gain, index, rank))
                continue

            covered[slots] = True
            total_over += over
            rank += 1
            retenus.append(index)
            chosen.append(self._materialise(candidate, gain, over, rank))

        covered_count = int(np.count_nonzero(covered))
        # Le plafond a-t-il arrêté la sélection alors qu'il restait des
        # candidats ? Un modèle coupé présenté comme complet fait décider sur
        # un catalogue qui n'est pas celui que le moteur a trouvé.
        tronquee = len(chosen) >= max_roles and bool(heap)

        users_covered = set()
        rights_covered = set()
        for role in chosen:
            users_covered.update(role["users"])
            rights_covered.update(role["rights"])

        return {
            "roles": chosen,
            # Ce dont la sélection exacte repart : les candidats retenus, et ce
            # qu'ils expliquent. Retirés avant que le résultat ne sorte.
            "_retenus": retenus,
            "_couvert": covered,
            "stats": {
                "total_assignments": total_assignments,
                "covered_assignments": covered_count,
                "coverage_pct": round(100.0 * covered_count / total_assignments, 2) if total_assignments else 0.0,
                "over_granted": total_over,
                # Rapporté aux **mêmes** habilitations que la couverture, et
                # non à la somme de ce que les rôles retenus accordent. Ce
                # dénominateur-là grandissait avec le nombre de rôles : deux
                # modèles n'étaient pas comparables sur ce taux, ce dont le
                # front de Pareto des seuils dépend pourtant entièrement.
                "over_granted_pct": (round(100.0 * total_over / total_assignments, 2)
                                     if total_assignments else 0.0),
                "tronquee": tronquee,
                # Ce que le modèle **n'explique pas**. Le nombre existait par
                # soustraction ; le rendre le rend disable : « 148 rôles
                # expliquent 95,16 % de vos habilitations, les 1 032 restantes
                # sont celles-ci ». Sans lui, la phrase s'arrête à un
                # pourcentage, et un pourcentage ne se traite pas.
                "assignments_uncovered": total_assignments - covered_count,
                "users_covered": len(users_covered),
                "rights_covered": len(rights_covered),
                "candidates_generated": len(candidates),
                # Candidats écartés faute d'apport suffisant. Jamais en
                # silence : sans ce compte, un modèle réduit par le plancher
                # se lit comme un référentiel qui ne porte que cela.
                "candidats_sous_apport": sous_apport,
                "similarity_threshold": theta,
            },
        }

    @staticmethod
    def _compte_rendu_de_selection(selection, glouton=None, arret=None,
                                   borne=None, optimale=False):
        """Ce que la sélection a fait, dans le même vocabulaire quel qu'il soit.

        `roles_glouton` est le nombre de rôles que le glouton avait retenus :
        c'est ce qui permet d'écrire « 398 rôles au lieu de 564 », et de le
        vérifier. `borne` est le minimum que le solveur a **prouvé** : aucun
        choix parmi ces candidats ne descend en dessous.
        """
        return {
            "selection": selection,
            "selection_roles_glouton": glouton,
            "selection_arret": arret,
            "selection_borne": borne,
            "selection_optimale": optimale,
        }

    def _reselectionner(self, selection, rendu, candidates, allowed, theta,
                        acquis, apport_minimal, effort, delai_s) -> Dict[str, Any]:
        """Remplace le choix du glouton par un choix plus court qui explique autant.

        `elaguee` retire les rôles du glouton que les autres rendent inutiles ;
        `exacte` cherche, dans tout le vivier, le plus petit ensemble qui
        explique la même chose. Les rôles retenus sont ensuite **reclassés par
        le glouton lui-même** : le rang, l'apport de chacun et la courbe des
        apports gardent leur sens — « ce que ce rôle ajoute à ceux qui le
        précèdent ».
        """
        glouton = len(rendu["roles"])
        a_couvrir = rendu["_couvert"].copy()
        if acquis is not None:
            a_couvrir &= ~acquis

        if theta < 1.0:
            # Sous θ = 1 un candidat accorde des droits non détenus : le plus
            # petit ensemble serait choisi au prix du sur-octroi. Le glouton
            # est gardé, et le compte rendu dit pourquoi.
            choix = {"retenus": None, "arret": ARRET_NON_APPLICABLE,
                     "borne": None, "optimale": False}
        else:
            choix = selectionner(
                candidates, self._indptr, self._indices, self._n_rights,
                a_couvrir, glouton, effort, delai_s)

        if choix["retenus"] is not None:
            sous_ensemble = [candidates[rang] for rang in choix["retenus"]]
            reclasse = self._greedy_cover(sous_ensemble, glouton, allowed,
                                          theta, acquis, 1)
            # Le plancher d'apport est un choix de l'utilisateur. Reclassés,
            # des rôles peuvent apporter moins que lui : garder alors le
            # glouton, plutôt que de rendre un modèle qui enfreint le réglage.
            if all(role["new_assignments_covered"] >= apport_minimal
                   for role in reclasse["roles"]):
                for cle in ("candidates_generated", "candidats_sous_apport",
                            "tronquee"):
                    reclasse["stats"][cle] = rendu["stats"][cle]
                rendu = reclasse
            else:
                choix = {**choix, "arret": ARRET_PLANCHER}

        rendu["stats"].update(self._compte_rendu_de_selection(
            selection, glouton, choix["arret"], choix["borne"],
            choix["optimale"]))
        return rendu

    def _materialise(self, candidate, gain, over, rank) -> Dict[str, Any]:
        """Traduit un candidat (indices) en rôle exploitable par l'API."""
        rights = [self._right_decoder[i] for i in candidate["rights"]]
        users = [self._user_decoder[i] for i in candidate["users"]]
        granted = len(users) * len(rights)

        return {
            # Nom technique et stable : le libellé lisible est de la
            # responsabilité du client, via les clés i18n ci-dessous.
            "name": f"APPROX_ROLE_{rank:03d}",
            "description_key": "mining.role.approx_description",
            "description_params": {"rights": len(rights), "users": len(users)},
            "role_type": "APPLICATIF",
            "mining_mode": "APPROX",
            "rights": rights,
            "users": users,
            "user_count": len(users),
            "right_count": len(rights),
            # Part des habilitations du rôle réellement détenues aujourd'hui.
            "fit_pct": round(100.0 * (granted - over) / granted, 2) if granted else 0.0,
            "over_granted": over,
            "over_granted_pct": round(100.0 * over / granted, 2) if granted else 0.0,
            # Habilitations existantes que ce rôle couvre et qu'aucun rôle
            # retenu avant lui ne couvrait.
            "new_assignments_covered": gain,
            "score": gain,
        }
