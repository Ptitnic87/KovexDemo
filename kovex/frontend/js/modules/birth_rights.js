/**
 * Détection des droits socles.
 *
 * Un droit socle est détenu par la quasi-totalité de la population : badge,
 * messagerie, intranet. Isolé avant le mining, il cesse de rapprocher des
 * identités qui n'ont rien d'autre en commun.
 *
 * Trois défauts corrigés ici :
 *
 * 1. les deux appels passaient par `fetch` sans en-tête d'authentification.
 *    L'authentification étant active par défaut, l'écran répondait 401 : le
 *    bouton semblait ne rien faire ;
 * 2. le nom du fichier téléchargé était écrit en dur
 *    (`01_birth_rights_candidates.xlsx`), ignorant celui que le serveur
 *    annonce — donc restant l'ancien nom quel que soit le produit ;
 * 3. une dizaine de libellés étaient écrits en français dans le code, et les
 *    replis passaient par `alert()`.
 */

const BirthRightsManager = {
    detectedRights: [],
    currentThreshold: 90,
    //: Les droits socles enregistrés — ce que le mining écarte aujourd'hui.
    socles: [],
    //: Le tableau de la fenêtre des socles, construit à la première ouverture.
    tableauDesSocles: null,

    init() {
        this.bindEvents();
    },

    bindEvents() {
        const detection = document.getElementById('launch-birth-rights-detection');
        if (detection) {
            detection.addEventListener('click', () => this.detectBirthRights());
        }

        const exportation = document.getElementById('export-birth-rights');
        if (exportation) {
            exportation.addEventListener('click', () => this.exportToExcel());
        }

        const nom = document.getElementById('save-socle-name');
        if (nom) {
            nom.addEventListener('click', () => this.enregistrerLeNom());
        }

        const voir = document.getElementById('birth-rights-show');
        if (voir) {
            voir.addEventListener('click', () => this.montrerLesSocles());
        }
    },

    /**
     * Le bouton qui ouvre la liste des socles dit combien il y en a, et
     * n'apparaît que s'il y en a : un bouton qui ouvre une liste vide
     * apprendrait à ne plus cliquer.
     */
    majBoutonDesSocles() {
        const bouton = document.getElementById('birth-rights-show');
        const libelle = document.getElementById('birth-rights-show-label');
        if (!bouton) return;
        bouton.hidden = this.socles.length === 0;
        if (libelle) {
            libelle.textContent = I18n.t('birth_rights.show_registered',
                                         { count: Utils.formatNumber(this.socles.length) });
        }
    },

    /**
     * Les droits socles enregistrés, dans une fenêtre, avec les colonnes du
     * référentiel des droits.
     *
     * La détection disait combien ; rien ne disait lesquels sans relancer
     * l'export. Le tableau est celui des autres écrans — recherche, tri,
     * choix des colonnes — et lit les identifiants enregistrés, pas ceux
     * d'une détection en cours : c'est ce que le mining écarte vraiment.
     */
    montrerLesSocles() {
        if (!this.tableauDesSocles) {
            this.tableauDesSocles = new DataTable({
                type: 'socles',
                endpoint: '/referentiels/rights/lignes',
                theadId: 'socles-thead',
                tbodyId: 'socles-list',
                searchId: 'socles-search',
                countId: 'socles-count',
                paginationPrefix: 'socles',
                detail: false,
                messageVide: 'birth_rights.none_registered',
                corps: () => ({ identifiants: this.socles }),
            });
        }
        const tableau = this.tableauDesSocles;
        tableau.state.page = 1;
        tableau.state.search = '';
        tableau.state.sortCol = null;
        tableau.state.sortDesc = false;
        const recherche = document.getElementById('socles-search');
        if (recherche) recherche.value = '';
        tableau.load();
        Modal.open('birth-rights-modal');
    },

    /**
     * Relit le nom du socle et la détection en place.
     *
     * L'écran se rouvre après une détection faite un autre jour : sans cette
     * lecture, le champ du nom serait vide alors que le socle en porte un, et
     * l'enregistrer l'effacerait sans que personne ne l'ait demandé.
     */
    async chargerLeSocle() {
        const champ = document.getElementById('socle-name');
        if (!champ) return;
        try {
            const info = await API.get('/kb/birth-rights/info');
            champ.value = info.name || '';
            this.currentThreshold = info.threshold || this.currentThreshold;
            this.socles = Array.isArray(info.rights) ? info.rights.map(String) : [];
            this.majBoutonDesSocles();
        } catch (erreur) {
            // L'écran sert d'abord à détecter : un nom illisible ne doit pas
            // empêcher la détection. Le champ reste vide, et l'enregistrer
            // reste un geste explicite.
            champ.value = '';
        }
    },

    /** Donne au socle le nom sous lequel l'IGA le recevra. */
    async enregistrerLeNom() {
        const champ = document.getElementById('socle-name');
        if (!champ) return;
        const bouton = document.getElementById('save-socle-name');
        const rendre = this._occuper(bouton, 'common.loading');
        const nom = champ.value.trim();
        try {
            const reponse = await API.put('/kb/birth-rights/name', {name: nom});
            champ.value = reponse.name || '';
            Toast.success(I18n.t('common.success'),
                          reponse.name
                              ? I18n.t('role.socle.name.saved', {nom: reponse.name})
                              : I18n.t('role.socle.name.cleared'));
        } catch (erreur) {
            Toast.error(I18n.t('common.error'), erreur.message);
        } finally {
            rendre();
        }
    },

    /** Met un bouton en attente et rend de quoi le rétablir. */
    _occuper(bouton, cleLibelle) {
        if (!bouton) return () => {};
        const initial = bouton.innerHTML;
        bouton.disabled = true;
        bouton.innerHTML = `<i class="fas fa-circle-notch fa-spin" aria-hidden="true"></i> ${
            Utils.escapeHtml(I18n.t(cleLibelle))}`;
        return () => {
            bouton.innerHTML = initial;
            bouton.disabled = false;
        };
    },

    async detectBirthRights() {
        const bouton = document.getElementById('launch-birth-rights-detection');
        const resultats = document.getElementById('birth-rights-results');
        const exportation = document.getElementById('export-birth-rights');
        const seuilSaisi = document.getElementById('birth-rights-threshold');

        if (!bouton || !resultats || !exportation || !seuilSaisi) {
            Toast.error(I18n.t('common.error'),
                        I18n.t('error.html_elements_missing'));
            return;
        }

        const seuil = parseFloat(seuilSaisi.value);
        if (!Number.isFinite(seuil) || seuil < 0 || seuil > 100) {
            Toast.error(I18n.t('common.error'),
                        I18n.t('birth_rights.threshold_out_of_range'));
            return;
        }
        this.currentThreshold = seuil;

        const rendre = this._occuper(bouton, 'birth_rights.detecting');

        try {
            // Le client d'API porte le jeton et traduit les refus du serveur.
            // L'appel direct à `fetch` ne faisait ni l'un ni l'autre.
            const donnees = await API.post('/birth-rights/detect',
                                           { frequency_threshold: seuil });

            this.detectedRights = donnees.birth_rights || [];

            if (typeof KnowledgeBase !== 'undefined' && KnowledgeBase.setBirthRights) {
                try {
                    const enregistres = this.detectedRights.map(droit => String(droit.ID_droit || droit));
                    await KnowledgeBase.setBirthRights(enregistres, seuil);
                    this.socles = enregistres;
                    this.majBoutonDesSocles();
                } catch (erreur) {
                    // La détection reste exploitable si l'enregistrement
                    // échoue ; on le dit plutôt que de l'ignorer.
                    Toast.warning(I18n.t('common.error'),
                                  I18n.t('birth_rights.not_saved'));
                }
            }

            this.renderResults(donnees);
            exportation.disabled = this.detectedRights.length === 0;
            resultats.style.display = 'block';

            if (this.detectedRights.length > 0) {
                Toast.success(I18n.t('birth_rights.detection_done'),
                              I18n.t('birth_rights.identified',
                                     { count: this.detectedRights.length, threshold: seuil }));
            } else {
                Toast.info(I18n.t('birth_rights.detection_done'),
                           I18n.t('birth_rights.none_found_threshold', { threshold: seuil }));
            }
        } catch (erreur) {
            Toast.error(I18n.t('common.error'), erreur.message);
        } finally {
            rendre();
            if (typeof MiningPage !== 'undefined' && MiningPage.loadKBStats) {
                MiningPage.loadKBStats();
            }
        }
    },

    renderResults(donnees) {
        const stats = donnees.stats;
        const socle = donnees.socle_role;
        if (!stats || !socle) return;

        const nombre = document.getElementById('birth-rights-count');
        const frequence = document.getElementById('birth-rights-avg-freq');
        const droitsSocle = document.getElementById('birth-rights-socle-rights');

        if (nombre) nombre.textContent = Utils.formatNumber(stats.birth_rights_count || 0);

        if (frequence) {
            const moyenne = stats.avg_frequency_birth_rights;
            // Aucune moyenne quand aucun droit n'est détecté : on l'écrit
            // « non renseigné », pas « N/A », qui n'est traduit nulle part.
            frequence.textContent = (moyenne === null || moyenne === undefined)
                ? I18n.t('common.not_provided')
                : Utils.formatPercent(Number(moyenne));
        }

        if (droitsSocle) {
            droitsSocle.textContent = I18n.t('stats.rights_count',
                                             { count: socle.right_count || 0 });
        }
    },

    async exportToExcel() {
        const bouton = document.getElementById('export-birth-rights');
        const rendre = this._occuper(bouton, 'birth_rights.exporting');

        try {
            // La langue voyage avec la demande : le serveur ne devine pas
            // celle de qui télécharge, et le classeur sortait en français
            // quelle que soit la langue de l'interface.
            const langue = encodeURIComponent(
                (typeof I18n !== 'undefined' && I18n.currentLocale) || 'fr');
            const reponse = await fetch(
                `${Config.API_URL}/birth-rights/export?langue=${langue}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...(typeof Auth !== 'undefined' ? Auth.getAuthHeaders() : {}),
                },
                body: JSON.stringify({ frequency_threshold: this.currentThreshold }),
            });

            if (!reponse.ok) {
                throw new Error(I18n.t('error.http_status', { status: reponse.status }));
            }

            // Le nom du fichier est celui que le serveur annonce : lui seul
            // connaît le nom du produit retenu.
            await Utils.enregistrerReponse(reponse, 'kovex_droits_socles.xlsx');
            Toast.success(I18n.t('birth_rights.export_done'),
                          I18n.t('birth_rights.export_downloaded'));
        } catch (erreur) {
            Toast.error(I18n.t('common.error'), I18n.t('birth_rights.export_failed'));
        } finally {
            rendre();
        }
    },

    /** Droits socles détectés, consommés par les modules de mining. */
    getDetectedRights() {
        return this.detectedRights.map(droit => droit.ID_droit);
    },

    hasDetectedRights() {
        return this.detectedRights.length > 0;
    },
};

window.BirthRightsManager = BirthRightsManager;
