# Fichier : src/core/knowledge/controles.py
"""Le contrôle compensatoire : ce qui rend une exception défendable.

Une dérogation dit « ce conflit est connu, accepté, pour cette raison, jusqu'à
cette date ». Un auditeur pose aussitôt la question suivante : **qu'est-ce qui
compense ?** Quelqu'un qui peut créer un fournisseur et le payer est acceptable
si, chaque mois, une autre personne relit les paiements aux fournisseurs créés
dans le mois. Sans ce contrôle, la dérogation n'est qu'un motif écrit.

Le contrôle devient donc un **objet** et non une phrase dans un motif :

- il a un **exécutant** et un **relecteur**, et ce ne peuvent pas être la même
  personne — un contrôle que son exécutant relit lui-même ne sépare rien ;
- il a un **âge maximal** : un contrôle mensuel dont la dernière exécution date
  de cinq mois ne compense plus rien, même s'il était conforme ;
- chaque **exécution** est consignée, datée, avec son résultat et la référence
  de sa preuve. Le produit ne stocke pas la preuve : il dit où elle est.

Et la question que ce module sert à répondre est celle de l'auditeur, posée à
l'envers : **pour quelles raisons cette dérogation ne couvre-t-elle plus son
constat ?** Chaque raison est nommée, une par une. Une dérogation qui en porte
une seule ne couvre plus rien — le conflit revient dans la liste des choses à
traiter, et l'écran dit pourquoi.

La forme vient du modèle de gouvernance des exceptions de
MaxwellM-GRC/sod-monitoring-poc (MIT) ; le calcul est réécrit ici sur les
objets de Kovex.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

#: Longueur d'un libellé, d'un nom d'exécutant ou de relecteur.
TEXTE_MAX = 200

#: Longueur de la référence d'une preuve : un chemin, un numéro de ticket, un
#: lien. Le produit ne stocke pas la preuve, il dit où elle est.
PREUVE_MAX = 500

#: Les deux résultats d'une exécution. Liste fermée : chaque code est aussi une
#: clé de traduction — `controle.resultat.<code>`.
CONFORME = "conforme"
NON_CONFORME = "non_conforme"
RESULTATS = (CONFORME, NON_CONFORME)

#: Les raisons pour lesquelles une dérogation ne couvre plus son constat.
#: Chaque code est une clé de traduction — `derogation.raison.<code>`.
SANS_CONTROLE = "sans_controle"
CONTROLE_INCONNU = "controle_inconnu"
CONTROLE_SUSPENDU = "controle_suspendu"
JAMAIS_EXECUTE = "jamais_execute"
EXECUTION_PERIMEE = "execution_perimee"
EXECUTION_NON_CONFORME = "execution_non_conforme"
RELU_PAR_SON_EXECUTANT = "relu_par_son_executant"
RAISONS = (SANS_CONTROLE, CONTROLE_INCONNU, CONTROLE_SUSPENDU, JAMAIS_EXECUTE,
           EXECUTION_PERIMEE, EXECUTION_NON_CONFORME, RELU_PAR_SON_EXECUTANT)


class ControleInvalide(ValueError):
    """Un contrôle ou une exécution que le produit refuse d'enregistrer."""


def _texte(brut: Any, champ: str, longueur: int = TEXTE_MAX,
           obligatoire: bool = True) -> str:
    texte = str(brut or "").strip()[:longueur]
    if obligatoire and not texte:
        raise ControleInvalide(f"{champ} est vide")
    return texte


def _meme_personne(premiere: str, seconde: str) -> bool:
    """Deux noms désignent-ils la même personne ?

    Comparés sans la casse ni les espaces de bord : « J. Martin » et
    « j. martin » sont la même personne, et la laisser relire son propre
    contrôle parce qu'elle a changé une majuscule serait une faille.
    """
    return premiere.strip().casefold() == seconde.strip().casefold()


@dataclass(frozen=True)
class Controle:
    """Un contrôle compensatoire, tel que le client le décrit.

    Attributes:
        identifiant: la clé, choisie par le produit.
        libelle: ce que le contrôle vérifie, dans les mots du client.
        executant: qui l'exécute.
        relecteur: qui relit l'exécution. Jamais l'exécutant.
        age_max_jours: au-delà de cet âge, la dernière exécution ne compense
            plus rien. C'est la fréquence du contrôle, écrite comme une borne.
        actif: un contrôle suspendu ne compense rien.
    """

    identifiant: str
    libelle: str
    executant: str
    relecteur: str
    age_max_jours: int
    actif: bool = True

    @classmethod
    def depuis_dict(cls, brut: Mapping[str, Any]) -> "Controle":
        identifiant = _texte(brut.get("id"), "l'identifiant du contrôle", 64)
        executant = _texte(brut.get("executant"), f"l'exécutant de {identifiant}")
        relecteur = _texte(brut.get("relecteur"), f"le relecteur de {identifiant}")
        if _meme_personne(executant, relecteur):
            raise ControleInvalide(
                f"le contrôle {identifiant} est relu par son exécutant : "
                "il ne sépare rien")
        try:
            age = int(brut.get("age_max_jours"))
        except (TypeError, ValueError):
            raise ControleInvalide(
                f"le contrôle {identifiant} n'a pas d'âge maximal") from None
        if age < 1:
            raise ControleInvalide(
                f"l'âge maximal du contrôle {identifiant} doit être positif")
        return cls(identifiant=identifiant,
                   libelle=_texte(brut.get("libelle"), f"le libellé de {identifiant}"),
                   executant=executant, relecteur=relecteur,
                   age_max_jours=age, actif=bool(brut.get("actif", True)))

    def en_dict(self) -> Dict[str, Any]:
        return {"id": self.identifiant, "libelle": self.libelle,
                "executant": self.executant, "relecteur": self.relecteur,
                "age_max_jours": self.age_max_jours, "actif": self.actif}


@dataclass(frozen=True)
class Execution:
    """Une exécution consignée d'un contrôle.

    `executant`, `relecteur`, `resultat` et `preuve` sont déclarés par celui
    qui consigne ; `consignee_par` et `consignee_le` viennent du serveur — sur
    l'objet qui rend une exception défendable, ce sont les deux champs qu'il ne
    faut pas accepter de l'extérieur.
    """

    controle: str
    execute_le: date
    executant: str
    relecteur: str
    resultat: str
    preuve: str
    consignee_par: str
    consignee_le: date

    @classmethod
    def depuis_dict(cls, brut: Mapping[str, Any]) -> "Execution":
        controle = _texte(brut.get("controle"), "le contrôle exécuté", 64)
        resultat = str(brut.get("resultat") or "").strip()
        if resultat not in RESULTATS:
            raise ControleInvalide(
                f"résultat inconnu : {resultat!r} (attendu : {', '.join(RESULTATS)})")
        execute_le = _jour(brut.get("execute_le"), "la date d'exécution")
        consignee_le = _jour(brut.get("consignee_le"), "la date de consignation")
        if execute_le > consignee_le:
            raise ControleInvalide(
                "une exécution ne se consigne pas avant d'avoir eu lieu")
        return cls(controle=controle, execute_le=execute_le,
                   executant=_texte(brut.get("executant"), "l'exécutant"),
                   relecteur=_texte(brut.get("relecteur"), "le relecteur",
                                    obligatoire=False),
                   resultat=resultat,
                   preuve=_texte(brut.get("preuve"), "la référence de la preuve",
                                 PREUVE_MAX),
                   consignee_par=str(brut.get("consignee_par") or "").strip(),
                   consignee_le=consignee_le)

    def en_dict(self) -> Dict[str, Any]:
        return {"controle": self.controle,
                "execute_le": self.execute_le.isoformat(),
                "executant": self.executant, "relecteur": self.relecteur,
                "resultat": self.resultat, "preuve": self.preuve,
                "consignee_par": self.consignee_par,
                "consignee_le": self.consignee_le.isoformat()}


def _jour(valeur: Any, champ: str) -> date:
    texte = str(valeur or "").strip()
    try:
        return date.fromisoformat(texte)
    except ValueError:
        raise ControleInvalide(
            f"{champ} n'est pas une date au format AAAA-MM-JJ : {texte!r}") from None


def controles_valides(bruts: Sequence[Mapping[str, Any]]) -> Dict[str, Controle]:
    """Les contrôles lisibles, par identifiant ; les autres sont signalés.

    Un contrôle écarté fait **perdre sa couverture** à la dérogation qui le
    cite — le défaut sûr : on remontre un conflit, on n'en cache aucun.
    """
    valides: Dict[str, Controle] = {}
    for brut in bruts:
        try:
            controle = Controle.depuis_dict(brut)
        except ControleInvalide as erreur:
            logger.warning("Contrôle compensatoire ignoré : %s", erreur)
            continue
        valides[controle.identifiant] = controle
    return valides


def executions_valides(brutes: Iterable[Mapping[str, Any]]) -> List[Execution]:
    valides: List[Execution] = []
    for brute in brutes:
        try:
            valides.append(Execution.depuis_dict(brute))
        except ControleInvalide as erreur:
            logger.warning("Exécution de contrôle ignorée : %s", erreur)
    return valides


def derniere_execution(controle: str,
                       executions: Sequence[Execution]) -> Optional[Execution]:
    """La plus récente, par date d'exécution puis de consignation.

    C'est elle qui décide : une exécution conforme d'il y a six mois ne rachète
    pas une exécution non conforme de la semaine dernière.
    """
    siennes = [une for une in executions if une.controle == controle]
    if not siennes:
        return None
    return max(siennes, key=lambda une: (une.execute_le, une.consignee_le))


def raisons(controle_cite: str,
            controles: Mapping[str, Controle],
            executions: Sequence[Execution],
            aujourdhui: date,
            exige: bool) -> List[Dict[str, Any]]:
    """Pourquoi une dérogation ne couvre plus son constat — chaque raison.

    Args:
        controle_cite: l'identifiant du contrôle que la dérogation cite, ou
            rien.
        controles: le catalogue du workspace.
        executions: toutes les exécutions consignées.
        aujourdhui: le jour du calcul.
        exige: le workspace exige-t-il un contrôle pour toute dérogation ?

    Returns:
        Une liste de `{"code", "params"}`. Vide, la dérogation couvre.
    """
    if not controle_cite:
        return [{"code": SANS_CONTROLE, "params": {}}] if exige else []
    controle = controles.get(controle_cite)
    if controle is None:
        return [{"code": CONTROLE_INCONNU, "params": {"controle": controle_cite}}]

    trouvees: List[Dict[str, Any]] = []
    if not controle.actif:
        trouvees.append({"code": CONTROLE_SUSPENDU,
                         "params": {"controle": controle.libelle}})
    derniere = derniere_execution(controle.identifiant, executions)
    if derniere is None:
        trouvees.append({"code": JAMAIS_EXECUTE,
                         "params": {"controle": controle.libelle}})
        return trouvees
    age = (aujourdhui - derniere.execute_le).days
    if age > controle.age_max_jours:
        trouvees.append({"code": EXECUTION_PERIMEE,
                         "params": {"controle": controle.libelle, "age": age,
                                    "age_max": controle.age_max_jours,
                                    "date": derniere.execute_le.isoformat()}})
    if derniere.resultat == NON_CONFORME:
        trouvees.append({"code": EXECUTION_NON_CONFORME,
                         "params": {"controle": controle.libelle,
                                    "date": derniere.execute_le.isoformat()}})
    if not derniere.relecteur or _meme_personne(derniere.executant,
                                                derniere.relecteur):
        trouvees.append({"code": RELU_PAR_SON_EXECUTANT,
                         "params": {"controle": controle.libelle,
                                    "date": derniere.execute_le.isoformat()}})
    return trouvees


def etat_du_controle(controle: Controle, executions: Sequence[Execution],
                     aujourdhui: date) -> Dict[str, Any]:
    """Ce qu'un écran montre d'un contrôle : lui, sa dernière exécution, ses raisons."""
    derniere = derniere_execution(controle.identifiant, executions)
    return {**controle.en_dict(),
            "derniere_execution": derniere.en_dict() if derniere else None,
            "raisons": raisons(controle.identifiant,
                               {controle.identifiant: controle}, executions,
                               aujourdhui, exige=True)}
