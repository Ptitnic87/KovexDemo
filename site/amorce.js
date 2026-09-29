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

