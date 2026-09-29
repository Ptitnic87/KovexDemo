# src/core/annotation/explication_conflit.py
"""Expliquer un conflit de séparation des tâches, sans nombre inventé.

Le marché ne le fait pas : la séparation des tâches y est à règles partout, et
un conflit s'y lit comme une ligne dans un tableau — deux libellés de droits,
une identité, une case à cocher. Le responsable du contrôle interne, lui, doit
écrire à la direction **pourquoi** cette combinaison est un risque et ce qui
le réduirait. C'est ce paragraphe que ce module fait rédiger.

Le même contrôle que l'explication d'un rôle, et pour la même raison : tout
nombre du paragraphe doit figurer parmi ceux transmis. Une phrase qui annonce
« 42 personnes » quand le calcul en a trouvé 40 est refusée, jamais corrigée.

**Ce qui ne part jamais : les personnes.** Le paragraphe porte sur la règle,
à l'échelle de la population. Les comptes (combien d'identités réunissent les
deux côtés, combien le tiennent d'un rôle, combien sont couvertes par une
dérogation) partent toujours ; aucun identifiant ne part, quelle que soit la
configuration. Les mots — libellé de la règle, libellés des droits, noms des
rôles qui portent les deux côtés — ne partent que si l'administrateur les a
ouverts pour cet usage.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

from src.core.annotation.annotateur import (AnnotateurIndisponible, Reglages,
                                            RienANommer, demander)
from src.core.annotation.assistance import (MATIERE_LIBELLES_DE_DROITS,
                                            MATIERE_NOMS_VALIDES,
                                            MATIERE_REGLES_DE_SEPARATION,
                                            Autorisation)
from src.core.annotation.explication import (DROITS_CITES_MAX,
                                             SCHEMA_DE_L_EXPLICATION,
                                             lire_l_explication)
from src.core.annotation.propositions import composer_la_demande_de

#: Les comptes d'une règle que le produit transmet, et les seuls qu'il
#: acceptera en retour. Nommés : c'est le nom qui porte le sens, et c'est ce
#: qui permet au contrôle de dire lequel a été inventé.
GRANDEURS_DU_CONFLIT = ("identites", "par_les_roles", "hors_role", "derogees",
                        "roles_en_conflit", "droits_gauche", "droits_droite")

CONSIGNE_EXPLICATION_DE_CONFLIT = (
    "On te donne une règle de séparation des tâches et les comptes de ses "
    "conflits, déjà calculés : combien de personnes réunissent les deux côtés "
    "de la règle, combien le tiennent d'un rôle qui porte les deux côtés, "
    "combien sont couvertes par une dérogation. Tu rédiges un paragraphe court "
    "pour un responsable du contrôle interne : pourquoi réunir ces deux côtés "
    "est un risque, ce que les comptes disent de son origine (un rôle à "
    "corriger, ou des cas individuels), et ce qui le réduirait.\n"
    "Règles, et la première est absolue :\n"
    "- N'écris AUCUN nombre qui ne soit pas dans les grandeurs données. Ne "
    "calcule rien, n'additionne rien, ne complète rien. Si une grandeur n'est "
    "pas donnée, n'en parle pas.\n"
    "- Écris les nombres en chiffres, jamais en toutes lettres.\n"
    "- Ne nomme aucune personne : tu n'en connais aucune.\n"
    "- Un paragraphe, pas de liste, pas de titre.\n"
    "- Suis la langue demandée.\n"
    "Réponds uniquement par un objet JSON avec une clé \"explication\", la "
    "valeur étant le paragraphe."
)


def grandeurs_du_conflit(synthese: Mapping[str, Any]) -> Dict[str, float]:
    """Les comptes de la règle, tels que l'écran des conflits les affiche.

    Un compte absent n'est pas transmis à zéro : non mesuré et nul ne sont
    pas la même chose, et un modèle à qui l'on annonce « dérogations : 0 »
    écrira qu'aucune exception n'a été accordée.
    """
    grandeurs: Dict[str, float] = {}
    for nom in GRANDEURS_DU_CONFLIT:
        valeur = synthese.get(nom)
        if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
            continue
        grandeurs[nom] = float(valeur)
    return grandeurs


def faits_du_conflit(autorisation: Autorisation, synthese: Mapping[str, Any],
                     gauche: List[str], droite: List[str],
                     roles: List[str]) -> tuple:
    """Ce qui part, matière par matière, et la liste des matières sorties."""
    faits: Dict[str, Any] = {"grandeurs": grandeurs_du_conflit(synthese)}
    categories: List[str] = []
    if autorisation.autorise(MATIERE_REGLES_DE_SEPARATION):
        faits["regle"] = {cle: str(synthese.get(cle) or "")
                          for cle in ("libelle", "processus", "severite")}
        categories.append(MATIERE_REGLES_DE_SEPARATION)
    if autorisation.autorise(MATIERE_LIBELLES_DE_DROITS) and (gauche or droite):
        faits["cote_gauche"] = gauche[:DROITS_CITES_MAX]
        faits["cote_droit"] = droite[:DROITS_CITES_MAX]
        categories.append(MATIERE_LIBELLES_DE_DROITS)
    if autorisation.autorise(MATIERE_NOMS_VALIDES) and roles:
        faits["roles_des_deux_cotes"] = roles[:DROITS_CITES_MAX]
        categories.append(MATIERE_NOMS_VALIDES)
    return faits, categories


def expliquer_un_conflit(reglages: Reglages, autorisation: Autorisation,
                         synthese: Mapping[str, Any], gauche: List[str],
                         droite: List[str], roles: List[str], langue: str,
                         envoyer) -> Dict[str, Any]:
    """Rédige l'explication d'une règle en conflit, ou ne rend rien.

    Une règle sans conflit n'a rien à expliquer : un paragraphe sur zéro
    personne se lirait comme un constat, et il n'y en a pas.
    """
    if not reglages.actif:
        raise AnnotateurIndisponible("assistance désactivée")
    if not autorisation.posable:
        raise RienANommer("usage fermé ou matière non autorisée")
    faits, categories = faits_du_conflit(autorisation, synthese, gauche, droite, roles)
    if not faits["grandeurs"].get("identites"):
        raise RienANommer("aucun conflit à expliquer")
    # Pas de garde sur une matière ouverte mais vide : `posable` exige le
    # libellé de la règle ou les libellés de droits, la règle a toujours un
    # libellé, et un conflit a toujours un droit de chaque côté.

    grandeurs = faits["grandeurs"]
    charge = composer_la_demande_de(CONSIGNE_EXPLICATION_DE_CONFLIT, faits,
                                    reglages, langue)
    rendu = demander(charge, reglages,
                     lambda reponse: lire_l_explication(reponse, grandeurs),
                     SCHEMA_DE_L_EXPLICATION, envoyer)
    return {
        "explication": rendu["explication"],
        "grandeurs": grandeurs,
        "modele": reglages.modele,
        "usage": autorisation.usage.code,
        "categories_transmises": sorted(categories),
    }
