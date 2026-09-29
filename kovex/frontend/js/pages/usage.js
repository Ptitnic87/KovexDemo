/**
 * Le signal d'usage : ce qui est détenu et ne sert plus.
 *
 * L'écran ne calcule rien tant que l'utilisateur n'a pas déclaré trois choses :
 * la colonne qui porte la date (sur les habilitations, sur les identités, ou
 * les deux), le format de ces dates, et le seuil d'inactivité. Le produit ne
 * connaît aucune colonne des fichiers du client ; il n'en devine pas une, et
 * il ne choisit pas le seuil à sa place.
 *
 * Ce que l'écran dit toujours à côté du résultat : combien de lignes n'avaient
 * pas de date, combien de dates ne se lisaient pas au format déclaré, et à
 * quelle date l'inactivité a été mesurée. Sans ces trois chiffres, « 40
 * droits dormants » ne se vérifie pas.
 */
const UsagePage = {
    colonnes: {habilitations: [], identites: []},
    resultat: null,
    //: La déclaration du dernier calcul : les listes nominatives la reprennent,
    //  pour dire les mêmes personnes que le compte qu'elles déplient.
    declaration: null,
    //: Ce que le tableau nominatif montre : les dormants d'un droit, ou les
    //  comptes inactifs.
    liste: null,
    tableau: null,
    branche: false,

    init() {
        if (!this.branche) {
            this.branche = true;
            const bouton = document.getElementById('usage-calculer');
            if (bouton) bouton.addEventListener('click', () => this.calculer());
            const zone = document.getElementById('usage-resultat');
            if (zone) {
                zone.addEventListener('click', (evenement) => {
                    const bouton = evenement.target.closest('button');
                    if (!bouton) return;
                    if (bouton.dataset.usageDroit) this.montrer({droit: bouton.dataset.usageDroit});
                    if (bouton.dataset.usageInactives) this.montrer({inactives: true});
                });
            }
        }
        this.chargerLesColonnes();
    },

    rafraichirLangue() {
        this.renderLesColonnes();
        this.render();
    },

    async chargerLesColonnes() {
        try {
            this.colonnes = await API.get('/usage/colonnes');
        } catch (erreur) {
            this.colonnes = {habilitations: [], identites: []};
            Toast.error(I18n.t('common.error'), erreur.message);
        }
        this.renderLesColonnes();
    },

    /**
     * Une option vide en tête de chaque liste : tant que personne n'a choisi,
     * rien n'est lu. Une colonne sélectionnée d'office ferait croire que la
     * déclaration a été faite.
     */
    renderLesColonnes() {
        [['usage-colonne-habilitation', this.colonnes.habilitations || []],
         ['usage-colonne-identite', this.colonnes.identites || []]].forEach(([id, liste]) => {
            const choix = document.getElementById(id);
            if (!choix) return;
            const retenu = choix.value;
            choix.innerHTML = `<option value="">${Utils.escapeHtml(I18n.t('usage.colonne.none'))}</option>`
                + liste.map((colonne) => `<option value="${Utils.escapeHtml(colonne)}">${
                    Utils.escapeHtml(colonne)}</option>`).join('');
            choix.value = liste.includes(retenu) ? retenu : '';
        });
    },

    lireLaDeclaration() {
        const valeur = (id) => (document.getElementById(id)?.value || '').trim();
        return {
            colonne_habilitation: valeur('usage-colonne-habilitation'),
            colonne_identite: valeur('usage-colonne-identite'),
            format_date: valeur('usage-format'),
            inactivite_jours: parseInt(valeur('usage-seuil'), 10),
            limite: parseInt(valeur('usage-limite'), 10),
            date_reference: valeur('usage-date-reference'),
        };
    },

    async calculer() {
        const declaration = this.lireLaDeclaration();
        if ((!declaration.colonne_habilitation && !declaration.colonne_identite)
            || !declaration.format_date
            || !Number.isFinite(declaration.inactivite_jours) || declaration.inactivite_jours < 1
            || !Number.isFinite(declaration.limite) || declaration.limite < 1) {
            Toast.error(I18n.t('common.error'), I18n.t('usage.declaration_requise'));
            return;
        }
        try {
            this.resultat = await API.get('/usage', declaration);
        } catch (erreur) {
            Toast.error(I18n.t('common.error'), erreur.message);
            return;
        }
        this.declaration = declaration;
        this.liste = null;
        this.render();
    },

    /** Ce que la lecture d'une colonne a donné : de quoi vérifier le résultat. */
    renderLeBilan(bilan) {
        const exemples = bilan.exemples_illisibles || [];
        return `<p class="form-hint">${Utils.escapeHtml(I18n.t('usage.bilan', {
                lignes: Utils.formatNumber(bilan.lignes),
                datees: Utils.formatNumber(bilan.datees),
                sans_date: Utils.formatNumber(bilan.sans_date),
                illisibles: Utils.formatNumber(bilan.illisibles)}))}</p>
            ${exemples.length ? `<p class="form-hint form-hint-error">${Utils.escapeHtml(
                I18n.t('usage.illisibles', {exemples: exemples.join(', ')}))}</p>` : ''}`;
    },

    render() {
        const zone = document.getElementById('usage-resultat');
        if (!zone) return;
        const rendu = this.resultat;
        if (!rendu) {
            zone.innerHTML = '';
            return;
        }
        const reference = rendu.date_reference
            ? I18n.t(rendu.date_reference_deduite ? 'usage.reference.deduite' : 'usage.reference.declaree',
                     {date: Utils.formatDate(rendu.date_reference),
                      jours: Utils.formatNumber(rendu.inactivite_jours)})
            : I18n.t('usage.reference.aucune');
        const habs = rendu.habilitations;
        const identites = rendu.identites;
        zone.innerHTML = `
            <p class="usage-reference">${Utils.escapeHtml(reference)}</p>
            ${habs ? `
                <h3>${Utils.escapeHtml(I18n.t('usage.habilitations.title'))}</h3>
                ${this.renderLeBilan(habs)}
                <p>${Utils.escapeHtml(I18n.t('usage.habilitations.resume', {
                    dormantes: Utils.formatNumber(habs.inactives),
                    droits: Utils.formatNumber(habs.droits_concernes)}))}</p>
                ${habs.droits.length ? this.renderLesDroits(habs) : ''}
            ` : ''}
            ${identites ? `
                <h3>${Utils.escapeHtml(I18n.t('usage.identites.title'))}</h3>
                ${this.renderLeBilan(identites)}
                <p>${Utils.escapeHtml(I18n.t('usage.identites.resume', {
                    inactives: Utils.formatNumber(identites.inactives)}))}
                    ${identites.inactives ? `<button type="button" class="btn btn-secondary btn-sm"
                        data-usage-inactives="1">${Utils.escapeHtml(I18n.t('usage.voir'))}</button>` : ''}</p>
            ` : ''}`;
    },

    renderLesDroits(habs) {
        return `
            <table class="role-detail-table">
                <thead><tr>
                    <th scope="col">${Utils.escapeHtml(I18n.t('common.rights'))}</th>
                    <th scope="col">${Utils.escapeHtml(I18n.t('usage.colonne.detenteurs'))}</th>
                    <th scope="col">${Utils.escapeHtml(I18n.t('usage.colonne.dormants'))}</th>
                    <th scope="col">${Utils.escapeHtml(I18n.t('usage.colonne.derniere'))}</th>
                </tr></thead>
                <tbody>${habs.droits.map((ligne) => `
                    <tr>
                        <td>${Utils.escapeHtml(ligne.droit)}</td>
                        <td>${Utils.escapeHtml(Utils.formatNumber(ligne.detenteurs))}</td>
                        <td><button type="button" class="btn btn-sm btn-link"
                                data-usage-droit="${Utils.escapeHtml(ligne.droit)}">${
                            Utils.escapeHtml(I18n.t('usage.part', {
                                dormants: Utils.formatNumber(ligne.dormants),
                                part: Utils.formatNumber(ligne.part_pct)}))}</button></td>
                        <td>${Utils.escapeHtml(Utils.formatDate(ligne.derniere_utilisation) || '—')}</td>
                    </tr>`).join('')}
                </tbody>
            </table>
            ${habs.au_dela_de_la_limite ? `<p class="form-hint">${Utils.escapeHtml(
                I18n.t('usage.au_dela', {nombre: Utils.formatNumber(habs.au_dela_de_la_limite)}))}</p>` : ''}`;
    },

    /** Les noms derrière un compte : les dormants d'un droit, ou les inactifs. */
    montrer(liste) {
        this.liste = liste;
        const zone = document.getElementById('usage-liste');
        if (zone) zone.hidden = false;
        const titre = document.getElementById('usage-liste-titre');
        if (titre) {
            titre.textContent = liste.inactives
                ? I18n.t('usage.liste.inactives')
                : I18n.t('usage.liste.dormants', {droit: liste.droit});
        }
        if (!this.tableau) {
            this.tableau = new DataTable({
                type: 'validation-identities',
                endpoint: '',
                theadId: 'usage-liste-thead',
                tbodyId: 'usage-liste-corps',
                searchId: 'usage-liste-recherche',
                countId: 'usage-liste-compte',
                paginationPrefix: 'usage-liste',
                detail: false,
                parametres: () => {
                    const {limite, ...declaration} = this.declaration;
                    return this.liste.inactives ? declaration
                        : {...declaration, droit: this.liste.droit};
                },
            });
        }
        this.tableau.endpoint = liste.inactives ? '/usage/inactives' : '/usage/dormants';
        this.tableau.state.page = 1;
        this.tableau.state.search = '';
        return this.tableau.load();
    },
};

window.UsagePage = UsagePage;
