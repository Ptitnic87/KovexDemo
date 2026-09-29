# Fichier : src/core/knowledge/socle.py
"""Le socle, vu comme ce qu'il est : un rôle.

Les droits socles sont détenus par la quasi-totalité de la population — badge,
messagerie, intranet. Le produit savait les détecter, les enregistrer et les
retirer du mining, mais ils n'existaient nulle part ensuite : ni dans le
catalogue des rôles, ni dans l'export du modèle. L'intégrateur recevait donc un
modèle **incomplet** — tous les rôles métiers et applicatifs, et pas la seule
chose que tout le monde reçoit à l'arrivée.

C'est pourtant un rôle, et le plus simple de tous : une population — les
identités analysées — et un jeu de droits. Le nommer autrement ne change rien à
ce qu'un IGA en fera.

**Il est dérivé, jamais stocké.** Le socle se recalcule à chaque lecture depuis
la décision de détection et le périmètre du jour, comme le travail en attente
se déduit des candidats et des décisions. L'enregistrer comme un rôle validé
créerait un second état à tenir à jour : relancer une détection, restreindre le
périmètre ou effacer les droits socles laisserait derrière un rôle qui ne
correspond plus à rien, et personne ne saurait lequel des deux dit vrai.

Ce qu'il n'est pas : un rôle qu'on renomme au fil de l'eau, qu'on versionne ou
qu'on sort du catalogue. On le change en changeant la décision qui le produit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set

#: Identifiant du rôle socle. Réservé : la validation d'un rôle le refuse, pour
#: qu'un rôle du client ne puisse pas venir le recouvrir dans le catalogue, ni
#: dans l'export.
IDENTIFIANT_SOCLE = "__socle__"

#: Type de rôle du socle. Il n'est ni métier ni applicatif : il ne décrit pas
#: un métier, et il traverse toutes les applications.
TYPE_SOCLE = "SOCLE"


@dataclass(frozen=True)
class Socle:
    """La décision de détection, telle qu'elle est enregistrée."""

    droits: List[str]
    seuil: float
    detecte_le: str
    #: Nom choisi par l'utilisateur. Vide tant qu'il n'en a pas choisi : le
    #: produit n'en invente pas un, il affiche un libellé traduit à la place.
    nom: str = ""

    @property
    def existe(self) -> bool:
        return bool(self.droits)


def socle_du_workspace(kb) -> Socle:
    """Lit la décision de détection, sans la juger."""
    info = kb.get_birth_rights_info() or {}
    return Socle(
        droits=sorted(str(droit) for droit in (info.get("rights") or ())),
        seuil=float(info.get("threshold") or 0.0),
        detecte_le=str(info.get("detected_at") or ""),
        nom=str(info.get("name") or "").strip(),
    )


def population(identites: Iterable[Mapping[str, Any]], colonne_identifiant: str,
               hors_perimetre: Optional[Set[str]] = None) -> List[str]:
    """Qui porte le socle : **toutes** les identités analysées.

    C'est ce qui distingue le socle des autres rôles. Un rôle métier désigne
    les identités qui détiennent tous ses droits ; le socle désigne celles qui
    devraient les détenir — c'est-à-dire tout le monde. Prendre ici les seuls
    détenteurs de tous les droits socles rendrait la mesure d'adhérence
    tautologique : elle vaudrait 100 % par construction, et la question utile —
    à qui manque le badge ? — n'aurait plus de réponse.

    Les identités hors périmètre sont écartées : les compter reviendrait à
    reprocher au socle de ne pas couvrir des gens qu'on a décidé de ne pas
    analyser.
    """
    ecartees = hors_perimetre or set()
    membres = []
    for identite in identites:
        identifiant = str(identite.get(colonne_identifiant, "") or "")
        if identifiant and identifiant not in ecartees:
            membres.append(identifiant)
    return sorted(set(membres))


def adherence_par_droit(droits: Sequence[str], membres: Sequence[str],
                        droits_par_identite: Mapping[str, Set[str]]
                        ) -> List[Dict[str, Any]]:
    """Combien de membres détiennent réellement chaque droit du socle.

    C'est la mesure qui fait du socle autre chose qu'une liste : « 98,7 % des
    identités analysées ont le badge » se lit comme « douze personnes ne l'ont
    pas », et celles-là se cherchent.
    """
    total = len(membres)
    detail = []
    for droit in droits:
        detenteurs = sum(1 for membre in membres
                         if droit in droits_par_identite.get(membre, set()))
        detail.append({
            "droit": droit,
            "detenteurs": detenteurs,
            "adherence_pct": round(100.0 * detenteurs / total, 1) if total else 0.0,
        })
    return detail


def role_socle(socle: Socle, membres: Sequence[str], nom_affiche: str = "",
               description: str = "") -> Dict[str, Any]:
    """Le socle sous la forme d'un rôle, pour les écrans et pour l'export.

    La forme est celle d'un rôle validé — mêmes clés, mêmes types — parce que
    tout ce qui affiche un rôle doit pouvoir l'afficher sans savoir d'où il
    vient. Ce qui le distingue tient en un drapeau : `is_socle`.

    `nom_affiche` n'est employé que si personne n'a nommé le socle, et il vaut
    vide par défaut : le libellé de repli est traduit, et c'est la surface qui
    l'affiche — l'écran dans la langue de l'utilisateur, l'export dans celle du
    document. Le serveur n'a pas à deviner laquelle.
    """
    return {
        "id": IDENTIFIANT_SOCLE,
        "name": socle.nom or nom_affiche,
        "description": description,
        "role_type": TYPE_SOCLE,
        "rights": list(socle.droits),
        "sub_roles": [],
        "additional_rights": [],
        "user_count": len(membres),
        "created_at": socle.detecte_le,
        "version": 1,
        # Le drapeau, plutôt qu'une comparaison d'identifiant chez chaque
        # appelant : un écran qui oublierait la comparaison proposerait de
        # renommer ou de sortir du catalogue un rôle qui ne s'y trouve pas.
        "is_socle": True,
        "threshold": socle.seuil,
    }


def _identites(loader) -> List[Dict[str, Any]]:
    cadre = loader.identities
    return cadre.to_dict("records") if cadre is not None and not cadre.empty else []


def membres_du_socle(loader, kb, colonne_identifiant: str) -> List[str]:
    """Les identités analysées, périmètre compris.

    Passe par `perimetre_effectif` plutôt que par la liste nominative : c'est
    le seul endroit qui combine les deux sources — exclusions nominatives et
    règles — et le contourner ferait compter des identités que tous les autres
    calculs du produit ont écartées.
    """
    from src.core.knowledge.perimetre import perimetre_effectif

    return population(_identites(loader), colonne_identifiant,
                      perimetre_effectif(loader, kb))


def detail_du_socle(loader, kb, colonne_identifiant: str,
                    droits_par_identite: Mapping[str, Set[str]]
                    ) -> Optional[Dict[str, Any]]:
    """Ce que contient le socle, sous la forme rendue pour un rôle validé.

    Le sur-octroi est nul **par construction**, et ce n'est pas une facilité :
    un droit socle est accordé à tout le monde, il ne peut donc être « en
    trop » pour personne. Ce qui se mesure ici est l'inverse — l'adhérence,
    c'est-à-dire ce qui manque : un droit socle que 98,7 % des identités
    détiennent désigne les 1,3 % qui ne l'ont pas, et ceux-là se cherchent.
    """
    socle = socle_du_workspace(kb)
    if not socle.existe:
        return None
    membres = membres_du_socle(loader, kb, colonne_identifiant)
    detail = adherence_par_droit(socle.droits, membres, droits_par_identite)
    couverture = (sum(entree["detenteurs"] for entree in detail)
                  / (len(membres) * len(socle.droits))
                  if membres and socle.droits else 0.0)
    return {
        "role": role_socle(socle, membres),
        "mesures": {
            "user_count": len(membres),
            "right_count": len(socle.droits),
            "over_granted": 0,
            "fit_pct": round(100.0 * couverture, 1),
        },
        "droits": detail,
        "membres_total": len(membres),
        # Le socle n'a pas d'historique : on ne le renomme pas et on ne le
        # modifie pas. On change la décision qui le produit, et il suit.
        "versions": [],
    }
