/**
 * Kovex - Page « Piste d'audit ».
 *
 * L'écran est en lecture seule par construction : l'API n'expose aucune route
 * d'écriture ni de suppression sur la piste. Une interface qui permettrait de
 * retirer une entrée retirerait toute valeur probante à l'ensemble.
 *
 * Le constat d'intégrité est affiché en permanence plutôt que caché derrière
 * une action : une piste rompue doit se voir sans qu'on ait pensé à vérifier.
 */

const AuditPage = {
    TAILLE_PAGE: 50,

    etat: {
        page: 1,
        total: 0,
        filtres: { acteur: '', action: '', recherche: '', depuis: '', jusqu_a: '' },
    },

    init() {
        this.bindEvents();
    },

    bindEvents() {
        const champs = {
            'audit-filter-actor': 'acteur',
            'audit-filter-action': 'action',
            'audit-filter-from': 'depuis',
            'audit-filter-to': 'jusqu_a',
        };
        Object.entries(champs).forEach(([identifiant, filtre]) => {
            const element = document.getElementById(identifiant);
            if (element) {
                element.addEventListener('change', () => {
                    this.etat.filtres[filtre] = element.value;
                    this.etat.page = 1;
                    this.charger();
                });
            }
        });

        const recherche = document.getElementById('audit-filter-search');
        if (recherche) {
            recherche.addEventListener('input', Utils.debounce(() => {
                this.etat.filtres.recherche = recherche.value.trim();
                this.etat.page = 1;
                this.charger();
            }, 300));
        }

        const reinitialiser = document.getElementById('audit-filter-reset');
        if (reinitialiser) {
            reinitialiser.addEventListener('click', () => this.reinitialiser());
        }

        const precedent = document.getElementById('audit-prev');
        if (precedent) precedent.addEventListener('click', () => this.changerPage(-1));
        const suivant = document.getElementById('audit-next');
        if (suivant) suivant.addEventListener('click', () => this.changerPage(1));

        const verifier = document.getElementById('audit-verify');
        if (verifier) verifier.addEventListener('click', () => this.verifier());

        const exporter = document.getElementById('audit-export');
        if (exporter) exporter.addEventListener('click', () => this.exporter());
    },

    async load() {
        await Promise.all([this.chargerFiltres(), this.charger(), this.verifier()]);
    },

    async chargerFiltres() {
        try {
            const [acteurs, actions] = await Promise.all([
                API.get('/audit/acteurs'),
                API.get('/audit/actions'),
            ]);
            this.remplirSelecteur('audit-filter-actor', acteurs.acteurs || [],
                                  'audit.filter.actor', (v) => v);
            this.remplirSelecteur('audit-filter-action', actions.actions || [],
                                  'audit.filter.action',
                                  (v) => I18n.t(`audit.action.${v}`));
        } catch (error) {
            // Les filtres sont un confort : leur absence ne doit pas empêcher
            // de lire la piste, qui est l'essentiel de l'écran.
        }
    },

    remplirSelecteur(identifiant, valeurs, cleVide, libelle) {
        const selecteur = document.getElementById(identifiant);
        if (!selecteur) return;
        const courant = selecteur.value;
        selecteur.innerHTML = `<option value="">${Utils.escapeHtml(I18n.t(cleVide))}</option>`
            + valeurs.map((v) =>
                `<option value="${Utils.escapeHtml(v)}">${Utils.escapeHtml(libelle(v))}</option>`
            ).join('');
        selecteur.value = courant;
    },

    parametres() {
        const parametres = new URLSearchParams();
        Object.entries(this.etat.filtres).forEach(([cle, valeur]) => {
            if (valeur) parametres.set(cle, valeur);
        });
        parametres.set('page', this.etat.page);
        parametres.set('taille', this.TAILLE_PAGE);
        return parametres;
    },

    async charger() {
        const corps = document.getElementById('audit-tbody');
        if (!corps) return;

        try {
            const reponse = await API.get(`/audit?${this.parametres().toString()}`);
            this.etat.total = reponse.total || 0;
            this.rendre(reponse.entrees || []);
        } catch (error) {
            corps.innerHTML = `<tr><td colspan="6" class="audit-empty">${
                Utils.escapeHtml(I18n.t('error.load_data_failed'))}</td></tr>`;
        }
    },

    rendre(entrees) {
        const corps = document.getElementById('audit-tbody');
        if (!corps) return;

        corps.innerHTML = entrees.length === 0
            ? `<tr><td colspan="6" class="audit-empty">${
                Utils.escapeHtml(I18n.t('audit.empty'))}</td></tr>`
            : entrees.map((entree) => `
                <tr>
                    <td class="audit-timestamp">${Utils.escapeHtml(this.formaterDate(entree.horodatage))}</td>
                    <td>${Utils.escapeHtml(entree.acteur)}</td>
                    <td><span class="audit-action">${
                        Utils.escapeHtml(I18n.t(`audit.action.${entree.action}`))}</span></td>
                    <td class="audit-objet">${Utils.escapeHtml(entree.objet_id || '—')}</td>
                    <td>${Utils.escapeHtml(entree.workspace || '—')}</td>
                    <td class="audit-details">${Utils.escapeHtml(this.formaterDetails(entree.details))}</td>
                </tr>
            `).join('');

        const compteur = document.getElementById('audit-count');
        if (compteur) {
            compteur.textContent = I18n.t('audit.count', { total: this.etat.total });
        }

        const pages = Math.max(1, Math.ceil(this.etat.total / this.TAILLE_PAGE));
        const pagination = document.getElementById('audit-page');
        if (pagination) {
            pagination.textContent = I18n.t('audit.page', { page: this.etat.page, pages });
        }
        const precedent = document.getElementById('audit-prev');
        if (precedent) precedent.disabled = this.etat.page <= 1;
        const suivant = document.getElementById('audit-next');
        if (suivant) suivant.disabled = this.etat.page >= pages;
    },

    /**
     * L'horodatage est stocké en UTC ; il est affiché dans le fuseau du poste
     * qui consulte, faute de quoi une décision prise à 9 h apparaîtrait à 7 h.
     */
    formaterDate(horodatage) {
        const date = new Date(horodatage);
        return Number.isNaN(date.getTime())
            ? horodatage
            : date.toLocaleString(I18n.currentLocale || undefined);
    },

    formaterDetails(details) {
        if (!details || Object.keys(details).length === 0) return '—';
        return Object.entries(details)
            .map(([cle, valeur]) => `${cle} : ${Array.isArray(valeur) ? valeur.join(', ') : valeur}`)
            .join(' · ');
    },

    changerPage(pas) {
        const pages = Math.max(1, Math.ceil(this.etat.total / this.TAILLE_PAGE));
        const cible = this.etat.page + pas;
        if (cible < 1 || cible > pages) return;
        this.etat.page = cible;
        this.charger();
    },

    reinitialiser() {
        this.etat.filtres = { acteur: '', action: '', recherche: '', depuis: '', jusqu_a: '' };
        this.etat.page = 1;
        ['audit-filter-actor', 'audit-filter-action', 'audit-filter-search',
         'audit-filter-from', 'audit-filter-to'].forEach((identifiant) => {
            const element = document.getElementById(identifiant);
            if (element) element.value = '';
        });
        this.charger();
    },

    async verifier() {
        const banniere = document.getElementById('audit-integrity');
        if (!banniere) return;

        try {
            const constat = await API.get('/audit/verification');
            // Le serveur rend une clé et ses paramètres ; le nombre d'entrées
            // vérifiées est ajouté ici parce qu'il vaut pour tous les constats.
            const message = I18n.t(constat.constat_key, {
                ...(constat.constat_params || {}),
                entrees: constat.entrees,
            });
            banniere.className = `audit-integrity ${constat.intacte ? 'intacte' : 'rompue'}`;
            banniere.innerHTML = `
                <i class="fas ${constat.intacte ? 'fa-shield-alt' : 'fa-exclamation-triangle'}" aria-hidden="true"></i>
                <span>${Utils.escapeHtml(message)}</span>`;
        } catch (error) {
            banniere.className = 'audit-integrity';
            banniere.textContent = I18n.t('error.load_failed');
        }
    },

    /**
     * L'export passe par fetch et non par un lien : la route exige l'en-tête
     * d'authentification, qu'un `<a href>` ne porterait pas.
     */
    async exporter() {
        try {
            const reponse = await fetch(
                `${Config.API_URL}/audit/export?${this.parametres().toString()}`,
                { headers: { Authorization: `Bearer ${Auth.getToken()}` } }
            );
            if (!reponse.ok) {
                throw new Error(I18n.t('error.http_status', { status: reponse.status }));
            }
            await Utils.enregistrerReponse(reponse, `kovex_audit_${Date.now()}.csv`);
            Toast.success(I18n.t('quality.export.done'), '');
            // L'export est lui-même une action consignée : la piste change.
            this.charger();
        } catch (error) {
            Toast.error(I18n.t('common.error'), I18n.t('quality.export.failed'));
        }
    },
};

window.AuditPage = AuditPage;
