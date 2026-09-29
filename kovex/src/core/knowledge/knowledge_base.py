"""
PyGIA Knowledge Base System - VERSION CORRIGÉE SPRINT 0.1
Gestion centralisée de la mémoire système (décisions utilisateur, rôles validés, etc.)

CORRECTIONS:
- Ajout logs détaillés pour debug
- Validation stricte des données
- Vérification save effectif
"""

import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path
import logging
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
from datetime import datetime
import shutil

from src.core.knowledge import document_json
from src.core.knowledge.socle import IDENTIFIANT_SOCLE

logger = logging.getLogger(__name__)

#: Un verrou par fichier de Knowledge Base, partagé par toutes les instances.
#:
#: Chaque requête HTTP construit sa propre KnowledgeBase (elle est injectée par
#: dépendance) : le verrou ne peut donc pas être porté par l'instance. Il est
#: réentrant, une mutation pouvant en appeler une autre — `add_validated_role`
#: délègue à `update_validated_role` quand le rôle existe déjà.
#:
#: Un verrou de processus suffit : l'application tourne en un seul processus
#: (`run_api.py` ne configure aucun `workers`). Un verrou de fichier couvrirait
#: le multi-processus, au prix d'un code différent sous Windows et sous Linux,
#: pour un cas qui ne se présente pas aujourd'hui.
#: Nombre d'exécutions de mining conservées dans l'historique.
HISTORIQUE_MAXIMUM = 100

_VERROUS: Dict[str, threading.RLock] = {}
_VERROU_DES_VERROUS = threading.Lock()


def _verrou_de(chemin: Path) -> threading.RLock:
    cle = str(Path(chemin).resolve())
    with _VERROU_DES_VERROUS:
        if cle not in _VERROUS:
            _VERROUS[cle] = threading.RLock()
        return _VERROUS[cle]


class KnowledgeBase:
    """
    Base de connaissances JSON pour PyGIA.
    Stocke les décisions utilisateur et l'historique du mining.
    """
    
    def __init__(self, kb_path: str = "knowledge_base.json"):
        """
        Initialise la KB.
        
        Args:
            kb_path: Chemin vers le fichier JSON (relatif au workspace actif)
        """
        self.kb_path = Path(kb_path)
        self.data, created = self._load()
        if created:
            # La structure vide n'est ecrite qu'une fois self.data affecte :
            # l'appeler depuis _load() levait AttributeError et faisait echouer
            # tout appel de mining sur un workspace neuf.
            self.save()
        logger.debug("Knowledge Base chargée : %d rôles validés", len(self.data.get("validated_roles", [])))
    
    def _load(self) -> Tuple[Dict[str, Any], bool]:
        """Charge la KB depuis le disque, ou prépare une structure vide.

        Returns:
            (données, structure_vide_créée)
        """
        if not self.kb_path.exists():
            logger.info("Knowledge Base absente (%s) : création d'une base vide", self.kb_path)
            return self._create_empty_kb(), True

        try:
            # Le document n'est analysé que s'il a changé depuis la dernière
            # lecture. Soixante routes reconstruisent cet objet à chaque appel :
            # sans cela, chacune repayait l'analyse du fichier entier.
            brut = document_json.lire(self.kb_path, defaut=None)
            if brut is None:
                raise json.JSONDecodeError("document illisible", "", 0)
            return self._migrer(self._completer(brut)), False
        except json.JSONDecodeError as exc:
            # La KB porte les décisions de gouvernance de l'utilisateur : rôles
            # validés, rôles refusés, droits socles. On ne les écrase jamais en
            # silence, on met le fichier illisible de côté avant de repartir.
            backup = self.kb_path.with_suffix(
                f".corrupted-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
            )
            try:
                shutil.copy2(self.kb_path, backup)
                logger.error(
                    "Knowledge Base illisible (%s). Copie conservée dans %s, "
                    "une base vide est utilisée en attendant.", exc, backup
                )
            except OSError as copy_error:
                logger.error(
                    "Knowledge Base illisible (%s) et sauvegarde impossible (%s).",
                    exc, copy_error
                )
            return self._create_empty_kb(), True
    
    def _completer(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Ajoute les sections absentes d'une base écrite par une version
        antérieure.

        Sans cela, toute nouvelle section obligerait à migrer les bases
        existantes à la main, ou ferait échouer un accès direct comme
        `data["mining_runs"]`. Seules les clés manquantes sont posées : rien
        de ce que l'utilisateur a décidé n'est touché.
        """
        for cle, defaut in self._create_empty_kb().items():
            if cle not in data:
                data[cle] = defaut
        return data

    def _migrer(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Déplace hors du document ce qui n'y a plus sa place.

        Les candidats du dernier mining y ont vécu, et ils en faisaient
        l'essentiel : sur un workspace réel, 3,8 Mo sur 9,56. Ce ne sont pas des
        décisions de gouvernance — ils se recalculent —, et leur présence
        faisait payer à chaque lecture de la base le poids d'un résultat de
        calcul. Une base existante est migrée à sa première ouverture, sans que
        personne ait à s'en occuper.
        """
        candidats = data.pop("candidate_roles", None)
        if candidats:
            document_json.ecrire(self._chemin_des_candidats, candidats,
                                 indentation=None)
            logger.info("Candidats du mining déplacés hors de la base de "
                        "connaissance : %s", self._chemin_des_candidats.name)
            self.data = data
            self._ecrire()
        return data

    @property
    def _chemin_des_candidats(self) -> Path:
        """À côté de la base, dans le même workspace."""
        return self.kb_path.with_name("candidats.json")

    def _create_empty_kb(self) -> Dict[str, Any]:
        """Crée une structure KB vide."""
        return {
            "version": "1.0",
            "created_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "birth_rights": {
                "threshold": 90.0,
                "detected_at": None,
                "rights": [],
                # Nom du rôle socle, choisi par l'utilisateur. Vide tant que
                # personne n'a choisi : le produit n'en invente pas un.
                "name": "",
            },
            "validated_roles": [],
            "rejected_roles": [],
            "excluded_users": [],
            # Règles de périmètre : « ne garder que les actifs », « écarter les
            # prestataires ». Une règle se réévalue à chaque chargement, là où
            # la liste ci-dessus gèle des identifiants et dérive dès que le
            # référentiel change. Les deux coexistent : la liste pour
            # l'exception nominative, la règle pour une population.
            "perimeter_rules": [],
            # Règles de séparation des tâches : « créer un fournisseur » et
            # « payer une facture » ne vont pas ensemble. Aucune n'est livrée —
            # le produit ne connaît le contrôle interne d'aucun client, et une
            # bibliothèque toute faite donnerait à croire que le sujet est
            # couvert. C'est une décision de gouvernance, elle vit ici avec les
            # autres et non dans la configuration.
            "sod_rules": [],
            # Les exceptions assumées : ce constat-là est connu, accepté par
            # quelqu'un, pour cette raison, jusqu'à cette date. Sans elles, les
            # mêmes conflits reviennent à chaque chargement, l'écran se remplit
            # de ce qu'on a déjà tranché, et on cesse de le lire. Une
            # dérogation expirée n'est pas supprimée : elle raconte ce qui a
            # été décidé et quand cela a cessé de valoir.
            "derogations": [],
            # Les contrôles compensatoires, et chaque exécution consignée. Un
            # contrôle est ce qui rend une exception défendable ; ses
            # exécutions disent s'il compense encore. Aucune exécution n'est
            # supprimée : c'est une piste, pas un état.
            "controles": [],
            "executions_de_controle": [],
            "mining_runs": [],
            "data_snapshots": [],
            # Rôles sortis du catalogue : le rôle complet, la date, l'auteur
            # et le motif. Dévalider n'est pas supprimer — six mois plus tard,
            # quelqu'un demandera ce que contenait ce rôle et pourquoi il n'y
            # est plus.
            "devalidated_roles": [],
            # Date du dernier export du modèle : la borne à partir de
            # laquelle le prochain document dit ce qui a changé.
            "last_model_export": None,
            # Contexte des décisions de gouvernance : ce que la personne avait
            # sous les yeux au moment où elle a validé ou rejeté un candidat.
            # Sans cette trace, chaque décision est un exemple perdu, et un
            # modèle appris de l'historique repartirait de zéro le jour où on
            # l'écrit.
            "decisions": []
        }
    
    def save(self):
        """Écrit l'état mémoire sur disque, tel quel.

        À n'utiliser que pour poser un contenu voulu dans son intégralité — la
        création d'une base vide, une restauration de sauvegarde. Toute
        modification partielle passe par `_mutation()`, qui relit d'abord :
        écrire un instantané mémoire écrase les décisions prises entre-temps.
        """
        with _verrou_de(self.kb_path):
            self._ecrire()

    def _ecrire(self):
        """Écriture atomique : temporaire, remplacement, vérification."""
        self.data["last_updated"] = datetime.now().isoformat()

        try:
            # Le document reste indenté : il se lit et se corrige à la main, et
            # il est petit depuis que les candidats du mining vivent à côté.
            document_json.ecrire(self.kb_path, self.data, indentation=4)

            if not self.kb_path.exists():
                raise IOError("Sauvegarde échouée - fichier non créé")

            logger.debug(f" KB: Sauvegardée avec succès ({len(self.data.get('validated_roles', []))} rôles)")
            
        except Exception as e:
            logger.error(f" KB: Erreur sauvegarde - {e}")
            # Le fichier temporaire laissé par une écriture interrompue : il
            # porte le suffixe que pose l'écriture atomique.
            temporaire = self.kb_path.with_suffix(self.kb_path.suffix + ".tmp")
            if temporaire.exists():
                temporaire.unlink()
            raise
    
    @contextmanager
    def _mutation(self):
        """Relit le document, laisse appliquer l'opération, puis écrit.

        C'est la correction du défaut central de cette classe. Chaque mutation
        modifiait l'instantané mémoire chargé à la construction de l'objet, puis
        réécrivait **le document entier**. Une exécution de mining, qui charge
        la KB puis part plusieurs secondes en calcul, réécrivait à son retour
        l'état d'avant : toute validation ou tout rejet intervenu pendant le
        calcul disparaissait, sans erreur ni trace.

        Chaque opération travaille désormais sur le document frais et n'applique
        que la sienne. Corollaire à ne pas perdre de vue : une opération dont la
        cible a disparu entre-temps doit le constater — c'est pourquoi les
        mutations qui visent un identifiant précis vérifient sa présence à
        l'intérieur du bloc, et non avant.
        """
        with _verrou_de(self.kb_path):
            self.data, _ = self._load()
            yield self.data
            self._ecrire()

    # ========== DROITS SOCLES ==========
    
    def get_birth_rights(self) -> List[str]:
        """Retourne la liste des droits socles détectés."""
        return self.data["birth_rights"]["rights"]
    
    def get_birth_rights_info(self) -> Dict[str, Any]:
        """
        Retourne les infos complètes sur les droits socles.

        Returns:
            Dict avec threshold, detected_at, rights, count, name
        """
        br = self.data["birth_rights"]
        return {
            "threshold": br["threshold"],
            "detected_at": br["detected_at"],
            "rights": br["rights"],
            "count": len(br["rights"]),
            # Absent des bases antérieures au nom du socle : une base écrite
            # avant cette version se relit sans migration.
            "name": br.get("name", ""),
        }

    def set_birth_rights(self, rights: List[str], threshold: float = 90.0,
                         name: Optional[str] = None):
        """
        Enregistre les droits socles détectés.

        Args:
            rights: Liste des droits socles
            threshold: Seuil utilisé pour la détection
            name: Nom du rôle socle, choisi par l'utilisateur. `None` conserve
                celui qui est enregistré — relancer une détection ne doit pas
                effacer un nom que l'intégrateur a déjà reçu.
        """
        with self._mutation() as data:
            ancien_nom = data.get("birth_rights", {}).get("name", "")
            data["birth_rights"] = {
                "threshold": threshold,
                "detected_at": datetime.now().isoformat(),
                "rights": rights,
                "name": ancien_nom if name is None else str(name).strip(),
            }
        logger.info("Droits socles enregistrés : %d droits (seuil %.1f%%)", len(rights), threshold)

    def nommer_le_socle(self, name: str) -> str:
        """Donne au socle le nom sous lequel l'IGA le recevra.

        Le nom ne peut pas être écrit dans le code : « Socle commun » chez un
        client, « Droits d'accueil » chez un autre, et une convention de
        nommage imposée ailleurs. Le produit n'en propose donc aucun par
        défaut — il affiche un libellé traduit tant que personne n'a choisi.
        """
        propre = str(name or "").strip()
        with self._mutation() as data:
            data.setdefault("birth_rights",
                            {"threshold": 90.0, "detected_at": None, "rights": []})
            data["birth_rights"]["name"] = propre
        logger.info("Socle nommé : %r", propre)
        return propre
    
    def clear_birth_rights(self):
        """Efface les droits socles (pour relancer détection).

        Le nom reste : effacer une détection n'annule pas le choix de nommage,
        et le retrouver après une nouvelle détection évite de le ressaisir.
        """
        with self._mutation() as data:
            data["birth_rights"]["rights"] = []
            data["birth_rights"]["detected_at"] = None
        logger.info("Droits socles effacés")
    
    # ========== VALIDATED ROLES ==========
    
    def get_validated_roles(self, role_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retourne les rôles validés.
        
        Args:
            role_type: Filtrer par type ("APPLICATIF", "METIER", None=tous)
        
        Returns:
            Liste des rôles validés
        """
        roles = self.data["validated_roles"]
        
        if role_type:
            filtered = [r for r in roles if r.get("role_type") == role_type]
            logger.debug(f" KB: get_validated_roles(type={role_type}) → {len(filtered)} rôles")
            return filtered
        
        logger.debug(f" KB: get_validated_roles(type=ALL) → {len(roles)} rôles")
        return roles
    
    def get_role_by_id(self, role_id: str) -> Optional[Dict[str, Any]]:
        """
        Récupère un rôle validé par son ID.
        
        Args:
            role_id: ID du rôle à récupérer
        
        Returns:
            Dict contenant le rôle ou None si introuvable
        """
        for role in self.data["validated_roles"]:
            if role.get("id") == role_id:
                logger.debug(f" KB: get_role_by_id({role_id}) → TROUVÉ")
                return role
        
        logger.warning(f" KB: get_role_by_id({role_id}) → NON TROUVÉ")
        return None
    
    def add_validated_role(self, role: Dict[str, Any]):
        """
        Ajoute un rôle validé à la KB.
        
        Args:
            role: Dictionnaire contenant les infos du rôle
                  {id, name, description, role_type, rights, users, ...}
        """
        for champ in ("id", "name", "role_type", "rights"):
            if champ not in role:
                raise ValueError(f"Champ requis manquant: {champ}")

        # Le socle n'est pas un rôle enregistré : il se dérive de la décision
        # de détection. Un rôle validé portant son identifiant le recouvrirait
        # dans le catalogue et dans l'export, et les deux se disputeraient la
        # même ligne sans que rien ne le signale.
        if str(role["id"]) == IDENTIFIANT_SOCLE:
            raise ValueError(f"Identifiant réservé au socle : {IDENTIFIANT_SOCLE}")

        # La présence est vérifiée **dans** le bloc, sur le document frais : un
        # rôle validé entre-temps par quelqu'un d'autre doit être vu.
        with _verrou_de(self.kb_path):
            self.data, _ = self._load()
            if any(r.get("id") == role["id"] for r in self.data["validated_roles"]):
                logger.info("Rôle %s déjà validé : mise à jour", role["id"])
                self.update_validated_role(role["id"], role)
                return

            role["validated_at"] = datetime.now().isoformat()
            self.data["validated_roles"].append(role)
            self._ecrire()

        logger.info(
            "Rôle %s validé (%d rôles validés au total)",
            role["id"], len(self.data["validated_roles"]),
        )
        self._verify_save(role["id"])
    
    def _verify_save(self, role_id: str):
        """Vérifie qu'un rôle a bien été sauvegardé."""
        # Recharger depuis le disque
        with open(self.kb_path, 'r', encoding='utf-8') as f:
            saved_data = json.load(f)
        
        saved_ids = [r["id"] for r in saved_data.get("validated_roles", [])]
        if role_id in saved_ids:
            logger.debug(f" KB: Vérification OK - Rôle {role_id} bien persisté sur disque")
        else:
            logger.error(f" KB: ERREUR CRITIQUE - Rôle {role_id} PAS persisté sur disque !")
            raise RuntimeError(f"Sauvegarde échouée pour rôle {role_id}")
    
    def update_validated_role(self, role_id: str, updates: Dict[str, Any]):
        """
        Met à jour un rôle validé existant.
        
        Args:
            role_id: ID du rôle à mettre à jour
            updates: Dictionnaire des champs à mettre à jour
        """
        with self._mutation() as data:
            # Le rôle a pu être supprimé pendant qu'on préparait la mise à jour :
            # on le constate ici plutôt que de le ressusciter.
            cible = next((r for r in data["validated_roles"] if r.get("id") == role_id), None)
            if cible is None:
                raise ValueError(f"Rôle {role_id} introuvable dans validated_roles")
            cible.update(updates)
            cible["updated_at"] = datetime.now().isoformat()
        logger.info("Rôle %s mis à jour", role_id)
    
    def versionner_role(self, role_id: str, modifications: Dict[str, Any],
                        constat: str = "", auteur: str = "",
                        etat_des_donnees: str = "") -> Dict[str, Any]:
        """Modifie un rôle validé **en gardant sa version précédente**.

        Un rôle validé a peut-être déjà été provisionné dans l'IGA du client.
        Le remplacer en silence donnerait à l'intégrateur un rôle qu'il croit
        nouveau, et il en créerait un doublon. Le rôle garde donc son
        identifiant, gagne une version, et l'état d'avant est conservé avec sa
        date, son auteur et le constat qui a motivé le changement.

        C'est la raison concrète du versionnement : elle est opérationnelle,
        pas documentaire.

        La version précédente est enregistrée sans son propre historique — le
        document doublerait de taille à chaque modification.
        """
        with self._mutation() as data:
            cible = next((role for role in data["validated_roles"]
                          if role.get("id") == role_id), None)
            if cible is None:
                raise ValueError(f"Rôle {role_id} introuvable dans validated_roles")

            precedente = int(cible.get("version") or 1)
            historique = list(cible.get("versions") or [])
            instantane = {cle: valeur for cle, valeur in cible.items()
                          if cle != "versions"}
            instantane["version"] = precedente
            historique.append({
                "version": precedente,
                "role": instantane,
                "remplacee_le": datetime.now().isoformat(),
                "auteur": auteur,
                "constat": constat,
                "etat_des_donnees": etat_des_donnees,
            })

            cible.update(modifications)
            cible["version"] = precedente + 1
            cible["versions"] = historique
            cible["updated_at"] = datetime.now().isoformat()
            resultat = dict(cible)

        logger.info("Rôle %s versionné : %d → %d", role_id, precedente,
                    precedente + 1)
        return resultat

    def devalider_role(self, role_id: str, motif: str = "", constat: str = "",
                       auteur: str = "") -> Dict[str, Any]:
        """Sort un rôle du catalogue, sans effacer qu'il y a été.

        Dévalider n'est pas supprimer. Le rôle a peut-être été provisionné dans
        l'IGA du client ; six mois plus tard, quelqu'un demandera ce qu'il
        contenait et pourquoi il n'y est plus. Le rôle complet est donc
        conservé avec la date, l'auteur et le motif.

        **Le candidat correspondant redevient à décider.** La décision inverse
        est consignée sans l'identifiant du candidat : le porter le laisserait
        compté comme tranché, et le travail en attente annoncerait qu'il n'y a
        rien à faire sur un rôle qu'on vient justement de remettre en
        question.

        La décision de validation est remplacée par celle-ci. C'est voulu :
        l'historique sert à apprendre des décisions, et une validation sur
        laquelle on est revenu n'est pas un bon exemple — le retour, lui, en
        est un.
        """
        with self._mutation() as data:
            cible = next((role for role in data["validated_roles"]
                          if role.get("id") == role_id), None)
            if cible is None:
                raise ValueError(f"Rôle {role_id} introuvable dans validated_roles")

            data["validated_roles"] = [role for role in data["validated_roles"]
                                       if role.get("id") != role_id]
            data.setdefault("devalidated_roles", []).append({
                "role": dict(cible),
                "devalide_le": datetime.now().isoformat(),
                "auteur": auteur,
                "motif": motif,
                "constat": constat,
            })
            data["decisions"] = [decision for decision in data["decisions"]
                                 if decision.get("role_id") != role_id]
            data["decisions"].append({
                "role_id": role_id,
                "verdict": "devalidee",
                "motif": motif,
                "indicateurs": {},
                "decided_at": datetime.now().isoformat(),
            })

        logger.info("Rôle %s dévalidé", role_id)
        return cible

    def roles_devalides(self) -> List[Dict[str, Any]]:
        """Les rôles sortis du catalogue, du plus ancien au plus récent."""
        return self.data.get("devalidated_roles") or []

    def delete_validated_role(self, role_id: str):
        """
        Supprime un rôle validé.
        
        Args:
            role_id: ID du rôle à supprimer
        """
        with self._mutation() as data:
            avant = len(data["validated_roles"])
            data["validated_roles"] = [
                r for r in data["validated_roles"] if r.get("id") != role_id
            ]
            supprime = len(data["validated_roles"]) < avant

        if supprime:
            logger.info("Rôle %s supprimé", role_id)
        else:
            logger.warning("Rôle %s introuvable : rien à supprimer", role_id)
    
    # ========== REJECTED ROLES ==========
    
    # ========== DÉCISIONS ==========

    def enregistrer_decision(self, role_id: str, verdict: str,
                             indicateurs: Dict[str, Any],
                             motif: str = "", candidate_id: str = "") -> None:
        """Consigne le contexte d'une validation ou d'un rejet.

        La piste d'audit dit *qui* a décidé *quoi* et *quand* : c'est une
        exigence de gouvernance, et elle est tenue. Elle ne dit pas *sur quoi*
        la personne s'est appuyée. Ce sont ces chiffres-là — sur-octroi,
        redondance, fiabilité de la règle — qui font d'un historique de
        décisions une matière exploitable.

        On n'enregistre que des nombres et l'identifiant du rôle. Ni les
        porteurs, ni les valeurs d'attributs de la règle : ce serait recopier
        des données personnelles dans un fichier qui n'est pas fait pour ça, et
        qui s'exporte avec le workspace.

        Une décision déjà consignée pour ce rôle est remplacée : revenir sur un
        rejet ne doit pas laisser deux vérités contradictoires dans
        l'historique.

        Les indicateurs non renseignés ne sont pas écrits : un historique
        rempli de valeurs nulles se relit comme une mesure à zéro.

        `candidate_id` désigne le candidat tranché, quand la décision vient du
        mining. Une validation crée un rôle dont l'identifiant est neuf : rien
        ne reliait plus la décision au candidat dont elle vient, et il était
        donc impossible de dire ce qui restait à décider. Un rejet, lui, porte
        déjà sur l'identifiant du candidat. Ce champ met les deux au même
        niveau, sans nouveau stockage.
        """
        mesures = {cle: valeur for cle, valeur in (indicateurs or {}).items()
                   if valeur is not None}
        with self._mutation() as data:
            data["decisions"] = [
                enregistree for enregistree in data["decisions"]
                if enregistree.get("role_id") != role_id
            ]
            decision = {
                "role_id": role_id,
                "verdict": verdict,
                "motif": motif,
                "indicateurs": mesures,
                "decided_at": datetime.now().isoformat(),
            }
            if candidate_id:
                decision["candidate_id"] = candidate_id
            data["decisions"].append(decision)

    def candidats_tranches(self) -> Set[str]:
        """Identifiants de candidats sur lesquels une décision est prise.

        Un rejet inscrit l'identifiant du candidat dans `rejected_roles` ; une
        validation le consigne dans la décision. Les deux réunis disent ce qui
        ne reste plus à faire.
        """
        tranches = {str(identifiant) for identifiant in self.data.get("rejected_roles", [])}
        for decision in self.data.get("decisions", []):
            candidat = decision.get("candidate_id")
            if candidat:
                tranches.add(str(candidat))
        return tranches

    def decisions_par_candidat(self) -> Dict[str, Dict[str, Any]]:
        """Ce qu'un candidat est devenu : le verdict, et le rôle qui en est né.

        `candidats_tranches` dit *qu'une* décision existe ; celle-ci dit
        *laquelle*, et c'est ce qui manquait. Un candidat validé revenait dans
        les résultats du mining suivant, identique, sans que rien ne dise qu'il
        avait déjà donné un rôle du catalogue — et le nom proposé par défaut
        entrait alors en collision avec celui d'un rôle existant, découverte
        faite au moment d'enregistrer, après la relecture de centaines
        d'identités.

        La dernière décision l'emporte : un candidat peut avoir été refusé puis
        repris. Le nom du rôle est résolu ici, parce que la décision ne porte
        qu'un identifiant et qu'un identifiant ne se lit pas à l'écran.
        """
        noms = {str(role.get("id")): role.get("name", "")
                for role in self.get_validated_roles()}
        par_candidat: Dict[str, Dict[str, Any]] = {}
        for decision in self.data.get("decisions", []):
            candidat = decision.get("candidate_id")
            if not candidat:
                continue
            role_id = str(decision.get("role_id") or "")
            par_candidat[str(candidat)] = {
                "verdict": decision.get("verdict", ""),
                "role_id": role_id,
                # Vide quand le rôle a été dévalidé depuis : la décision reste
                # vraie, son produit n'est plus dans le catalogue, et l'écran
                # doit pouvoir dire les deux.
                "role_name": noms.get(role_id, ""),
                "decided_at": decision.get("decided_at", ""),
            }
        return par_candidat

    def noms_des_roles_valides(self, role_type: Optional[str] = None) -> List[str]:
        """Les noms du catalogue, pour qu'un écran puisse prévenir d'un doublon.

        Le serveur reste seul juge — il refuse un nom déjà pris, et deux
        onglets ouverts ne se voient pas l'un l'autre. Cette liste sert à
        **prévenir** l'utilisateur avant qu'il ne travaille, pas à décider à la
        place du serveur.
        """
        return [str(role.get("name", ""))
                for role in self.get_validated_roles(role_type=role_type)
                if role.get("name")]

    def exclure_de_l_apprentissage(self, role_id: str, exclue: bool) -> bool:
        """Retire une décision de l'apprentissage, ou l'y remet.

        La décision reste dans l'historique : on désapprend, on n'efface pas.
        Rend faux si aucune décision ne porte cet identifiant.
        """
        with self._mutation() as data:
            for decision in data["decisions"]:
                if decision.get("role_id") == role_id:
                    if exclue:
                        decision["exclue_de_l_apprentissage"] = True
                    else:
                        decision.pop("exclue_de_l_apprentissage", None)
                    return True
        return False

    def oublier_l_apprentissage(self) -> int:
        """Retire toutes les décisions présentes de l'apprentissage.

        Les décisions prises ensuite apprennent à nouveau : c'est la remise à
        zéro d'un projet dont les six premiers mois ne doivent plus peser.
        Rend le nombre de décisions nouvellement retirées.
        """
        retirees = 0
        with self._mutation() as data:
            for decision in data["decisions"]:
                if not decision.get("exclue_de_l_apprentissage"):
                    decision["exclue_de_l_apprentissage"] = True
                    retirees += 1
        return retirees

    def get_decisions(self) -> List[Dict[str, Any]]:
        """Historique des décisions, dans l'ordre où elles ont été prises."""
        return self.data["decisions"]

    # ========== REJECTED ROLES ==========

    def get_rejected_roles(self) -> List[str]:
        """Retourne la liste des IDs de rôles rejetés."""
        return self.data["rejected_roles"]
    
    def is_role_rejected(self, role_id: str) -> bool:
        """Vérifie si un rôle est dans la blacklist."""
        return role_id in self.data["rejected_roles"]
    
    def reject_role(self, role_id: str, reason: str = ""):
        """
        Ajoute un rôle à la blacklist.
        
        Args:
            role_id: ID du rôle à rejeter
            reason: Raison du rejet (optionnel)
        """
        with self._mutation() as data:
            if role_id in data["rejected_roles"]:
                logger.info("Rôle %s déjà rejeté", role_id)
                return
            data["rejected_roles"].append(role_id)
        logger.info("Rôle %s rejeté%s", role_id, f" ({reason})" if reason else "")
    
    def unreject_role(self, role_id: str):
        """Retire un rôle de la blacklist."""
        with self._mutation() as data:
            if role_id not in data["rejected_roles"]:
                return
            data["rejected_roles"].remove(role_id)
        logger.info("Rôle %s retiré des rôles rejetés", role_id)
    
    # ========== EXCLUDED USERS ==========
    
    def get_excluded_users(self) -> List[str]:
        """Retourne la liste des utilisateurs exclus."""
        return self.data["excluded_users"]
    
    def is_user_excluded(self, user_id: str) -> bool:
        """Vérifie si un utilisateur est exclu."""
        return user_id in self.data["excluded_users"]
    
    def exclude_user(self, user_id: str, reason: str = ""):
        """
        Ajoute un utilisateur à la liste d'exclusion.
        
        Args:
            user_id: ID de l'utilisateur à exclure
            reason: Raison de l'exclusion (optionnel)
        """
        with self._mutation() as data:
            if user_id in data["excluded_users"]:
                logger.info("Identité %s déjà exclue", user_id)
                return
            data["excluded_users"].append(user_id)
        logger.info("Identité %s exclue du périmètre%s", user_id,
                    f" ({reason})" if reason else "")
    
    def exclude_users(self, user_ids: List[str], reason: str = "") -> List[str]:
        """Écarte plusieurs identités en une seule écriture.

        Le détail par groupe désigne parfois quelques centaines d'identités
        d'un coup. Les passer une par une ferait autant de relectures et de
        réécritures du document — et chacune est verrouillée : la base
        deviendrait lente au moment précis où l'on décide.

        Idempotente : une identité déjà écartée n'est pas dupliquée, et le motif
        de la première décision est conservé. Le remplacer effacerait la raison
        pour laquelle quelqu'un avait tranché, ce qu'une piste de gouvernance ne
        doit jamais faire.

        Returns:
            list: les identités effectivement ajoutées, dans l'ordre reçu. Vide
            si toutes l'étaient déjà — l'appelant a besoin de le savoir pour ne
            pas annoncer une décision qui n'a rien changé.
        """
        ajoutees: List[str] = []
        with self._mutation() as data:
            deja = set(data["excluded_users"])
            for identifiant in user_ids:
                if identifiant in deja:
                    continue
                deja.add(identifiant)
                ajoutees.append(identifiant)
            data["excluded_users"].extend(ajoutees)
        if ajoutees:
            logger.info("%d identité(s) écartée(s) du périmètre%s",
                        len(ajoutees), f" ({reason})" if reason else "")
        return ajoutees

    def unexclude_user(self, user_id: str):
        """Retire un utilisateur de la liste d'exclusion."""
        with self._mutation() as data:
            if user_id not in data["excluded_users"]:
                return
            data["excluded_users"].remove(user_id)
        logger.info("Identité %s réintégrée au périmètre", user_id)

    # ========== RÈGLES DE PÉRIMÈTRE ==========

    def get_perimeter_rules(self) -> List[Dict[str, Any]]:
        """Règles de périmètre, sous leur forme stockée."""
        return self.data["perimeter_rules"]

    def regles_perimetre(self) -> List[Any]:
        """Règles de périmètre validées, prêtes à être appliquées.

        Une règle devenue invalide — attribut vidé, plus aucune valeur — est
        **ignorée et signalée**, jamais appliquée de travers. Faire échouer
        chaque calcul sur une règle mal formée rendrait le produit inutilisable
        pour une décision de gouvernance qu'on peut simplement corriger.
        """
        from src.core.knowledge.perimetre import Regle

        valides = []
        for brut in self.data["perimeter_rules"]:
            try:
                valides.append(Regle.depuis_dict(brut))
            except ValueError as erreur:
                logger.warning("Règle de périmètre ignorée : %s", erreur)
        return valides

    def set_perimeter_rules(self, regles: List[Dict[str, Any]]):
        """Remplace les règles de périmètre par celles fournies.

        Un remplacement et non un ajout : l'écran rend l'état complet des
        règles, et un ajout laisserait sans moyen d'en retirer une.

        Raises:
            ValueError: une règle est mal formée. Ici on refuse — c'est une
                saisie, et une saisie fausse doit revenir à celui qui l'a faite
                plutôt que d'être rangée pour être ignorée plus tard.
        """
        from src.core.knowledge.perimetre import Regle

        for brut in regles:
            Regle.depuis_dict(brut)
        with self._mutation() as data:
            data["perimeter_rules"] = list(regles)
        logger.info("Périmètre : %d règle(s) enregistrée(s)", len(regles))
    
    # ========== SÉPARATION DES TÂCHES ==========

    def get_sod_rules(self) -> List[Dict[str, Any]]:
        """Règles de séparation, sous leur forme stockée."""
        return self.data["sod_rules"]

    def regles_separation(self) -> List[Any]:
        """Règles de séparation applicables.

        Une règle devenue illisible est **ignorée et signalée**, comme une
        règle de périmètre : faire échouer chaque écran sur une règle mal
        formée rendrait le produit inutilisable pour une décision qu'on peut
        corriger. La saisie, elle, refuse — c'est là que l'erreur doit revenir
        à celui qui l'a faite.
        """
        from src.core.knowledge.separation import regles_valides

        return regles_valides(self.data["sod_rules"])

    def set_sod_rules(self, regles: List[Dict[str, Any]]):
        """Remplace les règles de séparation par celles fournies.

        Un remplacement et non un ajout, pour la même raison que le périmètre :
        l'écran rend l'état complet, et un ajout laisserait sans moyen d'en
        retirer une.

        Raises:
            RegleInvalide: une règle est mal formée. Une règle de séparation
                qu'on croit active et qui ne calcule rien est le pire état
                possible de cette fonction — l'auditeur lit « aucun conflit »
                et conclut que tout va bien.
        """
        from src.core.knowledge.separation import Regle

        identifiants = set()
        for brut in regles:
            regle = Regle.depuis_dict(brut)
            if regle.identifiant in identifiants:
                from src.core.knowledge.separation import RegleInvalide
                raise RegleInvalide(
                    f"deux règles portent l'identifiant {regle.identifiant}")
            identifiants.add(regle.identifiant)
        with self._mutation() as data:
            data["sod_rules"] = list(regles)
        logger.info("Séparation des tâches : %d règle(s) enregistrée(s)",
                    len(regles))

    # ========== DÉROGATIONS ==========

    def derogations(self, reglages: Any = None) -> List[Any]:
        """Les dérogations lisibles, prêtes à être appliquées.

        Une dérogation illisible est ignorée et signalée. L'enjeu est ici
        l'inverse de d'habitude : l'écarter fait **réapparaître** un conflit,
        ce qui est le défaut sûr — on remontre quelque chose de déjà tranché,
        on ne cache rien.
        """
        from src.core.knowledge.derogations import derogations_valides

        return derogations_valides(self.data["derogations"], reglages)

    def accorder_une_derogation(self, brute: Dict[str, Any],
                                reglages: Any = None) -> Dict[str, Any]:
        """Ajoute une dérogation, après l'avoir validée.

        Un ajout et non un remplacement, contrairement aux règles : une
        dérogation est un acte daté, pas un état d'écran. Les remplacer en bloc
        ferait perdre celles qu'un autre poste vient d'accorder.

        Raises:
            DerogationInvalide: la saisie est refusée, et elle revient à celui
                qui l'a faite.
        """
        from src.core.knowledge.derogations import Derogation

        derogation = Derogation.depuis_dict(brute, reglages)
        with self._mutation() as data:
            deja = {une.get("id") for une in data["derogations"]}
            if derogation.identifiant in deja:
                from src.core.knowledge.derogations import DerogationInvalide
                raise DerogationInvalide(
                    f"une dérogation porte déjà l'identifiant "
                    f"{derogation.identifiant}")
            data["derogations"].append(derogation.en_dict())
        logger.info("Dérogation accordée : %s jusqu'au %s",
                    derogation.identifiant, derogation.echeance)
        return derogation.en_dict()

    def trancher_une_derogation(self, identifiant: str, accorder: bool,
                                par: str, le: Any, motif_de_refus: str = "",
                                reglages: Any = None) -> Optional[Dict[str, Any]]:
        """Approuve ou refuse une dérogation demandée.

        Celui qui tranche n'est **jamais** celui qui a demandé : une exception
        approuvée par la personne qui en profite ne sépare rien — c'est la
        règle même que la dérogation suspend. Une dérogation déjà tranchée ne
        se retranche pas : on la retire, et on en demande une autre.

        Returns:
            La dérogation tranchée, ou None si aucune ne porte cet identifiant.

        Raises:
            DerogationInvalide: elle n'est pas en attente, celui qui tranche
                est celui qui a demandé, ou un refus n'a pas de motif.
        """
        from src.core.knowledge.derogations import (ACCORDEE, DEMANDEE, REFUSEE,
                                                    Derogation,
                                                    DerogationInvalide)

        with self._mutation() as data:
            for rang, brute in enumerate(data["derogations"]):
                if brute.get("id") != identifiant:
                    continue
                derogation = Derogation.depuis_dict(brute, reglages)
                if derogation.statut != DEMANDEE:
                    raise DerogationInvalide(
                        f"la dérogation {identifiant} est déjà {derogation.statut}")
                if par.strip().casefold() == derogation.auteur.strip().casefold():
                    raise DerogationInvalide(
                        f"la dérogation {identifiant} ne peut pas être tranchée "
                        "par celui qui l'a demandée")
                motif = str(motif_de_refus or "").strip()
                if not accorder and not motif:
                    raise DerogationInvalide(
                        f"le refus de la dérogation {identifiant} n'a pas de motif")
                tranchee = {**derogation.en_dict(),
                            "statut": ACCORDEE if accorder else REFUSEE,
                            "decidee_par": par, "decidee_le": le.isoformat(),
                            "motif_de_refus": "" if accorder else motif}
                data["derogations"][rang] = Derogation.depuis_dict(
                    tranchee, reglages).en_dict()
                return data["derogations"][rang]
        return None

    def retirer_une_derogation(self, identifiant: str) -> bool:
        """Retire une dérogation avant son terme.

        C'est le seul cas où une dérogation disparaît du document. Retirer est
        une décision — on rend le constat à la liste des choses à traiter — là
        où expirer est le cours normal des choses, et laisse la trace.
        """
        with self._mutation() as data:
            restantes = [une for une in data["derogations"]
                         if une.get("id") != identifiant]
            retiree = len(restantes) != len(data["derogations"])
            data["derogations"] = restantes
        if retiree:
            logger.info("Dérogation retirée : %s", identifiant)
        return retiree

    # ========== CONTRÔLES COMPENSATOIRES ==========

    def controles(self) -> Dict[str, Any]:
        """Les contrôles lisibles, par identifiant."""
        from src.core.knowledge.controles import controles_valides

        return controles_valides(self.data["controles"])

    def executions_de_controle(self) -> List[Any]:
        """Toutes les exécutions lisibles, dans l'ordre de consignation."""
        from src.core.knowledge.controles import executions_valides

        return executions_valides(self.data["executions_de_controle"])

    def enregistrer_les_controles(self, bruts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remplace le catalogue des contrôles, après l'avoir validé.

        Un remplacement, comme les règles : l'écran rend le catalogue complet.
        Les exécutions, elles, ne sont jamais touchées — retirer un contrôle ne
        réécrit pas ce qui a été fait.

        Raises:
            ControleInvalide: un contrôle est mal formé, ou deux portent le
                même identifiant.
        """
        from src.core.knowledge.controles import Controle, ControleInvalide

        controles = [Controle.depuis_dict(brut) for brut in bruts]
        identifiants = [controle.identifiant for controle in controles]
        if len(set(identifiants)) != len(identifiants):
            raise ControleInvalide("deux contrôles portent le même identifiant")
        with self._mutation() as data:
            data["controles"] = [controle.en_dict() for controle in controles]
        return self.data["controles"]

    def consigner_une_execution(self, brute: Dict[str, Any]) -> Dict[str, Any]:
        """Ajoute une exécution, après l'avoir validée.

        Raises:
            ControleInvalide: l'exécution est mal formée, ou le contrôle
                qu'elle cite n'existe pas.
        """
        from src.core.knowledge.controles import ControleInvalide, Execution

        execution = Execution.depuis_dict(brute)
        if execution.controle not in self.controles():
            raise ControleInvalide(
                f"le contrôle {execution.controle} n'existe pas")
        with self._mutation() as data:
            data["executions_de_controle"].append(execution.en_dict())
        return execution.en_dict()

    # ========== MINING HISTORY ==========
    
    # ========== CANDIDATS DU DERNIER MINING ==========

    def set_candidate_roles(
        self,
        role_type: str,
        roles: List[Dict[str, Any]],
        params: Optional[Dict[str, Any]] = None,
        empreinte_donnees: str = "",
        stats: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Conserve les candidats du dernier mining d'un type.

        Un seul jeu par type, remplacé à chaque exécution. Conserver
        l'historique complet ferait grossir sans borne un document relu et
        réécrit intégralement à chaque décision de gouvernance : la base
        deviendrait lente au moment précis où elle sert le plus.

        Les paramètres et l'empreinte des données sont conservés avec les
        candidats. Sans eux, un rôle proposé n'est pas reproductible, et rien
        ne permet de dire s'il porte encore sur les données courantes.

        Les indicateurs du modèle le sont aussi. Ils ne se déduisent pas des
        rôles — couverture, sur-octroi et compression se calculent sur la
        population entière —, et les recalculer à la réouverture referait le
        travail long que l'utilisateur a déjà attendu. Sans eux, un résultat
        repris s'affiche amputé de tout ce qui permet de le juger.
        """
        with _verrou_de(self.kb_path):
            candidats = document_json.lire(self._chemin_des_candidats, defaut={})
            candidats[role_type] = {
                "roles": roles,
                "params": params or {},
                "stats": stats or {},
                "data_fingerprint": empreinte_donnees,
                "computed_at": datetime.now().isoformat(),
            }
            # Sans indentation : ce document ne se lit pas à la main, et
            # l'indentation y représentait plus de la moitié des octets.
            document_json.ecrire(self._chemin_des_candidats, candidats,
                                 indentation=None)
        logger.info("%d candidats conservés pour le mining %s", len(roles), role_type)

    def get_candidate_run(self, role_type: str) -> Optional[Dict[str, Any]]:
        """Dernier mining conservé d'un type, ou None."""
        # Sans copie : ce document est volumineux, et personne ne le modifie —
        # un jeu de candidats se remplace en entier, il ne se retouche pas.
        candidats = document_json.lire(self._chemin_des_candidats, defaut={},
                                       copie=False)
        return candidats.get(role_type)

    def get_candidate_roles(self, role_type: str) -> List[Dict[str, Any]]:
        run = self.get_candidate_run(role_type)
        return list(run.get("roles") or []) if run else []

    def nommer_les_candidats(self, role_type: str,
                             noms: Dict[str, Dict[str, str]]) -> int:
        """Inscrit sur les candidats conservés les noms retenus par quelqu'un.

        Nommer trois cents rôles est le poste le plus coûteux d'un projet de
        role mining — pas le calcul, la mise en mots. Ce travail se faisait
        jusqu'ici dans la page, et un rechargement le perdait en entier. Il
        est donc écrit là où le mining est déjà conservé.

        **Ce n'est pas une décision de gouvernance.** Un candidat nommé n'est
        ni validé ni refusé : il attend toujours qu'on décide de lui. Le nom
        est un brouillon, repris tel quel dans le formulaire de validation, et
        modifiable jusqu'au dernier moment.

        Rend le nombre de candidats effectivement touchés. Un identifiant
        inconnu est ignoré plutôt que créé : le jeu de candidats est le
        résultat d'un calcul, il ne s'enrichit pas par une écriture d'écran.
        """
        touches = 0
        with _verrou_de(self.kb_path):
            candidats = document_json.lire(self._chemin_des_candidats, defaut={})
            jeu = candidats.get(role_type)
            if not jeu:
                return 0
            for role in jeu.get("roles") or []:
                retenu = noms.get(str(role.get("id")))
                if not retenu:
                    continue
                role["name"] = retenu["name"]
                # La description n'est écrasée que si on en propose une : un
                # lot de nommage qui ne rendrait que des intitulés ne doit pas
                # effacer les descriptions déjà là.
                if retenu.get("description"):
                    role["description"] = retenu["description"]
                    # Le mining pose une clé de traduction plutôt qu'un texte.
                    # Laissée en place, elle gagnerait à l'affichage contre la
                    # description qu'on vient d'écrire.
                    role.pop("description_key", None)
                    role.pop("description_params", None)
                touches += 1
            if touches:
                document_json.ecrire(self._chemin_des_candidats, candidats,
                                     indentation=None)
        logger.info("%d candidats nommés pour le mining %s", touches, role_type)
        return touches

    def clear_candidate_roles(self, role_type: Optional[str] = None) -> None:
        """Oublie les candidats conservés, d'un type ou de tous."""
        with _verrou_de(self.kb_path):
            candidats = document_json.lire(self._chemin_des_candidats, defaut={})
            if role_type is None:
                candidats.clear()
            else:
                candidats.pop(role_type, None)
            document_json.ecrire(self._chemin_des_candidats, candidats,
                                 indentation=None)

    # ========== RAPPROCHEMENTS REFUSÉS ==========

    def refuser_le_rapprochement(self, referentiel: str, colonne: str,
                                 valeurs: Sequence[str], auteur: str = "") -> int:
        """Mémorise que ces valeurs ne désignent pas la même chose.

        `Cadre` et `Cadre de santé` sont proches et ne doivent pas fusionner.
        L'utilisateur ne doit avoir à le dire qu'une fois : sans mémoire, le
        repérage lui reproposerait la même grappe à chaque analyse, et il
        finirait par accepter par lassitude.

        Le refus est stocké comme des **paires** et non comme un groupe : c'est
        ce qui permet à une grappe de trois valeurs dont deux sont refusées de
        se scinder plutôt que de disparaître.

        Rend le nombre de paires nouvellement interdites.
        """
        propres = [str(valeur) for valeur in valeurs if str(valeur).strip()]
        if len(propres) < 2:
            return 0
        with self._mutation() as data:
            refus = data.setdefault("refused_pairs", [])
            connues = {(entree["referentiel"], entree["colonne"],
                        entree["valeurs"][0], entree["valeurs"][1])
                       for entree in refus}
            ajoutees = 0
            for rang, gauche in enumerate(propres):
                for droite in propres[rang + 1:]:
                    paire = tuple(sorted((gauche, droite)))
                    if (referentiel, colonne, paire[0], paire[1]) in connues:
                        continue
                    refus.append({
                        "referentiel": referentiel, "colonne": colonne,
                        "valeurs": list(paire), "auteur": auteur,
                        "refused_at": datetime.now().isoformat(),
                    })
                    connues.add((referentiel, colonne, paire[0], paire[1]))
                    ajoutees += 1
        logger.info("%d rapprochement(s) refusé(s) sur %s.%s", ajoutees,
                    referentiel, colonne)
        return ajoutees

    def rapprochements_refuses(self, referentiel: str,
                               colonne: str) -> List[Tuple[str, str]]:
        """Les paires que l'utilisateur a dites distinctes, pour cette colonne."""
        return [tuple(entree["valeurs"])
                for entree in self.data.get("refused_pairs", [])
                if entree.get("referentiel") == referentiel
                and entree.get("colonne") == colonne]

    # ========== VOLUMÉTRIE DU RÉFÉRENTIEL ==========

    def relever_volumetrie(self, volumes: Dict[str, int],
                           empreinte_donnees: str) -> bool:
        """Consigne la taille du référentiel, si elle porte sur d'autres données.

        Le tableau de bord affichait « +12 % » sous le nombre de droits. Le
        chiffre était écrit dans le gabarit : il ne mesurait rien, ne bougeait
        jamais, et se lisait pourtant comme une mesure. Sur un produit qui
        reproche aux autres d'afficher des chiffres qu'ils ne savent pas
        justifier, c'était le défaut le moins défendable.

        Mesurer une évolution demande deux relevés. Le produit n'en gardait
        aucun : les volumes se recomptaient à chaque chargement et l'état
        précédent disparaissait avec lui.

        Un relevé n'est ajouté que si l'empreinte des données diffère du
        dernier : recharger deux fois le même référentiel n'est pas un
        événement, et la liste se remplirait d'états identiques qui feraient
        conclure à une stabilité qu'on n'a pas observée.

        Returns:
            True si un relevé a été ajouté.
        """
        releves = self.data.get("data_snapshots") or []
        if releves and releves[-1].get("fingerprint") == empreinte_donnees:
            return False

        with self._mutation() as data:
            historique = data.setdefault("data_snapshots", [])
            historique.append({
                "recorded_at": datetime.now().isoformat(),
                "fingerprint": empreinte_donnees,
                **{cle: int(valeur) for cle, valeur in volumes.items()},
            })
            if len(historique) > HISTORIQUE_MAXIMUM:
                data["data_snapshots"] = historique[-HISTORIQUE_MAXIMUM:]
        logger.info("Volumétrie relevée : %s", volumes)
        return True

    def dernier_export(self) -> Optional[str]:
        """Horodatage du dernier export du modèle, ou None.

        Il sert à dire, au suivant, ce qui a changé depuis. Sans cela,
        l'intégrateur reçoit un rôle modifié qu'il croit nouveau et en crée un
        doublon dans l'IGA.
        """
        return self.data.get("last_model_export") or None

    def enregistrer_export(self) -> str:
        """Retient la date de cet export, pour que le suivant sache la borne.

        Un aperçu n'est pas un export : seul un document réellement produit
        déplace la borne, sinon le prochain document annoncerait « rien de
        changé » alors que rien n'est parti.
        """
        horodatage = datetime.now().isoformat()
        with self._mutation() as data:
            data["last_model_export"] = horodatage
        return horodatage

    def dernier_releve_de_donnees(self) -> Optional[Dict[str, Any]]:
        """Le dernier état connu du référentiel, ou None s'il n'y en a pas.

        Il date une modification de rôle : « ce rôle a changé le 3 mars, sur
        les données du 1er mars » se relit des années plus tard, là où la seule
        date de la décision laisse deviner sur quoi elle portait.
        """
        releves = self.data.get("data_snapshots") or []
        return dict(releves[-1]) if releves else None

    def evolution_du_referentiel(self) -> Optional[Dict[str, Any]]:
        """Écart entre les deux derniers relevés, ou None.

        None avec un seul relevé, et c'est le point : un produit qui ne peut
        pas comparer ne doit pas afficher de tendance. Il n'a rien à dire, il
        se tait.
        """
        releves = self.data.get("data_snapshots") or []
        if len(releves) < 2:
            return None

        avant, apres = releves[-2], releves[-1]
        compteurs = sorted(set(avant) | set(apres) - {"recorded_at", "fingerprint"})
        return {
            "since": avant.get("recorded_at"),
            "until": apres.get("recorded_at"),
            "counts": {cle: int(apres.get(cle, 0)) - int(avant.get(cle, 0))
                       for cle in compteurs
                       if cle not in ("recorded_at", "fingerprint")},
        }

    def add_mining_run(self, run_info: Dict[str, Any]):
        """
        Enregistre un run de mining dans l'historique.
        
        Args:
            run_info: {
                timestamp, type (applicatif/metier), 
                params, results_count, top_roles
            }
        """
        run_info["timestamp"] = datetime.now().isoformat()

        # C'est cette mutation qui détruisait le plus de décisions : elle
        # intervient à la fin d'un calcul long, et réécrivait l'instantané
        # chargé avant ce calcul.
        with self._mutation() as data:
            data["mining_runs"].append(run_info)
            if len(data["mining_runs"]) > HISTORIQUE_MAXIMUM:
                data["mining_runs"] = data["mining_runs"][-HISTORIQUE_MAXIMUM:]
        logger.info("Exécution de mining historisée (%s)", run_info.get("type"))
    
    def get_mining_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Retourne l'historique des runs de mining.
        
        Args:
            limit: Nombre max de runs à retourner
        
        Returns:
            Liste des runs (du plus récent au plus ancien)
        """
        return list(reversed(self.data["mining_runs"][-limit:]))
    
    # ========== UTILITY ==========
    
    def export_backup(self, backup_path: str):
        """Crée une copie de sauvegarde de la KB."""
        backup_path = Path(backup_path)
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.kb_path, backup_path)
        logger.debug(f" KB: Backup exporté vers {backup_path}")
    
    def import_backup(self, backup_path: str):
        """
        Restaure la KB depuis un backup.
        
        Args:
            backup_path: Chemin vers le fichier de backup
        
        Raises:
            FileNotFoundError: Si le backup n'existe pas
            json.JSONDecodeError: Si le backup est corrompu
        """
        backup_path = Path(backup_path)
        
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup introuvable : {backup_path}")
        
        logger.debug(f" KB: Restauration depuis {backup_path}")
        
        # Backup de sécurité de la KB actuelle
        current_backup = Path(f"backups/kb_before_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        current_backup.parent.mkdir(parents=True, exist_ok=True)
        self.export_backup(str(current_backup))
        logger.info(f"🔒 KB: Backup sécurité créé : {current_backup}")
        
        # Charger et valider le backup
        with open(backup_path, 'r', encoding='utf-8') as f:
            restored_data = json.load(f)
        
        # Vérifier structure minimale
        required_keys = ["version", "birth_rights", "validated_roles", "rejected_roles"]
        if not all(k in restored_data for k in required_keys):
            raise ValueError("Backup invalide : structure incorrecte")
        
        # Restauration : le contenu voulu remplace l'existant dans son
        # intégralité. C'est l'un des deux seuls cas où l'écriture directe est
        # la bonne opération.
        with _verrou_de(self.kb_path):
            self.data = restored_data
            self._ecrire()
        logger.info("Knowledge Base restaurée depuis %s", backup_path)
    
    def clear_all(self, confirm: bool = False):
        """
        Efface toutes les données de la KB (DANGEREUX).
        
        Args:
            confirm: Doit être True pour confirmer l'action
        
        Raises:
            ValueError: Si confirm=False (sécurité)
        """
        if not confirm:
            raise ValueError("clear_all nécessite confirm=True pour éviter suppressions accidentelles")
        
        logger.warning(f" KB: clear_all() - Effacement complet demandé")
        
        # Backup avant suppression
        backup_path = Path(f"backups/kb_before_clear_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        self.export_backup(str(backup_path))
        logger.info(f"🔒 KB: Backup sécurité créé : {backup_path}")
        
        # Effacement volontaire : là encore, l'état voulu remplace tout.
        with _verrou_de(self.kb_path):
            self.data = self._create_empty_kb()
            self._ecrire()
        logger.warning("Knowledge Base entièrement effacée")
    
    # ========== STATS ==========
    
    def get_stats(self) -> Dict[str, Any]:
        """Retourne des statistiques sur la KB."""
        validated_by_type = {}
        for role in self.data["validated_roles"]:
            # `get(clé, défaut)` rend `None` quand la clé existe avec une
            # valeur nulle : un rôle importé d'une base plus ancienne se
            # retrouvait compté sous la clé `null`, sérialisée « null » dans
            # la réponse d'API — un libellé que rien ne traduit.
            rtype = role.get("role_type") or "UNKNOWN"
            validated_by_type[rtype] = validated_by_type.get(rtype, 0) + 1
        
        return {
            "version": self.data["version"],
            "last_updated": self.data["last_updated"],
            "birth_rights_count": len(self.data["birth_rights"]["rights"]),
            "validated_roles_total": len(self.data["validated_roles"]),
            "validated_roles_by_type": validated_by_type,
            "rejected_roles_count": len(self.data["rejected_roles"]),
            "excluded_users_count": len(self.data["excluded_users"]),
            "mining_runs_count": len(self.data["mining_runs"])
        }
