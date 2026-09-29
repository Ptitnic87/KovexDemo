# src/api/security_policy.py
"""
Politique d'accès de l'API, déclarée en un seul endroit.

Chaque route est associée à la permission nécessaire pour l'appeler. Une route
absente de la table est **refusée** : ajouter un endpoint sans déclarer qui a le
droit de l'appeler produit un 403 immédiat, pas un accès ouvert. C'est
volontaire — la version précédente laissait 73 endpoints accessibles sans le
moindre jeton, dont la suppression d'un workspace client et l'effacement de la
Knowledge Base.

Rôles et permissions (définis dans src/core/security/auth.py) :

    admin    read, write, delete, admin, mining, roles
    analyst  read, write, mining, roles
    viewer   read

Principe de rattachement :

- ``read``   consultation de données ou de configuration ;
- ``write``  modification de données de travail ;
- ``roles``  création, validation ou refus d'un rôle — la matière même du
             produit, réservée aux profils qui font de la gouvernance ;
- ``mining`` déclenchement d'un traitement coûteux ;
- ``admin``  administration de la plateforme : workspaces, configuration,
             sauvegarde et restauration de la Knowledge Base, chemins disque.
"""

import logging
from typing import Dict, Optional, Tuple

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials

from src.core.security.auth import require_permission_or_dev, security

logger = logging.getLogger(__name__)

#: Accessible sans jeton.
PUBLIC = "public"

PREFIXE_API = "/api/v1"
API = ""

POLITIQUE: Dict[Tuple[str, str], str] = {
    # --- Service ---------------------------------------------------------
    ("GET", "/"): PUBLIC,
    ("GET", "/health"): PUBLIC,

    # --- Documentation ----------------------------------------------------
    # Lecture seule, ouverte à tout compte authentifié : une documentation
    # réservée aux administrateurs ne sert pas ceux qui en ont besoin.
    ("GET", f"{API}/documentation/sections"): "read",
    ("GET", f"{API}/documentation/{{section}}"): "read",

    # --- Piste d'audit ----------------------------------------------------
    # Réservée à l'administration : un compte qui peut être audité ne décide
    # pas de ce que l'audit montre. Aucune route d'écriture ni de suppression
    # n'existe — la piste ne s'alimente que depuis les actions consignées.
    ("GET", f"{API}/audit"): "admin",
    ("GET", f"{API}/audit/actions"): "admin",
    ("GET", f"{API}/audit/acteurs"): "admin",
    ("GET", f"{API}/audit/verification"): "admin",
    ("GET", f"{API}/audit/export"): "admin",

    # --- Authentification ------------------------------------------------
    ("POST", f"{API}/auth/login"): PUBLIC,
    ("POST", f"{API}/auth/token"): PUBLIC,
    ("GET", f"{API}/auth/me"): "read",
    ("GET", f"{API}/auth/verify"): "read",
    ("POST", f"{API}/auth/logout"): "read",
    # Tout compte authentifié doit pouvoir changer son propre mot de passe :
    # l'exiger d'une permission d'écriture le réserverait aux profils élevés.
    ("POST", f"{API}/auth/change-password"): "read",
    ("POST", f"{API}/auth/refresh"): "read",

    # --- Consultation des données ---------------------------------------
    ("GET", f"{API}/users"): "read",
    ("GET", f"{API}/users/count"): "read",
    ("GET", f"{API}/users/list"): "read",
    ("GET", f"{API}/rights"): "read",
    ("GET", f"{API}/rights/list"): "read",
    ("GET", f"{API}/applications/list"): "read",
    ("GET", f"{API}/data-status"): "read",
    ("GET", f"{API}/stats/dashboard"): "read",
    ("GET", f"{API}/stats/rights-distribution"): "read",
    ("GET", f"{API}/reports/cleaning"): "read",
    # Diagnostic des transformations : ce qu'elles ont changé, valeur par
    # valeur. Même niveau que le rapport de qualité — c'est de la lecture
    # de référentiel, pas une décision de gouvernance.
    ("GET", f"{API}/reports/transformations/{{referentiel}}"): "read",
    ("GET", f"{API}/graph/columns"): "read",
    ("GET", f"{API}/graph/roles-status"): "read",

    # Export du modèle de rôles : une lecture, filtrable, du modèle existant.
    ("GET", f"{API}/export/modele/filtres"): "read",
    ("GET", f"{API}/export/modele/apercu"): "read",
    ("GET", f"{API}/export/modele/excel"): "read",
    ("GET", f"{API}/export/modele/pdf"): "read",
    ("GET", f"{API}/graph/layer"): "read",
    ("GET", f"{API}/habilitations/stats"): "read",
    ("GET", f"{API}/habilitations/user/{{user_id}}"): "read",
    ("GET", f"{API}/habilitations/application/{{app_id}}"): "read",
    ("GET", f"{API}/habilitations/right/{{right_id}}"): "read",
    ("GET", f"{API}/data-quality/export/excel"): "read",
    ("GET", f"{API}/data-quality/export/pdf"): "read",
    # Marque des habilitations comme recertifiées : modification de données.
    ("POST", f"{API}/data-recertify"): "write",

    # --- Internationalisation -------------------------------------------
    #
    # La lecture des catalogues est publique, et c'est délibéré : la page de
    # connexion doit s'afficher dans la langue de l'utilisateur, et elle est
    # par construction servie avant toute authentification. L'exiger
    # authentifiée revenait à écrire ses libellés en dur dans le JavaScript —
    # ce qu'elle faisait, en français uniquement.
    #
    # Ce qui est exposé : les libellés d'interface du produit. Aucune donnée
    # client, aucune information sur le référentiel, aucun nom de workspace.
    # Le reste du module, dont le rechargement des catalogues, reste fermé.
    ("GET", f"{API}/i18n/locales"): PUBLIC,
    ("GET", f"{API}/i18n/translations/{{locale}}"): PUBLIC,
    ("GET", f"{API}/i18n/translate"): "read",
    # Relit les catalogues sur disque : opération d'exploitation.
    ("POST", f"{API}/i18n/reload"): "admin",

    # --- Mining ----------------------------------------------------------
    ("GET", f"{API}/mining/stats"): "read",
    ("POST", f"{API}/mining/launch"): "mining",
    ("POST", f"{API}/mining/threshold-scan"): "mining",
    ("POST", f"{API}/mining/consolidation-scan"): "mining",
    ("POST", f"{API}/mining/explain"): "mining",
    ("GET", f"{API}/mining/annotator"): "mining",
    ("POST", f"{API}/mining/suggest-name"): "mining",
    ("GET", f"{API}/mining-metiers/attributes/identity/business"): "read",
    ("POST", f"{API}/mining-metiers/find-roles-business"): "mining",
    # La courbe d'arbitrage rejoue la sélection du mining : même
    # calcul, mêmes données, même permission.
    ("POST", f"{API}/mining-metiers/arbitrage"): "mining",
    # La mesure d'impact rejoue le mining sur quelques valeurs d'un
    # paramètre : même calcul, même permission.
    ("POST", f"{API}/mining-metiers/impact"): "mining",
    # Le détail des identités sans droit décrit le modèle conservé : même
    # lecture que le mining dont il provient.
    ("GET", f"{API}/mining-metiers/population-detail"): "mining",
    ("POST", f"{API}/mining-metiers/create-role-business"): "roles",

    # --- Droits socles ----------------------------------------------------
    ("GET", f"{API}/birth-rights/stats"): "read",
    ("POST", f"{API}/birth-rights/detect"): "mining",
    # Relance la détection puis produit un fichier sur le serveur.
    ("POST", f"{API}/birth-rights/export"): "mining",

    # --- Rôles -----------------------------------------------------------
    ("GET", f"{API}/roles/"): "read",
    ("GET", f"{API}/roles/{{role_id}}"): "read",
    ("GET", f"{API}/roles/stats/summary"): "read",
    ("POST", f"{API}/roles/create"): "roles",
    ("PUT", f"{API}/roles/{{role_id}}"): "roles",
    ("DELETE", f"{API}/roles/{{role_id}}"): "roles",

    # --- Knowledge Base --------------------------------------------------
    # Elle porte les décisions de gouvernance : ce qui les consulte est en
    # lecture, ce qui les modifie exige le profil qui fait de la gouvernance,
    # ce qui les efface ou les restaure en masse exige l'administration.
    ("GET", f"{API}/kb/stats"): "read",
    # Le travail en attente ne rend que des comptes de candidats : la
    # lecture suffit. Décider, elle, demande la permission « roles ».
    ("GET", f"{API}/kb/pending-work"): "read",
    ("GET", f"{API}/kb/candidates/{{role_type}}"): "read",
    # Oublier des candidats ne valide ni ne refuse rien, mais fait disparaître
    # de l'écran le travail d'un calcul : c'est la permission du mining.
    ("DELETE", f"{API}/kb/candidates/{{role_type}}"): "mining",
    # Écrire les noms retenus d'un lot. Même exigence que le mining qui a
    # produit ces candidats : ce n'est pas une décision de gouvernance, mais
    # ce n'est pas non plus une lecture.
    ("POST", f"{API}/kb/candidates/{{role_type}}/noms"): "mining",
    ("GET", f"{API}/kb/birth-rights"): "read",
    ("GET", f"{API}/kb/birth-rights/info"): "read",
    ("GET", f"{API}/kb/revue"): "read",
    ("GET", f"{API}/kb/validated-roles"): "read",
    ("GET", f"{API}/kb/validated-roles/{{role_id}}"): "read",
    ("GET", f"{API}/kb/validated-roles/{{role_id}}/detail"): "read",
    # Les rôles sortis du catalogue se lisent comme ceux qui y sont : c'est la
    # même matière de gouvernance, à une décision près.
    ("GET", f"{API}/kb/devalidated-roles"): "read",
    ("GET", f"{API}/kb/rejected-roles"): "read",
    ("GET", f"{API}/kb/rejected-roles/{{role_id}}/check"): "read",
    ("GET", f"{API}/kb/excluded-users"): "read",
    ("GET", f"{API}/kb/mining-history"): "read",
    ("POST", f"{API}/kb/mining-history"): "write",
    ("POST", f"{API}/kb/exclude-user"): "write",
    # Écarter une population du périmètre déplace tous les chiffres des
    # analyses suivantes : même droit que l'exclusion unitaire.
    ("POST", f"{API}/kb/exclude-users"): "write",
    ("DELETE", f"{API}/kb/excluded-users/{{user_id}}"): "write",
    # Les règles de périmètre décident de qui entre dans l'analyse : les lire
    # est une lecture, les poser change tout chiffre que le produit affiche.
    ("GET", f"{API}/kb/perimeter-rules"): "read",
    ("PUT", f"{API}/kb/perimeter-rules"): "write",
    # Appliquer une proposition de la revue modifie un rôle validé : c'est une
    # décision de gouvernance, au même titre qu'une validation. La lecture de
    # la revue, elle, reste une lecture.
    ("POST", f"{API}/kb/revue/appliquer"): "roles",
    ("POST", f"{API}/kb/validate-role"): "roles",
    ("PUT", f"{API}/kb/validated-roles/{{role_id}}"): "roles",
    ("DELETE", f"{API}/kb/validated-roles/{{role_id}}"): "roles",
    # Les porteurs d'un rôle validé : une lecture du référentiel d'identités,
    # restreinte aux membres du rôle. Même exigence que l'explorateur.
    ("GET", f"{API}/kb/validated-roles/{{role_id}}/porteurs"): "read",
    # Les accès proches d'un rôle et leurs trois populations : des lectures
    # du même référentiel, au même droit que les porteurs.
    ("GET", f"{API}/kb/validated-roles/{{role_id}}/acces-proches"): "read",
    ("GET", f"{API}/kb/validated-roles/{{role_id}}/acces-proches/population"): "read",
    # Renommer et dévalider sont des décisions de gouvernance au même titre
    # qu'une validation : le nom fait partie de ce que l'IGA a reçu, et sortir
    # un rôle du catalogue défait une décision.
    # Poser la référence d'un rôle qui n'en a pas est une décision de
    # gouvernance : elle fixe ce à quoi tous les écarts futurs seront comparés.
    ("POST", f"{API}/kb/validated-roles/{{role_id}}/ancrer"): "roles",
    ("POST", f"{API}/kb/validated-roles/{{role_id}}/renommer"): "roles",
    ("POST", f"{API}/kb/validated-roles/{{role_id}}/devalider"): "roles",
    ("POST", f"{API}/kb/reject-role"): "roles",
    ("DELETE", f"{API}/kb/rejected-roles/{{role_id}}"): "roles",
    # Les droits socles conditionnent tous les minings du workspace.
    ("POST", f"{API}/kb/birth-rights"): "admin",
    # Nommer le socle, c'est nommer un rôle que l'IGA recevra : même exigence
    # que la détection qui le produit.
    ("PUT", f"{API}/kb/birth-rights/name"): "admin",
    ("DELETE", f"{API}/kb/birth-rights"): "admin",
    ("POST", f"{API}/kb/backup"): "admin",
    ("POST", f"{API}/kb/restore"): "admin",
    ("DELETE", f"{API}/kb/clear-all"): "admin",

    # --- Configuration et workspaces -------------------------------------
    # Les lignes d'un référentiel pour un ensemble d'identifiants. C'est une
    # lecture du référentiel, restreinte : la même exigence que l'explorateur.
    ("POST", f"{API}/referentiels/{{referentiel}}/lignes"): "read",
    # Cohérence des valeurs. Le repérage est une lecture ; la table et les
    # refus changent ce que tous les calculs suivants verront.
    ("GET", f"{API}/coherence/colonnes"): "read",
    ("POST", f"{API}/coherence/analyser"): "read",
    # Poser la question au modèle est un geste d'analyste, au même titre que
    # lancer un mining ; décider que les valeurs d'une colonne peuvent sortir
    # est un acte d'administration, et il est pris dans la matrice
    # d'assistance, colonne par colonne. Les deux permissions ne se confondent
    # pas : celle-ci ne peut pas ouvrir ce que celle-là a fermé.
    ("POST", f"{API}/coherence/enrichir"): "mining",
    ("POST", f"{API}/coherence/appliquer"): "write",
    ("POST", f"{API}/coherence/refuser"): "write",
    ("GET", f"{API}/coherence/table/{{referentiel}}/{{colonne}}"): "read",
    ("PUT", f"{API}/coherence/table/{{referentiel}}/{{colonne}}"): "write",
    # L'agent de navigation. Poser une question est un geste d'analyste, comme
    # lancer un mining : il ne décide rien, il regarde. La liste des questions
    # que le produit sait calculer se lit avec le même droit — la cacher
    # laisserait un champ de saisie sans exemple, c'est-à-dire une boîte noire.
    ("GET", f"{API}/agent/intentions"): "mining",
    ("POST", f"{API}/agent/question"): "mining",
    ("GET", f"{API}/settings/"): "read",
    ("POST", f"{API}/settings/"): "admin",
    # Ce que le produit a le droit de demander à un modèle. La lecture est
    # réservée à l'administration comme l'écriture : un analyste pose la
    # question au modèle, il ne décide pas de ce qui part, et la carte des
    # sorties possibles d'un système d'habilitations n'a pas à circuler plus
    # largement que la décision qu'elle décrit.
    ("GET", f"{API}/assistance/"): "admin",
    ("PUT", f"{API}/assistance/"): "admin",
    # Où part chaque question. Même raisonnement que la matrice : la carte
    # des sorties possibles d'un système d'habilitations ne circule pas plus
    # largement que la décision qu'elle décrit. La clé se pose et se retire,
    # elle ne se lit jamais.
    ("GET", f"{API}/points-de-terminaison/"): "admin",
    ("PUT", f"{API}/points-de-terminaison/"): "admin",
    ("PUT", f"{API}/points-de-terminaison/prereglages/{{identifiant}}/cle"): "admin",
    ("DELETE", f"{API}/points-de-terminaison/prereglages/{{identifiant}}/cle"): "admin",
    ("GET", f"{API}/points-de-terminaison/prereglages/{{identifiant}}/modeles"): "admin",
    ("POST", f"{API}/points-de-terminaison/prereglages/{{identifiant}}/essai"): "admin",
    # Poser la question est un geste d'analyste ; décider de ce qui a le droit
    # de sortir reste une décision d'administration, prise dans la matrice
    # avant que ces routes ne puissent rien envoyer.
    ("POST", f"{API}/assistance/droits-sensibles"): "mining",
    ("POST", f"{API}/assistance/attributs-pertinents"): "mining",
    ("POST", f"{API}/assistance/explication-de-role"): "mining",
    ("POST", f"{API}/assistance/explication-de-conflit"): "mining",
    ("POST", f"{API}/assistance/comptes-a-privileges"): "mining",
    # Le dénombrement des comptes marqués est une lecture du référentiel :
    # « combien de comptes à privilèges » se lit comme n'importe quel compteur
    # du tableau de bord. L'écran des paramètres l'affiche, mais l'écrire
    # relève de l'enregistrement de la configuration, qui est déjà réservé.
    ("GET", f"{API}/privileges"): "read",
    ("POST", f"{API}/privileges/mesurer"): "mining",
    # La séparation des tâches. Lire les conflits est un geste d'analyste ;
    # déclarer ce que la même personne ne doit pas pouvoir faire est une
    # décision de contrôle interne, et elle se prend au même niveau que le
    # périmètre d'analyse — celui qui conduit l'étude en répond.
    ("GET", f"{API}/separation/regles"): "mining",
    ("PUT", f"{API}/separation/regles"): "mining",
    ("GET", f"{API}/separation/conflits"): "mining",
    ("GET", f"{API}/separation/conflits/{{regle_id}}"): "mining",
    ("GET", f"{API}/separation/candidats"): "mining",
    ("POST", f"{API}/separation/controler"): "mining",
    ("GET", f"{API}/separation/roles"): "mining",

    # --- Mouvement --------------------------------------------------------
    # Les droits conservés d'un poste précédent : une lecture, au même niveau
    # que les conflits de séparation. Elle ne modifie rien et ne décide rien.
    ("GET", f"{API}/mouvement"): "mining",

    # --- Nommage des droits ------------------------------------------------
    # Ce que la convention découperait : une lecture de référentiel, au même
    # niveau que le rapport de qualité. Rien n'y est décidé, rien n'y est écrit.
    ("GET", f"{API}/nommage"): "read",
    # Assumer une exception fait taire un signalement : c'est la décision de
    # gouvernance la plus sensible du produit, et elle se prend au même niveau
    # que la déclaration des règles.
    ("GET", f"{API}/derogations"): "mining",
    ("POST", f"{API}/derogations"): "mining",
    ("DELETE", f"{API}/derogations/{{identifiant}}"): "mining",
    # Trancher une dérogation demandée : même permission, et le serveur
    # refuse que ce soit celui qui l'a demandée.
    ("POST", f"{API}/derogations/{{identifiant}}/approuver"): "mining",
    ("POST", f"{API}/derogations/{{identifiant}}/refuser"): "mining",
    # Les contrôles compensatoires : même décision, même permission que la
    # dérogation qu'ils rendent défendable.
    ("GET", f"{API}/controles"): "mining",
    ("PUT", f"{API}/controles"): "mining",
    ("GET", f"{API}/controles/{{identifiant}}/executions"): "mining",
    ("POST", f"{API}/controles/{{identifiant}}/executions"): "mining",
    # Le signal d'usage : des lectures du référentiel, au même droit que les
    # droits conservés d'un poste précédent.
    ("GET", f"{API}/usage/colonnes"): "mining",
    ("GET", f"{API}/usage"): "mining",
    ("GET", f"{API}/usage/dormants"): "mining",
    ("GET", f"{API}/usage/inactives"): "mining",
    # Le panneau d'une identité rassemble des constats de mining, de
    # séparation et de mouvement : il se lit au même droit que chacun d'eux.
    ("GET", f"{API}/identites/{{identite}}/constats"): "mining",
    # Ce que le workspace apprend de ses décisions : lire et scorer relèvent de
    # l'analyste ; désapprendre change ce que le produit recommandera à tous,
    # et relève de celui qui valide les rôles.
    ("GET", f"{API}/apprentissage"): "mining",
    ("POST", f"{API}/apprentissage/ressemblance"): "mining",
    ("PUT", f"{API}/apprentissage/decisions/{{role_id}}"): "roles",
    ("POST", f"{API}/apprentissage/oublier"): "roles",
    ("GET", f"{API}/workspaces/"): "read",
    ("GET", f"{API}/workspaces/active"): "read",
    ("GET", f"{API}/workspaces/{{workspace_id}}"): "read",
    ("GET", f"{API}/workspaces/{{workspace_id}}/config"): "read",
    # L'habillage est une donnée de consultation : tout compte qui voit le
    # workspace doit pouvoir en obtenir les couleurs, sans quoi l'écran d'un
    # lecteur s'afficherait aux couleurs du produit et celui d'un
    # administrateur à celles du client.
    ("GET", f"{API}/workspaces/{{workspace_id}}/themes"): "read",
    ("GET", f"{API}/workspaces/{{workspace_id}}/themes/{{theme_id}}/logo"): "read",
    ("POST", f"{API}/workspaces/"): "admin",
    ("PUT", f"{API}/workspaces/{{workspace_id}}"): "admin",
    ("DELETE", f"{API}/workspaces/{{workspace_id}}"): "admin",
    ("POST", f"{API}/workspaces/switch/{{workspace_id}}"): "admin",
    ("PUT", f"{API}/workspaces/{{workspace_id}}/config"): "admin",
    # Inspecter ne touche à rien — ni au workspace, ni aux fichiers en place —
    # mais lit ce qu'on lui envoie : même droit que l'import, puisque c'est la
    # même personne, au même moment, sur le même geste.
    ("POST", f"{API}/workspaces/{{workspace_id}}/inspecter-fichiers"): "admin",
    ("POST", f"{API}/workspaces/{{workspace_id}}/import-data"): "admin",
    ("POST", f"{API}/workspaces/{{workspace_id}}/export"): "admin",
    ("POST", f"{API}/workspaces/reload-data"): "admin",
    # Divulgue un chemin du serveur : réservé à l'administration.
    ("GET", f"{API}/workspaces/{{workspace_id}}/kb-path"): "admin",
}


#: Routes en POST qui ne sont **que** des lectures.
#:
#: La règle du produit est qu'une écriture exige plus qu'une permission de
#: lecture, et un test la vérifie. Quelques routes emploient POST sans rien
#: écrire : elles lisent selon un critère trop volumineux pour une adresse —
#: la liste des porteurs d'un rôle candidat peut compter des milliers
#: d'identifiants.
#:
#: La liste est déclarée **ici**, avec la politique qu'elle nuance, et non
#: dans le test : une exception écrite du côté du contrôle finit par servir à
#: faire taire le contrôle. Toute entrée doit rendre des données sans en
#: modifier aucune.
LECTURES_PAR_POST: frozenset = frozenset({
    f"{API}/referentiels/{{referentiel}}/lignes",
    # Le repérage ne modifie rien : il lit une colonne et rend des grappes. Le
    # verbe est POST parce que le référentiel et la colonne se nomment dans le
    # corps, comme le reste des lectures paramétrées du produit.
    f"{API}/coherence/analyser",
})


def normaliser(chemin: str) -> str:
    """Ramène un chemin de route à la forme utilisée par la table.

    Selon la version de FastAPI, le chemin porté par la route résolue inclut ou
    non le préfixe de montage. La table est donc écrite sans préfixe, et on le
    retire ici s'il est présent : la politique ne dépend pas d'un détail
    d'implémentation du framework.
    """
    if chemin.startswith(PREFIXE_API):
        chemin = chemin[len(PREFIXE_API):] or "/"
    return chemin


def permission_requise(methode: str, chemin: str) -> Optional[str]:
    """Permission exigée pour un couple (méthode, chemin), ou None si non déclaré."""
    methode = methode.upper()
    if methode == "HEAD":
        methode = "GET"
    return POLITIQUE.get((methode, normaliser(chemin)))


async def appliquer_politique(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> None:
    """Dépendance appliquée à toutes les routes de l'API.

    Le chemin utilisé est celui du gabarit de route (``/kb/validated-roles/{role_id}``)
    et non l'URL appelée : la politique ne dépend pas des valeurs transmises.
    """
    route = request.scope.get("route")
    chemin = getattr(route, "path", None) or request.url.path
    exigence = permission_requise(request.method, chemin)

    if exigence is None:
        # Refus par défaut : une route non déclarée n'est pas une route ouverte.
        logger.error(
            "Route absente de la politique d'accès : %s %s. Déclarez-la dans "
            "src/api/security_policy.py.", request.method, chemin,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "error.route_not_declared"},
        )

    if exigence == PUBLIC:
        return

    # Réutilise la vérification du module d'authentification : une seule
    # implémentation du contrôle, y compris pour le mode développement.
    await require_permission_or_dev(exigence)(credentials)
