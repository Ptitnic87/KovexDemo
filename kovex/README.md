# Kovex / PyGIA

Découverte de rôles dans un référentiel d'habilitations existant, et
accompagnement de leur validation. Fonctionne sur un serveur isolé, sans accès
réseau sortant, à partir des seuls fichiers qu'on lui donne.

## Démarrage rapide

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium   # une fois : les tests d'interface
cp .env.example .env                    # PYGIA_SECRET_KEY **et**
                                        # PYGIA_BOOTSTRAP_ADMIN_PASSWORD
python -m pytest                        # 3 229 tests
python run_api.py                       # API sur http://127.0.0.1:8000
```

Il n'existe **aucun mot de passe par défaut** : le premier démarrage crée le
seul compte `admin` avec le mot de passe de `PYGIA_BOOTSTRAP_ADMIN_PASSWORD`,
ou, si la variable est vide, avec un mot de passe aléatoire journalisé une
seule fois. Perdu, il se retrouve en supprimant `config/users.json` et en
redémarrant avec la variable renseignée.

L'installation du navigateur est une étape à part entière, et son oubli ne se
voit pas à l'installation : le paquet Playwright suffit à faire **collecter**
les 1 084 tests d'interface, qui échouent alors tous à l'ouverture du
navigateur. Un mur d'erreurs sur un dépôt neuf vient presque toujours de là.
Sur un poste isolé, récupérer le navigateur ailleurs et poser
`PLAYWRIGHT_BROWSERS_PATH` sur son emplacement ; sous WSL, ajouter
`python -m playwright install-deps`.

Pour ne faire tourner que le backend, sans navigateur :

```bash
python -m pytest --ignore=tests/ihm -q   # 2 145 tests
```

L'interface est servie séparément depuis `frontend/`. Sous Windows,
`START_PYGIA.bat` lance les deux.

### La campagne de couverture

Le projet exige **100 %**, serveur et interface. Les deux seuils sont opposés
par `tests/test_couverture.py`, qui relit les rapports produits par la
campagne — il faut donc deux appels, le second après que le rapport existe :

```bash
python -m pytest tests --ignore=tests/ihm --cov=src --cov-report=json -q
python -m pytest tests/test_couverture.py -q -k "module or total"
```

Côté interface, la campagne se découpe : d'un seul tenant les tests navigateur
épuisent la mémoire d'une machine ordinaire. Chaque tranche rend un relevé
**partiel** — elle ne charge qu'une partie des écrans — et le seuil n'est
opposable qu'après la réunion :

```bash
for i in 1 2 3 4; do
  KOVEX_COUVERTURE_JS=output/tranche-$i.json \
    python -m pytest $(python tools/tranches_ihm.py $i 4) -q
done
python couverture_frontend.py --fusionner output/tranche-*.json \
  --releve output/couverture_frontend.json --seuil 100
```

C'est exactement ce que fait l'intégration continue
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)), les quatre tranches
en parallèle. Une seule règle à retenir : **ne modifier aucun fichier de
`frontend/` pendant une campagne**. Les tranches mesureraient deux états
différents du même code, et le pourcentage qui en sort ne décrirait aucun des
deux — la réunion refuse d'ailleurs de le produire.

## Documentation

Tout est dans [`docs/`](docs/README.md) :

| | |
|---|---|
| [01 — L'approche](docs/01-approche.md) | ce que fait le produit, et pourquoi il le fait ainsi |
| [02 — Les paramètres](docs/02-parametres.md) | quel réglage change quoi, et comment le choisir |
| [03 — Exploitation](docs/03-exploitation.md) | installation, sécurité, mise en production |
| [04 — Validation](docs/04-validation.md) | comment on prouve que le mining est juste |
| [05 — Données](docs/05-donnees.md) | décrire vos fichiers à l'application |

## Licence

Logiciel propriétaire. Copyright (c) 2025-2026 Nicolas Cudon, tous droits
réservés — voir [LICENSE](LICENSE). L'accès à ce dépôt ne concède aucun droit
d'usage : toute concession résulte d'une convention écrite et signée.

Les composants tiers embarqués ou installés par le produit, et leurs licences,
sont énumérés dans [NOTICE](NOTICE).

## Le principe qui explique le reste

Aucune valeur métier n'est écrite dans le code. Le produit ne connaît ni le nom
de vos colonnes, ni ce qui fait un rôle raisonnable chez vous, ni le niveau
d'approximation que votre gouvernance accepte. Il refuse donc de choisir à votre
place — et, en contrepartie, il vous donne les chiffres calculés sur vos données
pour que vous puissiez choisir.
