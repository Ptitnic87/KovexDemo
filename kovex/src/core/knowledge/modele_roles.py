# Fichier : src/core/knowledge/modele_roles.py
"""Assemblage du modèle de rôles, filtrable, pour l'export.

Ce module ne produit ni classeur ni PDF : il construit la **matière** que les
deux formats mettent en page. Les deux documents partent ainsi des mêmes
chiffres — un export Excel et un export PDF demandés le même jour qui ne
donneraient pas les mêmes comptes seraient l'un et l'autre inutilisables en
comité.

Deux règles héritées du reste du produit :

- **les membres sont calculés, pas lus.** Un rôle est une règle ; sa liste de
  membres n'est pas figée dans la base. C'est le même calcul que celui du
  graphe, obtenu du même objet, pour que les deux écrans ne se contredisent
  jamais ;
- **aucun attribut n'est présupposé.** Les attributs sur lesquels on peut
  filtrer sont ceux du fichier du client, découverts à la lecture.

Sémantique des filtres, qui n'est pas neutre : un filtre côté identités
restreint **aussi** les membres listés, alors qu'un rôle conserve son compte
total. Sans cela, filtrer sur trente personnes ferait ressortir un rôle avec
ses six mille membres, et le lecteur ne saurait plus ce qu'il regarde.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from src.core.knowledge.socle import (IDENTIFIANT_SOCLE, TYPE_SOCLE,
                                      membres_du_socle, socle_du_workspace)

#: Ordre de présentation des origines : l'existant, puis le proposé, puis
#: l'écarté. L'ordre alphabétique aurait ouvert le document sur les rejets.
ORDRE_ORIGINES = ("validated", "suggested", "rejected")

TYPE_METIER = "METIER"
TYPE_APPLICATIF = "APPLICATIF"
#: Le socle est un type à part entière du document : il n'est ni métier ni
#: applicatif, et l'omettre revenait à livrer un modèle amputé de la seule
#: chose que tout le monde reçoit en arrivant.
TYPES = (TYPE_METIER, TYPE_APPLICATIF, TYPE_SOCLE)

#: Colonne du graphe correspondant à chaque type de rôle. Le socle n'en a
#: aucune : il ne vient pas d'un mining, il vient d'une décision de détection.
COLONNE_PAR_TYPE = {TYPE_METIER: "business_role",
                    TYPE_APPLICATIF: "application_role"}

#: Ordre de présentation des types. Le socle ouvre le document : c'est ce que
#: tout le monde reçoit en arrivant, et les autres rôles s'ajoutent par-dessus.
#: L'ordre des deux autres est celui qui existait — le changer déplacerait des
#: lignes dans un document que le destinataire compare au précédent.
ORDRE_TYPES = (TYPE_SOCLE, TYPE_APPLICATIF, TYPE_METIER)


@dataclass(frozen=True)
class Filtres:
    """Ce que l'utilisateur a choisi d'extraire.

    Un jeu vide signifie « aucune restriction sur ce critère », jamais
    « aucun résultat » : ne rien cocher ne doit pas produire un fichier vide
    sans explication.
    """

    origines: Sequence[str] = ()
    types: Sequence[str] = ()
    applications: Set[str] = field(default_factory=set)
    identites: Set[str] = field(default_factory=set)
    attribut: Optional[str] = None
    valeurs_attribut: Set[str] = field(default_factory=set)

    @property
    def restreint_les_identites(self) -> bool:
        """Un filtre porte-t-il sur les identités elles-mêmes ?"""
        return bool(self.identites) or bool(self.attribut and self.valeurs_attribut)

    def description(self) -> List[Dict[str, Any]]:
        """Filtres appliqués, pour être écrits dans le document produit.

        Un extrait filtré qui ne dit pas ce qu'il a filtré n'est pas
        exploitable : le lecteur ne peut pas savoir si un rôle absent a été
        écarté ou n'existe pas.
        """
        lignes: List[Dict[str, Any]] = [
            {"critere": "origins", "valeurs": list(self.origines)},
            {"critere": "role_types", "valeurs": list(self.types)},
        ]
        if self.applications:
            lignes.append({"critere": "applications",
                           "valeurs": sorted(self.applications)})
        if self.attribut and self.valeurs_attribut:
            lignes.append({"critere": "attribute",
                           "attribut": self.attribut,
                           "valeurs": sorted(self.valeurs_attribut)})
        if self.identites:
            lignes.append({"critere": "identities",
                           "valeurs": sorted(self.identites)})
        return lignes


#: Ce qu'un rôle est devenu depuis le dernier export. Sans cette mention,
#: l'intégrateur reçoit un rôle qu'il croit nouveau et en crée un doublon dans
#: l'IGA du client : c'est la raison concrète du versionnement.
NOUVEAU = "nouveau"
MODIFIE = "modifie"
INCHANGE = "inchange"


def evolution_depuis(role: Dict[str, Any], depuis: Optional[str]) -> str:
    """Nouveau, modifié ou inchangé depuis la date du dernier export.

    Sans export précédent, tout est nouveau — et c'est exact : le destinataire
    n'a rien reçu.
    """
    if not depuis:
        return NOUVEAU
    valide_le = str(role.get("validated_at") or "")
    modifie_le = str(role.get("updated_at") or "")
    if valide_le > depuis:
        return NOUVEAU
    if modifie_le > depuis:
        return MODIFIE
    return INCHANGE


@dataclass
class RoleExporte:
    """Un rôle, tel qu'il figurera dans le document."""

    id: str
    nom: str
    description: str
    type_role: str
    origine: str
    droits: List[str]
    membres: List[str]
    membres_total: int
    applications: List[str]
    #: Version du rôle validé. Un rôle jamais modifié est en version 1.
    version: int = 1
    #: Ce que ce rôle est devenu depuis le dernier export : NOUVEAU, MODIFIE,
    #: INCHANGE — ou vide pour un rôle qui n'appartient pas au modèle validé,
    #: un candidat n'ayant jamais été exporté comme faisant partie du modèle.
    evolution: str = ""

    @property
    def membres_masques(self) -> int:
        """Membres écartés par un filtre, et donc non listés."""
        return max(0, self.membres_total - len(self.membres))


@dataclass
class Modele:
    roles: List[RoleExporte]
    filtres: Filtres
    #: Attributs d'identité disponibles, tels que le fichier les nomme.
    attributs_disponibles: List[str]

    @property
    def totaux(self) -> Dict[str, int]:
        par_origine: Dict[str, int] = {}
        par_type: Dict[str, int] = {}
        for role in self.roles:
            par_origine[role.origine] = par_origine.get(role.origine, 0) + 1
            par_type[role.type_role] = par_type.get(role.type_role, 0) + 1
        return {
            "roles": len(self.roles),
            "droits": len({d for r in self.roles for d in r.droits}),
            "identites": len({m for r in self.roles for m in r.membres}),
            # Ce que le destinataire n'a pas encore reçu, ou a reçu autrement.
            "nouveaux": sum(1 for r in self.roles if r.evolution == NOUVEAU),
            "modifies": sum(1 for r in self.roles if r.evolution == MODIFIE),
            **{f"origine_{cle}": valeur for cle, valeur in par_origine.items()},
            **{f"type_{cle}": valeur for cle, valeur in par_type.items()},
        }


def attributs_identite(identites_df, colonne_identifiant: str) -> List[str]:
    """Attributs sur lesquels un filtre peut porter.

    Découverts dans le fichier : le produit n'impose ni `fonction`, ni
    `departement`, ni aucun autre nom.
    """
    if identites_df is None or getattr(identites_df, "empty", True):
        return []
    return [c for c in identites_df.columns if c != colonne_identifiant]


def valeurs_d_attribut(identites_df, attribut: str) -> List[str]:
    """Valeurs distinctes prises par un attribut, triées."""
    if identites_df is None or getattr(identites_df, "empty", True):
        return []
    if attribut not in identites_df.columns:
        return []
    valeurs = {str(v).strip() for v in identites_df[attribut].dropna().tolist()}
    return sorted(v for v in valeurs if v and v.lower() not in ("nan", "none"))


def _identites_retenues(identites: Iterable[Dict[str, Any]],
                        colonne_identifiant: str,
                        filtres: Filtres) -> Optional[Set[str]]:
    """Identités que les filtres retiennent, `None` si aucun ne s'applique."""
    if not filtres.restreint_les_identites:
        return None

    retenues: Set[str] = set()
    if filtres.attribut and filtres.valeurs_attribut:
        attendues = {v.casefold() for v in filtres.valeurs_attribut}
        for identite in identites:
            valeur = identite.get(filtres.attribut)
            if valeur is None:
                continue
            if str(valeur).strip().casefold() in attendues:
                identifiant = identite.get(colonne_identifiant)
                if identifiant is not None:
                    retenues.add(str(identifiant))

    if filtres.identites:
        # Deux filtres identitaires se cumulent par intersection : « les
        # infirmiers **parmi** ces personnes », pas « les infirmiers **et**
        # ces personnes », qui élargirait au lieu de restreindre.
        retenues = (retenues & filtres.identites) if retenues else set(filtres.identites)

    return retenues


def _socle_exporte(contexte, colonne_identifiant: str, filtres: Filtres,
                   retenues: Optional[Set[str]], nom_socle: str,
                   application_par_droit: Dict[str, str]) -> Optional[RoleExporte]:
    """Le socle, sous la forme d'une ligne du document.

    Il n'a ni colonne dans le graphe ni entrée dans la base : il se dérive de
    la décision de détection et du périmètre du jour. Son origine est celle du
    modèle en place — c'est une décision prise, pas une proposition.
    """
    socle = socle_du_workspace(contexte.kb)
    if not socle.existe:
        return None

    droits = list(socle.droits)
    applications = sorted({application_par_droit.get(d) for d in droits} - {None})
    if filtres.applications and not (set(applications) & filtres.applications):
        return None

    membres = set(membres_du_socle(contexte.loader, contexte.kb, colonne_identifiant))
    total = len(membres)
    if retenues is not None:
        membres = membres & retenues
        if not membres:
            return None

    return RoleExporte(
        id=IDENTIFIANT_SOCLE,
        nom=socle.nom or nom_socle,
        description="",
        type_role=TYPE_SOCLE,
        origine=ORDRE_ORIGINES[0],
        droits=sorted(droits),
        membres=sorted(membres),
        membres_total=total,
        applications=applications,
        version=1,
        # Le socle n'a pas d'historique de versions : il suit la décision qui
        # le produit. Dire qu'il est « nouveau » ou « inchangé » depuis le
        # dernier export supposerait une date de validation qu'il n'a pas.
        evolution="",
    )


def assembler(contexte, identites_df, colonne_identifiant: str,
              filtres: Filtres, depuis_export: Optional[str] = None,
              nom_socle: str = "") -> Modele:
    """Construit le modèle filtré.

    `contexte` est l'objet du graphe : il porte le calcul des membres et le
    rattachement d'un droit à son application. Le réutiliser garantit que
    l'export et l'écran répondent la même chose.

    `nom_socle` est le libellé de repli du rôle socle, dans la langue du
    document, employé tant que personne ne l'a nommé : le nom d'un socle est
    une décision du client, le produit n'en invente pas.
    """
    identites = (identites_df.to_dict("records")
                 if identites_df is not None and not identites_df.empty else [])
    retenues = _identites_retenues(identites, colonne_identifiant, filtres)
    application_par_droit = contexte.applications

    roles: List[RoleExporte] = []
    if TYPE_SOCLE in filtres.types and ORDRE_ORIGINES[0] in filtres.origines:
        entree = _socle_exporte(contexte, colonne_identifiant, filtres, retenues,
                                nom_socle, application_par_droit)
        if entree is not None:
            roles.append(entree)

    for type_role in filtres.types:
        colonne = COLONNE_PAR_TYPE.get(type_role)
        if colonne is None:
            continue
        for brut in contexte.roles(colonne, filtres.origines):
            droits = [str(d) for d in (brut.get("rights") or [])]
            applications = sorted({application_par_droit.get(d) for d in droits}
                                  - {None})

            if filtres.applications and not (set(applications) & filtres.applications):
                continue

            membres = contexte.membres(brut)
            total = len(membres)
            if retenues is not None:
                membres = membres & retenues
                # Un rôle qu'aucune identité retenue ne porte n'a pas sa place
                # dans un extrait demandé « pour ces personnes ».
                if not membres:
                    continue

            origine = brut.get("_origine", "")
            roles.append(RoleExporte(
                id=str(brut.get("id", "")),
                nom=str(brut.get("name", "") or ""),
                description=str(brut.get("description", "") or ""),
                type_role=type_role,
                origine=origine,
                droits=sorted(droits),
                membres=sorted(membres),
                membres_total=total,
                applications=applications,
                version=int(brut.get("version") or 1),
                # Un candidat n'a jamais été livré comme faisant partie du
                # modèle : dire qu'il est « nouveau » ou « inchangé » depuis le
                # dernier export n'aurait pas de sens.
                evolution=(evolution_depuis(brut, depuis_export)
                           if origine == ORDRE_ORIGINES[0] else ""),
            ))

    # L'ordre alphabétique des origines plaçait les rôles **rejetés** en tête
    # du document. Un livrable de gouvernance commence par le modèle en place,
    # puis ce qui est proposé, puis ce qui a été écarté.
    rang = {origine: index for index, origine in enumerate(ORDRE_ORIGINES)}
    rang_type = {type_role: index for index, type_role in enumerate(ORDRE_TYPES)}
    roles.sort(key=lambda r: (rang_type.get(r.type_role, len(rang_type)),
                              rang.get(r.origine, len(rang)),
                              r.nom or r.id))
    return Modele(
        roles=roles,
        filtres=filtres,
        attributs_disponibles=attributs_identite(identites_df, colonne_identifiant),
    )
