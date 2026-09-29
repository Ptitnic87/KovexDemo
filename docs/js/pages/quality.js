/**
 * PyGIA Frontend - Page Qualité des données.
 *
 * Deux règles structurent ce fichier :
 *  - aucun texte affiché n'est écrit ici, tout passe par I18n.t ;
 *  - aucun gestionnaire n'est écrit dans un attribut HTML. L'ancienne version
 *    construisait `<a href="#" onclick="QualityPage.showIssueDetails(...)">`
 *    en y sérialisant la liste complète des identifiants. Sur un jeu réel de
 *    3 573 identités cela produisait un attribut de plusieurs dizaines de
 *    milliers de caractères, et surtout le `href="#"` n'était jamais annulé :
 *    le routeur à base de hash voyait la barre d'adresse passer à `#` et
 *    renvoyait au tableau de bord avant que la liste ne s'affiche.
 */

const QualityPage = {
    // Nombre d'identifiants par page dans la modale de détail. Une liste de
    // plusieurs milliers d'entrées injectée d'un bloc fige le rendu.
    TAILLE_PAGE: 200,

    // Listes du dernier rapport, indexées par la clé que le serveur associe à
    // chaque anomalie (`list_key`). Le client n'a ainsi aucune correspondance
    // codée en dur entre un type d'anomalie et le champ qui porte ses IDs.
    listes: {},

    detail: {
        titre: '',
        identifiants: [],
        filtres: [],
        page: 1,
        filtre: '',
    },

    init() {
        this.bindEvents();
        this.chargerLesColonnes();
    },

    // ---------------------------------------------- cohérence des valeurs

    //: Dernière analyse, et le seuil d'effectif qui donne son sens à la
    //  conséquence affichée. Rien n'est appliqué tant que rien n'est accepté.
    coherence: null,

    /**
     * Les colonnes analysables, telles que le serveur les rend.
     *
     * Aucun nom n'est écrit ici : elles viennent des fichiers du client, et le
     * produit ne présume d'aucune. Une colonne de nombres ou de dates est
     * annoncée comme telle — la proximité textuelle y produirait du bruit.
     */
    async chargerLesColonnes() {
        const choix = document.getElementById('coherence-colonne');
        if (!choix) return;
        try {
            const rendu = await API.get('/coherence/colonnes');
            this.colonnesDeCoherence = rendu.colonnes || [];
        } catch (erreur) {
            this.colonnesDeCoherence = [];
        }
        choix.innerHTML = this.colonnesDeCoherence.map((colonne, index) => `
            <option value="${index}">${Utils.escapeHtml(
                `${I18n.t(`quality.referential.${colonne.referentiel}`)} — ${colonne.colonne}`)}</option>`
        ).join('');
        this.majLeBoutonDuModele();
    },

    /**
     * Le bouton d'enrichissement n'apparaît que là où il peut servir.
     *
     * Un bouton qu'on presse pour apprendre qu'il était fermé envoie chercher
     * au mauvais endroit : le serveur dit, colonne par colonne, laquelle est
     * ouverte à un modèle, et l'écran le reprend. Fermé partout, le bouton
     * n'existe pas — c'est le cas le plus fréquent, et il ne doit rien
     * encombrer.
     */
    majLeBoutonDuModele() {
        const bouton = document.getElementById('coherence-enrichir');
        const choix = document.getElementById('coherence-colonne');
        if (!bouton) return;
        const colonne = (this.colonnesDeCoherence || [])[Number(choix && choix.value)];
        const ouverte = Boolean(colonne && colonne.enrichissable);
        // Caché quand aucune colonne n'est ouverte ; visible mais désactivé
        // quand c'est **cette colonne-ci** qui ne l'est pas, avec la phrase qui
        // dit où cela se règle.
        const aucune = !(this.colonnesDeCoherence || []).some((c) => c.enrichissable);
        bouton.hidden = aucune;
        bouton.disabled = !ouverte;
        bouton.title = ouverte ? I18n.t('coherence.enrich_hint')
                               : I18n.t('coherence.enrich_closed');
    },

    /**
     * Demande au modèle les rapprochements que le repérage local ne voit pas.
     *
     * Les grappes rendues rejoignent la même liste que celles du repérage : ce
     * sont les mêmes gestes qui les acceptent ou les refusent, et l'origine
     * affichée dit d'où chacune vient. Rien n'est enregistré ici.
     */
    async enrichirParLeModele() {
        const choix = document.getElementById('coherence-colonne');
        const colonne = (this.colonnesDeCoherence || [])[Number(choix && choix.value)];
        if (!colonne) return;
        const bouton = document.getElementById('coherence-enrichir');
        const libelle = bouton.innerHTML;
        bouton.disabled = true;
        bouton.innerHTML = `<i class="fas fa-spinner fa-spin" aria-hidden="true"></i>`;
        try {
            const rendu = await API.post('/coherence/enrichir', {
                referentiel: colonne.referentiel, colonne: colonne.colonne,
                locale: I18n.currentLocale,
            });
            this.integrerLesGrappesDuModele(colonne, rendu);
            this.renderLaCoherence();
        } catch (erreur) {
            Toast.error(I18n.t('common.error'), erreur.message || I18n.t('common.error'));
        } finally {
            bouton.innerHTML = libelle;
            this.majLeBoutonDuModele();
        }
    },

    /**
     * Ajoute les grappes du modèle à celles qui sont déjà à l'écran.
     *
     * Elles s'ajoutent plutôt qu'elles ne remplacent : le repérage local est
     * complet et utile à lui seul, et une analyse en cours ne doit pas
     * disparaître parce qu'on a posé une question à un modèle. Le serveur a
     * déjà écarté ce que le repérage local propose : aucune n'est en double.
     */
    integrerLesGrappesDuModele(colonne, rendu) {
        const memeColonne = this.coherence
            && this.coherence.referentiel === colonne.referentiel
            && this.coherence.colonne === colonne.colonne;
        if (!memeColonne) {
            this.coherence = {
                referentiel: colonne.referentiel, colonne: colonne.colonne,
                grappes: [], valeurs_analysees: rendu.valeurs_soumises,
                valeurs_non_analysees: 0, typee: false,
                effectif_minimal: rendu.effectif_minimal,
            };
        }
        this.coherence.grappes = [...(this.coherence.grappes || []),
                                  ...(rendu.grappes || [])];
        this.coherence.modele = rendu;
    },

    async analyserLaCoherence() {
        const choix = document.getElementById('coherence-colonne');
        const colonne = (this.colonnesDeCoherence || [])[Number(choix && choix.value)];
        if (!colonne) return;
        const bouton = document.getElementById('coherence-analyser');
        const libelle = bouton.innerHTML;
        bouton.disabled = true;
        bouton.innerHTML = `<i class="fas fa-spinner fa-spin" aria-hidden="true"></i>`;
        try {
            this.coherence = await API.post('/coherence/analyser', {
                referentiel: colonne.referentiel, colonne: colonne.colonne,
            });
            this.coherence.modele = null;
            this.coherence.referentiel = colonne.referentiel;
            this.coherence.colonne = colonne.colonne;
            // Une analyse neuve remplace tout, y compris ce qu'un modèle avait
            // ajouté : deux lectures d'une même colonne ne se mélangent pas,
            // et le compte affiché doit décrire ce qui est à l'écran.
            this.renderLaCoherence();
        } catch (erreur) {
            Toast.error(I18n.t('common.error'), erreur.message || I18n.t('common.error'));
        } finally {
            bouton.disabled = false;
            bouton.innerHTML = libelle;
        }
    },

    /**
     * Les grappes, et pour chacune la conséquence du regroupement.
     *
     * La conséquence est le point décisif, et elle est affichée **avant**
     * l'acceptation : « ces cinq valeurs font une population de 63,
     * au-dessus de votre seuil de 15 — elle était invisible au mining ».
     * C'est la seule mesure qui justifie l'opération.
     */
    renderLaCoherence() {
        const resume = document.getElementById('coherence-resume');
        const zone = document.getElementById('coherence-grappes');
        if (!resume || !zone || !this.coherence) return;

        if (this.coherence.typee) {
            resume.textContent = I18n.t('coherence.typed');
            zone.innerHTML = '';
            return;
        }

        const lignes = [I18n.t('coherence.summary', {
            grappes: (this.coherence.grappes || []).length,
            analysees: this.coherence.valeurs_analysees,
        })];
        if (this.coherence.valeurs_non_analysees > 0) {
            lignes.push(I18n.t('coherence.not_analysed',
                               { count: this.coherence.valeurs_non_analysees }));
        }
        const modele = this.coherence.modele;
        if (modele) {
            lignes.push(I18n.t('coherence.model_submitted', {
                soumises: modele.valeurs_soumises,
                distinctes: modele.valeurs_distinctes,
                modele: modele.modele }));
            // Cinq raisons, cinq phrases. L'écran les additionnait en un seul
            // nombre suivi d'un « ou » : on ne savait pas s'il fallait changer
            // de modèle, revenir sur un refus, ou ne rien faire. Et la somme
            // était fausse — elle mêlait un compte de valeurs à trois comptes
            // de propositions.
            const ecartees = modele.ecartees || {};
            [['valeurs_inconnues', 'coherence.model_dropped_unknown'],
             ['refusees', 'coherence.model_dropped_refused'],
             ['deja_proposees', 'coherence.model_dropped_known'],
             ['trop_courtes', 'coherence.model_dropped_short'],
             ['valeurs_repliees', 'coherence.model_folded']]
                .forEach(([cle, message]) => {
                    const compte = Number(ecartees[cle] || 0);
                    if (compte > 0) lignes.push(I18n.t(message, { count: compte }));
                });
            if (!(modele.grappes || []).length) {
                lignes.push(I18n.t('coherence.model_none'));
            }
        }
        resume.textContent = lignes.join(' ');

        if (!(this.coherence.grappes || []).length) {
            zone.innerHTML = `<p class="form-hint">${
                Utils.escapeHtml(I18n.t('coherence.none'))}</p>`;
            return;
        }
        zone.innerHTML = this.coherence.grappes.map(
            (grappe, index) => this.ligneDeGrappe(grappe, index)).join('');
    },

    ligneDeGrappe(grappe, index) {
        // Chaque valeur se coche. Un groupe juste aux deux tiers était à
        // prendre ou à laisser : « CDI », « C.D.I. » et « CDD » proposées
        // ensemble, les deux premières se recodent, la troisième non. Tout
        // accepter fausse les populations ; tout refuser perd le rapprochement
        // correct **et** mémorise un refus entre « CDI » et « C.D.I. », qui ne
        // sera plus jamais proposé.
        //
        // Les cases disent la **portée** du bouton pressé, rien de plus : une
        // valeur décochée n'est ni acceptée ni refusée, elle est laissée de
        // côté. Le produit ne déduit rien d'une case décochée.
        const valeurs = grappe.valeurs.map((entree, rang) => `
            <li><label class="form-check">
                <input type="checkbox" checked
                       data-grappe-valeur="${index}-${rang}"
                       data-grappe-rang="${index}">
                <span>${Utils.escapeHtml(entree.valeur)}
                    <span class="form-hint">${Utils.escapeHtml(
                        I18n.t('unit.users', {
                            count: Utils.formatNumber(entree.effectif) }))}</span>
                </span></label></li>`
        ).join('');
        const signaux = grappe.signaux.map(
            (signal) => I18n.t(`coherence.signal.${signal}`)).join(', ');
        // La raison invoquée par le modèle, telle qu'il l'a écrite. Aucun
        // contrôle du serveur ne sait ce que les valeurs veulent dire : c'est
        // la seule chose à l'écran qui permette de rattraper un regroupement
        // faux. Elle n'apparaît que si le modèle en a donné une — le repérage
        // local n'argumente pas, il montre des signaux.
        const motif = grappe.motif
            ? `<p class="form-hint" data-grappe-motif="${index}">${
                Utils.escapeHtml(I18n.t('coherence.reason',
                                        { motif: grappe.motif }))}</p>`
            : '';
        const consequence = grappe.invisible_avant
            ? `<p class="alert alert-warning">${Utils.escapeHtml(
                I18n.t('coherence.invisible', {
                    total: Utils.formatNumber(grappe.effectif_total),
                    seuil: Utils.formatNumber(this.coherence.effectif_minimal) }))}</p>`
            : `<p class="form-hint">${Utils.escapeHtml(
                I18n.t('coherence.visible', { total: Utils.formatNumber(grappe.effectif_total) }))}</p>`;

        return `
            <div class="file-config" data-grappe="${index}">
                <ul class="list-bare">${valeurs}</ul>
                <p class="form-hint">${Utils.escapeHtml(signaux)} —
                    ${Utils.escapeHtml(I18n.t(`coherence.origin.${grappe.origine}`))}</p>
                ${motif}
                ${consequence}
                <p class="form-hint">${Utils.escapeHtml(
                    I18n.t('coherence.selection'))}</p>
                <div class="form-group">
                    <label class="form-label" for="coherence-forme-${index}"
                           >${Utils.escapeHtml(I18n.t('coherence.retained'))}</label>
                    <input type="text" class="form-input" id="coherence-forme-${index}"
                           data-grappe-forme="${index}"
                           value="${Utils.escapeHtml(grappe.forme_retenue)}">
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-primary btn-sm"
                            data-grappe-action="accepter" data-grappe-index="${index}">
                        ${Utils.escapeHtml(I18n.t('coherence.accept'))}</button>
                    <button type="button" class="btn btn-secondary btn-sm"
                            data-grappe-action="refuser" data-grappe-index="${index}">
                        ${Utils.escapeHtml(I18n.t('coherence.refuse'))}</button>
                </div>
            </div>`;
    },

    /**
     * Les valeurs cochées d'une grappe, dans l'ordre où elles sont affichées.
     *
     * L'ordre compte : la forme retenue proposée est la plus portée, et une
     * relecture doit retrouver la grappe telle qu'elle était à l'écran.
     */
    valeursCochees(index) {
        const grappe = (this.coherence && this.coherence.grappes || [])[index];
        if (!grappe) return [];
        return grappe.valeurs.filter((_, rang) => {
            const case_ = document.querySelector(
                `[data-grappe-valeur="${index}-${rang}"]`);
            return !case_ || case_.checked;
        }).map((entree) => entree.valeur);
    },

    /**
     * Une valeur seule ne se recode contre rien et ne se refuse avec rien.
     *
     * Laisser les boutons actifs enverrait une demande que le serveur refuse,
     * et l'utilisateur apprendrait la règle par un message d'erreur.
     */
    majLaPorteeDeLaGrappe(index) {
        const cochees = this.valeursCochees(index).length;
        const conteneur = document.querySelector(`[data-grappe="${index}"]`);
        if (!conteneur) return;
        conteneur.querySelectorAll('[data-grappe-action]').forEach((bouton) => {
            bouton.disabled = cochees < 2;
            bouton.title = cochees < 2 ? I18n.t('coherence.selection_short') : '';
        });
    },

    /**
     * Accepte une grappe : elle devient une entrée de table de recodage.
     *
     * La forme retenue est celle du champ, pas celle qui avait été proposée :
     * une organisation peut profiter du recodage pour adopter sa nomenclature
     * cible, y compris une valeur qui n'était dans aucune des deux.
     */
    async agirSurLaGrappe(action, index) {
        const grappe = (this.coherence && this.coherence.grappes || [])[index];
        if (!grappe) return;
        const champ = document.querySelector(`[data-grappe-forme="${index}"]`);
        const forme = ((champ && champ.value) || grappe.forme_retenue).trim();
        // La décision porte sur les valeurs cochées, et sur elles seules. Les
        // autres ne sont ni acceptées ni refusées : elles restent à décider.
        const valeurs = this.valeursCochees(index);
        if (valeurs.length < 2) return;

        try {
            if (action === 'accepter') {
                const rendu = await API.post('/coherence/appliquer', {
                    referentiel: this.coherence.referentiel,
                    colonne: this.coherence.colonne,
                    grappes: [{ valeurs, forme_retenue: forme,
                                origine: grappe.origine }],
                });
                Toast.success(I18n.t('common.success'), I18n.t('coherence.accepted',
                    { count: rendu.entrees_ajoutees }));
            } else {
                await API.post('/coherence/refuser', {
                    referentiel: this.coherence.referentiel,
                    colonne: this.coherence.colonne, valeurs,
                });
                Toast.success(I18n.t('common.success'), I18n.t('coherence.refused'));
            }
        } catch (erreur) {
            Toast.error(I18n.t('common.error'), erreur.message || I18n.t('common.error'));
            return;
        }
        // La grappe traitée quitte l'écran : la relaisser inviterait à la
        // traiter deux fois, et une acceptation répétée réécrirait la même
        // entrée sans le dire.
        this.coherence.grappes.splice(index, 1);
        this.renderLaCoherence();
    },


    bindEvents() {
        const analyser = document.getElementById('coherence-analyser');
        if (analyser) {
            analyser.addEventListener('click', () => this.analyserLaCoherence());
        }
        const enrichir = document.getElementById('coherence-enrichir');
        if (enrichir) {
            enrichir.addEventListener('click', () => this.enrichirParLeModele());
        }
        const colonne = document.getElementById('coherence-colonne');
        if (colonne) {
            colonne.addEventListener('change', () => this.majLeBoutonDuModele());
        }

        // Délégation : les grappes sont réécrites après chaque décision.
        const grappes = document.getElementById('coherence-grappes');
        if (grappes) {
            grappes.addEventListener('click', (evenement) => {
                const bouton = evenement.target.closest('[data-grappe-action]');
                if (!bouton) return;
                evenement.preventDefault();
                this.agirSurLaGrappe(bouton.dataset.grappeAction,
                                     Number(bouton.dataset.grappeIndex));
            });
            grappes.addEventListener('change', (evenement) => {
                const case_ = evenement.target.closest('[data-grappe-rang]');
                if (!case_) return;
                this.majLaPorteeDeLaGrappe(Number(case_.dataset.grappeRang));
            });
        }

        const recertifyBtn = document.getElementById('launch-recertification');
        if (recertifyBtn) {
            recertifyBtn.addEventListener('click', () => this.launchRecertification());
        }

        const exportExcelBtn = document.getElementById('export-excel-btn');
        if (exportExcelBtn) {
            exportExcelBtn.addEventListener('click', () => this.exportExcel());
        }

        const exportPdfBtn = document.getElementById('export-pdf-btn');
        if (exportPdfBtn) {
            exportPdfBtn.addEventListener('click', () => this.exportPDF());
        }

        // Délégation : la liste des anomalies est reconstruite à chaque
        // chargement, un écouteur posé sur chaque bouton serait perdu.
        const issuesList = document.getElementById('issues-list');
        if (issuesList) {
            issuesList.addEventListener('click', (evenement) => {
                const bouton = evenement.target.closest('[data-issue-list]');
                if (!bouton) return;
                evenement.preventDefault();
                this.showIssueDetails(
                    bouton.dataset.issueTitle,
                    this.listes[bouton.dataset.issueList] || []
                );
            });
        }

        const panneau = document.getElementById('transformations-panel');
        if (panneau) {
            panneau.addEventListener('click', (evenement) => {
                const bouton = evenement.target.closest('[data-transformation-diff]');
                if (!bouton) return;
                evenement.preventDefault();
                this.ouvrirDifferences(bouton.dataset.transformationDiff);
            });
        }

        this.bindDetailEvents();
        this.bindDifferenceEvents();
    },

    bindDifferenceEvents() {
        const recherche = document.getElementById('transformation-diff-search');
        if (recherche) {
            recherche.addEventListener('input', () => {
                this.diff.filtre = recherche.value.trim();
                this.diff.page = 1;
                this.chargerDifferences();
            });
        }

        const precedent = document.getElementById('transformation-diff-prev');
        if (precedent) {
            precedent.addEventListener('click', () => this.changerPageDiff(-1));
        }

        const suivant = document.getElementById('transformation-diff-next');
        if (suivant) {
            suivant.addEventListener('click', () => this.changerPageDiff(1));
        }
    },

    bindDetailEvents() {
        const recherche = document.getElementById('issue-details-search');
        if (recherche) {
            recherche.addEventListener('input', () => {
                this.detail.filtre = recherche.value.trim().toLowerCase();
                this.detail.page = 1;
                this.appliquerFiltre();
                this.renderDetails();
            });
        }

        const precedent = document.getElementById('issue-details-prev');
        if (precedent) {
            precedent.addEventListener('click', () => this.changerPage(-1));
        }

        const suivant = document.getElementById('issue-details-next');
        if (suivant) {
            suivant.addEventListener('click', () => this.changerPage(1));
        }

        const exportCsv = document.getElementById('issue-details-export');
        if (exportCsv) {
            exportCsv.addEventListener('click', () => this.exporterDetails());
        }
    },

    async load() {
        const issuesList = document.getElementById('issues-list');
        if (!issuesList) return;

        const setLoadingMessage = (message) => {
            const el = document.getElementById('loading-message');
            if (el) el.textContent = message;
        };

        issuesList.innerHTML = `
            <li class="issue-item loading">
                <div class="loading-spinner"></div>
                <span id="loading-message">${Utils.escapeHtml(I18n.t('quality.loading_init'))}</span>
            </li>
        `;

        try {
            setLoadingMessage(I18n.t('quality.loading_step2'));
            const report = await API.getDataStatus();
            setLoadingMessage(I18n.t('quality.loading_step3'));

            this.memoriserListes(report);
            this.renderCards(report);
            this.renderIssues(report);
            this.renderKeyPolicy(report);
            this.renderTransformations(report);
            this.animateCards();
        } catch (error) {
            issuesList.innerHTML = `
                <li class="issue-item">
                    <span class="issue-desc text-danger">
                         <i class="fas fa-exclamation-triangle me-2" aria-hidden="true"></i>
                         ${Utils.escapeHtml(I18n.t('error.load_data_failed'))}
                    </span>
                </li>
            `;
        }
    },

    memoriserListes(report) {
        this.listes = {};
        Object.keys(report || {}).forEach((cle) => {
            if (cle.endsWith('_list') && Array.isArray(report[cle])) {
                this.listes[cle] = report[cle];
            }
        });
    },

    /**
     * Renseigne une carte d'indicateur.
     *
     * Un contrôle que la configuration ne permet pas de calculer n'affiche pas
     * zéro : un zéro se lit « aucune anomalie », alors que la réalité est
     * « non vérifié ». La carte est alors neutralisée et explique pourquoi.
     */
    renderCard(id, valeur, disponible) {
        const el = document.getElementById(id);
        if (!el) return;
        const carte = el.closest('.quality-card');
        if (disponible === false) {
            el.textContent = '—';
            if (carte) {
                carte.classList.add('unavailable');
                carte.title = I18n.t('quality.check_unavailable');
            }
            return;
        }
        el.textContent = valeur || 0;
        if (carte) {
            carte.classList.remove('unavailable');
            carte.removeAttribute('title');
        }
    },

    renderCards(report) {
        const disponible = report.checks_available || {};
        this.renderCard('orphan-rights-count', report.orphan_rights_count, true);
        this.renderCard('orphan-users-count', report.orphan_users_count, true);
        this.renderCard('forest-users-count', report.forest_users_count, true);
        this.renderCard('broken-habs-count', report.broken_habs_count, true);
        this.renderCard('unused-rights-count', report.unused_rights_count,
                        disponible.unused_rights);
        this.renderCard('rights-without-app-count', report.rights_without_app_count,
                        disponible.rights_without_app);
        this.renderCard('unknown-app-refs-count', report.unknown_app_refs_count,
                        disponible.unknown_app_refs);
        this.renderCard('empty-applications-count', report.empty_applications_count,
                        disponible.empty_applications);
        this.renderCard('unused-applications-count', report.unused_applications_count,
                        disponible.unused_applications);
        // Une seule carte pour les trois référentiels : ce qui intéresse la
        // gouvernance est qu'il y ait des doublons, le détail des listes dit
        // lesquels et où.
        this.renderCard(
            'duplicate-ids-count',
            (report.duplicate_users_count || 0)
                + (report.duplicate_rights_count || 0)
                + (report.duplicate_applications_count || 0),
            true
        );
    },

    // Titre de la modale de détail, par type d'anomalie. Le serveur nomme le
    // champ qui porte les identifiants, le client nomme ce qu'il affiche.
    TITRES: {
        orphan_users_list: 'quality.ids_orphan_users',
        orphan_rights_list: 'quality.ids_orphan_rights',
        forest_users_list: 'quality.ids_forest_users',
        unused_rights_list: 'quality.ids_unused_rights',
        rights_without_app_list: 'quality.ids_rights_without_app',
        unknown_app_refs_list: 'quality.ids_unknown_app_refs',
        empty_applications_list: 'quality.ids_empty_applications',
        unused_applications_list: 'quality.ids_unused_applications',
        duplicate_users_list: 'quality.ids_duplicate_users',
        duplicate_rights_list: 'quality.ids_duplicate_rights',
        duplicate_applications_list: 'quality.ids_duplicate_applications',
        truncated_rights_list: 'quality.ids_truncated_rights',
    },

    SEVERITES: {
        critical: 'quality.severity.critical',
        warning: 'quality.severity.warning',
        info: 'quality.severity.info',
    },

    renderIssues(report) {
        const issuesList = document.getElementById('issues-list');
        if (!issuesList) return;

        const issues = report.issues_summary || [];

        if (issues.length === 0) {
            issuesList.innerHTML = `
                <li class="issue-item">
                    <span class="issue-desc text-success">
                        <i class="fas fa-check-circle me-2" aria-hidden="true"></i>
                        ${Utils.escapeHtml(I18n.t('quality.no_major_issues'))}
                    </span>
                </li>
            `;
            return;
        }

        issuesList.innerHTML = issues.map((issue) => {
            const cleListe = issue.list_key;
            const identifiants = cleListe ? (this.listes[cleListe] || []) : [];
            const severite = issue.severity || 'info';

            let detailHtml = '';
            if (identifiants.length > 0 && this.TITRES[cleListe]) {
                const titre = I18n.t(this.TITRES[cleListe]);
                detailHtml = `
                    <button type="button" class="btn-link btn-sm ms-3"
                            data-issue-list="${Utils.escapeHtml(cleListe)}"
                            data-issue-title="${Utils.escapeHtml(titre)}">
                        ${Utils.escapeHtml(I18n.t('quality.show_details', { count: Utils.formatNumber(identifiants.length) }))}
                    </button>`;
            }

            const libelleSeverite = I18n.t(this.SEVERITES[severite] || this.SEVERITES.info);

            return `
                <li class="issue-item severity-${Utils.escapeHtml(severite)}">
                    <span class="issue-severity">${Utils.escapeHtml(libelleSeverite)}</span>
                    <span class="issue-desc">${Utils.escapeHtml(I18n.t(issue.description_key, Utils.parametresDansLaLangue(issue.description_params)))}</span>
                    <span class="issue-count">${Utils.escapeHtml(String(Utils.valeurDansLaLangue(issue.count)))}</span>
                    ${detailHtml}
                </li>
            `;
        }).join('');
    },

    //: Pagination de la modale des valeurs transformées. Le serveur pagine :
    //  sur un fichier d'habilitations, la liste des valeurs changées se compte
    //  en centaines de milliers.
    TAILLE_PAGE_DIFF: 50,

    diff: { referentiel: '', page: 1, filtre: '', total: 0, pages: 1 },

    /**
     * Ce que les transformations déclarées ont changé, règle par règle.
     *
     * Une règle dont la colonne n'existe pas n'affiche pas « 0 valeur
     * changée » : elle affiche qu'elle n'a rien fait, et pourquoi. C'est la
     * panne silencieuse de ce mécanisme — une correction qu'on croit active et
     * qui ne l'est pas laisse exactement le défaut qu'elle devait réparer.
     *
     * @param {Object} report rapport de qualité rendu par le serveur.
     */
    renderTransformations(report) {
        const panneau = document.getElementById('transformations-panel');
        if (!panneau) return;

        const transformations = (report && report.transformations) || {};
        const regles = transformations.rules || [];

        const alertes = [];
        if (transformations.invalid) {
            alertes.push(this.ligneAlerte('critical', I18n.t(
                'quality.transformations.invalid', {
                    reason: transformations.invalid.reason,
                    field: transformations.invalid.field,
                    value: transformations.invalid.value,
                })));
        }
        if (regles.length === 0) {
            alertes.push(this.ligneAlerte(
                'info', I18n.t('quality.transformations.none')));
            panneau.innerHTML = alertes.join('');
            return;
        }

        const entetes = ['referential', 'column', 'operation', 'changed', 'produced']
            .map((cle) => `<th scope="col">${Utils.escapeHtml(
                I18n.t(`quality.transformations.col.${cle}`))}</th>`).join('');

        const referentiels = [];
        regles.forEach((regle) => {
            if (referentiels.indexOf(regle.referential) === -1) {
                referentiels.push(regle.referential);
            }
        });

        panneau.innerHTML = `
            ${alertes.join('')}
            <table class="key-policy-table">
                <thead><tr>${entetes}</tr></thead>
                <tbody>${regles.map((r) => this.ligneRegle(r)).join('')}</tbody>
            </table>
            <div class="transformation-actions">
                ${referentiels.map((referentiel) => `
                    <button type="button" class="btn-link btn-sm"
                            data-transformation-diff="${Utils.escapeHtml(referentiel)}">
                        ${Utils.escapeHtml(I18n.t('quality.transformations.show_differences'))}
                        — ${Utils.escapeHtml(I18n.t(`quality.referential.${referentiel}`))}
                    </button>`).join('')}
            </div>
        `;
    },

    ligneRegle(regle) {
        const nom = Utils.escapeHtml(
            I18n.t(`quality.referential.${regle.referential}`));
        const operation = Utils.escapeHtml(
            I18n.t(`transformation.operation.${regle.operation}`));

        if (!regle.applicable) {
            return `<tr class="key-policy-row unavailable">
                <td>${nom}</td>
                <td>${Utils.escapeHtml(regle.column)}</td>
                <td>${operation}</td>
                <td colspan="2">${Utils.escapeHtml(
                    I18n.t('quality.transformations.not_applicable'))}</td>
            </tr>`;
        }

        const echantillon = (regle.sample || []).map((couple) => I18n.t(
            'quality.transformations.sample',
            { before: couple.before, after: couple.after })).join(' — ');
        const detail = echantillon === '' ? '' : `
            <tr class="key-policy-detail">
                <td colspan="5">${Utils.escapeHtml(echantillon)}</td>
            </tr>`;

        return `<tr class="key-policy-row">
                <td>${nom}</td>
                <td>${Utils.escapeHtml(regle.column)}</td>
                <td>${operation}</td>
                <td>${Utils.escapeHtml(String(Utils.valeurDansLaLangue(regle.values_changed)))}</td>
                <td>${Utils.escapeHtml(String(Utils.valeurDansLaLangue(regle.rows_produced)))}</td>
            </tr>${detail}`;
    },

    // Libellés des actions, par champ. Deux familles distinctes : « écarter »
    // ne veut pas dire la même chose d'une clé vide (la ligne part) et d'un
    // doublon (toutes les occurrences partent), et un libellé partagé ferait
    // croire à un traitement commun.
    ACTIONS: {
        empty_key: 'key_policy.empty_key',
        duplicate_key: 'key_policy.duplicate_key',
    },

    /**
     * Ce que la politique de qualité des clés a fait de chaque référentiel.
     *
     * Un référentiel dont la colonne de clé n'a pas été associée n'affiche pas
     * zéro anomalie : il affiche qu'il n'a pas été vérifié, et lesquelles de
     * ses colonnes manquent. C'est la même règle que pour les cartes.
     *
     * @param {Object} report rapport de qualité rendu par le serveur.
     */
    renderKeyPolicy(report) {
        const panneau = document.getElementById('key-policy-panel');
        if (!panneau) return;

        const politique = (report && report.key_policy) || {};
        const referentiels = politique.referentials || [];

        const alertes = [];
        if (politique.invalid) {
            alertes.push(this.ligneAlerte('critical', I18n.t(
                'quality.key_policy.invalid', {
                    field: politique.invalid.field,
                    value: politique.invalid.value,
                    expected: (politique.invalid.expected || []).join(', '),
                })));
        }
        if (politique.refused) {
            alertes.push(this.ligneAlerte('critical', I18n.t(
                'quality.key_policy.refused', {
                    referential: I18n.t(`quality.referential.${politique.refused.referential}`),
                    reason: I18n.t(`key_policy.reason.${politique.refused.reason}`),
                })));
        }
        if (alertes.length === 0 && !politique.rows_discarded) {
            alertes.push(this.ligneAlerte('info', I18n.t('quality.key_policy.none')));
        }

        if (referentiels.length === 0) {
            panneau.innerHTML = alertes.join('');
            return;
        }

        const entetes = ['referential', 'empty_key', 'duplicate_key',
                         'rows_read', 'rows_kept', 'rows_discarded']
            .map((cle) => `<th scope="col">${Utils.escapeHtml(
                I18n.t(`quality.key_policy.col.${cle}`))}</th>`).join('');

        const lignes = referentiels.map((r) => this.ligneReferentiel(r)).join('');

        panneau.innerHTML = `
            ${alertes.join('')}
            <table class="key-policy-table">
                <thead><tr>${entetes}</tr></thead>
                <tbody>${lignes}</tbody>
            </table>
        `;
    },

    /**
     * Une alerte de politique de clés, et son niveau dit autrement qu'en
     * couleur.
     *
     * La gravité ne vivait que dans la classe : un liseré rouge, orange ou
     * bleu. Pour qui ne distingue pas ces trois teintes — ou ne voit pas
     * l'écran du tout — les trois alertes se lisaient à l'identique. Le
     * libellé est celui qu'affiche déjà la liste des anomalies ; il est ici
     * réservé aux outils d'assistance, la couleur suffisant à l'œil.
     * Critère RGAA 3.1.
     */
    ligneAlerte(severite, texte) {
        const libelle = I18n.t(this.SEVERITES[severite] || this.SEVERITES.info);
        return `<p class="key-policy-alert severity-${Utils.escapeHtml(severite)}">`
            + `<span class="sr-only">${Utils.escapeHtml(libelle)} : </span>`
            + `${Utils.escapeHtml(texte)}</p>`;
    },

    /**
     * Une ligne du tableau, plus sa ligne de détail quand il y a matière.
     *
     * @param {Object} rapport rapport d'un référentiel.
     * @returns {string} le HTML des une ou deux lignes.
     */
    ligneReferentiel(rapport) {
        const nom = Utils.escapeHtml(
            I18n.t(`quality.referential.${rapport.referential}`));

        if (!rapport.applicable) {
            const motif = I18n.t('quality.key_policy.not_applicable', {
                columns: (rapport.missing_columns || []).join(', '),
            });
            return `<tr class="key-policy-row unavailable">
                <td>${nom}</td>
                <td colspan="5">${Utils.escapeHtml(motif)}</td>
            </tr>`;
        }

        const politique = rapport.policy || {};
        const action = (champ) => Utils.escapeHtml(
            I18n.t(`${this.ACTIONS[champ]}.${politique[champ]}`));

        const details = [];
        if (rapport.empty_keys) {
            details.push(I18n.t('quality.key_policy.empty_keys',
                                { count: rapport.empty_keys }));
        }
        if (rapport.duplicate_keys) {
            details.push(I18n.t('quality.key_policy.duplicate_keys',
                                { count: rapport.duplicate_keys }));
        }
        if ((rapport.empty_key_rows_sample || []).length > 0) {
            details.push(I18n.t('quality.key_policy.sample_rows',
                                { rows: rapport.empty_key_rows_sample.join(', ') }));
        }
        if ((rapport.duplicate_keys_sample || []).length > 0) {
            details.push(I18n.t('quality.key_policy.sample_keys',
                                { keys: rapport.duplicate_keys_sample.join(', ') }));
        }

        const detailHtml = details.length === 0 ? '' : `
            <tr class="key-policy-detail">
                <td colspan="6">${Utils.escapeHtml(details.join(' — '))}</td>
            </tr>`;

        return `<tr class="key-policy-row">
                <td>${nom}</td>
                <td>${action('empty_key')}</td>
                <td>${action('duplicate_key')}</td>
                <td>${Utils.escapeHtml(String(Utils.valeurDansLaLangue(rapport.rows_read)))}</td>
                <td>${Utils.escapeHtml(String(Utils.valeurDansLaLangue(rapport.rows_kept)))}</td>
                <td>${Utils.escapeHtml(String(Utils.valeurDansLaLangue(rapport.rows_discarded)))}</td>
            </tr>${detailHtml}`;
    },

    animateCards() {
        const cards = document.querySelectorAll('.quality-card[data-animate]');
        setTimeout(() => Utils.animateIn(cards), 100);
    },

    // === Modale des valeurs transformées ===

    /**
     * Ouvre le détail des valeurs qu'une transformation a changées.
     *
     * L'échantillon du tableau répond à « ma règle fait-elle ce que je crois »
     * ; cette modale répond à l'autre question, celle d'un rapprochement qui
     * échoue : « qu'est-ce que le produit a fait de cet identifiant-là ». La
     * recherche et la pagination sont côté serveur — le total affiché est donc
     * le vrai total, pas la taille de ce qu'on a ramené.
     */
    ouvrirDifferences(referentiel) {
        this.diff = { referentiel, page: 1, filtre: '', total: 0, pages: 1 };

        const champ = document.getElementById('transformation-diff-search');
        if (champ) champ.value = '';

        const titre = document.getElementById('transformation-diff-title');
        if (titre) {
            titre.textContent = I18n.t(
                'quality.transformations.differences_title',
                { referential: I18n.t(`quality.referential.${referentiel}`) });
        }

        if (typeof Modal !== 'undefined'
            && document.getElementById('transformation-diff-modal')) {
            Modal.open('transformation-diff-modal');
        }
        return this.chargerDifferences();
    },

    async chargerDifferences() {
        const corps = document.getElementById('transformation-diff-body');
        if (!corps || !this.diff.referentiel) return;

        try {
            const reponse = await API.getTransformationDifferences(
                this.diff.referentiel, {
                    page: this.diff.page,
                    size: this.TAILLE_PAGE_DIFF,
                    search: this.diff.filtre,
                });
            this.diff.total = reponse.total_items || 0;
            this.diff.pages = Math.max(1, reponse.total_pages || 1);
            this.diff.page = reponse.current_page || 1;
            this.renderDifferences(reponse.data || []);
        } catch (erreur) {
            corps.innerHTML = `<p class="text-danger">${
                Utils.escapeHtml(I18n.t('error.load_data_failed'))}</p>`;
        }
    },

    renderDifferences(lignes) {
        const corps = document.getElementById('transformation-diff-body');
        if (!corps) return;

        corps.innerHTML = lignes.length === 0
            ? `<p>${Utils.escapeHtml(I18n.t('quality.transformations.empty'))}</p>`
            : `<table class="key-policy-table">
                <thead><tr>
                    <th scope="col">${Utils.escapeHtml(I18n.t('quality.transformations.col.column'))}</th>
                    <th scope="col">${Utils.escapeHtml(I18n.t('quality.transformations.before'))}</th>
                    <th scope="col">${Utils.escapeHtml(I18n.t('quality.transformations.after'))}</th>
                </tr></thead>
                <tbody>${lignes.map((ligne) => `<tr>
                    <td>${Utils.escapeHtml(String(ligne.column))}</td>
                    <td>${Utils.escapeHtml(String(ligne.before))}</td>
                    <td>${Utils.escapeHtml(String(ligne.after))}</td>
                </tr>`).join('')}</tbody>
            </table>`;

        const compteur = document.getElementById('transformation-diff-count');
        if (compteur) {
            compteur.textContent = I18n.t('quality.transformations.count',
                                          { count: this.diff.total });
        }

        const page = document.getElementById('transformation-diff-page');
        if (page) {
            page.textContent = I18n.t('quality.details.page', {
                page: this.diff.page, pages: this.diff.pages });
        }
    },

    changerPageDiff(pas) {
        const cible = this.diff.page + pas;
        if (cible < 1 || cible > this.diff.pages) return;
        this.diff.page = cible;
        return this.chargerDifferences();
    },

    // === Modale de détail ===

    showIssueDetails(titre, identifiants) {
        this.detail = {
            titre: titre || '',
            identifiants: Array.isArray(identifiants) ? identifiants : [],
            filtres: [],
            page: 1,
            filtre: '',
        };
        this.appliquerFiltre();

        const champ = document.getElementById('issue-details-search');
        if (champ) champ.value = '';

        const titreEl = document.getElementById('issue-details-title');
        if (titreEl) titreEl.textContent = this.detail.titre;

        this.renderDetails();

        if (typeof Modal !== 'undefined' && document.getElementById('issue-details-modal')) {
            Modal.open('issue-details-modal');
        }
        return false;
    },

    appliquerFiltre() {
        const filtre = this.detail.filtre;
        this.detail.filtres = filtre
            ? this.detail.identifiants.filter((id) => String(id).toLowerCase().includes(filtre))
            : this.detail.identifiants.slice();
    },

    nombrePages() {
        return Math.max(1, Math.ceil(this.detail.filtres.length / this.TAILLE_PAGE));
    },

    changerPage(pas) {
        const cible = this.detail.page + pas;
        if (cible < 1 || cible > this.nombrePages()) return;
        this.detail.page = cible;
        this.renderDetails();
    },

    renderDetails() {
        const corps = document.getElementById('issue-details-body');
        if (!corps) return;

        const pages = this.nombrePages();
        if (this.detail.page > pages) this.detail.page = pages;

        const debut = (this.detail.page - 1) * this.TAILLE_PAGE;
        const tranche = this.detail.filtres.slice(debut, debut + this.TAILLE_PAGE);

        corps.innerHTML = tranche.length === 0
            ? `<p class="issue-details-empty">${Utils.escapeHtml(I18n.t('quality.details.empty'))}</p>`
            : `<ul class="issue-details-ids">${
                tranche.map((id) => `<li>${Utils.escapeHtml(String(id))}</li>`).join('')
              }</ul>`;

        const compteur = document.getElementById('issue-details-count');
        if (compteur) {
            compteur.textContent = I18n.t('quality.details.shown', {
                shown: this.detail.filtres.length,
                total: this.detail.identifiants.length,
            });
        }

        const pagination = document.getElementById('issue-details-page');
        if (pagination) {
            pagination.textContent = I18n.t('quality.details.page', {
                page: this.detail.page,
                pages,
            });
        }

        const precedent = document.getElementById('issue-details-prev');
        if (precedent) precedent.disabled = this.detail.page <= 1;
        const suivant = document.getElementById('issue-details-next');
        if (suivant) suivant.disabled = this.detail.page >= pages;
    },

    /**
     * Export CSV de la liste filtrée, construit côté client : ces
     * identifiants sont déjà dans la page, un aller-retour serveur n'ajoute
     * rien et le poste peut être hors ligne.
     */
    exporterDetails() {
        const lignes = this.detail.filtres.map((id) => {
            const valeur = String(id).replace(/"/g, '""');
            return `"${valeur}"`;
        });
        const contenu = `﻿${lignes.join('\r\n')}\r\n`;
        const blob = new Blob([contenu], { type: 'text/csv;charset=utf-8;' });
        const url = window.URL.createObjectURL(blob);
        const lien = document.createElement('a');
        lien.href = url;
        lien.download = `kovex_${Date.now()}.csv`;
        document.body.appendChild(lien);
        lien.click();
        document.body.removeChild(lien);
        window.URL.revokeObjectURL(url);
    },

    async launchRecertification() {
        const btn = document.getElementById('launch-recertification');
        if (!btn) return;

        const originalText = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = `<i class="fas fa-spinner fa-spin" aria-hidden="true"></i> <span>${Utils.escapeHtml(I18n.t('quality.export.generating'))}</span>`;

        try {
            const result = await API.launchRecertification();

            if (result.status === 'success') {
                // Le serveur rend un code et ses paramètres ; la phrase est
                // composée ici, dans la langue de l'utilisateur.
                Toast.success(I18n.t('quality.recertification_launched'),
                              I18n.t(result.code, result.params || {}));
            } else {
                Toast.warning(I18n.t('common.info'),
                              I18n.t(result.code, result.params || {}));
            }

            await this.load();
        } catch (error) {
            Toast.error(I18n.t('common.error'), I18n.t('quality.recertification_failed'));
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalText;
        }
    },

    /**
     * Télécharge un export produit par le serveur.
     *
     * Le jeton d'authentification interdit un simple lien : la requête doit
     * porter l'en-tête `Authorization`, d'où le passage par fetch + Blob.
     */
    async telechargerExport(idBouton, chemin, extension, entetes, messageDepart, messageFin) {
        const btn = document.getElementById(idBouton);
        const contenuInitial = btn ? btn.innerHTML : '';
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = `<i class="fas fa-spinner fa-spin" aria-hidden="true"></i> ${Utils.escapeHtml(I18n.t('quality.export.generating'))}`;
        }

        try {
            Toast.info(I18n.t('quality.export.generating'), I18n.t(messageDepart));

            const response = await fetch(`${Config.API_URL}${chemin}`, {
                method: 'GET',
                headers: entetes,
            });

            if (!response.ok) {
                throw new Error(I18n.t('error.http_status', { status: response.status }));
            }

            // Le nom du fichier est celui que le serveur annonce : lui seul
            // connaît le nom du produit et l'horodatage retenus.
            await Utils.enregistrerReponse(
                response, `kovex_data_quality_${Date.now()}.${extension}`
            );

            Toast.success(I18n.t('quality.export.done'), I18n.t(messageFin));
        } catch (error) {
            Toast.error(I18n.t('common.error'), I18n.t('quality.export.failed'));
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = contenuInitial;
            }
        }
    },

    /**
     * Langue et contexte du workspace, communs aux deux exports.
     *
     * Le classeur ne les transmettait pas : il sortait en français quelle que
     * soit la langue choisie, et sans dire de quel workspace il provenait.
     *
     * `X-Generated-By` a été retiré. Le serveur ne le lit pas — il prend
     * l'auteur dans le jeton, et c'est la seule façon correcte de signer un
     * rapport d'audit : un en-tête que l'appelant compose se choisit. L'envoyer
     * quand même laissait croire le contraire.
     */
    /** Recharge le rapport : ses libellés viennent de clés traduites ici. */
    rafraichirLangue() {
        this.load();
    },

    contexteDExport() {
        let workspaceInfo = {};
        if (typeof WorkspaceManager !== 'undefined' && WorkspaceManager.currentWorkspace) {
            workspaceInfo = {
                name: WorkspaceManager.currentWorkspace.name || '',
                client: WorkspaceManager.currentWorkspace.client || '',
                environment: WorkspaceManager.currentWorkspace.environment || '',
            };
        }
        return {
            langue: encodeURIComponent(
                (typeof I18n !== 'undefined' && I18n.currentLocale) || 'fr'),
            entetes: {
                Authorization: `Bearer ${Auth.getToken()}`,
                'X-Workspace-Info': JSON.stringify(workspaceInfo),
            },
        };
    },

    async exportExcel() {
        const { langue, entetes } = this.contexteDExport();
        await this.telechargerExport(
            'export-excel-btn',
            `/data-quality/export/excel?langue=${langue}`,
            'xlsx',
            entetes,
            'quality.export.excel_started',
            'quality.export.excel_done'
        );
    },

    async exportPDF() {
        const { langue, entetes } = this.contexteDExport();
        await this.telechargerExport(
            'export-pdf-btn',
            `/data-quality/export/pdf?langue=${langue}`,
            'pdf',
            entetes,
            'quality.export.pdf_started',
            'quality.export.pdf_done'
        );
    },
};

window.QualityPage = QualityPage;
