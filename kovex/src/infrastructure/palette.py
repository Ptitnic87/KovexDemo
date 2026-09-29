"""Couleurs et typographie du produit, côté serveur.

Les documents produits par le serveur — le rapport PDF aujourd'hui — doivent
ressembler à l'application. Les couleurs vivent dans
`frontend/css/variables.css`, que Python ne lit pas ; elles sont donc reprises
ici, et un test vérifie que les deux ne divergent pas. Recopier sans garde-fou
serait pire que ne rien partager : les deux jeux se seraient éloignés à la
première retouche de thème.

**Les paliers sont choisis par mesure, pas au jugé.** Un document se lit sur
fond blanc, souvent imprimé : les paliers 500 de l'interface, posés sur un fond
sombre, n'y ont pas un contraste suffisant. Contrastes WCAG relevés sur blanc :

    danger-500  3,67  insuffisant      danger-700  6,29  conforme
    warning-500 2,15  insuffisant      warning-700 5,02  conforme
    info-500    4,47  gros texte       info-700    7,90  conforme
    primary-500 3,67  insuffisant      primary-700 6,74  conforme

D'où le choix des paliers 700 pour tout texte coloré, et des paliers 50 pour
les aplats. C'est la même palette que l'application, à la marche près qu'impose
le passage sur fond clair.
"""

from typing import Dict

#: Rampes de l'interface, reprises telles quelles de `variables.css`.
RAMPES: Dict[str, Dict[int, str]] = {
    "primary": {
        50: "#e8f0fe", 100: "#c5dafc", 500: "#2e84f4", 600: "#1a6ee0",
        700: "#1458b8", 800: "#0f4390", 900: "#0a2d68",
    },
    "success": {
        50: "#ecfdf5", 100: "#d1fae5", 500: "#10b981", 600: "#059669",
        700: "#047857", 800: "#065f46", 900: "#064e3b",
    },
    "warning": {
        50: "#fffbeb", 100: "#fef3c7", 500: "#f59e0b", 600: "#d97706",
        700: "#b45309", 800: "#92400e", 900: "#78350f",
    },
    "danger": {
        50: "#fff1f2", 100: "#ffe4e6", 500: "#f43f5e", 600: "#e11d48",
        700: "#be123c", 800: "#9f1239", 900: "#881337",
    },
    "info": {
        50: "#eef2ff", 100: "#e0e7ff", 500: "#6366f1", 600: "#4f46e5",
        700: "#4338ca", 800: "#3730a3", 900: "#312e81",
    },
    "neutral": {
        0: "#ffffff", 50: "#f8fafc", 100: "#f1f5f9", 200: "#e2e8f0",
        300: "#cbd5e1", 400: "#94a3b8", 500: "#64748b", 600: "#475569",
        700: "#334155", 800: "#1e293b", 900: "#0f172a",
    },
}

# --- Rôles, pour un document sur fond clair -------------------------------

ENCRE = RAMPES["neutral"][900]
ENCRE_SECONDAIRE = RAMPES["neutral"][600]
ENCRE_DISCRETE = RAMPES["neutral"][500]
FOND = RAMPES["neutral"][0]
FOND_ALTERNE = RAMPES["neutral"][50]
FOND_ENTETE = RAMPES["neutral"][100]
BORDURE = RAMPES["neutral"][200]
BORDURE_FORTE = RAMPES["neutral"][300]

ACCENT = RAMPES["primary"][700]
BANDEAU = RAMPES["primary"][700]
SUR_BANDEAU = RAMPES["neutral"][0]

#: Couleurs d'état. Elles sont **réservées** : jamais réutilisées pour
#: distinguer autre chose qu'une gravité, et toujours accompagnées de leur
#: libellé — une gravité signalée par la seule couleur est illisible pour une
#: partie des lecteurs, et disparaît à l'impression en noir et blanc.
SEVERITE_TEXTE = {
    "critical": RAMPES["danger"][700],
    "warning": RAMPES["warning"][700],
    "info": RAMPES["info"][700],
}
SEVERITE_FOND = {
    "critical": RAMPES["danger"][50],
    "warning": RAMPES["warning"][50],
    "info": RAMPES["info"][50],
}

#: Polices. Celles de l'interface (Outfit, JetBrains Mono) ne sont pas
#: embarquées dans reportlab ; on emploie les équivalents de base, dont les
#: métriques sont toujours disponibles, quel que soit le poste.
POLICE = "Helvetica"
POLICE_GRASSE = "Helvetica-Bold"
POLICE_MONO = "Courier"
