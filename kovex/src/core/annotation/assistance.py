# src/core/annotation/assistance.py
"""Ce que le produit a le droit de demander à un modèle, et avec quoi.

La politique du workspace portait trois drapeaux — `annotateur_envoie_*` — qui
décrivent **ce qui sort** sans rien dire de **pourquoi**. Tant qu'il n'existait
qu'un seul usage, proposer un nom de rôle, la distinction était sans objet.

Elle cesse de l'être au deuxième usage, et le défaut serait silencieux : un
administrateur qui avait autorisé les libellés de droits pour le nommage
verrait, à la livraison d'une fonction de cohérence droit ↔ application, ces
mêmes libellés partir vers un modèle **pour un usage qu'il n'a jamais
examiné**. Une autorisation donnée à une question ne vaut pas autorisation
pour toutes les questions suivantes.

Ce module est donc écrit **avant** le deuxième usage, et non après. Il ne
rend aucune fonction visible ; il rend possible d'en ajouter une sans rouvrir
la question du consentement à chaque fois.

Trois règles le gouvernent, toutes fermantes :

- **Intersection, jamais union.** Un appel n'a lieu que si l'usage est actif
  *et* que chaque matière dont il a besoin est autorisée *pour cet usage*.
- **Absent vaut refus.** Un usage absent du document est inactif ; une matière
  absente de sa liste est refusée. Il n'existe aucune valeur par défaut
  ouvrante.
- **Inconnu vaut refus, et se dit.** Un usage ou une matière que ce code ne
  connaît pas — une configuration écrite pour une version plus récente — ne
  peut ni ouvrir une porte que cette version ignore, ni disparaître en
  silence : elle est ignorée *et* signalée au chargement du workspace.

Les identités ne figurent dans aucune matière. Ce n'est pas un réglage, et il
n'y a pas de case à cocher qui les fasse sortir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Mapping, Tuple

# ----------------------------------------------------------------- la matière

#: Les catégories de données susceptibles de quitter le serveur. Chaque code
#: est aussi une clé de traduction — `assistance.matiere.<code>` — parce que
#: l'administrateur doit lire ce qui sort dans sa langue, et non un
#: identifiant technique.
MATIERE_LIBELLES_DE_DROITS = "libelles_de_droits"
MATIERE_REGLE_METIER = "regle_metier"
MATIERE_NOMS_VALIDES = "noms_valides"
#: Les **noms** des colonnes d'un référentiel, jamais leurs valeurs.
#:
#: La distinction n'est pas cosmétique : `service` est un nom de colonne,
#: `Oncologie` est une valeur. La première dit comment le client organise son
#: référentiel, la seconde dit quelque chose de ses gens. Un usage qui a besoin
#: de juger des colonnes n'a pas besoin de ce qu'il y a dedans.
MATIERE_NOMS_DE_COLONNES = "noms_de_colonnes"
#: Les **valeurs** d'une colonne : `Infirmier`, `Oncologie`, `CDI`.
#:
#: C'est la matière la plus sensible que ce catalogue porte, et de loin. Un nom
#: de colonne dit comment le client range son référentiel ; ses valeurs disent
#: ce que ses gens font et où ils sont. Une colonne `service` d'un hôpital
#: contient `Oncologie` et `Psychiatrie` — et l'effectif de chacune part avec.
#:
#: Elle est donc la seule matière dont l'autorisation ne suffit pas : l'usage
#: qui la réclame est **délimité par colonne**, et rien ne sort d'une colonne
#: que l'administrateur n'a pas ouverte nommément. Voir `Usage.par_colonne`.
MATIERE_VALEURS_D_ATTRIBUT = "valeurs_d_attribut"

#: Le texte d'une question posée par l'utilisateur, tel qu'il l'a écrit.
#:
#: C'est la matière la moins prévisible du catalogue, et c'est pour cela
#: qu'elle en est une. Les autres décrivent une catégorie connue — des
#: libellés, des noms de colonnes — dont on peut juger avant qu'elle ne parte.
#: Une question libre, non : « quels droits a Jean Dupont » contient un nom de
#: personne que personne n'a mis là et que rien ne filtre.
#:
#: Le produit ne peut pas router une question sans la lire, et un modèle ne
#: peut pas la lire sans la recevoir. L'arbitrage appartient donc à
#: l'administrateur, et il est pris ici plutôt que déduit du fait que
#: l'assistance est activée.
MATIERE_QUESTION_LIBRE = "question_libre"

#: Le libellé d'une règle de séparation, son processus et sa sévérité : des
#: mots écrits par le client pour nommer un risque (« Créer et payer un
#: fournisseur »). Ils ne désignent personne, mais ils disent comment
#: l'organisation découpe ses contrôles — c'est à l'administrateur de décider
#: s'ils sortent.
MATIERE_REGLES_DE_SEPARATION = "regles_de_separation"

#: Ordre d'affichage, et liste de référence de ce que le code connaît.
MATIERES: Tuple[str, ...] = (
    MATIERE_LIBELLES_DE_DROITS,
    MATIERE_REGLE_METIER,
    MATIERE_NOMS_VALIDES,
    MATIERE_NOMS_DE_COLONNES,
    MATIERE_VALEURS_D_ATTRIBUT,
    MATIERE_QUESTION_LIBRE,
    MATIERE_REGLES_DE_SEPARATION,
)


# ------------------------------------------------------------------- un usage


@dataclass(frozen=True)
class Usage:
    """Une question posée à un modèle, et la matière qu'elle réclame.

    Les besoins sont déclarés **dans le code et non dans la configuration**.
    Sans quoi la matrice deviendrait une grille que personne ne sait remplir :
    l'écran ne saurait pas expliquer pourquoi une case existe, et le produit
    ne saurait pas refuser tôt une configuration qui ne peut rien donner.

    Trois catégories, et la troisième n'est pas un détail :

    - `necessaires` — sans elles, la question n'a pas de sens ;
    - `au_moins_une` — il en faut une, n'importe laquelle ; c'est le cas du
      nommage, où libellés, règle et exemples sont interchangeables, mais où
      les trois fermés laissent le modèle inventer une finalité ;
    - `facultatives` — elles améliorent la réponse sans la conditionner.
    """

    code: str
    necessaires: Tuple[str, ...] = ()
    au_moins_une: Tuple[str, ...] = ()
    facultatives: Tuple[str, ...] = ()
    #: L'autorisation de cet usage se délimite **colonne par colonne**.
    #:
    #: Une matière autorisée ouvre une catégorie de données pour une question.
    #: Cela suffit tant que la catégorie est homogène : les libellés de droits
    #: d'un référentiel se valent entre eux. Les valeurs d'attribut, non — la
    #: colonne `type_de_contrat` et la colonne `service` d'un hôpital ne posent
    #: pas la même question, et un administrateur qui accepte que la première
    #: sorte n'a rien dit de la seconde.
    #:
    #: Déclaré dans le code, comme les besoins de matière : ce n'est pas un
    #: réglage qu'on active, c'est une propriété de la question posée.
    par_colonne: bool = False
    #: Faux pour un usage qui ne pose aucune question à un modèle de Kovex :
    #: le serveur MCP répond à un agent extérieur, il n'a pas de point de
    #: terminaison à régler. Le proposer dans l'écran des modèles ferait
    #: régler une adresse que rien n'appelle.
    appelle_un_modele: bool = True

    @property
    def matieres(self) -> Tuple[str, ...]:
        """Toute la matière que cet usage peut demander, et aucune autre.

        Une matière hors de cette liste ne s'ouvre pas pour cet usage, même
        écrite dans la configuration : ajouter une matière à un usage est une
        décision de conception, pas une frappe dans un fichier.
        """
        return self.necessaires + self.au_moins_une + self.facultatives

    def manque(self, autorisees: FrozenSet[str]) -> Tuple[str, ...]:
        """Ce qu'il faudrait ouvrir pour que la question puisse être posée.

        Rendue à l'écran telle quelle : un usage actif mais muet doit dire ce
        qui lui manque, faute de quoi l'administrateur croit avoir configuré.
        """
        absentes = tuple(m for m in self.necessaires if m not in autorisees)
        if self.au_moins_une and not (set(self.au_moins_une) & autorisees):
            absentes += self.au_moins_une
        return absentes


#: Les usages que ce code sait conduire.
#:
#: Un usage ne s'y ajoute qu'avec son traitement : listé à l'écran sans rien
#: derrière, il se lirait comme une fonction en panne. Les usages à venir —
#: cohérence des valeurs, cohérence droit ↔ application — s'ajouteront de la
#: même façon, et arriveront fermés comme tout le reste.
USAGE_NOMMAGE_DE_ROLE = Usage(
    code="nommage_de_role",
    au_moins_une=(MATIERE_LIBELLES_DE_DROITS, MATIERE_REGLE_METIER,
                  MATIERE_NOMS_VALIDES),
)

#: Proposer les fragments de nom qui signalent un droit sensible.
#:
#: Il réclame la **même matière** que le nommage — les libellés de droits — et
#: c'est précisément le cas que la matrice existe pour tenir : l'autorisation
#: donnée au nommage ne vaut pas pour cette question-là. Un administrateur qui
#: avait ouvert les libellés pour obtenir des noms de rôles doit examiner cette
#: demande séparément.
USAGE_DROITS_SENSIBLES = Usage(
    code="droits_sensibles",
    necessaires=(MATIERE_LIBELLES_DE_DROITS,),
)

#: Distinguer, parmi les colonnes d'identités, le métier de l'identifiant.
#:
#: Il ne demande que les **noms** des colonnes. Aucune valeur ne sort : juger
#: que `matricule` est un identifiant et que `service` porte du métier ne
#: demande pas de savoir qui travaille où.
USAGE_ATTRIBUTS_PERTINENTS = Usage(
    code="attributs_pertinents",
    necessaires=(MATIERE_NOMS_DE_COLONNES,),
)

#: Rapprocher les valeurs d'une colonne qui désignent la même chose.
#:
#: Le repérage local — distance d'édition, abréviation, troncature — trouve ce
#: qui se ressemble. `AS` et `Aide-soignant` ne se ressemblent pas ; `RRH` et
#: `Responsable ressources humaines` non plus. Il faut savoir ce que les mots
#: veulent dire, et c'est la seule chose qu'un modèle apporte ici.
#:
#: Il réclame les **valeurs** de la colonne, et c'est le seul usage du produit
#: dans ce cas. D'où la délimitation par colonne : l'autorisation ne se donne
#: pas pour « les valeurs d'attribut » en général, elle se donne pour
#: `identities.fonction` et pour rien d'autre.
#:
#: Le nom de la colonne est **facultatif**, et cette nuance a un effet réel.
#: Savoir que ces valeurs viennent d'une colonne nommée `fonction` oriente
#: fortement la réponse ; ne pas le savoir la dégrade sans l'empêcher. C'est
#: aussi le premier cas où le second contrôle d'envoi — « cette matière-là
#: a-t-elle le droit de partir ? » — n'est pas redondant avec `posable`.
USAGE_COHERENCE_DES_VALEURS = Usage(
    code="coherence_des_valeurs",
    necessaires=(MATIERE_VALEURS_D_ATTRIBUT,),
    facultatives=(MATIERE_NOMS_DE_COLONNES,),
    par_colonne=True,
)

#: Rédiger l'explication d'un rôle pour un responsable d'application.
#:
#: Les grandeurs — population, droits, couverture, sur-octroi — ne sont pas une
#: matière : ce sont des comptes, ils ne désignent personne, et ils partent
#: toujours. Ce qui se décide ici est ce qui les **accompagne** : la règle
#: métier, qui nomme un service et une fonction, et les libellés de droits.
#:
#: `au_moins_une` et non `necessaires` : les deux sont interchangeables pour
#: écrire un paragraphe, mais les deux fermées laissent le modèle rédiger à
#: partir de deux nombres — et il invente alors une finalité. C'est le défaut
#: observé sur le nommage, et il se reproduirait mot pour mot ici.
USAGE_EXPLICATION_DE_ROLE = Usage(
    code="explication_de_role",
    au_moins_une=(MATIERE_LIBELLES_DE_DROITS, MATIERE_REGLE_METIER),
)

#: Rédiger, pour un conflit de séparation des tâches, le paragraphe qui dit
#: pourquoi la combinaison est un risque et ce qui le réduirait.
#:
#: Ce qui part est **la règle, jamais les personnes** : les comptes du conflit
#: (combien d'identités, combien portées par un rôle, combien couvertes par une
#: dérogation) partent toujours, ce sont des nombres ; aucun identifiant ne
#: part, quelle que soit la configuration. S'y ajoutent, si l'administrateur
#: les ouvre, le libellé de la règle et les libellés des droits de chaque côté —
#: sans l'un ni l'autre, le modèle n'aurait que des nombres et inventerait le
#: risque. Les noms des rôles qui portent les deux côtés sont facultatifs.
USAGE_EXPLICATION_DE_CONFLIT = Usage(
    code="explication_de_conflit",
    au_moins_une=(MATIERE_REGLES_DE_SEPARATION, MATIERE_LIBELLES_DE_DROITS),
    facultatives=(MATIERE_NOMS_VALIDES,),
)

#: Comprendre une question posée en français, et la traduire en une question
#: que le produit sait calculer.
#:
#: Le modèle ne rend qu'un **code d'intention**, choisi dans une liste fermée.
#: Il n'écrit aucune phrase, ne reçoit aucun chiffre et ne nomme aucune entité :
#: les rôles, les droits et les identités sont reconnus localement, dans les
#: données, par comparaison de chaînes. Un chiffre inventé n'est donc pas
#: contrôlé après coup comme dans l'explication d'un rôle — il est impossible.
#:
#: Ce qui sort, en revanche, est la question elle-même, et c'est tout ce que
#: cet usage demande. Sans cette autorisation, l'agent s'en tient au routage
#: local par mots-clés : il répond quand même, moins souvent.
USAGE_AGENT_DE_NAVIGATION = Usage(
    code="agent_de_navigation",
    necessaires=(MATIERE_QUESTION_LIBRE,),
)

#: Proposer les conventions de nommage qui signalent un compte à privilèges.
#:
#: **Cet usage ne transmet rien, et c'est sa raison d'être.** Aucune matière :
#: ni identifiant, ni colonne, ni échantillon. La question posée au modèle ne
#: parle pas de ce client — elle demande comment les systèmes d'habilitations
#: nomment usuellement les comptes d'administration. C'est une question de
#: culture du métier, pas une question sur des données.
#:
#: Il figure tout de même dans la matrice, et il arrive fermé comme les
#: autres. Un administrateur qui interdit toute sortie vers un modèle a le
#: droit que sa règle vaille aussi pour les questions qui ne divulguent rien :
#: l'appel réseau existe quand même, et c'est lui qu'il refuse.
#:
#: La proposition qui revient est du **vocabulaire**, et elle est vérifiée
#: localement avant d'être montrée : un fragment que le référentiel ne porte
#: pas est écarté, et les comptes que les autres marqueraient sont comptés
#: ici. Le modèle apporte les mots, le produit apporte les nombres — et rien
#: de ce qu'il a vu n'a servi à les obtenir.
USAGE_COMPTES_A_PRIVILEGES = Usage(code="comptes_a_privileges")

#: Répondre, en lecture seule, aux questions d'un agent extérieur branché
#: par le protocole MCP (Claude Desktop, un IDE, un agent maison).
#:
#: Cet usage ne rédige rien et n'appelle aucun modèle : c'est l'agent
#: extérieur qui est le modèle, et **tout ce que le serveur lui rend sort de
#: Kovex**. C'est pourquoi il est dans la matrice, fermé par défaut, comme
#: les autres. Les comptes partent dès qu'il est ouvert ; les mots — codes de
#: droits, noms de rôles, libellés de règles — seulement si leur matière est
#: ouverte pour lui. **Aucun identifiant de personne ne part**, quelle que
#: soit la configuration : aucun outil n'en rend.
USAGE_SERVEUR_MCP = Usage(
    code="serveur_mcp",
    facultatives=(MATIERE_LIBELLES_DE_DROITS, MATIERE_NOMS_VALIDES,
                  MATIERE_REGLES_DE_SEPARATION),
    appelle_un_modele=False,
)

USAGES: Tuple[Usage, ...] = (USAGE_NOMMAGE_DE_ROLE, USAGE_DROITS_SENSIBLES,
                             USAGE_ATTRIBUTS_PERTINENTS,
                             USAGE_COHERENCE_DES_VALEURS,
                             USAGE_EXPLICATION_DE_ROLE,
                             USAGE_EXPLICATION_DE_CONFLIT,
                             USAGE_AGENT_DE_NAVIGATION,
                             USAGE_COMPTES_A_PRIVILEGES,
                             USAGE_SERVEUR_MCP)

#: Les usages qui posent une question à un modèle, et ont donc un point de
#: terminaison à régler.
USAGES_DE_MODELE: Tuple[Usage, ...] = tuple(usage for usage in USAGES
                                            if usage.appelle_un_modele)

#: Index par code, pour ne pas parcourir le registre à chaque lecture.
PAR_CODE: Mapping[str, Usage] = {usage.code: usage for usage in USAGES}


# ------------------------------------------------------- ce qui est autorisé


@dataclass(frozen=True)
class Autorisation:
    """L'intersection d'un usage et de la matière ouverte pour lui.

    Construite fermée : une `Autorisation` par défaut n'autorise rien, et
    c'est la valeur rendue pour un usage absent de la configuration. Le code
    appelant n'a donc jamais à distinguer « absent » de « refusé » — les deux
    se lisent pareil, ce qui est exactement le comportement voulu.
    """

    usage: Usage
    actif: bool = False
    matiere: FrozenSet[str] = frozenset()
    #: Les colonnes ouvertes, en paires `(référentiel, colonne)`. Vide par
    #: défaut, donc fermée : un usage délimité par colonne n'en ouvre aucune
    #: tant que l'administrateur n'en a nommé aucune.
    colonnes: FrozenSet[Tuple[str, str]] = frozenset()

    def autorise(self, matiere: str) -> bool:
        """La seule question que le reste du produit pose à ce module."""
        return (self.actif
                and matiere in self.matiere
                and matiere in self.usage.matieres)

    def autorise_la_colonne(self, referentiel: str, colonne: str) -> bool:
        """Cette colonne-là a-t-elle le droit de sortir pour cet usage ?

        Un usage qui ne se délimite pas par colonne répond oui dès qu'il est
        actif : la question ne se pose pas pour lui, et répondre non
        fermerait des usages qui n'ont jamais eu de colonnes.

        Pour les autres, l'appartenance est exigée. Absent vaut refus, comme
        partout dans ce module : une colonne nouvellement apparue dans les
        fichiers du client n'est pas ouverte parce qu'elle ressemble à une
        colonne ouverte.
        """
        if not self.actif:
            return False
        if not self.usage.par_colonne:
            return True
        return (str(referentiel), str(colonne)) in self.colonnes

    @property
    def colonnes_effectives(self) -> Tuple[Tuple[str, str], ...]:
        """Les colonnes ouvertes, triées. Vide pour un usage non délimité.

        Un usage qui ne se délimite pas par colonne ne **retient** aucune
        colonne, même si la configuration en portait : les écrire dans le
        document donnerait à croire qu'elles restreignent quelque chose.
        """
        if not self.usage.par_colonne:
            return ()
        return tuple(sorted(self.colonnes))

    @property
    def portee_ouverte(self) -> bool:
        """Une colonne au moins est-elle ouverte, quand l'usage en réclame ?

        `posable` ne le dit pas : il parle de la matière, et la matière peut
        être entièrement ouverte alors qu'aucune colonne ne l'est. L'écran doit
        distinguer les deux — ce ne sont pas le même geste à faire.
        """
        return not self.usage.par_colonne or bool(self.colonnes)

    @property
    def matiere_effective(self) -> Tuple[str, ...]:
        """Ce qui sortirait réellement, dans l'ordre d'affichage."""
        return tuple(m for m in MATIERES if self.autorise(m))

    @property
    def manque(self) -> Tuple[str, ...]:
        return self.usage.manque(frozenset(self.matiere_effective))

    @property
    def posable(self) -> bool:
        """L'usage peut-il rendre autre chose qu'une réponse inventée ?"""
        return self.actif and not self.manque


def _fermee(code: str) -> Autorisation:
    """Autorisation d'un usage inconnu : fermée, et qui ne connaît rien.

    Un usage inconnu ne peut pas être posable, puisqu'il ne déclare aucune
    matière et n'est pas actif.
    """
    return Autorisation(usage=PAR_CODE.get(code) or Usage(code=code))


# ----------------------------------------------- la lecture de configuration


#: Correspondance des trois drapeaux historiques. Ils ne décrivaient qu'un
#: usage — le nommage — et c'est ainsi qu'ils sont relus.
DRAPEAUX_HERITES: Mapping[str, str] = {
    "annotateur_envoie_libelles_de_droits": MATIERE_LIBELLES_DE_DROITS,
    "annotateur_envoie_regle_metier": MATIERE_REGLE_METIER,
    "annotateur_envoie_noms_valides": MATIERE_NOMS_VALIDES,
}

#: Clé du bloc dans le `config.json` du workspace.
CLE_ASSISTANCE = "assistance"


@dataclass(frozen=True)
class Assistance:
    """La matrice lue, et ce qu'il a fallu écarter pour la lire.

    Les avertissements ne sont pas des messages : ce sont des codes de
    traduction et leurs paramètres, comme partout ailleurs dans le produit.
    """

    autorisations: Mapping[str, Autorisation] = field(default_factory=dict)
    avertissements: Tuple[Dict[str, Any], ...] = ()

    def pour(self, code: str) -> Autorisation:
        """L'autorisation d'un usage. Jamais d'erreur : absent vaut fermé."""
        return self.autorisations.get(code) or _fermee(code)

    @classmethod
    def depuis_la_configuration(cls, configuration: Mapping[str, Any]) -> "Assistance":
        """Lit le bloc `assistance`, ou les trois drapeaux à défaut.

        **Reprise de l'existant.** Un workspace créé avant cette version ne
        porte que les drapeaux. En l'absence du bloc, ils sont lus comme la
        configuration du nommage, et d'aucun autre usage : c'est ce qu'ils
        voulaient dire, et c'est la lecture qui n'ouvre rien. Dès que le bloc
        existe, il fait seul foi — sans quoi un administrateur qui ferme une
        matière dans le nouvel écran la verrait rouverte par un drapeau
        oublié.
        """
        brut = configuration.get(CLE_ASSISTANCE)
        if not isinstance(brut, Mapping):
            return cls(autorisations=_depuis_les_drapeaux(configuration))

        autorisations: Dict[str, Autorisation] = {}
        avertissements: list = []
        for code, entree in brut.items():
            usage = PAR_CODE.get(code)
            if usage is None:
                avertissements.append({
                    "code": "assistance.warning.unknown_usage",
                    "params": {"usage": str(code)}})
                continue
            if not isinstance(entree, Mapping):
                avertissements.append({
                    "code": "assistance.warning.unreadable_usage",
                    "params": {"usage": code}})
                continue
            matiere, inconnues = _matiere_lue(usage, entree.get("matiere"))
            for inconnue in inconnues:
                avertissements.append({
                    "code": "assistance.warning.unknown_matter",
                    "params": {"usage": code, "matiere": inconnue}})
            brutes = entree.get("colonnes")
            if brutes and not usage.par_colonne:
                # Elle ne restreint rien, et l'administrateur qui l'a écrite
                # croyait limiter quelque chose. C'est le cas où le silence
                # coûterait le plus cher.
                avertissements.append({
                    "code": "assistance.warning.columns_ignored",
                    "params": {"usage": code}})
            colonnes, illisibles = _colonnes_lues(usage, brutes)
            for illisible in illisibles:
                avertissements.append({
                    "code": "assistance.warning.unreadable_column",
                    "params": {"usage": code, "entree": illisible}})
            autorisations[code] = Autorisation(
                usage=usage,
                actif=bool(entree.get("actif", False)),
                matiere=matiere,
                colonnes=colonnes,
            )
        return cls(autorisations=autorisations,
                   avertissements=tuple(avertissements))

    def en_document(self) -> Dict[str, Any]:
        """La matrice telle qu'elle s'écrit dans le `config.json`.

        Tous les usages connus y figurent, y compris fermés : un document
        complet se relit sans dépendre du code qui l'a écrit, et un usage qui
        disparaîtrait du fichier se lirait comme fermé plutôt que comme
        « jamais décidé » — même résultat, moins d'ambiguïté pour qui relit.
        """
        document: Dict[str, Any] = {}
        for usage in USAGES:
            autorisation = self.pour(usage.code)
            entree: Dict[str, Any] = {
                "actif": autorisation.actif,
                "matiere": list(autorisation.matiere_effective),
            }
            if usage.par_colonne:
                # Écrite seulement là où elle restreint quelque chose : une
                # liste vide sous un usage qui ne se délimite pas se lirait
                # comme un réglage qui existe et qui serait fermé.
                entree["colonnes"] = [
                    {"referentiel": referentiel, "colonne": colonne}
                    for referentiel, colonne in autorisation.colonnes_effectives]
            document[usage.code] = entree
        return document


def _matiere_lue(usage: Usage,
                 brut: Any) -> Tuple[FrozenSet[str], Tuple[str, ...]]:
    """Retient ce que l'usage déclare, signale le reste.

    Une matière inconnue du code, ou connue mais étrangère à cet usage, est
    écartée : ouvrir pour le nommage une matière que seul un autre usage
    réclame serait une permission accordée à une question qui n'est pas posée.
    """
    if not isinstance(brut, (list, tuple)):
        return frozenset(), ()
    retenues, inconnues = set(), []
    for valeur in brut:
        nom = str(valeur)
        if nom in usage.matieres:
            retenues.add(nom)
        else:
            inconnues.append(nom)
    return frozenset(retenues), tuple(inconnues)


def _colonnes_lues(usage: Usage,
                   brut: Any) -> Tuple[FrozenSet[Tuple[str, str]], Tuple[str, ...]]:
    """Les colonnes ouvertes pour cet usage, et ce qui n'a pas pu être lu.

    Une liste écrite sous un usage qui ne se délimite pas par colonne est
    écartée ; c'est l'appelant qui la signale, parce que lui seul peut le dire
    une fois et au bon moment.

    Aucune vérification d'existence : les colonnes du client ne sont pas
    connues de ce module, et une autorisation écrite pour un fichier
    momentanément absent ne doit pas disparaître de la configuration.
    """
    if not isinstance(brut, (list, tuple)) or not brut or not usage.par_colonne:
        return frozenset(), ()
    retenues, illisibles = set(), []
    for entree in brut:
        if not isinstance(entree, Mapping):
            illisibles.append(str(entree)[:80])
            continue
        referentiel = str(entree.get("referentiel", "")).strip()
        colonne = str(entree.get("colonne", "")).strip()
        if not referentiel or not colonne:
            illisibles.append(str(dict(entree))[:80])
            continue
        retenues.add((referentiel, colonne))
    return frozenset(retenues), tuple(illisibles)


def _depuis_les_drapeaux(
        configuration: Mapping[str, Any]) -> Dict[str, Autorisation]:
    """Les trois drapeaux historiques, lus comme la seule configuration du
    nommage.

    L'usage est actif dès lors qu'un drapeau est levé : ces drapeaux n'avaient
    pas d'interrupteur séparé, et l'annotateur était joignable ou non selon
    l'infrastructure. Les trois fermés donnent un usage inactif, ce qui est
    déjà ce que le produit faisait — il refusait la question.
    """
    matiere = frozenset(
        matiere for drapeau, matiere in DRAPEAUX_HERITES.items()
        if bool(configuration.get(drapeau, False)))
    return {USAGE_NOMMAGE_DE_ROLE.code: Autorisation(
        usage=USAGE_NOMMAGE_DE_ROLE, actif=bool(matiere), matiere=matiere)}
