# Manuel du développeur

## Architecture

```
src/
  api/          Points d'entrée HTTP (FastAPI), politique d'accès, schémas
  core/
    data/       Chargement des CSV, construction de la matrice, qualité
    mining/     Algorithmes de découverte de rôles et d'exploration de seuils
    knowledge/  Base de connaissances : rôles validés, rejetés, exclusions
    audit/      Piste d'audit chaînée
    security/   Authentification, mots de passe, limitation de débit
    workspaces/ Isolation par client ou environnement
  infrastructure/ Journalisation, i18n serveur, identité produit
frontend/       Application web sans dépendance externe
tests/          Suite pytest, dont tests/ihm pour le navigateur
docs/           Documentation, dont docs/manuel servi par l'application
```

Une règle traverse tout le code : **le serveur ne construit jamais un libellé
affiché**. Il rend un code et ses paramètres ; le client traduit. Un serveur
ne connaît pas la langue de son utilisateur.

## Conventions

**Aucune valeur en dur.** Seuils, chemins, noms de colonnes : tout vient de la
configuration. Une valeur écrite dans le code est un défaut, pas un
raccourci.

**Aucun nom de colonne présupposé.** Les fichiers clients ont les colonnes
qu'ils ont. Seule la configuration les relie aux identifiants internes.

**Refus par défaut.** Toute route doit être déclarée dans
`src/api/security_policy.py`. Une route non déclarée est refusée, et un test
le vérifie sur l'intégralité des routes de l'application.

**Les commentaires expliquent le pourquoi.** Un commentaire qui paraphrase le
code est du bruit. Un commentaire qui dit quel défaut la ligne évite a de la
valeur des années plus tard.

## Tests

```
python -m venv .venv                    # un environnement dedie : le verrou
.venv\Scripts\activate                  # ne tient que s'il est seul a decider
pip install -r requirements-dev.txt     # herite du verrou, pas des bornes
python -m playwright install chromium   # une fois, telecharge le navigateur

python -m pytest                        # tout
python -m pytest tests/ihm              # navigateur
python -m pytest --cov --cov-report=term-missing   # couverture du backend
python couverture_frontend.py           # couverture du JavaScript
```

Sans Playwright, les tests d'interface sont **ignores en silence** :
`tests/ihm/conftest.py` passe son import a `pytest.importorskip`. La campagne
passe, sans la moitie de ce qu'elle pretend verifier, et la couverture du
frontend ne mesure rien. `python -m playwright install chromium` demande un
acces reseau ; sur un poste isole, recuperez le navigateur ailleurs et posez
`PLAYWRIGHT_BROWSERS_PATH` sur son emplacement. Rien de cela ne concerne le
produit livre : Playwright ne sert qu'a le tester.

Trois familles :

- **unitaires et d'intégration** : la majorité, sur des jeux de données
  générés — jamais sur des données clientes, pour tourner sur un poste vierge.
- **structurelles** : gabarit HTML équilibré, aucune modale imbriquée, aucun
  identifiant lu par le JavaScript qui n'existe nulle part, aucun gestionnaire
  d'événement en attribut, parité des catalogues de traduction. Elles
  attrapent une classe entière de défauts invisibles autrement.
- **interface** : un vrai navigateur, une API bouchonnée. Elles existent parce
  qu'un défaut de structure HTML rendait une fonctionnalité silencieusement
  inopérante sans qu'aucun test serveur ne puisse le voir.

## Premier démarrage

Aucun mot de passe n'est écrit dans le code : le premier lancement crée le seul
compte `admin`, avec le mot de passe fourni par l'environnement.

```
set PYGIA_SECRET_KEY=...                   # signature des jetons
set PYGIA_BOOTSTRAP_ADMIN_PASSWORD=...     # mot de passe du compte initial
python run_api.py
```

Sans la seconde variable en développement, un mot de passe aléatoire est tiré
et **journalisé une seule fois** au démarrage. Il n'est jamais réaffiché : la
ligne défile dans le flot des messages, et une fois `config/users.json` créé,
plus rien ne la reproduit. Perdu, il se retrouve en supprimant ce fichier et en
redémarrant avec la variable renseignée — il ne contient que des empreintes,
aucune donnée de gouvernance.

En production, l'absence de la variable ne crée aucun compte : l'installation
reste fermée plutôt que d'être ouverte par un identifiant connu de tous.

## Versions des dépendances

`requirements.txt` porte des bornes basses et décrit ce que le code exige.
`requirements.lock` fige les versions exactes que la suite a exécutées, et
c'est à partir de lui qu'un serveur s'installe. Il est relevé, pas rédigé :

```
python -m tools.verrou_dependances            # signale l'écart, ne touche à rien
python -m tools.verrou_dependances --ecrire   # met le fichier à jour
```

Sans `--ecrire`, la commande rend 1 quand le verrou diffère de l'environnement
installé, ce qui la rend utilisable telle quelle dans une chaîne
d'intégration. Ne régénérez le verrou qu'après avoir vu passer toute la suite :
figer une version que rien n'a exécutée est exactement ce que ce fichier existe
pour empêcher.

## Ajouter un point d'entrée

1. Écrire la route dans un routeur de `src/api/routers/`.
2. **La déclarer dans `security_policy.py`** avec la permission requise. Sans
   cela elle répond 403.
3. Si elle modifie l'état de gouvernance, ajouter `journal: Journal =
   Depends(get_journal)` et consigner l'action avec un code de `Action`.
4. Rendre des codes de traduction, jamais des phrases.
5. Ajouter les clés correspondantes dans les trois catalogues.

## Ajouter une langue

Copier `config/locales/fr.json`, traduire les valeurs, conserver toutes les
clés. Les tests vérifient la parité des clés et la cohérence des
substitutions : une clé manquante ou un `{parametre}` oublié fait échouer la
suite.

Les manuels embarqués vivent dans `docs/manuel/<langue>/`. Une section absente
dans une langue est servie dans la langue de référence, et l'interface le dit
plutôt que d'afficher une page vide.

## Piste d'audit

`PisteAudit` écrit des lignes JSON ajoutées une à une, chacune portant
l'empreinte de la précédente. Le module n'expose aucune suppression, et
l'API aucune route d'écriture — deux tests le vérifient.

Pour consigner depuis une route, ne manipulez pas la piste directement :
déclarez la dépendance `Journal`. Elle résout l'acteur depuis le jeton et le
workspace actif, ce qui évite qu'un appelant s'attribue une décision à
quelqu'un d'autre en glissant un nom dans le corps de la requête.

## Frontend

Aucune dépendance externe : les bibliothèques sont embarquées dans
`frontend/vendor/`. Le produit doit fonctionner sur un serveur sans accès
sortant.

**Deux numéros, deux rôles.** `serve_frontend.py` réécrit le gabarit au vol :
il aligne l'affichage du bas de la barre sur `VERSION_PRODUIT`, et la clé de
cache des feuilles de style et des scripts sur une **empreinte du contenu
servi**. La seconde change exactement quand un fichier de `frontend/` change,
et jamais autrement — il n'y a donc rien à penser en livrant. Le numéro écrit
dans `index.html` ne sert qu'à rendre le fichier ouvrable tel quel ; il
n'atteint jamais le navigateur.

`VERSION_PRODUIT`, elle, ne se déduit de rien : c'est un numéro qui parle aux
humains. On la fait monter quand la livraison mérite d'être nommée, pas à
chaque modification.

Interdits, et vérifiés par les tests :

- `onclick="..."` dans le gabarit — utilisez la délégation d'événements ;
- `<a href="#">` pour déclencher une action — le routeur à hash le lit comme un
  retour au tableau de bord ;
- un identifiant lu par `getElementById` qui n'existe ni dans le gabarit ni
  dans du HTML généré ;
- du texte affiché écrit en dur.

Les ressources portent un numéro de version dans leur URL. Incrémentez-le à
chaque livraison frontend, sans quoi les navigateurs servent l'ancienne
version.
