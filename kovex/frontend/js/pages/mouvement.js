/**
 * Les droits conservés d'un poste précédent.
 *
 * L'écran pose une seule question et il faut y répondre avant tout calcul :
 * **qui sont ses pairs ?** Le produit ne connaît aucune colonne des fichiers du
 * client — ni `service`, ni `direction`, ni `jobtitle` — et en choisir une
 * d'office produirait des constats sur un regroupement que personne n'a voulu.
 *
 * Ce que l'écran dit, et ce qu'il ne dit pas : il montre que quelqu'un détient
 * des droits atypiques de son groupe et typiques d'un autre. Il ne dit pas que
 * la personne a changé de poste — la mobilité est l'explication la plus
 * fréquente de cette forme, pas la seule.
 */
const MouvementPage = {
    /** Le dernier résultat rendu, conservé pour le changement de langue. */
    resultat: null,
    /** Les colonnes proposées, telles que le serveur les a classées. */
    attributs: [],
    /** Ce qui a été demandé en dernier, pour ignorer les réponses dépassées. */
    jeton: 0,
    /** Vrai quand la lecture a échoué : le silence de l'écran s'explique. */
    illisible: false,

    init() {
        if (!this.branche) {
            const choix = document.getElementById('mouvement-attribut');
            if (choix) {
                choix.addEventListener('change', () => this.calculer());
            }
            this.branche = true;
        }
        this.chargerLesAttributs();
    },

    /** Réaffiche ce qui est déjà rendu, dans la langue courante. */
    rafraichirLangue() {
        this.renderLesAttributs();
        this.render();
    },

    /**
     * Les colonnes d'identités utilisables comme groupe de pairs.
     *
     * Ce sont celles du mining métier, par la même route : deux écrans qui
     * proposeraient deux listes de colonnes finiraient par ne pas parler du
     * même référentiel.
     */
    async chargerLesAttributs() {
        try {
            const rendu = await API.get(
                '/mining-metiers/attributes/identity/business');
            this.attributs = rendu.attributes || [];
        } catch (erreur) {
            this.attributs = [];
        }
        this.renderLesAttributs();
        this.calculer();
    },

    renderLesAttributs() {
        const choix = document.getElementById('mouvement-attribut');
        if (!choix) return;
        const retenu = choix.value;
        // Une option vide en tête : tant que personne n'a choisi, le produit
        // ne calcule rien. Un premier attribut sélectionné d'office ferait
        // croire que le regroupement a été décidé.
        choix.innerHTML = `<option value="">${Utils.escapeHtml(
            I18n.t('mouvement.attribut.none'))}</option>`
            + this.attributs.map((attribut) => `
                <option value="${Utils.escapeHtml(attribut.name)}">${
                    Utils.escapeHtml(attribut.name)} — ${Utils.escapeHtml(
                        I18n.t('mouvement.attribut.distinct',
                               {count: attribut.distinct_count}))}</option>`).join('');
        choix.value = retenu;
    },

    async calculer() {
        const choix = document.getElementById('mouvement-attribut');
        const attribut = choix ? choix.value : '';
        const jeton = (this.jeton += 1);
        this.illisible = false;
        if (!attribut) {
            this.resultat = null;
            this.render();
            return;
        }
        let rendu;
        try {
            rendu = await API.get('/mouvement', {attribut});
        } catch (erreur) {
            // Le silence s'explique : une liste vide se lirait « aucun droit
            // conservé », et rassurer sur un calcul qui n'a pas eu lieu est le
            // seul mensonge que cet écran puisse produire.
            if (jeton !== this.jeton) return;
            this.resultat = null;
            this.illisible = true;
            this.render();
            return;
        }
        // Le choix a pu changer pendant l'appel : afficher le résultat d'un
        // regroupement qu'on ne demande plus désignerait les mauvais pairs.
        if (jeton !== this.jeton) return;
        this.resultat = rendu;
        this.render();
    },

    render() {
        const zone = document.getElementById('mouvement-resultat');
        const total = document.getElementById('mouvement-total');
        if (!zone) return;
        if (total) total.textContent = this.texteDuTotal();
        if (this.illisible) {
            zone.innerHTML = `<div class="alert alert-warning">${
                Utils.escapeHtml(I18n.t('mouvement.illisible'))}</div>`;
            return;
        }
        if (!this.resultat) {
            zone.innerHTML = `<p class="form-hint">${Utils.escapeHtml(
                I18n.t('mouvement.attribut.prompt'))}</p>`;
            return;
        }
        zone.innerHTML = this.renderLaCouverture() + this.renderLesConstats();
    },

    texteDuTotal() {
        if (!this.resultat) return '';
        return I18n.t('mouvement.total', {
            identites: Utils.formatNumber(this.resultat.identites_concernees),
            constats: Utils.formatNumber(this.resultat.constats)});
    },

    /**
     * Sur quoi le constat porte, et sur quoi il ne porte pas.
     *
     * « Aucun constat » sur une population dont les trois quarts n'ont pas de
     * groupe exploitable n'est pas la même information que « aucun constat »
     * sur une population couverte — et les confondre ferait conclure à un
     * référentiel sain.
     */
    renderLaCouverture() {
        const resultat = this.resultat;
        return `
            <p class="form-hint">${Utils.escapeHtml(I18n.t('mouvement.couverture', {
                examinees: Utils.formatNumber(resultat.examinees),
                population: Utils.formatNumber(resultat.population),
                groupes: Utils.formatNumber(resultat.groupes_retenus),
                total: Utils.formatNumber(resultat.groupes)}))}</p>
            <p class="form-hint">${Utils.escapeHtml(I18n.t('mouvement.seuils', Utils.parametresDansLaLangue({
                groupe: resultat.reglages.groupe_min,
                rarete: resultat.reglages.rarete_max_pct,
                typique: resultat.reglages.typique_min_pct,
                droits: resultat.reglages.droits_min})))}</p>`;
    },

    renderLesConstats() {
        const lignes = this.resultat.lignes || [];
        if (!lignes.length) {
            return `<p class="empty-state-text">${Utils.escapeHtml(
                I18n.t('mouvement.aucun'))}</p>`;
        }
        return `
            <ul class="mouvement-constats">
                ${lignes.map((constat) => this.renderUnConstat(constat)).join('')}
            </ul>
            ${this.resultat.tronquee ? `<p class="form-hint">${
                Utils.escapeHtml(I18n.t('mouvement.tronquee',
                                        {max: lignes.length}))}</p>` : ''}`;
    },

    /**
     * Une personne, son groupe d'origine présumé, et les droits concordants.
     *
     * La phrase porte les deux faits et pas un score : « elle est la seule des
     * trente-trois autres » et « quatre-vingt-neuf pour cent de l'autre service
     * les ont » se vérifient l'un et l'autre, là où un score entre zéro et un
     * ne se vérifie pas.
     */
    renderUnConstat(constat) {
        return `
            <li class="mouvement-constat">
                <p class="mouvement-constat-titre">
                    <strong>${Utils.escapeHtml(constat.identite)}</strong>
                    — ${Utils.escapeHtml(I18n.t('mouvement.constat', {
                        groupe: constat.groupe,
                        effectif: Utils.formatNumber(constat.effectif),
                        droits: constat.droits.length,
                        origine: constat.origine,
                        part: Utils.valeurDansLaLangue(constat.part_minimale)}))}
                </p>
                <ul class="mouvement-droits">
                    ${constat.droits.map((droit) => `
                        <li>${Utils.escapeHtml(I18n.t('mouvement.droit', {
                            droit: droit.droit,
                            autres: Utils.formatNumber(droit.autres_du_groupe),
                            part: Utils.valeurDansLaLangue(droit.part_de_l_origine),
                            origine: constat.origine}))}${droit.justifie ? `
                            <span class="badge badge-success">${Utils.escapeHtml(
                                I18n.t('ecart.justifie'))}</span>` : ''}</li>`).join('')}
                </ul>
            </li>`;
    },
};

window.MouvementPage = MouvementPage;
