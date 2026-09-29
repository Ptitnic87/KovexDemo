"""Documentation embarquée, servie depuis `docs/manuel/`.

Le contenu vit dans des fichiers Markdown plutôt que dans les catalogues de
traduction. Ce n'est pas une entorse à la règle « aucun texte en dur » : un
catalogue sert à traduire les libellés d'interface, pas à héberger plusieurs
milliers de mots de prose qu'aucun traducteur ne relira ligne à ligne dans un
fichier JSON. Les titres et descriptions des sections, eux, restent des clés.

Le point d'entrée ne construit jamais un chemin à partir de ce que l'appelant
envoie : la section demandée doit figurer dans une liste fermée. Sans cela,
`../../.env` serait un nom de section valide.
"""

import logging
from pathlib import Path
from typing import Dict, List

from fastapi import APIRouter, HTTPException, Query, status
from src.infrastructure.chemins import depuis_la_racine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documentation", tags=["Documentation"])

RACINE_MANUEL = depuis_la_racine(Path("docs") / "manuel")

#: Langue de référence : celle dans laquelle la documentation est écrite en
#: premier. Une section non traduite est servie dans cette langue, et le client
#: le signale — plutôt que d'afficher une page vide ou une traduction inventée.
LANGUE_DE_REFERENCE = "fr"

#: Liste fermée des sections. Elle sert de contrôle d'entrée autant que de
#: sommaire : aucun autre nom ne peut atteindre le disque.
SECTIONS: List[Dict[str, str]] = [
    {
        "id": "analyste",
        "titre_key": "doc.section.analyste.title",
        "resume_key": "doc.section.analyste.summary",
        "icone": "fa-user-check",
    },
    {
        "id": "administrateur",
        "titre_key": "doc.section.administrateur.title",
        "resume_key": "doc.section.administrateur.summary",
        "icone": "fa-server",
    },
    {
        "id": "methode",
        "titre_key": "doc.section.methode.title",
        "resume_key": "doc.section.methode.summary",
        "icone": "fa-flask",
    },
    {
        "id": "developpeur",
        "titre_key": "doc.section.developpeur.title",
        "resume_key": "doc.section.developpeur.summary",
        "icone": "fa-code",
    },
]

_IDENTIFIANTS = {section["id"] for section in SECTIONS}


def _chemin(section: str, langue: str) -> Path:
    """Chemin d'une section, sans jamais interpoler l'entrée de l'appelant.

    `section` a déjà été vérifié contre la liste fermée ; `langue` est réduite
    aux caractères d'un code de langue. Les deux précautions sont redondantes,
    et c'est voulu.
    """
    langue_sure = "".join(c for c in langue if c.isalpha())[:5] or LANGUE_DE_REFERENCE
    return RACINE_MANUEL / langue_sure / f"{section}.md"


@router.get("/sections")
async def lister_sections(langue: str = Query(LANGUE_DE_REFERENCE)):
    """Sommaire : les parcours proposés, et lesquels existent dans la langue."""
    return {
        "langue_de_reference": LANGUE_DE_REFERENCE,
        "sections": [
            {**section, "traduite": _chemin(section["id"], langue).exists()}
            for section in SECTIONS
        ],
    }


@router.get("/{section}")
async def lire_section(section: str, langue: str = Query(LANGUE_DE_REFERENCE)):
    """Contenu Markdown d'une section.

    Rend aussi la langue effectivement servie : le client doit pouvoir dire
    « cette section n'est pas encore traduite » plutôt que laisser croire que
    le français est la langue choisie.
    """
    if section not in _IDENTIFIANTS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "doc.section_unknown", "params": {"section": section}},
        )

    chemin = _chemin(section, langue)
    langue_servie = "".join(c for c in langue if c.isalpha())[:5] or LANGUE_DE_REFERENCE
    if not chemin.exists():
        chemin = _chemin(section, LANGUE_DE_REFERENCE)
        langue_servie = LANGUE_DE_REFERENCE

    if not chemin.exists():
        # Le manuel n'est pas déployé : c'est une anomalie d'installation, pas
        # une demande invalide.
        logger.error("Documentation absente : %s", chemin)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "doc.unavailable", "params": {}},
        )

    return {
        "section": section,
        "langue_demandee": langue,
        "langue_servie": langue_servie,
        "traduite": langue_servie == "".join(c for c in langue if c.isalpha())[:5],
        "contenu": chemin.read_text(encoding="utf-8"),
    }
