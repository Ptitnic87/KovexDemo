/**
 * Ce que le workspace apprend de ses décisions, et comment le désapprendre.
 *
 * L'écran montre trois choses, dans cet ordre : où en est l'apprentissage
 * (combien de décisions sur combien il en faut), ce que vaut le score mesuré à
 * rebours contre la simple majorité, et l'historique qui le nourrit, décision
 * par décision, chacune retirable. Rien n'est appris qui ne se lise ici.
 */
const ApprentissagePage = {
    etat: null,
    branche: false,

    init() {
        if (!this.branche) {
            this.branche = true;
            document.getElementById('apprentissage-oublier')
                ?.addEventListener('click', () => this.oublier());
            document.getElementById('apprentissage-historique')
                ?.addEventListener('change', (evenement) => {
                    const coche = evenement.target.closest('[data-apprentissage-role]');
                    if (coche) this.exclure(coche.dataset.apprentissageRole, !coche.checked);
                });
        }
        return this.charger();
    },

    rafraichirLangue() {
        this.render();
    },

    async charger() {
        try {
            this.etat = await API.get('/apprentissage');
        } catch (erreur) {
            this.etat = null;
            Toast.error(I18n.t('common.error'), erreur.message);
        }
        this.render();
    },

    async exclure(role, exclue) {
        try {
            await API.put(`/apprentissage/decisions/${encodeURIComponent(role)}`, {exclue});
        } catch (erreur) {
            Toast.error(I18n.t('common.error'), erreur.message);
        }
        await this.charger();
    },

    async oublier() {
        try {
            const rendu = await API.post('/apprentissage/oublier', {});
            Toast.success(I18n.t('common.success'),
                          I18n.t('apprentissage.oubliees', {nombre: rendu.oubliees}));
        } catch (erreur) {
            Toast.error(I18n.t('common.error'), erreur.message);
        }
        await this.charger();
    },

    render() {
        const zone = document.getElementById('apprentissage-etat');
        const corps = document.getElementById('apprentissage-historique');
        if (!zone || !corps) return;
        const etat = this.etat;
        if (!etat) {
            zone.innerHTML = '';
            corps.innerHTML = '';
            return;
        }
        zone.innerHTML = `${ApprentissagePage.phraseDEtat(etat)}${
            etat.toile_des_validees ? `<figure class="apprentissage-toile">${Toile.svg(
                etat.axes_de_la_toile, etat.toile_des_validees, null)}${Toile.legende(
                etat.axes_de_la_toile, etat.toile_des_validees, null)}
                <figcaption class="form-hint">${Utils.escapeHtml(
                    I18n.t('apprentissage.toile.reference'))}</figcaption></figure>` : ''}${
            etat.exclues || etat.incompletes ? `<p class="form-hint">${Utils.escapeHtml(
                I18n.t('apprentissage.ecartees', {exclues: etat.exclues,
                                                  incompletes: etat.incompletes}))}</p>` : ''}`;
        corps.innerHTML = (etat.historique || []).map((decision) => `
            <tr>
                <td>${Utils.escapeHtml(decision.role_id || '')}</td>
                <td>${Utils.escapeHtml(I18n.t(`apprentissage.verdict.${decision.verdict}`))}</td>
                <td>${Utils.escapeHtml(Utils.formatDate((decision.decided_at || '').slice(0, 10)))}</td>
                <td>${decision.manquantes.length
                    ? Utils.escapeHtml(I18n.t('apprentissage.incomplete'))
                    : `<label class="chart-option">
                        <input type="checkbox" data-apprentissage-role="${
                            Utils.escapeHtml(decision.role_id || '')}"${decision.exclue ? '' : ' checked'}>
                        <span>${Utils.escapeHtml(I18n.t('apprentissage.apprend'))}</span></label>`}</td>
            </tr>`).join('');
    },

    /**
     * La phrase qui dit où en est l'apprentissage. Partagée avec l'écran des
     * résultats du mining : le démarrage à froid s'y écrit dans les mêmes mots.
     */
    phraseDEtat(etat) {
        if (!etat.pret) {
            return `<p>${Utils.escapeHtml(I18n.t('apprentissage.froid', {
                decisions: etat.decisions, minimum: etat.decisions_min,
                par_verdict: etat.par_verdict_min, validees: etat.validees,
                rejetees: etat.rejetees}))}</p>`;
        }
        const mesure = etat.mesure;
        return `<p>${Utils.escapeHtml(I18n.t('apprentissage.pret', {decisions: etat.decisions}))}</p>
            ${mesure ? `<p class="${mesure.meilleur_que_la_majorite ? 'form-hint' : 'alert alert-warning'}">${
                Utils.escapeHtml(I18n.t(mesure.meilleur_que_la_majorite
                    ? 'apprentissage.mesure' : 'apprentissage.mesure_insuffisante', {
                        justes: mesure.justes, decisions: mesure.decisions,
                        majorite: mesure.majorite}))}</p>` : ''}`;
    },
};

window.ApprentissagePage = ApprentissagePage;
