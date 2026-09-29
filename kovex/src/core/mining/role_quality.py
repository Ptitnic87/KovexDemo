# src/core/mining/role_quality.py
"""Qualité, consolidation et hiérarchie d'un ensemble de rôles candidats.

Un moteur de mining rend des rôles ; il ne dit pas s'ils forment un *bon*
modèle. La mesure de justesse l'a montré : sur un référentiel bruité, une part
des rôles restitués sont des variantes proches les unes des autres, et la
précision de l'ensemble tombe alors que celle des premiers rôles reste élevée.

Ce module travaille sur le résultat du mining, quel que soit le moteur, et
répond à trois questions distinctes :

1. **Que vaut ce modèle ?** Compression, redondance, part des habilitations
   laissée sans explication. Calculé toujours, sans rien modifier.
2. **Peut-on le simplifier ?** Fusion des rôles quasi identiques, au seuil de
   similarité fourni par l'appelant. Jamais appliqué sans ce seuil.
3. **Comment s'emboîtent-ils ?** Un rôle dont les droits sont inclus dans ceux
   d'un autre en est un sous-rôle. C'est ce qui renseigne `sub_roles`, que le
   mining laissait vide.

Toutes les mesures portent sur les couples (identité, droit) réellement
couverts. Les ensembles de droits sont représentés par des entiers utilisés
comme masques de bits : sur 18 000 identités et 8 000 droits, une couverture
complète tient en quelques dizaines de mégaoctets, là où un ensemble de couples
en occuperait plusieurs centaines.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Set

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------- outils


def _jaccard(gauche: frozenset, droite: frozenset) -> float:
    """Indice de Jaccard entre deux ensembles de droits. 1,0 = identiques.

    Deux ensembles vides donnent 0,0 et non la valeur conventionnelle 1,0 :
    ici, un rôle sans droit n'est parent de rien, et l'appelant l'écarte de
    toute façon avant la comparaison.
    """
    union = len(gauche | droite)
    return len(gauche & droite) / union if union else 0.0


def _index_des_droits(roles: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """Associe un rang à chaque droit rencontré, pour l'encodage en masque."""
    index: Dict[str, int] = {}
    for role in roles:
        for droit in role.get("rights") or ():
            if droit not in index:
                index[droit] = len(index)
    return index


def _masque(droits: Sequence[str], index: Dict[str, int]) -> int:
    masque = 0
    for droit in droits:
        rang = index.get(droit)
        if rang is not None:
            masque |= 1 << rang
    return masque


def _popcount(valeur: int) -> int:
    """Nombre de bits à 1, soit le nombre de droits d'un masque.

    `int.bit_count()` existe depuis Python 3.10 ; le produit exige 3.11.
    """
    return valeur.bit_count()


# ------------------------------------------------------------------- qualité


def mesurer(
    roles: Sequence[Dict[str, Any]],
    total_assignments: int,
    droits_reels: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Mesure ce que vaut un ensemble de rôles, sans le modifier.

    Args:
        roles: rôles candidats, dans l'ordre où ils seront proposés. L'ordre
            compte : la redondance d'un rôle est mesurée par rapport à ceux qui
            le précèdent.
        total_assignments: nombre d'habilitations réelles du périmètre.
        droits_reels: droits réellement détenus par identité. Fourni, il rend
            la couverture et le sur-octroi **exacts**, y compris après une
            consolidation qui a rendu caduques les chiffres du moteur. Absent,
            la couverture n'est renseignée que si aucun rôle n'octroie de droit
            en trop — auquel cas les couples accordés sont exactement les
            habilitations couvertes. Sinon elle vaut ``None`` : mieux vaut ne
            rien afficher qu'un chiffre approché présenté comme exact.

    Returns:
        {"roles": [...enrichis...], "metrics": {...}}

        Par rôle, deux mesures ajoutées :
            redundant_pairs : couples (identité, droit) du rôle déjà couverts
                par un rôle précédent.
            redundancy_pct : leur part dans le rôle. À 100 %, le rôle n'apporte
                rien qu'un autre n'apportait déjà.

        Globalement :
            granted_pairs : couples (identité, droit) distincts que le modèle
                accorde, sur-octroi compris.
            covered_assignments : habilitations réelles expliquées, ou ``None``.
            coverage_pct : leur part du total, ou ``None``.
            uncovered_assignments : la sous-affectation — ce que le modèle
                n'explique pas et qui restera en attribution individuelle.
            over_granted : couples que le modèle accorderait sans qu'ils
                existent aujourd'hui, ou ``None``.
            over_granted_pct : leur part des habilitations **existantes**, donc
                le même dénominateur que la couverture. « Ce modèle reprend
                39 % de l'existant et en créerait 7 % de plus » se lit ; une
                couverture dédupliquée à côté d'un sur-octroi additionné rôle
                par rôle ne se lit pas.
            total_assignments : le dénominateur, rendu pour qu'un pourcentage
                affiché reste interprétable.
            rbac_assignments : nombre de liens du modèle RBAC, soit les liens
                identité→rôle plus les liens rôle→droit.
            compression_ratio : couples accordés rapportés à ces liens. À 3,0,
                un lien du modèle en accorde trois ; en dessous de 1,0, le
                modèle coûte plus de liens qu'il n'accorde d'habilitations.
            wsc : complexité structurelle, soit le nombre de rôles augmenté du
                nombre de liens. Plus il est bas, plus le modèle est simple.
            redundant_pairs : couples couverts plusieurs fois, tous rôles
                confondus.
    """
    index = _index_des_droits(roles)
    couverture: Dict[str, int] = {}

    enrichis: List[Dict[str, Any]] = []
    total_paires = 0
    total_redondantes = 0
    liens_identite_role = 0
    liens_role_droit = 0

    for role in roles:
        droits = role.get("rights") or []
        membres = role.get("users") or []
        masque_role = _masque(droits, index)
        paires_role = len(membres) * len(droits)
        redondantes = 0

        for membre in membres:
            deja = couverture.get(membre, 0)
            redondantes += _popcount(deja & masque_role)
            couverture[membre] = deja | masque_role

        total_paires += paires_role
        total_redondantes += redondantes
        liens_identite_role += len(membres)
        liens_role_droit += len(droits)

        enrichi = dict(role)
        enrichi["redundant_pairs"] = redondantes
        enrichi["redundancy_pct"] = (
            round(100.0 * redondantes / paires_role, 2) if paires_role else 0.0
        )
        enrichis.append(enrichi)

    accordees = sum(_popcount(masque) for masque in couverture.values())

    if droits_reels is not None:
        couvertes = 0
        for identite, masque in couverture.items():
            masque_reel = _masque(droits_reels.get(identite) or (), index)
            couvertes += _popcount(masque & masque_reel)
        sur_octroi = accordees - couvertes
    elif all(role.get("over_granted", 0) == 0 for role in roles):
        couvertes, sur_octroi = accordees, 0
    else:
        couvertes, sur_octroi = None, None

    liens = liens_identite_role + liens_role_droit

    return {
        "roles": enrichis,
        "metrics": {
            "roles_count": len(enrichis),
            "granted_pairs": accordees,
            "covered_assignments": couvertes,
            "coverage_pct": (
                round(100.0 * couvertes / total_assignments, 2)
                if couvertes is not None and total_assignments else None
            ),
            "uncovered_assignments": (
                max(0, total_assignments - couvertes) if couvertes is not None else None
            ),
            "over_granted": sur_octroi,
            # Rapporté aux habilitations **existantes**, comme la couverture.
            # Les deux chiffres se lisent alors dans le même espace : « ce
            # modèle reprend 39 % de l'existant et en créerait 7 % de plus ».
            # L'écran métier affichait jusqu'ici une couverture dédupliquée à
            # côté d'un sur-octroi additionné rôle par rôle, rapporté à ce que
            # le modèle accorde : deux dénominateurs différents, présentés
            # comme comparables. Sur un référentiel réel, l'écart entre la
            # somme et l'union dépassait 25 %.
            "over_granted_pct": (
                round(100.0 * sur_octroi / total_assignments, 2)
                if sur_octroi is not None and total_assignments else None
            ),
            "total_assignments": total_assignments,
            "user_role_links": liens_identite_role,
            "role_right_links": liens_role_droit,
            "rbac_assignments": liens,
            "compression_ratio": round(accordees / liens, 2) if liens else 0.0,
            "wsc": len(enrichis) + liens,
            "redundant_pairs": total_redondantes,
            "redundancy_pct": (
                round(100.0 * total_redondantes / total_paires, 2) if total_paires else 0.0
            ),
        },
    }


# -------------------------------------------------------------- consolidation


def consolider(
    roles: Sequence[Dict[str, Any]],
    seuil_similarite: float,
) -> Dict[str, Any]:
    """Retire les rôles quasi identiques à un rôle mieux classé.

    Deux rôles forment une même famille lorsque l'indice de Jaccard de leurs
    droits atteint le seuil ; la relation est propagée par transitivité. De
    chaque famille, **un seul rôle survit : le mieux classé**, c'est-à-dire
    celui que la couverture gloutonne a jugé le plus utile. Les autres sont
    absorbés, et le rôle survivant garde la trace de ce qu'il a absorbé.

    Aucun rôle n'est modifié : un rôle conservé est exactement celui que le
    moteur a produit. C'est ce qui distingue cette consolidation d'une fusion.

    **Pourquoi pas une fusion.** Une fusion — intersection des droits, union
    des membres — a été implémentée puis mesurée sur un référentiel dont les
    rôles étaient connus à l'avance. Elle améliore la compression mais détruit
    les rôles : à seuil 0,8, le nombre de rôles retrouvés à l'identique tombe
    de 12 sur 15 à 4, et le rappel de 0,97 à 0,88. L'absorption, aux mêmes
    seuils, laisse rappel et rôles exacts **inchangés** tout en divisant la
    complexité structurelle par deux. La fusion a donc été abandonnée sur
    mesure, pas sur principe.

    Le choix du survivant a lui aussi été mesuré. Retenir le rôle portant le
    plus de droits, ou le plus de membres, dégrade le rappel (0,87 et 0,90
    contre 0,97) : c'est le classement du moteur qui porte l'information, pas
    la taille du rôle.

    Args:
        seuil_similarite: dans ]0, 1]. À 1,0, seuls des rôles portant
            exactement les mêmes droits sont réunis.

    Returns:
        {"roles": [...], "stats": {...}}

        Le rôle survivant reçoit ``absorbs`` : les noms des rôles qu'il
        remplace. Les statistiques comptent les couples (identité, droit) que
        le modèle n'accorde plus, seul coût réel de l'opération.
    """
    if not 0.0 < seuil_similarite <= 1.0:
        raise ValueError("seuil_similarite doit appartenir à ]0, 1]")

    vide = {
        "roles_before": len(roles), "roles_after": len(roles), "families": 0,
        "roles_absorbed": 0, "granted_pairs_before": 0, "granted_pairs_after": 0,
        "granted_pairs_lost": 0,
    }
    if len(roles) < 2:
        return {"roles": [dict(role) for role in roles], "stats": vide}

    ensembles = [frozenset(role.get("rights") or ()) for role in roles]
    ordre = sorted(range(len(roles)), key=lambda rang: len(ensembles[rang]))

    parent = list(range(len(roles)))

    def racine(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    # Deux ensembles ne peuvent atteindre le seuil que si le rapport de leurs
    # tailles l'atteint déjà : |A∩B| ≤ min, |A∪B| ≥ max. On parcourt donc les
    # rôles par taille croissante et on arrête dès que la taille de l'autre
    # rend le seuil inatteignable. Sans cette borne, le coût est quadratique
    # sur le nombre de rôles demandé, qui peut monter à plusieurs milliers.
    for position, gauche in enumerate(ordre):
        taille_gauche = len(ensembles[gauche])
        if taille_gauche == 0:
            continue
        for droite in ordre[position + 1:]:
            taille_droite = len(ensembles[droite])
            if taille_gauche < seuil_similarite * taille_droite:
                break
            if _jaccard(ensembles[gauche], ensembles[droite]) >= seuil_similarite:
                a, b = racine(gauche), racine(droite)
                if a != b:
                    parent[b] = a

    familles: Dict[int, List[int]] = {}
    for index in range(len(roles)):
        familles.setdefault(racine(index), []).append(index)

    survivants: List[int] = []
    absorptions: Dict[int, List[str]] = {}
    for membres in familles.values():
        porteur = min(membres)
        survivants.append(porteur)
        if len(membres) > 1:
            absorptions[porteur] = [
                roles[index].get("name") for index in sorted(membres) if index != porteur
            ]

    survivants.sort()
    conserves: List[Dict[str, Any]] = []
    for index in survivants:
        role = dict(roles[index])
        if index in absorptions:
            role["absorbs"] = absorptions[index]
        conserves.append(role)

    avant = _couples_accordes(roles)
    apres = _couples_accordes(conserves)

    logger.info(
        "Consolidation au seuil %.2f : %d rôles -> %d, %d absorbés, "
        "%d couples accordés en moins",
        seuil_similarite, len(roles), len(conserves),
        len(roles) - len(conserves), avant - apres,
    )

    return {
        "roles": conserves,
        "stats": {
            "roles_before": len(roles),
            "roles_after": len(conserves),
            "families": sum(1 for membres in familles.values() if len(membres) > 1),
            "roles_absorbed": len(roles) - len(conserves),
            "granted_pairs_before": avant,
            "granted_pairs_after": apres,
            "granted_pairs_lost": avant - apres,
        },
    }


def _couples_accordes(roles: Sequence[Dict[str, Any]]) -> int:
    """Nombre de couples (identité, droit) distincts accordés par un modèle."""
    index = _index_des_droits(roles)
    couverture: Dict[str, int] = {}
    for role in roles:
        masque = _masque(role.get("rights") or (), index)
        for membre in role.get("users") or ():
            couverture[membre] = couverture.get(membre, 0) | masque
    return sum(_popcount(masque) for masque in couverture.values())


# ----------------------------------------------------------------- hiérarchie


def hierarchiser(roles: Sequence[Dict[str, Any]],
                 catalogue: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """Déduit la hiérarchie des rôles de l'inclusion de leurs droits.

    Un rôle dont les droits sont **strictement inclus** dans ceux d'un autre en
    est un sous-rôle. Seuls les liens directs sont conservés : si A ⊂ B ⊂ C, le
    lien A ⊂ C est omis, sans quoi la hiérarchie serait illisible sur un
    référentiel réel.

    Deux rôles portant exactement les mêmes droits ne sont pas hiérarchisés :
    c'est un doublon, pas une inclusion, et cela relève de la consolidation.

    `catalogue` — les rôles **déjà validés** — participe à la relation sans
    être rendu. C'est ce qui manquait : la hiérarchie ne se calculait qu'entre
    les candidats d'une même exécution, si bien qu'un candidat contenant un
    rôle validé recopiait ses droits à plat au lieu de le composer. L'IGA du
    client recevait alors deux fois le même ensemble, sans lien entre eux, et
    la moindre évolution du rôle validé cessait de se propager.

    Chaque rôle reçoit :
        sub_roles : identifiants des rôles candidats directement inclus.
        parent_roles : identifiants des candidats qui l'incluent directement.
        sub_roles_valides : identifiants des rôles **du catalogue** que ce
            candidat contient. Ils ne sont pas soumis à la règle des liens
            directs : un candidat doit connaître tout ce qu'il compose déjà,
            même par l'intermédiaire d'un autre candidat qu'on ne validera
            peut-être pas.

    La hiérarchie **encaisse** aussi : `wsc_hierarchique` compte le modèle tel
    qu'une IGA le porterait avec l'héritage. Un rôle ne porte plus que ses
    droits propres — ceux qu'aucun de ses sous-rôles ne lui donne —, un
    porteur n'est rattaché qu'au rôle le plus large qu'il porte, et chaque
    lien d'héritage compte pour un. C'est la complexité structurelle (WSC) au
    sens de la littérature (Molloy et al., 2008), là où `mesurer` rend celle du
    modèle à plat. Mesuré sur les jeux HP : le glouton hiérarchisé descend à
    1 793 sur Firewall-1, contre 5 204 à plat et 1 795 pour la meilleure des
    décompositions de référence.

    Returns:
        {"roles": [...], "stats": {"links": int, "roots": int, "max_depth": int,
                                   "wsc_hierarchique": int}}
    """
    enrichis = [dict(role) for role in roles]
    ensembles = [frozenset(role.get("rights") or ()) for role in enrichis]
    identifiants = [
        role.get("id") or role.get("name") or str(rang)
        for rang, role in enumerate(enrichis)
    ]

    # Ancêtres : tous les rôles qui incluent strictement le rôle courant.
    ancetres: List[Set[int]] = [set() for _ in enrichis]
    for enfant in range(len(enrichis)):
        for parent in range(len(enrichis)):
            if enfant == parent:
                continue
            if ensembles[enfant] < ensembles[parent]:
                ancetres[enfant].add(parent)

    liens = 0
    parents_directs: List[Set[int]] = [set() for _ in enrichis]
    for enfant, candidats in enumerate(ancetres):
        for parent in candidats:
            # Un parent est direct si aucun autre ancêtre ne s'intercale.
            if any(
                intermediaire != parent and ensembles[intermediaire] < ensembles[parent]
                for intermediaire in candidats
            ):
                continue
            parents_directs[enfant].add(parent)
            liens += 1

    enfants_directs: List[List[int]] = [[] for _ in enrichis]
    for enfant, parents in enumerate(parents_directs):
        for parent in parents:
            enfants_directs[parent].append(enfant)

    # Ce que chaque candidat compose déjà du catalogue. Calculé à part : la
    # règle des liens directs vaut entre candidats, pas ici — un candidat doit
    # connaître tout ce qu'il contient de validé, y compris ce qu'un autre
    # candidat contient aussi et qu'on ne validera peut-être jamais.
    valides = [(str(role.get("id") or role.get("name") or ""),
                frozenset(str(droit) for droit in (role.get("rights") or ())),
                str(role.get("name") or ""))
               for role in catalogue]
    valides = [entree for entree in valides if entree[1]]

    for rang, role in enumerate(enrichis):
        role["sub_roles"] = [identifiants[enfant] for enfant in sorted(enfants_directs[rang])]
        role["parent_roles"] = [identifiants[parent] for parent in sorted(parents_directs[rang])]
        composes = [(identifiant, nom) for identifiant, droits, nom in valides
                    if droits < ensembles[rang]]
        role["sub_roles_valides"] = [identifiant for identifiant, _ in composes]
        role["sub_roles_valides_names"] = [nom for _, nom in composes]

    profondeurs: Dict[int, int] = {}

    def profondeur(rang: int) -> int:
        if rang in profondeurs:
            return profondeurs[rang]
        # Pas de cycle possible : l'inclusion stricte est un ordre partiel.
        profondeurs[rang] = (
            1 + max((profondeur(parent) for parent in parents_directs[rang]), default=0)
        )
        return profondeurs[rang]

    # Le modèle tel qu'une IGA le porterait avec l'héritage : droits propres,
    # porteurs rattachés au seul rôle le plus large, liens d'héritage.
    membres = [frozenset(role.get("users") or ()) for role in enrichis]
    droits_propres = 0
    porteurs_directs = 0
    for rang in range(len(enrichis)):
        herites = frozenset().union(*(ensembles[enfant] for enfant in enfants_directs[rang]))
        droits_propres += len(ensembles[rang] - herites)
        par_un_parent = frozenset().union(*(membres[parent] for parent in parents_directs[rang]))
        porteurs_directs += len(membres[rang] - par_un_parent)

    return {
        "roles": enrichis,
        "stats": {
            "links": liens,
            "roots": sum(1 for parents in parents_directs if not parents),
            "max_depth": max((profondeur(rang) for rang in range(len(enrichis))), default=0),
            "wsc_hierarchique": len(enrichis) + droits_propres + porteurs_directs + liens,
            "droits_propres": droits_propres,
            "porteurs_directs": porteurs_directs,
        },
    }
