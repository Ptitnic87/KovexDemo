# 05 — Décrire vos données

## 1. Le principe

**Kovex ne connaît pas vos colonnes.** Il ne suppose ni leur nom, ni leur ordre,
ni leur nombre. Vous lui indiquez seulement, pour chaque fichier, quelles
colonnes portent les identifiants qui relient les fichiers entre eux. Tout le
reste est conservé et exploité sans être nommé.

C'est ce qui permet de brancher le produit sur un extrait d'annuaire quelconque
sans le renommer, et c'est vérifié par les tests : le jeu de données de test
utilise volontairement `matricule` et `code_droit` là où le produit manipule
en interne `ID_utilisateur` et `ID_droit`.

## 2. Les quatre fichiers

    identités ──(ID utilisateur)── habilitations ──(ID droit)── droits ──(ID application)── applications

| Fichier | Une ligne = | Colonnes à désigner |
|---|---|---|
| **identités** | une personne | `id_column` |
| **habilitations** | un couple (personne, droit) | `user_id_column`, `right_id_column` |
| **droits** | un droit du référentiel | `id_column`, `app_id_column` |
| **applications** | une application | `id_column` |

Formats : CSV, séparateur et encodage au choix, déclarés par fichier.

## 3. Le fichier de configuration

`workspaces/<ID>/config.json` :

```json
{
    "files": {
        "identities": {
            "path": "workspaces/CLIENT/data/identites.csv",
            "delimiter": ";",
            "encoding": "utf-8",
            "id_column": "matricule"
        },
        "habs": {
            "path": "workspaces/CLIENT/data/habilitations.csv",
            "delimiter": ";",
            "encoding": "utf-8",
            "user_id_column": "matricule",
            "right_id_column": "code_droit"
        },
        "rights": {
            "path": "workspaces/CLIENT/data/droits.csv",
            "delimiter": ";",
            "encoding": "utf-8",
            "id_column": "code_droit",
            "app_id_column": "code_application"
        },
        "applications": {
            "path": "workspaces/CLIENT/data/applications.csv",
            "delimiter": ";",
            "encoding": "utf-8",
            "id_column": "code_application"
        }
    },

    "mining_min_users": 5,
    "mining_min_rights": 2,
    "mining_attribute_max_cardinality_ratio": 0.5,
    "health_threshold_alert": 10.0,
    "health_threshold_critical": 50.0
}
```

Les chemins sont relatifs à la racine de l'application.

## 4. Les colonnes que vous ne déclarez pas

Ce sont les plus utiles.

Toutes les colonnes supplémentaires du fichier d'identités — direction, site,
fonction, statut, date d'entrée… — sont conservées telles quelles et deviennent :

- les **critères candidats du mining métier**. Kovex calcule la cardinalité de
  chacune et signale celles qui restent sous le seuil du workspace comme
  recommandées ; seules une colonne à une valeur par ligne et une colonne
  constante sont écartées, parce qu'elles ne permettent aucun regroupement ;
- le contenu de l'**infobulle d'une identité** dans le graphe des accès, sous
  forme de tableau, dans l'ordre du fichier.

Vous n'avez donc rien à faire pour qu'une colonne RH devienne exploitable :
il suffit qu'elle soit dans le fichier.

## 5. Rattachement d'un droit à son application

Il vient **du référentiel des droits**, par la colonne que vous désignez dans
`rights.app_id_column`. Jamais d'une convention de nommage.

Deux corrections ont été nécessaires sur ce point, et elles disent pourquoi la
règle compte :

- seule une colonne littéralement nommée `ID_application` était reconnue — ce
  qui fonctionnait sur un jeu de données par coïncidence ;
- la couverture applicative était déduite d'un `identifiant.split('_')[1]`,
  après retrait de préfixes propres à un client (`RS_`, `UP_`, `GSH_`).

Si votre référentiel de droits ne porte pas de colonne d'application, le produit
ne l'invente pas : la couverture applicative n'est simplement pas calculée, et
c'est signalé.

## 6. Qualité des données

Le chargeur produit un état de nettoyage et un score de santé, consultables au
tableau de bord et dans `GET /api/v1/reports/cleaning` :

- **droits orphelins** — présents dans les habilitations, absents du référentiel
  des droits ;
- **identités orphelines** — présentes dans les habilitations, absentes du
  référentiel des identités ;
- **identités hors périmètre** — présentes dans le référentiel, sans aucune
  habilitation.

Le score est `100 − taux d'anomalies`, le taux étant le total de ces anomalies
rapporté au nombre d'identités. L'étiquette (*sain* / *alerte* / *critique*)
dépend des deux seuils du workspace.

Ces anomalies ne bloquent pas le mining, mais elles le dégradent : une identité
orpheline crée une signature parasite, un droit orphelin ne peut pas être
rattaché à une application.

## 7. Ce que la forme de vos données implique pour le mining

Le tableau de bord affiche la **distribution du nombre de droits par identité**.
Ce n'est pas un graphique décoratif : c'est la mesure qui prédit ce que le
mining pourra faire.

- **Distribution resserrée** — beaucoup d'identités détiennent le même nombre de
  droits, souvent les mêmes : les signatures se répètent, le mode exact trouve
  déjà des rôles.
- **Distribution étalée, longue traîne** — chaque identité a son propre paquet :
  peu de signatures partagées, le mode exact ne trouve presque rien, et le mode
  approché avec un θ adapté devient indispensable.
- **Beaucoup d'identités à zéro droit** — comptes inactifs ou périmètre mal
  découpé. Ils ne gênent pas le mining, mais ils faussent tout ratio rapporté au
  nombre d'identités, score de santé compris.

Ce graphique remplace une courbe d'« activité des habilitations » sur 7, 30 ou
90 jours qui était alimentée par des valeurs aléatoires tirées dans le
navigateur. Un référentiel est un instantané : il ne porte aucune dimension
temporelle, aucune activité ne pouvait en être tirée.
