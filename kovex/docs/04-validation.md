# 04 — Comment on prouve que le mining est juste

## 1. Cohérent n'est pas juste

Un moteur peut être parfaitement reproductible et se tromper de la même façon à
chaque exécution. La distinction structure toute la démarche de validation :

- **cohérent** — déterministe, respecte ses seuils, ne s'octroie rien à θ = 1,
  n'est jamais moins couvrant que le mode exact, métriques arithmétiquement
  justes ;
- **juste** — les rôles restitués sont bien ceux qui structurent réellement les
  habilitations.

La suite de tests couvre les deux. Ce document décrit la seconde, qui est la
plus difficile à établir.

## 2. Niveau 1 — vérité terrain plantée

**Le principe : construire le référentiel à l'envers.** On décide d'abord les
rôles, on en déduit mécaniquement les habilitations, on les dégrade avec du
bruit, puis on demande au moteur de retrouver les rôles de départ.

Deux bruits, ceux qu'on observe sur un référentiel réel :

- **omission** — un porteur n'a pas, ou n'a plus, tous les droits de son rôle ;
- **exception** — une habilitation accordée hors de tout rôle.

Trois mesures, toutes fondées sur l'indice de Jaccard des ensembles de droits :

| Mesure | Définition | Ce qu'elle dit |
|---|---|---|
| **rappel** | pour chaque rôle attendu, le meilleur rôle restitué | ce qu'on retrouve |
| **précision** | pour chaque rôle restitué, le meilleur rôle attendu | ce qu'on invente |
| **rappel des membres** | Jaccard sur les porteurs du rôle apparié | la population est-elle reconstituée ou éclatée |

Le générateur : `tests/rbac_verite_terrain.py`. Rien n'y est figé — dimensions,
nombre et taille des rôles, rôles par identité, niveaux de bruit et noms de
colonnes sont des arguments, et le tirage est piloté par une graine, donc
reproductible à l'identique.

### Résultats

600 identités, 120 droits, 15 rôles plantés de 4 à 9 droits, 1 à 3 rôles par
identité.

| Bruit (omission / exception) | Mode | Rôles rendus | Rappel | Précision | Membres | Retrouvés à l'identique |
|---|---|---|---|---|---|---|
| 0 % / 0 % | exact | 106 | 1,000 | 0,588 | 0,170 | 15 / 15 |
| 0 % / 0 % | **approché θ = 1,0** | **15** | **1,000** | **1,000** | **1,000** | **15 / 15** |
| 5 % / 2 % | approché θ = 1,0 | 183 | 0,993 | 0,665 | 0,652 | 14 / 15 |
| 10 % / 5 % | approché θ = 1,0 | 173 | 0,955 | 0,692 | 0,371 | 9 / 15 |
| 10 % / 5 % | approché θ = 0,8 | 200 | 0,973 | 0,625 | 0,817 | 12 / 15 |
| 20 % / 10 % | approché θ = 1,0 | 116 | 0,884 | 0,675 | 0,165 | 4 / 15 |
| 20 % / 10 % | **approché θ = 0,7** | 200 | **0,977** | 0,559 | **0,780** | **12 / 15** |

### Ce que ces chiffres établissent

1. **Sur des données propres, le moteur restitue exactement la vérité.** 15
   rôles plantés, 15 rendus, précision et rappel à 1,000, populations
   reconstituées à l'identique. C'est le premier test qui pouvait le contredire.
2. **Le mode exact éclate les populations.** Une identité portant deux rôles a
   une signature qui n'est celle d'aucun des deux : le mode exact en fait un
   troisième rôle. 106 rôles pour 15 réels, rappel des membres à 0,17. C'est la
   justification chiffrée du mode approché.
3. **Le classement glouton place les vrais rôles en tête.** À bruit faible, la
   précision des 15 premiers rôles vaut 0,99 quand celle des 183 tombe à 0,66.
   La queue de liste est du résidu de bruit, pas de la découverte — ce qui fait
   du paramètre « nombre maximum de rôles » un levier réel.
4. **Le seuil doit baisser quand le bruit monte.** C'est le résultat qui
   justifie que θ reste un choix de l'utilisateur et ne soit jamais figé.

### Ce qu'ils n'établissent pas

Le générateur produit des rôles **tirés aléatoirement**, pas des rôles métier.
Un référentiel réel a des rôles imbriqués, des droits socles portés par tout le
monde, une distribution très déséquilibrée des effectifs. La vérité terrain
plantée mesure la capacité de restitution du moteur, pas sa pertinence métier.
Condition nécessaire, pas suffisante.

## 3. Niveau 2 — jeux de données publics

`tools/banc_verite_terrain.py`, mode `public`, rejoue un jeu **présent sur le
poste** — le banc ne télécharge rien — et mesure le nombre de rôles nécessaires
pour couvrir 100 % des habilitations sans aucun sur-octroi.

### Les neuf jeux HP, contre les optima publiés

Les neuf jeux HP Labs (Ene et al., 2008) sont les jeux de référence de la
littérature. Le dépôt ConstrainedRM (Blundo, Cimato et al., licence MIT) les
distribue au format « une habilitation par ligne », avec **le nombre minimal
de rôles** qui couvre exactement chacun d'eux et huit décompositions de
référence par jeu. Ces optima sont repris dans
`tools/references/hp_optima.json`, avec leur source.

```
python tools/banc_verite_terrain.py public \
    --racine ConstrainedRM/datasets/realWorld --motif "*.txt" --format paires \
    --selection exacte --references tools/references/hp_optima.json
```

Mesuré le 19/09/2026, θ = 1, `min_users = min_rights = 1`, les trois
générateurs :

| Jeu | Dimensions | Habilitations | Optimum publié | Kovex glouton | Kovex exact | Meilleure décomposition de référence¹ | Temps (exact) |
|---|---|---|---|---|---|---|---|
| Domino | 79 × 231 | 730 | 20 | 21 | **20** | 20 | 0,04 s |
| Healthcare | 46 × 46 | 1 486 | 14 | 17 | **14** | 14 | 0,04 s |
| EMEA | 35 × 3 046 | 7 220 | 34 | 43 | **34** | 34 | 0,26 s |
| Firewall-1 | 365 × 709 | 31 951 | 64 | 66 | **64** | 65 | 0,71 s |
| Firewall-2 | 325 × 590 | 36 428 | 10 | 10 | **10** | 10 | 0,25 s |
| APJ | 2 044 × 1 164 | 6 841 | 453 | 465 | **453** | 453 | 0,73 s |
| Americas small | 3 477 × 1 587 | 105 205 | 178 | 196 | 179 | 198 | 8,7 s |
| Americas large | 3 485 × 10 127 | 185 294 | 398 | 564 | **398** | 415 | 17,4 s |
| Customer | 10 021 × 277 | 45 427 | non publié | 287 | 276 | 276 | 64 s |

¹ Le plus petit des sept résultats heuristiques de référence que distribue le
dépôt pour ce jeu : RM1 à RM4, FastMiner, OBMD, Biclique. Leur décomposition
« optimale » n'est pas comptée ici. Pour Firewall-1, elle compte 66 rôles
alors que l'optimum publié est 64 ; Kovex en rend 64.

Dans tous les cas, la couverture est de 100 % et le sur-octroi nul. Sur huit
jeux, la sélection exacte atteint l'optimum publié. Sur le neuvième, Americas
small, elle rend 179 rôles pour un optimum de 178, et c'est le minimum
**prouvé sur les candidats** que les générateurs proposent (`borne_sur_candidats`).
Le rôle manquant n'est donc pas un défaut du solveur : aucun des générateurs
ne proposait le candidat qu'il faudrait — c'est corrigé par le treillis,
ci-dessous. Sur les neuf jeux, elle rend autant de
rôles que la meilleure des sept heuristiques de référence, ou moins.

### Avec le treillis : les huit optima publiés sur huit

Le candidat qui manquait sur Americas small a été cherché, et trouvé. La
décomposition optimale que publie ConstrainedRM (178 rôles) a été comparée au
vivier de Kovex : une fois chaque rôle complété par les droits que tous ses
détenteurs partagent, **dix** n'y figuraient pas. Aucun n'est une clôture, ni
un profil, ni l'intersection de deux profils : ce sont des terrains communs à
**trois profils ou plus**. Le quatrième générateur, `treillis`, recroise les
terrains communs avec les profils jusqu'au point fixe
(`docs/02-parametres.md`, § 3.1).

Mesuré le 26/09/2026, mêmes réglages, avec `--generateurs
cloture,signature,intersection,treillis` :

| Jeu | Optimum publié | Kovex exact, sans treillis | Kovex exact, avec treillis | Treillis complet | Temps (avec) |
|---|---|---|---|---|---|
| Domino | 20 | 20 | **20** | oui | 0,06 s |
| Healthcare | 14 | 14 | **14** | oui | 0,05 s |
| EMEA | 34 | 34 | **34** | oui | 0,78 s |
| Firewall-1 | 64 | 64 | **64** | oui | 1,1 s |
| Firewall-2 | 10 | 10 | **10** | oui | 0,24 s |
| APJ | 453 | 453 | **453** | oui | 0,47 s |
| Americas small | 178 | 179 | **178** | oui | 13,0 s |
| Americas large | 398 | 398 | **398** | non (borne) | 105 s |
| Customer | non publié | 276 | **276** | oui | 91 s |

**Huit sur huit.** Sur Americas small, le glouton passe aussi de 196 à 194.

**Customer : 276 est l'optimum, et c'est désormais prouvé.** Aucun optimum
n'est publié pour ce jeu. Quand le treillis est complet, le vivier contient
toutes les intersections de profils — c'est-à-dire tous les ensembles de
droits qu'un rôle sans sur-octroi peut porter, une fois complété par ce que ses
détenteurs partagent. Le solveur, qui clôt sur ce vivier, prouve donc le
minimum sur **tous** les modèles exacts possibles, pas seulement sur les
candidats. Cette preuve vaut à θ = 1, avec `min_users = min_rights = 1`, sur
un croisement non restreint (`croisement_borne` faux) et un treillis complet
(`treillis_borne` faux) — les quatre conditions sont rendues avec le résultat.

**Pourquoi il n'est pas coché par défaut.** Il ne change le résultat que sur
un jeu sur huit, et il multiplie le calcul par six sur Americas large, où le
résultat était déjà optimal — et où le treillis complet dépasse la mémoire d'un
poste, d'où la borne `mining_treillis_max`. Sur le banc de vérité terrain
bruité (§ 2), les rôles plantés retrouvés à l'identique sont **les mêmes** avec
et sans lui, à chaque niveau de bruit et à chaque seuil.

### Des jeux plus durs que les jeux HP

Les jeux HP sont propres et structurés. Trois familles publiques le sont moins.

**Amazon (Kaggle, *Employee Access Challenge*) et deux synthétiques creux**,
tels que les distribue le dépôt rm-idf (Blundo, Cimato et al., GPL-3 — les
fichiers sont lus, le code n'est pas repris). Aucun optimum publié. θ = 1,
`min_users = min_rights = 1`, sélection exacte :

| Jeu | Dimensions | Habilitations | Glouton | Exact | Treillis complet | Temps (sans / avec treillis) |
|---|---|---|---|---|---|---|
| Amazon 1 | 9 298 × 7 226 | 30 872 | 4 838 | **4 734** | oui | 2,9 s / 10,1 s |
| Amazon 2 | 9 561 × 7 518 | 32 769 | 4 993 | **4 881** | oui | 3,1 s / 10,9 s |
| Amazon 3 | 11 797 × 4 971 | 58 921 | 4 541 | **4 346** | non (borne) | 19,7 s / 42,1 s |
| synt_5k_4k | 4 875 × 4 029 | 13 787 | 2 821 | **2 778** | oui | 0,9 s / 2,2 s |
| synt_6k_24k | 6 000 × 24 000 | 126 572 | 5 049 | **4 892** | oui | 4,8 s / 8,9 s |

Couverture 100 %, sur-octroi nul, solveur clos à l'optimum dans tous les cas.
Sur les quatre jeux où le treillis est complet, le chiffre est donc **l'optimum
prouvé**, au sens du paragraphe précédent. Sur Amazon 3, 4 346 est le minimum
prouvé sur les candidats.

Ces jeux sont durs d'une autre façon : Amazon 1 demande un rôle pour deux
identités. Il n'y a presque pas de structure à trouver, et c'est la bonne
réponse — un outil qui y « trouverait » cent rôles le ferait au prix d'un
sur-octroi massif ou d'une couverture effondrée.

**Rôles plantés de ConstrainedRM** (`datasets/synthetic`, MIT) : quatre jeux
générés à partir d'un modèle connu, de 20 rôles / 200 identités à 100 rôles /
1 000 identités. Ils mesurent ce qui compte plus qu'un nombre de rôles : les
**vrais** rôles sont-ils retrouvés ?

| Jeu | Rôles plantés | Glouton : rôles / retrouvés à l'identique | Exact : rôles / retrouvés |
|---|---|---|---|
| 20_200_40_2_5 | 20 | 20 / 18 | 20 / 18 |
| 40_400_80_4_5 | 40 | 43 / 37 | 40 / 35 |
| 80_800_160_8_5 | 80 | 83 / 74 | 80 / 76 (77 avec treillis) |
| 100_1000_200_10_5 | 100 | 102 / **97** | 99 / 91 |

Sur le plus grand, la sélection exacte trouve **moins de rôles que le modèle
réel** (99 pour 100 plantés) et en retrouve moins à l'identique que le glouton.
C'est le constat du § 2, sur une seconde famille de données produite par
d'autres : le plus petit modèle n'est pas le modèle vrai.

Un jeu plus proche d'un client, avec des attributs RH, existe : **Amazon Access
Samples** (UCI, CC BY 4.0, 30 000 identités). Le réseau de mesure n'y a pas
accès ; il sera mesuré dès qu'il sera déposé sur le poste.

**Le glouton est un bon glouton, pas un optimiseur.** Il rend jusqu'à 42 % de
rôles de plus que l'optimum (Americas large : 564 contre 398). C'est le résultat
d'OBMD, l'heuristique de référence qui lui ressemble le plus.

**Ce qu'il ne faut pas en conclure.** Un nombre minimal de rôles n'est pas un
meilleur modèle. Les jeux HP ne portent aucun bruit ; un référentiel réel en
porte. Sur le banc de vérité terrain à 5 % d'omission et 2 % d'exception
(§ 2), le glouton retrouve 13 des 15 rôles plantés à l'identique. La sélection
exacte n'en retrouve aucun : le plus petit ensemble découpe les rôles réels en
morceaux ajustés au bruit. C'est pourquoi `mining_selection` est livré à
`gloutonne`, et pourquoi le choix appartient au workspace
(`docs/02-parametres.md`, § 2).

**Réserve.** Les dimensions ci-dessus sont celles des fichiers de ConstrainedRM.
Pour Domino, elles diffèrent de la version que distribue OnlineRBACFixing,
mesurée plus bas (711 habilitations au lieu de 730) : ce ne sont pas les mêmes
fichiers.

### La complexité structurelle, comptée comme dans la littérature

Les publications comparent aussi les modèles par leur **complexité
structurelle** (WSC, Molloy et al., 2008) : le nombre de rôles, plus les liens
rôle→droit, plus les liens identité→rôle, plus les liens d'héritage entre rôles.
Kovex rendait jusqu'ici la complexité **à plat** : chaque rôle avec tous ses
droits, rattaché à tous ses porteurs. La hiérarchie qu'il calcule par ailleurs
n'y changeait rien. Depuis le lot 88, il rend aussi la complexité **avec la
hiérarchie** (`wsc_hierarchique`) : un rôle ne porte plus que ses droits
propres, un porteur n'est rattaché qu'au rôle le plus large qu'il porte, et
chaque lien d'héritage compte pour un.

```
python tools/banc_verite_terrain.py public --racine ConstrainedRM/datasets/realWorld \
    --motif "*.txt" --format paires \
    --decompositions ConstrainedRM/decompositions
```

Mesuré le 19/09/2026 avec le glouton, θ = 1, en comparant à la plus basse des
huit décompositions de référence de chaque jeu, comptées de la même façon :

| Jeu | Kovex à plat | Kovex avec la hiérarchie | Meilleure référence | Écart |
|---|---|---|---|---|
| Healthcare | 836 | **145** | 147 (RM4 org_col) | −1 % |
| Firewall-1 | 5 204 | **1 793** | 1 795 (OBMD) | −0,1 % |
| APJ | 6 370 | **4 312** | 4 331 (OBMD) | −0,4 % |
| EMEA | 8 685 | **5 164** | 5 313 (OBMD) | −2,8 % |
| Domino | 907 | 446 | 440 (OBMD) | +1,4 % |
| Firewall-2 | 1 961 | 982 | 972 (FastMiner) | +1,0 % |
| Americas large | 113 091 | 31 404 | 31 081 (RM4 org_col) | +1,0 % |
| Americas small | 20 232 | 7 579 | 7 329 (RM4 org_col) | +3,4 % |
| Customer | 47 824 | 43 843 | 40 827 (RM1 org_row) | +7,4 % |

Kovex fait mieux que les huit références sur quatre jeux et reste à moins de
3,5 % de la meilleure sur quatre autres. Sur Customer, l'écart est de 7,4 %.
Chaque ligne compare Kovex à la meilleure référence **de ce jeu** : ce n'est
jamais la même heuristique qui gagne partout. La sélection la plus courte
(§ précédent) rend moins de rôles mais une complexité hiérarchisée plus
**haute** (Firewall-1 : 1 848, Americas small : 8 892). Les grands rôles que le
glouton prend tôt servent de parents, et la hiérarchie les rentabilise.

**Ce qui a été essayé et écarté.** Le « lattice shrink » de minrolemining
retire un rôle égal à l'union des rôles qu'il contient, jusqu'à point fixe. Sur
le banc de vérité terrain à 5 % d'omission et 2 % d'exception, il fait tomber
les rôles plantés retrouvés à l'identique de 13 à 0. Les fragments de bruit
d'un rôle réel en couvrent l'union, et c'est le rôle réel qui part. L'élagage
des rôles redondants a le même effet. Rattacher chaque porteur au plus petit
ensemble de rôles qui le couvre ne fait gagner que 0 à 2 % sur ces jeux, pour
un modèle moins lisible (« pourquoi elle a ce rôle-ci et pas celui-là ») ;
il n'a pas été retenu.

**La pondération IDF des droits, mesurée et écartée.** rm-idf (GPL-3, idée
reprise, pas le code) pèse chaque droit par `−log2(|U_p| / |U|)` : un droit rare
compte plus qu'un droit commun. Appliquée au gain du glouton — le reste du
moteur inchangé —, elle a été mesurée le 19/09/2026 à θ = 1 sur les neuf jeux
HP et les trois jeux Amazon. Écart en nombre de rôles pour couvrir 100 %
(IDF − glouton) :

| Jeu | Glouton | IDF | Écart |
|---|---|---|---|
| Domino | 21 | 22 | +1 |
| Healthcare | 17 | 16 | −1 |
| EMEA | 43 | 41 | −2 |
| APJ | 465 | 462 | −3 |
| Firewall-1 | 66 | 67 | +1 |
| Firewall-2 | 10 | 10 | 0 |
| Americas small | 196 | 195 | −1 |
| Americas large | 564 | 551 | −13 (−2,3 %) |
| Customer | 287 | 295 | +8 (+2,8 %) |
| Amazon 1 / 2 / 3 | 4 838 / 4 993 / 4 541 | 4 806 / 4 953 / 4 527 | −0,7 / −0,8 / −0,3 % |

Sur la vérité terrain (3 graines, 15 rôles plantés, 0 / 5 / 10 % de bruit,
θ = 1 et 0,8 ; 17 configurations mesurées), les rôles retrouvés à l'identique
sont les mêmes dans 12 cas, meilleurs dans 2, moins bons dans 3. Aucun sens constant, des écarts
de l'ordre de ±3 % : la mesure ne justifie pas de changer le critère, ni d'en
faire un réglage de plus. Écartée.

### Les jeux au format matriciel

Le mode `public` lit aussi le format matriciel (`UPA.txt` : une ligne par
identité, une colonne par droit, 0/1 séparés par des espaces), celui
d'OnlineRBACFixing. Mesuré le 19/09/2026, θ = 1, `min_users = min_rights = 1` :

| Jeu | Dimensions | Habilitations | Kovex glouton | Kovex exact | Temps (exact) |
|---|---|---|---|---|---|
| Domino | 79 × 231 | 711 | 24 | **21** | 0,18 s |
| University | 493 × 56 | 3 945 | 25 | **21** | 0,28 s |
| Firewall-1 | 365 × 709 | 31 919 | 88 | **75** | 9,3 s |
| SmallComp | 11 × 11 | 25 | 7 | **7** | < 0,01 s |

Ces fichiers ne sont pas ceux de ConstrainedRM : Domino porte 711
habilitations au lieu de 730, Firewall-1 31 919 au lieu de 31 951. Leurs
nombres de rôles ne se comparent donc pas aux optima du tableau précédent.
Le dépôt fournit aussi une décomposition de référence de 71 rôles pour Domino,
71 pour University et 13 pour SmallComp.

## 4. Niveau 3 — la consolidation, décidée sur mesure

La vérité terrain plantée ne sert pas qu'à valider : elle sert aussi à trancher
des choix de conception qui, sans elle, se feraient à l'intuition.

Deux façons de simplifier un modèle ont été implémentées puis comparées sur le
même référentiel (600 identités, 15 rôles plantés, 10 % d'omission, 5 %
d'exception, 200 rôles candidats) :

| Stratégie | Seuil | Rôles | Rappel | Rôles exacts | WSC |
|---|---|---|---|---|---|
| aucune | — | 200 | 0,973 | 12 / 15 | 7 754 |
| **fusion** (intersection des droits) | 0,8 | 174 | 0,878 | **4 / 15** | 6 160 |
| **fusion** | 0,7 | 137 | 0,736 | **2 / 15** | 4 591 |
| **absorption** (garder le mieux classé) | 0,8 | 174 | **0,973** | **12 / 15** | 6 133 |
| **absorption** | 0,7 | 137 | **0,973** | **12 / 15** | 4 544 |
| **absorption** | 0,6 | 99 | **0,973** | **12 / 15** | 3 123 |

La fusion simplifie et détruit. L'absorption simplifie à qualité constante :
à seuil 0,6, la moitié des rôles disparaît, la complexité structurelle est
divisée par 2,5, et le rappel comme les rôles retrouvés à l'identique ne bougent
pas d'un chiffre. La fusion a donc été retirée du produit.

Le choix du survivant a été arbitré de la même façon :

| Survivant retenu | Rappel à seuil 0,7 | Rôles exacts |
|---|---|---|
| **le mieux classé par le moteur** | **0,973** | **12 / 15** |
| celui qui porte le plus de droits | 0,797 | 0 / 15 |
| celui qui a le plus de membres | 0,830 | 2 / 15 |

C'est le classement par gain marginal qui porte l'information, pas la taille du
rôle. Sans référentiel à vérité connue, ce résultat n'était pas devinable.

## 5. Ce que le reste de la suite vérifie

- **Aucun droit octroyé en trop à θ = 1**, rôle par rôle, à trois niveaux de
  bruit.
- **Couverture et sur-octroi croissent** quand le seuil baisse.
- **Le mode approché couvre au moins autant que le mode exact.**
- **Reproductibilité à l'octet près** de deux exécutions identiques.
- **Équivalence de la réécriture vectorisée du mining métier** : ancienne et
  nouvelle implémentation exécutées côte à côte sur 33 combinaisons de
  paramètres. Rôles, membres, droits, couvertures, sur-provisionnement, scores
  et statistiques de périmètre strictement identiques dans tous les cas.
- **Contrôle d'accès sur les 86 routes réellement exposées**, lues depuis la
  table des routes de l'application.
- **Parité des trois catalogues i18n** et existence de chaque clé utilisée.
- **Absence de ressource externe** dans le frontend.
- **Absence de donnée simulée** dans les pages du frontend.

## 6. Ce que le mining coûte, et jusqu'où il tient

La justesse ne suffit pas : un mining juste qui met une heure ne sert pas. Il
n'existait aucun test de performance — seulement des relevés ponctuels, refaits
à la main.

### Le jeu de mesure

Un banc ne vaut que par la ressemblance de son jeu d'essai. Deux
caractéristiques sont reprises du référentiel réel :

| Caractéristique | Référentiel réel | Jeu du banc |
|---|---|---|
| Habilitations par identité | ~13 | 13 |
| Signatures distinctes | 69,6 % (12 438 / 17 881) | 69,6 % |
| Signatures partagées par ≥ 3 identités | 409 | même proportion |

Un premier générateur donnait 97 % de signatures distinctes : les temps relevés
n'avaient aucun rapport avec la réalité, et le mining n'y trouvait rien. Un
banc optimiste ne sert à rien.

### Le résultat

`python banc_performance.py` — mesures sur un poste de développement, à titre
de comparaison relative :

| Identités | Habilitations | Droits socles laissés | Socles exclus | Mémoire |
|---:|---:|---:|---:|---:|
| 1 000 | 13 000 | 0,27 s | **0,07 s** | 0,6 Mo |
| 5 000 | 65 000 | 1,60 s | **0,35 s** | 2,8 Mo |
| 10 000 | 130 000 | 4,40 s | **0,69 s** | 5,6 Mo |
| 20 000 | 260 000 | 13,26 s | **1,45 s** | 11,1 Mo |
| 50 000 | 650 000 | 51,99 s | **4,05 s** | 28,3 Mo |

### Le constat qui compte

**Le coût du mining est dominé par les droits que tout le monde détient.** Un
tel droit n'apporte aucune information de regroupement — personne ne s'en
distingue — mais il coûte une incrémentation **par identité et par candidat**.

Une fois ces droits exclus :

- la croissance passe de **n^1,49 à n^1,12** — de nettement superlinéaire à
  quasi linéaire ;
- le temps à 50 000 identités passe de 52 s à **4 s**, treize fois moins ;
- et le résultat est meilleur : le mining retrouve exactement les rôles plantés,
  au lieu de rendre le maximum autorisé de rôles indistincts. Les signatures
  gonflées par des droits socles se ressemblent toutes.

Projection à **500 000 identités**, socles exclus : **moins d'une minute**.
C'est une extrapolation depuis 50 000, pas une mesure — elle situe un ordre de
grandeur. Sans exclusion, la même projection donne près d'une demi-heure.

### Ce qui en découle dans le produit

Le mining exclut déjà automatiquement les droits socles **enregistrés**. Mais
rien n'obligeait à lancer leur détection : le mining partait alors handicapé,
sans que rien ne le signale. Il rend désormais un avertissement
(`mining.universal_rights_not_excluded`) qui donne le nombre de droits
concernés et quelques exemples. Il ne les exclut pas d'autorité : le choix
reste à l'utilisateur.

Le seuil est réglable par workspace — `birth_rights_alert_pct`, 90 % par
défaut.

### Les garde-fous permanents

`tests/test_performance.py` tourne à chaque campagne. Il affirme des **rapports
de croissance**, pas des secondes : « doubler le volume ne doit pas plus que
tripler le temps » reste vrai sur une machine lente comme sur une rapide, là
où un plafond en secondes ne vaut que pour la machine qui l'a écrit.

Ce qui est gardé :

- le mining ne croît pas quadratiquement, dans les deux modes ;
- une fois les socles exclus, la croissance reste quasi linéaire ;
- l'exclusion des droits socles change toujours l'ordre de grandeur ;
- elle améliore aussi le **résultat**, pas seulement le temps ;
- le détail d'une habilitation ne rebalaie pas le référentiel par ligne ;
- l'assemblage du modèle ne recalcule pas l'index des détenteurs par rôle ;
- le jeu d'essai ressemble toujours au référentiel réel.

### Le jeu Amazon : ce qu'il a révélé, et la correction

Les trois jeux Amazon Employee Access (dérivés par rm-idf, 9 298 à 11 797
identités, 3 à 5 droits par identité) ne ressemblent à aucun jeu HP : très
creux, presque autant de profils distincts que d'identités. Le mining y
prenait 76 s, 80 s et 130 s à θ = 1 ; Customer (10 021 identités) 63 s.

Le profil a désigné un seul coupable : le croisement des profils (§ lot 71)
faisait 23 millions d'intersections sur Amazon 1, dont l'immense majorité
entre profils qui ne partagent aucun droit. Deux changements, sans toucher au
résultat :

- un index droit → profils compte, pour chaque profil, ce qu'il partage avec
  chacun des suivants ; seules les paires qui atteignent la taille minimale
  sont croisées ;
- l'intersection se lit dans un masque des droits du profil de gauche plutôt
  que par `intersect1d`, qui concatène et trie à chaque paire.

| Jeu | Avant | Après | Rôles |
|---|---|---|---|
| Amazon 1, θ = 1 | 76,0 s | 2,0 s | 4 838, identiques |
| Amazon 1, θ = 0,8 | 52,2 s | 1,6 s | 5 687, identiques |
| Customer, θ = 1 | 62,7 s | 13,9 s | 287, identiques |
| Customer, θ = 0,8 | 82,3 s | 32,2 s | 960, identiques |
| APJ, θ = 1 | 0,69 s | 0,19 s | 465, identiques |

Les rôles rendus sont identiques, dans le même ordre, sur les neuf jeux HP et
Amazon 1 aux deux seuils ; un test compare le croisement indexé à celui de
toutes les paires sur des référentiels tirés au hasard. Les jeux Amazon ne
sont pas livrés (données dérivées d'une compétition Kaggle) : le banc les lit
sur le poste, `public --format paires`.

### Une optimisation mesurée puis abandonnée

`_expand_members` consomme 66 % du temps de mining et parcourt tout l'effectif
à chaque appel. Une version restreignant la recherche aux seuls membres
possibles a été écrite — un membre détenant `required` droits sur `|R|` figure
forcément dans l'union des `|R| - required + 1` listes de porteurs les plus
courtes. Elle s'est révélée **plus lente** : 0,44 s contre 0,33 s sur 5 000
identités, 1,75 s contre 1,40 s sur 20 000. Le tri, la concaténation et la
déduplication coûtent davantage que le balayage vectorisé qu'ils évitent.

Elle a été retirée. C'est la deuxième optimisation « évidente » de ce chantier
à mesurer moins bien que le code qu'elle remplaçait.

## 7. Comment rejouer

```bash
python -m pytest                                          # toute la suite

python -m pytest tests/test_mining_verite_terrain.py      # justesse
python -m pytest tests/test_threshold_explorer.py         # exploration du seuil
python -m pytest tests/test_role_quality.py               # qualité et consolidation
python -m pytest tests/test_consolidation_explorer.py     # courbe de consolidation
python -m pytest tests/test_performance.py                # garde-fous de performance

python banc_performance.py                                # volumétrie, jusqu'à 20 000
python banc_performance.py --jusqu-a 50000 --json m.json  # plus loin, mesures conservées
python -m pytest tests/test_banc_verite_terrain.py        # le banc lui-même

python tools/banc_verite_terrain.py synthetique --seuils 1.0 0.9 0.8 0.7
python tools/banc_verite_terrain.py public --racine <dossier contenant les UPA.txt>
python tools/banc_verite_terrain.py public --racine <ConstrainedRM/datasets/realWorld> \
    --motif "*.txt" --format paires --selection exacte \
    --references tools/references/hp_optima.json \
    --generateurs cloture,signature,intersection,treillis   # les huit optima
```

Le jeu de données des tests est **généré**, jamais lu depuis un workspace
client : la suite tourne sur un poste vierge et sur un serveur isolé.

Les bornes inscrites dans les tests sont des **garde-fous de non-régression**,
choisies sous les valeurs mesurées. Ce ne sont pas des objectifs : les valeurs
réelles sont dans les tableaux ci-dessus. Les modules de mesure eux-mêmes sont
couverts à 100 % — un banc faux produirait des chiffres faux sans que rien ne le
signale.

## 8. Sources

- [Role Mining Data for RBAC Programming Challenge — Y. A. Liu, Stony Brook University (LPOP20)](https://www3.cs.stonybrook.edu/~liu/papers/RoleMiningData-LPOP20.pdf)
- [Algorithms for Mining Meaningful Roles — Z. Xu, S. D. Stoller (SACMAT'12)](https://www.fsl.cs.sunysb.edu/ssw/files/Download/xu12algorithms.pdf)
- [OnlineRBACFixing — dépôt distribuant les jeux Domino, University, Firewall-1, SmallComp au format UPA/UA/PA](https://github.com/OnlineRBACFixing/OnlineRBACFixing)
- [IRMAOC — Cybersecurity, SpringerOpen, 2024](https://cybersecurity.springeropen.com/articles/10.1186/s42400-024-00348-z)
- [ConstrainedRM — jeux HP, optima, décompositions de référence et synthétiques à rôles plantés (MIT)](https://github.com/RoleMining/ConstrainedRM)
- [rm-idf — jeux Amazon (Kaggle) et synthétiques creux (GPL-3, fichiers lus, code non repris)](https://github.com/carblu/rm-idf)
- [Amazon Access Samples — UCI Machine Learning Repository (CC BY 4.0)](https://archive.ics.uci.edu/ml/datasets/Amazon+Access+Samples)
