/**
 * Les contrôles compensatoires : ce qui rend une exception défendable.
 *
 * Une dérogation dit « ce conflit est accepté, pour cette raison, jusqu'à
 * cette date ». Un auditeur demande aussitôt ce qui compense. Le contrôle est
 * donc un objet — un exécutant, un relecteur qui n'est pas lui, un âge
 * maximal — et chacune de ses exécutions est consignée avec sa preuve.
 *
 * L'écran montre, pour chaque contrôle, les raisons pour lesquelles il ne
 * compense plus : ce sont celles qu'hériteraient les dérogations qui le
 * citent, et il vaut mieux les corriger ici qu'apprendre, conflit par
 * conflit, qu'elles ne couvrent plus rien.
 */
const ControlesPage = {
    catalogue: [],
    resultats: [],
    aujourdhui: '',
    //: Le contrôle dont le formulaire d'exécution est ouvert. Un seul à la fois.
    enExecution: '',
    //: Les identifiants que le serveur connaît. Un contrôle ajouté à l'écran
    //: n'existe pour lui qu'une fois enregistré : consigner une exécution
    //: avant cela échouait sur « le contrôle … n'existe pas ».
    enregistres: new Set(),
    branche: false,

    async init() {
        this.brancher();
        await this.charger();
    },

    /** Réaffiche le catalogue dans la langue courante. */
    rafraichirLangue() {
        this.render();
    },

    brancher() {
        if (this.branche) return;
        this.branche = true;
        const zone = document.getElementById('controles-compensatoires');
        if (!zone) return;
        zone.addEventListener('input', (evenement) => {
            const champ = evenement.target.closest('[data-controle-champ]');
            if (champ) this.modifier(champ.dataset.controle, champ.dataset.controleChamp, champ);
        });
        zone.addEventListener('change', (evenement) => {
            const champ = evenement.target.closest('[data-controle-champ]');
            if (champ) this.modifier(champ.dataset.controle, champ.dataset.controleChamp, champ);
        });
        zone.addEventListener('click', (evenement) => {
            const bouton = evenement.target.closest('button');
            if (!bouton) return;
            if (bouton.id === 'controles-ajouter') this.ajouter();
            if (bouton.id === 'controles-enregistrer') this.enregistrer();
            if (bouton.dataset.controleRetirer) this.retirer(bouton.dataset.controleRetirer);
            if (bouton.dataset.controleExecuter) this.ouvrirLExecution(bouton.dataset.controleExecuter);
            if (bouton.dataset.controleConsigner) this.consigner(bouton.dataset.controleConsigner);
            if (bouton.dataset.controleAnnuler) this.fermerLExecution();
        });
    },

    async charger() {
        try {
            const rendu = await API.get('/controles');
            this.catalogue = (rendu.controles || []).map((controle) => ({...controle}));
            this.retenirLesEnregistres();
            this.resultats = rendu.resultats || [];
            this.aujourdhui = rendu.aujourdhui || '';
        } catch (erreur) {
            Toast.error(I18n.t('common.error'), erreur.message);
            return;
        }
        this.render();
    },

    retenirLesEnregistres() {
        this.enregistres = new Set(this.catalogue.map((controle) => controle.id));
    },

    /** Un identifiant qui ne ressemble à rien de métier, comme les règles. */
    nouvelIdentifiant() {
        const pris = new Set(this.catalogue.map((controle) => controle.id));
        let rang = this.catalogue.length + 1;
        while (pris.has(`CTRL${rang}`)) rang += 1;
        return `CTRL${rang}`;
    },

    ajouter() {
        this.catalogue.push({id: this.nouvelIdentifiant(), libelle: '', executant: '',
                             relecteur: '', age_max_jours: '', actif: true,
                             derniere_execution: null, raisons: []});
        this.render();
    },

    retirer(identifiant) {
        this.catalogue = this.catalogue.filter((controle) => controle.id !== identifiant);
        this.render();
    },

    /**
     * Reporte une saisie dans l'état, sans redessiner : réécrire le bloc à
     * chaque frappe ferait perdre le curseur.
     */
    modifier(identifiant, champ, element) {
        const controle = this.catalogue.find((candidat) => candidat.id === identifiant);
        if (!controle) return;
        controle[champ] = champ === 'actif' ? element.checked : element.value;
    },

    async enregistrer() {
        const envoi = this.catalogue.map((controle) => ({
            id: controle.id,
            libelle: controle.libelle,
            executant: controle.executant,
            relecteur: controle.relecteur,
            age_max_jours: parseInt(controle.age_max_jours, 10),
            actif: controle.actif !== false,
        }));
        try {
            const rendu = await API.put('/controles', {controles: envoi});
            this.catalogue = rendu.controles || [];
            this.retenirLesEnregistres();
        } catch (erreur) {
            Toast.error(I18n.t('common.error'), erreur.message);
            return;
        }
        Toast.success(I18n.t('common.success'), I18n.t('controle.saved'));
        this.render();
        this.signalerLeChangement();
    },

    ouvrirLExecution(identifiant) {
        if (!this.enregistres.has(identifiant)) return;
        this.enExecution = identifiant;
        this.render();
        const date = document.getElementById('controle-execute-le');
        if (date) date.focus();
    },

    fermerLExecution() {
        this.enExecution = '';
        this.render();
    },

    async consigner(identifiant) {
        const lire = (id) => document.getElementById(id)?.value || '';
        try {
            await API.post(`/controles/${encodeURIComponent(identifiant)}/executions`, {
                execute_le: lire('controle-execute-le'),
                executant: lire('controle-executant'),
                relecteur: lire('controle-relecteur'),
                resultat: lire('controle-resultat'),
                preuve: lire('controle-preuve'),
            });
        } catch (erreur) {
            Toast.error(I18n.t('common.error'), erreur.message);
            return;
        }
        Toast.success(I18n.t('common.success'), I18n.t('controle.executed'));
        this.enExecution = '';
        await this.charger();
        this.signalerLeChangement();
    },

    /**
     * Les conflits dépendent des contrôles : une exécution consignée peut
     * rendre sa couverture à une dérogation, un contrôle retiré la lui ôter.
     * L'écran des conflits l'écoute pour se relire.
     */
    signalerLeChangement() {
        document.dispatchEvent(new CustomEvent('kovex:controles-modifies'));
    },

    /** Une raison de ne plus compenser, dans la langue de l'utilisateur. */
    raison(raison) {
        return I18n.t(`derogation.raison.${raison.code}`, Utils.parametresDansLaLangue(raison.params));
    },

    render() {
        const liste = document.getElementById('controles-liste');
        if (!liste) return;
        if (!this.catalogue.length) {
            liste.innerHTML = `<p class="form-hint">${Utils.escapeHtml(I18n.t('controle.empty'))}</p>`;
            return;
        }
        liste.innerHTML = this.catalogue.map((controle) => this.renderLeControle(controle)).join('');
    },

    renderLeControle(controle) {
        const id = Utils.escapeHtml(controle.id);
        const champ = (nom, cle, type = 'text') => `
            <div class="form-group">
                <label class="form-label" for="controle-${nom}-${id}">${
                    Utils.escapeHtml(I18n.t(cle))}</label>
                <input type="${type}" class="form-input" id="controle-${nom}-${id}"
                       data-controle="${id}" data-controle-champ="${nom}"
                       ${type === 'number' ? 'min="1" step="1"' : 'maxlength="200"'}
                       value="${Utils.escapeHtml(String(controle[nom] ?? ''))}">
            </div>`;
        const derniere = controle.derniere_execution;
        const raisons = controle.raisons || [];
        const enregistre = this.enregistres.has(controle.id);
        return `
            <div class="controle" data-controle-bloc="${id}">
                ${champ('libelle', 'controle.label')}
                <div class="form-row">
                    ${champ('executant', 'controle.performer')}
                    ${champ('relecteur', 'controle.reviewer')}
                    ${champ('age_max_jours', 'controle.max_age', 'number')}
                </div>
                <p class="form-hint">${Utils.escapeHtml(derniere
                    ? I18n.t('controle.last_execution', {
                        date: Utils.formatDate(derniere.execute_le),
                        resultat: I18n.t(`controle.resultat.${derniere.resultat}`),
                        preuve: derniere.preuve})
                    : I18n.t('controle.never_executed'))}</p>
                ${raisons.length ? `
                    <ul class="controle__raisons">${raisons.map((raison) => `
                        <li>${Utils.escapeHtml(this.raison(raison))}</li>`).join('')}</ul>
                ` : `<p class="form-hint">${Utils.escapeHtml(I18n.t('controle.compensates'))}</p>`}
                <div class="form-actions">
                    <label class="chart-option" for="controle-actif-${id}">
                        <input type="checkbox" id="controle-actif-${id}" data-controle="${id}"
                               data-controle-champ="actif" ${controle.actif !== false ? 'checked' : ''}>
                        <span>${Utils.escapeHtml(I18n.t('controle.active'))}</span>
                    </label>
                    <button type="button" class="btn btn-secondary btn-sm"
                            data-controle-executer="${id}"${enregistre ? '' : `
                            disabled aria-describedby="controle-a-enregistrer-${id}"`}>${
                        Utils.escapeHtml(I18n.t('controle.record_execution'))}</button>
                    <button type="button" class="btn btn-secondary btn-sm"
                            data-controle-retirer="${id}">${
                        Utils.escapeHtml(I18n.t('controle.remove'))}</button>
                </div>
                ${enregistre ? '' : `<p class="form-hint" id="controle-a-enregistrer-${id}">${
                    Utils.escapeHtml(I18n.t('controle.save_first'))}</p>`}
                ${this.enExecution === controle.id ? this.renderLExecution(controle) : ''}
            </div>`;
    },

    /**
     * Le formulaire d'une exécution. Ni qui consigne ni quand : ils viennent du
     * serveur. L'exécutant et le relecteur sont proposés d'après le contrôle,
     * et restent modifiables — un remplaçant a pu l'exécuter.
     */
    renderLExecution(controle) {
        const id = Utils.escapeHtml(controle.id);
        return `
            <div class="controle__execution">
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label" for="controle-execute-le">${
                            Utils.escapeHtml(I18n.t('controle.executed_on'))}</label>
                        <input type="date" class="form-input" id="controle-execute-le"
                               max="${Utils.escapeHtml(this.aujourdhui)}"
                               value="${Utils.escapeHtml(this.aujourdhui)}">
                    </div>
                    <div class="form-group">
                        <label class="form-label" for="controle-executant">${
                            Utils.escapeHtml(I18n.t('controle.performer'))}</label>
                        <input type="text" class="form-input" id="controle-executant" maxlength="200"
                               value="${Utils.escapeHtml(controle.executant || '')}">
                    </div>
                    <div class="form-group">
                        <label class="form-label" for="controle-relecteur">${
                            Utils.escapeHtml(I18n.t('controle.reviewer'))}</label>
                        <input type="text" class="form-input" id="controle-relecteur" maxlength="200"
                               value="${Utils.escapeHtml(controle.relecteur || '')}">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label" for="controle-resultat">${
                            Utils.escapeHtml(I18n.t('controle.result'))}</label>
                        <select class="form-input" id="controle-resultat">${this.resultats.map((code) => `
                            <option value="${Utils.escapeHtml(code)}">${
                                Utils.escapeHtml(I18n.t(`controle.resultat.${code}`))}</option>`).join('')}
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label" for="controle-preuve">${
                            Utils.escapeHtml(I18n.t('controle.evidence'))}</label>
                        <input type="text" class="form-input" id="controle-preuve" maxlength="500"
                               placeholder="${Utils.escapeHtml(I18n.t('controle.evidence.placeholder'))}">
                    </div>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary btn-sm"
                            data-controle-annuler="${id}">${Utils.escapeHtml(I18n.t('action.cancel'))}</button>
                    <button type="button" class="btn btn-primary btn-sm"
                            data-controle-consigner="${id}">${
                        Utils.escapeHtml(I18n.t('controle.record'))}</button>
                </div>
            </div>`;
    },
};

window.ControlesPage = ControlesPage;
