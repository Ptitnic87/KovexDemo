/**
 * Le pont : le frontend de Kovex, inchangé, parlant à son backend qui tourne
 * dans la page.
 *
 * L'interface émet ses requêtes avec `fetch`, sur `/api/v1/…`. On remplace
 * `fetch` — et **rien d'autre**. Aucune ligne du frontend n'est touchée : ni
 * `api.js`, ni les quinze écrans, ni leurs tests. Une route, un corps, un code
 * d'erreur : ce que l'interface reçoit est ce que l'application ASGI a produit,
 * la validation Pydantic comprise.
 *
 * C'est ce qui permet d'affirmer qu'il n'y a **aucune différence** : ce n'est
 * pas une autre application qui imite la première, c'est la même.
 */
(function () {
  "use strict";

  const RACINE = "./moteur/";

  /**
   * L'empreinte du moteur, lue sur la balise qui charge ce fichier.
   *
   * Sans elle, un navigateur qui a déjà ouvert la page garde les archives en
   * cache : il peut alors exécuter **une archive périmée avec un pont neuf**,
   * ou l'inverse — un mélange que personne n'a testé. La construction pose
   * `?v=<empreinte>` sur la balise ; on la reporte sur tout ce que le moteur
   * charge, pour que le cache ne réponde plus à la place d'un fichier changé.
   *
   * Absente — un poste qui sert la page à la main — on charge sans marque,
   * comme avant.
   */
  const EMPREINTE = (function () {
    const balise = (typeof document !== "undefined" && document.currentScript)
      ? String(document.currentScript.src || "") : "";
    const trouve = /[?&]v=([A-Za-z0-9._-]+)/.exec(balise);
    return trouve ? trouve[1] : "";
  })();

  /**
   * L'adresse d'un fichier du moteur, marquée par l'empreinte.
   *
   * Elle ne sert qu'aux fichiers dont **le nom ne change jamais** : l'archive
   * du code. Les roues portent leur version dans leur nom, donc un changement
   * change déjà leur adresse — et Pyodide déduit le nom du paquet du nom du
   * fichier, qu'une chaîne de requête lui rendrait illisible.
   */
  function adresseDuMoteur(nom) {
    return RACINE + nom + (EMPREINTE ? "?v=" + EMPREINTE : "");
  }

  const ROUES = [
    "numpy-2.4.6-cp314-cp314-pyemscripten_2026_0_wasm32.whl",
    "scipy-1.18.0-cp314-cp314-pyemscripten_2026_0_wasm32.whl",
    "pandas-3.0.2-cp314-cp314-pyemscripten_2026_0_wasm32.whl",
    "pydantic_core-2.41.5-cp314-cp314-pyemscripten_2026_0_wasm32.whl",
    "pillow-12.2.0-cp314-cp314-pyemscripten_2026_0_wasm32.whl",
    "annotated_types-0.7.0-py3-none-any.whl",
    "annotated_doc-0.0.4-py3-none-any.whl",
    "typing_extensions-4.15.0-py3-none-any.whl",
    "typing_inspection-0.4.2-py3-none-any.whl",
    "pydantic-2.12.5-py3-none-any.whl",
    "sniffio-1.3.1-py3-none-any.whl",
    "idna-3.11-py3-none-any.whl",
    "anyio-4.13.0-py3-none-any.whl",
    "starlette-1.0.0-py3-none-any.whl",
    "fastapi-0.136.1-py3-none-any.whl",
    "six-1.17.0-py2.py3-none-any.whl",
    "python_dateutil-2.9.0.post0-py2.py3-none-any.whl",
    "pytz-2026.1.post1-py2.py3-none-any.whl",
    "pyjwt-2.14.0-py3-none-any.whl",
  ];

  //: Celles que Pyodide ne connaît pas : on les dépose à la main, parce que
  //: `micropip` irait les chercher sur le réseau et qu'il n'y a pas de réseau.
  const ROUES_DEPOSEES = [
    "et_xmlfile-2.0.0-py3-none-any.whl",
    "openpyxl-3.2.0b1-py2.py3-none-any.whl",
    "python_dotenv-1.2.3-py3-none-any.whl",
    "python_multipart-0.0.32-py3-none-any.whl",
    "reportlab-4.5.1-py3-none-any.whl",
  ];

  const PREPARATION = `
import os, sys, functools
os.chdir("/kovex")
sys.path.insert(0, "/kovex")
os.environ.setdefault("PYGIA_ENV", "development")
os.environ.setdefault("PYGIA_AUTH_DISABLED", "true")
os.environ.setdefault("PYGIA_SECRET_KEY", "page-autonome")

# Un navigateur n'a pas de fil d'exécution à prêter. FastAPI en réclame un pour
# tout endpoint qui n'est pas "async def", et le produit appelle
# run_in_threadpool pour ses calculs longs. On exécute directement.
#
# Ce n'est pas une dégradation : il y a un seul utilisateur, et la pile entière
# tourne dans un Worker — l'écran ne gèle pas davantage. Et c'est anyio qu'on
# adapte, pas Kovex : pas une ligne du produit ne change.
import anyio.to_thread, starlette.concurrency

async def _sans_fil(fonction, *args, abandon_on_cancel=False, cancellable=False,
                    limiter=None, **kwargs):
    return fonction(*args, **kwargs)

anyio.to_thread.run_sync = _sans_fil
starlette.concurrency.run_in_threadpool = (
    lambda fonction, *a, **k: _sans_fil(functools.partial(fonction, **k), *a))

from src.api.main import app
import json as _json
import js
from pyodide.ffi import to_js
# Le seul point reseau du produit est annotateur._poster, et il parle par
# urllib, qui n'existe pas dans un navigateur. On remplace **le transport**, et
# rien d'autre : la charge est construite en amont par le produit, la matrice
# d'assistance decide de ce qui peut sortir, et les identites n'en font jamais
# partie. Ce qui est remplace ici ne decide de rien.
#
# Les erreurs rendues sont celles que le produit attend, parce que c'est elles
# qui pilotent son comportement : une HTTPError 4xx fait redescendre d'un cran
# la contrainte de generation, une URLError fait dire "modele injoignable".
# Rendre autre chose changerait le comportement sans changer une ligne de
# Kovex.
#
# Une limite propre au navigateur, et il faut la dire : l'appel part de
# l'origine de la page. Le serveur de modele doit l'autoriser (pour Ollama,
# OLLAMA_ORIGINS). Un serveur qui refuse l'origine donne un refus reseau, que
# l'interface affiche comme un modele injoignable.
import urllib.error
from src.core.annotation import annotateur as _annotateur


def _aller_retour(adresse, entetes, corps, delai_ms, methode="POST"):
    """Un aller-retour HTTP par le navigateur. Rend (statut, texte).

    La methode est un parametre depuis que la lecture des modeles passe aussi
    par ici : elle est en GET, et un GET ne porte pas de corps. POST reste la
    valeur par defaut, et l'envoi des vraies questions ne change pas.
    """
    import js
    from pyodide.ffi import to_js

    import pyodide.ffi as _ffi

    run_sync = getattr(_ffi, "run_sync", None)
    if run_sync is not None:
        options = {"method": methode, "headers": entetes,
                   "signal": js.AbortSignal.timeout(delai_ms)}
        if methode != "GET":
            options["body"] = corps
        reponse = run_sync(js.fetch(
            adresse, to_js(options, dict_converter=js.Object.fromEntries)))
        return int(reponse.status), str(run_sync(reponse.text()))

    # Sans JSPI, il reste la requete synchrone. Elle fige l'onglet le temps de
    # la reponse : c'est moins bon, mais c'est mieux que pas de modele.
    requete = js.XMLHttpRequest.new()
    requete.open(methode, adresse, False)
    for cle, valeur in entetes.items():
        requete.setRequestHeader(cle, valeur)
    requete.timeout = delai_ms
    requete.send(None if methode == "GET" else corps)
    return int(requete.status), str(requete.responseText or "")


def _poster_par_le_navigateur(charge, reglages):
    adresse = reglages.adresse + "/chat/completions"
    try:
        statut, texte = _aller_retour(
            adresse, _annotateur.entetes(reglages), _json.dumps(charge),
            int(float(reglages.delai_s) * 1000))
    except Exception as erreur:  # une panne de reseau, un refus d'origine
        # L'adresse est nommee, jamais la cle : elle ne figure que dans
        # l'en-tete d'autorisation, et ne doit pas atterrir dans un journal.
        raise urllib.error.URLError(
            "appel au modele impossible (%s) : %s"
            % (adresse, type(erreur).__name__)) from None

    if statut >= 400:
        raise urllib.error.HTTPError(adresse, statut, texte[:200], None, None)

    brut = texte.encode("utf-8")[: _annotateur.REPONSE_MAX_OCTETS]
    return _json.loads(brut.decode("utf-8", "ignore"))


_annotateur._poster = _poster_par_le_navigateur


def _lister_par_le_navigateur(reglages):
    """La lecture des modeles, par le navigateur, comme l'envoi.

    Elle avait ete ecrite comme une fonction a part pour pouvoir etre
    branchee ici, et ne l'avait jamais ete : dans la page, elle tentait
    d'ouvrir une connexion que le navigateur ne donne pas, et l'ecran disait
    que le fournisseur n'avait pas repondu. Les erreurs rendues sont les memes
    que celles de l'envoi, pour que l'ecran distingue une cle refusee d'un
    serveur injoignable.
    """
    adresse = reglages.adresse + "/models"
    try:
        statut, texte = _aller_retour(
            adresse, _annotateur.entetes(reglages), None,
            int(float(reglages.delai_s) * 1000), methode="GET")
    except Exception as erreur:  # une panne de reseau, un refus d'origine
        raise urllib.error.URLError(
            "lecture des modeles impossible (%s) : %s"
            % (adresse, type(erreur).__name__)) from None

    if statut >= 400:
        raise urllib.error.HTTPError(adresse, statut, texte[:200], None, None)

    brut = texte.encode("utf-8")[: _annotateur.REPONSE_MAX_OCTETS]
    return _json.loads(brut.decode("utf-8", "ignore"))


_annotateur._lister = _lister_par_le_navigateur


def _declarer_le_modele(reglages_json):
    """Pose, ou retire, les reglages du modele dans l'environnement.

    Sur un poste, c'est l'infrastructure qui pose ces variables. Dans une page,
    l'infrastructure, c'est la personne qui l'ouvre : elle declare l'adresse et
    le modele, et le produit se comporte exactement comme s'ils venaient d'un
    fichier d'environnement. Sans declaration, l'annotateur n'existe pas —
    c'est le defaut du produit, et il est conserve.
    """
    declare = _json.loads(reglages_json) if reglages_json else {}
    for nom, cle in (("URL", "adresse"), ("MODELE", "modele"),
                     ("CLE", "cle"), ("DELAI_S", "delai")):
        variable = "KOVEX_ANNOTATEUR_" + nom
        valeur = str(declare.get(cle) or "").strip()
        if valeur:
            os.environ[variable] = valeur
        else:
            os.environ.pop(variable, None)
    return _json.dumps({
        "adresse": os.environ.get("KOVEX_ANNOTATEUR_URL", ""),
        "modele": os.environ.get("KOVEX_ANNOTATEUR_MODELE", ""),
        "cle_posee": bool(os.environ.get("KOVEX_ANNOTATEUR_CLE", "")),
    })



async def _appeler(methode, chemin, charge, entetes_json):
    """Conduit une requete a travers la pile ASGI, sans reseau.

    La charge arrive en **octets**, jamais en texte : l'import de fichiers
    passe par un envoi multipart, dont le corps n'est pas du texte et dont la
    frontiere est calculee par le navigateur. Le convertir en chaine le
    corromprait sur le premier octet non representable, et l'erreur
    apparaitrait dans l'analyseur multipart, tres loin de sa cause.

    Aucun accent grave dans ce bloc : il traverse un gabarit JavaScript, qui
    s'y refermerait.
    """
    corps = bytes(charge.to_py()) if charge is not None else b""
    chemin, _, requete_brute = chemin.partition("?")
    entetes = [(cle.lower().encode(), valeur.encode())
               for cle, valeur in _json.loads(entetes_json).items()]
    entetes.append((b"host", b"kovex.page"))
    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": methode.upper(), "scheme": "http",
        "path": chemin, "raw_path": chemin.encode(),
        "query_string": requete_brute.encode(), "root_path": "",
        "headers": entetes, "client": ("page", 0), "server": ("kovex.page", 80),
    }
    recu = []
    async def recevoir():
        return {"type": "http.request", "body": corps, "more_body": False}
    async def emettre(message):
        recu.append(message)
    await app(scope, recevoir, emettre)

    debut = next(m for m in recu if m["type"] == "http.response.start")
    charge = b"".join(m.get("body", b"") for m in recu
                      if m["type"] == "http.response.body")

    # Le corps repart en **octets**, jamais en texte. Il etait decode en UTF-8
    # avec remplacement des octets invalides : un classeur ou un PDF telecharge
    # depuis la page arrivait corrompu — l'en-tete du fichier survivait, le
    # reste non, et le classeur ne s'ouvrait plus. Un corps de reponse n'est pas
    # du texte, meme quand il en contient.
    rendu = js.Array.new()
    rendu.push(debut["status"])
    rendu.push(_json.dumps(
        {cle.decode(): valeur.decode() for cle, valeur in debut["headers"]}))
    rendu.push(js.Uint8Array.new(to_js(charge)))
    return rendu
`;

  let pretDuMoteur = null;
  let appeler = null;
  let declarerAuMoteur = null;

  /**
   * L'avancement du demarrage, dans le loader que l'interface a deja.
   *
   * Onze secondes de silence, ou plusieurs minutes sur une connexion lente,
   * se lisent comme une panne — et quelqu'un rechargera la page au milieu du
   * telechargement. Le loader de Kovex porte deja un texte et une barre : on
   * s'en sert plutot que d'en ajouter un.
   *
   * Les libelles passent par le catalogue quand il est charge, et tombent sur
   * un texte de repli sinon : le pont se met en place **avant** les scripts du
   * produit, donc avant l'i18n, et un ecran vide pendant ce temps-la serait
   * exactement le defaut qu'on veut eviter.
   */
  const REPLI = {
    runtime: "Telechargement du moteur — 34 Mo, une seule fois",
    bibliotheques: "Mise en place des bibliotheques de calcul",
    produit: "Chargement de Kovex",
    api: "Demarrage de l'API locale",
    pret: "Pret",
  };

  function annoncer(etape, part) {
    const texte = document.querySelector("#app-loader .loader-text");
    const barre = document.querySelector("#app-loader .loader-progress-bar");
    if (texte) {
      const cle = "loader.moteur." + etape;
      const traduit = (typeof I18n !== "undefined" && typeof I18n.t === "function")
        ? I18n.t(cle) : cle;
      texte.textContent = (traduit === cle) ? REPLI[etape] : traduit;
    }
    if (barre) {
      barre.style.animation = "none";
      barre.style.width = part + "%";
    }
    window.dispatchEvent(new CustomEvent("kovex:demarrage", {
      detail: { etape: etape, part: part } }));
  }

  /**
   * Le disque de la page : ce qui doit survivre à la fermeture de l'onglet.
   *
   * Sur un poste, les espaces de travail et la piste d'audit sont des fichiers.
   * Dans une page, le système de fichiers de Pyodide vit en mémoire : fermer
   * l'onglet perdait l'import, les rôles validés et la piste — c'est-à-dire
   * tout le travail. Ces deux dossiers sont donc montés sur IndexedDB, le seul
   * stockage durable qu'un navigateur offre sans rien demander.
   *
   * `config/` reste en mémoire, et c'est voulu : il vient de l'archive du
   * produit (les catalogues de langue, la configuration de repli). Le monter
   * masquerait ce que l'archive dépose.
   *
   * Un navigateur qui refuse le stockage — fenêtre privée, quota épuisé — ne
   * doit pas empêcher de travailler : on le dit, et la page continue en
   * mémoire seule.
   */
  const DOSSIERS_DURABLES = ["/kovex/workspaces", "/kovex/audit"];

  //: Nom du verrou d'écriture. Un seul onglet écrit le disque durable.
  const VERROU_DU_DISQUE = "kovex-demo-disque";

  let disqueDurable = false;
  let sauvegardeEnCours = Promise.resolve();
  let sauvegarde = async () => {};

  /**
   * Prend le verrou d'écriture, ou dit qu'un autre onglet l'a.
   *
   * IndexedDB ne fusionne rien : chaque onglet tient son propre système de
   * fichiers en mémoire, et une sauvegarde écrit **ce que cet onglet-là
   * contient**. Deux onglets ouverts, et le second effacait le travail du
   * premier — c'est arrivé : un espace de travail importé dans un onglet a
   * disparu quand l'autre a sauvegardé.
   *
   * Un verrou exclusif règle la question sans rien inventer : le premier
   * onglet écrit, les suivants travaillent en mémoire et **le disent**. Le
   * verrou est tenu pour toute la vie de la page — d'où la promesse qui ne se
   * résout jamais — et le navigateur le rend dès que l'onglet se ferme.
   */
  async function prendreLeVerrou() {
    if (!navigator.locks || typeof navigator.locks.request !== "function") {
      // Navigateur sans l'API des verrous : on ne peut pas garantir l'unicité.
      // Continuer en écrivant est le comportement d'avant ; le taire, non.
      console.warn("kovex: ce navigateur n'a pas l'API des verrous — si la page "
                   + "est ouverte dans deux onglets, le dernier enregistrement "
                   + "écrase l'autre.");
      return true;
    }
    return new Promise((tenu) => {
      navigator.locks.request(
        VERROU_DU_DISQUE, { mode: "exclusive", ifAvailable: true },
        (verrou) => {
          if (!verrou) {
            tenu(false);
            return undefined;
          }
          tenu(true);
          // Tenu jusqu'à la fermeture de l'onglet.
          return new Promise(function () {});
        }).catch(function () { tenu(true); });
    });
  }

  /**
   * Prévient que rien ne sera conservé, par les moyens de l'interface.
   *
   * Le message passe par le catalogue quand il est chargé, et tombe sur un
   * texte de repli sinon : le pont se met en place avant l'i18n du produit.
   */
  function prevenirQueRienNEstConserve(cause) {
    const dire = (cle, repli) => {
      const traduit = (typeof I18n !== "undefined" && typeof I18n.t === "function")
        ? I18n.t(cle) : cle;
      return traduit === cle ? repli : traduit;
    };
    const titre = dire("page.disque.partage_titre", "Un autre onglet a la main");
    const texte = dire("page.disque.partage",
                       "Kovex est deja ouvert dans un autre onglet. Ce que vous "
                       + "faites ici ne sera pas conserve : fermez cet onglet et "
                       + "travaillez dans l'autre.");
    console.warn("kovex: " + texte + (cause ? " (" + cause + ")" : ""));
    window.dispatchEvent(new CustomEvent("kovex:disque", {
      detail: { durable: false, cause: cause || "verrou tenu ailleurs" } }));
    // L'avertissement doit atteindre l'écran, pas seulement la console.
    const annoncer = () => {
      if (typeof Toast !== "undefined" && typeof Toast.warning === "function") {
        Toast.warning(titre, texte);
        return true;
      }
      return false;
    };
    if (!annoncer()) {
      let essais = 0;
      const attente = setInterval(() => {
        essais += 1;
        if (annoncer() || essais > 60) clearInterval(attente);
      }, 500);
    }
  }

  async function monterLeDisque(pyodide) {
    if (!(await prendreLeVerrou())) {
      disqueDurable = false;
      prevenirQueRienNEstConserve(null);
      return;
    }
    try {
      for (const dossier of DOSSIERS_DURABLES) {
        pyodide.FS.mkdirTree(dossier);
        pyodide.FS.mount(pyodide.FS.filesystems.IDBFS, {}, dossier);
      }
      // `true` : on lit ce qui était là. C'est cette lecture qui fait qu'une
      // page rouverte retrouve son espace de travail.
      await new Promise((tenu, rompu) => {
        pyodide.FS.syncfs(true, (erreur) => (erreur ? rompu(erreur) : tenu()));
      });
      disqueDurable = true;
      sauvegarde = () => new Promise((tenu) => {
        pyodide.FS.syncfs(false, (erreur) => {
          if (erreur) {
            // Un quota atteint ne doit pas passer sous silence : le travail
            // en cours tient encore en mémoire, mais il ne survivra pas.
            console.error("kovex: sauvegarde impossible — " + erreur);
            window.dispatchEvent(new CustomEvent("kovex:sauvegarde", {
              detail: { tenue: false, cause: String(erreur) } }));
          }
          tenu();
        });
      });
    } catch (erreur) {
      disqueDurable = false;
      console.warn("kovex: stockage durable indisponible, le travail de cette "
                   + "page ne survivra pas à sa fermeture — " + erreur);
    }
  }

  /**
   * Écrit sur le disque durable ce que l'appel vient de changer.
   *
   * Appelé **avant** que la réponse ne parte, et non plus tard : quelqu'un qui
   * ferme l'onglet juste après avoir validé un rôle doit retrouver ce rôle. Les
   * sauvegardes sont mises en file pour qu'elles ne se chevauchent pas.
   */
  function enregistrer() {
    if (!disqueDurable) return Promise.resolve();
    sauvegardeEnCours = sauvegardeEnCours.then(sauvegarde, sauvegarde);
    return sauvegardeEnCours;
  }

  /**
   * Le disque de la démonstration, séparé de celui de KovexPublic.
   *
   * Les deux pages sont servies depuis la même origine (le compte GitHub
   * Pages), et le pont nomme ses bases IndexedDB d'après le dossier monté :
   * sans cette séparation, la démonstration écrivait ses espaces dans le disque
   * de KovexPublic — et changeait son espace actif —, et un onglet de l'une
   * prenait le verrou d'écriture de l'autre. Le second onglet travaillait
   * alors en mémoire, et chaque changement d'espace, qui recharge la page,
   * ramenait l'amorce et le premier espace.
   *
   * On préfixe donc le nom des bases, au seul endroit où l'IDBFS les ouvre, et
   * le verrou porte un autre nom (remplacé à la construction).
   */
  function isolerLeDisqueDeLaDemo(pyodide) {
    const idbfs = pyodide.FS.filesystems.IDBFS;
    if (!idbfs || idbfs.__kovexDemo) return;
    const ouvrir = idbfs.getDB;
    idbfs.getDB = function (nom, rappel) {
      return ouvrir.call(idbfs, "kovex-demo:" + nom, rappel);
    };
    idbfs.__kovexDemo = true;
  }

  /**
   * L'amorce de la démonstration : les espaces figés, remis à chaque ouverture.
   *
   * Inséré dans le pont de la page par `construire_le_site.py` (KovexDemo),
   * juste après le montage du disque durable. La page de démonstration s'ouvre
   * ainsi directement sur les espaces de démo, datés du jour, avec leurs
   * minings conservés. L'amorce passe **une fois par onglet** : un nouvel
   * onglet repart de l'état figé, un rechargement (changer d'espace en est un)
   * garde la séance en cours. Les espaces créés par le visiteur ne sont pas
   * touchés.
   *
   * Une amorce absente ou illisible ne bloque pas la page : on le dit dans la
   * console, et la page démarre comme KovexPublic, vide.
   */
  async function amorcerLaDemo(pyodide) {
    const BASE = "./amorce/";
    let index;
    try {
      const reponse = await fetch(BASE + "index.json", { cache: "no-store" });
      if (!reponse.ok) return;
      index = await reponse.json();
    } catch (erreur) {
      console.warn("kovex: amorce illisible — " + erreur);
      return;
    }
    // Une fois par onglet. Changer d'espace recharge la page : remettre
    // l'amorce à chaque chargement ramènerait l'espace actif au premier et
    // effacerait la séance en cours. Un nouvel onglet repart de zéro ; un
    // disque vidé entre-temps aussi.
    const DRAPEAU = "kovex-demo-amorcee";
    const jeu = String(index.construit_le || "") + "-" + String(index.kovex_version || "");
    const premier = (index.espaces || [])[0];
    const present = premier && pyodide.FS.analyzePath(
      "/kovex/workspaces/" + premier.id).exists;
    let dejaFait = false;
    try { dejaFait = sessionStorage.getItem(DRAPEAU) === jeu; } catch (e) { dejaFait = false; }
    if (dejaFait && present) return;
    annoncer("amorce", 78);
    const marque = "?v=" + encodeURIComponent(String(index.construit_le || "") + "-"
                                              + String(index.kovex_version || ""));
    const dossier = "/kovex/_amorce";
    pyodide.FS.mkdirTree(dossier);
    const ecrire = async (nom) => {
      const octets = new Uint8Array(await (await fetch(BASE + nom + marque)).arrayBuffer());
      pyodide.FS.writeFile(dossier + "/" + nom, octets);
    };
    await ecrire("index.json");
    await ecrire("restaurer.py");
    await ecrire("modele.json");
    for (const espace of index.espaces || []) {
      await ecrire(espace.id + ".tar.gz");
    }
    try {
      await pyodide.runPythonAsync(`
import sys, json
from datetime import date
from pathlib import Path
sys.path.insert(0, "/kovex")
sys.path.insert(0, "/kovex/_amorce")
import restaurer as _restaurer
_modele = json.loads(Path("/kovex/_amorce/modele.json").read_text(encoding="utf-8"))
_restaurer.restaurer(Path("/kovex"), Path("/kovex/_amorce"), _modele, None, date.today())
`);
      await enregistrer();
      try { sessionStorage.setItem(DRAPEAU, jeu); } catch (e) { /* sans stockage : on remet à chaque chargement */ }
    } catch (erreur) {
      console.error("kovex: amorce de la démonstration impossible — " + erreur);
    }
  }

  async function demarrer() {
    annoncer("runtime", 5);
    const pyodide = await loadPyodide({ indexURL: RACINE });

    annoncer("bibliotheques", 25);
    // Sans marque d'empreinte : Pyodide déduit le nom du paquet de celui du
    // fichier, et une chaîne de requête le lui rend illisible. Ces archives
    // portent déjà leur version dans leur nom — un changement change
    // l'adresse, donc le cache ne peut pas les confondre.
    await pyodide.loadPackage(ROUES.map((nom) => RACINE + nom));

    for (const nom of ROUES_DEPOSEES) {
      const octets = new Uint8Array(await (await fetch(RACINE + nom)).arrayBuffer());
      pyodide.unpackArchive(octets, "zip",
                            { extractDir: "/lib/python3.14/site-packages" });
    }

    annoncer("produit", 70);
    const source = new Uint8Array(
      await (await fetch(adresseDuMoteur("kovex-src.zip"))).arrayBuffer());
    pyodide.unpackArchive(source, "zip", { extractDir: "/kovex" });

    isolerLeDisqueDeLaDemo(pyodide);
    await monterLeDisque(pyodide);
    await amorcerLaDemo(pyodide);

    annoncer("api", 85);
    await pyodide.runPythonAsync(PREPARATION);
    appeler = pyodide.globals.get("_appeler");
    declarerAuMoteur = pyodide.globals.get("_declarer_le_modele");
    await appliquerLaDeclaration();

    annoncer("pret", 100);
    return pyodide;
  }

  /**
   * `fetch`, remplacé pour les seules adresses de l'API.
   *
   * Tout le reste — les feuilles de style, les polices, les données de la page
   * elle-même — passe par le `fetch` d'origine. On ne détourne que ce qui
   * s'adressait au serveur.
   *
   * Ce que le navigateur faisait dans ce `fetch` et qu'il ne fait plus est une
   * différence pour l'interface. L'interface n'a pas été touchée : c'est donc
   * au pont de le refaire. Les redirections en sont une — le produit répond
   * `307` sur `/api/v1/workspaces` vers la route avec barre finale, un vrai
   * `fetch` la suit sans que l'appelant l'apprenne, et l'écran des workspaces
   * affichait « Chargement impossible ».
   */
  const fetchOrigine = window.fetch.bind(window);

  const ADRESSE_LOCALE = "http://kovex.page";

  //: Les codes qu'un `fetch` suit de lui-même.
  const REDIRECTIONS = [301, 302, 303, 307, 308];

  //: La borne du navigateur : au-delà, `fetch` rend une erreur de réseau.
  const REDIRECTIONS_MAX = 20;

  //: Les statuts auxquels un corps est interdit. Le constructeur de `Response`
  //: refuse la chaîne vide pour ceux-là — il faut `null`.
  const SANS_CORPS = [101, 103, 204, 205, 304];

  function estUneAdresseDeLApi(chemin) {
    return /^\/(api\/|health\b)/.test(chemin);
  }

  function cheminDe(adresse) {
    return String(adresse).replace(/^https?:\/\/[^/]+/, "");
  }

  /**
   * Conduit un appel jusqu'à l'application ASGI et rend ce qu'elle a produit.
   *
   * Le corps traverse en octets dans les deux sens : un envoi multipart n'est
   * pas du texte, et un classeur ou un PDF téléchargé ne l'est pas davantage.
   */
  async function traverser(methode, chemin, octets, entetes) {
    const rendu = await appeler(methode, chemin, octets, JSON.stringify(entetes));
    const statut = rendu[0];
    const entetesRendus = JSON.parse(rendu[1]);
    // La copie est nécessaire : la vue rendue par le moteur pointe dans sa
    // mémoire, que l'appel suivant réutilise.
    const corps = new Uint8Array(rendu[2]);
    if (typeof rendu.destroy === "function") rendu.destroy();
    return { statut: statut, entetes: entetesRendus, corps: corps };
  }

  window.fetch = async function (ressource, options) {
    const chemin = cheminDe(typeof ressource === "string" ? ressource
                            : (ressource && ressource.url) || String(ressource));

    if (!estUneAdresseDeLApi(chemin)) {
      return fetchOrigine(ressource, options);
    }

    if (!pretDuMoteur) pretDuMoteur = demarrer();
    await pretDuMoteur;

    // On passe par `Request` pour que le navigateur fasse ce qu'il ferait
    // vraiment : sérialiser un `FormData` en multipart, calculer la frontière,
    // et poser le `Content-Type` qui va avec. Reconstruire tout cela à la main
    // reviendrait à réécrire une partie du navigateur — et à s'en écarter.
    const demande = new Request(ADRESSE_LOCALE + chemin,
                                Object.assign({}, options || {}));
    const suivi = demande.redirect || "follow";

    let methode = demande.method;
    let adresse = chemin;
    let octets = new Uint8Array(await demande.arrayBuffer());
    const entetes = {};
    demande.headers.forEach((valeur, cle) => { entetes[cle] = valeur; });

    for (let saut = 0; ; saut += 1) {
      const rendu = await traverser(methode, adresse, octets, entetes);
      const emplacement = rendu.entetes
        && (rendu.entetes.location || rendu.entetes.Location);
      const redirige = REDIRECTIONS.indexOf(rendu.statut) !== -1 && emplacement;

      if (!redirige || suivi === "manual") {
        // Un appel qui a pu écrire — tout ce qui n'est pas une lecture — est
        // suivi d'une sauvegarde, avant que l'interface ne reprenne la main.
        if (methode !== "GET" && methode !== "HEAD" && rendu.statut < 400) {
          await enregistrer();
        }
        const corps = SANS_CORPS.indexOf(rendu.statut) !== -1 ? null : rendu.corps;
        return new Response(corps, { status: rendu.statut, headers: rendu.entetes });
      }

      if (suivi === "error") {
        throw new TypeError("kovex: redirection refusée vers " + emplacement);
      }

      if (saut + 1 >= REDIRECTIONS_MAX) {
        throw new TypeError("kovex: trop de redirections depuis " + chemin);
      }

      const cible = new URL(emplacement, ADRESSE_LOCALE + adresse);
      const suite = cible.pathname + cible.search;

      // Une redirection qui sort de l'API désigne un document de la page :
      // c'est au `fetch` d'origine de le chercher, sur la vraie origine.
      if (!estUneAdresseDeLApi(suite)) {
        return fetchOrigine(suite, { method: methode === "HEAD" ? "HEAD" : "GET" });
      }

      // La règle est celle de `fetch` : `307` et `308` reconduisent la même
      // requête, les autres repartent en `GET` et **sans corps** — un `POST`
      // rejoué sur la cible d'un `303` enverrait deux fois la même écriture.
      if (rendu.statut === 303 ? methode !== "GET" && methode !== "HEAD"
                               : rendu.statut !== 307 && rendu.statut !== 308) {
        methode = "GET";
        octets = new Uint8Array(0);
        delete entetes["content-type"];
        delete entetes["content-length"];
      }
      adresse = suite;
    }
  };

  /**
   * Le moteur de modèle, déclaré par la personne qui ouvre la page.
   *
   * Sur un poste, ces réglages viennent de l'environnement du serveur : ouvrir
   * une sortie réseau depuis un système d'habilitations est une décision
   * d'infrastructure. Dans une page, l'infrastructure, c'est la personne qui
   * l'ouvre. Elle déclare l'adresse et le modèle ; le produit se comporte
   * ensuite **exactement** comme si un fichier d'environnement les portait —
   * même matrice d'assistance, mêmes catégories, mêmes attestations.
   *
   * Sans déclaration, il n'y a pas de modèle : c'est le défaut du produit, et
   * la page le conserve.
   *
   * La clé, elle, ne va pas dans le stockage durable. Une clé déposée là
   * survit à la fermeture de l'onglet et se lit depuis l'origine de la page :
   * elle reste en mémoire, et au plus dans le stockage de session si la
   * personne le demande pour cet onglet. L'adresse et le modèle, qui ne sont
   * pas des secrets, sont retenus pour ne pas être ressaisis.
   */
  const CLE_ADRESSE = "kovex_modele_adresse";
  const CLE_SESSION = "kovex_modele_cle";

  let declaration = null;

  function lireLaDeclarationRetenue() {
    try {
      const garde = JSON.parse(localStorage.getItem(CLE_ADRESSE) || "null");
      if (!garde) return null;
      const cle = sessionStorage.getItem(CLE_SESSION) || "";
      return Object.assign({}, garde, cle ? { cle: cle } : {});
    } catch (erreur) {
      return null;
    }
  }

  async function appliquerLaDeclaration() {
    if (!declarerAuMoteur) return null;
    const posee = declaration || lireLaDeclarationRetenue();
    return JSON.parse(await declarerAuMoteur(posee ? JSON.stringify(posee) : ""));
  }

  /** Ce que la page peut dire de son disque : durable, ou mémoire seule. */
  window.KovexDisque = {
    durable() { return disqueDurable; },
  };

  window.KovexModele = {
    /**
     * Déclare — ou retire — le moteur de modèle.
     *
     * `conserver: "onglet"` garde la clé dans le stockage de session, le temps
     * de l'onglet. Tout autre valeur la laisse en mémoire seule.
     */
    async declarer(reglages) {
      declaration = reglages && reglages.adresse
        ? { adresse: String(reglages.adresse).replace(/\/+$/, ""),
            modele: String(reglages.modele || ""),
            cle: String(reglages.cle || ""),
            delai: reglages.delai ? String(reglages.delai) : "" }
        : null;
      try {
        if (declaration) {
          localStorage.setItem(CLE_ADRESSE, JSON.stringify({
            adresse: declaration.adresse, modele: declaration.modele,
            delai: declaration.delai }));
          if (declaration.cle && reglages.conserver === "onglet") {
            sessionStorage.setItem(CLE_SESSION, declaration.cle);
          } else {
            sessionStorage.removeItem(CLE_SESSION);
          }
        } else {
          localStorage.removeItem(CLE_ADRESSE);
          sessionStorage.removeItem(CLE_SESSION);
        }
      } catch (erreur) {
        // Un navigateur qui refuse le stockage n'empêche pas de déclarer : la
        // déclaration tient en mémoire pour la durée de la page.
      }
      if (!pretDuMoteur) pretDuMoteur = demarrer();
      await pretDuMoteur;
      return appliquerLaDeclaration();
    },

    /** Ce que le moteur porte : jamais la clé, seulement qu'elle est posée. */
    async etat() {
      if (!pretDuMoteur) return { adresse: "", modele: "", cle_posee: false };
      await pretDuMoteur;
      return appliquerLaDeclaration();
    },

    /** Retire la déclaration, de la mémoire comme du stockage. */
    async oublier() {
      return window.KovexModele.declarer(null);
    },
  };

  /**
   * La session locale.
   *
   * L'interface montre son écran de connexion tant qu'aucune session n'est
   * enregistrée. Dans une page, cet écran ne protège rien : il y a un seul
   * utilisateur, sur sa propre machine, et le serveur qu'il interrogerait
   * tourne dans le même onglet. Demander un mot de passe pour accéder à ses
   * propres fichiers serait du théâtre.
   *
   * On pose donc la session que le backend accorde déjà dans ce mode —
   * `PYGIA_AUTH_DISABLED`, que `src/api/main.py` **refuse** dès que
   * `PYGIA_ENV=production`, et qui ne peut donc pas ouvrir une instance
   * servie. La page hérite de cette garantie : elle n'est jamais servie.
   *
   * Ce qui est protégé l'est ailleurs, et l'est vraiment : aucune donnée ne
   * sort sans qu'une colonne ait été ouverte à un modèle, et les identités ne
   * sortent jamais.
   */
  function poserLaSessionLocale() {
    try {
      if (localStorage.getItem("pygia_token")) return;
      localStorage.setItem("pygia_token", "page-autonome");
      localStorage.setItem("pygia_user", JSON.stringify({
        username: "local",
        email: "local@page",
        full_name: "Poste local",
        role: "admin",
        disabled: false,
        permissions: ["read", "write", "admin", "mining", "validate", "export"],
      }));
    } catch (erreur) {
      // Un navigateur qui refuse le stockage local — fenêtre privée, site
      // bloqué — laisse l'écran de connexion. Le dire vaut mieux que de
      // tourner sans comprendre.
      console.warn("kovex: stockage local indisponible, l'écran de connexion "
                   + "restera affiché — " + erreur);
    }
  }

  poserLaSessionLocale();

  // Le moteur démarre sans attendre la première requête : onze secondes de
  // chargement au premier appel de l'interface se liraient comme une panne.
  window.addEventListener("DOMContentLoaded", () => {
    if (!pretDuMoteur) {
      pretDuMoteur = demarrer();
      // Un démarrage qui échoue en silence laisse une page qui tourne sans
      // dire pourquoi : c'est le pire état possible pour qui l'ouvre.
      pretDuMoteur.catch((erreur) => {
        window.__PANNE = String(erreur && erreur.message || erreur);
        console.error("kovex: le moteur n'a pas démarré — " + window.__PANNE);
      });
    }
  });
})();
