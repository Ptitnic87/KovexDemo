"""La plateforme de démonstration : générateur, restauration, réglage du modèle.

    python -m pytest tests -q

Le réglage du modèle passe par les lecteurs de Kovex, copié dans ``kovex/``.
"""

import io
import json
import sys
import tarfile
from datetime import date
from pathlib import Path

import pytest

ICI = Path(__file__).resolve().parents[1]
RACINE = ICI / "kovex"
sys.path.insert(0, str(ICI))
sys.path.insert(0, str(RACINE))

import generer_secteur  # noqa: E402
import restaurer  # noqa: E402

FICHES = sorted((ICI / "secteurs").glob("*.json"))


# -- les fiches ---------------------------------------------------------------


@pytest.mark.parametrize("chemin", FICHES, ids=[f.stem for f in FICHES])
def test_chaque_fiche_se_lit(chemin):
    fiche = generer_secteur.lire_la_fiche(chemin)
    assert fiche["identifiant"] == chemin.stem
    assert fiche["gouvernance"]["regles"][0]["gauche"] == fiche["couple_enfreint"]["droits"][0]


def test_une_fiche_incomplete_est_refusee(tmp_path):
    fiche = json.loads(FICHES[0].read_text(encoding="utf-8"))
    del fiche["troncature"]
    chemin = tmp_path / "x.json"
    chemin.write_text(json.dumps(fiche), encoding="utf-8")
    with pytest.raises(generer_secteur.FicheInvalide, match="troncature"):
        generer_secteur.lire_la_fiche(chemin)


def test_un_departement_inconnu_est_refuse(tmp_path):
    fiche = json.loads(FICHES[0].read_text(encoding="utf-8"))
    fiche["troncature"]["departements_eligibles"] = ["Nulle part"]
    chemin = tmp_path / "x.json"
    chemin.write_text(json.dumps(fiche), encoding="utf-8")
    with pytest.raises(generer_secteur.FicheInvalide, match="Nulle part"):
        generer_secteur.lire_la_fiche(chemin)


@pytest.mark.parametrize("chemin", FICHES, ids=[f.stem for f in FICHES])
def test_chaque_secteur_plante_tous_ses_cas(chemin):
    generateur = generer_secteur.generer(generer_secteur.lire_la_fiche(chemin))
    rates = [nom for nom, tenu, _ in generateur.verifier() if not tenu]
    assert rates == []


def test_la_generation_est_deterministe(tmp_path):
    fiche = generer_secteur.lire_la_fiche(ICI / "secteurs" / "luxe.json")
    for sortie in ("a", "b"):
        generer_secteur.generer(fiche).ecrire(tmp_path / sortie)
    for nom in ("identities.csv", "droits.csv", "habilitations.csv"):
        assert (tmp_path / "a" / "data" / nom).read_bytes() == \
            (tmp_path / "b" / "data" / nom).read_bytes()


# -- la restauration ----------------------------------------------------------


def test_les_dates_sont_decalees_ensemble():
    document = {"execute_le": "2026-09-21", "decided_at": "2026-09-28T07:30:33.360794",
                "motif": "revue du 2026-09-01", "n": 3}
    decale = restaurer.decaler(document, 10)
    assert decale["execute_le"] == "2026-10-01"
    assert decale["decided_at"] == "2026-10-08T07:30:33.360794"
    # Un libellé qui contient une date n'est pas une date.
    assert decale["motif"] == "revue du 2026-09-01"
    assert decale["n"] == 3


def _archive(chemin, membres):
    with tarfile.open(chemin, "w:gz") as tar:
        for nom, contenu in membres:
            info = tarfile.TarInfo(nom)
            donnees = contenu.encode("utf-8")
            info.size = len(donnees)
            tar.addfile(info, io.BytesIO(donnees))


@pytest.mark.parametrize("nom", ["../evade.txt", "/etc/evade", "Autre/x.txt"])
def test_une_archive_qui_sort_de_son_dossier_est_refusee(tmp_path, nom):
    archive = tmp_path / "E.tar.gz"
    _archive(archive, [(nom, "x")])
    with pytest.raises(restaurer.RestaurationRefusee):
        restaurer.extraire(archive, tmp_path / "espaces", "E")
    assert not (tmp_path / "evade.txt").exists()


def test_un_lien_dans_l_archive_est_refuse(tmp_path):
    archive = tmp_path / "E.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        lien = tarfile.TarInfo("E/lien")
        lien.type = tarfile.SYMTYPE
        lien.linkname = "/etc/passwd"
        tar.addfile(lien)
    with pytest.raises(restaurer.RestaurationRefusee):
        restaurer.extraire(archive, tmp_path, "E")


def test_le_modele_passe_par_les_lecteurs_du_produit():
    modele = json.loads((ICI / "modele.json").read_text(encoding="utf-8"))
    modele["prereglage"].update(adresse="https://llm.exemple.test/v1", modele="m")
    configuration = {}
    notes = restaurer.regler_le_modele(configuration, modele)
    assert notes == []
    assert configuration["points_de_terminaison"]["commun"]["prereglage"] == "demo"
    assert configuration["assistance"]["nommage_de_role"]["actif"] is True
    # Aucune clé : elle se pose sur le serveur, jamais dans un espace.
    assert "cle" not in json.dumps(configuration["points_de_terminaison"])


def test_un_modele_sans_adresse_n_ouvre_aucun_point_de_terminaison():
    modele = json.loads((ICI / "modele.json").read_text(encoding="utf-8"))
    configuration = {}
    notes = restaurer.regler_le_modele(configuration, modele)
    assert "points_de_terminaison" not in configuration
    assert notes


def test_un_usage_inconnu_arrete_la_restauration():
    with pytest.raises(restaurer.RestaurationRefusee):
        restaurer.regler_le_modele({}, {"assistance": {"usage_invente": {"actif": True}}})


def test_la_restauration_remet_l_espace_et_decale_ses_dates(tmp_path):
    instantane = tmp_path / "instantane"
    instantane.mkdir()
    kb = json.dumps({"derogations": [{"echeance": "2026-12-27"}]})
    _archive(instantane / "X_DEMO.tar.gz",
             [("X_DEMO/config.json", "{}"), ("X_DEMO/knowledge_base.json", kb)])
    (instantane / "index.json").write_text(json.dumps({
        "construit_le": "2026-09-28",
        "espaces": [{"id": "X_DEMO", "name": "X", "created_at": "2026-09-28T07:00:00"}]}),
        encoding="utf-8")
    racine = tmp_path / "kovex"
    (racine / "workspaces" / "X_DEMO").mkdir(parents=True)
    (racine / "workspaces" / "X_DEMO" / "trace_d_une_seance.json").write_text("{}")
    (racine / "workspaces" / "workspaces.json").write_text(json.dumps({
        "version": "1.0", "active_workspace": "Autre",
        "workspaces": [{"id": "Autre"}, {"id": "X_DEMO", "name": "ancien"}]}))

    restaures, _, ecart = restaurer.restaurer(racine, instantane, {"assistance": {}},
                                              None, date(2026, 10, 8))

    assert restaures == ["X_DEMO"] and ecart == 10
    espace = racine / "workspaces" / "X_DEMO"
    assert not (espace / "trace_d_une_seance.json").exists()
    assert json.loads((espace / "knowledge_base.json").read_text())[
        "derogations"][0]["echeance"] == "2027-01-06"
    registre = json.loads((racine / "workspaces" / "workspaces.json").read_text())
    assert registre["active_workspace"] == "X_DEMO"
    assert [e["id"] for e in registre["workspaces"]] == ["Autre", "X_DEMO"]
    assert registre["workspaces"][1]["name"] == "X"


def test_un_serveur_qui_tourne_empeche_la_restauration(monkeypatch, tmp_path):
    monkeypatch.setattr(restaurer, "kovex_repond", lambda api: True)
    assert restaurer.main(["--racine", str(tmp_path)]) == 2


# -- la version de Kovex ------------------------------------------------------


def _instantane_minimal(tmp_path, version):
    instantane = tmp_path / "instantane"
    instantane.mkdir()
    _archive(instantane / "X_DEMO.tar.gz", [("X_DEMO/config.json", "{}")])
    (instantane / "index.json").write_text(json.dumps({
        "construit_le": "2026-09-28", "kovex_version": version,
        "espaces": [{"id": "X_DEMO", "name": "X"}]}), encoding="utf-8")
    racine = tmp_path / "kovex"
    racine.mkdir()
    return instantane, racine


def test_la_version_se_lit_dans_le_fichier_d_archive(tmp_path):
    (tmp_path / restaurer.FICHIER_VERSION).write_text("abc123\n", encoding="utf-8")
    assert restaurer.version_de_kovex(tmp_path) == "abc123"


def test_une_autre_version_de_kovex_est_refusee(tmp_path):
    instantane, racine = _instantane_minimal(tmp_path, "aaaa")
    (racine / restaurer.FICHIER_VERSION).write_text("bbbb", encoding="utf-8")
    with pytest.raises(restaurer.RestaurationRefusee, match="aaaa"):
        restaurer.restaurer(racine, instantane, {"assistance": {}}, None, date(2026, 9, 28))
    # Pas un octet écrit avant le refus.
    assert not (racine / "workspaces").exists()


def test_la_version_peut_etre_forcee(tmp_path):
    instantane, racine = _instantane_minimal(tmp_path, "aaaa")
    (racine / restaurer.FICHIER_VERSION).write_text("bbbb", encoding="utf-8")
    restaures, _, _ = restaurer.restaurer(racine, instantane, {"assistance": {}}, None,
                                          date(2026, 9, 28), forcer_version=True)
    assert restaures == ["X_DEMO"]


def test_la_meme_version_passe(tmp_path):
    instantane, racine = _instantane_minimal(tmp_path, "aaaa")
    (racine / restaurer.FICHIER_VERSION).write_text("aaaa", encoding="utf-8")
    restaures, _, _ = restaurer.restaurer(racine, instantane, {"assistance": {}}, None,
                                          date(2026, 9, 28))
    assert restaures == ["X_DEMO"]


def test_sans_fichier_ni_depot_la_version_est_inconnue(tmp_path):
    """`git -C` remonterait au dépôt parent : il ne doit pas être consulté."""
    assert restaurer.version_de_kovex(tmp_path) is None


# -- la copie de Kovex ---------------------------------------------------------


import subprocess  # noqa: E402

import mettre_a_jour_kovex  # noqa: E402


def _depot(tmp_path, fichiers):
    depot = tmp_path / "source"
    depot.mkdir()
    for nom, contenu in fichiers.items():
        (depot / nom).parent.mkdir(parents=True, exist_ok=True)
        (depot / nom).write_text(contenu, encoding="utf-8")
    for commande in (["init", "-q"], ["add", "-A"],
                     ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "v"]):
        subprocess.run(["git", "-C", str(depot)] + commande, check=True)
    return depot


def test_la_copie_ecarte_la_page_et_les_tests_et_note_la_version(tmp_path):
    depot = _depot(tmp_path, {"run_api.py": "x", "src/a.py": "a",
                              "pages/gros.whl": "w", "tests/t.py": "t", "page/p.js": "p"})
    cible = tmp_path / "kovex"
    complet = mettre_a_jour_kovex.mettre_a_jour(depot, "HEAD", cible)
    assert (cible / "src" / "a.py").exists()
    assert not (cible / "pages").exists() and not (cible / "tests").exists()
    assert not (cible / "page").exists()
    assert restaurer.version_de_kovex(cible) == complet


def test_une_mise_a_jour_garde_ce_qui_vit_sur_le_serveur(tmp_path):
    depot = _depot(tmp_path, {"run_api.py": "x", "src/ancien.py": "a"})
    cible = tmp_path / "kovex"
    mettre_a_jour_kovex.mettre_a_jour(depot, "HEAD", cible)
    (cible / ".env").write_text("SECRET", encoding="utf-8")
    (cible / "workspaces").mkdir()
    (cible / "workspaces" / "w.json").write_text("{}", encoding="utf-8")
    (depot / "src" / "ancien.py").unlink()
    (depot / "src" / "nouveau.py").write_text("n", encoding="utf-8")
    subprocess.run(["git", "-C", str(depot), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(depot), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-q", "-m", "v2"], check=True)
    mettre_a_jour_kovex.mettre_a_jour(depot, "HEAD", cible)
    assert (cible / ".env").read_text(encoding="utf-8") == "SECRET"
    assert (cible / "workspaces" / "w.json").exists()
    assert not (cible / "src" / "ancien.py").exists()
    assert (cible / "src" / "nouveau.py").exists()


# -- le site ------------------------------------------------------------------


import construire_le_site  # noqa: E402

PONT = ("(function () {\n  async function monterLeDisque(p) {}\n"
        "  async function demarrer() {\n    await monterLeDisque(pyodide);\n  }\n})();\n")


def test_l_amorce_s_insere_une_fois_aux_deux_ancres():
    resultat = construire_le_site.inserer_l_amorce(PONT, "  async function amorcerLaDemo(p) {}\n")
    assert resultat.count("async function amorcerLaDemo") == 1
    assert "    await monterLeDisque(pyodide);\n    await amorcerLaDemo(pyodide);\n" in resultat


def test_une_ancre_deplacee_arrete_la_construction():
    with pytest.raises(construire_le_site.SiteImpossible):
        construire_le_site.inserer_l_amorce(PONT.replace("monterLeDisque(pyodide)", "x()"), "")


def test_le_pont_change_d_adresse_pour_ne_pas_etre_servi_du_cache():
    html = '<script src="moteur/pont.js?v=abc"></script>'
    assert construire_le_site.marquer_le_pont(html) == \
        '<script src="moteur/pont.js?demo=1&v=abc"></script>'


def test_le_site_embarque_l_amorce_et_rien_de_secret(tmp_path):
    pages = tmp_path / "pages"
    (pages / "moteur").mkdir(parents=True)
    (pages / "moteur" / "kovex-src.zip").write_bytes(b"PK")
    (pages / "moteur" / "pont.js").write_text(PONT, encoding="utf-8")
    (pages / "index.html").write_text('<script src="moteur/pont.js?v=1"></script>',
                                      encoding="utf-8")
    sortie = tmp_path / "docs"
    construire_le_site.construire(pages, sortie)
    publies = {f.relative_to(sortie).as_posix() for f in sortie.rglob("*") if f.is_file()}
    assert "amorce/index.json" in publies and "amorce/restaurer.py" in publies
    assert ".nojekyll" in publies
    assert not any(n.endswith((".env", "users.json", "cles_annotateur.json")) for n in publies)
    assert "cle" not in json.loads((sortie / "amorce" / "modele.json").read_text(
        encoding="utf-8"))["prereglage"]


def test_une_page_sans_archive_du_produit_est_refusee(tmp_path):
    (tmp_path / "pages" / "moteur").mkdir(parents=True)
    with pytest.raises(construire_le_site.SiteImpossible):
        construire_le_site.construire(tmp_path / "pages", tmp_path / "docs")


# -- l'habillage ----------------------------------------------------------------


import habiller  # noqa: E402

BASE_WAVESTONE = RACINE / "config" / "themes" / "wavestone" / "theme.json"


@pytest.mark.parametrize("theme", sorted(p.name for p in habiller.HABILLAGE.iterdir()
                                          if (p / "theme.json").exists()))
def test_chaque_habillage_est_un_theme_que_kovex_accepte(tmp_path, theme):
    """Couleurs Wavestone, logo du client : validé par le lecteur du produit."""
    from src.core.workspaces import theme_visuel
    dossier = tmp_path / theme
    dossier.mkdir()
    (dossier / "theme.json").write_bytes(habiller.document_du_theme(theme, base=BASE_WAVESTONE))
    (dossier / "logo.png").write_bytes((habiller.HABILLAGE / theme / "logo.png").read_bytes())
    lu = theme_visuel.charger(dossier, theme)
    assert lu.logo == "logo.png"
    base = json.loads(BASE_WAVESTONE.read_text(encoding="utf-8"))["variantes"]
    assert lu.variantes["dark"] == {k: v.lower() for k, v in base["dark"].items()}


def test_chaque_secteur_a_son_habillage():
    themes = habiller.themes_par_client()
    for fiche in FICHES:
        document = json.loads(fiche.read_text(encoding="utf-8"))
        assert themes[document["client"]] == document["theme"]
        assert (habiller.HABILLAGE / document["theme"] / "logo.png").exists()


def test_habiller_une_archive_pose_le_theme_et_garde_le_reste(tmp_path):
    archive = tmp_path / "X_DEMO.tar.gz"
    _archive(archive, [("X_DEMO/config.json", "{}")])
    habiller.habiller_l_archive(archive, "X_DEMO", "alvea", base=BASE_WAVESTONE)
    habiller.habiller_l_archive(archive, "X_DEMO", "alvea", base=BASE_WAVESTONE)
    with tarfile.open(archive) as tar:
        noms = sorted(tar.getnames())
    assert noms == ["X_DEMO/config.json", "X_DEMO/themes/alvea/logo.png",
                    "X_DEMO/themes/alvea/theme.json"]
