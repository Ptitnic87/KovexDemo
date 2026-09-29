# Fichier : src/mcp/serveur.py
"""Le serveur MCP de Kovex : un agent extérieur interroge, Kovex calcule.

Le marché converge vers le protocole MCP (Model Context Protocol) : SailPoint,
Saviynt et Radiant exposent leur référentiel à un agent — et tous le font
depuis leur cloud. Kovex l'expose **sur la machine où il tourne**, par
l'entrée et la sortie standard : l'agent (Claude Desktop, un IDE, un agent
maison) lance ce processus et lui parle en JSON-RPC. Aucun port ouvert, aucun
jeton, aucun réseau : le serveur a exactement les droits du compte qui le
lance, c'est-à-dire ceux qu'il faut pour lire les fichiers de Kovex.

Trois règles, qui sont toute la conception :

1. **lecture seule.** Aucun outil n'écrit : pas de rôle validé, pas de
   dérogation, pas de réglage. Un agent qui décide à la place d'un humain est
   ce qu'un auditeur reprochera d'abord — le produit ne lui en donne pas les
   moyens ;
2. **aucune personne ne sort.** Les outils rendent des comptes, des codes de
   droits, des noms de rôles, des libellés de règles — jamais un identifiant
   d'identité. Les questions qui portent sur une personne (« quels droits a
   Jean Dupont ») ne sont pas exposées ;
3. **gouverné par la même matrice que le reste.** L'usage `serveur_mcp` est
   fermé par défaut ; ouvert, il rend les comptes, et les mots seulement si
   leur matière est ouverte pour lui. Chaque appel est consigné dans la piste
   d'audit, avec ce qui est sorti.

Les réponses sont celles de l'assistant (lot 59) et de l'écran des conflits :
mêmes fonctions, mêmes chiffres. Un agent qui obtiendrait d'autres nombres que
l'écran ferait perdre confiance dans les deux.

Lancement : ``python -m src.mcp.serveur --langue fr --racine <dossier de
Kovex>``, avec ce dossier dans ``PYTHONPATH`` et les mêmes variables
d'environnement que l'API.
"""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import sys
from typing import Any, Callable, Dict, List, Mapping, Optional, TextIO, Tuple

from src.core.annotation.assistance import (MATIERE_LIBELLES_DE_DROITS,
                                            MATIERE_NOMS_VALIDES,
                                            MATIERE_REGLES_DE_SEPARATION,
                                            USAGE_SERVEUR_MCP, Autorisation)
from src.core.audit.piste_audit import Action
from src.infrastructure.branding import NOM_PRODUIT, VERSION_PRODUIT

logger = logging.getLogger(__name__)

#: Les versions du protocole que ce serveur parle, la plus récente d'abord.
#: Un client qui en demande une autre reçoit la plus récente, comme le
#: protocole le prévoit ; à lui de décider s'il continue.
VERSIONS_DU_PROTOCOLE: Tuple[str, ...] = ("2025-06-18", "2025-03-26", "2024-11-05")

#: Codes d'erreur JSON-RPC 2.0.
ERREUR_LECTURE = -32700
ERREUR_REQUETE = -32600
ERREUR_METHODE = -32601
ERREUR_PARAMETRES = -32602

#: Longueur d'un argument accepté : un code de droit ou de rôle, pas un texte.
ARGUMENT_MAX = 200

#: Éléments rendus dans une liste. Un agent qui reçoit dix mille codes de
#: droits ne les lit pas ; il en tire une conclusion sur les premiers.
ELEMENTS_MAX = 200


class RefusDeL_Outil(Exception):
    """Une demande que l'outil ne peut pas servir : la phrase, dans la langue."""


# ------------------------------------------------------------------ les outils


def _schema(**proprietes: str) -> Dict[str, Any]:
    return {"type": "object",
            "properties": {nom: {"type": "string", "maxLength": ARGUMENT_MAX}
                           for nom in proprietes},
            "required": list(proprietes), "additionalProperties": False}


def _mots(autorisation: Autorisation, matiere: str, valeurs: List[str]) -> Optional[List[str]]:
    """Les mots, si leur matière est ouverte pour cet usage ; sinon rien."""
    if not autorisation.autorise(matiere):
        return None
    return valeurs[:ELEMENTS_MAX]


def _calcul_de_l_agent(code: str):
    from src.api.routers.agent import CALCULS

    return CALCULS[code]


def _porteurs_du_role(contexte, autorisation, arguments) -> Dict[str, Any]:
    reponse = _calcul_de_l_agent("porteurs_du_role")(contexte.loader, contexte.kb,
                                                   arguments["role"])
    # Les porteurs sont des personnes : seul leur nombre sort.
    return {"role": arguments["role"], "porteurs": reponse.params["porteurs"],
            "nom": (_mots(autorisation, MATIERE_NOMS_VALIDES, [reponse.params["role"]])
                    or [None])[0]}


def _droits_du_role(contexte, autorisation, arguments) -> Dict[str, Any]:
    reponse = _calcul_de_l_agent("droits_du_role")(contexte.loader, contexte.kb,
                                                 arguments["role"])
    return {"role": arguments["role"], "droits": reponse.params["droits"],
            "codes": _mots(autorisation, MATIERE_LIBELLES_DE_DROITS, reponse.identifiants)}


def _detenteurs_du_droit(contexte, autorisation, arguments) -> Dict[str, Any]:
    reponse = _calcul_de_l_agent("detenteurs_du_droit")(contexte.loader, contexte.kb,
                                                      arguments["droit"])
    return {"droit": arguments["droit"], "detenteurs": reponse.params["detenteurs"],
            "part_pct": reponse.params["part_pct"]}


def _catalogue(contexte, autorisation, arguments) -> Dict[str, Any]:
    reponse = _calcul_de_l_agent("compte_du_catalogue")(contexte.loader, contexte.kb, "")
    roles = contexte.kb.get_validated_roles()
    return {**reponse.params,
            "identifiants": reponse.identifiants,
            "noms": _mots(autorisation, MATIERE_NOMS_VALIDES,
                          [str(role.get("name") or "") for role in roles])}


def _roles_en_sur_octroi(contexte, autorisation, arguments) -> Dict[str, Any]:
    reponse = _calcul_de_l_agent("roles_en_sur_octroi")(contexte.loader, contexte.kb, "")
    return {**reponse.params, "identifiants": reponse.identifiants}


def _roles_sans_reference(contexte, autorisation, arguments) -> Dict[str, Any]:
    reponse = _calcul_de_l_agent("roles_sans_reference")(contexte.loader, contexte.kb, "")
    return {**reponse.params, "identifiants": reponse.identifiants}


def _le_socle(contexte, autorisation, arguments) -> Dict[str, Any]:
    reponse = _calcul_de_l_agent("le_socle")(contexte.loader, contexte.kb, "")
    return {**reponse.params,
            "codes": _mots(autorisation, MATIERE_LIBELLES_DE_DROITS, reponse.identifiants)}


def _travail_en_attente(contexte, autorisation, arguments) -> Dict[str, Any]:
    reponse = _calcul_de_l_agent("travail_en_attente")(contexte.loader, contexte.kb, "")
    return dict(reponse.params)


def _conflits_de_separation(contexte, autorisation, arguments) -> Dict[str, Any]:
    """Les règles et leurs comptes, comme l'écran des conflits les affiche."""
    from src.api.routers.separation import _synthese

    synthese = _synthese(contexte.loader, contexte.kb)
    libelles = autorisation.autorise(MATIERE_REGLES_DE_SEPARATION)
    regles = []
    for regle in synthese["regles"][:ELEMENTS_MAX]:
        ligne = {cle: regle[cle] for cle in ("regle", "applicable", "identites",
                                             "par_les_roles", "hors_role",
                                             "roles_en_conflit", "derogees")}
        if libelles:
            ligne.update({cle: regle[cle] for cle in ("libelle", "processus", "severite")})
        regles.append(ligne)
    return {"regles": regles,
            "identites_en_conflit": synthese["identites_en_conflit"],
            "identites_derogees": synthese["identites_derogees"],
            "population": synthese["population"]}


#: Les outils, dans l'ordre où l'agent les découvre. Chacun : son schéma
#: d'arguments et son calcul. La description vient du catalogue de traduction.
OUTILS: Dict[str, Tuple[Dict[str, Any], Callable]] = {
    "kovex_catalogue_des_roles": (_schema(), _catalogue),
    "kovex_porteurs_d_un_role": (_schema(role="role"), _porteurs_du_role),
    "kovex_droits_d_un_role": (_schema(role="role"), _droits_du_role),
    "kovex_detenteurs_d_un_droit": (_schema(droit="droit"), _detenteurs_du_droit),
    "kovex_roles_en_sur_octroi": (_schema(), _roles_en_sur_octroi),
    "kovex_roles_sans_reference": (_schema(), _roles_sans_reference),
    "kovex_socle": (_schema(), _le_socle),
    "kovex_conflits_de_separation": (_schema(), _conflits_de_separation),
    "kovex_travail_en_attente": (_schema(), _travail_en_attente),
}


# --------------------------------------------------------------- le protocole


class Contexte:
    """Les données et la base du workspace actif, relues à chaque appel.

    Relues et non gardées : un agent reste branché des heures, et un chiffre
    lu au démarrage serait faux dès le premier import.
    """

    @property
    def loader(self):
        from src.api.dependencies import get_data_loader

        return get_data_loader()

    @property
    def kb(self):
        from src.api.dependencies import get_kb

        return get_kb()


class ServeurMcp:
    """Traite un message JSON-RPC et rend la réponse, ou rien pour une notification."""

    def __init__(self, langue: str, contexte: Optional[Contexte] = None,
                 journal: Optional[Callable[[], Any]] = None) -> None:
        self.langue = langue
        self.contexte = contexte or Contexte()
        self.journal = journal or _journal_du_processus

    def traduire(self, cle: str, **parametres) -> str:
        from src.infrastructure.i18n_manager import i18n

        return i18n.t(cle, locale=self.langue, **parametres)

    # -- la boucle -----------------------------------------------------------

    def servir(self, entree: TextIO, sortie: TextIO) -> None:
        """Une ligne, un message ; une ligne, une réponse. Jusqu'à la fin de l'entrée."""
        for ligne in entree:
            if not ligne.strip():
                continue
            reponse = self.traiter_la_ligne(ligne)
            if reponse is not None:
                sortie.write(json.dumps(reponse, ensure_ascii=False) + "\n")
                sortie.flush()

    def traiter_la_ligne(self, ligne: str) -> Optional[Dict[str, Any]]:
        try:
            message = json.loads(ligne)
        except ValueError:
            return _erreur(None, ERREUR_LECTURE, self.traduire("mcp.erreur.lecture"))
        return self.traiter(message)

    def traiter(self, message: Any) -> Optional[Dict[str, Any]]:
        if (not isinstance(message, Mapping) or message.get("jsonrpc") != "2.0"
                or not isinstance(message.get("method"), str)):
            return _erreur(message.get("id") if isinstance(message, Mapping) else None,
                           ERREUR_REQUETE, self.traduire("mcp.erreur.requete"))
        identifiant = message.get("id")
        methode = message["method"]
        parametres = message.get("params") or {}
        if "id" not in message:
            # Une notification n'attend pas de réponse — `initialized`,
            # `cancelled` : il n'y a rien à annuler, tout est synchrone.
            return None
        if methode == "initialize":
            return _resultat(identifiant, self.initialiser(parametres))
        if methode == "ping":
            return _resultat(identifiant, {})
        if methode == "tools/list":
            return _resultat(identifiant, {"tools": self.lister()})
        if methode == "tools/call":
            return self.appeler(identifiant, parametres)
        return _erreur(identifiant, ERREUR_METHODE,
                       self.traduire("mcp.erreur.methode", methode=methode))

    def initialiser(self, parametres: Mapping[str, Any]) -> Dict[str, Any]:
        demandee = parametres.get("protocolVersion") if isinstance(parametres, Mapping) else None
        version = demandee if demandee in VERSIONS_DU_PROTOCOLE else VERSIONS_DU_PROTOCOLE[0]
        return {"protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": NOM_PRODUIT, "version": VERSION_PRODUIT},
                "instructions": self.traduire("mcp.instructions")}

    def lister(self) -> List[Dict[str, Any]]:
        return [{"name": nom, "description": self.traduire(f"mcp.outil.{nom}"),
                 "inputSchema": schema,
                 # Aucun outil n'écrit : l'agent peut les appeler sans demander.
                 "annotations": {"readOnlyHint": True, "openWorldHint": False}}
                for nom, (schema, _) in OUTILS.items()]

    def appeler(self, identifiant: Any, parametres: Any) -> Dict[str, Any]:
        if not isinstance(parametres, Mapping) or parametres.get("name") not in OUTILS:
            nom = parametres.get("name") if isinstance(parametres, Mapping) else None
            return _erreur(identifiant, ERREUR_PARAMETRES,
                           self.traduire("mcp.erreur.outil_inconnu", outil=str(nom)))
        nom = parametres["name"]
        schema, calcul = OUTILS[nom]
        arguments = parametres.get("arguments") or {}
        attendus = set(schema["properties"])
        if (not isinstance(arguments, Mapping) or set(arguments) != attendus
                or any(not isinstance(valeur, str) or not valeur or len(valeur) > ARGUMENT_MAX
                       for valeur in arguments.values())):
            return _erreur(identifiant, ERREUR_PARAMETRES,
                           self.traduire("mcp.erreur.arguments", outil=nom))
        try:
            corps = self.repondre(nom, calcul, arguments)
        except RefusDeL_Outil as refus:
            return _resultat(identifiant, {"content": [{"type": "text", "text": str(refus)}],
                                           "isError": True})
        return _resultat(identifiant, {
            "content": [{"type": "text", "text": json.dumps(corps, ensure_ascii=False)}],
            "structuredContent": corps, "isError": False})

    def repondre(self, nom: str, calcul: Callable, arguments: Mapping[str, str]) -> Dict[str, Any]:
        loader = self.contexte.loader
        autorisation = loader.config.assistance.pour(USAGE_SERVEUR_MCP.code)
        if not autorisation.actif:
            raise RefusDeL_Outil(self.traduire("mcp.ferme"))
        corps = calcul(self.contexte, autorisation, arguments)
        # Les mots qui ne sont pas sortis se disent : une liste absente n'est
        # pas une liste vide, et l'agent doit pouvoir l'expliquer.
        corps["matiere_fermee"] = sorted(
            matiere for matiere in USAGE_SERVEUR_MCP.facultatives
            if not autorisation.autorise(matiere))
        self.journal().consigner(
            Action.ASSISTANCE_CONSULTEE, "mcp", nom,
            {"usage": USAGE_SERVEUR_MCP.code, "outil": nom,
             "categories": ", ".join(autorisation.matiere_effective),
             "hors_du_poste": True})
        return corps


def _resultat(identifiant: Any, resultat: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": identifiant, "result": resultat}


def _erreur(identifiant: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": identifiant, "error": {"code": code, "message": message}}


def _journal_du_processus():
    """La piste d'audit, au nom du compte système qui a lancé le serveur.

    Pas de jeton ici : le serveur est lancé par un agent local, sous un compte
    du poste. C'est ce compte qui répond de ce qui est sorti.
    """
    from src.api.journal import Journal, _workspace_actif
    from src.core.audit.piste_audit import get_piste_audit

    return Journal(get_piste_audit(), f"mcp:{getpass.getuser()}", _workspace_actif())


def main(arguments: Optional[List[str]] = None, entree: TextIO = sys.stdin,
         sortie: TextIO = sys.stdout) -> int:
    analyseur = argparse.ArgumentParser(prog="python -m src.mcp.serveur")
    analyseur.add_argument("--langue", required=True,
                           help="langue des descriptions et des messages (fr, en, de)")
    analyseur.add_argument("--racine", required=True,
                           help="dossier d'installation de Kovex (celui qui contient workspaces/)")
    options = analyseur.parse_args(arguments)
    # Un agent lance le serveur depuis son propre dossier, pas depuis celui de
    # Kovex : sans ce changement, le workspace actif serait introuvable et
    # chaque outil répondrait sur un référentiel vide.
    os.chdir(options.racine)
    # La sortie standard est le canal du protocole : un seul journal écrit
    # dessus corromprait la conversation. Tout ce qui se journalise part sur
    # l'erreur standard.
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    for gestionnaire in list(logging.getLogger().handlers):
        if getattr(gestionnaire, "stream", None) is sys.stdout:
            gestionnaire.setStream(sys.stderr)
    ServeurMcp(options.langue).servir(entree, sortie)
    return 0


if __name__ == "__main__":  # pragma: no cover - point d'entrée du processus
    sys.exit(main())
