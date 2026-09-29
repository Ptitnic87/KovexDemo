# 02 — Les paramètres

Trois familles, dans trois endroits différents, avec trois durées de vie
différentes :

| Famille | Où | Portée | Modifiable par |
|---|---|---|---|
| **Variables d'environnement** | environnement du processus | l'installation entière | l'exploitant, au démarrage |
| **Configuration de workspace** | `workspaces/<ID>/config.json` | un jeu de données | un administrateur, dans l'application |
| **Paramètres d'exécution** | corps de la requête | une exécution | l'analyste, à chaque lancement |

Règle générale : **plus le paramètre engage un choix métier, plus il est près de
l'utilisateur.** Aucun seuil métier n'a de valeur par défaut côté serveur ; une
requête qui n'en fournit pas est refusée.

---

## 1. Variables d'environnement

Elles se placent dans un fichier `.env` à la racine (gabarit :
`.env.example`) ou dans l'environnement du service.

### `PYGIA_ENV`

- **Valeurs** : `development` (défaut) | `production`
- **Effet** : en `production`, l'application refuse de démarrer si
  `PYGIA_SECRET_KEY` est absente ou si `PYGIA_AUTH_DISABLED=true` ; la
  documentation interactive (`/api/docs`, `/openapi.json`) est fermée ; aucun
  compte n'est créé automatiquement.
- **À régler** : `production` sur le serveur du client. Toujours.

### `PYGIA_SECRET_KEY`

- **Valeurs** : chaîne aléatoire, 32 octets minimum.
- **Effet** : clé de signature des jetons JWT. Qui la possède peut fabriquer un
  jeton administrateur valide.
- **Comportement** : obligatoire en production, le démarrage échoue sans elle.
  En développement, une clé éphémère est générée à chaque démarrage, avec un
  avertissement — les sessions ne survivent donc pas à un redémarrage.
- **À régler** : générer une valeur propre à l'installation, par exemple
  `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Une clé ayant
  transité par un dépôt Git est compromise et doit être régénérée.

### `PYGIA_AUTH_DISABLED`

- **Valeurs** : `false` (défaut) | `true`
- **Effet** : `true` désactive entièrement l'authentification. **Refusé en
  production** : le démarrage échoue.
- **À régler** : ne l'utiliser qu'en développement local, jamais ailleurs.

### `PYGIA_BOOTSTRAP_ADMIN_PASSWORD`

- **Valeurs** : mot de passe initial de l'administrateur.
- **Effet** : à la toute première initialisation, si aucun fichier d'utilisateurs
  n'existe, crée le compte administrateur avec ce mot de passe. Sans elle en
  production, **aucun compte n'est créé** : l'installation reste fermée plutôt
  qu'ouverte par un identifiant connu de tous. En développement, un compte est
  créé avec un mot de passe aléatoire journalisé une seule fois.
- **À régler** : le temps de la première connexion, puis retirer la variable et
  changer le mot de passe depuis l'application.

### `PYGIA_ALLOWED_ORIGINS`

- **Valeurs** : liste d'origines séparées par des virgules.
- **Effet** : origines acceptées par le contrôle CORS du navigateur.
- **À régler** : l'URL exacte par laquelle vos utilisateurs atteignent
  l'application. Sur un poste isolé où frontend et backend partagent l'origine,
  la question ne se pose pas.

### `PYGIA_RATE_LIMIT`

- **Valeurs** : `true` (défaut) | `false`
- **Effet** : limite le débit des requêtes, par client et par famille
  d'endpoints : 5 tentatives de connexion par minute, 10 minings par minute,
  5 exports par 5 minutes, 60 requêtes par minute pour le reste.
- **À régler** : laisser activé. La désactiver retire le seul frein à une
  attaque par force brute sur `/auth/login` ; le journal le rappelle au
  démarrage quand c'est le cas.

## Périmètre de lecture des fichiers sources

### `base_autorisee`

Ce réglage n'est **pas** une clé du `config.json` : il est imposé par le
serveur, qui le fixe au dossier du workspace actif. Il figure ici parce qu'il
détermine ce que le produit accepte de lire.

Les chemins des fichiers sources vivent dans la configuration du workspace, que
l'API laisse modifier. Sans borne, y inscrire le fichier `.env` puis consulter
l'explorateur rendait le contenu de ce fichier — donc la clé de signature des
jetons — par une réponse d'API parfaitement normale. Avec cette clé, on
fabrique un jeton administrateur valide, indéfiniment.

Deux barrières s'appliquent désormais :

1. `PUT /workspaces/{id}/config` refuse (422) toute configuration dont un
   chemin de fichier source, une fois résolu, sort du dossier du workspace.
   La résolution est indispensable : `..`, un chemin absolu et un lien
   symbolique doivent être ramenés à leur destination réelle avant d'être
   comparés.
2. Le chargeur refuse de lire un fichier hors de ce périmètre, même si la
   configuration a été modifiée à la main sur le serveur ou est arrivée par
   l'import d'un workspace.

Un chemin vide reste licite : il signifie « fichier non configuré ».

### `KOVEX_SESSION_MAX_MINUTES`

Durée maximale d'une session, renouvellements compris. Défaut : 480 minutes.

`/auth/refresh` reconduit l'instant de **connexion initiale**, il ne le remet
pas à zéro. Sans ce report, la chaîne de renouvellements prolongeait un jeton
volé indéfiniment : chaque appel repoussait l'échéance, et rien n'y mettait
jamais fin.

**Révocation.** Chaque compte porte un numéro de version inscrit dans ses
jetons. Changer le mot de passe l'incrémente, ce qui invalide instantanément
tous les jetons déjà distribués à ce compte — c'est ce qui rend un changement
de mot de passe réellement protecteur. `UserManager.revoquer_jetons()` permet
de le faire sans changer le mot de passe.

Le mécanisme survit à un redémarrage, contrairement à une liste de révocation
tenue en mémoire, et n'affecte que le compte visé. Un jeton émis avant cette
mise à jour vaut la version 1 : les sessions en cours ne sont pas coupées, elles
expirent naturellement.

### `PYGIA_AUDIT_FILE`

Emplacement du fichier de piste d'audit. Vide : `audit/audit.jsonl` à la racine.

La piste consigne les décisions de gouvernance — validation et rejet de rôle,
lancement de mining, export, changement de configuration, création et
suppression de workspace. Elle est délibérément **hors des workspaces** :
supprimer un workspace ne doit pas effacer l'historique des décisions prises
dessus, précisément parce que c'est à ce moment-là qu'il compte.

Le fichier n'est jamais réécrit, seulement complété, et chaque ligne porte
l'empreinte de la précédente. Modifier ou retirer une ligne rompt le chaînage
et la vérification d'intégrité le signale en désignant l'entrée fautive. Cela
n'empêche pas la falsification d'un fichier accessible en écriture — rien ne
l'empêche —, cela la rend détectable, ce qu'un auditeur exige.

Conséquence d'exploitation : ce fichier ne tourne pas et ne se purge pas. Il
grossit. Prévoyez-le dans la sauvegarde, et **pas** dans un nettoyage
automatique.

### Les deux préfixes

Le produit s'appelait PyGIA et s'appelle Kovex. Le changement de nom a été
décidé « visible uniquement » : les variables existantes gardent `PYGIA_`, pour
ne casser aucune installation. Les réglages ajoutés depuis portent `KOVEX_`.

**Les deux préfixes sont acceptés partout.** `KOVEX_` l'emporte si les deux sont
définis. Ce document nomme chaque réglage sous son préfixe recommandé ; l'autre
fonctionne à l'identique.

---

### `PYGIA_LOG_LEVEL`, `PYGIA_LOG_FORMAT`, `PYGIA_LOG_FILE`

- **Valeurs** : niveau `INFO` (défaut) / `DEBUG` / `WARNING`… ; format `text`
  (défaut) ou `json` ; chemin du fichier, `logs/kovex.log` par défaut — une
  valeur vide désactive l'écriture dans un fichier.
- **Effet** : journalisation. Le format `json` convient à une collecte
  automatisée ; **le fichier est toujours écrit en JSON**, quel que soit le
  format de la console : un journal d'incident se relit avec un outil.
- **À régler** : `INFO` en exploitation. `DEBUG` produit un volume important et
  détaille les paramètres de chaque mining.

Le fichier est écrit par défaut parce que plusieurs refus du produit renvoient
l'exploitant vers « le journal du serveur ». Sur un serveur isolé, la sortie
standard n'est lue par personne et disparaît à l'arrêt.

### `PYGIA_LOG_MAX_BYTES`, `PYGIA_LOG_BACKUPS`

- **Valeurs** : taille en octets (10 Mo par défaut) ; nombre d'archives
  conservées (5 par défaut).
- **Effet** : rotation du journal. Au-delà de la taille, le fichier est archivé
  et un nouveau commence ; au-delà du nombre d'archives, la plus ancienne est
  effacée.
- **À régler** : les défauts plafonnent le journal à environ 60 Mo. Sur un
  serveur isolé, un journal en ajout continu finit par remplir le disque, et
  c'est le produit qui s'arrête.

---

### `KOVEX_API_HOST`, `KOVEX_API_PORT`, `KOVEX_API_RELOAD`

- **Valeurs** : hôte (`127.0.0.1` par défaut), port (`8000`), rechargement
  automatique (`false`).
- **Effet** : écoute de l'API, lue par `run_api.py`.
- **À régler** : laisser `127.0.0.1` sauf si l'interface est servie depuis une
  autre machine. Le rechargement automatique ne s'active qu'en développement.

### `KOVEX_API_URL`

- **Valeur** : adresse complète de l'API, préfixe compris —
  `http://10.0.0.5:8000/api/v1`. Vide par défaut.
- **Effet** : `serve_frontend.py` la reporte dans la balise
  `<meta name="kovex-api-url">` du gabarit à chaque envoi de la page.
  L'interface la lit au chargement.
- **Pourquoi** : l'adresse était écrite dans `frontend/js/config.js`. Déplacer
  l'API sur un autre hôte ou un autre port obligeait à modifier un fichier
  livré, et rien ne le signalait : l'interface se contentait de ne plus
  répondre.
- **Laissée vide** : le gabarit garde la valeur qu'il porte. Derrière un
  relais qui expose l'API et l'interface sous le même hôte, videz la balise
  du gabarit : l'interface vise alors `<origine de la page>/api/v1`.
- **À ne pas oublier** : l'origine de l'interface doit figurer dans
  `PYGIA_ALLOWED_ORIGINS`, sans quoi le navigateur refusera les appels.

### `KOVEX_FRONTEND_HOST`, `KOVEX_FRONTEND_PORT`

- **Valeurs** : hôte (`127.0.0.1`), port (`3000`).
- **Effet** : écoute du serveur d'interface, lue par `serve_frontend.py`.

### `KOVEX_CORS_MAX_AGE`

- **Valeur** : durée en secondes pendant laquelle un navigateur garde en cache
  la réponse à une requête préparatoire CORS.
- **Effet** : moins de requêtes préparatoires. Une valeur élevée retarde la
  prise en compte d'un changement d'origine autorisée.

### `KOVEX_PBKDF2_ITERATIONS`

- **Valeur** : nombre d'itérations du hachage des mots de passe. **480 000**
  par défaut, la recommandation OWASP.
- **Effet** : coût d'un hachage, donc coût d'une attaque hors ligne sur le
  fichier des comptes.
- **À régler** : ne pas abaisser en exploitation. La suite de tests l'abaisse
  pour elle-même, et deux tests vérifient que le défaut livré n'a pas bougé.

### `KOVEX_JOURNAL_LENTEUR_MS`

- **Valeur** : durée à partir de laquelle une requête est consignée comme lente,
  en millisecondes (1 000 par défaut).
- **Effet** : toute requête plus longue laisse une ligne dans le journal, avec
  sa méthode, son chemin et sa durée. Chaque réponse porte par ailleurs sa durée
  dans l'en-tête `X-Duree-Ms`, que l'écran lit pour distinguer le temps du
  serveur de celui de l'affichage.
- **À régler** : l'abaisser sur une machine lente ou pendant une recherche de
  cause ; le remonter si le journal devient illisible. Ce n'est pas un seuil
  d'alerte, c'est la limite au-delà de laquelle un utilisateur commence à
  attendre — et une lenteur dont personne ne garde trace est une lenteur que
  personne ne corrige.

### `KOVEX_IMPORT_MAX_BYTES`

- **Valeur** : taille maximale d'un fichier importé dans un workspace
  (512 Mo par défaut).
- **Effet** : borne ce qu'un compte autorisé peut déposer. Sans elle, un
  import épuise le disque ou la mémoire du serveur.

### Débits : `KOVEX_RATE_*`

Une variable par famille pour le nombre de requêtes, et son homologue `_PER`
pour la fenêtre en secondes :

| Famille | Requêtes | Fenêtre | Défaut |
|---|---|---|---|
| Par défaut | `KOVEX_RATE_DEFAULT` | `KOVEX_RATE_DEFAULT_PER` | 120 / 60 s |
| Authentification | `KOVEX_RATE_AUTH` | `KOVEX_RATE_AUTH_PER` | 5 / 60 s |
| Mining | `KOVEX_RATE_MINING` | `KOVEX_RATE_MINING_PER` | 10 / 60 s |
| Assistance | `KOVEX_RATE_ASSISTANCE` | `KOVEX_RATE_ASSISTANCE_PER` | 60 / 60 s |
| Export | `KOVEX_RATE_EXPORT` | `KOVEX_RATE_EXPORT_PER` | 5 / 300 s |
| Lecture | `KOVEX_RATE_READ` | `KOVEX_RATE_READ_PER` | 600 / 60 s |
- **Effet** : débit autorisé par famille de routes, par client.
- **À régler** : la lecture est volontairement large — l'écran de cartographie
  interroge quatre colonnes à chaque sélection, et un débit calculé pour une
  navigation page par page bloque une interface qui rayonne.

**Assistance et mining ne sont pas la même famille**, et les confondre a coûté.
Poser une question à un modèle n'est pas lancer un calcul : le nommage en lot
envoie une demande par rôle candidat, à la file. Sur un poste réel, ces
demandes tombaient dans le seau du mining — dix par minute — et six cents
étaient refusées d'affilée, l'écran annonçant « sans réponse du modèle » alors
que le modèle n'avait rien reçu. Le vrai régulateur de ce flux est le modèle
lui-même, qui répond à une question à la fois ; le seau ne borne qu'un client
emballé.

**La famille d'une route se décide par le motif le plus précis**, jamais par
l'ordre de déclaration. Ce fichier a connu trois fois le même défaut — `/auth/`
attrapant `/auth/me`, `api_read` déclaré et inatteignable, `/mining` attrapant
`/mining/suggest-name` — et à chaque fois parce qu'un motif général était écrit
avant un motif précis. L'ordre d'écriture ne dit rien de ce qu'une route coûte.

**Un refus de débit ne rend aucune phrase** : il rend le code `error.rate_limited`,
ses paramètres, `retry_after`, et l'en-tête HTTP standard `Retry-After`. Un
client qui se cale sur le débit — la file de nommage en lot le fait — attend le
délai annoncé et reprend la ligne au lieu de la perdre.

---

## 2. Configuration de workspace

Un **workspace** est un jeu de données isolé : ses fichiers, sa configuration,
sa Knowledge Base. On en crée un par client, ou par environnement.

Fichier : `workspaces/<ID>/config.json`. Il porte la description des fichiers
(voir [05 — Données](05-donnees.md)) et les réglages ci-dessous.

### `mining_min_users`

- **Domaine** : entier ≥ 2. Livré à 5.
- **Effet** : effectif minimal d'un rôle. En dessous, le candidat est écarté.
- **Comment le régler** : un rôle à 2 personnes n'est pas un rôle, c'est une
  coïncidence. Un rôle à 50 personnes ne se trouve que dans les grandes
  populations homogènes. Commencez haut pour voir les rôles structurants,
  descendez pour les rôles de niche.

### `mining_min_rights`

- **Domaine** : entier ≥ 1. Livré à 2.
- **Effet** : nombre minimal de droits d'un rôle.
- **Comment le régler** : à 1, tout droit un peu partagé devient un « rôle » —
  bruit garanti. À 2 ou 3, on ne retient que ce qui ressemble à un paquet.

### `mining_attribute_max_cardinality_ratio`

- **Domaine** : réel dans ]0 ; 1]. Livré à 0,5.
- **Effet** : au-delà de ce rapport (valeurs distinctes / nombre d'identités),
  un attribut est signalé comme trop discriminant pour porter un rôle métier.
  **C'est un signalement, pas un filtre** : l'attribut reste proposé, il perd
  seulement son drapeau « recommandé ».
- **Comment le régler** : 0,5 signifie « une valeur pour deux identités, c'est
  déjà trop fin ». Un référentiel très segmenté (beaucoup de petites entités)
  supporte un ratio plus élevé.

### `mining_profils_croises_max`

- **Domaine** : entier ≥ 0. Livré à 20 000.
- **Effet** : nombre de profils distincts au-delà duquel le croisement des
  profils (générateur `intersection`, § 3.1) porte sur un **échantillon
  régulier** de cette taille au lieu de tous les profils. L'interface annonce
  alors que le croisement a été restreint, et que la couverture obtenue est
  inférieure à celle d'un croisement complet.
- **Comment le régler** : ce n'est pas un choix métier, c'est la limite
  au-delà de laquelle l'écran cesserait de répondre. Le croisement compare les
  profils deux à deux : son coût croît comme le **carré** de leur nombre —
  mille profils font un demi-million de paires, vingt mille en font deux cents
  millions. Un profil, ici, est un ensemble de droits distinct : un
  référentiel de 20 000 identités en compte typiquement beaucoup moins, la
  plupart des gens en partageant un. Monter la borne cherche plus de rôles et
  allonge le calcul ; `0` ne croise jamais.
- **Ce que le produit ne fait pas** : rendre moins de rôles en silence. Un
  croisement restreint est annoncé à côté du résultat, parce qu'une couverture
  obtenue sur un échantillon n'est pas celle qu'on aurait eue.
- **Pourquoi un échantillon plutôt qu'un abandon** : au-dessus de la borne, le
  croisement était purement et simplement annulé — sur un référentiel de
  20 000 identités portant 11 534 profils distincts, il ne tournait donc
  jamais, et le générateur `intersection` n'apportait rien. Un échantillon
  régulier est arbitraire et le document le dit ; il est reproductible, et il
  rend des rôles. Mesuré sur le jeu de démonstration : 1 362 rôles / 87,54 %
  de couverture sans croisement, 711 rôles / 89,66 % avec — moins de rôles,
  plus de couverture, zéro sur-octroi dans les deux cas.

### `mining_treillis_max`

- **Domaine** : entier ≥ 0. Livré à 20 000.
- **Effet** : nombre maximal de rôles candidats que le générateur `treillis`
  (§ 3.1) peut ajouter. Il ne joue que si cette façon de chercher est cochée.
  Atteint avant la fin de l'exploration, le résultat l'annonce : le modèle
  n'est alors pas forcément le plus petit que les données admettent.
- **Comment le régler** : ce n'est pas un choix métier, c'est la mémoire et le
  temps qu'on accepte de payer. Le nombre d'ensembles obtenus en recroisant les
  profils n'a pas de borne utile : 2 762 sur le jeu HP Americas small
  (1,6 s), plus que la mémoire d'un poste sur Americas large. Vingt mille
  couvre largement les 920 ajouts qu'il faut à Americas small pour atteindre
  son optimum publié. `0` ne recroise jamais.
- **Ce que le produit ne fait pas** : présenter un treillis partiel comme
  complet. La borne atteinte est dite à côté du résultat et sur chaque point de
  la courbe des seuils.

### `mining_apport_minimal`

- **Domaine** : entier ≥ 1. Livré à 1, c'est-à-dire **aucun plancher** — le
  comportement historique, gardé par défaut pour qu'aucun référentiel ne
  change de résultat à la mise à jour.
- **Effet** : nombre d'habilitations non encore couvertes qu'un rôle doit
  apporter pour être retenu par le glouton. `mining_min_users` et
  `mining_min_rights` disent quelle **taille** un rôle doit avoir ; celui-ci
  dit ce qu'il doit **expliquer**.
- **Pourquoi** : rien ne le disait, et le glouton retenait donc tout candidat
  apportant au moins une habilitation, jusqu'au plafond de rôles. Mesuré sur
  le banc de performance — six mille identités, socles exclus, θ = 1, les
  trois générateurs — les cent trente-sept rôles plantés dans le jeu
  apportent **140 à 150** habilitations chacun, et les deux cent
  cinquante-trois suivants en apportent **6, 4, 3, 2 ou 1**. Le modèle passait
  de 137 à 390 rôles pour 1,15 point de couverture.
- **Comment le régler** : sur la courbe des apports du référentiel, pas sur
  une règle générale. Une valeur entre les deux paliers sépare les rôles des
  fragments ; une valeur trop haute écarte des rôles légitimes et la
  couverture le dit.
- **Ce que le produit ne fait pas** : écarter en silence. Le nombre de
  candidats écartés faute d'apport est rendu dans les statistiques du moteur
  et affiché à côté du résultat — sans lui, un modèle réduit par le plancher
  se lirait comme un référentiel qui ne porte que cela.

### `mining_selection`, `mining_selection_effort` et `mining_selection_delai_s`

- **Domaine** : `mining_selection` vaut `gloutonne` (livré) ou `exacte` ;
  `mining_selection_effort` est un entier ≥ 1, livré à 2 000 ;
  `mining_selection_delai_s` est un nombre de secondes > 0, livré à 120.
- **Effet** : comment les rôles sont choisis parmi les candidats. `gloutonne`
  retient à chaque pas le candidat qui explique le plus d'habilitations encore
  non couvertes. `exacte` repart de ce que le glouton explique et cherche, dans
  tout le vivier, **le plus petit ensemble de rôles qui l'explique aussi**. Le
  calcul est un programme linéaire en nombres entiers, résolu par HiGHS, le
  solveur livré avec scipy. Il ne demande aucune dépendance de plus et aucun
  appel réseau, et c'est le même solveur dans la page que sur un poste.
- **Ce que la sélection exacte garantit** : la même couverture, aucun
  sur-octroi et jamais plus de rôles que le glouton. Si le solveur ne trouve
  pas mieux dans l'effort accordé, le résultat du glouton est gardé, et le
  compte rendu le dit. Elle ne s'applique qu'à θ = 1 ; en dessous, le glouton
  est gardé, avec la mention « non applicable ».
- **L'effort est compté en nœuds, pas en secondes** : deux exécutions sur les
  mêmes données rendent le même modèle, quelle que soit la vitesse de la
  machine. Le délai sert seulement à protéger le serveur. S'il est atteint, le
  compte rendu le signale, parce qu'un arrêt au temps n'est plus reproductible.
- **Pourquoi elle n'est pas livrée par défaut** : moins de rôles ne veut pas
  dire de meilleurs rôles, et c'est mesuré. Sur le banc de vérité terrain
  (600 identités, 15 rôles plantés, 5 % d'omission, 2 % d'exception, θ = 1),
  le glouton retient 181 rôles et retrouve **13** des 15 rôles plantés à
  l'identique. La sélection exacte en retient 149 et n'en retrouve **aucun** :
  sur une donnée bruitée, le plus petit ensemble recoupe les rôles réels avec
  des fragments de bruit. Elle sert donc sur une donnée propre, ou quand on
  veut opposer un nombre de rôles à l'état de l'art.
- **Ce qu'elle rend sur les jeux de référence** : voir `docs/04-validation.md`,
  § 3. Sur les neuf jeux HP, elle atteint l'optimum publié sur huit et le
  prouve sur les candidats, à couverture totale et sans sur-octroi.

### `mining_max_roles_plafond`

- **Domaine** : entier ≥ 1. Livré à 5 000.
- **Effet** : nombre maximal de rôles qu'une demande de mining ou une
  exploration de seuil peut réclamer. Au-delà, la demande est refusée avec le
  plafond et l'endroit où le régler.
- **Comment le régler** : ce n'est pas un choix métier, c'est la borne qui
  protège le serveur d'une demande hors de sa portée. Elle se monte quand le
  référentiel porte plus de rôles candidats que le plafond : l'écran affiche
  sinon, sur chaque point de la courbe d'exploration, un « plafond atteint »
  qui parle d'une limite du produit et se lit comme un fait sur la donnée.
- **Ce que le produit ne fait pas** : imposer cette borne depuis son code. Elle
  y était écrite — 5 000, dans deux déclarations de champ et dans l'attribut
  `max` de la saisie — et l'avertissement « plafond atteint » devenait alors
  indélébile sur tout référentiel plus riche que cela : la seule réponse
  possible était interdite.

### `troncature_bornes`

- **Domaine** : liste d'entiers positifs. Livrée avec les plafonds d'export
  usuels : 1 000, 1 500, 5 000, 10 000, 20 000, 50 000, 65 536, 100 000,
  1 048 576. Une liste vide éteint le contrôle.
- **Effet** : un droit dont le nombre de porteurs tombe **exactement** sur une
  de ces bornes, ou un référentiel dont le nombre de lignes y tombe, est
  signalé en anomalie — l'export a probablement été tronqué à la source.
- **Comment le régler** : ce sont les plafonds des **systèmes sources du
  client**, pas une propriété du produit : pagination d'annuaire, seuil de vue
  de liste, limite de lignes d'un tableur. Retirer une borne que le client
  n'a pas, ajouter celle qu'il a. Une liste vide est un choix légitime sur un
  référentiel exporté sans plafond.
- **Ce que le produit ne fait pas** : corriger. Un compte tombant sur une borne
  peut être une coïncidence — le contrôle signale au niveau `warning`, il ne
  refuse ni le fichier ni le mining.

### `sod_severites`

- **Domaine** : liste de libellés, distincts et non vides, **du plus grave au
  moins grave**. Livrée vide.
- **Effet** : les niveaux qu'une règle de séparation des tâches peut porter
  (§ 3 quater). Les conflits s'affichent la règle la plus grave d'abord. Une
  règle sans niveau, ou dont le niveau a été retiré de la liste, vient après
  toutes les autres.
- **Pourquoi aucune liste n'est livrée** : ce qu'est un risque « critique »
  dépend du client, de son secteur et de son contrôle interne. Une échelle
  livrée par le produit serait appliquée telle quelle, sans que personne ne
  l'ait décidée. Tant que la liste est vide, les règles restent sans niveau, et
  l'écran l'affiche.
- **Ce qui est refusé** : une règle enregistrée avec un niveau absent de la
  liste (`separation.severite_inconnue`). Elle serait triée au fond de l'écran
  sans que personne sache pourquoi.

### `birth_rights_alert_pct`

- **Valeur** : part de la population, en pourcentage. `90.0` par défaut, la
  même que le seuil de détection des droits socles, pour que les deux écrans
  parlent du même chiffre.
- **Effet** : au-delà de cette part, un droit est considéré comme universel.
  S'il n'a pas été exclu, le mining le signale — il ne l'exclut pas d'autorité,
  le choix reste à l'utilisateur.
- **Pourquoi** : un droit détenu par tout le monde n'apporte aucune information
  de regroupement, mais coûte une incrémentation par identité et par candidat.
  Mesuré sur un jeu calibré : **13,6 s contre 1,5 s** pour 20 000 identités,
  soit neuf fois plus lent, pour un résultat de moins bonne qualité. Voir
  `04-validation.md`.

### `sensitive_right_keywords`

- **Valeur** : liste de fragments de nom. **Vide par défaut**, et c'est
  délibéré.
- **Effet** : dans les écrans de validation d'un rôle, un droit dont le nom
  contient l'un de ces fragments porte un signalement visuel. Aucun calcul
  n'en dépend : ni le mining, ni la consolidation, ni les exports.
- **Pourquoi le paramètre existe** : l'interface décidait elle-même qu'un
  droit était sensible si son nom contenait « ADMIN » ou « SUPPRESSION ».
  Cette règle suppose une convention de nommage et une langue, et se trompe
  dans les deux sens : un droit « ADMINistratif » était signalé, un droit
  « DELETE_ALL » ne l'était pas. Seul le client connaît son référentiel.
- **Comment le régler** : les fragments sont comparés sans tenir compte de la
  casse. `ADMIN, SUPPR, ROOT` sur un référentiel francophone ; `ADMIN, DELETE,
  GRANT` sur un référentiel anglophone. Laissé vide, aucun droit n'est
  signalé — ce qui vaut mieux qu'un signalement faux.

### `right_naming_column`, `right_naming_separator` et `right_naming_positions`

Ces trois clés portent la **convention de nommage des droits**, et
`naming_invalide` en porte le refus de lecture.

- **Valeur** : le nom d'une colonne du référentiel des droits où lire, **vide
  par défaut**, ce qui signifie l'identifiant du droit ; un séparateur, **vide
  par défaut** ; et la liste de ce que chaque position nomme, dans l'ordre —
  `application`, `module`, `action`, `objet`, `environnement`, `entite`, ou
  vide pour une position dont le contenu ne se range dans aucun de ces rôles.
- **Effet** : le référentiel des droits gagne une colonne par rôle déclaré,
  nommée `kovex_<rôle>`. Elles s'affichent comme les colonnes du client et
  s'emploient partout où le produit propose des colonnes.
- **Pourquoi le paramètre existe** : `D_SAP_FI_CREATE_VENDOR` porte une
  application, un module, une action et un objet, et le produit ne les lisait
  pas. Un client devant quarante mille identifiants n'a aucun moyen de les lui
  donner à la main.
- **Pourquoi déclarer plutôt que deviner** : un nommage est une **convention**,
  pas un texte à interpréter. Une fois dite, elle s'applique à cent pour cent
  des droits qui la respectent, de façon reproductible, sans qu'aucun modèle
  n'intervienne — et le produit dit combien ne la respectent pas plutôt que de
  leur inventer une valeur. La convention ne peut pas être dans le code : le
  séparateur est un souligné chez l'un et un point chez l'autre, la position de
  l'application est la première ici et la deuxième là, et beaucoup de
  référentiels n'en ont aucune.
- **Comment le régler** : l'écran **découpe et dénombre** avant qu'on déclare
  quoi que ce soit. On donne un séparateur et un nombre de positions, le produit
  montre ce que chacune contient — « position 2 : 61 valeurs distinctes, dont
  SAP 12 400 fois » — et on nomme ensuite. Personne ne connaît sa convention de
  mémoire ; tout le monde la reconnaît en la voyant. La **distribution des
  découpes** est rendue avec le reste, et c'est elle qui dit si le référentiel
  a une convention du tout : trois découpes majoritaires sur quatre mille droits
  se déclarent, douze découpes équiprobables ne se déclarent pas.

Trois choses que le produit ne fait **jamais** :

- **décaler.** Un identifiant qui porte moins de segments que la convention n'en
  déclare ne reçoit aucune valeur dérivée. Prendre les segments dont on dispose
  et les ranger dans les premières positions produirait une application
  crédible et fausse — et une application fausse vaut moins que pas
  d'application. Un identifiant qui en porte **plus** est accepté et le surplus
  ignoré : un référentiel régulier sur ses premières positions et libre sur les
  dernières est le cas le plus fréquent ;
- **écraser une colonne du client.** Les colonnes dérivées portent un nom
  réservé ; si ce nom existe déjà dans le fichier, la dérivation est abandonnée
  entière et l'écran le dit ;
- **se rabattre sur l'identifiant** quand la colonne déclarée manque du fichier
  chargé. Découper une autre colonne que celle déclarée donnerait un résultat
  crédible et faux.

**Un seul endroit où la convention alimente un calcul** plutôt qu'un affichage :
si elle nomme une position `application` et que le référentiel des droits n'a
**pas** de colonne de rattachement, la colonne dérivée en tient lieu — et les
règles de séparation des tâches par application deviennent calculables sur un
référentiel qui ne portait pas d'application. Elle ne prend jamais la place
d'une colonne déclarée à l'import : deux sources pour le même rattachement
finiraient par ne pas dire la même chose du même droit. L'écran annonce lequel
des deux cas s'applique.

**Un rôle mal orthographié arrête la lecture** au lieu d'être écarté. Écarter la
position décalerait toutes les suivantes, et la convention nommerait alors les
mauvaises.

**Le refus est à l'écriture, pas à la lecture.** L'écran de paramétrage refuse
d'enregistrer une convention que le chargeur écarterait — sans quoi le réglage
serait accepté puis ignoré, et rien ne l'indiquerait. Mais une convention déjà
écrite à la main dans le fichier, même illisible, n'empêche pas d'ouvrir cet
écran : c'est le seul endroit d'où la corriger. Le chargeur a la même position,
il signale et ne dérive rien plutôt que de refuser le workspace entier.

### `privileged_account_keywords`, `privileged_account_column` et `privileged_account_place`

Ces trois clés portent le paramètre `privileges` du chargeur — le **marqueur de
comptes à privilèges** —, et `privileges_invalide` en porte le refus de lecture.

- **Valeur** : une liste de fragments d'identifiant, **vide par défaut** ; le
  nom d'une colonne d'identités où les chercher, **vide par défaut**, ce qui
  signifie l'identifiant du compte ; et la place du fragment dans la valeur.
- **Effet** : un compte marqué est signalé **partout où le produit le rend** —
  l'explorateur d'identités, les porteurs d'un rôle validé, les porteurs du
  socle, les tableaux de la fenêtre de validation, le détail d'un conflit de
  séparation, les réponses de l'agent, et l'emplacement de rédaction qui permet
  à une réponse écrite de nommer le compte d'administration d'une personne.
  Aucun calcul n'en dépend : ni le mining, ni la consolidation.
- **Comment il atteint un tableau** : le serveur rend, à côté des lignes, la
  liste des identifiants **de la page** qui portent la marque. Elle est rendue
  à part et non ajoutée comme une colonne : les colonnes viennent du fichier du
  client, et en inventer une écraserait celle qui porterait ce nom chez lui. Le
  marquage se fait **après la pagination**, sur les seules lignes rendues —
  marquer une page de cinquante lignes en relisant trois cent mille identités
  coûterait le prix d'un mining pour décorer un tableau.
- **Ce qu'il ne fait jamais** : se rabattre sur l'identifiant quand la colonne
  déclarée manque du fichier chargé. Marquer d'après une autre colonne que
  celle déclarée donnerait un résultat crédible et faux — et un résultat faux
  sur cette question-là passe la revue. Il ne marque pas non plus le
  référentiel des droits : un droit n'est pas un compte.
- **Pourquoi le paramètre existe** : une personne porte souvent deux comptes,
  son compte nominatif et un compte d'administration, et le produit les rendait
  côte à côte sans jamais dire lequel était lequel. La règle ne peut pas être
  écrite dans le code : `ADM` signale un compte d'administration chez un client
  et l'abréviation d'« administratif » chez un autre. Se tromper ici ne produit
  pas un badge en trop — cela produit une revue qui passe à côté du compte qui
  pouvait tout faire.
- **Les places** : `jeton` (le fragment occupe un morceau entier de
  l'identifiant, entre deux séparateurs ou à un bout : `ADM` marque `ADM_X` et
  `x.adm`, pas `ADMINISTRATIF`), `debut`, `fin`, et `partout` — le plus large
  et le plus bruyant, offert parce qu'un référentiel sans séparateur ni
  position stable n'a rien d'autre.
- **Comment le régler** : l'écran des paramètres **dénombre** ce que la
  déclaration marque, fragment par fragment, sur le référentiel entier. Un
  fragment qui marque la moitié des identités se dénonce par son nombre, et
  c'est le seul contrôle qui vaille. Le bouton « proposer des conventions »
  interroge le modèle sur les usages du métier — voir `comptes_a_privileges`
  plus bas : **cette demande ne transmet aucune donnée**.
- **Une place mal orthographiée arrête la lecture** au lieu d'être remplacée
  par une place de repli, et le refus est rendu à l'écran. `debbut` relu
  silencieusement comme « partout » marquerait dix fois plus de comptes que
  demandé, et le client ne le saurait qu'en comptant.

**Mesurer la convention dans ses données** — `POST /api/v1/privileges/mesurer`
(`{"colonnes": [...]}`). C'est la première question de l'entretien du premier
import, et aucun modèle n'y intervient. L'utilisateur coche les colonnes qui
désignent la personne (nom et prénom, matricule RH…) ; le produit n'en devine
aucune. Kovex regroupe les comptes d'une même personne, relève les suites de
lettres qui distinguent le second compte (`599326084` / `fkciadm1` → `adm`), et
rend pour chaque fragment : le nombre de personnes dont il distingue le second
compte, le nombre de paires de comptes sans aucun droit commun, le nombre de
comptes isolés qui le portent aussi, des exemples, et ce qu'il marquerait à
chacune des quatre places. La proposition se reprend dans le champ comme celle
du modèle, puis s'enregistre ; elle se retire de la même façon.

| Paramètre du workspace | Défaut | Ce qu'il change |
|---|---|---|
| `privileges_mesure_groupes_min` | 2 | personnes à distinguer pour qu'un fragment soit proposé |
| `privileges_mesure_fragments_max` | 10 | fragments proposés au plus |

### `health_threshold_alert` et `health_threshold_critical`

- **Domaine** : pourcentages. Livrés à 10,0 et 50,0.
- **Effet** : bornes du taux d'anomalies (droits orphelins, identités
  orphelines, identités hors périmètre, rapporté au nombre d'identités) qui
  font passer l'indicateur de santé de *sain* à *alerte* puis à *critique*.
- **Comment le régler** : selon ce que votre gouvernance considère comme
  tolérable. Ces seuils ne changent aucun calcul, seulement l'étiquette.

### `data_quality` — la politique de qualité des clés

Ce réglage porte le paramètre `politique_qualite` du chargeur, et lui seul
décide de ce qu'il advient d'une ligne dont la clé est vide ou dupliquée.
Jusqu'ici ce comportement était écrit dans le code, et il différait d'un
référentiel à l'autre sans que personne l'ait choisi.

- **Forme** :

  ```json
  "data_quality": {
      "default": {"empty_key": "discard", "duplicate_key": "first"},
      "files": {"habs": {"duplicate_key": "last"}}
  }
  ```

- **Portée** : `default` s'applique à tous les référentiels ; `files` le
  surcharge pour un référentiel donné — `identities`, `applications`, `rights`
  ou `habs`. Un nom de référentiel inconnu est **refusé à l'écriture** : un
  réglage accepté puis jamais appliqué est pire qu'un réglage refusé.
- **`empty_key`** — ligne dont la clé n'est pas renseignée :
  - `reject` : refuser le chargement ;
  - `discard` *(défaut)* : écarter la ligne et poursuivre.

  Deux actions seulement : « garder la première occurrence » ne veut rien dire
  pour une clé qui ne désigne personne.
- **`duplicate_key`** — plusieurs lignes portant la même clé :
  - `reject` : refuser le chargement ;
  - `discard` : écarter **toutes** les occurrences — la clé devient inconnue ;
  - `first` *(défaut)* : garder la première rencontrée dans le fichier ;
  - `last` : garder la dernière, ce qu'attend un extract où la dernière ligne
    est la plus récente.
- **Clé des habilitations** : elle est **composée** (utilisateur, droit). Une
  même paire présente deux fois est un doublon ; la même personne sur deux
  droits ne l'est pas.
- **Effet d'un refus** : **tous** les référentiels sont vidés, pas seulement
  celui qui l'a provoqué. Ne vider que le fautif produirait des milliers
  d'anomalies dérivées — orphelins, score de santé effondré — qui masqueraient
  la seule information utile : le chargement a été refusé, et pour ce motif.
- **Traçabilité** : l'écran **Qualité** rend, référentiel par référentiel, le
  nombre de lignes lues, retenues et écartées, avec un échantillon des numéros
  de ligne et des clés concernées. Un contrôle qui n'a pas pu avoir lieu —
  colonne de clé non associée — est signalé comme tel plutôt que rendu à zéro.
- **Ce que change le défaut** : sur les habilitations, rien — écarter les
  lignes incomplètes et ne compter qu'une fois une même paire est ce que le
  produit faisait déjà. Sur les trois autres référentiels, les doublons
  d'identifiants étaient conservés et ne le sont plus.

### `transformations` — réparer un référentiel au chargement

Ce réglage porte le paramètre `pipeline` du chargeur. Rien ne permettait
jusqu'ici de réparer un fichier source : si les identifiants d'un client
portent un préfixe de domaine d'un côté et pas de l'autre, si une colonne est
en majuscules dans l'annuaire et en minuscules dans l'extract applicatif, ou si
un fichier d'habilitations met plusieurs droits dans une même cellule, le
rapprochement échouait et la seule issue était d'éditer les CSV à la main, hors
du produit et sans trace.

- **Forme** :

  ```json
  "transformations": {
      "habs": [
          {"column": "matricule", "operation": "trim"},
          {"column": "matricule", "operation": "strip_prefix", "value": "CORP\\"},
          {"column": "droits", "operation": "split", "value": ","}
      ]
  }
  ```

- **L'ordre de la liste est l'ordre d'application**, et il compte : découper
  une cellule multivaluée puis élaguer chaque morceau n'est pas la même chose
  que l'inverse.
- **`column`** est le nom de colonne **du fichier de l'utilisateur**, pas le
  nom standardisé : les règles s'appliquent avant la standardisation, donc
  avant que `matricule` ne devienne `ID_utilisateur`.
- **`operation`** :
  - `trim` — retire les espaces de début et de fin ;
  - `upper`, `lower` — change la casse ;
  - `strip_prefix` — retire un préfixe s'il est présent (exige `value`) ;
  - `add_prefix` — ajoute un préfixe (exige `value`) ;
  - `split` — découpe une cellule multivaluée : une ligne devient autant de
    lignes que la cellule contenait de valeurs (exige `value`, le séparateur).
- **`value`** est **exigée** par les trois dernières et **refusée** par les
  trois premières. Accepter un séparateur sur un « passer en majuscules »
  enregistrerait un réglage que rien n'applique.
- **Quand elles s'appliquent** : avant la standardisation des colonnes, et
  avant la politique de qualité des clés. C'est délibéré — c'est sur la valeur
  transformée que les doublons se comptent, sans quoi deux écritures du même
  identifiant resteraient deux identifiants jusque dans la matrice.
- **Valeurs manquantes** : elles le restent. Aucune opération ne transforme une
  absence en chaîne de caractères.
- **Traçabilité** : la valeur d'origine est conservée, dans une structure
  parallèle et non dans les tableaux affichés. L'écran **Qualité** rend, pour
  chaque règle, le nombre de valeurs changées, les lignes produites par un
  découpage, et un échantillon de couples avant/après.
- **Colonne introuvable** : la règle est signalée comme non applicable et
  comptée comme anomalie. C'est la panne silencieuse de ce mécanisme — une
  correction qu'on croit active et qui ne l'est pas laisse exactement le défaut
  qu'elle devait réparer.

### `pipeline_invalide` — une règle illisible ne passe pas pour une règle

Comme `politique_invalide`, ce champ du chargeur n'est pas un paramètre : il
porte le motif d'une règle que le produit n'a pas su lire. Le chargement se
poursuit **sans aucune transformation**, et le rapport de qualité affiche une
anomalie critique.

### `politique_invalide` — un réglage illisible ne passe pas pour un réglage

Ce champ du chargeur n'est pas un paramètre : il porte le message d'une
politique que le produit n'a pas su lire — une action mal orthographiée dans un
`config.json` corrigé à la main. Le chargement se poursuit avec la politique
par défaut, et le rapport de qualité affiche une anomalie **critique**. Une
faute de frappe ne doit ni empêcher l'application de démarrer, ni passer pour
un réglage actif.

### Deux paramètres retirés

`mining_gamma_min` et `mining_max_depth` figuraient dans le fichier de
configuration, dans le schéma de l'API et dans l'écran Configuration —
**et aucun moteur ne les lisait**. Vestiges du mode « fuzzy » supprimé, ils
portaient de surcroît des valeurs livrées contradictoires d'un fichier à
l'autre (0,5 côté chargeur, 75,0 côté gestionnaire de workspaces). Ils ont été
retirés partout. La profondeur de croisement du mining métier vient de la
requête, pas de la configuration.

L'écran **Configuration** écrivait par ailleurs dans `config/config.json`,
alors que le chargeur lit **en priorité** le `config.json` du workspace actif :
tant qu'un workspace était actif — le cas normal — les réglages saisis
n'étaient jamais relus. Il écrit désormais là où le chargeur lit, **par
fusion** : les clés qu'il ne connaît pas sont conservées, et la modification
prend effet sans redémarrage.

---

## 3. Paramètres d'exécution

Ce sont les seuls réglages que l'analyste manipule au quotidien. Aucun n'a de
valeur par défaut côté serveur : une requête incomplète est refusée avec un code
d'erreur explicite, jamais complétée en silence.

### 3.1 Mining applicatif — `POST /api/v1/mining/launch`

| Paramètre | Domaine | Ce qu'il change |
|---|---|---|
| `mining_mode` | `EXACT` \| `APPROX` | signature identique, ou clôture au seuil θ |
| `min_users` | ≥ 2 | effectif minimal du rôle |
| `min_rights` | ≥ 1 | nombre minimal de droits du rôle |
| `excluded_rights` | liste | droits ignorés, en plus des droits socles |
| `similarity_threshold` (θ) | ]0 ; 1], **obligatoire en APPROX** | tolérance à l'écart |
| `max_roles` | 1 à 5 000, **obligatoire en APPROX** | borne le nombre de rôles rendus |
| `consolidation_threshold` | ]0 ; 1], facultatif | au-delà de ce seuil de similarité, deux rôles n'en font qu'un : seul le mieux classé est conservé. Absent, rien n'est consolidé |
| `generateurs` | liste parmi `cloture`, `signature`, `intersection`, `treillis`, facultatif | les façons d'amorcer un rôle candidat. Absent, les trois premières sont employées. Une liste vide ne cherche rien et le rend explicitement |
| `selection` | `gloutonne` \| `exacte`, facultatif | comment les rôles sont choisis parmi les candidats. Absent, le réglage du workspace `mining_selection` s'applique. `exacte` ne joue qu'à θ = 1 (§ 2) |

**Les quatre façons de chercher — `generateurs`.**

Un rôle candidat commence par un ensemble de droits, et il y a quatre manières
d'en proposer un. Aucune n'est meilleure en soi : chacune trouve des rôles que
les autres ne trouvent pas. Les trois premières sont employées par défaut ; la
quatrième est un choix.

- **`cloture`** — partir d'un droit `r` et retenir les droits que partagent au
  moins θ·|U(r)| de ses détenteurs. Trouve ce qui gravite autour d'un droit.
- **`signature`** — partir d'un profil exact : l'ensemble des droits que
  plusieurs personnes détiennent à l'identique. C'est ce que rend le mining
  exact.
- **`intersection`** — croiser deux profils distincts et retenir ce qu'ils ont
  en commun. C'est la seule qui produise **le terrain commun à deux
  populations dont aucun droit ne leur est propre** — précisément le rôle qu'un
  analyste écrirait en premier, et que ni la clôture ni la signature ne
  proposent.
- **`treillis`** — recroiser ces terrains communs avec les profils, jusqu'à ce
  que plus rien de nouveau n'apparaisse. Trouve **le terrain commun à trois
  populations ou plus**, que le croisement deux à deux n'atteint pas. Borné par
  `mining_treillis_max` (§ 2).

**Pourquoi le treillis, et pourquoi il n'est pas coché d'office.** Sur le jeu HP
Americas small, dix rôles de la décomposition optimale publiée ne sont ni une
clôture, ni un profil, ni l'intersection de deux profils : sans eux, la
sélection exacte trouvait 179 rôles pour un optimum publié de 178. Avec le
treillis, Kovex atteint **les huit optima publiés sur huit** (§ 3 de
`04-validation.md`). Mais il ne change le résultat que sur ce seul jeu, et il
multiplie le calcul par trois sur Customer et par six sur Americas large. Sur
le banc de vérité terrain bruité, il ne retrouve ni plus ni moins de rôles
réels. Il sert donc là où la donnée est propre et où l'on veut le plus petit
modèle — avec la sélection exacte.

**Le croisement change ce que θ sert à acheter.** Mesuré sur le référentiel de
démonstration, à bornes égales :

| générateurs | θ | rôles | couverture | octroyés en trop | hors modèle |
|---|---|---|---|---|---|
| `cloture`+`signature` | 1,00 | 39 | 79,91 % | **0** | 428 |
| `cloture`+`signature` | 0,80 | 148 | 92,25 % | 4 306 | 165 |
| les trois | 1,00 | 148 | **95,16 %** | **0** | 103 |
| les trois | 0,80 | 189 | 98,22 % | 3 188 | 38 |

La troisième ligne rend le même nombre de rôles que la deuxième, couvre
davantage, et n'octroie **rien** en trop. Autrement dit : le sur-octroi que
θ < 1 achetait n'était pas le prix de la couverture, c'était le prix d'un jeu
de candidats trop pauvre. À θ = 1, le sur-octroi est nul **par construction** —
un rôle ne contient alors que des droits que tous ses membres détiennent — et
ce qui reste à arbitrer est la dernière colonne : les habilitations qu'aucun
rôle n'explique et qui restent en attribution individuelle.

**Le croisement a un coût quadratique**, et une borne :
`mining_profils_croises_max` (§ 2). Il compare les profils deux à deux — mille
profils font un demi-million de paires, vingt mille en font deux cents
millions. Au-delà de la borne, il ne porte que sur un échantillon régulier des
profils, et l'interface le dit à côté du résultat plutôt que de rendre moins de
rôles en silence.

**θ, en une phrase par valeur :**

- **θ = 1,00** — clôture exacte. Aucun membre ne reçoit un droit qu'il n'a pas.
  Sur des données propres, restitue exactement les rôles sous-jacents. Sur un
  référentiel bruité, la couverture s'effondre.
- **θ = 0,95 à 0,90** — tolère une minorité d'écarts. C'est là que se situe
  généralement le meilleur rapport, mais il faut le vérifier sur vos données :
  sur une mesure réelle, θ = 0,95 couvrait 1,5 point de plus que θ = 1,00 pour
  **zéro** droit octroyé en trop.
- **θ ≤ 0,80** — couverture élevée, sur-octroi significatif (autour de 6 à 10 %
  sur les mesures faites). À réserver aux référentiels très dégradés, et à
  n'accepter qu'en connaissance du chiffre de sur-octroi.

**`max_roles` n'est pas un réglage anodin.** Quand il est atteint, la couverture
affichée est bornée par lui et non par vos données. L'exploration du seuil le
signale explicitement sur chaque point concerné.

**`consolidation_threshold`, en une phrase par valeur :**

- **absent** — aucun rôle n'est retiré. C'est le défaut : supprimer un candidat
  est une décision, elle ne se prend pas à votre place.
- **1,00** — seuls les rôles portant *exactement* les mêmes droits sont réunis.
  Retire les doublons stricts, ne peut rien coûter d'autre.
- **0,80 à 0,70** — retire les variantes proches. Sur un référentiel bruité,
  c'est là que le modèle se simplifie vraiment : mesuré sur 1 693 rôles
  candidats, le seuil 0,80 en retire 1 066 et divise la complexité structurelle
  par plus de deux.
- **en dessous de 0,60** — regroupe des rôles qui ne se ressemblent plus
  beaucoup. Le nombre d'habilitations que le modèle n'accorde plus, rendu par
  l'API et affiché dans l'interface, est le chiffre à surveiller.

Un rôle conservé n'est **jamais modifié** : c'est exactement celui que le moteur
a produit. La consolidation retire des rôles, elle n'en fabrique pas.

### 3.2 Exploration du seuil — `POST /api/v1/mining/threshold-scan`

| Paramètre | Domaine | Ce qu'il change |
|---|---|---|
| `thresholds` | liste de 1 à 20 valeurs dans ]0 ; 1] | les seuils évalués. Dédoublonnés, ordonnés du plus strict au plus lâche |
| `min_users`, `min_rights`, `max_roles` | comme ci-dessus | les bornes du balayage doivent être **celles du mining réel**, sinon la courbe ne décrit pas ce que vous obtiendrez |
| `excluded_rights` | liste | idem |
| `generateurs`, `apport_minimal`, `selection` | comme ci-dessus | les mêmes leviers qu'un mining. Chaque point dit ce que la sélection a fait (`selection_arret`) et combien de rôles le glouton aurait retenus (`selection_roles_glouton`) |
| `max_over_granted_pct` | 0 à 100, facultatif | votre contrainte de gouvernance. Sans elle, aucun seuil n'est désigné |

La borne de 20 seuils n'est pas un choix métier : chaque seuil est un mining
complet, et c'est une protection contre une requête qui bloquerait le serveur
plusieurs minutes.

Dans l'interface, vous saisissez un **seuil de départ, un seuil d'arrivée et un
pas** ; le seuil d'arrivée est toujours évalué, même quand le pas ne tombe pas
juste dessus.

### 3.3 Exploration de la consolidation — `POST /api/v1/mining/consolidation-scan`

| Paramètre | Domaine | Ce qu'il change |
|---|---|---|
| paramètres de mining | comme au 3.1 | la courbe décrit exactement les rôles que cette exécution produirait |
| `consolidation_thresholds` | liste de 1 à 20 valeurs dans ]0 ; 1] | les seuils de consolidation évalués |
| `max_granted_loss_pct` | 0 à 100, facultatif | part des habilitations accordées que vous acceptez de perdre. Sans elle, aucun point n'est désigné |

**Le mining n'est exécuté qu'une fois.** Seule la consolidation est rejouée à
chaque seuil : un balayage complet coûte à peine plus qu'un mining seul — 4
secondes pour six seuils sur 18 000 identités, contre 24 secondes pour un
balayage de θ, qui refait un mining par point.

La réponse porte un **modèle de référence** (`baseline`, sans consolidation) qui
sert d'étalon à toutes les pertes annoncées, et pour chaque point : rôles
conservés, rôles retirés, habilitations que le modèle n'accorde plus,
compression, redondance, complexité, et deux rendements.

**Le rendement est ce qui distingue réellement les points.** Contrairement à la
courbe de θ, celle-ci est monotone — baisser le seuil retire toujours des rôles
et perd toujours des habilitations — donc aucun point n'en domine un autre et un
marqueur « non dominé » dirait « oui » partout. Ce qui se lit, c'est :

- `efficiency` — rôles retirés par millier d'habilitations perdues, depuis le
  modèle non consolidé ;
- `marginal_efficiency` — le même rapport depuis le seuil précédent, c'est-à-dire
  ce que rapporte le fait de relâcher le seuil d'un cran. **Sa décroissance
  montre où la simplification cesse de payer.**

Mesuré sur 1 693 rôles candidats (18 000 identités, 244 000 habilitations) :

| Seuil | Rôles | Habilitations perdues | Compression | Redondance | WSC | Rendement marginal |
|---|---|---|---|---|---|---|
| 1,00 | 1 693 | 0,00 % | 1,83 | 68,9 % | 125 404 | — |
| 0,90 | 1 601 | 2,15 % | 1,88 | 67,2 % | 119 426 | 18,9 |
| **0,80** | **627** | 13,70 % | 4,13 | 24,6 % | 47 975 | **37,3** |
| 0,70 | 444 | 15,96 % | 5,70 | 5,3 % | 33 834 | 35,8 |
| 0,60 | 409 | 16,47 % | 6,18 | 0,9 % | 31 017 | 30,0 |
| 0,50 | 400 | 16,66 % | 6,34 | 0,1 % | 30 182 | 21,8 |

Le rendement marginal culmine à 0,80 puis décroît : au-delà, chaque habilitation
sacrifiée retire de moins en moins de rôles. C'est exactement le genre
d'inflexion qu'on ne voit pas sans la courbe.

### 3.4 Mining métier — `POST /api/v1/mining-metiers/find-roles-business`

| Paramètre | Domaine | Ce qu'il change |
|---|---|---|
| `attributes` | liste de colonnes d'identité | les critères du rôle |
| `mining_depth` | 1 à 6 | jusqu'à combien d'attributs sont croisés simultanément |
| `min_coverage` | ]0 ; 100] % | part du groupe devant détenir un droit pour qu'il entre dans le rôle |
| `min_users` | ≥ 2 | effectif minimal du groupe |
| `min_rights` | ≥ 1 | nombre minimal de droits du rôle |
| `couverture_visee` | ]0 ; 100] % ou absent | part des habilitations à expliquer avant que la sélection s'arrête |
| `arbitrage` | ≥ 0, **0 par défaut** | poids du sur-octroi face à la couverture dans la sélection |
| `parcimonie` | [0 ; 100] %, **0 par défaut** | ce qu'un sous-rôle doit expliquer, en part de son parent, pour être retenu à côté de lui |
| `inclure_sans_droit` | booléen, **faux par défaut** | les identités qui ne détiennent aucun droit entrent-elles dans le calcul |

**`mining_depth` est le paramètre coûteux.** Le nombre de groupes croît comme le
produit des cardinalités : profondeur 1 sur un attribut à 500 valeurs donne 500
groupes ; profondeur 2 sur deux attributs à 500 et 16 valeurs en donne 8 000.
Mesuré sur 21 000 identités et 220 000 habilitations : 1,8 s en profondeur 1,
8,1 s en profondeur 2, 26,5 s en profondeur 3.

**`min_coverage` décide de la nature du rôle.** À 100 %, le rôle ne contient que
les droits que *tout* le groupe possède : peu de droits, aucune surprise. À
70 %, il contient ce que la majorité possède : plus riche, mais l'attribuer
donnera des droits à la minorité qui ne les avait pas.

**`arbitrage` et `couverture_visee` vont ensemble.** C'est une mesure qui l'a
imposé, pas un choix de conception : laissé courir jusqu'à épuisement, le
glouton retient de toute façon tout candidat qui apporte quelque chose, et
l'arbitrage ne change alors que l'ordre — sur un référentiel de 230 000
habilitations, le sur-octroi final passe de 14 738 à 14 679 selon l'arbitrage,
c'est-à-dire rien. L'écart n'apparaît qu'au moment où l'on **s'arrête**.

Avec un objectif de 34,46 % de couverture, sur ce même référentiel :

| `arbitrage` | rôles | sur-octroi réel |
|---|---|---|
| 0 *(défaut)* | 784 | 13 251 |
| 0,5 | 791 | 12 719 |
| 1 | 809 | 12 266 |
| 2 | 908 | 11 338 |
| 4 | 1 240 | 11 010 |

À 0, le produit se comporte exactement comme avant l'existence de ce réglage,
coût marginal non calculé compris : personne ne subit un arbitrage qu'il n'a pas
demandé.

**Ce paramètre n'est pas fait pour être saisi.** Personne ne sait ce que vaut
« 1,5 ». `POST /api/v1/mining-metiers/arbitrage` rend la liste des points —
*tant de rôles pour tant de sur-octroi* — et l'écran les donne à choisir ; la
valeur se déduit du point désigné. Le calcul rejoue la sélection sans
réénumérer les candidats, mais reste de l'ordre de la demi-minute pour six
points sur un référentiel réel : d'où un appel explicite, et non un calcul
imposé à chaque mining.

**`parcimonie` répond à une sur-découpe mesurée.** Le moteur retient
« fonction = infirmier » et, à côté, « fonction = infirmier ET service =
cardiologie », « ET service = réanimation »… Ce n'est pas absurde — un
référentiel réel est plein de hiérarchies — mais mesuré sur le banc de vérité
terrain, le moteur en garde **onze fois plus qu'il n'en existe** : 78
stratifications retenues pour 7 réellement présentes.

Le départage interne préférait déjà la règle la plus simple, mais seulement à
apport marginal *strictement égal*. Sous bruit, un sous-rôle capte presque
toujours quelques lignes de plus : la condition ne se déclenchait jamais.

`parcimonie` exige qu'un sous-rôle batte son parent d'une marge. Elle
s'exprime en part de ce que le parent explique, et non en nombre
d'attributions : une part se transporte d'un référentiel de 3 000 identités à
un de 300 000, un nombre non.

Mesuré sur trois tirages du banc, toutes idéalisations levées (600 identités,
120 droits, 12 règles plantées, profondeur 2) :

| `parcimonie` | sous-rôles retenus | couverture | règles retrouvées à l'identique |
|---|---|---|---|
| 0 *(défaut)* | 7 / 6 / 10 | 67,3 / 67,5 / 61,9 % | 12 / 10 / 11 |
| 1 % | 4 / 6 / 9 | 67,2 / 67,5 / 61,8 % | 12 / 10 / 11 |
| 3 % | 2 / 4 / 6 | 66,9 / 67,3 / 61,7 % | 12 / 10 / 11 |
| 10 % | 2 / 4 / 4 | 66,9 / 67,3 / 60,5 % | 12 / 10 / **9** |

Les trois nombres de chaque case sont les trois tirages. À 3 %, les sous-rôles
tombent de moitié à un tiers pour moins d'un demi-point de couverture, et
aucune règle réelle n'est perdue. À 10 %, le troisième tirage — celui qui
plante le plus de hiérarchies — commence à en perdre.

**Ce n'est donc pas un réglage à monter au maximum**, et c'est pourquoi il vaut
0 par défaut : les sous-rôles écartés portent 43 % de la couverture marginale
du modèle. Le produit montre ce que chaque position coûte ; il ne choisit pas.

**`inclure_sans_droit` répond à une limite du mining.** Le mining métier
travaille sur la jointure des habilitations et des identités : une identité qui
ne détient **aucun** droit n'appartient à aucun groupe. Elle ne pèse donc ni sur
la couverture d'un droit, ni sur le sur-octroi annoncé — alors qu'un rôle qui
lui serait attribué lui accorderait bien tout ce qu'il porte. Sur un référentiel
réel, cela représentait 16,7 % des identités.

Le produit ne peut pas trancher à la place de l'utilisateur : sans statut ni
date de création, un arrivant — qui recevra bien les rôles — ressemble
exactement à un partant dont les accès ont été révoqués. D'où un paramètre, et
non une règle.

Mesuré sur ce référentiel — 21 454 identités, 3 573 sans aucun droit, deux
attributs croisés en profondeur 2, couverture minimale 70 % :

| `inclure_sans_droit` | rôles | couverture | sur-octroi du calcul | sur-octroi si attribué | sans droit touchées |
|---|---|---|---|---|---|
| faux *(défaut)* | 1 176 | 34,4 % | 14 230 | **18 373** | 1 166 |
| vrai | 1 154 | 33,4 % | 14 268 | 14 268 | 235 |

Deux choses se lisent dans ce tableau. D'abord le prix du choix : compter ces
identités fait baisser les taux de couverture des groupes, donc produit 22 rôles
de moins et un point de couverture en moins. Ensuite, et c'est l'essentiel, le
sur-octroi annoncé par défaut est un **minorant de 29 %** — 14 230 annoncés pour
18 373 réellement créés le jour de l'attribution.

C'est pourquoi `over_provisioning_if_applied` est rendu **dans les deux cas**,
et affiché à côté du sur-octroi du calcul. Les deux coïncident dès que le calcul
porte sur tout le monde ; l'écart, sinon, est exactement ce que le chiffre
principal passe sous silence. L'écran annonce également combien d'identités sans
droit les rôles proposés toucheraient, coché ou non.

### 3.4 bis Périmètre d'analyse — `PUT /api/v1/kb/perimeter-rules`

| Paramètre | Domaine | Ce qu'il change |
|---|---|---|
| `attribut` | une colonne d'identité | sur quoi porte la règle |
| `sens` | `keep` / `discard` | ne garder que ces valeurs, ou les écarter |
| `valeurs` | valeurs observées dans le référentiel chargé | qui la règle désigne |
| `sans_valeur` | `keep` / `discard` | le sort des identités dont la colonne est vide |

**Une règle, pas une liste.** Le produit savait déjà exclure une identité
nommément. C'est ce qu'il faut pour l'exception — ce compte de service précis,
avec son motif — et ce qu'il ne faut pas pour une population. Une liste
d'identifiants est figée : les identités arrivées depuis la décision n'y sont
pas, et personne ne s'en aperçoit. Une règle se réévalue à chaque chargement.
Les deux coexistent et s'appliquent au même endroit, en amont de tous les
moteurs.

**Les règles se cumulent.** Une identité reste dans le périmètre si elle
satisfait *toutes* les règles : « les actifs **et** pas les prestataires ».

**`sans_valeur` n'a pas de défaut, et c'est voulu.** Sur un référentiel réel la
colonne est incomplète. Trancher à la place de l'utilisateur reviendrait à
décider du sort d'une population qu'il n'a pas regardée.

**Une règle dont la colonne a disparu n'écarte personne.** Un rechargement de
données qui renomme une colonne viderait sinon le périmètre, ou ferait échouer
chaque calcul. Ne rien écarter est le seul défaut sûr — et l'écran signale la
règle restée sans effet, faute de quoi l'utilisateur croirait son périmètre
restreint alors qu'il ne l'est pas.

**Écarter change le dénominateur de tout** — couverture, sur-octroi, effectifs.
Chaque écran qui affiche un chiffre dérivé annonce donc la population sur
laquelle il porte : *« 18 200 identités analysées sur 21 454 ; 3 224 écartées
par une règle, 30 exclues nominativement »*. C'est la même exigence que sur le
sur-octroi réel du lot 6b, appliquée à l'autre bout de la chaîne.

**Les colonnes proposées viennent des données.** Le produit ne connaît pas les
colonnes du client, donc pas non plus les valeurs qu'elles prennent : l'écran
lit les deux dans le référentiel chargé. Une colonne à plus de 200 valeurs
distinctes n'est pas offerte — c'est un identifiant, pas un critère — et la
borne est rendue par le serveur avec la liste, pour que les deux ne divergent
pas.

### 3.4 ter Détail des identités sans droit — `GET /api/v1/mining-metiers/population-detail`

Aucun paramètre : la route décrit le **modèle conservé** — les candidats du
dernier mining métier. Un détail recalculé rendrait autre chose dès qu'un
réglage a bougé, et décrirait des règles que l'utilisateur n'a pas sous les
yeux.

Le lot 6b a fait annoncer un nombre : « tant d'identités sans droit recevraient
un rôle proposé ». Cette route donne le moyen de le regarder — une ligne par
règle RH concernée, avec l'effectif du groupe, le nombre d'identités sans droit
qu'il contient, la part qu'elles y représentent, le nombre de droits du rôle et
le nombre de couples que l'attribution créerait.

**Le classement suit le coût, pas l'effectif.** Dix identités qui recevraient
vingt droits pèsent plus que cent qui en recevraient deux ; un tableau trié par
effectif mettrait en tête une décision qui n'est pas la première à prendre.

Mesuré sur un référentiel réel de 21 454 identités : 1 166 identités sans droit
concernées se répartissent en **222 règles**, dont les dix premières portent
42 % du coût total et dont **131 ne concernent qu'une seule personne**. C'est ce
qui rend l'écran praticable — et ce qui montre qu'une liste identité par
identité ne le serait pas.

Deux lignes de tête y sont plus instructives que le total : *« Agent.e propreté
et hygiène : 290 identités sans aucun droit sur 558 »* et *« Employé.e de
restaurant : 199 sur 303 »*. Une part majoritaire signale généralement une
population sans accès informatique du tout, ou un chargement incomplet — dans
les deux cas, une question à poser avant de décider, et que le seul total ne
faisait pas apparaître.

La réponse porte `stale` : les données ont-elles changé depuis le calcul. Un
tableau qui décrit un référentiel rechargé depuis induirait en erreur au moment
précis où il sert à décider.

### 3.4 quater Exclusions nominatives — `POST /api/v1/kb/exclude-users`

| Paramètre | Domaine | Ce qu'il change |
|---|---|---|
| `user_ids` | au moins un identifiant | les identités retirées de toutes les analyses |
| `reason` | texte libre | le motif conservé avec la décision |

**En lot, et en une seule écriture.** Le détail par groupe désigne parfois
quelques centaines d'identités d'un coup. La Knowledge Base relit et réécrit son
document sous verrou à chaque mutation : les passer une par une ferait autant
d'allers-retours, au moment précis où l'on décide.

**Idempotente.** Une identité déjà écartée n'est pas dupliquée, et le motif de la
première décision est conservé — le remplacer effacerait la raison pour laquelle
quelqu'un avait tranché. La réponse porte `added`, les identités effectivement
ajoutées : vide, l'appelant sait qu'il n'a rien changé et n'annonce pas une
décision qui n'a pas eu lieu.

**Nominative, et non une règle.** Les deux mécanismes coexistent parce qu'ils ne
répondent pas à la même question. Une règle (§ 3.4 bis) se réévalue à chaque
chargement et convient à une population ; une exclusion nominative fige des
identifiants et convient à l'exception. Écarter par une règle les identités sans
droit d'un groupe en retirerait aussi tous les membres qui détiennent des droits
et que le modèle explique très bien : c'est pourquoi l'action depuis le détail
passe par le chemin nominatif.

**Tracée.** `perimeter.updated` entre dans la piste d'audit pour l'exclusion en
lot, l'exclusion unitaire, la réintégration et la pose d'une règle. Ces décisions
déplacent la couverture, le sur-octroi et les effectifs de toutes les analyses
suivantes : sans trace, deux minings aux résultats différents sur les mêmes
données restent inexplicables. Un lot qui n'ajoute rien n'est pas consigné — une
piste d'audit ne se remplit pas de décisions sans effet.

**Réversible.** `DELETE /api/v1/kb/excluded-users/{user_id}` réintègre, et la
réintégration est tracée au même titre. Une décision de gouvernance qu'on ne peut
pas défaire n'en est pas une : elle devient un état subi.

### 3.4 quater ter Usage des droits — `GET /api/v1/usage`

| Paramètre | Domaine | Ce qu'il change |
|---|---|---|
| `colonne_habilitation` | une colonne du fichier des habilitations | la date de dernière utilisation de chaque habilitation |
| `colonne_identite` | une colonne du fichier des identités | la date de dernière connexion de chaque identité |
| `format_date` | un format `strptime`, **obligatoire** | `%d/%m/%Y`, `%Y-%m-%d %H:%M:%S`… |
| `inactivite_jours` | ≥ 1, **obligatoire** | au-delà, une habilitation est dormante et un compte inactif |
| `limite` | ≥ 1, **obligatoire** | nombre de droits rendus, les plus dormants d'abord |
| `date_reference` | AAAA-MM-JJ, facultatif | la date de l'export |

Au moins une des deux colonnes est requise. Le produit n'en connaît aucune et
n'en devine aucune. Sans déclaration, la fonction est muette, et l'écran le dit.

**L'inactivité se mesure à la date de l'export, pas à aujourd'hui** : un export
d'avril lu en septembre ne rend pas tout le monde inactif. Sans
`date_reference`, c'est la plus récente date trouvée dans les colonnes qui
tient lieu de date d'export, et la réponse le signale
(`date_reference_deduite`).

**Rien n'est inventé.** Une cellule vide compte comme « sans date », pas
comme « jamais utilisé ». Une date qui ne suit pas le format déclaré compte
comme illisible et est montrée avec quelques exemples. Elle n'est jamais
écartée en silence : un format mal déclaré qui ferait disparaître la moitié
des lignes rendrait un constat faux sans que rien ne l'indique.

Les droits sont triés par part de détenteurs inactifs (« 40 des 42
détenteurs ne s'en servent plus »). Deux routes paginées donnent les noms :
`/usage/dormants?droit=…` et `/usage/inactives`. Elles prennent la même
déclaration, pour que la liste corresponde exactement au compte qu'elle
détaille. Les identités écartées de l'analyse ne comptent pas.

### 3.4 quater quater Constats d'une identité — `GET /api/v1/identites/{id}/constats`

| Paramètre | Domaine | Ce qu'il change |
|---|---|---|
| `attribut_pairs` | une colonne du fichier des identités, facultatif | la colonne qui définit ses pairs ; sans elle, l'écart aux pairs n'est pas calculé |

Le panneau s'ouvre dans la fenêtre de détail d'une identité, au-dessus de ses
droits. Il rassemble, pour une personne, des constats que d'autres écrans
calculent déjà, **par les mêmes fonctions** :

- **référentiel** : droits détenus, compte absent du référentiel des identités,
  identité écartée de l'analyse ;
- **compte à privilèges** : ce que le marqueur déclaré trouve dans la colonne
  déclarée (§ comptes à privilèges) ;
- **séparation des tâches** : les règles qu'elle enfreint, avec la dérogation
  qui couvre le conflit ou la raison pour laquelle elle ne le couvre plus ;
- **écart aux pairs** : les droits que 5 % ou moins des *autres* membres de son
  groupe détiennent (`mouvement_rarete_max_pct`), avec le groupe où chacun est
  le plus répandu. Un droit qui n'est typique nulle part est montré aussi : c'est
  une exception, pas un droit résiduel. Les droits résiduels sont exactement
  ceux de l'écran « droits conservés » pour cette personne ;
- **rôles et modèle** : les rôles validés dont elle est porteuse, ce que chacun
  lui accorderait qu'elle n'a pas, et les droits qu'aucun rôle ni le socle
  n'explique ;
- **droits hors référentiel** : ceux que le référentiel des droits ne connaît pas.

**Aucun score.** Chaque constat garde son chiffre et sa définition. Une section
qui n'a pas pu être établie le dit (`declare: false`, `examinee: false`, aucune
règle applicable, aucun rôle validé) : une liste vide n'y vaut jamais « rien à
signaler ». La colonne de pairs n'a pas de valeur par défaut ; une fois choisie
dans le panneau, elle est gardée pour les identités ouvertes ensuite.

### 3.4 quater bis Accès proches d'un rôle — `GET /api/v1/kb/validated-roles/{id}/acces-proches`

| Paramètre | Domaine | Ce qu'il change |
|---|---|---|
| `jaccard_min` | [0 ; 1], **obligatoire** | ressemblance minimale entre la population du rôle et celle de l'accès |
| `limite` | ≥ 1, **obligatoire** | nombre d'accès rendus, les plus proches d'abord |

La question posée est : **faut-il faire entrer cet accès dans le rôle ?** Pour
chaque accès hors du rôle que détient au moins un de ses porteurs, la route rend
trois comptes :

- `avec_le_role` : les porteurs du rôle qui détiennent l'accès ;
- `hors_du_role` : les détenteurs de l'accès hors du rôle ;
- `sans_l_acces` : les porteurs du rôle qui ne le détiennent pas. C'est ce que
  l'entrée de l'accès dans le rôle leur accorderait en trop, et c'est le
  compte qui décide.

Elle rend aussi l'indice de Jaccard des deux populations, qui sert à classer.
Chaque compte se déplie en noms par
`GET …/acces-proches/population?droit=…&population=…`, avec les colonnes du
client, la recherche et la pagination du tableau des porteurs.

Aucun des deux paramètres n'a de valeur par défaut : c'est à l'utilisateur de
dire à partir de quand deux populations se ressemblent. Les droits socles ne
sont jamais proposés, puisque le rôle socle les porte déjà. La réponse compte
aussi les accès écartés par l'indice (`sous_le_seuil`) et par la limite
(`au_dela_de_la_limite`) : une liste courte ne doit pas se lire comme un rôle
sans voisins. La forme des trois populations vient d'IdentityStream/RoleMining
(MIT) ; le calcul a été réécrit pour Kovex.

### 3.4 quater quinquies Apprentissage des décisions — `GET /api/v1/apprentissage`

| Paramètre du workspace | Domaine | Défaut | Ce qu'il change |
|---|---|---|---|
| `apprentissage_decisions_min` | ≥ 2 | 40 | décisions nécessaires avant tout score |
| `apprentissage_par_verdict_min` | ≥ 1 | 10 | validations **et** refus nécessaires, chacun |
| `apprentissage_regularisation` | ≥ 0 | 1.0 | force qui resserre les coefficients ; 0 la désactive |

Chaque validation et chaque refus d'un candidat du mining est consigné avec
ses chiffres. Kovex en apprend, localement, une régression logistique sur cinq
grandeurs : nombre de droits et de porteurs (au logarithme), part du
sur-octroi dans les attributions du rôle, adhérence, redondance. Le score porte
son nom — **« ressemble à ce que vous validez »** — et n'est pas une confiance
ni un risque.

- **Réfutable.** `GET /apprentissage` rend la mesure à rebours : chaque
  décision prédite par un modèle entraîné sans elle, comparée à « deviner
  toujours le verdict le plus fréquent ». Un modèle qui ne fait pas mieux que
  la majorité le dit.
- **Décomposable.** `POST /apprentissage/ressemblance` rend, pour chaque
  candidat, la probabilité et la contribution de chaque grandeur, de la plus
  forte à la plus faible. Les cartes du mining montrent les deux premières.
  Seuls les cinq chiffres de la carte partent de l'écran.
- **Désapprenable.** `PUT /apprentissage/decisions/{role}` retire une décision
  de l'apprentissage ou l'y remet ; `POST /apprentissage/oublier` les retire
  toutes. Les décisions restent dans l'historique. Le modèle n'est conservé
  nulle part : il se reconstruit à chaque lecture.
- **Il ne décide rien.** Il ordonne l'attention ; aucune validation ni aucun
  refus n'en découle.
- **La toile part avec le score, jamais le score seul.** Quatre axes sur
  0-100, tous « plus haut vaut mieux » : population (rang parmi les décisions
  de l'historique), adhérence, absence de sur-octroi, absence de redondance.
  La forme moyenne de ce que le workspace valide (`toile_des_validees`) est
  dessinée en pointillé dessous ; la page Apprentissage la montre seule. Le
  dessin est un SVG sans bibliothèque, et la même information est rendue en
  mots pour les lecteurs d'écran.

Une grandeur manquante n'est jamais remplacée par zéro : une décision
incomplète ne sert pas, et un candidat incomplet n'est pas scoré. Sous les
seuils, aucun score n'est rendu et l'écran dit combien de décisions il manque.

### 3.4 quinquies Les deux chiffres du sur-octroi

Le modèle métier publie **deux** grandeurs de sur-octroi, et deux seulement.
Elles répondent à deux questions différentes ; toute autre a été retirée.

| clé | ce qu'elle répond |
|---|---|
| `over_provisioning_distinct` | ce que le modèle **affiché** crée en trop, chaque couple (identité, droit) compté une fois |
| `over_provisioning_if_applied` | ce qu'il créerait le jour de l'attribution, en comptant les identités sans aucun droit que ses règles désignent |

La seconde majore toujours la première ; leur écart est exactement ce que le
calcul ne compte pas (§ 3.4).

**Ce qui a été retiré, et pourquoi.** Le produit en publiait quatre. Sur un
référentiel réel, pour un seul et même modèle : 16 625 (somme rôle par rôle),
14 230 (union relevée avant filtrage), 14 230 (la même union relevée après, sous
un autre nom), 18 373 (coût réel). Et deux pourcentages sur le même écran —
12,4 % dans la phrase de synthèse, 6,06 % dans la tuile voisine — parce qu'ils
n'avaient ni le même numérateur ni le même dénominateur.

La somme rôle par rôle est un **majorant** : deux rôles peuvent sur-octroyer le
même couple, et elle valait 17 % de plus que l'union. Elle n'est plus rendue.
L'union n'est plus calculée qu'une fois, sur le modèle **après** filtrage par la
Knowledge Base — un chiffre relevé avant décrirait des rôles qu'on n'affiche
pas. Un seul pourcentage subsiste, rapporté aux habilitations existantes, qui
est le dénominateur de la couverture : les deux se comparent.

Un test interdit qu'une troisième grandeur réapparaisse au niveau du modèle.
Cette ambiguïté avait produit deux conclusions fausses en une semaine, dont un
comparatif où le majorant d'un outil était opposé à l'union d'un autre.

Les grandeurs **par rôle** (`stats_over_provisioning`) restent : elles décrivent
un rôle, pas le modèle, et leur nom le dit.

### 3.5 Droits socles — `POST /api/v1/birth-rights/detect`

| Paramètre | Domaine | Ce qu'il change |
|---|---|---|
| `frequency_threshold` | 0 à 100 % | au-delà de cette fréquence de détention, un droit est considéré comme universel |

Les droits détectés sont exclus **automatiquement de tous les minings suivants**
tant qu'ils restent dans la Knowledge Base. Un seuil trop bas ampute le
référentiel de droits légitimement partagés ; un seuil trop haut laisse le bruit
dans tous les candidats. Le nombre de droits exclus est rappelé sur chaque
résultat de mining.

---

## 3 quater. Séparation des tâches

Ce que la même personne ne doit pas pouvoir faire : créer un fournisseur **et**
payer une facture, saisir une commande **et** la valider. C'est la première
chose qu'un auditeur cherche, et la seule qu'un outil de gouvernance puisse dire
d'une habilitation sans rien savoir du métier — que deux pouvoirs réunis chez une
personne valent plus que leur somme.

**Aucune règle n'est livrée avec le produit.** Il ne connaît ni le plan
comptable d'un client, ni son organisation. Une bibliothèque de règles toutes
faites se tromperait partout et, pire, donnerait à croire que le sujet est
couvert. Les règles sont des décisions de gouvernance : elles vivent dans la
base de connaissance du workspace, avec le périmètre d'analyse et les rôles
validés — pas dans `config.json`.

### Quand elles se déclarent

**Avant le mining**, en prétraitement. L'ordre n'est pas cosmétique : un rôle qui
réunit deux pouvoirs incompatibles ne doit pas naître, et l'en empêcher demande
que la règle existe déjà quand le candidat s'affiche.

Cela ne serait pas tenable sans la découverte calculée — demander à un client de
déclarer ses règles devant quarante mille droits qu'il n'a jamais regardés, c'est
lui demander de remplir un écran vide. Les **couples candidats** ne lui demandent
pas de savoir, ils lui montrent ce que son organisation sépare déjà, et ils ne
demandent eux-mêmes que les habilitations. Ils vivent donc au même endroit.

Les **conflits constatés**, eux, restent en gouvernance : « qui cumule
aujourd'hui » est un constat d'audit, il se recalcule à chaque chargement.

### La forme d'une règle

Un libellé, un drapeau d'activité, et deux côtés. **Un côté ne nomme pas des
droits, il nomme des pouvoirs** : c'est une liste de **références typées**.

| Type | Ce qu'il désigne |
|---|---|
| `droit` | ce droit, et rien d'autre |
| `application` | tous les droits rattachés à cette application, **relus à chaque calcul** |
| `role` | tous les droits d'un rôle du catalogue, relus de même |

La conséquence qui compte n'est pas l'ergonomie, c'est la durée de vie : **une
règle qui nomme une application se réévalue, une règle qui énumère des droits se
périme.** Un droit ajouté demain à l'application de paiement est couvert d'office
par la première et invisible pour la seconde. C'est exactement l'argument des
règles de périmètre contre la liste nominative.

Deux conséquences à connaître :

- une règle qui nomme un **rôle** ne se déclare qu'après un premier catalogue :
  le rôle n'existe pas avant. Les règles sur droits et applications, elles, se
  déclarent avant le mining ;
- une règle qui nomme un rôle porte sur **les droits de ce rôle, pas sur son
  port**. Quelqu'un qui détient le droit directement, sans le rôle, a le même
  pouvoir — et c'est précisément le cas que la gouvernance veut voir. Le
  contraire laisserait un conflit se cacher derrière une attribution directe.

Les références se choisissent **dans le référentiel**, par recherche, avec les
colonnes du client à côté de l'identifiant. La saisie libre demandait de
connaître `D_FIN_0042` de mémoire, c'est-à-dire précisément la colonne qui ne dit
rien.

Une fois résolue, la règle se déclenche dès qu'une identité détient au moins un
droit de chaque côté : c'est la lecture d'un auditeur — « saisir une commande »
est un pouvoir, quel que soit le droit technique qui le porte.

**Trois champs qualifient la règle**, et tous trois sont facultatifs, pour
qu'une règle déclarée avant eux se relise telle quelle :

- `severite` : un niveau pris dans `sod_severites` (§ 2). Sans niveau,
  quarante conflits se lisent tous pareil ; avec, l'écran montre d'abord le plus
  grave ;
- `processus` : le processus métier que la règle protège (achats, paie,
  trésorerie), dans les mots du client ;
- `proprietaire` : qui répond du risque. C'est lui qu'une campagne interroge.
  L'écran des conflits compte les règles actives **sans propriétaire** : ce
  n'est pas un conflit d'habilitation, c'est un défaut du programme de
  séparation lui-même, et c'est le premier qu'un auditeur relève.

La forme vient du ruleset de SAP GRC (risque, processus, niveau, propriétaire),
tel que le reproduit zsectools, et de la règle de sod-monitoring-poc. Seul le
schéma a été repris, pas le code.

### Ce qui est refusé, et ce qui est constaté

**Refusé à la saisie**, parce que cela se voit sans regarder les données :

- un **côté vide** — la règle ne se déclencherait jamais, et l'auditeur lirait
  « aucun conflit » ;
- la **même référence des deux côtés** — elle signalerait quiconque détient un
  seul de ses droits ;
- une **règle sans libellé** — personne ne saurait ce qu'elle interdit ;
- un **type inconnu** — relu silencieusement comme `droit`, il viserait un droit
  inexistant et la règle ne signalerait plus rien.

**Constaté à la résolution**, parce que cela dépend des données du jour. Une
règle dans l'un de ces états ne calcule rien, et l'écran dit lequel — les
confondre ferait chercher l'erreur au mauvais endroit :

- une référence **ne désigne plus rien** : une application retirée de l'export,
  un rôle dévalidé, un droit disparu. C'est l'export qu'il faut regarder, pas la
  règle ;
- les deux côtés **se recouvrent une fois résolus** : une application et un rôle
  qui en contient une partie. La règle signalerait alors quiconque détient un
  seul droit ;
- un côté vise **trop de droits** et a été tronqué. La troncature est
  déterministe — deux lectures des mêmes données rendent le même constat — et
  elle est annoncée plutôt que subie.

Une règle peut enfin être **suspendue** sans être supprimée — le temps d'une
remédiation. Elle ne calcule alors rien, et garde son libellé et son historique.

### Le conflit, et d'où il vient

Le conflit se calcule sur les **droits détenus**, c'est-à-dire les habilitations
chargées. Un droit reçu par un rôle y figure comme un droit reçu directement,
puisque c'est ainsi que le système d'origine l'a écrit : le cumul « à travers
les rôles » n'est pas un cas particulier à traiter, il est déjà dans les
données.

Ce qui demande de connaître les rôles, c'est l'**origine**. Le produit rend,
côté par côté, les rôles validés du porteur qui apportent les droits — et
`hors_role` quand aucun ne l'explique. Deux situations que rien ne doit
confondre :

- un conflit **hors rôle** est une exception, à traiter identité par identité ;
- un rôle qui accorde **les deux côtés à lui seul** est un défaut du modèle : il
  donne le conflit à quiconque le reçoit, y compris à ceux qui ne l'ont pas
  encore. Le corriger corrige tous les porteurs d'un coup ; corriger les
  porteurs un à un laisse le rôle le redonner.

L'écran distingue donc « quarante conflits » de « trente-huit d'entre eux
viennent d'un rôle », parce que ce ne sont pas la même décision.

### Les couples candidats

Un client devant une liste de règles vide et quarante mille droits ne la
remplira jamais. Les données, elles, savent quelque chose : si quatre cents
personnes détiennent `A`, trois cents détiennent `B`, et que **personne** ne
détient les deux, c'est une règle que l'organisation applique déjà sans l'avoir
écrite.

Sous l'hypothèse que les deux droits s'attribuent indépendamment, on attendrait
`n_a × n_b / N` personnes détenant les deux ; on en observe `n_ab`. L'écart est
ce que le produit montre — **un nombre de personnes**, pas un score entre zéro
et un dont personne ne sait ce qu'il vaut.

Rien n'y est appris et aucun modèle n'y intervient : deux lectures des mêmes
données rendent les mêmes couples, dans le même ordre. C'est la condition pour
qu'un auditeur s'en serve.

Le produit ne dit pas que le couple **doit** être séparé : deux droits jamais
réunis peuvent appartenir à deux métiers qui ne se croisent pas. Il rend le
couple et ce qui l'a motivé ; la règle reste à écrire à la main. Et il ne dit
pas « aucun risque » quand il ne trouve rien : un référentiel où tout le monde a
tout ne produit aucun couple, et c'est le référentiel le plus inquiétant qui
soit.

Quatre réglages de workspace bornent ce repérage. Ce sont des seuils de bruit et
de calcul, pas des valeurs métier :

- `sod_droits_confrontes_max` (400) — la confrontation est quadratique, et vingt
  mille droits en feraient deux cents millions de couples. Les droits les moins
  portés sont écartés les premiers ;
- `sod_support_minimal_pct` (1,0) — part de la population en deçà de laquelle un
  droit ne dit rien. Exprimé en part et non en nombre : trois personnes sur
  trois cents et trois sur trois cent mille ne sont pas le même fait ;
- `sod_cumuls_manquants_min` (5,0) — le seuil de bruit, et le seul. Il porte sur
  des personnes : « il manque deux cumuls » ne motive aucune règle ;
- `sod_couples_max` (50) — une liste de mille couples ne se relit pas.

### Le contrôle arrive avant la validation

Un candidat de mining qui réunit deux pouvoirs incompatibles est **marqué sur sa
carte**, avant qu'on l'ouvre, et détaillé dans la fenêtre de validation. Le
calcul est le même que sur le catalogue ; c'est le moment qui change, et il
change tout : un rôle validé en conflit donne le conflit à tous ses porteurs,
présents et futurs.

La fenêtre propose alors **les deux retraits possibles, chiffrés** — « sans
`D_CREER`, le rôle n'expliquerait plus 12 habilitations ; sans `D_PAYER`, 340 ».
Le produit ne choisit pas : il ne sait pas de quel pouvoir le rôle est censé
parler, et les deux chiffres côte à côte rendent la décision évidente sans qu'il
ait à trancher.

Le coût est **ce que le rôle cesse d'expliquer**, et non un accès perdu : le rôle
n'est pas appliqué, et un porteur qui détient le droit directement le garde.

Les droits contrôlés sont ceux de l'écran, pas ceux que le serveur a calculés :
l'utilisateur peut en avoir décoché, et rassurer sur un rôle que personne ne va
valider ne sert à rien. Le signalement **ne bloque pas**, et un contrôle
indisponible n'affiche rien — écrire « aucun conflit » alors qu'on n'a pas pu
regarder est le seul mensonge que cet écran puisse produire.

### Les quatre endroits où un rôle se décide

Le contrôle ne vaut que s'il est présent partout où un rôle prend forme. Il
l'est désormais aux quatre :

| Où | Ce qui est contrôlé | Ce que ça coûte |
|---|---|---|
| carte de candidat | les droits du candidat | un appel pour toute la liste |
| fenêtre de validation | les mêmes, avec les porteurs | les deux retraits chiffrés |
| **compositeur** | l'union des sous-rôles, des droits cochés et des exceptions saisies | un appel par geste, retardé |
| **catalogue** | les rôles validés | un appel, **aucune habilitation lue** |

Le compositeur est le seul endroit où un rôle se fabrique **à la main** : il
échappait au signalement que recevait un candidat de mining, c'est-à-dire que
le chemin le plus direct pour créer un rôle en conflit était aussi le seul qui
ne prévenait pas. Il contrôle donc à chaque changement de composition, sur
l'**union** des droits — deux sous-rôles partagent souvent des droits, et une
règle se juge sur un ensemble. Aucun porteur n'est envoyé, et c'est exact : le
rôle n'existe pas encore, il n'y a rien à chiffrer.

Le catalogue, lui, porte la marque sur la carte du rôle, avec le **nom de la
règle et ses deux côtés** : « ce rôle enfreint une règle » n'aide personne à
décider, là où « il réunit la création d'un fournisseur et le paiement » se
traite. Le calcul ne lit **aucune habilitation et aucune identité** — un rôle
est en conflit par ce qu'il accorde, pas par qui le porte — ce qui le rend assez
peu cher pour marquer le catalogue à chaque affichage, et exact pour un rôle
qui n'a encore aucun porteur.

Une différence assumée avec le mining : quand le contrôle **n'a pas pu être
fait**, ces deux écrans le disent. Une marque absente se lit « aucun conflit » ;
si personne n'a regardé, l'écran doit l'écrire, sans quoi il rassure sur un
contrôle qui n'a pas eu lieu.

### Ce que les chiffres du mining veulent dire

Trois grandeurs se lisent côte à côte sur l'écran de mining, et elles doivent se
rapporter au **même tout** pour qu'un arbitrage ait un sens :

- la **couverture** est la part des habilitations réelles que les rôles
  expliquent ;
- le **sur-octroi** est le nombre de couples (identité, droit) que les rôles
  accorderaient à des personnes qui ne les détiennent pas ;
- la **part de sur-octroi** rapporte le second aux **mêmes** habilitations que
  la première. Elle peut dépasser cent pour cent, et c'est une information : un
  modèle qui accorde deux fois plus en trop qu'il n'existe d'habilitations
  réelles est un modèle qu'on ne veut pas.

Elle était auparavant rapportée à la somme de ce que les rôles retenus
accordent — un dénominateur qui **grandit avec le nombre de rôles**. Deux
modèles n'étaient donc pas comparables sur ce taux, ce dont le choix d'un seuil
de similarité dépend pourtant entièrement.

**Le seuil de similarité et son front de Pareto.** Les seuils se comparent sur
la couverture et sur le sur-octroi **en valeur absolue** : les deux points
décrivent le même référentiel, leurs nombres d'habilitations en trop sont
directement comparables.

Contrairement à l'intuition, **baisser le seuil ne fait pas toujours monter le
sur-octroi** : un seuil plus lâche produit d'autres candidats, parfois mieux
ajustés. C'est mesuré, et c'est ce qui rend le front utile — si les deux
grandeurs variaient de façon monotone, aucun point n'en dominerait un autre.

**La courbe d'arbitrage applique la parcimonie.** Elle ne la recevait pas :
l'utilisateur réglait son curseur de parcimonie, puis choisissait sa position
d'arbitrage sur une courbe calculée sans elle. Mesuré sur un référentiel
construit pour cela : quatre rôles annoncés à chaque position, deux produits.

**Un modèle tronqué le dit.** Quand le plafond de rôles arrête la sélection
alors qu'il restait des candidats, le résultat porte `tronquee`. Un modèle
coupé présenté comme complet fait décider sur un catalogue qui n'est pas celui
que le moteur a trouvé.

**Le nom d'un rôle métier porte son attribut autant que sa valeur.** Sans lui,
`service = Lyon` et `site = Lyon` sortaient sous le même nom : deux
populations, deux ensembles de droits, un seul nom dans le catalogue.

**Les identifiants ne sont jamais tirés au hasard.** Ni pour un rôle métier —
c'est sa règle et ses droits — ni pour un rôle applicatif — c'est son ensemble
de droits. Un identifiant aléatoire rendait impossible de rattacher une
décision au candidat sur lequel elle a été prise : un rôle refusé revenait
proposé au calcul suivant.

### Les droits conservés d'un poste précédent

Le constat que les clients demandent en premier, et que presque aucun outil ne
rend : quelqu'un change de service, reçoit les accès de son nouveau poste, et
**garde ceux de l'ancien**. Personne ne les retire, parce que personne ne sait
qu'ils sont là.

Le problème apparent est qu'il faudrait un historique — deux exports à deux
dates, ou une colonne portant le poste précédent — et qu'un référentiel n'en a
presque jamais. **Un seul instantané suffit**, et c'est l'idée du mécanisme :

> Un droit résiduel n'est pas un droit *rare*. C'est un droit **typique
> d'ailleurs**.

Sept droits que personne d'autre du service Achats ne détient sont peut-être
sept exceptions. Mais si ces sept droits sont détenus par quatre-vingt-neuf
pour cent du service Comptabilité, ce ne sont pas des exceptions : c'est le
poste occupé avant. Le produit **nomme le service d'origine sans qu'on le lui
ait dit**.

**Le regroupement vient de l'utilisateur.** Le produit ne connaît aucune colonne
des fichiers du client — ni `service`, ni `direction`, ni `jobtitle` — et en
choisir une d'office produirait des constats sur un regroupement que personne
n'a voulu. L'écran propose les mêmes colonnes que le mining métier, par la même
route, et ne calcule rien tant que rien n'est choisi.

**La rareté se mesure sans la personne elle-même.** Une identité fait partie de
son propre groupe et détient le droit qu'on examine : `1 / 34` sur un service de
trente-quatre, `1 / 10` sur un service de dix. Le même fait — « elle est la
seule » — donnerait deux nombres différents, et un seuil en pourcentage
laisserait passer les petits groupes. La part porte donc sur **les autres** :
`(porteurs − 1) / (effectif − 1)`, et « elle est la seule » vaut zéro quelle que
soit la taille du groupe.

**Le produit ne dit pas que la personne a changé de poste.** La mobilité est
l'explication la plus fréquente de cette forme, pas la seule : une double
casquette, un remplacement, un transfert de mission la produisent aussi. Le
produit rend le rapprochement et ce qui l'a motivé ; conclure appartient à celui
qui connaît l'organisation.

Il ne dit pas non plus « aucun droit résiduel » quand il ne trouve rien :
l'écran annonce **combien d'identités ont été analysées sur combien**, parce
qu'« aucun constat » sur une population dont les trois quarts n'ont pas de
groupe exploitable ferait conclure à un référentiel sain.

Rien n'y est appris et aucun modèle n'y intervient : deux lectures des mêmes
données rendent les mêmes constats, dans le même ordre.

Cinq réglages de workspace bornent le repérage. Ce sont des seuils de bruit, pas
des valeurs métier :

- `mouvement_groupe_min` (5) — effectif en deçà duquel un groupe ne dit rien.
  « Personne d'autre de son service ne l'a » sur un service de trois ne signifie
  rien : c'est peut-être les autres qui sont l'exception. La borne vaut pour le
  groupe examiné **et** pour le groupe d'origine présumé ;
- `mouvement_rarete_max_pct` (5,0) — part des autres membres du groupe en deçà
  de laquelle un droit est atypique pour cette personne. Zéro signifie « elle
  est la seule » ;
- `mouvement_typique_min_pct` (60,0) — part d'un autre groupe au-delà de
  laquelle le droit y est typique. C'est ce qui distingue un droit résiduel
  d'une exception : une exception n'est typique nulle part ;
- `mouvement_droits_min` (2) — nombre de droits concordants en deçà duquel
  aucun constat n'est rendu. Un droit atypique isolé est du bruit ; deux droits
  qui désignent **le même** autre groupe ne se produisent pas par hasard ;
- `mouvement_constats_max` (200) — une liste de mille lignes ne se relit pas.

### L'exception assumée

Un outil de gouvernance meurt rarement en se trompant. Il meurt en devenant du
bruit : le deuxième chargement refait apparaître tout ce qu'on a déjà examiné et
tranché, et on cesse de lire l'écran.

La **dérogation** est la réponse, et elle tient en une phrase : *ce constat-là
est connu, accepté par quelqu'un, pour cette raison, jusqu'à cette date.*

Trois refus font toute sa conception :

- **aucune dérogation sans motif.** Une exception sans raison écrite est
  indiscernable d'un oubli, et six mois plus tard personne ne sait si la
  décision a été prise ou subie ;
- **aucune dérogation sans échéance.** Une dérogation perpétuelle n'est pas une
  exception, c'est une **suppression silencieuse de la règle** — avec le
  désavantage supplémentaire que la règle reste affichée et qu'on la croit
  appliquée. L'échéance est obligatoire, bornée, et jamais reconduite d'elle-même ;
- **aucune dérogation ne cache le constat.** Un conflit couvert reste compté et
  reste affiché, rangé à part et daté. L'écran montre deux nombres — ce qui
  reste à traiter, et ce qui a été accepté — parce qu'un seul ferait croire qu'il
  reste tout à faire, ou cacherait à un auditeur ce qui a été assumé.

Une dérogation expirée n'est pas supprimée : elle reste lisible et raconte ce qui
a été décidé et quand cela a cessé de valoir. Ce qui disparaît sans laisser de
trace, c'est une décision perdue. **Retirer** une dérogation est en revanche une
décision — le constat revient dans ce qui reste à traiter — et elle laisse elle
aussi une trace.

Deux champs ne sont **jamais** acceptés de l'appelant : la date d'octroi et
l'auteur. Les laisser écrire permettrait d'antidater une décision ou de
l'attribuer à quelqu'un d'autre, et c'est l'objet qui fait taire un signalement.

Deux réglages de workspace bornent le mécanisme :

- `derogation_duree_max_jours` (365) — une organisation qui revoit ses
  exceptions chaque trimestre et une autre qui les revoit chaque année ne
  veulent pas la même borne. Mais une borne existe toujours : sans elle,
  « jusqu'au 31 décembre 2099 » redevient une dérogation perpétuelle écrite
  autrement ;
- `derogation_preavis_jours` (30) — à partir de quand une échéance qui approche
  est annoncée. C'est du travail qui arrive, et le dire tard revient à ne pas le
  dire.

- `derogation_controle_exige` (non) — une dérogation doit-elle citer un
  contrôle compensatoire qui tourne pour couvrir son constat ? Décochée à la
  création du workspace : l'exiger avant d'avoir décrit ses contrôles ferait
  réapparaître d'un coup toutes les exceptions déjà accordées.

Ces trois réglages ne s'appliquaient pas avant le lot 86. Ils se lisaient par
une méthode qui ne rendait que les attributs de la configuration chargée, et
aucun des trois n'en avait : la valeur écrite dans le workspace était ignorée,
et le repli du code (365 jours, 30 jours) s'appliquait partout sans que rien le
signale. Les seuils des droits conservés (`mouvement_*`) et la borne des
couples candidats de séparation (`sod_couples_max`) avaient le même défaut.
Les trois familles de réglages sont maintenant lues, et un test le vérifie pour
chacune.

- `derogation_approbation_exigee` (non) — une dérogation doit-elle être
  approuvée par une autre personne que celle qui la demande ? Cochée, une
  dérogation naît **demandée** et ne couvre rien tant qu'elle n'est pas
  approuvée (`POST /api/v1/derogations/{id}/approuver`). Le serveur refuse que
  le demandeur approuve lui-même : une exception approuvée par la personne qui
  en profite ne sépare rien. Un refus (`…/refuser`) exige un motif. La
  dérogation refusée reste lisible, avec son motif, et ne couvre rien. Une
  dérogation tranchée ne se retranche pas : on la retire, puis on en demande
  une autre. Une dérogation écrite avant ce réglage se relit comme accordée.

**Le programme se compte lui-même.** Au-dessus des conflits, l'écran compte
trois défauts du contrôle, sans en faire un score : les règles actives sans
propriétaire, les règles suspendues et les dérogations en attente de décision.
Ce ne sont pas des conflits d'habilitation, et chacun dit ce qu'il faut aller
faire.

### Le contrôle compensatoire — `/api/v1/controles`

Une dérogation dit que tel conflit est accepté, pour telle raison, jusqu'à
telle date. Un auditeur demande aussitôt **ce qui compense**. Le contrôle
compensatoire est donc un objet à part entière, pas une phrase dans un motif :

| Champ | Ce qu'il porte |
|---|---|
| `libelle` | ce que le contrôle vérifie, dans les mots du client |
| `executant` | qui l'exécute |
| `relecteur` | qui relit l'exécution — **jamais l'exécutant** : un contrôle relu par la personne qui l'a fait ne sépare rien, et il est refusé à la saisie |
| `age_max_jours` | au-delà de cet âge, la dernière exécution ne compense plus rien. C'est la fréquence du contrôle, exprimée comme une borne |
| `actif` | un contrôle suspendu ne compense rien |

Chaque **exécution** est consignée avec sa date, son exécutant, son relecteur,
son résultat (`conforme` ou `non_conforme`) et **l'endroit où se trouve la
preuve** (un ticket, un dossier, un lien) ; le produit ne stocke pas la preuve.
Deux champs viennent du serveur et ne sont jamais acceptés de l'appelant : qui
consigne, et quand. Une exécution ne se retire jamais : c'est une piste, pas un
état. Retirer un contrôle du catalogue ne réécrit pas ses exécutions.

Une dérogation peut **citer** un contrôle (`controle`). Elle cesse alors de
couvrir son conflit dès qu'une de ces raisons apparaît, et chacune est nommée à
l'écran :

- le contrôle cité n'existe plus, ou il est suspendu ;
- il n'a jamais été exécuté ;
- sa dernière exécution date de plus de `age_max_jours` ;
- sa dernière exécution n'est pas conforme. C'est bien la **dernière** qui
  décide : une exécution conforme de janvier ne rachète pas un échec de mars ;
- sa dernière exécution n'a pas été relue par une autre personne que son
  exécutant ;
- le workspace exige un contrôle, et la dérogation n'en cite aucun.

Une dérogation dans ce cas **reste enregistrée**. Le conflit revient dans ce
qui reste à traiter, avec la mention « dérogation sans effet » et la liste de
ses raisons. Sans cela, l'auditeur lirait « non traité » là où une décision
existe et a cessé de valoir. La forme vient de MaxwellM-GRC/sod-monitoring-poc
(MIT) ; le calcul a été réécrit pour Kovex.

Le mécanisme est **générique** : une dérogation porte une famille et une cible,
et chaque famille déclare les clés que sa cible doit nommer.

| Famille | Cible | Où elle se donne |
|---|---|---|
| `separation` | `regle`, `identite` | le détail d'une règle en conflit |
| `ecart_au_pair` | `identite`, `droit` | le panneau d'une identité, sur un droit que ses pairs n'ont pas |

Un écart justifié **reste affiché** : dans le panneau, avec sa réponse, et dans
l'écran des droits conservés, marqué « justifié » (`justifie: true` sur le
droit). Il reste compté : le constat ne change pas, il a reçu une réponse. La
cible nomme la personne *et* le droit — justifier une personne entière ferait
taire les droits qu'elle recevra demain. Échéance, contrôle compensatoire,
approbation par une autre personne : les règles des dérogations de séparation
s'appliquent telles quelles, par le même code. Le sur-octroi accepté et le
compte dormant assumé entreront de la même façon.

### Ce que le produit ne fait pas

Il ne retire aucun droit et ne rejette aucun rôle. Un conflit de séparation des
tâches est un constat d'audit : il se rend **entier**, sans seuil qui en
cacherait la queue, et la remédiation appartient à celui qui répond du contrôle
interne.

---

## 3 ter. Cohérence des valeurs et recodage

Le mining métier regroupe les identités par valeurs d'attributs **identiques**,
au sens de la chaîne de caractères. `Infirmier`, `infirmière`, `INF`, `Inf.` et
`Infirmier ` font cinq populations.

Sur un effectif minimal à quinze, soixante infirmiers écrits de cinq façons
donnent cinq groupes de douze. Aucun n'atteint le seuil, le rôle n'est pas
trouvé — et **rien à l'écran ne dit qu'il a été manqué**. C'est le pire mode de
défaillance d'un outil de role mining : un silence qui ressemble à un résultat.

**Aucune intelligence artificielle n'entre dans le calcul.** Le repérage est
local, déterministe et rejouable ; ce qui est enregistré est une **table de
recodage**, et c'est elle, seule, que le calcul relit ensuite. Deux exécutions
sur les mêmes fichiers et la même table donnent le même résultat.

### Ce que le repérage compare

Six signaux, et aucun ne suppose de nomenclature : le produit ne compare les
valeurs qu'entre elles.

| Signal | Ce qu'il attrape |
|---|---|
| `forme` | casse, accents, ponctuation, espaces multiples |
| `frappe` | faute de frappe, à distance d'édition bornée |
| `pluriel` | singulier et pluriel |
| `abreviation` | sigle par préfixe court ou par initiales — `INF`, `RRH`, `CDI` pour « Contrat à durée indéterminée » |
| `troncature` | libellé rogné **au milieu d'un mot** à l'export |
| `effectif` | une valeur rare face à une valeur fréquente |

Le sixième ne rapproche rien à lui seul : il **qualifie** un rapprochement déjà
motivé. Trois `Infimier` contre huit cent douze `Infirmier` ne prouvent rien par
eux-mêmes ; adossés à une distance d'édition de un, ils emportent la décision.

**Les initiales sautent les mots outils, sans dictionnaire.** Un sigle ne garde
pas « à », « de », « des » : `CDI` n'est pas `CADI`, `DRH` n'est pas `DDRH`. Un
mot plus court que `coherence_longueur_racine_min` peut donc être sauté ; un mot
plus long doit donner sa lettre. « Chef de service » admet `CS` et `CDS` ;
« Chef de service informatique » n'admet pas `CS`. Aucune liste de mots outils
n'est écrite nulle part : la longueur suffit, dans toutes les langues.

**Deux exclusions délibérées**, et elles vont dans le même sens : entre manquer
un rapprochement et en inventer un, le produit manque.

- Le **suffixe commun** n'est pas un signal. « Secrétaire médicale » et
  « Assistante médicale » le partagent et ne désignent pas la même chose.
- Un **préfixe qui s'arrête sur un mot entier** n'est pas une troncature.
  « Cadre » est le début de « Cadre de santé », et les deux portent des droits
  différents : les fusionner fabriquerait un rôle faux. Une troncature coupe au
  milieu d'un mot.

### Ce que l'écran montre avant qu'on accepte

La **conséquence** du regroupement, qui est le point décisif : « ces cinq
valeurs font une population de 63, au-dessus de votre effectif minimal de 15 —
elle était invisible au mining ». C'est la seule mesure qui justifie
l'opération, et elle est à l'écran avant l'acceptation, pas après.

La forme retenue est la valeur **la plus fréquente**, jamais un choix du
produit — entre `Infirmier` et `INF`, c'est l'organisation qui tranche. Elle est
modifiable, y compris vers une valeur qui n'est dans aucune des deux : un client
peut profiter du recodage pour adopter sa nomenclature cible.

**Un refus est mémorisé**, et il porte sur la forme repliée. Sans ce
repliement, un refus se contournerait en changeant un accent : dire que `Cadre`
et `Cadre de santé` sont distincts doit valoir pour `Cadre de sante`. Un refus
n'est pas contourné par transitivité non plus : une grappe ne peut pas contenir
deux valeurs que l'utilisateur a dites distinctes.

### Seuils du workspace

| Réglage | Défaut | Ce qu'il fait |
|---|---|---|
| `coherence_distance_edition_max` | 2 | Au-delà, deux valeurs ne sont plus une faute de frappe mais deux mots. |
| `coherence_longueur_racine_min` | 4 | En deçà, une racine commune ne prouve rien : « Com » commence « Comptable » comme « Commercial ». Sépare aussi le sigle du libellé tronqué, et dit quels mots un sigle peut sauter. |
| `coherence_ecart_effectif_significatif` | 20 | Rapport au-delà duquel une valeur est dite rare face à une autre. Qualifie, ne rapproche jamais. |
| `coherence_valeurs_analysees_max` | 2000 | Borne de calcul, pas choix métier : le repérage compare deux à deux. Les plus fréquentes d'abord, et le dépassement est **annoncé**. |
| `coherence_valeurs_soumises_max` | 300 | **Combien de valeurs quittent le système d'information** à chaque demande faite à un modèle. Celui-ci n'est pas un seuil de bruit : c'est une décision, et elle se règle plus bas que le plafond d'analyse. |
| `coherence_part_typee_max` | 0.5 | Au-delà, la colonne porte surtout des nombres ou des dates et n'est pas analysée — `2024-01-01` et `2024-01-02` sont proches et n'ont rien à voir. Calculé sur les valeurs, jamais déduit d'un nom de colonne. |

### La table, septième opération de transformation

Une grappe acceptée devient une entrée de l'opération `recode` du pipeline du
workspace. Elle s'ordonne avec les autres — recoder puis élaguer n'est pas
élaguer puis recoder —, s'exporte avec le workspace, conserve la valeur
d'origine, et **s'édite à la main sans aucune analyse** : c'est le mode dégradé,
et c'est aussi le mode expert pour un client qui possède déjà sa table.

Rien n'est jamais écrit dans les fichiers sources.

### Le critère de livraison

Le lot n'a d'intérêt que s'il fait trouver des rôles qui n'étaient pas trouvés,
et cela se mesure. Le banc dégrade une colonne, lance le mining sur le
référentiel propre, sur le dégradé, puis sur le dégradé recodé, et exige que le
**repérage local seul** restitue ce que la dispersion a fait perdre. Faire
dépendre le gain d'un modèle externe contredirait la promesse du serveur isolé.

Le banc vérifie aussi la régression qui coûterait le plus cher : deux fonctions
proches et légitimement distinctes ne doivent pas fusionner.

---

## 3 bis. Assistance par modèle

Facultative, **fermée par défaut**. Un seul usage existe aujourd'hui — proposer
un nom et une description pour un rôle découvert. Il ne décide rien, et la
proposition ne s'applique que si quelqu'un la reprend.

Les réglages sont à deux endroits, parce qu'ils relèvent de deux responsables :
ouvrir une sortie réseau est une décision d'infrastructure, autoriser une
catégorie de données à l'emprunter **pour une question donnée** est une
décision de l'administrateur applicatif.

### `KOVEX_ANNOTATEUR_URL`, `KOVEX_ANNOTATEUR_MODELE`, `KOVEX_ANNOTATEUR_CLE`, `KOVEX_ANNOTATEUR_DELAI_S`

Environnement du serveur. Sans adresse **ni** modèle, l'annotateur n'existe pas
— aucune valeur par défaut n'est posée, parce qu'un oubli de configuration
ferait d'un serveur d'habilitations un client réseau silencieux.

Ouvrir cette sortie est une décision d'infrastructure, et ces valeurs ne
s'exportent jamais avec un workspace. La clé ne quitte pas l'en-tête
d'autorisation : elle n'est ni journalisée, ni rendue par l'API, qui ne publie
que l'**hôte** de l'adresse — assez pour dire si l'envoi quitte la machine,
trop peu pour transporter un secret glissé dans un chemin.

Le protocole visé est `POST {URL}/chat/completions`, celui que parlent les
serveurs locaux comme Ollama. Aucune dépendance n'est ajoutée.

### `KOVEX_ANNOTATEUR_URL_<USAGE>` et ses trois compagnons

Facultatifs. Ils remplacent le réglage commun **pour un usage donné**, le code
de l'usage écrit en majuscules :
`KOVEX_ANNOTATEUR_URL_NOMMAGE_DE_ROLE`, `KOVEX_ANNOTATEUR_MODELE_NOMMAGE_DE_ROLE`,
`KOVEX_ANNOTATEUR_CLE_NOMMAGE_DE_ROLE`, `KOVEX_ANNOTATEUR_DELAI_S_NOMMAGE_DE_ROLE`.

Un client peut ainsi faire tourner le nommage sur un petit modèle local et
n'ouvrir aucune autre sortie — ou l'inverse. Le trajet se décide comme la
matière : usage par usage.

**Le groupe se prend entier ou pas du tout.** Dès qu'une adresse propre à
l'usage est définie, le modèle, la clé et le délai sont lus sur le même
suffixe, et jamais complétés par les valeurs communes. Mélanger les deux
enverrait la clé configurée pour un point de terminaison à un autre : ce n'est
pas une commodité qu'on accorde à une variable d'environnement, et la fuite
serait invisible puisque la clé n'est ni rendue ni journalisée.

### Le protocole : agnostique du moteur, et vérifié comme tel

Le produit s'installe chez le client avec le moteur que le client sert — un
petit modèle local sur une machine sans accès, un moteur d'entreprise, un
service distant. Il ne choisit pas, ne recommande pas, et ne doit pas dépendre
de ce choix. Deux choses se distinguent, et une seule relève du produit :

- **le jugement.** Savoir que `jobtitle` porte du métier et `last_name` non. Un
  modèle vaut ce qu'il vaut ; aucun code ne rendra bon celui qui se trompe. Ce
  n'est pas grave : le produit ne décide rien sur cette base, il propose, et un
  humain tranche.
- **le protocole.** Obtenir une réponse exploitable quelle que soit la façon
  dont le modèle la met en forme. Cela relève entièrement du produit.

Quatre mécanismes, et aucun ne présume du fournisseur.

**La contrainte est négociée, jamais présumée.** Certains moteurs savent
imposer un schéma JSON à la génération, d'autres seulement un objet JSON,
d'autres rien. Écrire en dur lequel fait quoi serait faux le jour où le client
change de version — et ce serait un fichier que personne ne penserait à
relire. Le produit propose donc le niveau le plus fort et redescend d'un cran à
chaque refus **du serveur** : une erreur 4xx, qui dit « je ne sais pas faire
ça », et non une panne, qui dit « je ne réponds pas ». Ce sont les **refus**
qui sont retenus, pour la durée du processus et par point de terminaison — pas
les acceptations : qu'un serveur accepte un objet JSON ne prouve pas qu'il
refuse un schéma, puisque la demande en cours n'en avait peut-être pas.

Rien n'est écrit sur disque : c'est une observation sur le serveur en face, pas
un réglage du client, et elle doit se refaire si l'exploitant change de moteur
derrière la même adresse.

**La lecture est tolérante à la mise en forme.** L'objet JSON est cherché
*dans* le texte rendu, qu'il soit encadré de ```` ``` ````, précédé d'une
phrase ou suivi d'un commentaire. L'enveloppe du moteur l'est aussi :
`choices[0].message.content` est répandu, il n'est pas universel.

**Les formes équivalentes sont reconnues, jamais devinées.** Une liste nue au
lieu d'un objet, une enveloppe nommée autrement, un dictionnaire `{colonne:
classe}` au lieu d'une liste d'objets, des clés en anglais, deux champs
intervertis : ce sont des écritures différentes de la même information. Chacune
se reconnaît de façon déterministe, et la limite est nette — une enveloppe qui
contient deux listes n'est pas reconnue, parce que choisir laquelle serait
deviner.

**Une reprise guidée, une seule fois.** Si rien n'est exploitable, la demande
repart avec la réponse reçue sous les yeux du modèle et le rappel de la forme
attendue. Deux reprises seraient une boucle sur un modèle qui ne sait pas
répondre, payée en secondes par l'utilisateur qui attend.

**Ce que le protocole ne fait pas.** Il rend lisible ce qui a été dit ; il ne
rend pas vrai ce qui est faux. Une valeur que le référentiel ne porte pas reste
écartée, et un modèle qui juge mal juge mal. `tests/test_banc_protocole.py`
rejoue un catalogue de réponses réellement rencontrées et exige de chacune
qu'elle donne le bon résultat, ou un refus explicite : c'est ce qui rend
l'agnosticisme opposable au lieu d'être une promesse.

### `assistance` — la matrice usage × matière

Configuration du **workspace**, tout fermé. Elle décide de ce qui a le droit de
quitter le système pour *ces* données, **et pour quelle question**. Ce sont des
politiques, pas des secrets : elles s'exportent avec le workspace, et c'est
voulu — la règle voyage avec les données qu'elle protège.

```json
"assistance": {
  "nommage_de_role": {
    "actif": true,
    "matiere": ["libelles_de_droits", "noms_valides"]
  },
  "droits_sensibles": {
    "actif": false,
    "matiere": []
  },
  "attributs_pertinents": {
    "actif": false,
    "matiere": []
  }
}
```

| Usage | Ce qu'il fait | Matière nécessaire |
|---|---|---|
| `nommage_de_role` | Propose un intitulé et une description pour un rôle candidat. | au moins une des trois ci-dessous |
| `droits_sensibles` | Propose les fragments de nom qui signalent un droit à regarder de près. | `libelles_de_droits` |
| `attributs_pertinents` | Distingue, parmi les colonnes d'identités, le métier de l'identifiant. | `noms_de_colonnes` |
| `coherence_des_valeurs` | Rapproche les valeurs d'une colonne qui désignent la même chose — `AS` et `Aide-soignant`. | `valeurs_d_attribut`, **colonne par colonne** |
| `explication_de_role` | Rédige le paragraphe qui explique un rôle à un responsable d'application. | au moins une parmi `libelles_de_droits` et `regle_metier` |
| `explication_de_conflit` | Rédige le paragraphe qui dit pourquoi une règle de séparation en conflit est un risque et ce qui le réduirait. | au moins une parmi `regles_de_separation` et `libelles_de_droits` ; `noms_valides` facultative |
| `serveur_mcp` | Répond, en lecture seule, à un agent extérieur branché par le protocole MCP (voir 03-exploitation § 9 bis). N'appelle aucun modèle : tout ce qu'il rend part vers l'agent. Aucune personne n'est jamais nommée. | aucune ; `libelles_de_droits`, `noms_valides`, `regles_de_separation` facultatives |
| `agent_de_navigation` | Comprend une question posée en français dans l'assistant, et la traduit en une question que le produit sait calculer. | `question_libre` |

**`agent_de_navigation` : le modèle ne choisit qu'un mot.** Il reçoit la
question et la liste fermée des questions que le produit sait calculer ; il
rend le code de l'une d'elles, et rien d'autre. Aucune phrase, aucun chiffre,
aucun nom de rôle, de droit ou d'identité. Un chiffre inventé n'est donc pas
contrôlé après coup comme dans `explication_de_role` : il est impossible.

La matière `question_libre` est la question elle-même, telle que
l'utilisateur l'écrit. C'est la moins prévisible du catalogue — « quels droits
a Jean Dupont » contient un nom de personne que rien ne filtre — et c'est pour
cela qu'elle est déclarée : le produit ne peut pas router une question sans la
lire, et un modèle ne peut pas la lire sans la recevoir. L'arbitrage appartient
à l'administrateur.

Usage fermé, **l'assistant continue de répondre** : le routage local par
mots-clés reconnaît la plupart des questions sans rien faire sortir. Les mots
de chaque question vivent dans les catalogues de traduction
(`agent.intention.<code>.mots`), donc dans les trois langues, et s'enrichissent
du vocabulaire d'une maison sans toucher au code.


**`explication_de_role` : les chiffres ne sortent pas du modèle, ils y
entrent.** Les grandeurs d'un rôle — population, droits, couverture,
sur-octroi — ne sont pas une matière : ce sont des comptes, ils ne désignent
personne, et ils partent toujours. Ce qui se décide est ce qui les accompagne.

Tout nombre écrit dans la phrase rendue doit figurer parmi ceux transmis. Le
contrôle relève les nombres du texte et les confronte à la liste envoyée ; un
seul intrus fait **refuser** la phrase — jamais corriger, jamais tronquer. Une
phrase amputée de son chiffre faux resterait une phrase que le produit a
réécrite, sans que le lecteur puisse le savoir.

L'arrondi d'un nombre transmis est accepté : le produit donne `87.5` et la
phrase écrit « 87 % ». Refuser l'arrondi rendrait l'usage inutilisable sans
rien protéger — le lecteur ne peut pas être trompé par un nombre moins précis
que celui d'origine.

La limite est connue et écrite : un nombre en toutes lettres — « trois cents
personnes » — n'est pas relevé. La consigne demande des chiffres, et les modèles
en écrivent quand on leur en donne ; la garantie porte sur les chiffres.

**`explication_de_conflit` : la règle, jamais les personnes.** L'écran
n'envoie que l'identifiant de la règle ; le serveur relit tout le reste sur les
données du jour. Les comptes de la règle — identités en conflit, portées par un
rôle, hors rôle, couvertes par une dérogation, rôles qui portent les deux
côtés, droits de chaque côté — partent toujours. Aucun identifiant de personne
ne part, quelle que soit la configuration. La matière `regles_de_separation`
ouvre le libellé de la règle, son processus et sa sévérité ;
`libelles_de_droits` ouvre les droits que les conflits réunissent vraiment, les
plus fréquents d'abord (douze au plus par côté) ; `noms_valides` ajoute le nom
des rôles qui portent les deux côtés. Le contrôle des nombres est celui de
`explication_de_role`, et le paragraphe est effacé dès que le détail de la
règle est relu : il cite des comptes, et des comptes qui ont changé le
rendraient faux.

**`nommage_de_role` et `droits_sensibles` réclament la même matière**, et c'est
exactement le cas que cette matrice existe pour tenir : autoriser les libellés
de droits pour obtenir des noms de rôles n'autorise pas à les envoyer pour une
autre question. Les deux se règlent séparément.

La règle est une **intersection, jamais une union** : un appel n'a lieu que si
l'usage est actif *et* que chaque matière dont il a besoin est autorisée *pour
cet usage*. Une autorisation donnée à une question ne vaut pas autorisation
pour toutes les questions suivantes — c'est la §2 de la licence, *aucune
concession implicite*, appliquée aux données du client.

Trois règles de lecture, toutes fermantes :

- usage absent du document → inactif ;
- matière absente de sa liste → refusée ;
- usage ou matière que cette version ne connaît pas → ignorés **et** signalés
  au chargement du workspace. Une configuration écrite pour une version plus
  récente ne doit ni ouvrir une porte que cette version ignore, ni disparaître
  en silence.

| Matière | Fermée | Ouverte |
|---|---|---|
| `libelles_de_droits` | le modèle ne voit aucun libellé | il voit les libellés, plafonnés à 40, le reste étant annoncé comme non transmis, **et les applications** auxquelles ces droits se rattachent |
| `regle_metier` | il ne voit aucune valeur d'attribut | il voit la règle, par exemple `service = Comptabilité` |
| `noms_valides` | il ne voit aucun nom déjà retenu | il voit jusqu'à 8 rôles déjà validés, comme exemples de convention |
| `noms_de_colonnes` | il ne voit aucune colonne | il voit les **noms** des colonnes du référentiel d'identités, jamais leurs valeurs |
| `valeurs_d_attribut` | il ne voit aucune valeur | il voit les valeurs distinctes des **colonnes explicitement ouvertes**, les plus fréquentes d'abord, plafonnées par `coherence_valeurs_soumises_max` |
| `question_libre` | il ne reçoit aucune question : l'assistant s'en tient au routage local par mots-clés | il reçoit la question telle qu'elle est écrite, et rien d'autre — ni chiffre, ni nom de rôle, de droit ou d'identité |

### `coherence_des_valeurs` : la seule autorisation qui se donne colonne par colonne

C'est le seul usage qui fait sortir des **valeurs**, et c'est la matière la plus
sensible du catalogue. Un nom de colonne dit comment le client range son
référentiel ; ses valeurs disent ce que ses gens font et où ils sont. Une
colonne `service` d'un hôpital contient `Oncologie` et `Psychiatrie` — et
l'effectif de chacune part avec.

Ouvrir « les valeurs d'attribut » en bloc n'aurait donc pas de sens : la colonne
`type_de_contrat` et la colonne `service` ne posent pas la même question, et un
administrateur qui accepte que la première sorte n'a rien dit de la seconde.
L'autorisation se donne colonne par colonne :

```json
"coherence_des_valeurs": {
    "actif": true,
    "matiere": ["valeurs_d_attribut"],
    "colonnes": [
        {"referentiel": "identities", "colonne": "fonction"}
    ]
}
```

Aucune colonne par défaut, donc rien ne sort. Une colonne nouvellement apparue
dans les fichiers du client n'est pas ouverte parce qu'elle ressemble à une
colonne ouverte. Le champ `colonnes` n'est écrit que pour les usages qui s'en
servent : une liste vide sous un usage qui ne se délimite pas se lirait comme un
réglage qui existe, et elle est **refusée** à l'enregistrement plutôt
qu'ignorée.

**`noms_de_colonnes` y est facultative**, et la nuance a un effet réel. Savoir
que ces valeurs viennent d'une colonne nommée `fonction` oriente fortement la
réponse ; ne pas le savoir la dégrade sans l'empêcher. C'est aussi le premier
cas où le second contrôle d'envoi — « cette matière-là a-t-elle le droit de
partir ? » — n'est pas redondant avec « la question peut-elle être posée ? ».

**Une colonne typée n'est jamais soumise**, quelle que soit l'autorisation :
rien de ce qu'un modèle dirait de `2024-01-01` ne vaut le fait de l'avoir
envoyé.

**Ce que le modèle rend est confronté au référentiel.** Une valeur absente est
retirée du groupe, un groupe réduit à une valeur est écarté, une valeur ne peut
appartenir qu'à un groupe, un groupe contenant une paire déjà refusée est jeté
entier, et un groupe que le repérage local propose déjà n'est pas reproposé.
Les effectifs et la conséquence du regroupement sont calculés par le produit,
jamais lus dans la réponse. Le compte de ce qui a été écarté est rendu à
l'écran : s'il grossit, c'est ce modèle-là qui ne convient pas.

**Reprise de l'existant.** Un workspace créé avant cette version ne porte que
les trois drapeaux `annotateur_envoie_libelles_de_droits`,
`annotateur_envoie_regle_metier` et `annotateur_envoie_noms_valides`. En
l'absence du bloc `assistance`, ils sont lus comme la configuration du nommage,
et **d'aucun autre usage** — c'est ce qu'ils voulaient dire, et c'est la
lecture qui n'ouvre rien. Dès que le bloc existe, il fait seul foi : sans quoi
un administrateur qui ferme une matière dans l'écran la verrait rouverte par un
drapeau que personne n'a pensé à effacer.

**Les exemples de nommage** méritent une remarque. Ils sont choisis par
proximité applicative — les rôles validés qui partagent des droits avec le
candidat — puis, à proximité égale, par date de validation décroissante : c'est
la convention en vigueur, pas celle qu'on a abandonnée. Ce **classement
s'appuie sur les droits, qui ne quittent pas la machine pour cet usage** ;
seuls les noms retenus sont transmis.

Le choix est délibérément à l'échelle de l'organisation et non par valideur :
un catalogue vaut par sa cohérence, et renvoyer à chacun ses propres habitudes
renforcerait les divergences.

**Les applications relèvent de la même autorisation que les libellés**, et non
d'un quatrième réglage : sur un référentiel réel, le libellé d'un droit porte
déjà le nom de son application. Les séparer donnerait un réglage de plus sans
rien protéger de plus. Le rattachement vient du référentiel des droits, jamais
d'une convention de nommage.

**Le nommage réclame au moins une de ses trois matières.** Les trois fermées,
le produit refuse de demander une proposition. Il ne
resterait que deux nombres, et un modèle privé de matière n'est pas prudent :
il invente. Constaté sur un rôle réel d'un client, mistral a proposé « Garde des
Droits » à partir du seul nombre de droits et de porteurs — un intitulé qui a
l'air d'un métier et ne désigne rien. L'écran dit alors ce qu'il faudrait
autoriser pour poser la question.

**Ce qui ne sort jamais, quel que soit le réglage : les identités.** Ce n'est
pas un arbitrage, et ce n'est pas garanti par la seule discipline du client :
le schéma de l'API ne déclare aucun champ d'identités et refuse tout champ
inconnu. La demande ne peut donc pas en transporter, même par erreur.

Sur un jeu hospitalier, un libellé de droit peut être révélateur
(`ONCOLOGIE_DOSSIER_PATIENT`). Autoriser sa sortie vers un fournisseur distant
est une décision de sécurité ; l'écran affiche l'hôte visé et signale quand
l'envoi quitte le serveur.

Chaque demande laisse une entrée dans la piste d'audit : **l'usage**, le modèle
interrogé, les **catégories** transmises, et si elles sont sorties du poste.
Jamais leur contenu, qui est déjà dans le référentiel. Un lecteur de la piste
doit pouvoir répondre à « pour quoi le modèle a-t-il été interrogé ce mois-ci,
et qu'est-ce qui est sorti » sans ouvrir les données.

Toute modification de la matrice laisse elle aussi une trace
(`assistance.updated`) : autoriser une sortie de données est une décision de
gouvernance, au même titre qu'écarter une identité de l'analyse.

**Proposer les conventions de comptes à privilèges** (`comptes_a_privileges`).
Cet usage est le seul du produit qui **ne transmet rien** : ni identifiant, ni
nom de colonne, ni échantillon. La question posée ne parle pas de ce client —
elle demande comment les systèmes d'habilitations nomment usuellement leurs
comptes d'administration. C'est une question de culture du métier.

Il figure tout de même dans la matrice, et il arrive fermé comme les autres : un
administrateur qui interdit toute sortie vers un modèle a le droit que sa règle
vaille aussi pour une question qui ne divulgue rien — l'appel réseau existe
quand même, et c'est lui qu'il refuse.

Ce qui revient est du vocabulaire, **éprouvé localement** : chaque convention
est cherchée dans le référentiel, à la place déclarée ; celle qui ne marque
aucun compte est écartée, et le nombre montré pour les autres est compté ici.
Le modèle apporte les mots, le produit apporte les nombres — et rien de ce
qu'il a vu n'a servi à les obtenir.

**Proposer les droits sensibles.** Le réglage `sensitive_right_keywords`
appartient au client — le produit ne peut pas décider qu'un droit est sensible
à sa place — et il reste vide chez la plupart, faute de savoir quoi y mettre.
Un réglage vide est une fonctionnalité morte. L'écran de configuration demande
au modèle les fragments de nom qui signalent un droit à regarder de près.

**Les mots viennent du modèle, les chiffres du calcul.** Chaque fragment
proposé est cherché dans le référentiel entier : celui qui ne correspond à rien
est écarté, et le nombre de droits que les autres signaleraient est compté par
le serveur, avec quelques exemples. Sans ce contrôle, on obtiendrait une liste
crédible annonçant des volumes inventés. Les fragments cochés sont **ajoutés** à
ce qui était saisi, jamais substitués.

L'échantillon de libellés transmis est plafonné et prélevé à pas régulier sur
l'ensemble trié : la tête d'un référentiel trié ne montre qu'une famille de
préfixes. Il est déterministe, pour qu'un audit se rejoue.

**Proposer les attributs pertinents.** Parmi quarante colonnes, l'analyste
cherche par essais successifs, à plusieurs minutes la tentative. Le modèle dit
de chaque colonne si elle porte du métier, si elle identifie une personne, ou
ni l'un ni l'autre. **Seuls les noms des colonnes sortent** : juger que
`matricule` identifie et que `service` porte du métier ne demande pas de savoir
qui travaille où.

La proposition ne coche rien. La règle de cardinalité reste le garde-fou, et
l'écran montre les deux : quand ils se contredisent — une colonne jugée
« métier » mais qui porte presque une valeur par identité —, c'est le décompte
qui tranche, et l'écran le dit. Le modèle lit des mots, le décompte porte sur
les données du client.

**Les droits et les identités d'un rôle, à la validation.** La fenêtre ne
montrait que l'identifiant de chaque porteur et de chaque droit — la seule
colonne que le produit connaisse par construction, et justement celle qui ne
dit rien : personne ne décoche `U0042` en connaissance de cause. Les deux
onglets affichent désormais **toutes les colonnes du référentiel**, triables,
avec la même recherche et le même sélecteur de colonnes que les écrans
d'exploration. Les colonnes masquées et leurs largeurs restent sur le poste,
par référentiel, comme ailleurs.

Deux points de correction accompagnent ce changement :

- **ce qui est validé est la sélection, pas les cases visibles.** Elle vivait
  dans le document ; dès qu'un tableau trie et pagine, une ligne non rendue
  n'existe plus, et lire les cases cochées viderait le rôle au premier tri.
  L'ordre du rôle est conservé : trier un tableau ne change pas ce qui sera
  exporté ;
- **un identifiant absent du référentiel reste dans le rôle.** Un droit
  orphelin — présent dans les habilitations, absent du référentiel des
  droits — s'affiche avec sa seule colonne d'identifiant, et l'écran dit
  combien il y en a. Le faire disparaître ferait valider un rôle qui n'est pas
  celui qui a été proposé.

**Le nommage en lot.** L'écran de résultats propose de nommer tous les
candidats d'un coup. Trois règles le gouvernent, et la deuxième est celle qui
le rend acceptable :

- **une demande par rôle, l'une après l'autre.** Un modèle local répond à une
  question à la fois : lui en envoyer trente ensemble ne va pas trente fois
  plus vite, cela sature la mémoire du poste — et chez un fournisseur distant,
  une rafale est un incident de débit. La file est séquentielle, elle
  s'interrompt sur demande, et l'écran estime la durée restante **à partir des
  réponses déjà obtenues**, jamais d'une valeur écrite dans le code ;
- **rien ne s'enregistre sans passage humain.** Les propositions remplissent
  des champs modifiables ; un geste distinct les conserve. Nommer n'est pas
  valider : un candidat nommé attend toujours qu'on décide de lui ;
- **un échec est par rôle, jamais global.** Le lot continue, la ligne fautive
  reste à reprendre.

Le volume est annoncé avant l'envoi, avec l'hôte visé : envoyer une demande à
un fournisseur et lui en envoyer trois cents ne sont pas le même geste. Les
noms retenus sont écrits sur les candidats conservés — une heure de relecture
ne doit pas se perdre à un rechargement de page.

**Un seul écran répond à « qu'est-ce qui peut sortir d'ici, et pour quoi
faire »** — *Configuration → Assistance par modèle* : la liste des usages,
l'état de chacun, la matière autorisée, le point de terminaison et son hôte, et
si l'envoi quitte le poste. Un usage fermé y figure aussi, avec la phrase qui
dit ce qu'il faudrait ouvrir : une fonction invisible passe pour une fonction
manquante, et la question revient en avant-vente.

---

## 4. Où chaque paramètre est vérifié

Ce n'est pas une intention : les tests le contrôlent.

- Un seuil hors domaine est refusé (422), au niveau du schéma comme du moteur.
- Le mode approché sans `similarity_threshold` ou sans `max_roles` est refusé
  (`mining.approx_parameters_required`), jamais complété par une valeur du code.
- À θ = 1, le sur-octroi est nul — vérifié rôle par rôle, à trois niveaux de
  bruit.
- Baisser θ augmente la couverture **et** le sur-octroi — vérifié sur la courbe.
- Les noms de colonnes du jeu de test sont volontairement différents des noms
  canoniques, ce qui vérifie qu'aucun nom de colonne n'est présupposé.
