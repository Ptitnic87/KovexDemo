# Plateforme de démonstration Kovex

Ce dépôt fait une démonstration de Kovex sans rien attendre ni préparer : des
référentiels fictifs par secteur, six mois de gouvernance déjà posés, et les
minings **déjà calculés**.

Kovex n'y est pas copié : c'est le sous-module `kovex/`, figé sur la version
pour laquelle l'instantané a été construit. `restaurer.py` refuse de remettre
l'instantané sous une autre version.

## Organisation

| Chemin | Rôle |
|---|---|
| `kovex/` | sous-module : le produit, à la version de l'instantané |
| `secteurs/` | une fiche par secteur : organisation, applications, cas plantés, gouvernance |
| `generer_secteur.py` | génère le référentiel d'une fiche, et recompte les cas plantés |
| `construire_la_demo.py` | construit les espaces par l'API de Kovex et les fige dans `instantane/` |
| `instantane/` | les six espaces figés, et la version de Kovex qui les a construits |
| `restaurer.py` | remet l'instantané dans `kovex/workspaces/`, dates du jour, modèle réglé |
| `modele.json` | point de terminaison et usages ouverts au modèle — **aucune clé** |
| `poser_la_cle.py` | pose la clé une fois dans le porte-clés du serveur |
| `lancer_la_demo.sh`, `LANCER_LA_DEMO.bat` | restaurer, puis lancer Kovex |
| `empaqueter.py` | une archive unique pour un serveur sans réseau |
| `atelier/` | le déroulé de l'atelier en direct des Assises |
| `tests/` | générateur, restauration, contrôle de version |

Aucune donnée de client : les identités, les droits et les organisations sont
inventés par `generer_secteur.py`, à partir des fiches de `secteurs/`.

## Ce qu'il y a dedans

| Espace | Secteur | Identités | Droits | Applications | Habilitations |
|---|---|---:|---:|---:|---:|
| Assurance — Groupe Alvéa | assurance | 20 999 | 8 000 | 240 | 255 882 |
| Grande distribution — Groupe Marelle | commerce | 29 999 | 9 000 | 260 | 361 284 |
| Santé — Hôpital des Tilleuls | santé | 13 999 | 7 000 | 220 | 172 678 |
| Énergie — Hélior Énergie | énergie | 11 999 | 6 000 | 200 | 144 696 |
| Luxe — Maison Aurèle | luxe | 5 991 | 3 000 | 100 | 75 341 |
| Atelier — référentiel brut | assurance, rien de décidé | 20 999 | 8 000 | 240 | 255 882 |

Chaque espace sectoriel contient :

- **des cas plantés**, recomptés à la génération : un droit dont le nombre de
  porteurs tombe pile sur une borne d'export, des couples de droits que
  l'organisation sépare déjà, une application que plus personne n'utilise,
  des comptes qui ne se connectent plus, des mobilités qui ont gardé leurs
  anciens droits, des valeurs de contrat écrites de plusieurs façons, des
  comptes à privilèges ;
- **six mois de gouvernance** : droits socles, deux ou trois règles de
  séparation propres au secteur (prescrire / dispenser, saisir / confirmer une
  transaction, accorder / valider une remise…), un contrôle compensatoire
  exécuté, une dérogation qui le cite, un rôle fait main, une cinquantaine de
  décisions qui nourrissent le score appris ;
- **un mining applicatif et un mining métier conservés**. Sur l'écran du
  mining, le bandeau « Un mining du … est conservé » propose **Afficher** :
  le résultat apparaît en moins d'une demi-seconde, au lieu de 30 s à
  4 min 30 de calcul selon le secteur.

L'espace « Atelier — référentiel brut » sert au déroulé en direct : rien n'y
est décidé, tout se joue devant la salle.

## Récupérer

Avec un accès au dépôt de Kovex :

```
git clone --recurse-submodules https://github.com/Ptitnic87/KovexDemo.git
```

Pour un serveur sans réseau, sur un poste qui a les deux dépôts :
`python empaqueter.py --sortie KovexDemo.zip`, puis copier et décompresser
l'archive sur le serveur. Seuls les fichiers suivis par git y entrent.

## Installer, une fois

1. **Les dépendances** : `pip install -r kovex/requirements.txt`.
2. **L'authentification**. Dans `kovex/.env` : `PYGIA_AUTH_DISABLED=false`, une
   `PYGIA_SECRET_KEY` propre au serveur, et `PYGIA_BOOTSTRAP_ADMIN_PASSWORD`
   pour créer le premier compte — variable à retirer après le premier
   démarrage. Sur un serveur partagé, chacun se connecte avec son compte : la
   piste d'audit dit qui a fait quoi.
3. **Le réseau**, pour un accès depuis d'autres postes : `KOVEX_API_HOST` et
   `KOVEX_FRONTEND_HOST` (`0.0.0.0`), `KOVEX_API_URL`
   (`http://<serveur>:8000/api/v1`) et `PYGIA_ALLOWED_ORIGINS`
   (`http://<serveur>:3000`).
4. **Le modèle**. Dans `modele.json`, renseigner `adresse` (compatible
   OpenAI, par exemple `https://…/v1`) et `modele`. Ce fichier ne contient
   **aucune clé** et se versionne.
5. **Premier lancement** : `./lancer_la_demo.sh` (Linux) ou
   `LANCER_LA_DEMO.bat` (Windows). Pour ouvrir un autre espace au démarrage :
   `--actif Alvea_ATELIER`.
6. **La clé**, une seule fois, Kovex lancé :
   `python poser_la_cle.py --utilisateur admin`. La clé est saisie sans
   écho et rangée dans le porte-clés du serveur (`kovex/config/cles_annotateur.json`,
   hors dépôt, droits restreints). On peut aussi la poser dans
   **Paramètres → Points de terminaison des modèles**.

## Lancer, et remettre à zéro

À chaque lancement (`lancer_la_demo.sh` ou `LANCER_LA_DEMO.bat`) :

- les six espaces reviennent dans leur état figé : ce qu'une séance
  précédente a validé, refusé ou supprimé disparaît ;
- **les dates suivent le jour du lancement** : le contrôle compensatoire a
  toujours été exécuté quelques jours avant, la dérogation échoit toujours
  dans trois mois. Sans ce décalage, la démonstration se périmerait d'elle-même ;
- le modèle de `modele.json` est réglé dans chaque espace ;
- la clé, les comptes et la piste d'audit ne sont **pas** touchés.

Pour remettre à zéro entre deux rendez-vous : arrêter Kovex, relancer.

## Changer de modèle

Modifier `modele.json`, relancer. Si le préréglage garde le même
`identifiant`, la clé posée reste valable ; sinon, la reposer.

Les usages ouverts à un modèle sont listés dans le même fichier. Ils ne
laissent sortir que des libellés de droits, des noms de colonnes, des règles
et les valeurs des colonnes nommées — **jamais d'identité**, c'est une règle
du produit et non un réglage.

## Refaire l'instantané

Pour passer à une nouvelle version de Kovex, ou ajouter un secteur (une fiche
de plus dans `secteurs/`) :

```
git -C kovex fetch && git -C kovex checkout <commit de main>
python -m pytest tests -q
# Kovex lancé depuis kovex/, sans espace existant, authentification désactivée
python construire_la_demo.py
git add kovex instantane && git commit
```

La construction dure une quinzaine de minutes. Elle écrit `instantane/` :
une archive par espace, et `index.json` avec la version de Kovex utilisée.

## Ce que la démonstration ne montre pas

- **La piste d'audit ne contient pas les six mois** : elle est chaînée, et
  elle ne se fabrique pas après coup. Elle montre ce qui a été fait sur le
  serveur de démonstration, par qui.
- **L'explorateur de seuil** n'est pas conservé : il se relance (35 s sur
  l'assurance, mesuré ; davantage sur la grande distribution).
- Les volumes sont ceux d'organisations moyennes. Pour montrer la tenue à
  l'échelle, utiliser le banc de Kovex (`kovex/banc_performance.py`).
