"""Ce qu'un candidat du mining est devenu, et ce qu'il reste à décider.

Un mining produit des candidats ; l'utilisateur en valide, en refuse, et laisse
les autres. Savoir lesquels restent est une question qui se pose à trois
endroits — l'indicateur de travail en attente, le graphe « avant / après », et
l'écran de mining lui-même. Répondue trois fois, elle recevrait trois réponses
différentes le jour où l'une des trois oublie un cas ; elle l'était, et elle en
recevait effectivement trois.

Un candidat est **décidé** de trois façons, et il faut les trois :

1. son identifiant figure parmi les rôles refusés du workspace ;
2. une décision consignée le désigne comme le candidat sur lequel elle porte —
   c'est le cas d'une validation, qui crée un rôle dont l'identifiant est neuf
   et ne ressemble plus à celui du candidat ;
3. un rôle validé porte exactement le même ensemble de droits. Ce dernier
   critère rattrape les validations antérieures à l'enregistrement du lien, et
   celles faites hors de l'écran de mining : sans lui, un rôle accepté
   resterait annoncé comme « à décider » indéfiniment.

Aucun stockage nouveau : tout se lit dans la base de connaissance du workspace.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

#: Le candidat a été accepté : un rôle validé en est issu.
VALIDE = "validated"
#: Le candidat a été écarté.
REJETE = "rejected"
#: Le candidat n'a reçu aucune décision : c'est lui, et lui seul, qui constitue
#: le travail en attente.
EN_ATTENTE = "suggested"


@dataclass(frozen=True)
class Referentiel:
    """Ce qu'il faut savoir du workspace pour juger un candidat.

    Construit une fois par appel : les trois lectures qu'il porte parcourent
    l'intégralité des décisions et des rôles validés, et les refaire par
    candidat rendrait la question quadratique sur un référentiel volumineux.
    """

    tranches: frozenset
    droits_valides: frozenset

    @classmethod
    def depuis(cls, kb, type_role: Optional[str] = None) -> "Referentiel":
        valides = kb.get_validated_roles(role_type=type_role)
        return cls(
            tranches=frozenset(kb.candidats_tranches()),
            droits_valides=frozenset(
                frozenset(str(droit) for droit in (role.get("rights") or []))
                for role in valides
            ),
        )


def verdict(candidat: Dict[str, Any], referentiel: Referentiel) -> str:
    """Ce qu'est devenu ce candidat : validé, refusé, ou toujours en attente."""
    identifiant = str(candidat.get("id"))
    droits = frozenset(str(droit) for droit in (candidat.get("rights") or []))
    if droits and droits in referentiel.droits_valides:
        return VALIDE
    if identifiant in referentiel.tranches:
        # Un identifiant tranché qui n'a pas de rôle validé de mêmes droits est
        # un refus : une validation aurait laissé son rôle derrière elle.
        return REJETE
    return EN_ATTENTE


@dataclass(frozen=True)
class EtatDesCandidats:
    """Le compte, par type de rôle, de ce qui a été décidé et de ce qui reste."""

    type_de_role: str
    total: int
    en_attente: int
    valides: int
    refuses: int
    calcule_le: Optional[str]
    #: Les données ont changé depuis ce calcul : ce qui reste à décider porte
    #: sur un référentiel qui n'est plus le référentiel courant. On le dit.
    obsolete: bool

    def en_dict(self) -> Dict[str, Any]:
        return {
            "role_type": self.type_de_role,
            "candidates": self.total,
            "undecided": self.en_attente,
            "validated": self.valides,
            "rejected": self.refuses,
            "computed_at": self.calcule_le,
            "stale": self.obsolete,
        }


def etat_des_candidats(kb, type_de_role: str, empreinte_courante: str) -> EtatDesCandidats:
    """État des candidats conservés pour un type de rôle."""
    run = kb.get_candidate_run(type_de_role)
    candidats: Sequence[Dict[str, Any]] = list(run.get("roles") or []) if run else []
    referentiel = Referentiel.depuis(kb, type_de_role)

    comptes = {VALIDE: 0, REJETE: 0, EN_ATTENTE: 0}
    for candidat in candidats:
        comptes[verdict(candidat, referentiel)] += 1

    empreinte_du_run = (run or {}).get("data_fingerprint") or ""
    return EtatDesCandidats(
        type_de_role=type_de_role,
        total=len(candidats),
        en_attente=comptes[EN_ATTENTE],
        valides=comptes[VALIDE],
        refuses=comptes[REJETE],
        calcule_le=run.get("computed_at") if run else None,
        # Sans empreinte conservée, on ne sait pas : on ne prétend pas que le
        # calcul est à jour, mais on ne crie pas à l'obsolescence non plus.
        obsolete=bool(empreinte_du_run) and empreinte_du_run != empreinte_courante,
    )


def travail_en_attente(kb, types_de_role: Sequence[str],
                       empreinte_courante: str) -> Dict[str, Any]:
    """Ce qu'il reste à décider, tous types de rôles confondus."""
    etats: List[EtatDesCandidats] = [
        etat_des_candidats(kb, type_de_role, empreinte_courante)
        for type_de_role in types_de_role
    ]
    return {
        "total": sum(etat.en_attente for etat in etats),
        "stale": any(etat.obsolete for etat in etats),
        "types": [etat.en_dict() for etat in etats],
    }
