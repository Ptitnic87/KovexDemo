"""La forme d'un modèle de rôles : ce qu'il faut en savoir avant de le lire.

Un mining métier sur un référentiel hospitalier de 21 000 identités rend 1 751
rôles. L'écran l'annonçait ainsi : « 1 751 résultats », suivis de 1 751 cartes.
C'est exact, et inexploitable. Personne ne prend 1 751 décisions ; personne ne
lit 1 751 cartes pour découvrir que les 162 premières portent la moitié du
travail.

Le moteur connaît pourtant la forme de ce qu'il rend. Sa sélection est
gloutonne : chaque rôle retenu porte l'apport qu'il a fait au moment où il a été
choisi (`marginal_gain`), et son rang. La somme de ces apports, cumulée dans
l'ordre des rangs, décrit exactement comment le modèle se construit — et où il
cesse de progresser. Ce module ne calcule rien de neuf : il lit ce que la
sélection a déjà mesuré et en tire deux réponses.

**Combien de rôles pour quelle part du modèle.** « 162 rôles expliquent la
moitié de ce que le modèle explique, 885 en expliquent 90 % » est une phrase sur
laquelle on peut agir : le produit a un paramètre de couverture visée, et
personne ne pouvait le renseigner sans cette phrase. Un curseur sans sa courbe
n'est pas un réglage, c'est une devinette.

**Quelle taille ont ces rôles.** La médiane des effectifs dit en un chiffre si le
mining a produit des règles ou des poignées de gens. Six porteurs médians sur un
référentiel de 21 000 identités ne se lit pas comme un modèle trop grand : cela
se lit comme un `min_users` trop bas, et c'est une autre correction.

Une précision qui n'est pas un détail : la part est **celle du modèle**, pas
celle du référentiel. Elle dit quelle fraction de ce que ce modèle explique est
portée par ses n premiers rôles. Ce que le modèle explique du référentiel entier
est une autre mesure, rendue ailleurs sous `quality.coverage_pct`. Les
confondre ferait lire « 90 % » comme une couverture des habilitations, qu'elle
n'est pas.
"""

from typing import Any, Dict, List, Sequence

#: Parts du modèle dont on rend le rang d'atteinte. Ce ne sont pas des seuils de
#: décision — rien n'en dépend dans le calcul — mais les repères d'une lecture :
#: la moitié, l'essentiel, la quasi-totalité. Les publier ici plutôt que dans le
#: client permet aux trois écrans de citer les mêmes.
PALIERS = (0.5, 0.8, 0.9, 0.95)


def _quantile(valeurs_triees: Sequence[int], part: float) -> int:
    """Quantile par rang, sans interpolation.

    Un effectif est un nombre de personnes : une médiane de 6,5 porteurs ne
    décrit rien. On rend donc une valeur observée.

    La suite reçue n'est jamais vide : `forme` rend une description vide avant
    d'appeler cette fonction. Un garde ici serait du code que rien n'atteint.
    """
    rang = min(len(valeurs_triees) - 1, int(part * len(valeurs_triees)))
    return int(valeurs_triees[rang])


def forme(roles: Sequence[Dict[str, Any]],
          lignes_du_perimetre: int = 0) -> Dict[str, Any]:
    """Décrit un modèle : sa progression, et la taille de ses rôles.

    `roles` est la liste retenue par la sélection, dans n'importe quel ordre :
    le rang porté par chaque rôle fait foi.
    """
    if not roles:
        return {"total_roles": 0, "lignes_expliquees": 0,
                "paliers": [], "effectifs": {}}

    # L'ordre de la sélection, et non celui de la liste reçue : une route qui
    # trierait les rôles pour l'affichage fausserait la courbe sans le dire.
    ordonnes = sorted(roles, key=lambda role: role.get("rank") or 0)
    apports = [int(role.get("marginal_gain") or 0) for role in ordonnes]
    total = sum(apports)

    paliers: List[Dict[str, Any]] = []
    if total:
        cumul = 0
        restants = list(PALIERS)
        for rang, apport in enumerate(apports, start=1):
            cumul += apport
            while restants and cumul >= restants[0] * total:
                paliers.append({
                    "part": restants.pop(0),
                    "roles": rang,
                    # Ce que ce nombre de rôles couvre du **référentiel**, dans
                    # l'unité du paramètre de couverture visée. Absent quand le
                    # périmètre n'est pas connu : mieux vaut ne pas proposer le
                    # report que de proposer un chiffre faux.
                    "couverture": (round(100.0 * cumul / lignes_du_perimetre, 1)
                                   if lignes_du_perimetre else None),
                })

    effectifs = sorted(int(role.get("user_count") or 0) for role in roles)
    return {
        "total_roles": len(roles),
        # Lignes d'habilitation que ce modèle explique. C'est le dénominateur
        # des parts ci-dessus, et il est rendu pour qu'elles soient
        # vérifiables plutôt qu'à croire.
        "lignes_expliquees": total,
        "paliers": paliers,
        "effectifs": {
            "min": effectifs[0],
            "q1": _quantile(effectifs, 0.25),
            "mediane": _quantile(effectifs, 0.5),
            "q3": _quantile(effectifs, 0.75),
            "max": effectifs[-1],
        },
    }
