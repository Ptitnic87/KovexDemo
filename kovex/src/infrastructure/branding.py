"""Identité du produit, en un seul endroit.

Le nom du produit était réécrit à la main dans le titre de l'API, la bannière
de démarrage, l'en-tête des exports, le gabarit HTML et cinq entrées de
catalogue. Un changement de nom obligeait à les retrouver toutes, et il en
restait toujours.

Le nom n'est pas une chaîne traduisible : il est identique dans toutes les
langues. Il est donc défini ici, côté serveur, et exposé au client par
l'API — plutôt que dupliqué dans chaque catalogue, où trois valeurs pourraient
diverger.
"""

#: Nom commercial du produit, affiché partout où l'utilisateur le voit.
NOM_PRODUIT = "Kovex"

#: Sous-titre : ce que fait le produit. Traduisible, lui — d'où la clé.
CLE_BASELINE = "app.baseline"

#: Préfixe des fichiers produits par les exports.
PREFIXE_FICHIERS = "kovex"

#: Version du produit.
#:
#: Elle était écrite trois fois, et les trois ne disaient pas la même chose :
#: « 2.1.0 » deux fois dans l'API, « 2.1.0 » dans la barre latérale, et
#: « 4.4.0 » une trentaine de fois dans le gabarit — où elle sert de numéro de
#: cache pour les feuilles de style et les scripts. Cette dernière n'avait
#: jamais bougé : une mise à jour du produit laissait donc chaque poste sur
#: l'ancienne interface jusqu'à ce que son utilisateur vide son cache, et
#: personne ne pouvait le savoir.
VERSION_PRODUIT = "2.1.0"
