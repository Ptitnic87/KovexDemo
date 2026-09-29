# src/core/annotation/regroupeur.py
"""Ce qu'un modèle apporte au rapprochement des valeurs, et ce qu'on lui refuse.

Le repérage local du lot 39a compare les valeurs **entre elles** : distance
d'édition, pluriel, abréviation, troncature. Il trouve `Infimier` pour
`Infirmier`, et `secretaire medic` pour `secrétaire médicale`.

Il ne trouvera jamais `AS` pour `Aide-soignant`, ni `RRH` pour
`Responsable ressources humaines`, ni les deux nomenclatures d'un groupe né
d'une fusion. Ces rapprochements-là demandent de savoir ce que les mots
veulent dire, et c'est la seule chose qu'un modèle apporte ici.

**Ce qu'on lui refuse, en revanche, tient en une phrase : il ne dit que des
mots, et pas un seul chiffre.** Les effectifs, la conséquence du regroupement,
le nombre de valeurs concernées sont calculés par le produit sur le
référentiel — jamais lus dans la réponse. Un modèle qui annoncerait « ces
quatre valeurs font 63 personnes » serait cru, et il aurait inventé le nombre.

Cinq contrôles s'appliquent à chaque groupe proposé, et chacun correspond à
une façon dont une réponse plausible ferait un faux rôle :

1. **une valeur absente du référentiel est retirée.** Le modèle reformule
   volontiers — `Aide soignant` pour `Aide-soignant` — et la valeur reformulée
   ne recoderait rien ;
2. **un groupe réduit à une valeur est écarté.** Il ne rapproche plus rien ;
3. **une valeur ne peut appartenir qu'à un groupe.** Deux groupes qui la
   partagent donneraient deux recodages contradictoires pour la même valeur ;
4. **un groupe qui contient une paire refusée est écarté entier.** L'utilisateur
   a déjà dit que ces deux valeurs sont distinctes ; le produit ne répare pas
   la proposition à sa place, il la jette ;
5. **un groupe que le repérage local propose déjà est écarté.** L'enrichissement
   complète le repérage, il ne le répète pas — un écran qui montrerait deux
   fois la même grappe ferait douter des deux.

La forme retenue, elle, peut venir du modèle, à une condition : qu'elle soit
**l'une des valeurs du référentiel**. Choisir `Aide-soignant` plutôt que `AS`
est un jugement sur les mots, et c'est utile ; écrire une nomenclature que le
client n'emploie pas ne l'est pas. À défaut, c'est la plus fréquente, comme
pour le repérage local — et l'utilisateur corrige à l'écran dans les deux cas.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from src.core.annotation.annotateur import (
    LONGUEUR_DESCRIPTION_MAX,
    AnnotateurIndisponible,
    Reglages,
    RienANommer,
    _nettoyer,
)
from src.core.annotation.assistance import (
    MATIERE_NOMS_DE_COLONNES,
    MATIERE_VALEURS_D_ATTRIBUT,
    Autorisation,
)
from src.core.annotation.propositions import composer_la_demande_de
from src.core.data import coherence

logger = logging.getLogger(__name__)

#: Groupes retenus d'une réponse. Au-delà, l'écran n'est plus relisible et la
#: réponse ressemble à un découpage systématique plutôt qu'à un jugement.
GROUPES_MAX = 50

#: Valeurs retenues dans un groupe. Un groupe plus large que cela ne rapproche
#: plus des écritures d'une même chose : il fusionne des populations.
VALEURS_PAR_GROUPE_MAX = 20

#: L'origine inscrite sur les grappes rendues ici. Un auditeur doit pouvoir
#: isoler ce qui vient d'un modèle de ce qui vient du calcul.
ORIGINE_MODELE = "modele"


CONSIGNE_REGROUPEMENT = (
    "On te donne les valeurs distinctes d'une colonne d'un référentiel "
    "d'identités ou d'habilitations. Tu regroupes celles qui désignent la "
    "même chose.\n"
    "Ce qu'on cherche, c'est ce qu'une comparaison de chaînes ne trouve pas : "
    "une abréviation et son développé, un sigle et son intitulé, deux "
    "nomenclatures pour une même réalité, un libellé ancien et son "
    "remplaçant.\n"
    "Règles :\n"
    "- Ne rends que des valeurs présentes telles quelles dans la liste "
    "donnée. Ne les reformule pas, ne corrige ni la casse ni les accents.\n"
    "- Ne regroupe pas deux libellés qui désignent des fonctions voisines "
    "mais distinctes : dans le doute, ne regroupe pas.\n"
    "- Deux codes courts qui ne diffèrent que d'une seule lettre désignent "
    "presque toujours deux choses différentes, souvent contraires : ce sont "
    "deux codes d'une même famille, pas deux écritures d'une même chose. Ne "
    "les regroupe jamais. Exemple à ne pas faire : regrouper \"CDI\" et "
    "\"CDD\" ; en revanche \"CDI\" et \"C.D.I.\" sont bien la même "
    "chose, et \"CDI\" avec son développé aussi.\n"
    "- Ne regroupe jamais une valeur avec son contraire ou sa négation.\n"
    "- Un intitulé plus précis n'est pas une écriture d'un intitulé plus "
    "large.\n"
    "- \"forme_retenue\" doit être l'une des valeurs du groupe : celle qui "
    "s'écrit le plus clairement.\n"
    "- S'il n'y a rien à regrouper, rends une liste vide.\n"
    "Réponds uniquement par un objet JSON avec une clé \"groupes\", un "
    "tableau d'objets ayant \"valeurs\" (un tableau de valeurs), "
    "\"forme_retenue\" et \"motif\" (une phrase courte disant pourquoi ces "
    "valeurs désignent la même chose)."
)


def groupes_lus(charge: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Lit la réponse, sans encore rien confronter au référentiel.

    Cette étape ne juge que la **forme** : ce qui n'a pas la forme d'un groupe
    n'est pas un groupe. La confrontation aux valeurs réelles vient après, et
    elle est séparée parce que c'est elle qui porte les garanties du lot.
    """
    try:
        contenu = charge["choices"][0]["message"]["content"]
        propose = json.loads(contenu)
        bruts = propose["groupes"]
        if not isinstance(bruts, list):
            raise TypeError("groupes n'est pas une liste")
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        raise AnnotateurIndisponible("réponse illisible")

    lus: List[Dict[str, Any]] = []
    for brut in bruts:
        if not isinstance(brut, Mapping):
            continue
        valeurs = brut.get("valeurs")
        if not isinstance(valeurs, (list, tuple)):
            continue
        lus.append({
            "valeurs": [str(valeur) for valeur in valeurs
                        if isinstance(valeur, (str, int, float))],
            "forme_retenue": str(brut.get("forme_retenue", "")),
            "motif": _nettoyer(brut.get("motif"), LONGUEUR_DESCRIPTION_MAX),
        })
        if len(lus) == GROUPES_MAX:
            break
    return lus


def _index_local(grappes: Sequence[coherence.Grappe]) -> Dict[str, int]:
    """À quelle grappe locale appartient chaque valeur, si elle en a une."""
    index: Dict[str, int] = {}
    for rang, grappe in enumerate(grappes):
        for valeur in grappe.valeurs:
            index[valeur] = rang
    return index


def grappes_verifiees(
        proposes: Sequence[Mapping[str, Any]],
        effectifs: Mapping[str, int],
        soumises: Sequence[str],
        refus: Iterable[Tuple[str, str]] = (),
        grappes_locales: Sequence[coherence.Grappe] = (),
) -> Tuple[List[coherence.Grappe], Dict[str, int]]:
    """Les cinq contrôles, et le compte de ce qu'ils ont écarté.

    Le compte n'est pas une statistique : il s'affiche. « Le modèle a proposé
    douze regroupements, trois ont été écartés parce qu'ils citaient des
    valeurs absentes de votre référentiel » est la preuve visible que la
    réponse a été confrontée aux données — et le signe, s'il devient gros, que
    ce modèle-là ne convient pas.

    Seules les valeurs **soumises** sont admises : une valeur du référentiel
    que le modèle n'a pas reçue mais qu'il aurait devinée ne viendrait pas de
    son jugement sur ce qu'on lui a montré.
    """
    admissibles = set(soumises)
    # Le modèle rend ce qu'il veut. La consigne lui interdit de reformuler,
    # mais une majuscule, un accent ou une espace de trop suffisaient à faire
    # écarter la proposition **entière** comme une valeur inventée — et c'est
    # précisément ce qui faisait échouer le seul rapprochement qui justifie cet
    # usage : « Contrat à durée indéterminée » avec « CDI ».
    #
    # Le contrôle ne s'affaiblit pas : la valeur doit toujours exister dans la
    # colonne. Seule la **reconnaissance** devient tolérante, par le même
    # repliement que le repérage local — casse, accents, ponctuation, espaces —
    # et uniquement quand ce repliement désigne **une seule** valeur soumise.
    # Ambigu, on n'arbitre pas : `Cadre` et `cadre` coexistent parfois dans un
    # référentiel, et choisir à la place de l'utilisateur serait pire.
    repliees: Dict[str, List[str]] = {}
    for valeur in soumises:
        repliees.setdefault(coherence.replier(valeur), []).append(valeur)

    def resoudre(brute: Any) -> Optional[str]:
        texte = str(brute)
        if texte in admissibles:
            return texte
        candidates = repliees.get(coherence.replier(texte), ())
        return candidates[0] if len(candidates) == 1 else None

    interdites = {coherence._paire(gauche, droite) for gauche, droite in refus}
    index_local = _index_local(grappes_locales)

    ecartees = {"valeurs_inconnues": 0, "trop_courtes": 0, "refusees": 0,
                "deja_proposees": 0, "valeurs_reprises": 0,
                "valeurs_repliees": 0, "propositions_ecartees": 0}
    retenues: List[coherence.Grappe] = []
    deja_placees: set = set()

    for propose in proposes:
        valeurs, inconnues, reprises, tolerees = [], 0, 0, 0
        for brute in propose["valeurs"]:
            valeur = resoudre(brute)
            if valeur is None:
                inconnues += 1
                continue
            if str(brute) != valeur:
                tolerees += 1
            if valeur in deja_placees or valeur in valeurs:
                reprises += 1
                continue
            valeurs.append(valeur)
        ecartees["valeurs_inconnues"] += inconnues
        ecartees["valeurs_reprises"] += reprises
        ecartees["valeurs_repliees"] += tolerees
        valeurs = valeurs[:VALEURS_PAR_GROUPE_MAX]

        # Les compteurs ne mesurent pas la même chose : `valeurs_inconnues`
        # compte des **valeurs**, les trois suivants comptent des
        # **propositions**. L'écran les additionnait, et annonçait « onze
        # propositions écartées » là où il y en avait moins — une proposition
        # citant une valeur inventée était comptée deux fois. Ce compteur-ci
        # est celui qui se dit « propositions », et lui seul.
        if len(valeurs) < 2:
            ecartees["trop_courtes"] += 1
            ecartees["propositions_ecartees"] += 1
            continue
        if any(coherence._paire(un, autre) in interdites
               for rang, un in enumerate(valeurs) for autre in valeurs[rang + 1:]):
            # L'utilisateur a déjà tranché. Le produit ne recompose pas un
            # groupe amputé : il jette la proposition et le dit.
            ecartees["refusees"] += 1
            ecartees["propositions_ecartees"] += 1
            continue
        rangs = {index_local.get(valeur) for valeur in valeurs}
        if len(rangs) == 1 and None not in rangs:
            ecartees["deja_proposees"] += 1
            ecartees["propositions_ecartees"] += 1
            continue

        ordonnees = sorted(valeurs, key=lambda v: (-effectifs.get(v, 0), v))
        forme = propose.get("forme_retenue", "")
        retenues.append(coherence.Grappe(
            valeurs=tuple(ordonnees),
            effectifs=tuple(effectifs.get(valeur, 0) for valeur in ordonnees),
            forme_retenue=forme if forme in valeurs else ordonnees[0],
            signaux=(),
            origine=ORIGINE_MODELE,
            # La raison invoquée, telle que le modèle l'a écrite. Elle n'est ni
            # vérifiée ni vérifiable : c'est précisément pour cela qu'elle doit
            # atteindre l'écran. Les contrôles ci-dessus savent qu'une valeur
            # existe ; seul un humain sait que « CDD » n'est pas un contrat à
            # durée indéterminée, et il ne peut le voir que là.
            motif=propose.get("motif", "") or "",
        ))
        deja_placees.update(ordonnees)

    retenues.sort(key=lambda grappe: (-grappe.effectif_total,
                                      grappe.forme_retenue))
    return retenues, ecartees


def proposer_les_regroupements(
        reglages: Reglages, autorisation: Autorisation,
        valeurs: Sequence[Any], referentiel: str, colonne: str,
        reglages_coherence: coherence.Reglages, langue: str, envoyer,
        refus: Iterable[Tuple[str, str]] = ()) -> Dict[str, Any]:
    """Soumet les valeurs d'une colonne, et ne garde que ce qui résiste.

    Quatre refus avant tout envoi, et aucun n'est redondant :

    - l'assistance est éteinte — il n'y a pas de modèle ;
    - l'usage est fermé, ou sa matière nécessaire n'est pas ouverte ;
    - **cette colonne-là** n'est pas ouverte. C'est la garantie propre à cet
      usage : autoriser `type_de_contrat` à sortir n'autorise pas `service` ;
    - la colonne est typée — nombres, dates, montants. Rien de ce qu'un modèle
      dirait de `2024-01-01` ne vaut le fait de l'avoir envoyé.
    """
    if not reglages.actif:
        raise AnnotateurIndisponible("assistance désactivée")
    if not autorisation.posable:
        raise RienANommer("usage fermé ou matière non autorisée")
    if not autorisation.autorise(MATIERE_VALEURS_D_ATTRIBUT):
        raise RienANommer("valeurs d'attribut non autorisées")
    if not autorisation.autorise_la_colonne(referentiel, colonne):
        raise RienANommer("colonne non autorisée")

    effectifs = coherence.compter(valeurs)
    if not effectifs:
        raise RienANommer("colonne vide")
    if coherence.est_typee(effectifs) > reglages_coherence.part_typee_max:
        raise RienANommer("colonne typée")

    soumises = coherence.valeurs_retenues(
        effectifs, reglages_coherence.valeurs_soumises_max)
    if len(soumises) < 2:
        raise RienANommer("rien à rapprocher")

    faits: Dict[str, Any] = {"valeurs": soumises}
    categories = [MATIERE_VALEURS_D_ATTRIBUT]
    if autorisation.autorise(MATIERE_NOMS_DE_COLONNES):
        # Facultative, et c'est ici que la distinction se voit : le nom de la
        # colonne oriente fortement la réponse, et il sort seulement si
        # l'administrateur l'a ouvert pour cet usage.
        faits["colonne"] = colonne
        categories.append(MATIERE_NOMS_DE_COLONNES)

    locale = coherence.analyser(valeurs, referentiel, colonne,
                                reglages_coherence, refus)
    reponse = envoyer(composer_la_demande_de(
        CONSIGNE_REGROUPEMENT, faits, reglages, langue))
    grappes, ecartees = grappes_verifiees(
        groupes_lus(reponse), effectifs, soumises, refus, locale.grappes)

    return {
        "referentiel": referentiel,
        "colonne": colonne,
        "grappes": grappes,
        "ecartees": ecartees,
        "valeurs_soumises": len(soumises),
        "valeurs_distinctes": len(effectifs),
        "modele": reglages.modele,
        "usage": autorisation.usage.code,
        "categories_transmises": categories,
    }
