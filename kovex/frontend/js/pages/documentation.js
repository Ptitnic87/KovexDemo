/**
 * Kovex - Page « Documentation ».
 *
 * L'écran s'ouvre sur un sommaire de parcours plutôt que sur un mur de texte :
 * un administrateur qui cherche comment sauvegarder et un analyste qui cherche
 * comment lire un rôle n'ont pas la même question, et une documentation unique
 * les sert mal tous les deux.
 */

const DocumentationPage = {
    sections: [],
    sectionCourante: null,

    init() {
        const retour = document.getElementById('doc-back');
        if (retour) retour.addEventListener('click', () => this.afficherSommaire());

        // Délégation : les cartes du sommaire sont reconstruites à chaque
        // chargement, et un écouteur par carte serait perdu.
        const sommaire = document.getElementById('doc-sections');
        if (sommaire) {
            sommaire.addEventListener('click', (evenement) => {
                const carte = evenement.target.closest('[data-doc-section]');
                if (carte) this.ouvrir(carte.dataset.docSection);
            });
        }
    },

    async load() {
        const sommaire = document.getElementById('doc-sections');
        if (!sommaire) return;
        try {
            const reponse = await API.get(
                `/documentation/sections?langue=${encodeURIComponent(I18n.currentLocale || 'fr')}`
            );
            this.sections = reponse.sections || [];
            this.rendreSommaire();
        } catch (error) {
            sommaire.innerHTML = `<p class="doc-error">${
                Utils.escapeHtml(I18n.t('error.load_data_failed'))}</p>`;
        }
        this.afficherSommaire();
    },

    rendreSommaire() {
        const sommaire = document.getElementById('doc-sections');
        if (!sommaire) return;
        sommaire.innerHTML = this.sections.map((section) => `
            <button type="button" class="doc-card surface-actionnable" data-doc-section="${Utils.escapeHtml(section.id)}">
                <span class="doc-card-icon"><i class="fas ${Utils.escapeHtml(section.icone)}" aria-hidden="true"></i></span>
                <span class="doc-card-title">${Utils.escapeHtml(I18n.t(section.titre_key))}</span>
                <span class="doc-card-summary">${Utils.escapeHtml(I18n.t(section.resume_key))}</span>
            </button>
        `).join('');
    },

    afficherSommaire() {
        this.sectionCourante = null;
        this.basculer(false);
    },

    basculer(surContenu) {
        const sommaire = document.getElementById('doc-summary-view');
        const contenu = document.getElementById('doc-content-view');
        if (sommaire) sommaire.hidden = surContenu;
        if (contenu) contenu.hidden = !surContenu;
    },

    async ouvrir(identifiant) {
        const corps = document.getElementById('doc-content');
        if (!corps) return;

        this.sectionCourante = identifiant;
        this.basculer(true);
        corps.innerHTML = `<p class="doc-loading">${
            Utils.escapeHtml(I18n.t('common.loading'))}</p>`;

        const section = this.sections.find((s) => s.id === identifiant);
        const titre = document.getElementById('doc-content-title');
        if (titre && section) titre.textContent = I18n.t(section.titre_key);

        try {
            const reponse = await API.get(
                `/documentation/${encodeURIComponent(identifiant)}`
                + `?langue=${encodeURIComponent(I18n.currentLocale || 'fr')}`
            );

            const avertissement = document.getElementById('doc-untranslated');
            if (avertissement) {
                // Dire que la section n'est pas traduite vaut mieux que servir
                // du français en laissant croire que c'est la langue choisie.
                avertissement.hidden = reponse.traduite !== false;
                if (!avertissement.hidden) {
                    avertissement.textContent = I18n.t('doc.not_translated', {
                        langue: reponse.langue_servie,
                    });
                }
            }
            corps.innerHTML = Markdown.rendre(reponse.contenu);
        } catch (error) {
            corps.innerHTML = `<p class="doc-error">${
                Utils.escapeHtml(I18n.t('error.load_failed'))}</p>`;
        }
    },
};

window.DocumentationPage = DocumentationPage;
