# Fichier : src/core/knowledge/document_json.py
"""Lire un document JSON sans le relire quand il n'a pas changé.

La base de connaissance d'un workspace réel pesait 9,56 Mo — les candidats du
dernier mining en faisaient l'essentiel. Soixante routes la reconstruisent à
chaque appel, et une simple validation de rôle enchaînait deux cycles complets
lecture-écriture, suivis d'un rafraîchissement d'écran qui en relisait trois
fois plus. Le clic coûtait près d'une seconde sur une machine rapide, et
plusieurs sur un poste d'entreprise où l'antivirus inspecte chaque écriture.

Rien ne saturait : un seul cœur occupé à analyser du JSON, et du disque. C'est
exactement ce qui rend ce défaut invisible aux deux graphes qu'on regarde.

**L'empreinte du fichier décide.** Date de modification et taille : deux
appels système, quelques microsecondes. Tant qu'elles ne bougent pas, le
document en mémoire fait foi. Une modification extérieure — quelqu'un qui
édite le fichier à la main — change l'empreinte et le cache tombe, ce qui était
la condition pour que ce cache soit acceptable dans un produit dont les
utilisateurs ouvrent parfois le fichier.
"""

from __future__ import annotations

import copy
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

#: Documents déjà lus : chemin → (empreinte, contenu).
_MEMOIRE: Dict[str, Tuple[str, Any]] = {}


def empreinte(chemin: Path) -> str:
    """Ce qui distingue deux états d'un fichier, sans le lire.

    La taille seule ne suffit pas — une correction de même longueur passerait
    inaperçue. La date seule non plus : sa résolution est celle du système de
    fichiers, et deux écritures rapprochées peuvent la partager. Les deux
    ensemble tiennent.
    """
    try:
        etat = os.stat(chemin)
    except OSError:
        return ""
    return f"{etat.st_mtime_ns}:{etat.st_size}"


def oublier(chemin: Optional[Path] = None) -> None:
    """Vide le souvenir d'un document, ou de tous."""
    if chemin is None:
        _MEMOIRE.clear()
    else:
        _MEMOIRE.pop(str(Path(chemin).resolve()), None)


def lire(chemin: Path, defaut: Any = None, copie: bool = True) -> Any:
    """Le contenu du document, analysé une fois tant qu'il ne change pas.

    `copie` protège le souvenir : l'appelant qui modifie ce qu'il reçoit
    corromprait sinon la lecture suivante. Elle se désactive pour les documents
    volumineux dont l'appelant ne fait que lire — la copie coûterait alors
    précisément ce qu'on cherche à éviter.
    """
    cle = str(Path(chemin).resolve())
    signature = empreinte(chemin)
    if not signature:
        return copy.deepcopy(defaut) if copie else defaut

    connu = _MEMOIRE.get(cle)
    if connu is None or connu[0] != signature:
        try:
            contenu = json.loads(Path(chemin).read_text(encoding="utf-8"))
        except (OSError, ValueError) as erreur:
            logger.error("Document %s illisible : %s", chemin, erreur)
            return copy.deepcopy(defaut) if copie else defaut
        _MEMOIRE[cle] = (signature, contenu)
        connu = _MEMOIRE[cle]

    return copy.deepcopy(connu[1]) if copie else connu[1]


def ecrire(chemin: Path, contenu: Any, indentation: Optional[int] = 4) -> None:
    """Écrit le document, et oublie ce qu'on croyait savoir de lui.

    L'écriture est atomique — fichier temporaire, remplacement — parce que le
    contenu est une décision de gouvernance et qu'une écriture interrompue ne
    doit pas laisser un document tronqué.

    `indentation` se règle : un document qu'on ouvre à la main la mérite, un
    document que seule la machine relit la paie en octets. Sur les candidats
    d'un mining, l'indentation représentait plus de la moitié du fichier.
    """
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    temporaire = chemin.with_suffix(chemin.suffix + ".tmp")
    texte = json.dumps(contenu, indent=indentation, ensure_ascii=False)
    temporaire.write_text(texte, encoding="utf-8")
    # Un système de fichiers peut accepter une écriture sans la conserver — un
    # montage réseau qui décroche. C'est précisément le cas où un document à
    # moitié écrit passerait pour une sauvegarde réussie.
    if not temporaire.exists():
        raise IOError(f"écriture non conservée : {temporaire}")
    temporaire.replace(chemin)
    # Le souvenir est effacé plutôt que remplacé par ce qu'on vient d'écrire :
    # l'appelant garde une référence sur cette structure et continuera de la
    # modifier. Un cache qui pointerait dessus rendrait, à la lecture suivante,
    # un état intermédiaire que personne n'a jamais écrit sur le disque.
    oublier(chemin)
