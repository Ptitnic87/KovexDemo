# Kovex aux Assises 2026 — déroulé de l'atelier en direct

**45 minutes · démonstration en direct · RSSI et décideurs · document du 28 septembre 2026**

Ce document remplace, pour les Assises, le document de tournage du 15/09. Ce
dernier visait une vidéo de 30 minutes pour des consultants. Ici, le public est
un comité de sécurité, et tout se joue en direct : chaque calcul doit tenir
dans le temps où l'on parle.

Tous les chiffres ci-dessous ont été **relevés sur l'écran le 28/09**, sur le
référentiel de démonstration, pas sur des données de client. Les durées ont été
mesurées sur une machine de 2 cœurs. **Répète une fois sur le poste de
l'atelier** et corrige les durées si elles diffèrent.

---

## La thèse, en une phrase

> Qui a accès à quoi, pourquoi — et pouvez-vous le prouver dans six mois ?
> Kovex répond aux trois questions sur vos propres fichiers, sur votre poste,
> sans rien envoyer nulle part. Chaque chiffre se dérive ; rien ne se décide
> sans un humain.

Pour un RSSI, le role mining n'est pas le sujet : c'est le moyen. Le sujet,
c'est la **preuve** et la **dérive**.

---

## 1. Préparer (la veille)

**Version requise : celle du sous-module `kovex/` de ce dépôt (lot 103 inclus).** Sans lui, la toile de
l'acte 5.3 n'a pas ses axes écrits, et les tuiles du mining affichent
« 63.73 % » au lieu de « 63,73 % ».

### P1. Les deux espaces de travail

Ils viennent de la plateforme de démonstration (ce dépôt) : aucun script à
lancer la veille. `lancer_la_demo.sh` (ou `LANCER_LA_DEMO.bat`) les remet dans
leur état figé à chaque lancement, **dates décalées au jour même**. Le
contrôle compensatoire a donc toujours été exécuté une semaine avant, et la
dérogation échoit toujours dans trois mois.

Tous deux portent le même référentiel synthétique (groupe d'assurance fictif
« Alvéa » : 20 999 identités, 8 000 droits, 240 applications, 255 882
habilitations) :

| Espace | Ce qu'il contient | Sert à |
|---|---|---|
| **Atelier — référentiel brut** (`Alvea_ATELIER`) | les fichiers, rien de décidé | actes 1 à 4 : du fichier brut au modèle |
| **Assurance — Groupe Alvéa** (`Alvea_DEMO`) | 2 règles de séparation, 1 contrôle compensatoire exécuté il y a 7 jours et exigé par les dérogations, 1 dérogation à échéance J+90, 1 rôle fait main, 56 décisions (33 validations, 23 refus), un mining applicatif et un mining métier conservés | actes 5 et 6 : ce qui dérive, et la preuve |

**Relance la plateforme juste avant l'atelier** : ce qu'une séance précédente
aurait validé ou supprimé disparaît.

### P2. L'authentification

**Elle doit être active.** Vérifie que `.env` ne contient pas
`PYGIA_AUTH_DISABLED=true` et connecte-toi avec un compte nominatif. Sans elle,
la piste d'audit de l'acte 6 signe chaque entrée « anonymous » avec la mention
« authentification-desactivee » — exactement ce qu'un RSSI relève en premier.

### P3. Le poste

- Langue **Français**, fenêtre 1920 × 1080, zoom navigateur 100 %, barre de
  favoris masquée.
- **Wi-Fi coupé.** Le dire à la salle : « rien de ce que vous allez voir ne sort
  de ce poste ».
- Ollama n'est pas nécessaire : rien dans ce déroulé n'en dépend. S'il tourne,
  la variante de l'acte 5 le montre.
- Espace actif au démarrage : **Atelier — référentiel brut**. Lance la
  plateforme avec `lancer_la_demo.sh --actif Alvea_ATELIER` (ou
  `LANCER_LA_DEMO.bat --actif Alvea_ATELIER`).
- Un second onglet ouvert sur **Piste d'audit**, dans l'espace « Assurance —
  Groupe Alvéa », pour l'acte 6.

---

## 2. Découpage

| # | Acte | Espace | Durée | Cumul |
|---|---|---|---|---|
| 0 | Ouverture : la question du RSSI | — | 3 min | 3 |
| 1 | Le référentiel qu'on n'a pas regardé | brut | 8 min | 11 |
| 2 | Ce qui dort | brut | 4 min | 15 |
| 3 | La séparation des tâches, avant le modèle | brut | 5 min | 20 |
| 4 | Un modèle qu'on peut défendre | brut | 11 min | 31 |
| 5 | Six mois plus tard : ce qui dérive | Alvéa | 8 min | 39 |
| 6 | La preuve, et l'IA qui ne décide pas | Alvéa | 4 min | 43 |
| — | Questions | — | 2 min + | 45 |

Deux calculs seulement prennent du temps, et tous deux tombent dans l'acte 4 :
**l'exploration du seuil (35 à 40 s)** et **le mining applicatif complet
(2 min 15 à 2 min 40)**. Chacun est lancé *avant* le texte qui l'accompagne.

---

## Acte 0 — La question du RSSI · 3 min · écran : tableau de bord, sans commentaire

🗣 « Trois questions que tout auditeur finit par vous poser. Qui a accès à quoi.
Pourquoi. Et pouvez-vous le prouver — pas aujourd'hui, dans six mois, quand la
personne qui a décidé sera partie.

Les outils répondent bien à la première. Mal à la deuxième. Presque jamais à la
troisième.

Ce que je vais vous montrer tourne sur ce poste, Wi-Fi coupé. Les données sont
celles d'un assureur fictif, vingt mille personnes, huit mille droits. Ce
sont des données inventées, mais tout ce que vous allez voir est calculé devant
vous. »

⚠ Ne dis pas « IA » dans les trois premières minutes. La salle en a entendu
parler toute la journée.

---

## Acte 1 — Le référentiel qu'on n'a pas regardé · 8 min · espace brut

### 1.1 Tableau de bord — 1 min

**MENU** → « Tableau de Bord »

À l'écran : **20 999** utilisateurs, **240** applications, **8 000** droits,
santé **100 /100 « Sain »**, 12 droits en médiane par identité.

🗣 « Rien de cassé. Aucune ligne orpheline, aucune habilitation qui pointe dans le
vide. Un référentiel propre, en apparence. Et pourtant. »

### 1.2 Qualité des données — 3 min

**MENU** → « Qualité des Données ». Attends la fin de l'analyse, quelques
secondes.

Dans « Détails des Anomalies », trois lignes :

- **800** droits ne sont rattachés à aucune application ;
- **1 118** droits du référentiel ne sont attribués à personne ;
- **1** droit dont le nombre de porteurs tombe exactement sur une borne
  d'export connue.

**CLIC** sur « Voir les identifiants (1) » de la troisième ligne : c'est
`GED_DOS_REA_DOCUMENT`.

🗣 « Celui-là est celui que je préfère. Un droit détenu par cinq mille personnes.
Pas quatre mille neuf cent quatre-vingt-dix-sept : cinq mille pile.

Cinq mille, c'est le plafond d'une vue de liste dans un portail documentaire.
Un export tronqué ne ressemble pas à une erreur, il ressemble à une donnée. Le
fichier se charge et les chiffres sont plausibles, mais tout ce qu'on en déduit
est faux. Vous allez voir dans dix minutes que ça fausse même la séparation des
tâches.

Le produit ne dit pas que c'est tronqué. Il dit que ça tombe pile sur une
borne, et que ça se vérifie à la source. »

**Les 800 droits sans application**, une phrase : « ceux-là ne seront jamais
recertifiés dans une campagne par application : personne ne les voit. »

### 1.3 Cohérence des valeurs — 2 min

Plus bas, carte **« Cohérence des valeurs »**.
**SAISIE** « Colonne à analyser » : `Identités — type_contrat`.
**CLIC** → **« Analyser cette colonne »**.

À l'écran : 4 rapprochements proposés sur 10 valeurs. En tête : **CDI**
(9 728), **C.D.I.** (2 723), **Contrat à durée indéterminée** (1 479). Population
réunie : **13 930**. La mention dit « repérage local ».

🗣 « Trois façons d'écrire le même contrat. Pour un outil, ce sont trois
populations, donc trois rôles, ou aucun.

Regardez la mention : repérage local. Aucun modèle de langage n'a été appelé. Les
sigles se reconnaissent par leur forme, sur ce poste. Et rien ne s'applique tout
seul : vous acceptez, vous refusez, et c'est tracé. »

⚠ N'accepte rien : on montre la proposition, pas la correction.

### 1.4 Comptes à privilèges — 30 s (facultatif)

**MENU** → « Paramètres », carte « Paramètres Globaux », champ « Comptes à
privilèges » : le fragment `ADM` est déclaré. Sur les 20 999 identités, **611**
sont des comptes `.ADM` ; il reste environ 20 388 personnes.

🗣 « Le produit ne devine pas ce qu'est un compte à privilèges chez vous. Vous
le déclarez, et il le marque partout : dans les rôles, dans les conflits. »

---

## Acte 2 — Ce qui dort · 4 min · espace brut

**MENU** → « Usage des droits »

- « Dernière utilisation (fichier des habilitations) » : `derniere_utilisation`
- « Dernière connexion (fichier des identités) » : `derniere_connexion`
- « Format des dates » : `%d/%m/%Y`
- « Inactif au-delà de (jours) » : `180`
- « Nombre de droits montrés » : `50`

**CLIC** → **« Lire l'usage »**, réponse en trois secondes environ.

À l'écran : inactivité mesurée au **15/09/2026**, la date la plus récente
trouvée faute de date d'export déclarée. **10 962 habilitations** n'ont pas servi
depuis 180 jours, sur **1 053 droits**. En tête de liste, les droits d'une même
application, `MGN_…` : ses **17 droits** sont tous dormants, et ils sont détenus
par **2 350 personnes** distinctes. Le premier de la liste, à lui seul : 988
détenteurs sur 988 ne s'en servent plus. Plus
bas, **520 identités** ne se sont pas connectées depuis le seuil.

🗣 « Tout en haut, une application entière que plus personne n'utilise, et que
deux mille trois cent cinquante personnes détiennent encore. C'est un
décommissionnement que personne n'a fait. C'est aussi une surface d'attaque
que personne ne surveille.

Et cinq cent vingt comptes qui ne se connectent plus. Partis ? En congé ?
Le référentiel ne le dit pas. Le produit ne tranche pas à votre place : il
vous donne la liste. »

**Remarque clé pour la salle** : l'inactivité se mesure à la **date de
l'export**, jamais à aujourd'hui. Sinon, le même fichier dirait autre chose
la semaine prochaine.

---

## Acte 3 — La séparation des tâches, avant le modèle · 5 min · espace brut

**MENU** → « Séparation des tâches » (section « Prétraitement »)

🗣 « Dans la plupart des outils, la séparation des tâches est un contrôle qu'on
passe **après** avoir construit ses rôles. C'est l'ordre le plus coûteux : une
règle qui arrive après coup invalide des rôles déjà signés en comité.

Ici, elle se déclare avant. Et comme personne ne remplit jamais une liste vide
de huit mille droits, le produit commence par regarder ce que vos données
savent déjà. »

**MONTRER** la carte **« Couples que votre organisation sépare déjà »**.

Première ligne : **GED_DOS_REA_DOCUMENT / ACH_DOS_CRE_COMMANDE**. « 5 000
détiennent l'un, 2 602 l'autre. On en attendrait 620 avec les deux ; il y en a
271. »

🗣 « Tiens. Cinq mille. Notre droit tronqué de tout à l'heure. Si l'export est
coupé, il manque des porteurs, donc des cumuls, et le produit vous propose une
règle qui n'existe pas. Une donnée d'entrée fausse ne reste jamais dans son
coin. »

Deuxième ligne : **SIN_DOS_CRE_DOSSIER / IND_FLU_VAL_MOUVEMENT**. « 2 601
détiennent l'un, 2 602 l'autre. On en attendrait 322 avec les deux ; il y en a
0. »

🗣 « Celle-là est une vraie règle : déclarer un sinistre, et valider son
indemnisation. Deux mille six cents personnes de chaque côté, et personne n'a
les deux. Ce n'est pas un hasard : c'est un contrôle que l'organisation
applique déjà, sans l'avoir écrit nulle part.

Regardez comment c'est dit : un nombre de personnes attendu, un nombre
observé. Pas un score. Et c'est calculé sans aucun modèle : deux lectures
rendent la même liste, dans le même ordre. C'est la condition pour qu'un
auditeur s'en serve. »

**CLIC** → **« En faire une règle »** sur la deuxième ligne, puis
**« Sauvegarder »**.

⚠ Ne sauvegarde pas la première ligne. C'est l'artefact de la troncature.

---

## Acte 4 — Un modèle qu'on peut défendre · 11 min · espace brut

### 4.1 Droits socles — 1 min

**MENU** → « Droits socles ». « Seuil de Fréquence (%) » : `90`.
**CLIC** → **« Détecter les droits socles »**.

À l'écran : **3 droits socles** (badge, messagerie, intranet), détenus par
95,5 % à 95,6 % de la population.

🗣 « Le badge, la messagerie, l'intranet. Tout le monde les a : ils ne disent
rien d'un métier. Ils forment un rôle à part, le socle, et sortent du calcul. »

### 4.2 Explorer le seuil — 3 min · **lancer d'abord, parler ensuite**

**MENU** → « Mining Applicatif ».
« Mode de Mining » : **« Approché (similarité) »**. Sans ce choix, l'explorateur
n'apparaît pas.

Dans « Comment chercher », laisse cochées **« Partir d'un droit »** et **« Partir
d'un profil exact »**. **Décoche** « Croiser les profils » et « Croiser plus de
deux profils ».

Carte **« Explorer le seuil de similarité »** : Seuil de départ `0,90`, Seuil
d'arrivée `1`, Pas `0,05`. Laisse « Sur-octroi maximal accepté (%) » **vide**.
**CLIC** → **« Explorer »**, 35 à 40 s.

🗣 *(pendant le calcul)* « Chaque point est un mining complet sur vos données, pas
une extrapolation. Le seuil, thêta, dit à quel point un rôle a le droit
d'accorder à quelqu'un un droit qu'il n'a pas encore. À un, jamais. »

À l'écran : la courbe et le tableau.

| Seuil | Rôles | Couverture | Sur-octroi |
|---|---|---|---|
| 1 | 200 ⚠ | 75,87 % | 0 % |
| 0,95 | 200 ⚠ | 75,96 % | 0 % |
| 0,9 | 200 ⚠ | 81,65 % | 8,79 % |

🗣 « Voilà l'arbitrage classique. Pour couvrir six points de plus, on accorde
près de neuf pour cent de droits que les gens n'avaient pas. En sécurité, ça
s'appelle de l'élévation de privilèges, et elle serait signée par un comité.

Et le produit ne choisit pas pour vous. Aucune contrainte n'est saisie, donc
aucun seuil n'est désigné. La phrase le dit : le choix vous revient. »

Le ⚠ à côté de 200 : « C'est le plafond de rôles, une valeur par défaut que
chacun règle. Le produit dit qu'il l'a atteint au lieu de le cacher. »

⚠ Le droit tronqué `GED_DOS_REA_DOCUMENT` entre dans le premier rôle proposé
(`APPROX_ROLE_001`). Si la question vient : « c'est pour ça que la qualité se
regarde avant le mining ; ce rôle-là ne se valide pas tant que l'export n'est
pas refait ».

### 4.3 Le mining complet — 4 min · **lancer d'abord, parler ensuite**

Coche maintenant **« Croiser les profils »**.
« Seuil de similarité » : `1`.
**CLIC** → **« Lancer le Mining Applicatif »**, 2 min 15 à 2 min 40.

🗣 *(pendant le calcul, c'est le moment de la thèse)* « Je viens de cocher une
troisième façon de chercher : croiser les profils, c'est-à-dire trouver ce que
deux populations ont en commun. C'est le rôle qu'un analyste écrirait en
premier, et c'est celui qu'aucune des deux autres méthodes ne propose.

Ce que ça change, je l'ai mesuré sur ce référentiel. »

**MONTRER** le tableau suivant, préparé en diapositive ou sur papier. Les
couvertures sont comptées hors droits socles, comme dans l'explorateur.

| Façons de chercher | θ | Couverture | Droits accordés en trop | Hors modèle |
|---|---|---|---|---|
| droit + profil | 1,00 | 75,9 % | 0 | 47 212 |
| droit + profil | 0,90 | 81,7 % | 17 209 | 35 900 |
| **+ croiser les profils** | **1,00** | **83,3 %** | **0** | **32 601** |
| + croiser les profils | 0,90 | 85,9 % | 8 282 | 27 610 |

🗣 « Comparez la troisième ligne à la deuxième. **Plus de couverture, et zéro
droit accordé en trop.** Le sur-octroi que le seuil achetait n'était pas le prix
de la couverture. C'était le prix d'une recherche trop pauvre. On payait en
sécurité ce qu'il fallait payer en calcul.

Pour vous, ça se dit simplement : un modèle de rôles qui n'accorde à personne
un seul droit qu'il n'a pas déjà. Ce qui reste, les habilitations hors modèle,
reste en attribution individuelle. Ce n'est pas un échec du modèle : c'est ce
qui reste à décider, nommément. »

À l'écran, quand le calcul se termine :

- **« Ce que le mining a trouvé »** : 200 rôles, 19 756 utilisateurs, 295 droits,
  105 applications ;
- **« Ce que ce modèle reprend, et à quel prix »** : habilitations couvertes
  **63,73 %**, droits octroyés en trop **0 %**, hors modèle **92 815** ;
- **« Ce que valent ces rôles »** : compression 1,87, redondance 56,47 %.

⚠ **La question qui viendra : « 63,73 % à l'écran, 83,3 % sur votre tableau ? »**
La tuile compte sur **tout** le référentiel, droits socles compris (255 882
habilitations). Le tableau et l'explorateur comptent sur les 195 668
habilitations analysées, **socles retirés** : la phrase sous la courbe le
précise. Les 92 815 hors modèle comprennent les 60 214 habilitations des trois
droits socles, qui sont portées par le rôle socle. Réponds-le tel quel : c'est
exactement ce que fait le produit, dire sur quoi porte chaque chiffre.

### 4.4 Un rôle, ouvert — 1 min 30

**CLIC** sur une carte de résultat : la fenêtre de validation s'ouvre.

**MONTRER** les onglets « Droits (n) », « Identités (n) » et « Explication ».
Dans « Explication », coche un ou deux « Attributs à croiser » (par exemple
`departement`, `fonction`), puis **CLIC** → **« Expliquer ce rôle »** : **ce
qui plaide pour, ce qui plaide contre** s'affiche, chacun avec son chiffre.

⚠ Choisis une carte **autre que la première** : la première contient le droit
tronqué (voir 4.2).

Relevé sur la deuxième carte (`APPROX_ROLE_002`, onglets « Droits (6) » et
« Identités (598) ») : la règle proposée est **fonction = Développeur**,
fiabilité **38,7 %** pour 90 % attendus, et elle désignerait **948 personnes
de plus** — 61,3 % de ce qu'elle accorderait.

🗣 « Regardez : le produit trouve la règle la plus proche, et il dit qu'elle ne
tient pas. Si on attribuait ce rôle à tous les développeurs, neuf cent
quarante-huit personnes recevraient des droits qu'elles n'ont pas. Un outil
qui ne sait que proposer ne vous aurait pas dit ça. »

🗣 « Chaque rôle dit qui en est membre, quels droits, combien de ses membres les
détiennent déjà. Et le diagnostic n'est pas un score : ce sont des constats
séparés, chacun avec son chiffre. Un score que personne ne peut décomposer,
personne ne peut le contester devant un auditeur. »

⚠ Ne valide pas. Ferme.

### 4.5 Mining métier — 1 min 30

**MENU** → « Mining Métier ». Coche **departement** et **fonction**.
**CLIC** → **« Lancer l'Analyse Métier »**, 3 secondes environ.

À l'écran : **33 rôles**, couverture moyenne **88,2 %**, sur-octroi **9,7 %**,
et « Sur-octroi si attribué » **24 747**. La phrase sous les tuiles relie les
deux : attribuer ces rôles octroierait 24 747 attributions que personne ne
détient aujourd'hui, soit 9,7 % de ce que le modèle accorde.

🗣 « Le premier écran regroupait les gens par ce qu'ils **détiennent**. Celui-ci
les regroupe par ce qu'ils **sont** : leur département, leur fonction. Il rend
des règles, pas des paquets : "les gestionnaires sinistres reçoivent ces
droits-là". Une règle s'applique toute seule le jour où quelqu'un arrive.

Et regardez ce chiffre : vingt-quatre mille attributions **créées** le jour où on
applique ces règles. Des gens qui recevraient des droits qu'ils n'ont pas
aujourd'hui. Le produit le compte avant, pas après la mise en production. »

---

## Acte 5 — Six mois plus tard : ce qui dérive · 8 min · espace Assurance — Groupe Alvéa

Change d'espace par le sélecteur en haut à gauche : **« Assurance — Groupe
Alvéa »**.

🗣 « Même référentiel. Imaginons que l'équipe y ait travaillé six mois : des
règles déclarées, des rôles validés, des exceptions accordées. »

### 5.1 Conflits constatés — 3 min

**MENU** → « Conflits de séparation » (section « Gouvernance »).

À l'écran : **40 identités en conflit sur 20 999, dont 1 acceptée**. Règle
**« Créer et valider un même contrat »**, sévérité Critique, processus
Souscription, propriétaire Direction des risques.

**CLIC** → **« Voir Détails »**.

À l'écran : le rôle **« Souscription — bureau des contrats »** accorde à lui seul
les deux côtés. **38 conflits** passent par ce rôle, **2 sont hors rôle**.

🗣 « Quarante conflits, ça ne se traite pas. Trente-huit qui viennent d'un seul
rôle, ça se traite en une décision : un rôle qui accorde les deux côtés donne
le conflit à tous ses porteurs, présents et futurs. On corrige le rôle, on
corrige trente-huit personnes d'un coup, et celles qui arriveront demain. »

**MONTRER** la ligne acceptée : l'agence de Lille, avec son motif, son échéance
dans trois mois et le contrôle « Revue mensuelle des contrats validés ».
Des deux conflits hors rôle, **un seul** est couvert par cette dérogation ;
l'autre reste un conflit ouvert.

🗣 « Et les deux autres ? L'un est une exception assumée : une petite agence,
une seule personne habilitée. L'autre, personne ne l'a encore traité, et il
reste affiché. Une exception, ici, porte un motif, une **échéance
obligatoire**, et un **contrôle compensatoire** : exécuté par quelqu'un, relu
par un autre, il y a moins de trente et un jours, avec sa preuve. Si le
contrôle cesse de tourner, l'exception cesse de couvrir. Et l'écran le dit. »

### 5.2 Droits conservés — 2 min

**MENU** → « Droits conservés ». « Qui sont ses pairs » : `fonction`.

À l'écran : **6 identités** portent des droits typiques d'un autre métier. Chaque
ligne dit, pour la personne, la part de ses anciens pairs qui détiennent les
mêmes droits — **au moins 84,3 %** sur le premier constat.

🗣 « C'est ce qu'un client m'a dit en premier : ce qui l'inquiète, ce n'est pas
ce qu'on donne à quelqu'un qui arrive, c'est ce qu'on oublie de retirer à
quelqu'un qui bouge.

L'idée est contre-intuitive : un droit résiduel n'est pas un droit rare, c'est
un droit **typique ailleurs**. Il est absent chez ses collègues actuels, et
présent chez presque tous ses anciens. Deux nombres, pas un score. »

### 5.3 Ce que le produit apprend de vos décisions — 3 min

**MENU** → « Apprentissage ».

À l'écran : **56 décisions** (33 validations, 23 refus). Rejouées à rebours,
**55 sur 56 sont retrouvées**, contre 33 en répondant toujours la réponse
majoritaire. La toile montre la forme moyenne de ce que l'équipe valide, et ses
axes sont écrits à côté.

🗣 « Chaque validation et chaque refus est gardé avec les chiffres que la
personne avait sous les yeux. Le produit en apprend, **localement**, une seule
chose : "ce candidat ressemble à ce que vous validez". C'est un tri de
l'attention, pas une décision. Et ça se mesure : cinquante-cinq sur
cinquante-six, contre trente-trois pour qui répondrait toujours pareil. »

Facultatif, si le temps le permet : **MENU** → « Mining Applicatif », laisse
seulement les deux premières façons de chercher, θ = `1`, **« Lancer le Mining
Applicatif »** (≈ 10 s). Chaque carte porte « Ressemble à vos validations : …
% », les deux raisons les plus fortes, et la toile avec ses axes.

⚠ Sur ce référentiel, les toiles des cartes se ressemblent toutes : à θ = 1,
aucun rôle n'accorde de droit en trop, et les décisions préparées rangent
toutes les populations entre 237 et 459 porteurs au même rang (41,1). Ce qui
distingue les scores (70,1 % contre 13,8 %), c'est le nombre de droits, qui
n'est pas un axe de la toile. Montre le score et ses raisons ; ne commente
pas la forme.

---

## Acte 6 — La preuve, et l'IA qui ne décide pas · 4 min

### 6.1 Piste d'audit — 2 min

Passe au second onglet, **« Piste d'audit »**.
**CLIC** → **« Vérifier l'intégrité »**.

À l'écran : **« Chaîne intacte : N entrées vérifiées, aucune altération
détectée. »** N vaut 73 juste après la préparation et augmente avec chaque
geste fait pendant l'atelier.

🗣 « Et voilà la réponse à la troisième question. Chaque mining avec ses
paramètres : sans eux, un rôle validé il y a six mois n'est pas
reproductible. Chaque validation, chaque refus, chaque exception, chaque
changement de configuration.

La piste est **chaînée** : chaque entrée scelle la précédente. Si quelqu'un
modifie une ligne après coup, ce bouton le voit. »

### 6.2 Ce que le produit refuse de demander à un modèle — 2 min

**MENU** → « Paramètres », carte **« Assistance par modèle »**.

🗣 « Tout le monde vous a vendu de l'IA aujourd'hui. Voici ce que je vous montre
à la place.

Cet écran dit, usage par usage, ce que le produit a le **droit** de demander à
un modèle, et ce qui partirait. Par défaut, **tout est fermé**. Les identités ne
sortent jamais : ce n'est pas un réglage, c'est une règle du produit.

Et ce qu'il ne fera jamais, quelle que soit la configuration : recommander de
valider un rôle, produire un score de risque, décider quoi que ce soit.

L'IA nomme. L'algorithme compte. Vous décidez, et c'est tracé. »

**VARIANTE, si Ollama tourne** : ouvre l'usage « Proposition de nom de rôle »,
retourne sur un résultat de mining et nomme un rôle. La piste d'audit consigne
l'appel et les catégories envoyées, **jamais leur contenu**.

---

## 3. Fiche de secours

| Si… | Alors |
|---|---|
| Le mining complet dépasse 3 min | Annonce les chiffres de l'acte 4.3 (200 rôles, 63,73 %, 0 % en trop) et passe à 4.5. Reviens au résultat avant l'acte 5 |
| « Comment chercher » ou l'explorateur n'apparaissent pas | Le mode est resté sur « Exact ». Repasse « Mode de Mining » sur « Approché (similarité) » |
| La dérogation s'affiche « sans effet » | La préparation date de plus de 24 jours : le contrôle a dépassé son âge maximal. Dis-le, c'est le produit qui fonctionne : « un contrôle qui ne tourne plus ne couvre plus rien » |
| L'écran des conflits dit « aucune règle déclarée » | Tu es resté dans l'espace brut : le sélecteur en haut à gauche doit afficher « Assurance — Groupe Alvéa ». Change d'espace, l'écran se recharge |
| Un chiffre diffère de ce document | Lis celui de l'écran. Ce document a été relevé sur une autre machine ; l'écran a raison |
| Une question sur la couverture « 63,73 % contre 83,3 % » | Voir l'encadré de l'acte 4.3 |
| « Et si mes données sont en anglais ? » | Le produit ne traduit pas les données : il lit vos colonnes et vos valeurs telles qu'elles sont, dans n'importe quelle langue. Le sélecteur en haut à droite change la langue **de l'interface** : français, anglais, allemand |
| La piste d'audit montre « anonymous » | L'authentification est désactivée (voir P2). Ne montre pas l'acte 6.1 dans cet état |

---

## 4. Ce qu'il ne faut pas dire

| Ne dis pas | Dis plutôt |
|---|---|
| « L'IA trouve vos rôles » | « L'algorithme les trouve, et chaque chiffre se dérive » |
| « Score de risque » | « Ce qui plaide pour, ce qui plaide contre, chacun avec son chiffre » |
| « L'outil recommande » | « Le produit propose, vous décidez, c'est tracé » |
| « Prêt pour la production » | Parle de ce qui a été mesuré devant eux |
| « Le mining » tout court | « Le mining applicatif » ou « le mining métier » |

---

## 5. Ce qui a changé depuis le document de tournage du 15/09

- **Public et format** : RSSI et décideurs, en direct, 45 minutes, contre une vidéo
  de 30 minutes pour des consultants.
- **Chiffres** : tous relevés sur le référentiel de démonstration. Le tableau
  d'incrustation du 15/09 venait d'un référentiel de client : il ne se cite
  plus.
- **Cohérence des valeurs** : le rapprochement CDI / C.D.I. / « Contrat à durée
  indéterminée » se fait désormais **sans modèle**. Ce n'est plus « la première
  intervention de l'IA », c'est mieux pour ce public.
- **Façons de chercher** : il y en a quatre. La quatrième, croiser plus de deux
  profils, n'apporte presque rien sur ce référentiel (83,6 % au lieu de
  83,3 %, en 3 min 40 au lieu de 2 min 16) ; elle reste décochée.
- **Nouveaux écrans intégrés** : droits conservés (lot 67), puis usage des
  droits, apprentissage et contrôles compensatoires (lots 84 à 97). Ils parlent
  directement à un RSSI.
- **Explorer le seuil** : de 0,90 à 1 et avec deux façons de chercher seulement.
  L'intervalle de 0,80 à 1 du document de tournage prenait plusieurs minutes
  par point.
