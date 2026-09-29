# Fichier : src/core/knowledge/derive.py
"""Ce que le catalogue est devenu depuis qu'on l'a validé.

Un rôle est une règle, et une règle vieillit avec les données. Six mois après,
la population qu'elle désigne a changé, les droits que ses membres détiennent
aussi — et rien dans le produit ne le disait. Le catalogue restait affiché comme
au premier jour, avec les chiffres du jour de la décision.

C'est ce qui manque pour que Kovex serve en gouvernance récurrente plutôt qu'en
projet : aujourd'hui, rien n'incite personne à rouvrir l'outil six mois plus
tard.

**L'ancre existe déjà.** `enregistrer_decision` conserve les chiffres que la
personne avait sous les yeux au moment de décider — effectif, droits, sur-octroi,
adhérence. La dérive est la comparaison de ces mêmes chiffres, recalculés
aujourd'hui, avec ceux-là. Rien de nouveau à stocker.

**Ce module ne modifie rien.** Il constate. Un rôle validé est une décision de
gouvernance, et il a peut-être déjà été provisionné dans l'IGA du client :
aucune correction ne s'applique sans un geste humain, et ce geste appartient à un
autre lot.

**Un rôle composé à la main n'a pas d'indicateurs** — la classe qui les porte le
dit explicitement, leur présence distingue une décision sur un candidat du mining
d'une composition manuelle. Sa dérive se mesure alors sans point de départ : on
rend ses chiffres du jour, sans écart, et l'écran dit pourquoi il n'y en a pas.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

#: Écart relatif, en pourcentage, au-delà duquel un constat est levé. Ce n'est
#: pas une valeur métier — c'est le bruit en dessous duquel un référentiel
#: bouge sans que cela veuille dire quoi que ce soit — mais il se règle : un
#: référentiel de trois cents identités et un de trois cent mille ne bougent pas
#: à la même échelle.
ECART_SIGNIFICATIF_PCT = 20.0

#: Recouvrement, en pourcentage, à partir duquel deux rôles validés sont
#: signalés comme faisant double emploi.
RECOUVREMENT_PCT = 80.0

#: Adhérence, en pourcentage, en dessous de laquelle un droit du rôle est
#: proposé au retrait. Ce n'est pas une règle : un rôle peut légitimement
#: accorder ce que ses membres n'ont pas encore — c'est même le propre d'un
#: modèle qui harmonise. La proposition rend les deux lectures, et la personne
#: tranche.
ADHERENCE_MINIMALE_PCT = 80.0


#: Types de proposition. Ce sont des codes, pas des phrases : le serveur ne
#: connaît pas la langue de celui qui les lira.
RESTREINDRE = "restreindre"
ELARGIR = "elargir"
FUSIONNER = "fusionner"
RETIRER = "retirer"

#: Les propositions que l'écran peut appliquer.
#:
#: Les quatre le sont désormais. Retirer et fusionner font disparaître un rôle
#: du catalogue — un rôle qui a peut-être déjà été provisionné dans l'IGA du
#: client. Ce geste a d'abord été laissé de côté faute d'une réponse à *que
#: devient un rôle dévalidé ?*. La réponse est posée : il sort du catalogue,
#: reste consultable avec son motif, et le candidat dont il venait redevient à
#: décider. Rien n'est effacé, et rien ne s'applique sans un geste humain.
APPLICABLES = frozenset({RESTREINDRE, ELARGIR, FUSIONNER, RETIRER})


@dataclass(frozen=True)
class Constat:
    """Une observation sur un rôle validé, avec les deux chiffres qui la font.

    `avant` et `apres` sont rendus ensemble et jamais séparément : un constat
    qui annoncerait « la population a baissé » sans dire de combien à combien
    n'est pas actionnable, et c'est le reproche que ce produit fait aux outils
    du marché.
    """

    code: str
    role_id: str
    role_nom: str
    avant: Optional[float] = None
    apres: Optional[float] = None
    parametres: Dict[str, Any] = field(default_factory=dict)

    def en_document(self) -> Dict[str, Any]:
        return {"code": self.code, "role_id": self.role_id, "role_nom": self.role_nom,
                "avant": self.avant, "apres": self.apres,
                "parametres": dict(self.parametres)}


@dataclass(frozen=True)
class Proposition:
    """Ce qu'on pourrait faire du constat — jamais ce que le produit fait.

    Une proposition porte, comme un constat, **les deux chiffres de la
    grandeur qu'elle déplace** : proposer de restreindre un rôle sans dire ce
    que le sur-octroi deviendrait, c'est demander une décision à l'aveugle.

    L'empreinte est ce qui rend l'application vérifiable. Le client renvoie
    l'empreinte de la proposition qu'il a vue ; le serveur recalcule la revue
    et n'applique que s'il retrouve la même. Une charge forgée ne peut donc pas
    faire modifier un rôle validé par une route d'analyse.
    """

    type: str
    role_id: str
    role_nom: str
    constat: str
    avant: Optional[float] = None
    apres: Optional[float] = None
    droits: Tuple[str, ...] = ()
    autre_role_id: str = ""
    parametres: Dict[str, Any] = field(default_factory=dict)

    @property
    def applicable(self) -> bool:
        return self.type in APPLICABLES

    def empreinte(self) -> str:
        """Identifiant stable de ce que la proposition ferait.

        Il ne porte que ce qui a un effet — le type, le rôle, les droits, le
        rôle associé — et non les chiffres affichés : ceux-ci bougent avec les
        données, et une empreinte qui changerait à chaque import rendrait toute
        application impossible dès que le référentiel bouge d'une ligne.
        """
        matiere = json.dumps(
            [self.type, self.role_id, sorted(self.droits), self.autre_role_id],
            ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(matiere.encode("utf-8")).hexdigest()[:32]

    def en_document(self) -> Dict[str, Any]:
        return {"code": f"revue.proposition.{self.type}", "type": self.type,
                "role_id": self.role_id, "role_nom": self.role_nom,
                "constat": self.constat, "applicable": self.applicable,
                "avant": self.avant, "apres": self.apres,
                "droits": list(self.droits), "autre_role_id": self.autre_role_id,
                "empreinte": self.empreinte(), "parametres": dict(self.parametres)}


def _ecart_relatif(avant: Optional[float], apres: Optional[float]) -> Optional[float]:
    """Variation en pourcentage, ou `None` quand elle n'a pas de sens.

    Partir de zéro n'a pas de variation relative : le dire en pourcentage
    donnerait l'infini, et l'afficher donnerait un constat illisible.
    """
    if avant is None or apres is None or not avant:
        return None
    return round(100.0 * (apres - avant) / avant, 1)


def mesurer_aujourdhui(role: Mapping[str, Any],
                       membres: Set[str],
                       droits_par_identite: Mapping[str, Set[str]]) -> Dict[str, Any]:
    """Les chiffres du rôle, sur les données du jour.

    Mêmes définitions que celles enregistrées au moment de la décision, sans
    quoi la comparaison opposerait deux grandeurs différentes — ce qui est
    exactement l'erreur que le produit s'interdit ailleurs.
    """
    droits = {str(droit) for droit in (role.get("rights") or ())}
    effectif = len(membres)
    detenus = 0
    for membre in membres:
        detenus += len(droits & droits_par_identite.get(membre, set()))
    accorde = effectif * len(droits)
    return {
        "user_count": effectif,
        "right_count": len(droits),
        "over_granted": accorde - detenus,
        "fit_pct": round(100.0 * detenus / accorde, 1) if accorde else 0.0,
    }


def _constats_du_role(role: Mapping[str, Any],
                      avant: Mapping[str, Any],
                      apres: Mapping[str, Any],
                      effectif_minimal: int,
                      ecart_significatif: float) -> List[Constat]:
    identifiant = str(role.get("id") or "")
    nom = str(role.get("name") or "")
    constats: List[Constat] = []

    ecart = _ecart_relatif(avant.get("user_count"), apres.get("user_count"))
    if ecart is not None and abs(ecart) >= ecart_significatif:
        # Perdue ou gagnée : ce ne sont pas les mêmes suites. Une population
        # qui fond fait perdre au rôle sa raison d'être ; une population qui
        # grossit lui fait accorder des droits à des gens qui ne les ont pas.
        constats.append(Constat(
            code=("revue.constat.population_perdue" if ecart < 0
                  else "revue.constat.population_gagnee"),
            role_id=identifiant, role_nom=nom,
            avant=avant.get("user_count"), apres=apres.get("user_count"),
            parametres={"ecart": abs(ecart)}))

    # Sous l'effectif minimal du workspace, le rôle ne serait plus proposé
    # aujourd'hui. Ce n'est pas une erreur — c'est une décision à reprendre.
    if (effectif_minimal and apres.get("user_count") is not None
            and apres["user_count"] < effectif_minimal):
        constats.append(Constat(
            code="revue.constat.sous_le_seuil", role_id=identifiant, role_nom=nom,
            avant=avant.get("user_count"), apres=apres["user_count"],
            parametres={"seuil": effectif_minimal}))

    ecart_cout = _ecart_relatif(avant.get("over_granted"), apres.get("over_granted"))
    if ecart_cout is not None and ecart_cout >= ecart_significatif:
        constats.append(Constat(
            code="revue.constat.sur_octroi_augmente", role_id=identifiant, role_nom=nom,
            avant=avant.get("over_granted"), apres=apres.get("over_granted"),
            parametres={"ecart": ecart_cout}))
    elif (avant.get("over_granted") in (0, None)
          and apres.get("over_granted", 0) > 0):
        # Passer de zéro à quelque chose n'a pas d'écart relatif, et c'est
        # pourtant le cas le plus net : le rôle n'accordait rien en trop.
        constats.append(Constat(
            code="revue.constat.sur_octroi_apparu", role_id=identifiant, role_nom=nom,
            avant=avant.get("over_granted"), apres=apres["over_granted"]))

    return constats


def _adherence_par_droit(droits: Set[str], membres: Set[str],
                         droits_par_identite: Mapping[str, Set[str]]
                         ) -> Dict[str, float]:
    """Part des membres qui détiennent réellement chaque droit du rôle.

    L'appelant garantit une population non vide : un rôle sans membre n'a pas
    d'adhérence, et le cas est écarté avant plutôt que rattrapé ici.
    """
    return {droit: 100.0 * sum(1 for membre in membres
                               if droit in droits_par_identite.get(membre, set()))
            / len(membres)
            for droit in droits}


def _droits_communs(membres: Set[str],
                    droits_par_identite: Mapping[str, Set[str]]) -> Set[str]:
    """Droits que **tous** les membres détiennent aujourd'hui.

    Sur un rôle sans membre, l'intersection d'aucun ensemble vaudrait tout le
    référentiel : le cas est écarté avant, pas rattrapé après.
    """
    if not membres:
        return set()
    commun: Optional[Set[str]] = None
    for membre in membres:
        detenus = droits_par_identite.get(membre, set())
        commun = set(detenus) if commun is None else (commun & detenus)
        if not commun:
            break
    return commun or set()


def _octroyes_par_ailleurs(role_id: str, membres: Set[str],
                           roles_valides: Sequence[Mapping[str, Any]],
                           membres_par_role: Mapping[str, Set[str]]) -> Set[str]:
    """Droits qu'un **autre** rôle validé octroie déjà à tous ces membres.

    C'est la règle du modèle acquis, appliquée ici pour la même raison qu'au
    mining : proposer d'ajouter à un rôle un droit que le catalogue donne déjà
    à toute sa population recréerait le défaut corrigé au lot 36 — le droit MFA
    remis dans un rôle de direction alors que les rôles Interne et Externe le
    portent déjà.
    """
    octroyes: Set[str] = set()
    if not membres:
        return octroyes
    for autre in roles_valides:
        identifiant = str(autre.get("id") or "")
        if identifiant == role_id:
            continue
        if membres <= membres_par_role.get(identifiant, set()):
            octroyes |= {str(droit) for droit in (autre.get("rights") or ())}
    return octroyes


def _couples(role_id: str, roles_valides: Sequence[Mapping[str, Any]],
             membres_par_role: Mapping[str, Set[str]]) -> int:
    """Nombre de couples (identité, droit) qu'un rôle porte aujourd'hui."""
    role = next((candidat for candidat in roles_valides
                 if str(candidat.get("id") or "") == role_id), None)
    if role is None:
        return 0
    return len(role.get("rights") or ()) * len(membres_par_role.get(role_id, ()))


def _qui_survit(premier: str, second: str,
                membres_par_role: Mapping[str, Set[str]],
                roles_valides: Sequence[Mapping[str, Any]]) -> Tuple[str, str]:
    """Lequel des deux rôles reste, lequel est absorbé.

    Le plus large survit : c'est celui qui explique le plus, et absorber le
    petit dans le grand ajoute moins de droits à moins de monde que l'inverse.
    À égalité, l'ordre des identifiants tranche — il faut une règle, et une
    règle qui ne dépende pas de l'ordre de lecture.
    """
    poids_premier = _couples(premier, roles_valides, membres_par_role)
    poids_second = _couples(second, roles_valides, membres_par_role)
    if poids_premier > poids_second:
        return premier, second
    if poids_second > poids_premier:
        return second, premier
    return (premier, second) if premier <= second else (second, premier)


def _propositions_du_role(role: Mapping[str, Any], membres: Set[str],
                          droits_par_identite: Mapping[str, Set[str]],
                          apres: Mapping[str, Any],
                          codes: Sequence[str],
                          droits_communs: Tuple[str, ...],
                          roles_valides: Sequence[Mapping[str, Any]],
                          adherence_minimale: float) -> List[Proposition]:
    """Ce qu'on pourrait faire, rôle par rôle. Rien n'est appliqué ici.

    Chaque proposition est rattachée au constat qui la motive : sans constat,
    pas de proposition. Un produit qui suggérerait de retoucher un rôle que
    rien ne signale demanderait des décisions pour le plaisir d'en demander.
    """
    identifiant = str(role.get("id") or "")
    nom = str(role.get("name") or "")
    droits = {str(droit) for droit in (role.get("rights") or ())}
    propositions: List[Proposition] = []

    sur_octroi = next((code for code in codes
                       if code in ("revue.constat.sur_octroi_apparu",
                                   "revue.constat.sur_octroi_augmente")), "")
    if sur_octroi and membres:
        adherence = _adherence_par_droit(droits, membres, droits_par_identite)
        faibles = tuple(sorted(droit for droit, part in adherence.items()
                               if part < adherence_minimale))
        if faibles and len(faibles) < len(droits):
            # Ce que coûterait le rôle une fois ces droits retirés. Le calcul
            # ne suppose rien : il remesure le rôle amputé sur les mêmes
            # données que le rôle entier.
            restant = {"rights": sorted(droits - set(faibles))}
            propositions.append(Proposition(
                type=RESTREINDRE, role_id=identifiant, role_nom=nom,
                constat=sur_octroi, droits=faibles,
                avant=apres.get("over_granted"),
                apres=mesurer_aujourdhui(restant, membres,
                                         droits_par_identite)["over_granted"],
                parametres={"nombre": len(faibles),
                            "adherence": round(adherence_minimale, 1)}))

    if droits_communs:
        propositions.append(Proposition(
            type=ELARGIR, role_id=identifiant, role_nom=nom,
            constat="revue.constat.droits_communs_apparus", droits=droits_communs,
            avant=len(droits), apres=len(droits) + len(droits_communs),
            parametres={"nombre": len(droits_communs)}))

    if "revue.constat.sous_le_seuil" in codes:
        propositions.append(Proposition(
            type=RETIRER, role_id=identifiant, role_nom=nom,
            constat="revue.constat.sous_le_seuil",
            avant=len(roles_valides), apres=len(roles_valides) - 1))

    return propositions


def _recouvrements(roles: Sequence[Mapping[str, Any]],
                   membres_par_role: Mapping[str, Set[str]],
                   seuil: float) -> List[Constat]:
    """Rôles validés qui font désormais double emploi.

    Deux rôles peuvent avoir été validés sur des populations disjointes et se
    recouvrir aujourd'hui — une réorganisation suffit. Le recouvrement se
    mesure sur les couples (identité, droit) : deux rôles peuvent partager
    leurs membres sans partager leurs droits, et l'inverse.
    """
    couples: Dict[str, Set[tuple]] = {}
    for role in roles:
        identifiant = str(role.get("id") or "")
        droits = {str(droit) for droit in (role.get("rights") or ())}
        membres = membres_par_role.get(identifiant, set())
        if droits and membres:
            couples[identifiant] = {(membre, droit)
                                    for membre in membres for droit in droits}

    noms = {str(role.get("id") or ""): str(role.get("name") or "") for role in roles}
    constats: List[Constat] = []
    identifiants = sorted(couples)
    for rang, premier in enumerate(identifiants):
        for second in identifiants[rang + 1:]:
            commun = couples[premier] & couples[second]
            if not commun:
                continue
            # La part du plus petit des deux : c'est lui qui n'apporte
            # presque plus rien, et c'est de lui qu'on parle.
            plus_petit = min(len(couples[premier]), len(couples[second]))
            part = round(100.0 * len(commun) / plus_petit, 1)
            if part >= seuil:
                constats.append(Constat(
                    code="revue.constat.recouvrement", role_id=premier,
                    role_nom=noms[premier], apres=part,
                    parametres={"autre": noms[second], "autre_id": second}))
    return constats


def _signature_de_regle(role: Mapping[str, Any]) -> str:
    """La règle d'un rôle, sous une forme comparable.

    Un rôle métier est une règle d'attributs ; un rôle applicatif n'en a pas.
    La chaîne vide signifie « pas de règle », et deux absences ne se
    rapprochent jamais : tous les rôles applicatifs se ressembleraient.
    """
    attributs = role.get("source_attributes")
    if isinstance(attributs, Mapping) and attributs:
        return json.dumps({str(cle): str(valeur)
                           for cle, valeur in sorted(attributs.items())},
                          ensure_ascii=False, sort_keys=True)
    regle = str(role.get("rh_rule") or "").strip()
    return regle


def _doublons_structurels(roles: Sequence[Mapping[str, Any]]) -> List[Constat]:
    """Deux rôles que le recouvrement par couples ne peut pas voir.

    Le recouvrement se mesure sur les couples (identité, droit), et c'est la
    bonne mesure pour « ces deux rôles font désormais double emploi ». Mais
    elle est **aveugle par construction** à deux formes de doublon, parce que
    dans les deux l'intersection des couples est vide :

    - **deux rôles portant la même règle.** Même population, droits
      différents : aucun couple commun. Relevé sur un catalogue réel, deux
      rôles portaient la règle `jobtitle = Médecin chef.fe de clinique` et
      accordaient des droits sans rapport. Ce n'est pas forcément une erreur —
      un socle et un accès applicatif peuvent coexister — mais personne ne
      devrait le découvrir en relisant le fichier.
    - **deux rôles accordant exactement les mêmes droits.** Droits identiques,
      populations disjointes : aucun couple commun non plus. Sur le même
      catalogue, deux grades de médecin recevaient les deux mêmes droits. Là
      encore, c'est le signe que la règle sépare ce que les droits ne séparent
      pas.

    L'égalité est **exacte**, sans seuil. Un seuil demanderait de justifier un
    chiffre ; l'égalité se constate, et le constat est incontestable.
    """
    par_regle: Dict[str, List[Mapping[str, Any]]] = {}
    par_droits: Dict[frozenset, List[Mapping[str, Any]]] = {}
    for role in roles:
        regle = _signature_de_regle(role)
        if regle:
            par_regle.setdefault(regle, []).append(role)
        droits = frozenset(str(droit) for droit in (role.get("rights") or ()))
        if droits:
            par_droits.setdefault(droits, []).append(role)

    constats: List[Constat] = []
    for code, groupes in (("revue.constat.meme_regle", par_regle.values()),
                          ("revue.constat.memes_droits", par_droits.values())):
        for groupe in groupes:
            if len(groupe) < 2:
                continue
            # Un constat par rôle du groupe, et non un par couple : à cinq
            # rôles identiques, dix constats diraient dix fois la même chose.
            ordonne = sorted(groupe, key=lambda r: str(r.get("name") or ""))
            for role in ordonne:
                autres = [str(autre.get("name") or "") for autre in ordonne
                          if autre is not role]
                constats.append(Constat(
                    code=code, role_id=str(role.get("id") or ""),
                    role_nom=str(role.get("name") or ""),
                    avant=None, apres=float(len(groupe)),
                    parametres={"autres": ", ".join(autres),
                                "autres_ids": ", ".join(
                                    str(autre.get("id") or "") for autre in ordonne
                                    if autre is not role)}))
    return constats


def analyser(roles_valides: Sequence[Mapping[str, Any]],
             membres_par_role: Mapping[str, Set[str]],
             droits_par_identite: Mapping[str, Set[str]],
             decisions: Sequence[Mapping[str, Any]],
             effectif_minimal: int = 0,
             ecart_significatif: float = ECART_SIGNIFICATIF_PCT,
             recouvrement: float = RECOUVREMENT_PCT,
             adherence_minimale: float = ADHERENCE_MINIMALE_PCT) -> Dict[str, Any]:
    """La revue du catalogue : ce que chaque rôle est devenu, et les constats.

    Les membres sont fournis par l'appelant plutôt que recalculés ici : c'est la
    même définition que le graphe et que le complément, et il n'en faut qu'une
    dans le produit.

    Chaque constat peut porter une **proposition typée**. Aucune n'est
    appliquée : ce module ne modifie rien, et l'application demande un geste
    humain explicite, sur une autre route.
    """
    indicateurs_par_role = {str(decision.get("role_id")): decision.get("indicateurs") or {}
                            for decision in decisions}
    dates = {str(decision.get("role_id")): decision.get("decided_at")
             for decision in decisions}

    revue: List[Dict[str, Any]] = []
    constats: List[Constat] = []
    propositions: List[Proposition] = []
    for role in roles_valides:
        identifiant = str(role.get("id") or "")
        nom = str(role.get("name") or "")
        droits = {str(droit) for droit in (role.get("rights") or ())}
        membres = membres_par_role.get(identifiant, set())
        apres = mesurer_aujourdhui(role, membres, droits_par_identite)
        avant = indicateurs_par_role.get(identifiant) or {}
        propres = _constats_du_role(role, avant, apres, effectif_minimal,
                                    ecart_significatif) if avant else []

        # Ce constat-ci ne demande pas de point de départ : c'est une
        # observation du jour, aussi vraie pour un rôle composé à la main que
        # pour un rôle issu du mining.
        communs = tuple(sorted(
            _droits_communs(membres, droits_par_identite) - droits
            - _octroyes_par_ailleurs(identifiant, membres, roles_valides,
                                     membres_par_role)))
        if communs:
            propres.append(Constat(
                code="revue.constat.droits_communs_apparus",
                role_id=identifiant, role_nom=nom,
                avant=len(droits), apres=len(communs)))

        constats.extend(propres)
        codes = [constat.code for constat in propres]
        propositions.extend(_propositions_du_role(
            role, membres, droits_par_identite, apres, codes, communs,
            roles_valides, adherence_minimale))

        revue.append({
            "role_id": identifiant,
            "role_nom": nom,
            "role_type": str(role.get("role_type") or ""),
            # Sans indicateurs, il n'y a pas d'écart à mesurer : le rôle a été
            # composé à la main. On rend ses chiffres du jour et l'écran le dit,
            # plutôt que d'inventer un point de départ.
            "compare": bool(avant),
            "decide_le": dates.get(identifiant),
            "version": int(role.get("version") or 1),
            "avant": dict(avant),
            "apres": apres,
            "constats": codes,
        })

    # Ceux-ci ne portent aucune proposition : le produit ne sait pas lequel des
    # deux rôles devrait disparaître, ni s'il doit en disparaître un. Deux
    # rôles de même règle peuvent être un socle et un accès applicatif ; deux
    # rôles de mêmes droits peuvent être deux grades qu'on tient à distinguer.
    # Le constat suffit, et il est incontestable.
    structurels = _doublons_structurels(roles_valides)
    constats.extend(structurels)
    par_role_structurel: Dict[str, List[str]] = {}
    for constat in structurels:
        par_role_structurel.setdefault(constat.role_id, []).append(constat.code)
    for entree in revue:
        entree["constats"].extend(par_role_structurel.get(entree["role_id"], ()))

    croises = _recouvrements(roles_valides, membres_par_role, recouvrement)
    constats.extend(croises)
    noms = {str(role.get("id") or ""): str(role.get("name") or "")
            for role in roles_valides}
    par_role = {entree["role_id"]: entree for entree in revue}
    for constat in croises:
        if constat.role_id in par_role:
            par_role[constat.role_id]["constats"].append(constat.code)
        # Fusionner fait disparaître un rôle : la proposition dit lequel.
        # « Fusionner A et B » sans dire lequel des deux survit demanderait de
        # décider sans savoir ce qu'on décide.
        autre_id = str(constat.parametres.get("autre_id") or "")
        survivant, absorbe = _qui_survit(constat.role_id, autre_id,
                                         membres_par_role, roles_valides)
        propositions.append(Proposition(
            type=FUSIONNER, role_id=constat.role_id, role_nom=constat.role_nom,
            constat=constat.code, autre_role_id=autre_id,
            avant=len(roles_valides), apres=len(roles_valides) - 1,
            parametres={"autre": constat.parametres.get("autre", ""),
                        "survivant": noms.get(survivant, survivant),
                        "survivant_id": survivant,
                        "absorbe": noms.get(absorbe, absorbe),
                        "absorbe_id": absorbe}))

    return {
        "roles": revue,
        "constats": [constat.en_document() for constat in constats],
        "propositions": [proposition.en_document() for proposition in propositions],
        "stats": {
            "roles_examines": len(revue),
            "roles_compares": sum(1 for entree in revue if entree["compare"]),
            "constats": len(constats),
            "roles_avec_constat": sum(1 for entree in revue if entree["constats"]),
            "propositions": len(propositions),
            "propositions_applicables": sum(
                1 for proposition in propositions if proposition.applicable),
        },
    }


def proposition_par_empreinte(revue: Mapping[str, Any],
                              empreinte: str) -> Optional[Dict[str, Any]]:
    """Retrouve, dans une revue recalculée, la proposition qu'on prétend appliquer.

    C'est le point de contrôle : le client renvoie une empreinte, jamais un
    ordre. Une charge forgée — retirer tel droit de tel rôle — ne correspond à
    aucune proposition recalculée et n'est donc pas appliquée.
    """
    for proposition in revue.get("propositions", ()):
        if proposition.get("empreinte") == empreinte:
            return proposition
    return None
