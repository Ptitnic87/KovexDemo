# 06 — La page autonome

Kovex tourne d'ordinaire sur un serveur : Python, une API, un frontend servi à
côté. Cette page-ci est le même produit, servi comme un site statique et
exécuté **dans l'onglet** : le navigateur télécharge le runtime Python, dépose
le code, démarre l'API en mémoire, et l'interface lui parle comme elle parlerait
au serveur.

Ce n'est pas une version réduite. C'est le même code : les mêmes 156 routes,
les mêmes écrans, le même moteur de mining, les mêmes chiffres. Un banc le
vérifie parcours par parcours, et il n'accepte aucun écart (voir
« Ce qui le prouve » plus bas).

## À quoi elle répond

Un client qui met des semaines à obtenir une machine, ou dont la politique
interdit d'installer un interpréteur, peut ouvrir une page. C'est la seule
différence qu'elle vise : **le mode de livraison**, pas le produit.

Elle sert aussi de démonstration : rien à installer, rien à configurer, et les
fichiers ne quittent pas le poste — il n'y a pas de serveur à qui les envoyer.

## Comment elle est construite

```
python tools/construire_la_page.py --racine . --destination pages
```

La construction part de `frontend/`, de `src/` et de la configuration livrée.
Elle ne recopie pas un dossier tenu à la main, et c'est délibéré : un fichier
oublié, et la page publiée n'est plus celle que les campagnes vérifient.

Trois refus, et chacun répond à un incident :

- **le gabarit déjà ponté** : construire la page depuis la page empilerait les
  balises ;
- **un fichier ignoré par git** dans la liste blanche de l'archive :
  `config/users.json` — des empreintes de mots de passe, délibérément hors du
  dépôt — s'était retrouvé dans l'archive publiée ;
- **un runtime incomplet** : Pyodide, ses roues et le pont doivent être là,
  sinon la page démarre et échoue à l'écran.

L'archive est écrite triée et à date fixe : deux constructions des mêmes
sources donnent les mêmes octets.

## Ce que le pont fait, et ce qu'il ne fait pas

`pages/moteur/pont.js` remplace `window.fetch` **pour les seules adresses de
l'API**, construit un appel ASGI et rend une vraie `Response`. Aucune ligne du
frontend n'est touchée.

Tout ce que le navigateur faisait dans ce `fetch` et qu'il ne fait plus est une
différence pour l'interface, donc une charge du pont :

| Ce que fait un vrai `fetch` | Ce que fait le pont |
|---|---|
| suivre les redirections | suit `301/302/303/307/308`, `303` repart en `GET` sans corps, la borne est celle du navigateur (20) |
| sérialiser un `FormData` | passe par `Request`, donc c'est le navigateur qui calcule la frontière multipart |
| refuser un corps sur `204/304` | rend `null` plutôt que la chaîne vide |
| rendre un corps binaire tel quel | le corps traverse en octets, jamais en texte |
| respecter `redirect: "manual"` | rend la redirection telle quelle |

Le premier défaut trouvé ainsi : le produit répond `307` sur
`/api/v1/workspaces` (vers la route avec barre finale). Un vrai `fetch` suit
cette redirection sans que l'appelant l'apprenne ; le pont la rendait telle
quelle, et l'écran des workspaces affichait « Chargement impossible ».

Le second : le corps des réponses était décodé en UTF-8 avec remplacement des
octets invalides. L'en-tête d'un fichier survivait — un PDF commençait bien par
`%PDF` — mais le reste non : le classeur exporté ne s'ouvrait plus. C'est le banc
des exports qui l'a attrapé, en relisant les feuilles du classeur au lieu de se
contenter de sa taille.

Le pont **adapte aussi la plateforme au produit**, jamais l'inverse :

- `anyio.to_thread.run_sync` et `run_in_threadpool` exécutent directement —
  un navigateur n'a pas de fil à prêter ;
- `annotateur._poster` parle par le `fetch` du navigateur au lieu d'`urllib`,
  en rendant **les mêmes erreurs** : une `HTTPError` 4xx fait redescendre la
  contrainte de génération, une `URLError` dit « modèle injoignable ».

## Ce qui survit à la fermeture de l'onglet

Le système de fichiers de Pyodide vit en mémoire. Deux dossiers sont donc
montés sur IndexedDB, le seul stockage durable qu'un navigateur offre sans
rien demander :

- `workspaces/` — les fichiers importés, la configuration du workspace, la base
  de connaissance, donc les décisions de gouvernance ;
- `audit/` — la piste d'audit.

L'écriture a lieu **avant** que la réponse ne parte, et pour les seuls appels
qui écrivent : quelqu'un qui ferme l'onglet juste après avoir validé un rôle
doit retrouver ce rôle. `config/` reste en mémoire : il vient de l'archive du
produit, et le monter masquerait ce que l'archive dépose.

Un navigateur qui refuse le stockage — fenêtre privée, quota épuisé — ne
bloque pas le travail : la page le dit et continue en mémoire seule. Un quota
atteint en cours de route est journalisé et signalé par l'événement
`kovex:sauvegarde`.

## Le moteur de modèle

Sur un serveur, l'adresse du modèle, son nom et sa clé viennent de
l'environnement : ouvrir une sortie réseau depuis un système d'habilitations
est une décision d'infrastructure (voir [02 — Les paramètres](02-parametres.md)).
Dans une page, il n'y a pas d'environnement de serveur — l'infrastructure,
c'est la personne qui l'ouvre. Elle déclare donc le moteur dans l'écran de
configuration, et le produit se comporte **exactement** comme si un fichier
d'environnement portait ces variables : même matrice d'assistance, mêmes
catégories autorisées, mêmes attestations dans la piste d'audit. Les identités
ne sortent jamais, et ce n'est pas un réglage.

Cette carte ne s'affiche **que** là où l'exécution peut accepter une
déclaration. Sur un poste, elle reste masquée : un écran qui proposerait de
changer ce que seul l'exploitant règle mentirait sur qui décide.

Deux limites, et il faut les dire :

- **la clé n'est pas conservée durablement.** Elle reste en mémoire, et au plus
  dans le stockage de session si la personne le demande pour cet onglet. Une
  clé déposée dans le stockage durable survivrait à la fermeture et se lirait
  depuis l'origine de la page.
- **le serveur de modèle doit autoriser l'origine de la page.** L'appel part du
  navigateur : un serveur qui ne renvoie pas les en-têtes d'origine refuse, et
  l'interface affiche « modèle injoignable ». Pour Ollama, c'est
  `OLLAMA_ORIGINS`. Certains fournisseurs refusent tout appel venant d'un
  navigateur : le modèle local, ou une passerelle d'entreprise, restent la voie
  sûre.

Et une conséquence de la publication en `https`, mesurée plutôt que supposée
(Chromium) : depuis une page servie en `https`, un appel en `http` vers
`127.0.0.1` ou `localhost` **passe** — le navigateur les tient pour des
origines de confiance. Un appel en `http` vers **toute autre** adresse est
bloqué comme contenu mixte, avant même de partir. Autrement dit : le modèle qui
tourne sur la machine de la personne fonctionne depuis la page publiée ; un
modèle posé sur une autre machine du réseau doit être servi en `https`, ou
atteint par une passerelle qui l'est.

## Ce que la page ne peut pas faire

- **Le mot de passe.** `hashlib.pbkdf2_hmac` vient d'OpenSSL, qu'un navigateur
  n'a pas. L'authentification n'est donc pas disponible dans la page ; elle y
  est désactivée, ce qui est refusé au démarrage en production. Le produit ne
  dégrade ni le schéma ni le nombre d'itérations : il refuse de hacher et le
  dit.
- **Le premier chargement coûte.** Le runtime, les bibliothèques de calcul et
  le code font une trentaine de mégaoctets, une fois, mis en cache ensuite. Le
  démarrage est annoncé dans le loader du produit.

## Ce qui le prouve

Les bancs sont dans `pages/banc/` et s'exécutent par `pages/banc/tout.sh` :

| Banc | Ce qu'il vérifie |
|---|---|
| `pont.mjs` | le pont, sans navigateur : redirections, multipart, statuts sans corps, démarrage unique, la clé hors du stockage durable, le disque monté et relu |
| `modele.py` | l'appel au modèle part vraiment, la clé ne voyage que dans l'en-tête, **aucune identité dans la demande**, un 4xx fait redescendre la contrainte, un modèle absent donne « injoignable » |
| `persistance.py` | importer, miner, **recharger la page**, et retrouver l'espace, les chiffres, les candidats et la piste |
| `iso.py` | le même parcours par les écrans, dans la page **et** en natif, puis chaque chiffre comparé — zéro écart accepté |

Le dernier est celui qui décide : ce sont les mêmes clics, les mêmes fichiers,
les mêmes réglages, et ce sont les chiffres lus à l'écran qui sont confrontés.
