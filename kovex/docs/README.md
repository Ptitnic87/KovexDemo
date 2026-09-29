# Documentation Kovex / PyGIA

Kovex découvre des rôles dans un référentiel d'habilitations existant, puis
accompagne leur validation. Il fonctionne sur un serveur isolé, sans accès
réseau sortant, à partir des seuls fichiers que vous lui donnez.

Cette documentation est écrite pour trois lecteurs différents. Prenez l'entrée
qui correspond à ce que vous cherchez.

| Vous cherchez à… | Lisez |
|---|---|
| comprendre **ce que fait le produit et pourquoi il le fait ainsi** | [01 — L'approche](01-approche.md) |
| savoir **quel paramètre règle quoi**, et ce qu'il change | [02 — Les paramètres](02-parametres.md) |
| **installer, sécuriser, exploiter** l'application | [03 — Exploitation](03-exploitation.md) |
| savoir **comment on prouve que le mining est juste** | [04 — Validation](04-validation.md) |
| **décrire vos fichiers** à l'application | [05 — Données](05-donnees.md) |
| **livrer le produit comme une page**, sans rien installer | [06 — La page autonome](06-page-autonome.md) |

## Le principe qui explique tout le reste

Aucune valeur métier n'est écrite dans le code.

Le produit ne sait pas comment vos colonnes s'appellent, ni combien de droits
fait un rôle raisonnable chez vous, ni quel niveau d'approximation votre
gouvernance accepte. Il refuse donc de choisir à votre place : chaque seuil est
un paramètre explicite, sans valeur par défaut côté serveur, et un appel qui
n'en fournit pas est rejeté plutôt que complété silencieusement.

La contrepartie est que le produit doit vous donner de quoi choisir. C'est le
rôle de l'exploration du seuil, des métriques de sur-octroi, et de la
distribution affichée au tableau de bord : à chaque endroit où vous devez
trancher, un chiffre calculé sur vos données vous est présenté.

## Périmètre de cette documentation

Elle décrit l'état du code au 29 août 2026. Ce qui n'y est pas décrit n'existe
pas encore : la documentation ne décrit jamais une intention. Les manques connus
sont listés en fin de [01 — L'approche](01-approche.md).
