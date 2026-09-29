# Manuel de l'administrateur

Ce manuel s'adresse à la personne qui installe, configure et exploite Kovex.

## Contrainte de conception

Kovex est prévu pour tourner **entièrement en local, sur un serveur sans accès
sortant**. Aucune fonction n'appelle un service externe. Cela a deux
conséquences : les dépendances doivent être installées avant l'isolement du
serveur, et rien dans le produit ne « se met à jour tout seul ».

## Installation

1. Python 3.11 ou plus récent.
2. `pip install -r requirements.lock` — **sur une machine ayant accès au
   réseau**, ou depuis un dépôt de paquets interne. Sur le serveur isolé,
   cette commande échoue faute de réseau ; utilisez alors
   `pip install --no-index --find-links <dossier> -r requirements.lock`.
   `requirements.lock` fige les versions exactes que la suite de tests a
   exécutées ; `requirements.txt` ne porte que des bornes basses et sert au
   développement.
3. Copier `.env.example` vers `.env`. `START_KOVEX.bat` le crée
   automatiquement s'il est absent, avec une clé de signature tirée au hasard.
4. Lancer `START_KOVEX.bat`. `STOP_KOVEX.bat` arrête les deux serveurs.

## Lancer sans le script

Le script Windows ne fait qu'enchaîner deux commandes. Sur un autre système,
ou pour lancer les deux moitiés séparément :

```
python run_api.py            # API,       http://127.0.0.1:8000
python serve_frontend.py     # interface, http://127.0.0.1:3000
```

Les deux doivent tourner en même temps, dans deux terminaux. Ports et adresses
se règlent par `KOVEX_API_PORT`, `KOVEX_API_HOST`, `KOVEX_FRONTEND_PORT`,
`KOVEX_FRONTEND_HOST`.

`serve_frontend.py` n'est pas un simple serveur de fichiers : il sert
l'interface avec `Cache-Control: no-store`. Sans cela, le navigateur resert un
`index.html` en cache après une mise à jour, et l'interface reste à l'ancienne
version alors que le correctif est bien déployé — ce qui fait chercher la
panne au mauvais endroit.

Au premier démarrage, un compte administrateur est créé avec un **mot de passe
aléatoire affiché une seule fois** dans la console de l'API. Notez-le. Il n'y a
pas de compte par défaut, et c'est volontaire : un mot de passe par défaut dans
un produit de gouvernance des identités est une contradiction.

## Configuration

Tout se règle par variables d'environnement dans `.env`. Le détail de chacune
figure dans `docs/02-parametres.md`. Les plus structurantes :

| Variable | Effet |
|---|---|
| `PYGIA_SECRET_KEY` | Clé de signature des jetons. **Unique par installation.** Une clé partagée permet de fabriquer un jeton administrateur valide ailleurs. |
| `PYGIA_ENV` | `production` refuse au démarrage les combinaisons dangereuses. |
| `PYGIA_AUTH_DISABLED` | Désactive l'authentification. Refusé en production. Ne jamais activer sur une instance servie. |
| `PYGIA_RATE_LIMIT` | Limitation de débit. La désactiver retire le seul frein à une attaque par force brute sur la connexion. |
| `PYGIA_ALLOWED_ORIGINS` | Origines autorisées par le CORS. |
| `PYGIA_AUDIT_FILE` | Emplacement de la piste d'audit. |

## Workspaces

Un workspace isole les données, la configuration et la base de connaissances
d'un client ou d'un environnement. Créer un workspace crée son arborescence ;
le supprimer archive sa base de connaissances avant d'effacer le reste.

La piste d'audit, elle, vit **hors des workspaces**. Supprimer un workspace ne
doit pas effacer l'historique des décisions prises dessus.

## Thèmes visuels

L'application s'ouvre aux couleurs du produit. Un workspace peut porter celles
de son client : un **thème** est un dossier déposé sous `themes/`, dans le
dossier du workspace, contenant un fichier `theme.json` et, si on le souhaite,
un logo.

```
workspaces/<workspace>/themes/<nom-du-theme>/theme.json
workspaces/<workspace>/themes/<nom-du-theme>/logo.png
```

Un thème peut aussi être déposé **pour toute l'installation**, et il est alors
proposé à tous les workspaces — un cabinet qui ouvre un dossier par client
dépose sa marque une fois :

```
config/themes/<nom-du-theme>/theme.json
config/themes/<nom-du-theme>/logo.png
```

Les deux dépôts se cumulent. À nom égal, **celui du workspace gagne** : un
dossier client peut corriger le thème maison sans que personne ne touche à
l'installation. Le format, les contrôles et les refus sont les mêmes des deux
côtés.

Le fichier déclare ses libellés par langue, ses couleurs par variante
d'affichage, et le nom de son logo :

```json
{
  "libelles": { "fr": "Nom affiché", "en": "Displayed name", "de": "Angezeigter Name" },
  "logo": "logo.png",
  "variantes": {
    "dark":  { "accent-primary": "#6d28d9", "encre-primary": "#c4b5fd" },
    "light": { "accent-primary": "#5b21b6", "encre-primary": "#5b21b6" }
  }
}
```

Trois règles, et le refus dit toujours laquelle a manqué :

- **Les deux variantes sont exigées**, avec les mêmes jetons de part et
  d'autre. Un thème qui n'habillerait que l'affichage sombre laisserait le
  clair aux couleurs du produit, et l'écran changerait d'identité selon un
  réglage personnel.
- **Seuls les jetons de couleur de la feuille de style sont redéfinissables**,
  avec une valeur hexadécimale à six chiffres. Un dégradé, un voile
  translucide ou un mélange calculé restent hors de portée : les remplacer par
  une couleur pleine casserait l'effet qu'ils produisent.
- **Le contraste est recalculé** sur la palette obtenue, selon le même contrat
  WCAG AA que la palette d'origine. Un thème qui rend un texte illisible est
  refusé, et le motif nomme la paire fautive avec son rapport.

Le logo est jugé sur ses octets et non sur son nom. Les formats acceptés sont
PNG, JPEG et WebP ; le format vectoriel ne l'est pas, car un SVG est un
document qui peut porter du script et serait servi depuis l'origine de
l'application.

Un gabarit prêt à copier est livré avec le produit, dans
`docs/exemples/theme-exemple/`. Ses couleurs ne sont celles de personne : le
produit n'embarque aucune marque tierce, et celles d'un client se déposent sur
l'installation qui en a besoin.

Le thème se choisit depuis la carte du workspace, écran **Workspaces**, une
fois le dossier déposé — jamais à la création, où le dossier du workspace vient
d'être créé et ne contient encore rien. Les dépôts refusés y sont listés avec
leur motif : un fichier mal placé ne disparaît pas en silence.

Les couleurs et les logos d'un client ne sont pas livrés avec le produit. Ils
sont déposés sur l'installation qui en a besoin.

## Associer les colonnes des fichiers sources

Kovex ne présuppose aucun nom de colonne. Quatre fichiers CSV sont attendus :
identités, applications, droits, habilitations. Pour chacun, la configuration
indique quelle colonne porte quel identifiant.

Ce qui doit impérativement être renseigné :

- identités : la colonne de l'identifiant de personne ;
- droits : la colonne de l'identifiant de droit, et celle de l'application de
  rattachement ;
- applications : la colonne de l'identifiant d'application ;
- habilitations : les deux colonnes reliant une personne à un droit.

Une colonne non associée n'est pas une erreur : les contrôles qui en dépendent
sont simplement déclarés indisponibles, et l'écran de qualité l'affiche « — »
plutôt que zéro.

Le séparateur et l'encodage sont réglables par fichier. En cas de doute sur un
export Windows, `;` et `utf-8` sont les valeurs les plus courantes.

**Le plus simple est de tout déclarer au chargement.** Dans la fenêtre d'import,
le bouton « Vérifier les fichiers » lit le début de chaque fichier choisi et
affiche ce qu'il y a vu : l'encodage qui le décode, le séparateur qui le découpe
régulièrement, les noms de colonnes et quelques lignes. Les listes ne proposent
alors que des colonnes qui existent réellement, et votre choix est écrit dans la
configuration du workspace.

Une colonne déclarée que le fichier ne contient pas fait **refuser** le
chargement, en la nommant, et le référentiel en place n'est pas remplacé.
C'était le défaut le plus coûteux : le chargeur ne renomme que les colonnes
qu'il trouve et se tait sur les autres, si bien qu'un fichier de onze mille
identités se chargeait sans erreur et affichait zéro identité.

## Comptes et rôles

Trois rôles, avec des permissions fixes :

| Rôle | Permissions |
|---|---|
| `admin` | lecture, écriture, suppression, administration, mining, rôles |
| `analyst` | lecture, écriture, mining, rôles |
| `viewer` | lecture |

Trois rôles, mais **un seul compte à l'installation**. Le premier démarrage
crée `admin`, et rien d'autre : les comptes de démonstration et leurs mots de
passe ont été retirés du code, où ils rendaient toute installation calculable
hors ligne. Il n'existe donc aucun mot de passe par défaut.

- En production, le mot de passe initial est fourni par la variable
  `PYGIA_BOOTSTRAP_ADMIN_PASSWORD`. Sans elle, aucun compte n'est créé et
  personne ne se connecte : l'installation reste fermée plutôt que d'être
  ouverte par un identifiant connu de tous.
- En développement, si la variable est absente, un mot de passe aléatoire est
  tiré et **journalisé une seule fois**, au démarrage, en niveau
  avertissement. Il n'est jamais réaffiché.

Si ce mot de passe a été perdu — la ligne défile vite au premier démarrage —
il n'y a rien à réparer : supprimer `config/users.json`, renseigner
`PYGIA_BOOTSTRAP_ADMIN_PASSWORD`, redémarrer. Le compte est recréé avec ce
mot de passe. Le fichier ne contient que des empreintes ; le supprimer ne perd
aucune donnée de gouvernance.

La lecture de la **piste d'audit exige `admin`**. Un compte qui peut être
audité ne décide pas de ce que l'audit montre.

Le contrôle d'accès fonctionne par **refus par défaut** : une route non
déclarée dans la politique est refusée, pas ouverte. Ajouter un point d'entrée
sans le déclarer le rend inaccessible — c'est le comportement voulu.

## Piste d'audit

La piste consigne les décisions de gouvernance : validation et rejet de rôle,
lancement de mining avec ses paramètres, export, changement de configuration,
création et suppression de workspace.

Trois propriétés à connaître :

- **Elle n'est jamais réécrite.** Chaque décision est une ligne ajoutée. Aucune
  route de l'API ne permet d'en retirer une.
- **Elle est chaînée.** Chaque entrée porte l'empreinte de la précédente.
  Modifier ou supprimer une ligne rompt la chaîne, et l'écran le signale en
  désignant l'entrée fautive. Cela ne rend pas la falsification impossible —
  rien ne le peut sur un fichier accessible — cela la rend **détectable**.
- **Elle ne tourne pas.** Elle grossit. Incluez-la dans la sauvegarde, et
  excluez-la de tout nettoyage automatique.

Vérifiez l'intégrité périodiquement : l'écran affiche le constat à chaque
ouverture, sans action de votre part.

## Sauvegarde

À sauvegarder :

- `workspaces/` — données, configuration et bases de connaissances ;
- le fichier de piste d'audit ;
- `config/` — comptes et catalogues de traduction ;
- `.env` — **contient la clé de signature**. Sa perte invalide tous les jetons
  émis ; sa divulgation permet d'en fabriquer.

À ne pas sauvegarder : `output/`, régénérable.

## Diagnostic

**L'application répond 403 sur une route.** La route n'est pas déclarée dans la
politique d'accès, ou le compte n'a pas la permission. Le journal du serveur
nomme la route à déclarer.

**Le mining ne trouve aucun rôle.** Vérifiez d'abord le nombre
d'habilitations exploitables dans l'onglet Qualité. Une matrice vide produit
zéro rôle sans lever d'erreur.

**Un contrôle de qualité affiche « — ».** La colonne correspondante n'est pas
associée dans la configuration du workspace.

**Les modifications du frontend ne s'appliquent pas.** Le navigateur sert une
version en cache. Les ressources portent un numéro de version dans leur URL ;
un rechargement forcé suffit.

**La piste d'audit est déclarée rompue.** Le fichier a été modifié hors de
l'application. L'écran désigne l'entrée à partir de laquelle l'historique
n'est plus opposable. Conservez le fichier en l'état : c'est une preuve.
