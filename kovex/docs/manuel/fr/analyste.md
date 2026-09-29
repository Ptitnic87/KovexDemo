# Manuel de l'analyste

Ce manuel s'adresse à la personne qui exploite Kovex : celle qui lance les
analyses, lit les rôles proposés, et décide de les valider ou de les rejeter.
Il ne suppose aucune connaissance des algorithmes.

## Ce que fait Kovex, en une phrase

Kovex lit qui possède quels droits, cherche les groupes de personnes qui
possèdent les mêmes droits, et vous propose de transformer ces groupes en
rôles. Un rôle remplace des dizaines d'attributions individuelles par une
seule décision.

## Le vocabulaire

**Identité.** Une personne, avec ses attributs : fonction, service, type de
contrat. Kovex ne présuppose aucun de ces attributs : ce sont les colonnes de
votre fichier, quelles qu'elles soient.

**Droit.** Une autorisation élémentaire dans une application : un groupe de
sécurité, un profil, une habilitation.

**Habilitation.** Le fait qu'une identité possède un droit. C'est la matière
première : sans elle, il n'y a rien à analyser.

**Rôle applicatif.** Un ensemble de droits qui vont ensemble techniquement.
Découvert par le mining.

**Rôle métier.** Un ensemble de rôles applicatifs et de droits, attribué sur
une règle portant sur les attributs d'identité — par exemple « tout infirmier
du service X ». C'est ce qui permet l'attribution automatique.

**Règle métier d'un rôle.** Ce que les porteurs d'un rôle ont en commun,
exprimé sur les attributs de votre référentiel — « service = Comptabilité *et*
statut = Cadre ». Kovex la cherche après coup, sur un rôle déjà trouvé : le
mining sait dire quels droits vont ensemble, pas pourquoi.

**Fiabilité de la règle.** Parmi les personnes que la règle désigne, la part
qui porte réellement le rôle. Ce qui manque pour atteindre 100 % est le
sur-octroi qu'on accepterait en appliquant la règle telle quelle.

**Pouvoir explicatif.** Combien de fois la règle désigne mieux les porteurs
qu'un tirage au hasard. À 1, elle n'apprend rien — et c'est un piège fréquent :
sur un grand référentiel, une régularité minuscule devient statistiquement
certaine sans avoir la moindre valeur. « 51 % des porteurs ont cette mention,
contre 50 % dans la population » est un fait incontestable et une règle inutile.

**Droit socle. Un droit que presque tout le monde possède : accès
messagerie, accès réseau. Il n'apporte aucune information pour distinguer un
métier d'un autre, et sature les analyses si on l'y laisse.

## Le parcours normal

### 1. Vérifier la qualité des données avant tout

L'onglet **Qualité des données** n'est pas une formalité. Un mining sur des
données incohérentes produit des rôles incohérents, et rien dans le résultat
ne le signalera.

Regardez en priorité :

- **Droits orphelins** et **utilisateurs orphelins** : des habilitations qui
  pointent vers un droit ou une personne absents du référentiel. Elles ne
  participent à aucune analyse.
- **Habilitations brisées** : le nombre de *lignes* inexploitables.
- **Droits non attribués** : candidats au décommissionnement, sans effet sur le
  mining mais utiles à la gouvernance.
- **Doublons de référentiel** : un identifiant présent deux fois fausse tous
  les comptages.

Un contrôle affiché « — » n'est pas à zéro : il n'a pas pu être calculé, faute
d'une colonne associée dans la configuration. Ne le lisez pas comme un
« aucune anomalie ».

Le bouton **Afficher les détails** de chaque anomalie ouvre la liste complète
des identifiants concernés, filtrable et exportable en CSV. C'est cette liste
qu'il faut transmettre au responsable du référentiel.

### 2. Détecter les droits socles

Avant le mining métier, lancez la détection des droits socles. Un droit
possédé par 95 % des identités n'aide pas à distinguer un métier : le laisser
dans l'analyse produit des rôles énormes qui se ressemblent tous.

Le seuil est à vous. Plus il est bas, plus vous retirez de droits, plus les
rôles restants sont différenciants — mais plus vous risquez de retirer un
droit qui caractérisait réellement une population large.

### 3. Lancer le mining applicatif

Deux modes.

**Exact** : regroupe les identités qui possèdent *exactement* le même ensemble
de droits. Sans paramètre à régler, sans arbitraire. Résultat : peu de rôles,
très purs, et une couverture faible — la réalité est rarement aussi nette.

**Approché** : regroupe les identités dont les ensembles de droits sont
*similaires* à un seuil θ près. Couvre beaucoup plus de monde, au prix
d'attributions en trop.

Deux paramètres cadrent le résultat :

- **Minimum d'utilisateurs** : en dessous, un groupe n'est pas un rôle, c'est
  une coïncidence. Trois est un plancher raisonnable.
- **Minimum de droits** : un « rôle » à un seul droit n'apporte rien qu'une
  attribution directe n'apporte déjà.

### 4. Choisir θ plutôt que le subir

C'est le point où la plupart des outils vous laissent seul avec une valeur par
défaut. Kovex vous donne la courbe.

L'écran d'**aide au choix de θ** balaie une série de seuils et trace, pour
chacun, deux quantités qui s'opposent :

- **la couverture** : la part des habilitations réelles expliquées par les
  rôles ;
- **le sur-octroi** : les droits que les rôles donneraient à des gens qui ne
  les ont pas aujourd'hui.

θ = 1 n'octroie aucun droit en trop. Baisser θ augmente la couverture *et* le
sur-octroi. Il n'y a pas de bonne valeur dans l'absolu : il y a la valeur que
votre politique de sécurité tolère. Lisez la courbe, fixez d'abord le
sur-octroi maximal acceptable, puis prenez le seuil qui couvre le plus sans
dépasser cette limite — en général le θ le plus bas qui la respecte. Saisissez
la limite à l'écran : c'est ce seuil-là qu'il désigne.

### 5. Lire un rôle proposé

Pour chaque rôle, quatre chiffres comptent :

- **Nombre d'utilisateurs** : la population que le rôle couvrirait.
- **Nombre de droits** : la taille du rôle. Un rôle de 200 droits n'est pas un
  rôle, c'est un service entier.
- **Couverture** : la part des habilitations de ces utilisateurs que le rôle
  explique.
- **Sur-octroi** : ce que le rôle donnerait en trop.

Un rôle avec un sur-octroi non nul n'est pas disqualifié pour autant. La
question est : ces droits en trop sont-ils anodins, ou sensibles ? Un rôle qui
donne en trop un accès en lecture à un annuaire n'est pas un rôle qui donne en
trop un accès au dossier patient.

### 5 bis. Demander l'explication métier d'un rôle

L'onglet **Explication** de la fenêtre de validation répond à la question que
posera le responsable d'application : *qu'ont ces gens en commun ?*

Choisissez les attributs à croiser — ce sont les colonnes de vos fichiers — et
fixez vos exigences. Elles sont les vôtres, pas celles du produit :

| Réglage | Ce qu'il décide |
|---|---|
| Fiabilité attendue | En dessous, la règle est signalée comme non défendable. |
| Porteurs à expliquer au minimum | Plus vous exigez, plus la règle est large, et moins elle est fiable. |
| Pouvoir explicatif minimal | Écarte les attributs qui n'apprennent rien. |
| Risque de hasard accepté | Probabilité maximale que la concordance soit fortuite. |
| Nombre de critères combinés | Une règle longue est plus précise et moins lisible. |

Kovex rend **la règle la plus fiable qui explique encore la part de porteurs
que vous exigez**. Il ne choisit pas le compromis à votre place : ajouter un
critère fait monter la fiabilité et baisser le nombre de porteurs expliqués.

Le diagnostic **ce qui plaide pour, ce qui plaide contre** liste les constats
un par un, du plus bloquant au plus rassurant, chacun avec son chiffre. Ce
n'est volontairement pas une note globale : un pourcentage unique ne se
conteste pas, alors qu'un comité doit pouvoir s'opposer point par point.

Deux constats méritent une attention particulière :

- **Les exceptions** sont les porteurs que la règle ne décrit pas. Ce sont eux
  qu'un comité examine un par un.
- **Le sur-octroi** compte les personnes que la règle désignerait sans qu'elles
  portent le rôle aujourd'hui. C'est le coût de sécurité de la simplification.

Un rôle sans règle n'est pas un mauvais rôle : c'est un rôle que vos attributs
ne décrivent pas. Cela arrive quand le référentiel d'identités ne porte pas la
dimension qui structure réellement ces habilitations — un projet, une
astreinte, une ancienneté.

### 5 ter. Le nom proposé par un modèle

Si votre administrateur a activé l'annotateur sémantique, l'onglet Explication
propose un nom et une description. **Rien ne s'applique tant que vous ne
reprenez pas la proposition** : elle remplit les champs seulement quand vous le
demandez, et vous restez responsable de ce que vous validez.

Avant tout envoi, l'écran affiche le modèle interrogé, ce qui va lui être
transmis, et **si ces données quittent le serveur**. Par défaut le modèle ne
voit que le nombre de droits et de porteurs : aucun libellé, aucune valeur
d'attribut, aucun nom déjà retenu. Ce que vous voyez annoncé est exactement ce
qui part.

Si votre administrateur autorise les noms déjà validés, le modèle reçoit
quelques rôles de votre catalogue comme exemples et suit votre convention de
nommage. Ils sont choisis parmi les rôles proches de celui-ci — un calcul qui
reste sur le serveur.

Sans annotateur configuré, l'emplacement le dit et vous nommez le rôle à la
main — c'est le fonctionnement normal, pas une panne.

### 6. Valider ou rejeter

**Valider** place le rôle dans la base de connaissances. Il devient visible
dans la cartographie et sert de base aux analyses suivantes.

**Rejeter** l'écarte durablement. Le rejet est mémorisé par l'empreinte des
droits du rôle, pas par son nom : le même rôle ne vous sera pas reproposé au
prochain mining sous un autre libellé.

Motivez vos rejets. Le motif est consigné dans la piste d'audit et c'est lui
qui, dans six mois, expliquera pourquoi ce rôle n'existe pas.

### 7. Composer un rôle métier

Le compositeur assemble des rôles applicatifs validés, y ajoute des droits
unitaires et des exceptions, et produit un rôle métier attribuable sur une
règle RH.

La règle est une égalité stricte sur des attributs d'identité. Une identité
dont l'attribut est vide ne correspond à rien — c'est délibéré : une valeur
manquante ne doit jamais être interprétée comme « correspond à tout ».

### 8. Revoir le catalogue plus tard

Un rôle est une règle, et une règle vieillit avec les données. Six mois après
la validation, la population que la règle désigne a changé, et les droits que
ses membres détiennent aussi.

Le catalogue affiche donc, au-dessus des rôles, une **revue du modèle** : la
comparaison entre les chiffres que vous aviez sous les yeux au moment de
décider et ceux d'aujourd'hui. Une population qui a fondu, une population qui
a grossi, un rôle passé sous l'effectif minimal, un sur-octroi apparu, deux
rôles qui font désormais double emploi. Chaque constat porte ses deux chiffres
— l'ancien et le nouveau — parce qu'un écart sans son point de départ ne se
décide pas.

Un rôle composé à la main n'a pas de chiffres enregistrés à sa création : sa
carte affiche ses mesures du jour et dit qu'il n'y a pas d'écart à mesurer.

Cette revue **ne corrige rien**. Elle constate. Un rôle validé est une décision
de gouvernance, et il a peut-être déjà été provisionné dans votre outil de
gestion des identités : reprendre cette décision vous appartient.

Le seuil au-delà duquel un écart devient un constat se règle dans la
configuration du workspace : un référentiel de trois cents identités et un de
trois cent mille ne bougent pas à la même échelle.

### 9. Appliquer une proposition, et ce que l'export en dit

Un constat peut porter une **proposition** : retirer du rôle des droits que ses
membres ne détiennent pas, y ajouter des droits qu'ils détiennent déjà tous,
fusionner deux rôles qui font double emploi, retirer un rôle passé sous
l'effectif minimal. Chaque proposition dit ce que le chiffre concerné
deviendrait — décider sans cela, c'est décider à l'aveugle.

Deux d'entre elles s'appliquent depuis l'écran, parce qu'elles ne touchent
qu'aux droits d'un rôle. Les deux autres font disparaître un rôle qui a
peut-être déjà été provisionné dans votre outil de gestion des identités :
elles sont rendues et expliquées, jamais appliquées d'ici.

Restreindre un rôle a une contrepartie, et l'écran la dit : un rôle peut
légitimement accorder ce que ses membres n'ont pas encore — c'est même le
propre d'un modèle qui harmonise. Le seuil au-delà duquel Kovex cesse de lire
un écart comme une harmonisation se règle dans la configuration du workspace.

**Un rôle appliqué garde son identifiant et gagne une version.** La version
précédente est conservée avec sa date, son auteur et le constat qui l'a
motivée, et la piste d'audit porte les mêmes éléments : « pourquoi ce rôle
a-t-il changé le 3 mars » se répond sans rouvrir les données.

C'est aussi ce que l'export vous rend : chaque rôle y porte sa version et ce
qu'il est devenu depuis le dernier document produit — nouveau, modifié,
inchangé. Sans cette mention, l'intégrateur reçoit un rôle modifié qu'il croit
neuf, et il en crée un doublon. Un aperçu ne déplace pas cette borne ; seul un
document réellement produit le fait.

### 10. Rouvrir un rôle du catalogue

Le catalogue n'affichait qu'un nom et deux compteurs. Le bouton **Voir le
détail** ouvre ce que le rôle contient réellement : ses porteurs, ses droits, et
pour chacun la part de ses membres qui le détient déjà.

C'est cette dernière colonne qui compte. « Ce rôle accorde 340 attributions en
trop » ne se corrige pas ; « ce droit-ci, quatre membres sur cent le
détiennent » se décide.

La même fenêtre porte le nom et la description — les modifier **versionne** le
rôle, pour la même raison que la modification des droits — et un bouton qui
demande une proposition de nom à un modèle, quand vous en avez configuré un. La
proposition remplit le champ ; elle ne s'enregistre pas toute seule.

**Sortir un rôle du catalogue** se fait aussi depuis cette fenêtre. Le motif est
obligatoire. Le rôle n'est pas effacé : il reste consultable avec votre motif,
votre nom et sa date, et le candidat dont il venait redevient à décider —
autrement dit, il vous sera reproposé au prochain mining.

## Ce qui est tracé

Toute décision de gouvernance est consignée dans la **piste d'audit** :
validation, rejet, lancement de mining avec ses paramètres, export, changement
de configuration. La piste est chaînée par empreinte : une modification a
posteriori est détectable.

Cela veut dire deux choses pour vous. Vos décisions sont défendables — vous
pouvez montrer quand et sur quels paramètres un rôle a été validé. Et elles
sont attribuables — la piste porte votre nom.

## Erreurs fréquentes

**Lancer le mining avant d'avoir regardé la qualité des données.** Le résultat
sera propre en apparence et faux en profondeur.

**Chercher le θ « optimal ».** Il n'existe pas. Il existe un arbitrage, et il
vous appartient.

**Valider un rôle sans regarder son sur-octroi.** C'est ainsi qu'un projet de
role mining finit par élargir les accès au lieu de les réduire.

**Ignorer les droits socles.** Ils font ressembler tous les rôles les
uns aux autres et gonflent artificiellement la couverture.
