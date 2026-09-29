# Méthode de role mining

Ce document explique ce que Kovex calcule, pourquoi, et comment la justesse du
résultat est vérifiée. Il s'adresse à qui doit défendre la méthode devant un
auditeur ou un client exigeant.

## Le problème

On dispose d'une matrice booléenne : en lignes les identités, en colonnes les
droits, une case vraie quand la personne possède le droit. On cherche un
ensemble de rôles — des sous-ensembles de droits — et une affectation des
personnes à ces rôles, tels que le résultat reproduise la matrice.

Le problème sous sa forme exacte est celui de la **décomposition booléenne de
matrice**, connu pour être NP-difficile. Aucun outil ne le résout exactement à
l'échelle de 20 000 identités et 8 000 droits ; tous emploient des heuristiques.
La question honnête n'est donc pas « est-ce optimal » mais « qu'est-ce que
l'heuristique garantit, et que coûte-t-elle ».

## Les trois critères qui s'opposent

Toute solution se juge sur trois axes, et améliorer l'un dégrade les autres.

**Couverture.** La part des habilitations réelles expliquées par les rôles. Une
couverture de 100 % avec un rôle par personne est triviale et sans intérêt.

**Sur-octroi.** Les droits que les rôles attribueraient à des personnes qui ne
les possèdent pas. C'est le coût de sécurité de la simplification. Un
sur-octroi élevé transforme un projet de rationalisation en élargissement
d'accès.

**Complexité structurelle.** Le nombre de rôles, leur taille, le nombre
d'affectations. Une solution que personne ne peut relire n'a aucune valeur
opérationnelle, quelle que soit sa couverture.

Kovex rend ces trois grandeurs pour chaque configuration. Un outil qui n'en
affiche qu'une vous cache l'arbitrage.

## Les algorithmes

### Regroupement exact

Les identités possédant exactement le même ensemble de droits forment un
groupe. Chaque groupe donne un rôle candidat.

Aucun paramètre, aucun arbitraire, sur-octroi nul par construction. En
contrepartie, la couverture est faible : sur des données réelles, très peu de
personnes ont un portefeuille rigoureusement identique.

C'est la référence : tout rôle produit ainsi est incontestable.

### Regroupement approché

Deux identités sont rapprochées si leurs ensembles de droits sont similaires
à un seuil θ près. Le rôle retenu est l'intersection ou une fermeture des
droits du groupe, selon la variante.

θ est **le** paramètre du produit. Il n'a pas de bonne valeur universelle : il
encode la tolérance au sur-octroi de votre politique de sécurité. C'est
pourquoi Kovex ne le fixe pas et fournit à la place la courbe complète.

### Couverture par ensembles

Une fois les candidats produits, il faut en choisir un sous-ensemble qui
couvre le plus d'habilitations avec le moins de rôles. C'est un problème de
**couverture d'ensembles**, également NP-difficile.

Kovex emploie une heuristique gloutonne paresseuse : à chaque étape, le rôle
qui apporte le plus d'habilitations nouvelles. Cette heuristique a une
garantie théorique connue — le résultat est au pire un facteur logarithmique
au-dessus de l'optimum. Ce n'est pas l'optimum, c'est une borne, et c'est ce
qu'on peut affirmer honnêtement.

La variante paresseuse exploite la sous-modularité du gain pour éviter de
réévaluer tous les candidats à chaque étape. Le résultat est identique à celui
du glouton naïf ; seul le temps de calcul change.

### Consolidation

Deux rôles très proches se fusionnent ou l'un absorbe l'autre. Cela réduit la
complexité structurelle sans toucher à la couverture, ou en la touchant peu.

Ce point a été tranché par la mesure, pas par principe. Trois stratégies ont
été comparées sur un référentiel à vérité connue :

- **fusion par intersection** : effondre la justesse — 4 rôles exacts
  retrouvés sur 15, contre 12 sans consolidation. Écartée.
- **absorption** : conserve le rappel à 0,973, inchangé, en divisant par deux
  la complexité structurelle. Retenue.
- **choix du représentant** : prendre le mieux classé conserve le rappel ;
  prendre un autre le fait tomber à 0,797 ou 0,830. Le représentant est donc
  toujours le mieux classé.

Le seuil de consolidation dispose lui aussi de son écran d'exploration.
L'efficacité marginale — le gain de complexité par point de rappel perdu —
présente un maximum net, ce qui donne un point de départ défendable.

## Droits socles

Un droit possédé par la quasi-totalité des identités ne porte aucune
information discriminante. Le laisser dans la matrice a deux effets : il gonfle
artificiellement la couverture, et il rend tous les rôles semblables.

Kovex les détecte sur un seuil de prévalence réglable et permet de les retirer
avant le mining métier. Le seuil est laissé à l'utilisateur : selon
l'organisation, « presque tout le monde » commence à 80 % ou à 98 %.

## Validation de la justesse

Un outil de role mining qui ne se vérifie que sur des données clientes ne se
vérifie pas : sur des données réelles, personne ne connaît la bonne réponse.

Kovex embarque un générateur de **référentiels à vérité terrain**. Il construit
une population dont les rôles sont connus par construction, y ajoute du bruit
— attributions surnuméraires, attributions manquantes — puis fait tourner le
mining sur le résultat.

Les rôles produits sont appariés aux rôles plantés par similarité de Jaccard,
ce qui donne une précision et un rappel mesurés, pas estimés.

Un banc en ligne de commande rejoue cette validation, en mode synthétique ou
sur des matrices publiques lues localement. Il tourne hors ligne, sur un
serveur isolé, sans donnée client.

C'est ce dispositif qui a permis de trancher les choix de consolidation
ci-dessus par la mesure. C'est aussi ce qui permet, avant chaque livraison, de
constater qu'une modification n'a pas dégradé la justesse.

## Ce que Kovex ne fait pas

Par honnêteté, et parce qu'un outil qui prétend tout faire n'est crédible sur
rien :

- il ne garantit pas l'optimalité — aucun outil ne le peut à cette échelle ;
- il ne nomme pas les rôles de lui-même : un nom n'est proposé que si un
  modèle de langage est branché et son usage ouvert par l'administrateur, et
  c'est l'analyste qui le retient ou l'écarte ;
- il ne détecte pas qu'une valeur du référentiel est un remplissage
  (« information manquante » traité comme une application réelle) ;
- il ne remplace pas une revue humaine. Il la rend praticable.
