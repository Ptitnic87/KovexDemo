"""Les clés d'API, et l'endroit où elles n'ont pas le droit d'aller.

Une clé de fournisseur n'est pas un réglage : c'est un secret. Elle ne va donc
ni dans le `config.json` du workspace — qui est exporté, relu, comparé — ni
dans le dépôt, ni dans une réponse de l'API, ni dans le journal.

Deux mondes, et la différence est assumée plutôt que subie.

**Sur un poste**, le serveur tient un fichier d'instance hors dépôt. La clé
survit au redémarrage, comme n'importe quel secret de service.

**Dans la page**, il n'y a pas de serveur : le backend est l'onglet. Rien n'y
est écrit, jamais — la clé vit en mémoire et meurt avec l'onglet. Ce n'est pas
un effet de bord du montage des dossiers durables, c'est un refus explicite :
si un jour la configuration devenait durable dans le navigateur, une clé
d'entreprise ne se mettrait pas à y dormir en silence.

Le porte-clés ne rend jamais une clé à l'écran. Il dit seulement lesquelles
sont posées, ce qui suffit à afficher un état et ne suffit à rien d'autre.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import sys
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional

logger = logging.getLogger(__name__)

#: Fichier d'instance, hors dépôt. Le nom dit ce qu'il contient : personne ne
#: doit avoir à l'ouvrir pour le deviner.
NOM_DU_FICHIER = "cles_annotateur.json"


def dans_un_navigateur() -> bool:
    """Le backend tourne-t-il dans la page plutôt que sur un poste ?

    Pyodide compile CPython vers WebAssembly : `sys.platform` y vaut
    `emscripten`. C'est la seule marque qui ne dépende d'aucun réglage.
    """
    return sys.platform == "emscripten"


class PorteCles:
    """Les clés posées, par identifiant de préréglage."""

    def __init__(self, chemin: Optional[Path] = None,
                 persistant: Optional[bool] = None) -> None:
        self.chemin = Path(chemin) if chemin else None
        #: Un porte-clés non persistant ne relit ni n'écrit rien.
        self.persistant = (not dans_un_navigateur()) if persistant is None \
            else bool(persistant)
        self._cles: Dict[str, str] = {}
        self._relire()

    # -- lecture ----------------------------------------------------------

    def _relire(self) -> None:
        if not (self.persistant and self.chemin and self.chemin.is_file()):
            return
        try:
            brut = json.loads(self.chemin.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as erreur:
            # Un porte-clés illisible ne fait pas échouer le démarrage : les
            # appels au modèle seront refusés faute de clé, ce qui se voit à
            # l'écran, là où un serveur qui ne démarre pas ne se voit nulle part.
            logger.error("Porte-clés illisible (%s) : aucune clé n'est chargée.",
                         erreur)
            return
        if isinstance(brut, Mapping):
            self._cles = {str(nom): str(valeur) for nom, valeur in brut.items()
                          if str(valeur).strip()}

    def __contains__(self, prereglage: object) -> bool:
        return str(prereglage) in self._cles

    def get(self, prereglage: str, defaut: str = "") -> str:
        """La clé d'un préréglage. Réservé à l'appel sortant, jamais à l'écran."""
        return self._cles.get(str(prereglage), defaut)

    def poses(self) -> Iterable[str]:
        """Les préréglages qui ont une clé. C'est tout ce que l'écran peut savoir."""
        return sorted(self._cles)

    # -- écriture ---------------------------------------------------------

    def poser(self, prereglage: str, cle: str) -> None:
        """Pose ou remplace une clé. Une valeur vide retire la clé."""
        identifiant = str(prereglage).strip()
        if not identifiant:
            raise ValueError("un préréglage sans identifiant ne porte pas de clé")
        valeur = str(cle).strip()
        if valeur:
            self._cles[identifiant] = valeur
        else:
            self._cles.pop(identifiant, None)
        self._ecrire()

    def retirer(self, prereglage: str) -> None:
        self.poser(prereglage, "")

    def _ecrire(self) -> None:
        if not (self.persistant and self.chemin):
            return
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        # Écrit en place : remplacer le fichier par un autre perdrait ses
        # droits, et un secret lisible par tout le monde n'est plus un secret.
        with open(self.chemin, "w", encoding="utf-8") as flux:
            json.dump(self._cles, flux, indent=2, ensure_ascii=False,
                      sort_keys=True)
        try:
            os.chmod(self.chemin, stat.S_IRUSR | stat.S_IWUSR)
        except OSError as erreur:
            # Windows ne connaît pas ces bits ; l'écriture, elle, a eu lieu.
            logger.debug("Droits du porte-clés non restreints (%s).", erreur)


#: Le porte-clés de l'instance. Un seul par processus : dans la page, ce
#: processus est l'onglet, et sa mémoire est exactement la durée de la session.
_porte_cles: Optional[PorteCles] = None


def chemin_par_defaut() -> Path:
    """Le fichier d'instance, à côté de la configuration livrée."""
    from src.infrastructure.chemins import RACINE_PROJET

    return RACINE_PROJET / "config" / NOM_DU_FICHIER


def get_porte_cles(chemin: Optional[Path] = None) -> PorteCles:
    """Le porte-clés de l'instance, construit au premier appel."""
    global _porte_cles
    if chemin is not None:
        _porte_cles = PorteCles(chemin)
    elif _porte_cles is None:
        _porte_cles = PorteCles(chemin_par_defaut())
    return _porte_cles


def reinitialiser_le_porte_cles() -> None:
    """Oublie le porte-clés de l'instance (déconnexion, tests)."""
    global _porte_cles
    _porte_cles = None
