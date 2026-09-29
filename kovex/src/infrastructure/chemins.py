# Fichier : src/infrastructure/chemins.py
"""Ancrage des chemins relatifs du produit.

Les chemins écrits dans les documents de configuration — sources de données,
catalogues de traduction, manuel — sont relatifs. Ils étaient résolus contre le
**répertoire de travail du processus**, c'est-à-dire contre l'endroit d'où la
commande de lancement a été tapée. Lancé depuis la racine du projet, tout
fonctionnait ; lancé d'ailleurs — un service Windows, une tâche planifiée, un
raccourci — le produit démarrait sans erreur et ne trouvait plus rien : ni
données, ni traductions, ni documentation. Le défaut a déjà été constaté sur
les catalogues i18n, qu'un serveur lancé hors de la racine ne chargeait pas du
tout.

Ces chemins sont donc ancrés sur l'emplacement du code, seule référence stable
quel que soit le mode de lancement.

L'ancrage sert aussi de garantie de cohérence entre les deux barrières qui
contrôlent le périmètre de lecture : le point d'entrée qui refuse d'écrire un
chemin et le chargeur qui refuse de le lire doivent résoudre un chemin relatif
de la même manière, sinon l'un accepte ce que l'autre rejette.
"""

from pathlib import Path

#: Racine du projet : le dossier qui contient `src/`, `config/` et `docs/`.
RACINE_PROJET: Path = Path(__file__).resolve().parents[2]


def depuis_la_racine(chemin) -> Path:
    """Résout un chemin relatif contre la racine du projet.

    Un chemin absolu est rendu tel quel : il désigne déjà un emplacement
    précis, que l'appelant reste libre de contrôler par ailleurs.
    """
    candidat = Path(chemin)
    return candidat if candidat.is_absolute() else RACINE_PROJET / candidat
