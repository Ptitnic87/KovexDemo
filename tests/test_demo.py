"""La plateforme de démonstration : générateur, restauration, réglage du modèle.

    python -m pytest tests -q

Kovex doit être présent dans ``kovex/`` (``git submodule update --init``) : le
réglage du modèle passe par ses lecteurs.
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
