/**
 * L'assistant : une question posée depuis l'écran où l'on est.
 *
 * Il n'a pas de page. Une question sur un rôle se pose en regardant ce rôle,
 * et devoir naviguer vers un écran dédié pour la poser revient exactement à la
 * navigation que l'assistant existe pour éviter.
 *
 * Ce que l'écran affiche, dans cet ordre de préférence :
 *
 * 1. la réponse **rédigée**, quand l'administrateur a ouvert l'usage et que le
 *    modèle a respecté son contrat — il écrit un gabarit, le serveur le
 *    remplit, et aucun chiffre ne lui a été transmis ;
 * 2. sinon la phrase **calculée**, assemblée à partir du catalogue de
 *    traduction et des nombres du produit.
 *
 * La seconde existe toujours : c'est ce qui permet à l'assistant de servir sur
 * un serveur sans accès, et de continuer à répondre quand une phrase rédigée
 * est refusée.
 */

const AgentPanneau = {
    /** Les questions que le serveur sait calculer, telles qu'il les nomme. */
    intentions: [],

    /** Ce dont parlait le dernier échange. C'est ce qui permet « et ses rôles ? ». */
    contexte: {},

    /** Tableaux construits pour les réponses, par rang d'échange. */
    tableaux: {},

    /** Rang du prochain échange. Il sert d'identifiant aux éléments rendus. */
    rang: 0,

    ouvert: false,

    init() {
        const lanceur = document.getElementById('agent-lanceur');
        if (!lanceur || lanceur.dataset.branche) return;
        lanceur.dataset.branche = 'oui';
        lanceur.addEventListener('click', () => this.basculer());

        const fermer = document.getElementById('agent-fermer');
        if (fermer) fermer.addEventListener('click', () => this.fermer());

        const vider = document.getElementById('agent-vider');
        if (vider) vider.addEventListener('click', () => this.vider());

        const formulaire = document.getElementById('agent-formulaire');
        if (formulaire) {
            formulaire.addEventListener('submit', (evenement) => {
                evenement.preventDefault();
                this.poser();
            });
        }

        // Les réponses sont réécrites à chaque échange : le clic est écouté
        // sur le conteneur, qui, lui, reste en place.
        const echanges = document.getElementById('agent-echanges');
        if (echanges) {
            echanges.addEventListener('click', (evenement) => {
                const choix = evenement.target.closest('[data-agent-choix]');
                if (choix) {
                    this.poser(choix.dataset.agentQuestion,
                               choix.dataset.agentIntention,
                               choix.dataset.agentEntite);
                    return;
                }
                const ecran = evenement.target.closest('[data-agent-ecran]');
                if (ecran) this.ouvrirLEcran(ecran.dataset.agentEcran,
                                             ecran.dataset.agentFiltre || '');
            });
        }

        // Échap ferme le panneau : il se superpose à l'écran de travail, et
        // tout ce qui se superpose doit se refermer au clavier.
        document.addEventListener('keydown', (evenement) => {
            if (evenement.key === 'Escape' && this.ouvert) this.fermer();
        });
    },

    basculer() {
        if (this.ouvert) this.fermer(); else this.ouvrir();
    },

    ouvrir() {
        const panneau = document.getElementById('agent-panneau');
        const lanceur = document.getElementById('agent-lanceur');
        if (!panneau) return;
        panneau.hidden = false;
        this.ouvert = true;
        if (lanceur) lanceur.setAttribute('aria-expanded', 'true');
        if (!this.intentions.length) this.chargerLesIntentions();
        const champ = document.getElementById('agent-question');
        if (champ) champ.focus();
    },

    fermer() {
        const panneau = document.getElementById('agent-panneau');
        const lanceur = document.getElementById('agent-lanceur');
        if (panneau) panneau.hidden = true;
        this.ouvert = false;
        if (lanceur) {
            lanceur.setAttribute('aria-expanded', 'false');
            // Le focus revient d'où il vient : sans cela, il repart en haut de
            // la page et l'utilisateur au clavier a tout perdu.
            lanceur.focus();
        }
    },

    /** Efface la conversation, et le sujet qu'elle portait. */
    vider() {
        const echanges = document.getElementById('agent-echanges');
        if (echanges) {
            echanges.innerHTML = `<p class="agent-vide">${
                Utils.escapeHtml(I18n.t('agent.panneau.vide'))}</p>`;
        }
        this.contexte = {};
        this.tableaux = {};
    },

    /**
     * Les exemples. Un champ de saisie libre sans exemple se lit comme une
     * boîte noire, et l'utilisateur y écrit des questions auxquelles rien ne
     * répond.
     */
    async chargerLesIntentions() {
        const zone = document.getElementById('agent-exemples');
        if (!zone) return;
        try {
            const corps = await API.get('/agent/intentions',
                                        {locale: I18n.currentLocale});
            this.intentions = corps.intentions || [];
        } catch (erreur) {
            this.intentions = [];
        }
        zone.innerHTML = this.intentions.map((intention) => `
            <button type="button" class="btn btn-sm btn-secondary"
                    data-agent-exemple="${Utils.escapeHtml(intention.code)}">
                ${Utils.escapeHtml(intention.libelle)}
            </button>`).join('');
        zone.querySelectorAll('[data-agent-exemple]').forEach((bouton) => {
            bouton.addEventListener('click', () => {
                const champ = document.getElementById('agent-question');
                if (champ) {
                    champ.value = bouton.textContent.trim();
                    champ.focus();
                }
            });
        });
    },

    /** Pose la question écrite, ou celle qu'un choix vient de préciser. */
    async poser(question, intention, entite) {
        const champ = document.getElementById('agent-question');
        const texte = (question !== undefined ? question
                                              : (champ ? champ.value : '')).trim();
        if (!texte) {
            Toast.error(I18n.t('common.error'), I18n.t('agent.question_vide'));
            return;
        }
        const bouton = document.getElementById('agent-demander');
        if (bouton) bouton.disabled = true;
        try {
            const charge = {question: texte, locale: I18n.currentLocale};
            if (intention) charge.intention = intention;
            if (entite) charge.entite = entite;
            // Le sujet du dernier échange voyage avec la question : c'est ce
            // qui permet d'écrire « et ses rôles ? » sans répéter le matricule.
            if (this.contexte && this.contexte.entite) charge.contexte = this.contexte;
            const rendu = await API.post('/agent/question', charge);
            this.contexte = rendu.contexte && rendu.contexte.entite
                ? rendu.contexte : this.contexte;
            this.rendreUnEchange(rendu);
            if (champ && question === undefined) champ.value = '';
        } catch (erreur) {
            Toast.error(I18n.t('common.error'),
                        erreur.message || I18n.t('agent.erreur'));
        } finally {
            if (bouton) bouton.disabled = false;
        }
    },

    /** D'où vient la réponse, dite en clair sous chaque échange. */
    provenance(rendu) {
        const lignes = [];
        if ((rendu.redaction || {}).texte) {
            lignes.push(I18n.t('agent.redige_par',
                               {modele: rendu.redaction.modele || ''}));
        }
        if (rendu.origine === 'modele') {
            lignes.push(I18n.t('agent.origine.modele', {modele: rendu.modele || ''}));
        } else if (rendu.origine === 'utilisateur') {
            lignes.push(I18n.t('agent.origine.utilisateur'));
        } else if (rendu.origine === 'locale') {
            lignes.push(I18n.t('agent.origine.locale'));
        }
        return lignes;
    },

    /** La réponse affichée : rédigée si elle existe, calculée sinon. */
    phrases(rendu) {
        if ((rendu.redaction || {}).texte) return [rendu.redaction.texte];
        const phrases = [];
        if ((rendu.entete || {}).cle) {
            phrases.push(I18n.t(rendu.entete.cle, rendu.entete.params || {}));
        }
        const sujets = rendu.sujets || [];
        if (sujets.length > 1) {
            sujets.forEach((sujet) => phrases.push(
                I18n.t(sujet.reponse.cle, sujet.reponse.params || {})));
        } else if (rendu.reponse && rendu.reponse.cle) {
            phrases.push(I18n.t(rendu.reponse.cle, rendu.reponse.params || {}));
        }
        return phrases;
    },

    rendreUnEchange(rendu) {
        const echanges = document.getElementById('agent-echanges');
        if (!echanges) return;
        const vide = echanges.querySelector('.agent-vide');
        if (vide) vide.remove();

        const rang = (this.rang += 1);
        const choix = rendu.choix || {};
        const options = choix.options || [];
        const sujets = (rendu.sujets || []).filter(
            (sujet) => (sujet.lignes || {}).identifiants
                && sujet.lignes.identifiants.length);

        const bloc = document.createElement('article');
        bloc.className = 'agent-echange';
        bloc.innerHTML = `
            <p class="agent-question">${Utils.escapeHtml(rendu.question || '')}</p>
            ${this.phrases(rendu).map((phrase) =>
                `<p class="agent-reponse">${Utils.escapeHtml(phrase)}</p>`).join('')}
            ${this.provenance(rendu).map((ligne) =>
                `<p class="agent-origine">${Utils.escapeHtml(ligne)}</p>`).join('')}
            ${options.length ? `
                <p class="form-hint">${Utils.escapeHtml(I18n.t(choix.cle))}</p>
                <div class="agent-choix">${options.map((option) => `
                    <button type="button" class="btn btn-sm btn-secondary"
                            data-agent-choix="1"
                            data-agent-question="${Utils.escapeHtml(rendu.question || '')}"
                            data-agent-intention="${Utils.escapeHtml(
                                option.valeur || rendu.intention || '')}"
                            data-agent-entite="${Utils.escapeHtml(
                                option.identifiant || '')}">
                        ${Utils.escapeHtml(option.libelle || option.identifiant || '')}
                    </button>`).join('')}</div>
            ` : ''}
            ${sujets.map((sujet, rangSujet) => `
                <p class="agent-legende">${Utils.escapeHtml(
                    [sujets.length > 1 ? sujet.identifiant : '',
                     I18n.t(sujet.lignes.legende)].filter(Boolean).join(' — '))}${
                    // Le marquage vient du serveur, jamais d'une lecture de
                    // l'identifiant ici : la règle est déclarée dans le
                    // workspace, et deux endroits qui la reliraient séparément
                    // finiraient par ne pas dire la même chose du même compte.
                    sujet.a_privileges ? `
                    <span class="badge badge-warning">${Utils.escapeHtml(
                        I18n.t('agent.compte.a_privileges'))}</span>` : ''}</p>
                <div class="table-wrapper" role="region"
                     aria-label="${Utils.escapeHtml(I18n.t(sujet.lignes.legende))}">
                    <table class="data-table" id="agent-table-${rang}-${rangSujet}">
                        <thead id="agent-thead-${rang}-${rangSujet}"></thead>
                        <tbody id="agent-tbody-${rang}-${rangSujet}"></tbody>
                    </table>
                </div>
                <div class="table-pagination">
                    <button class="pagination-btn" id="agent-${rang}-${rangSujet}-prev" disabled>
                        <i class="fas fa-chevron-left" aria-hidden="true"></i>
                        <span data-i18n-key="pagination.previous">Précédent</span>
                    </button>
                    <div class="pagination-info">
                        <span data-i18n-key="pagination.page">Page</span>
                        <span class="pagination-current" id="agent-${rang}-${rangSujet}-current-page">1</span>
                        <span data-i18n-key="pagination.of">sur</span>
                        <span class="pagination-total" id="agent-${rang}-${rangSujet}-total-pages">1</span>
                    </div>
                    <button class="pagination-btn" id="agent-${rang}-${rangSujet}-next">
                        <span data-i18n-key="pagination.next">Suivant</span>
                        <i class="fas fa-chevron-right" aria-hidden="true"></i>
                    </button>
                </div>
                ${(sujet.ecran || {}).page ? `
                    <button type="button" class="btn btn-sm btn-secondary"
                            data-agent-ecran="${Utils.escapeHtml(sujet.ecran.page)}"
                            data-agent-filtre="${Utils.escapeHtml(
                                sujet.ecran.filtre || '')}">
                        ${Utils.escapeHtml(I18n.t('agent.voir_ecran'))}
                    </button>
                ` : ''}
            `).join('')}
        `;
        // Le dernier échange en premier : c'est celui qu'on vient de demander.
        echanges.insertBefore(bloc, echanges.firstChild);
        I18n.applyTranslations();

        sujets.forEach((sujet, rangSujet) =>
            this.rendreLeTableau(rang, rangSujet, sujet.lignes));
    },

    /**
     * Le tableau des lignes concernées, avec les colonnes du client.
     *
     * Le même composant et la même route que la fenêtre de validation et que
     * les porteurs d'un rôle : trois écrans qui afficheraient différemment un
     * identifiant inconnu du référentiel diraient trois choses différentes de
     * la même donnée.
     */
    rendreLeTableau(rang, rangSujet, lignes) {
        const tableau = new DataTable({
            type: `agent-${lignes.referentiel}`,
            endpoint: `/referentiels/${lignes.referentiel}/lignes`,
            theadId: `agent-thead-${rang}-${rangSujet}`,
            tbodyId: `agent-tbody-${rang}-${rangSujet}`,
            paginationPrefix: `agent-${rang}-${rangSujet}`,
            pageSize: 5,
            detail: false,
            corps: () => ({identifiants: lignes.identifiants}),
        });
        this.tableaux[`${rang}-${rangSujet}`] = tableau;
        tableau.load();
    },

    /** Champ de recherche de chaque écran, pour y porter le filtre. */
    get CHAMPS_DE_RECHERCHE() {
        return {
            users: 'search-users',
            rights: 'search-rights',
            applications: 'search-applications',
            'roles-catalog': 'roles-search',
        };
    },

    /**
     * Ouvre l'écran concerné, **filtré sur la réponse**.
     *
     * Sans le filtre, le lien renvoyait vers un référentiel entier : à
     * l'utilisateur de retrouver lui-même ce dont l'assistant venait de
     * parler. C'était exactement le trajet que l'assistant existe pour éviter.
     */
    ouvrirLEcran(page, filtre) {
        if (!page) return;
        App.navigateTo(page);
        this.fermer();
        const champ = document.getElementById(this.CHAMPS_DE_RECHERCHE[page] || '');
        if (!champ || !filtre) return;
        champ.value = filtre;
        // L'événement, et non l'appel direct : chaque écran a branché sa propre
        // réaction à la saisie, et la contourner en appellerait une autre.
        champ.dispatchEvent(new Event('input', {bubbles: true}));
    },
};

window.AgentPanneau = AgentPanneau;
