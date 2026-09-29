# 01 — L'approche

## 1. Le problème

Une organisation accumule des habilitations : des couples (identité, droit).
Chez un client de taille moyenne, 18 000 identités et 8 000 droits produisent
230 000 couples. Personne ne sait plus pourquoi la majorité d'entre eux existe.

Le *role mining* cherche la structure sous-jacente : des ensembles de droits
qui reviennent ensemble chez des populations comparables, et qu'on pourrait
attribuer d'un bloc plutôt qu'un par un. Un rôle bien trouvé remplace des
centaines d'attributions individuelles par une règle.

Deux natures de rôles coexistent dans Kovex, et elles ne se découvrent pas de
la même façon :

- **Rôle applicatif** — un paquet de droits techniques qui va ensemble.
  Il se découvre en regardant *la matrice des habilitations*.
- **Rôle métier** — un paquet de droits que détiennent les gens partageant un
  même attribut RH (direction, fonction, site). Il se découvre en croisant
  *les attributs des identités* avec leurs habilitations.

## 2. Le modèle de données

Kovex ne présuppose **rien** sur vos fichiers, hors le fait qu'ils s'articulent
par des identifiants que vous désignez.

    identités ──(ID utilisateur)── habilitations ──(ID droit)── droits ──(ID application)── applications

Quatre fichiers, quatre rôles :

| Fichier | Ce qu'il apporte | Colonnes que vous désignez |
|---|---|---|
| identités | la population et ses attributs RH | l'identifiant |
| habilitations | les couples (identité, droit) | l'identifiant d'identité, l'identifiant de droit |
| droits | le référentiel des droits et leur rattachement applicatif | l'identifiant de droit, l'identifiant d'application |
| applications | le référentiel des applications | l'identifiant |

Toutes les autres colonnes sont conservées telles quelles et exploitées sans
être nommées : ce sont elles qui deviennent des critères de rôle métier, et
qui s'affichent dans l'infobulle d'une identité sur le graphe.

Le détail du fichier de configuration est dans [05 — Données](05-donnees.md).

En mémoire, les habilitations deviennent une **matrice creuse** identités ×
droits au format CSR. C'est cette structure qui rend le mining rapide : les
droits d'une identité s'obtiennent en temps constant, sans rebalayer la matrice.

## 3. Le mining applicatif

### 3.1 Le mode exact

Deux identités qui détiennent **exactement** le même ensemble de droits ont la
même *signature*. Le mode exact regroupe les identités par signature : chaque
groupe assez peuplé et assez fourni devient un rôle candidat.

C'est le critère le plus sûr qui soit : un membre du rôle détient déjà, par
construction, tous les droits du rôle. Personne ne reçoit rien de nouveau.

C'est aussi le plus stérile. Sur un référentiel réel, la plupart des identités
ont une signature unique — il suffit d'une dérogation pour sortir du groupe.
Mesuré sur un référentiel de 17 881 identités et 234 689 habilitations : le
mode exact produit 374 rôles qui couvrent **4,7 %** des habilitations. Les 95 %
restants demeurent des attributions individuelles.

Le mode exact garde son utilité : il ne se trompe jamais, et sur les
populations très standardisées il trouve immédiatement le bon rôle. Il n'est
simplement pas suffisant.

### 3.2 Le mode approché, et pourquoi θ existe

Le mode approché relâche la contrainte d'égalité au moyen d'un seuil de
similarité **θ**, choisi par vous.

Il procède en trois temps :

1. **Génération de candidats par clôture.** Pour chaque droit *r*, on prend
   l'ensemble U(r) de ses détenteurs, puis on retient les droits partagés par au
   moins θ·|U(r)| d'entre eux. Cet ensemble de droits est un rôle candidat.
   À θ = 1, la clôture est exacte : tous les détenteurs de *r* possèdent tous
   les droits retenus. En dessous, on accepte qu'une minorité de membres ne les
   détienne pas tous.
2. **Extension des membres.** Une identité rejoint le rôle dès qu'elle détient
   au moins θ·|R| des droits du rôle, même si elle ne détient pas le droit
   d'amorce.
3. **Couverture gloutonne paresseuse.** Les candidats sont retenus dans l'ordre
   du gain marginal : le nombre d'habilitations *réelles* qu'ils couvrent et
   qu'aucun rôle déjà retenu ne couvrait. Deux exécutions sur les mêmes données
   donnent strictement le même résultat.

Des candidats **amorcés par signature** complètent la génération : ils
garantissent que le mode approché ne restitue jamais moins que le mode exact.
Un test le vérifie.

### 3.3 Le prix de θ : le sur-octroi

Baisser θ augmente la couverture. Ce gain a un coût, et Kovex le nomme :

> **Sur-octroi** — les couples (identité, droit) que le rôle accorderait à ses
> membres sans qu'ils existent aujourd'hui.

C'est un chiffre d'audit, pas un détail technique : accorder un rôle à 400
personnes dont 30 n'avaient pas trois de ses droits, c'est créer 90
habilitations nouvelles. Kovex le remonte par rôle (`fit_pct`,
`over_granted_pct`) et globalement, et l'interface l'affiche à côté de la
couverture. Annoncer le gain sans son coût serait trompeur.

À θ = 1, le sur-octroi est **nul par construction**, quel que soit l'état des
données. C'est vérifié par test à trois niveaux de bruit.

### 3.4 Comment choisir θ

Il n'existe pas de bonne valeur universelle, et ce n'est pas une opinion : c'est
un résultat mesuré. Sur des référentiels dont les rôles sont connus à l'avance
(voir [04 — Validation](04-validation.md)) :

- sans bruit, θ = 1 restitue **exactement** les rôles sous-jacents ;
- à 20 % d'habilitations manquantes, θ = 1 n'en retrouve plus que 4 sur 15,
  quand θ = 0,7 en retrouve 12.

Autrement dit, le bon θ dépend de la propreté de *votre* référentiel, que le
produit ne connaît pas. D'où l'**exploration du seuil** : Kovex exécute le
mining sur une série de seuils que vous délimitez et vous rend la courbe
couverture / sur-octroi / nombre de rôles.

L'exploration ne choisit pas pour vous. Elle fait deux choses :

- elle marque les points **non dominés** — aucun autre seuil ne couvre
  davantage en octroyant moins en trop. C'est un fait mathématique, pas un avis,
  et il élimine souvent des seuils qu'on aurait retenus par habitude : sur une
  mesure réelle, θ = 1,00 est dominé par θ = 0,95, qui couvre 1,5 point de plus
  sans octroyer un seul droit supplémentaire ;
- si — et seulement si — vous exprimez une contrainte (« je n'accepte pas plus
  de X % de sur-octroi »), elle désigne le seuil le plus couvrant qui la
  respecte. À couverture égale, le moins de rôles ; puis le seuil le plus strict.

Coût : chaque point de la courbe est un mining complet. Sur un référentiel de
18 000 identités et 244 000 habilitations, 7 seuils prennent 24 secondes.

### 3.5 Ce que valent les rôles pris ensemble

Un rôle peut être bon isolément et le modèle mauvais : deux cents rôles qui se
recouvrent tous expliquent les mêmes habilitations deux cents fois. Kovex mesure
donc le modèle, pas seulement ses pièces.

| Mesure | Définition | Comment la lire |
|---|---|---|
| **compression** | couples (identité, droit) accordés, rapportés au nombre de liens du modèle (identité→rôle plus rôle→droit) | à 3,0, un lien du modèle en accorde trois. **En dessous de 1,0, le modèle coûte plus de liens qu'il n'accorde d'habilitations** : il ne simplifie rien |
| **redondance** | part des couples couverts plusieurs fois | à 70 %, la plupart du travail est fait plusieurs fois. C'est le signal qu'une consolidation s'impose |
| **complexité structurelle (WSC)** | nombre de rôles augmenté du nombre de liens | sert à comparer deux modèles du même référentiel : plus bas, plus simple |
| **sous-affectation** | habilitations qu'aucun rôle n'explique | ce qui restera en attribution individuelle |

Chaque rôle porte en plus sa **redondance propre** : la part de ses
habilitations que des rôles mieux classés couvraient déjà. À 100 %, il n'apporte
rien.

Ces chiffres sont calculés sur les habilitations réelles, pas déduits des
compteurs du moteur — ce qui les rend justes y compris après consolidation.

### 3.6 Consolidation : retirer ce qui fait doublon

Deux rôles dont les droits se ressemblent au-delà d'un seuil que vous fixez sont
considérés comme le même rôle. **Un seul survit : le mieux classé**, celui que
la couverture gloutonne a jugé le plus utile. Les autres sont retirés, et le
survivant garde la trace de ce qu'il remplace.

Rien n'est fusionné. Un rôle conservé est exactement celui que le moteur a
produit, ce qui garantit que sa définition, ses membres et son sur-octroi restent
ceux qu'on a examinés.

**Une fusion avait été implémentée d'abord** — intersection des droits, union des
membres — puis mesurée contre une vérité terrain connue. Elle améliore la
compression et détruit les rôles : à seuil 0,8, le nombre de rôles retrouvés à
l'identique tombe de 12 sur 15 à 4, et le rappel de 0,97 à 0,88. L'absorption,
aux mêmes seuils, laisse rappel et rôles exacts **inchangés** tout en divisant la
complexité par deux. La fusion a été abandonnée sur mesure, pas sur principe.

Le choix du survivant a été mesuré de la même façon. Retenir le rôle portant le
plus de droits, ou le plus de membres, dégrade le rappel (0,87 et 0,90 contre
0,97) : c'est le classement du moteur qui porte l'information, pas la taille du
rôle.

Le seuil se choisit comme θ : **sur une courbe, pas à l'intuition.** Kovex
rejoue la consolidation sur une série de seuils que vous délimitez et rend, pour
chacun, les rôles conservés, les habilitations que le modèle n'accorde plus, la
compression, la redondance et la complexité. Le mining n'est exécuté qu'une
fois — un balayage coûte à peine plus qu'un mining seul.

Cette courbe se lit autrement que celle de θ. Elle est monotone : baisser le
seuil retire toujours des rôles et perd toujours des habilitations, donc aucun
point n'en domine un autre. Ce qui distingue les points, c'est le **rendement
marginal** — combien de rôles un cran de plus retire, par millier
d'habilitations sacrifiées. Sa décroissance montre où la simplification cesse de
payer.

### 3.7 Hiérarchie

Un rôle dont les droits sont **strictement inclus** dans ceux d'un autre en est
un sous-rôle. C'est ce qui renseigne `sub_roles`, que le mining laissait vide.

Seuls les liens directs sont conservés : si A ⊂ B ⊂ C, le lien A ⊂ C est omis,
sans quoi la hiérarchie serait illisible. Deux rôles portant exactement les mêmes
droits ne sont pas hiérarchisés — c'est un doublon, pas une inclusion, et cela
relève de la consolidation.

## 4. Le mining métier

Le mining métier part des **attributs des identités**, pas de la matrice. Vous
choisissez un ou plusieurs attributs (direction, fonction, site…) ; pour chaque
combinaison de valeurs, Kovex regarde quels droits sont détenus par une part
suffisante du groupe, et propose ce paquet comme rôle métier.

Quatre réglages, tous à votre main : les attributs croisés, la profondeur du
croisement, la couverture minimale d'un droit dans le groupe, et les planchers
d'effectif et de droits.

**Les attributs proposés ne sont pas une liste écrite dans le code.** Kovex
calcule la cardinalité réelle de chaque colonne — combien de valeurs distinctes
rapportées au nombre d'identités — et signale comme *recommandés* ceux qui
restent sous le seuil du workspace. Une colonne à une valeur par ligne
(identifiant technique) et une colonne constante sont écartées : elles ne
permettent aucun regroupement. Tout le reste vous est proposé, et c'est vous
qui tranchez.

## 5. La gouvernance : ce qui rend le mining utilisable deux fois

Un moteur de mining qui repropose à chaque exécution les rôles qu'on a déjà
refusés est inutilisable. La **Knowledge Base** du workspace mémorise les
décisions et les réapplique :

- **droits socles** — les droits détenus par presque tout le monde. Ils polluent
  toute recherche de rôle : s'ils restent dans la matrice, ils apparaissent dans
  chaque candidat. Ils sont détectés au seuil de fréquence que vous fixez, puis
  exclus automatiquement de tous les minings.
- **Rôles validés** — ils ne sont plus reproposés.
- **Rôles rejetés** — ils ne sont plus reproposés non plus. L'identité d'un rôle
  est le SHA-256 de ses droits triés : **renommer un rôle ne le fait pas
  réapparaître**, et le frontend applique exactement le même calcul.
- **Identités exclues** — sorties du périmètre d'analyse.
- **Historique des exécutions** — quels paramètres, quand, par qui, avec quel
  résultat.

## 6. Un rôle est une règle, pas une liste de membres

C'est un choix de conception, et il a une conséquence visible.

Stocker la liste des membres d'un rôle au moment de sa validation produit une
liste fausse dès le premier mouvement d'annuaire. Kovex stocke donc la **règle**
et recalcule les membres à la lecture :

- rôle **métier** : les identités dont les attributs RH satisfont la règle ;
- rôle **applicatif** : les identités détenant l'intégralité de ses droits.

Effet de bord utile : le lien identité → rôle est rétabli **rétroactivement**
pour des rôles validés avant que ce principe soit posé, sans migration de
données.

## 7. Le graphe des accès

Cinq colonnes successives, lues dans les deux sens :

    Identités → Rôles métier → Rôles applicatifs → Droits → Applications

Chaque colonne est une requête distincte, filtrée par la sélection et paginée :
rien n'est chargé d'avance. Une sélection, quelle que soit sa colonne, est
traduite en un périmètre — les identités et les droits qu'elle désigne — puis
projetée sur toutes les autres colonnes. Sélectionner un rôle métier montre ses
identités à gauche et ses applications à droite ; sélectionner un droit remonte
ses détenteurs et les rôles qui le portent.

Une vue en réseau avait été essayée d'abord. Sur 17 881 identités, la borne de
nœuds était épuisée par les seules identités : ni droit, ni rôle, ni application
n'apparaissait. Les colonnes règlent le problème en ne chargeant que ce qui est
demandé.

## 8. Ce que Kovex ne fait pas

Dire ce qu'un produit ne fait pas vaut mieux que le laisser découvrir.

- **Aucune dimension temporelle.** Le référentiel est un instantané. Aucune
  courbe d'activité, aucune tendance, aucun « depuis 30 jours » ne peut en être
  tiré, et le produit n'en affiche pas.
- **La hiérarchie déduite ne remonte pas dans la Knowledge Base.** Elle est
  calculée à chaque mining et affichée, mais un rôle validé ne conserve pas ses
  sous-rôles.
- **Aucune mesure de pertinence métier d'un rôle.** Le produit sait dire qu'un
  modèle est compact et peu redondant ; il ne sait pas dire qu'un rôle a un sens
  pour un responsable d'application.
- **Aucun accès réseau sortant.** Y compris pour les bibliothèques du frontend,
  servies localement.
