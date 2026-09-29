/**
 * PyGIA Frontend - UI Components
 * Reusable UI component classes
 */

/**
 * Toast Notification System
 */
class ToastManager {
    /** Durée de vie d'une notification d'erreur, en millisecondes. */
    static DUREE_ERREUR_MS = 15000;

    constructor(containerId = 'toast-container') {
        this.container = document.getElementById(containerId);
    }

    show({ type = 'info', title, message, duration = 4000 }) {
        // Une notification identique à celle qui est déjà à l'écran n'apprend
        // rien de plus : elle empile deux fois le même texte et fait croire à
        // deux incidents. Elle est **rafraîchie** plutôt qu'ajoutée — son
        // compte à rebours repart, donc le message reste visible aussi
        // longtemps que s'il venait d'arriver. La masquer serait pire : un
        // refus répété doit rester lisible.
        const jumelle = this.identique(type, title, message);
        if (jumelle) {
            this.reporter(jumelle, duration);
            return jumelle;
        }
        const icons = {
            success: 'fa-check',
            error: 'fa-times',
            warning: 'fa-exclamation',
            info: 'fa-info'
        };

        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        // Une erreur interrompt la lecture en cours ; le reste attend une
        // pause. Le conteneur est déjà une région de statut : ce rôle-ci ne
        // sert qu'à distinguer l'urgence.
        toast.setAttribute('role', type === 'error' ? 'alert' : 'status');
        toast.innerHTML = `
            <div class="toast-icon"><i class="fas ${icons[type]}" aria-hidden="true"></i></div>
            <div class="toast-content">
                <div class="toast-title">${Utils.escapeHtml(title)}</div>
                ${message ? `<div class="toast-message">${Utils.escapeHtml(message)}</div>` : ''}
            </div>
            <button class="toast-close" aria-label="${Utils.escapeHtml(I18n.t('a11y.close_notification'))}"><i class="fas fa-times" aria-hidden="true"></i></button>
        `;

        toast.querySelector('.toast-close').addEventListener('click', () => this.remove(toast));
        this.container.appendChild(toast);

        this.reporter(toast, duration);
        return toast;
    }

    /** Repousse la disparition d'une notification, et annule la précédente. */
    reporter(toast, duration) {
        if (toast._minuteur) clearTimeout(toast._minuteur);
        if (duration > 0) {
            toast._minuteur = setTimeout(() => this.remove(toast), duration);
        }
    }

    /** La notification déjà affichée qui porte exactement ce message. */
    identique(type, title, message) {
        if (!this.container) return null;
        return Array.from(this.container.querySelectorAll('.toast'))
            .find((toast) => !toast.classList.contains('removing')
                && toast.classList.contains(type)
                && (toast.querySelector('.toast-title')?.textContent || '') === (title || '')
                && (toast.querySelector('.toast-message')?.textContent || '') === (message || ''))
            || null;
    }

    remove(toast) {
        toast.classList.add('removing');
        setTimeout(() => toast.remove(), 300);
    }

    success(title, message) { return this.show({ type: 'success', title, message }); }

    /**
     * Une erreur reste bien plus longtemps qu'un succès.
     *
     * Quatre secondes, c'est le temps de voir passer quelque chose, pas de le
     * lire : une notification d'erreur est le seul endroit où l'utilisateur
     * apprend *pourquoi* une action a été refusée, et la faire disparaître si
     * vite revient à refuser en silence.
     *
     * Elle ne reste pas indéfiniment pour autant. Les notifications occupent un
     * coin de l'écran : une erreur qui ne part jamais finit par recouvrir ce
     * qu'on essaie de cliquer, et transforme un refus en blocage. Le bouton de
     * fermeture reste la sortie immédiate.
     */
    error(title, message) {
        return this.show({ type: 'error', title, message,
                           duration: ToastManager.DUREE_ERREUR_MS });
    }
    warning(title, message) { return this.show({ type: 'warning', title, message }); }
    info(title, message) { return this.show({ type: 'info', title, message }); }
}

/**
 * Modal Manager
 */
class ModalManager {
    /**
     * Ce qui, dans une fenêtre modale, peut recevoir le focus.
     *
     * `:not([disabled])` et le filtre de visibilité écartent ce qui existe
     * dans le balisage mais n'est pas atteignable : un bouton désactivé, un
     * bloc masqué. Les inclure ferait tourner la tabulation dans le vide.
     */
    static get SELECTEUR_FOCUSABLE() {
        return 'a[href], button:not([disabled]), input:not([disabled]),'
             + ' select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
    }

    constructor() {
        this.activeModal = null;
        //: Élément qui a ouvert la fenêtre. Le focus lui revient à la
        //: fermeture : sans cela il repart au début du document, et
        //: l'utilisateur au clavier doit refaire tout le chemin.
        this.declencheur = null;
        this.initEventListeners();
    }

    initEventListeners() {
        document.addEventListener('click', (e) => {
            if (e.target.matches('[data-close-modal]')) {
                this.close();
            }
            if (e.target.matches('.modal-overlay')) {
                this.close();
            }
        });

        document.addEventListener('keydown', (e) => {
            if (!this.activeModal) {
                return;
            }
            if (e.key === 'Escape') {
                this.close();
                return;
            }
            if (e.key === 'Tab') {
                this.retenirLeFocus(e);
            }
        });
    }

    /** Éléments focusables et visibles de la fenêtre ouverte. */
    focusables() {
        return [...this.activeModal.querySelectorAll(ModalManager.SELECTEUR_FOCUSABLE)]
            .filter(el => el.offsetWidth || el.offsetHeight || el.getClientRects().length);
    }

    /**
     * Fait tourner la tabulation à l'intérieur de la fenêtre.
     *
     * Le reste de la page est déjà rendu inerte, mais la tabulation sort par
     * le haut et par le bas vers les commandes du navigateur, puis revient au
     * début du document : l'utilisateur se retrouve derrière une fenêtre
     * qu'il ne voit plus. Critère RGAA 12.8.
     */
    retenirLeFocus(evenement) {
        const atteignables = this.focusables();
        if (!atteignables.length) {
            evenement.preventDefault();
            return;
        }
        const premier = atteignables[0];
        const dernier = atteignables[atteignables.length - 1];
        const courant = document.activeElement;
        if (evenement.shiftKey && (courant === premier || !this.activeModal.contains(courant))) {
            evenement.preventDefault();
            dernier.focus();
        } else if (!evenement.shiftKey && courant === dernier) {
            evenement.preventDefault();
            premier.focus();
        }
    }

    /**
     * Rend inerte tout ce qui n'est pas la fenêtre ouverte.
     *
     * Seul `#app` l'était. C'était suffisant tant que tout le reste de la page
     * vivait dedans — ce n'est plus vrai : le lanceur de l'assistant est un
     * frère de `#app` sous `<body>`, et il restait donc atteignable au clavier
     * **derrière** une fenêtre modale. La première tabulation en sortait, et
     * l'utilisateur se retrouvait sur un bouton qu'il ne voyait pas.
     *
     * Nommer cet élément-là ici aurait corrigé ce cas et laissé le suivant :
     * la règle est que **rien hors de la fenêtre n'est atteignable**, et c'est
     * la règle qui est écrite. Les notifications y passent aussi — elles
     * restent visibles, mais ne se ferment qu'une fois la fenêtre fermée, ce
     * qui est le comportement qu'un lecteur d'écran attend d'un dialogue.
     *
     * Les éléments déjà inertes sont mémorisés pour ne pas être « réveillés »
     * à la fermeture : rendre vivant ce qui ne l'était pas est le défaut
     * symétrique, et il est plus difficile à voir.
     */
    rendreInerteLeReste(fenetre) {
        this.rendus = [];
        for (const element of document.body.children) {
            if (element === fenetre || element.inert) continue;
            element.inert = true;
            this.rendus.push(element);
        }
    }

    /** Rend au reste de la page ce que l'ouverture lui avait retiré. */
    rendreLeResteVivant() {
        (this.rendus || []).forEach((element) => { element.inert = false; });
        this.rendus = [];
    }

    open(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            this.declencheur = document.activeElement;
            modal.style.display = 'flex';  // ← AJOUTÉ !
            modal.classList.add('active');
            this.activeModal = modal;
            document.body.style.overflow = 'hidden';
            // Le reste de la page cesse d'exister pour le clavier et pour les
            // outils d'assistance tant que la fenêtre est ouverte. `inert`
            // fait en une ligne ce que `aria-hidden` et une gestion manuelle
            // des `tabindex` font mal.
            this.rendreInerteLeReste(modal);
            // Le focus entre dans la fenêtre : sans cela il reste sur le
            // bouton qui l'a ouverte, derrière un voile, et la tabulation
            // suivante repart du haut du document.
            const boite = modal.querySelector('[role="dialog"]') || modal;
            if (!boite.hasAttribute('tabindex')) {
                boite.setAttribute('tabindex', '-1');
            }
            const premier = this.focusables()[0];
            (premier || boite).focus();
        }
    }

    close() {
        if (this.activeModal) {
            this.activeModal.classList.remove('active');
            this.activeModal = null;
            document.body.style.overflow = '';
            this.rendreLeResteVivant();
            if (this.declencheur && this.declencheur.isConnected) {
                this.declencheur.focus();
            }
            this.declencheur = null;
        }
    }
}

/**
 * Data Table Component
 */
class DataTable {
    /** Préfixe des réglages retenus sur le poste, par type de tableau. */
    static get CLE_REGLAGES() { return 'kovex.tableau'; }

    /** Largeur minimale d'une colonne, en pixels. En deçà, l'en-tête et sa
     *  poignée ne tiennent plus, et la colonne devient impossible à rattraper. */
    static get LARGEUR_MINIMALE() { return 72; }

    /** Pas de réglage au clavier, en pixels. */
    static get PAS_DE_LARGEUR() { return 16; }

    /**
     * Ce que l'utilisateur a réglé sur ce poste pour ce tableau.
     *
     * Les colonnes masquées et les largeurs sont un confort de lecture, pas
     * une décision de gouvernance : elles restent sur le poste et ne partent
     * ni dans l'espace de travail, ni dans un export. Un stockage indisponible
     * — navigation privée, site bloqué — rend les réglages par défaut sans
     * casser le tableau.
     */
    static reglagesRetenus(type) {
        const retenu = Utils.storage.get(`${DataTable.CLE_REGLAGES}.${type}`, {});
        return {
            masquees: Array.isArray(retenu && retenu.masquees) ? retenu.masquees : [],
            largeurs: (retenu && typeof retenu.largeurs === 'object' && retenu.largeurs)
                ? retenu.largeurs : {}
        };
    }

    constructor(options) {
        this.type = options.type;
        this.endpoint = options.endpoint;
        this.theadId = options.theadId;
        this.tbodyId = options.tbodyId;
        this.searchId = options.searchId;
        this.countId = options.countId;
        this.paginationPrefix = options.paginationPrefix;

        //: Corps de requête, quand le tableau ne se lit pas par son adresse.
        //
        //  Un tableau restreint à une liste d'identifiants — les porteurs d'un
        //  rôle candidat — ne peut pas les faire tenir dans une chaîne de
        //  requête : un rôle de trois mille porteurs la ferait déborder. La
        //  fonction rend ce que l'appelant veut envoyer ; le tableau y ajoute
        //  la page, le tri et la recherche.
        this.corps = options.corps || null;

        //: Paramètres d'adresse ajoutés à chaque page, quand l'adresse seule
        //  ne dit pas quelles lignes rendre — une population d'un couple
        //  (rôle, accès), par exemple. La fonction est relue à chaque
        //  chargement : le tableau suit ce que l'utilisateur a choisi.
        this.parametres = options.parametres || null;

        //: Sélection tenue **hors du tableau**, quand il en porte une.
        //
        //  C'est la condition pour que trier ou changer de page ne perde rien :
        //  une case non rendue n'existe plus dans la page, et une sélection
        //  lue dans le DOM se viderait au premier tri. L'objet répond à
        //  `contient(identifiant)` et `basculer(identifiant, coche)`.
        this.selection = options.selection || null;

        //: L'accès au détail. Il ouvre une fenêtre par-dessus le tableau : à
        //  l'intérieur d'une fenêtre de validation, ce serait une fenêtre
        //  sur une fenêtre, et le travail en cours passerait derrière.
        this.detail = options.detail !== false;

        //: Lignes par page. Une fenêtre de validation en montre moins qu'un
        //  écran d'exploration, et la valeur n'a pas à être la même partout.
        this.pageSize = options.pageSize || null;

        //: Clé du message d'une table vide, quand le domaine en a un plus
        //  juste que « aucune donnée ». Un rôle sans droit n'est pas un
        //  référentiel vide, et l'utilisateur n'a pas à faire la traduction.
        this.messageVide = options.messageVide || 'table.no_data';
        
        this.columnsButtonId = options.columnsButtonId
            || `${this.paginationPrefix}-columns-button`;
        this.columnsPanelId = options.columnsPanelId
            || `${this.paginationPrefix}-columns-panel`;
        this.columnsListId = options.columnsListId
            || `${this.paginationPrefix}-columns-list`;
        this.columnsCountId = options.columnsCountId
            || `${this.paginationPrefix}-columns-count`;
        this.columnsAllId = options.columnsAllId
            || `${this.paginationPrefix}-columns-all`;
        //: Le bouton qui rend l'ordre et la recherche d'origine. Facultatif :
        //  le tableau fonctionne sans, et n'en cherche un que s'il existe.
        this.resetId = options.resetId || `${this.paginationPrefix}-reset`;

        const retenu = DataTable.reglagesRetenus(this.type);
        this.state = {
            page: 1,
            totalPages: 1,
            search: '',
            sortCol: null,
            sortDesc: false,
            // Les colonnes ne sont connues qu'après la première réponse : ce
            // sont celles du fichier du client, et le produit n'en présume
            // aucune. Elles sont mémorisées à chaque rendu pour que le
            // sélecteur ait quelque chose à proposer.
            colonnes: [],
            masquees: new Set(retenu.masquees),
            largeurs: Object.assign({}, retenu.largeurs)
        };

        this.initEventListeners();
        this.initColumnControls();
    }

    initEventListeners() {
        // Search
        const searchInput = document.getElementById(this.searchId);
        if (searchInput) {
            searchInput.addEventListener('input', Utils.debounce((e) => {
                this.state.search = e.target.value;
                this.state.page = 1;
                this.load();
            }, Config.SEARCH_DEBOUNCE));
        }

        // Pagination
        const prevBtn = document.getElementById(`${this.paginationPrefix}-prev`);
        const nextBtn = document.getElementById(`${this.paginationPrefix}-next`);
        
        if (prevBtn) prevBtn.addEventListener('click', () => this.changePage(-1));
        if (nextBtn) nextBtn.addEventListener('click', () => this.changePage(1));

        // Délégation sur le corps : les cases sont réécrites à chaque tri et à
        // chaque page, un écouteur posé sur chacune serait perdu — et la
        // sélection avec lui.
        const tbody = document.getElementById(this.tbodyId);
        if (tbody && this.selection) {
            tbody.addEventListener('change', (evenement) => {
                const case_ = evenement.target.closest('[data-selection]');
                if (!case_) return;
                this.selection.basculer(case_.dataset.selection, case_.checked);
                this.majCaseTout();
            });
        }

        // La case de l'en-tête coche ou décoche **toutes** les lignes, pas
        // seulement celles de la page : la sélection vit hors du tableau, et
        // c'est elle qui décide de ce qui sera validé. L'en-tête est réécrit
        // à chaque chargement, d'où la délégation.
        const thead = document.getElementById(this.theadId);
        if (thead && this.peutToutSelectionner()) {
            thead.addEventListener('change', (evenement) => {
                const case_ = evenement.target.closest('[data-selection-tout]');
                if (!case_) return;
                this.selection.tout(case_.checked);
                if (tbody) {
                    tbody.querySelectorAll('[data-selection]').forEach((ligne) => {
                        ligne.checked = case_.checked;
                    });
                }
                this.majCaseTout();
            });
        }

        const reinitialisation = document.getElementById(this.resetId);
        if (reinitialisation) {
            reinitialisation.addEventListener('click', () => this.reinitialiser());
        }
    }

    /**
     * Rend l'ordre et la recherche d'origine.
     *
     * Trier par une colonne, puis par une autre, puis chercher : il n'y avait
     * plus de chemin pour revenir à la liste telle qu'elle s'ouvre, sinon
     * fermer la fenêtre et perdre ce qu'on avait décoché.
     */
    reinitialiser() {
        this.state.search = '';
        this.state.sortCol = null;
        this.state.sortDesc = false;
        this.state.page = 1;
        const recherche = document.getElementById(this.searchId);
        if (recherche) recherche.value = '';
        this.load();
    }

    /** Le bouton de réinitialisation n'est actif que s'il y a de quoi faire. */
    majReinitialisation() {
        const bouton = document.getElementById(this.resetId);
        if (!bouton) return;
        bouton.disabled = !this.state.search && !this.state.sortCol;
    }

    /** La sélection sait-elle tout cocher et dire où elle en est ? */
    peutToutSelectionner() {
        return Boolean(this.selection
            && typeof this.selection.tout === 'function'
            && typeof this.selection.etat === 'function');
    }

    /**
     * L'état de la case de l'en-tête : cochée si tout est retenu, vide si rien
     * ne l'est, indéterminée entre les deux — l'état qu'un tableau à cases
     * annonce partout ailleurs.
     */
    majCaseTout() {
        if (!this.peutToutSelectionner()) return;
        const thead = document.getElementById(this.theadId);
        const case_ = thead && thead.querySelector('[data-selection-tout]');
        if (!case_) return;
        const etat = this.selection.etat();
        case_.checked = etat === 'tous';
        case_.indeterminate = etat === 'partiel';
    }

    async load() {
        const tbody = document.getElementById(this.tbodyId);
        const thead = document.getElementById(this.theadId);
        
        if (!tbody) return;
        this.majReinitialisation();

        tbody.innerHTML = `
            <tr>
                <td colspan="10" class="table-loading">
                    <div class="loading-spinner"></div>
                    <span>${Utils.escapeHtml(I18n.t('table.loading_data'))}</span>
                </td>
            </tr>
        `;

        try {
            const params = Object.assign({}, this.parametres ? this.parametres() : {}, {
                page: this.state.page,
                size: this.taillePage()
            });
            
            if (this.state.search) params.search = this.state.search;
            if (this.state.sortCol) {
                params.sort_col = this.state.sortCol;
                params.sort_desc = this.state.sortDesc;
            }

            const response = this.corps
                ? await API.client.post(this.endpoint,
                                        Object.assign({}, this.corps(), params))
                : await API.client.get(this.endpoint, params);
            // Les colonnes sont rendues par le serveur quand il les connaît :
            // une page vide garde alors ses en-têtes, et l'utilisateur voit
            // toujours sur quoi il cherche.
            if (Array.isArray(response.colonnes) && response.colonnes.length) {
                this.state.colonnesServeur = response.colonnes;
            }
            this.state.colonneIdentifiant = response.colonne_identifiant || null;
            // Les comptes à privilèges de **cette page**. Rendus à part des
            // lignes : les colonnes viennent du fichier du client, et en
            // ajouter une écraserait celle qui porterait ce nom chez lui.
            this.state.aPrivileges = new Set(
                Array.isArray(response.comptes_a_privileges)
                    ? response.comptes_a_privileges : []);
            // Les identifiants demandés que le référentiel ne connaît pas.
            // L'appelant les signale : une ligne sans colonne se lit sinon
            // comme un défaut d'affichage.
            this.state.inconnus = Array.isArray(response.inconnus)
                ? response.inconnus : [];
            
            this.state.totalPages = response.total_pages || 1;
            this.updatePagination(response);
            this.renderTable(thead, tbody, response.data);
            
        } catch (error) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="10" class="table-loading text-danger">
                        <i class="fas fa-exclamation-triangle" aria-hidden="true"></i>
                        <span>${Utils.escapeHtml(I18n.t('table.load_error'))}</span>
                    </td>
                </tr>
            `;
        }
    }

    /** Taille de page. Réglable par tableau, sans quoi elle serait en dur. */
    taillePage() {
        return this.pageSize || Config.DEFAULT_PAGE_SIZE;
    }

    updatePagination(response) {
        const countEl = document.getElementById(this.countId);
        const currentPageEl = document.getElementById(`${this.paginationPrefix}-current-page`);
        const totalPagesEl = document.getElementById(`${this.paginationPrefix}-total-pages`);
        const prevBtn = document.getElementById(`${this.paginationPrefix}-prev`);
        const nextBtn = document.getElementById(`${this.paginationPrefix}-next`);

        if (countEl) countEl.textContent = Utils.formatNumber(response.total_items);
        if (currentPageEl) currentPageEl.textContent = response.current_page;
        if (totalPagesEl) totalPagesEl.textContent = response.total_pages;
        if (prevBtn) prevBtn.disabled = response.current_page <= 1;
        if (nextBtn) nextBtn.disabled = response.current_page >= response.total_pages;
    }

    changePage(delta) {
        const newPage = this.state.page + delta;
        if (newPage >= 1 && newPage <= this.state.totalPages) {
            this.state.page = newPage;
            this.load();
        }
    }

    // ------------------------------------------- colonnes : choix et largeur

    retenirLesReglages() {
        Utils.storage.set(`${DataTable.CLE_REGLAGES}.${this.type}`, {
            masquees: Array.from(this.state.masquees),
            largeurs: this.state.largeurs
        });
    }

    /**
     * Les colonnes effectivement rendues.
     *
     * Un garde-fou plutôt qu'une politesse : les réglages retenus survivent au
     * changement d'espace de travail, et un référentiel dont toutes les
     * colonnes portent les noms masqués la fois précédente afficherait un
     * tableau vide, sans rien pour le réparer. Dans ce cas le masquage est
     * oublié — mieux vaut montrer trop que ne rien montrer.
     */
    colonnesVisibles(colonnes) {
        const visibles = colonnes.filter(col => !this.state.masquees.has(col));
        if (visibles.length > 0) return visibles;
        this.state.masquees = new Set();
        this.retenirLesReglages();
        return colonnes.slice();
    }

    /** Style de largeur d'une colonne, vide tant qu'elle n'a pas été réglée. */
    styleDeColonne(col) {
        const largeur = this.state.largeurs[col];
        if (!largeur) return '';
        // `max-width` autant que `width` : la feuille de style borne les
        // cellules à 300px, et une colonne élargie doit pouvoir dépasser.
        return ` style="width:${largeur}px;max-width:${largeur}px"`;
    }

    initColumnControls() {
        const bouton = document.getElementById(this.columnsButtonId);
        if (bouton) {
            bouton.addEventListener('click', () => this.basculerLeSelecteur());
        }
        const tout = document.getElementById(this.columnsAllId);
        if (tout) {
            tout.addEventListener('click', () => {
                this.state.masquees = new Set();
                this.retenirLesReglages();
                this.rendreLeSelecteur();
                this.load();
            });
        }
        // Fermetures : au clavier par Échap, à la souris en cliquant ailleurs.
        // Un panneau qui reste ouvert derrière le reste de l'écran est une
        // gêne, et il masque la première colonne du tableau.
        document.addEventListener('keydown', (evenement) => {
            if (evenement.key === 'Escape') this.fermerLeSelecteur();
        });
        document.addEventListener('click', (evenement) => {
            const panneau = document.getElementById(this.columnsPanelId);
            if (!panneau || panneau.hidden) return;
            if (evenement.target.closest(`#${this.columnsPanelId}`)
                || evenement.target.closest(`#${this.columnsButtonId}`)) return;
            this.fermerLeSelecteur();
        });
    }

    basculerLeSelecteur() {
        const panneau = document.getElementById(this.columnsPanelId);
        if (!panneau) return;
        if (panneau.hidden) {
            this.rendreLeSelecteur();
            panneau.hidden = false;
        } else {
            panneau.hidden = true;
        }
        const bouton = document.getElementById(this.columnsButtonId);
        if (bouton) bouton.setAttribute('aria-expanded', String(!panneau.hidden));
    }

    fermerLeSelecteur() {
        const panneau = document.getElementById(this.columnsPanelId);
        if (!panneau || panneau.hidden) return;
        panneau.hidden = true;
        const bouton = document.getElementById(this.columnsButtonId);
        if (bouton) bouton.setAttribute('aria-expanded', 'false');
    }

    /**
     * Écrit la liste des colonnes à cocher.
     *
     * Les libellés sont les noms de colonnes du fichier du client : ce sont
     * des données, elles ne passent pas par le catalogue de traductions et
     * elles sont échappées.
     */
    rendreLeSelecteur() {
        const liste = document.getElementById(this.columnsListId);
        if (!liste) return;
        const visibles = this.state.colonnes.filter(col => !this.state.masquees.has(col));
        liste.innerHTML = this.state.colonnes.map(col => {
            const affichee = !this.state.masquees.has(col);
            // La dernière colonne visible ne se décoche pas : un tableau sans
            // colonne n'apprend rien.
            const verrouillee = affichee && visibles.length === 1;
            return `
                <label class="selecteur-de-colonnes__ligne">
                    <input type="checkbox" data-colonne="${Utils.escapeHtml(col)}"
                           ${affichee ? 'checked' : ''} ${verrouillee ? 'disabled' : ''}>
                    <span>${Utils.escapeHtml(col)}</span>
                </label>
            `;
        }).join('');

        liste.querySelectorAll('input[data-colonne]').forEach(case_ => {
            case_.addEventListener('change', () => {
                const col = case_.dataset.colonne;
                if (case_.checked) {
                    this.state.masquees.delete(col);
                } else {
                    this.state.masquees.add(col);
                }
                this.retenirLesReglages();
                this.rendreLeSelecteur();
                this.load();
            });
        });
        this.majCompteDeColonnes();
    }

    majCompteDeColonnes() {
        const compte = document.getElementById(this.columnsCountId);
        if (!compte) return;
        const masquees = this.state.colonnes.filter(col => this.state.masquees.has(col)).length;
        compte.hidden = masquees === 0;
        compte.textContent = masquees === 0 ? '' : `(${Utils.formatNumber(masquees)})`;
    }

    /**
     * Applique une largeur à une colonne, en direct.
     *
     * L'en-tête est reconstruit à chaque chargement ; pendant un glissement il
     * ne l'est pas, et les cellules doivent suivre le pointeur. Le rang de la
     * colonne suffit à les désigner : l'en-tête et le corps sont écrits dans
     * le même ordre, à partir de la même liste.
     */
    appliquerLaLargeur(rang, largeur) {
        const thead = document.getElementById(this.theadId);
        const tbody = document.getElementById(this.tbodyId);
        [thead, tbody].forEach(zone => {
            if (!zone) return;
            zone.querySelectorAll(`tr > *:nth-child(${rang + 1})`).forEach(cellule => {
                cellule.style.width = `${largeur}px`;
                cellule.style.maxWidth = `${largeur}px`;
            });
        });
    }

    /**
     * Règle la largeur d'une colonne et la retient.
     */
    reglerLaLargeur(col, rang, largeur) {
        const bornee = Math.max(DataTable.LARGEUR_MINIMALE, Math.round(largeur));
        this.state.largeurs[col] = bornee;
        this.appliquerLaLargeur(rang, bornee);
        this.retenirLesReglages();
    }

    /**
     * Rend une colonne réglable, à la souris et au clavier.
     *
     * Le glissement s'écoute sur le **document**, pas sur la poignée : celle-ci
     * fait une douzaine de pixels de large, et le pointeur en sort au premier
     * mouvement. Écouter la poignée seule donnait une colonne qui ne bougeait
     * pas, ou pire, qui restait collée au curseur parce qu'on avait relâché
     * ailleurs.
     */
    armerLaPoignee(poignee, col, rang) {
        // Le clic sur l'en-tête trie : sans cet arrêt, chaque glissement
        // déclencherait un tri et rechargerait le tableau qu'on est en train
        // de régler.
        ['click', 'pointerdown'].forEach(nom =>
            poignee.addEventListener(nom, evenement => evenement.stopPropagation()));

        poignee.addEventListener('pointerdown', (evenement) => {
            const cellule = poignee.closest('th');
            const depart = evenement.clientX;
            const largeurInitiale = cellule.offsetWidth;
            poignee.setAttribute('data-en-cours', '');
            document.body.classList.add('redimensionnement-en-cours');

            const glisser = (mouvement) => this.reglerLaLargeur(
                col, rang, largeurInitiale + (mouvement.clientX - depart));
            const relacher = () => {
                document.removeEventListener('pointermove', glisser);
                document.removeEventListener('pointerup', relacher);
                document.removeEventListener('pointercancel', relacher);
                poignee.removeAttribute('data-en-cours');
                document.body.classList.remove('redimensionnement-en-cours');
            };
            document.addEventListener('pointermove', glisser);
            document.addEventListener('pointerup', relacher);
            document.addEventListener('pointercancel', relacher);
            evenement.preventDefault();
        });

        poignee.addEventListener('keydown', (evenement) => {
            const sens = {ArrowLeft: -1, ArrowRight: 1}[evenement.key];
            if (!sens) return;
            evenement.preventDefault();
            evenement.stopPropagation();
            const cellule = poignee.closest('th');
            this.reglerLaLargeur(
                col, rang, cellule.offsetWidth + sens * DataTable.PAS_DE_LARGEUR);
        });
    }
}

// Initialize global instances
/**
 * Demande de confirmation.
 *
 * L'application utilisait `confirm()` du navigateur. Cette boîte n'est pas
 * traduisible — le navigateur écrit lui-même les deux boutons, dans sa propre
 * langue —, elle ignore le thème, et elle bloque le fil d'exécution de la
 * page. Sur un produit dont toutes les chaînes passent par i18n, elle était le
 * seul endroit où l'utilisateur lisait autre chose que sa langue choisie.
 *
 * Elle rend une promesse : `await Confirm.demander(...)` remplace `confirm()`
 * ligne pour ligne.
 */
const Confirm = {
    /**
     * @param {{titre: string, message: string, details?: string[],
     *          confirmer?: string, annuler?: string, danger?: boolean,
     *          saisie?: {label: string, placeholder?: string}}} options
     * @returns {Promise<boolean|string>} `false` si l'utilisateur renonce ;
     *   `true` sinon, ou le texte saisi quand `saisie` est demandée.
     *
     *   Avec `saisie`, la confirmation reste **fermée tant que le champ est
     *   vide** : une décision de gouvernance sans motif est précisément ce
     *   qu'une piste d'audit existe pour empêcher. L'ambiguïté entre « annulé »
     *   et « confirmé sans rien écrire » disparaît du même coup.
     */
    demander(options) {
        return new Promise(resoudre => {
            const fond = document.createElement('div');
            fond.className = 'confirm-fond';
            fond.setAttribute('role', 'dialog');
            fond.setAttribute('aria-modal', 'true');
            // Le titre nomme la boîte : sans lui, elle s'annonce
            // « dialogue » et il faut la lire pour savoir ce qu'elle demande.
            const ancreDuTitre = Utils.generateId('confirm-titre');
            fond.setAttribute('aria-labelledby', ancreDuTitre);

            const details = (options.details || []).length
                ? `<ul class="confirm-details">${options.details
                       .map(d => `<li>${Utils.escapeHtml(d)}</li>`).join('')}</ul>`
                : '';

            const saisie = options.saisie
                ? `<label class="form-label" for="confirm-saisie">${
                       Utils.escapeHtml(options.saisie.label)}</label>
                   <input type="text" id="confirm-saisie" class="form-input"
                          placeholder="${Utils.escapeHtml(
                              options.saisie.placeholder || '')}">`
                : '';

            fond.innerHTML = `
                <div class="confirm-boite${options.danger ? ' confirm-boite--danger' : ''}">
                    <h2 class="confirm-titre" id="${ancreDuTitre}">${Utils.escapeHtml(options.titre)}</h2>
                    <p class="confirm-message">${Utils.escapeHtml(options.message)}</p>
                    ${details}
                    ${saisie}
                    <div class="confirm-actions">
                        <button class="btn btn-secondary" data-confirm="non">${
                            Utils.escapeHtml(options.annuler || I18n.t('common.cancel'))}</button>
                        <button class="btn ${options.danger ? 'btn-danger' : 'btn-primary'}"
                                data-confirm="oui"${options.saisie ? ' disabled' : ''}>${
                            Utils.escapeHtml(options.confirmer || I18n.t('common.confirm'))}</button>
                    </div>
                </div>`;

            const champ = () => fond.querySelector('#confirm-saisie');
            const valider = () => fond.querySelector('[data-confirm="oui"]');

            //: Élément qui a demandé la confirmation. Le focus lui revient
            //: quand la boîte se referme.
            const declencheur = document.activeElement;

            const fermer = (reponse) => {
                document.removeEventListener('keydown', auClavier);
                const texte = champ() ? champ().value.trim() : '';
                fond.remove();
                const application = document.getElementById('app');
                if (application) {
                    application.inert = false;
                }
                if (declencheur && declencheur.isConnected) {
                    declencheur.focus();
                }
                resoudre(reponse && options.saisie ? texte : reponse);
            };

            // Échap annule, Entrée confirme : ce que fait la boîte native, et
            // ce que l'utilisateur a dans les doigts.
            const auClavier = (evenement) => {
                if (evenement.key === 'Escape') fermer(false);
                if (evenement.key === 'Enter' && !valider().disabled) fermer(true);
                if (evenement.key === 'Tab') retenir(evenement);
            };

            // La tabulation reste dans la boîte : elle ne compte que deux ou
            // trois commandes, et en sortir mène derrière un voile.
            const retenir = (evenement) => {
                const atteignables = [...fond.querySelectorAll(
                    ModalManager.SELECTEUR_FOCUSABLE)];
                if (!atteignables.length) return;
                const premier = atteignables[0];
                const dernier = atteignables[atteignables.length - 1];
                const courant = document.activeElement;
                if (evenement.shiftKey && (courant === premier || !fond.contains(courant))) {
                    evenement.preventDefault();
                    dernier.focus();
                } else if (!evenement.shiftKey && courant === dernier) {
                    evenement.preventDefault();
                    premier.focus();
                }
            };

            fond.addEventListener('click', evenement => {
                const bouton = evenement.target.closest('[data-confirm]');
                if (bouton) return fermer(bouton.dataset.confirm === 'oui');
                if (evenement.target === fond) fermer(false);
            });
            document.addEventListener('keydown', auClavier);
            if (options.saisie) {
                fond.addEventListener('input', () => {
                    valider().disabled = champ().value.trim() === '';
                });
            }

            // Le reste de la page cesse d'exister pour le clavier tant que
            // la question est posée.
            const application = document.getElementById('app');
            if (application) {
                application.inert = true;
            }
            document.body.appendChild(fond);
            // Le champ prend le focus quand il y en a un — c'est là que
            // l'utilisateur doit aller. Sinon c'est l'annulation : une action
            // destructrice ne doit pas se déclencher sur une frappe distraite.
            (champ() || fond.querySelector('[data-confirm="non"]')).focus();
        });
    },
};

window.Confirm = Confirm;

window.Toast = new ToastManager();
window.Modal = new ModalManager();

// ===================================================================
// SPRINT 2 : DRILL-DOWN HABILITATIONS
// ===================================================================

/**
 * Rendu des tableaux avec accès au détail.
 *
 * Ces méthodes complètent `DataTable`. Il en existait deux versions : celle
 * de la classe et celle-ci, qui écrasait la première au chargement du script.
 * La version morte est supprimée — deux rendus à maintenir dont un seul
 * s'exécute est un piège pour la prochaine correction.
 */
Object.assign(DataTable.prototype, {
    /**
     * Détermine si une colonne est cliquable (drill-down)
     */
    isClickableColumn(col) {
        if (!this.detail) return false;
        const clickableColumns = [
            'ID_utilisateur',
            'ID_application', 
            'ID_droit'
        ];
        return clickableColumns.includes(col);
    },

    /**
     * La colonne de cases à cocher, quand le tableau porte une sélection.
     *
     * Elle est écrite ici et non dans l'appelant : un deuxième rendu de
     * tableau serait un deuxième endroit à corriger, et le fichier en a déjà
     * connu un — mort, mais qui écrasait l'autre au chargement.
     */
    enteteDeSelection() {
        if (!this.selection) return '';
        // L'en-tête de la colonne de sélection avait l'air d'un bouton — il en
        // avait le curseur et le survol — sans rien faire. Il porte désormais
        // la case « tout cocher » quand la sélection sait le faire, et
        // seulement le nom de la colonne sinon.
        const tout = this.peutToutSelectionner()
            ? `<input type="checkbox" data-selection-tout aria-label="${
                Utils.escapeHtml(I18n.t('table.selection.all'))}" title="${
                Utils.escapeHtml(I18n.t('table.selection.all'))}">`
            : '';
        return `<th scope="col" class="colonne-selection">
                    ${tout}
                    <span class="sr-only">${Utils.escapeHtml(
                        I18n.t('table.selection.column'))}</span>
                </th>`;
    },

    /**
     * L'en-tête : une colonne par colonne du fichier, plus la sélection.
     *
     * Extrait du rendu parce qu'une page vide doit pouvoir le réafficher sans
     * corps — et parce qu'un en-tête écrit à deux endroits finirait par
     * diverger de son corps.
     */
    renderHeader(thead, columns) {
        if (!thead) return;
        thead.innerHTML = `
            <tr>
                ${this.enteteDeSelection()}
                ${columns.map(col => {
                    const isSorted = this.state.sortCol === col;
                    const sortIcon = isSorted
                        ? (this.state.sortDesc ? 'fa-sort-down' : 'fa-sort-up')
                        : 'fa-sort';
                    return `
                        <th scope="col" class="${isSorted ? 'sorted' : ''}" data-column="${Utils.escapeHtml(col)}"${this.styleDeColonne(col)}>
                            ${Utils.escapeHtml(col)}
                            <i class="fas ${sortIcon} sort-icon" aria-hidden="true"></i>
                            <button type="button" class="poignee-de-colonne"
                                    data-poignee="${Utils.escapeHtml(col)}"
                                    aria-label="${Utils.escapeHtml(I18n.t('table.column.resize', {colonne: col}))}"></button>
                        </th>
                    `;
                }).join('')}
            </tr>
        `;

        this.majCaseTout();

        thead.querySelectorAll('th[data-column]').forEach((th, rang) => {
            th.addEventListener('click', () => {
                const col = th.dataset.column;
                if (this.state.sortCol === col) {
                    this.state.sortDesc = !this.state.sortDesc;
                } else {
                    this.state.sortCol = col;
                    this.state.sortDesc = false;
                }
                this.load();
            });
            const poignee = th.querySelector('.poignee-de-colonne');
            if (poignee) this.armerLaPoignee(poignee, columns[rang], rang);
        });
    },

    celluleDeSelection(row) {
        if (!this.selection) return '';
        const identifiant = String(row[this.state.colonneIdentifiant] ?? '');
        const cochee = this.selection.contient(identifiant);
        // Le marqueur accompagne la case parce qu'il qualifie la ligne, pas
        // une de ses colonnes : les colonnes viennent du fichier du client, et
        // le produit n'a rien à y ajouter.
        const marqueur = this.selection.marqueur
            ? this.selection.marqueur(identifiant) : '';
        return `<td class="colonne-selection">
                    <input type="checkbox" data-selection="${
                        Utils.escapeHtml(identifiant)}" ${cochee ? 'checked' : ''}
                           aria-label="${Utils.escapeHtml(
                               I18n.t('table.selection.row', {ligne: identifiant}))}">
                    ${marqueur}
                </td>`;
    },
    
    /**
     * Rend l'en-tête, le corps et les accès au détail.
     */
    renderTable(thead, tbody, data) {
        if (!data || data.length === 0) {
            // Les en-têtes survivent à une page vide quand le serveur a dit
            // quelles colonnes existent : sans elles, l'utilisateur qui ne
            // trouve rien ne sait plus sur quoi il cherchait.
            if (this.state.colonnesServeur) {
                this.renderHeader(thead, this.colonnesVisibles(
                    this.state.colonnesServeur));
            } else {
                thead.innerHTML = '';
            }
            tbody.innerHTML = `
                <tr>
                    <td colspan="10" class="table-loading">
                        <span>${Utils.escapeHtml(this.state.search
                            ? I18n.t('table.no_result_for_search')
                            : I18n.t(this.messageVide))}</span>
                    </td>
                </tr>
            `;
            return;
        }

        // Les colonnes viennent du fichier du client : elles sont relevées à
        // chaque rendu, parce qu'un changement d'espace de travail peut les
        // changer entièrement.
        this.state.colonnes = this.state.colonnesServeur || Object.keys(data[0]);
        const columns = this.colonnesVisibles(this.state.colonnes);
        this.majCompteDeColonnes();
        this.renderHeader(thead, columns);
        // Corps du tableau, avec accès au détail.
        //
        // Les valeurs viennent des fichiers du client : elles peuvent contenir
        // n'importe quoi. La version précédente les insérait dans un attribut
        // `onclick`, échappées en HTML — ce qui ne protège pas un contexte
        // JavaScript. Le navigateur décode les entités **avant** d'analyser le
        // code : un identifiant contenant `'); ... ('` sortait de la chaîne et
        // s'exécutait. Un attribut de données ne peut pas faire ça, parce que
        // rien n'y est jamais interprété comme du code.
        //
        // La valeur est écrite **entière**. Elle était coupée à cinquante
        // caractères par le script, et la coupe était donc définitive :
        // élargir la colonne ne révélait rien de plus, puisque le reste
        // n'était jamais arrivé dans la page. C'est la feuille de style qui
        // tronque désormais, à la largeur de la colonne — celle que
        // l'utilisateur règle.
        tbody.innerHTML = data.map(row => `
            <tr>
                ${this.celluleDeSelection(row)}
                ${columns.map(col => {
                    const value = String(row[col] || '');
                    const isClickable = this.isClickableColumn(col);

                    return `
                        <td class="${isClickable ? 'clickable-cell' : ''}"
                            ${isClickable ? `data-drilldown-col="${Utils.escapeHtml(col)}" data-drilldown-value="${Utils.escapeHtml(value)}"` : ''}
                            title="${Utils.escapeHtml(value)}"${this.styleDeColonne(col)}>
                            ${isClickable ? '<i class="fas fa-search clickable-icon" aria-hidden="true"></i>' : ''}
                            ${this.marqueDePrivilege(col, value)}${Utils.escapeHtml(value)}
                        </td>
                    `;
                }).join('')}
            </tr>
        `).join('');
    },

    /**
     * La marque d'un compte à privilèges, sur la cellule qui le nomme.
     *
     * Elle ne se pose que sur la **colonne d'identifiant**, et seulement quand
     * le serveur a dit laquelle : la poser sur toute cellule dont la valeur
     * figure dans la liste marquerait une colonne du client qui porterait par
     * hasard la même chaîne.
     *
     * Le titre porte la phrase ; l'icône est décorative. Un lecteur d'écran ne
     * doit pas lire une balance et deviner, et un pictogramme seul n'est pas
     * une information — c'est le même défaut que la couleur employée seule.
     */
    marqueDePrivilege(col, valeur) {
        if (!this.state.colonneIdentifiant || col !== this.state.colonneIdentifiant) {
            return '';
        }
        if (!this.state.aPrivileges || !this.state.aPrivileges.has(valeur)) {
            return '';
        }
        const phrase = I18n.t('privileges.compte_marque');
        return `<span class="table-privilege" title="${Utils.escapeHtml(phrase)}">`
            + '<i class="fas fa-user-shield" aria-hidden="true"></i>'
            + `<span class="sr-only">${Utils.escapeHtml(phrase)}</span></span> `;
    }
});

// Délégation pour l'accès au détail : posée une fois, elle survit à chaque
// reconstruction du tableau.
document.addEventListener('click', (evenement) => {
    const cellule = evenement.target.closest('[data-drilldown-col]');
    if (!cellule || typeof HabilitationsModal === 'undefined') return;
    HabilitationsModal.show(cellule.dataset.drilldownCol,
                            cellule.dataset.drilldownValue);
});

/**
 * Modale de détail d'une habilitation.
 *
 * Elle affichait quatre colonnes fixes — Nom, Description, Département, Date
 * d'attribution — que le produit ne peut pas imposer : les colonnes des
 * fichiers ne sont pas connues à l'avance. Sur un référentiel qui ne les porte
 * pas, la modale montrait quatre colonnes vides, et rien ne distinguait « le
 * client n'a pas renseigné ce champ » de « ce champ n'existe pas chez lui ».
 *
 * Les colonnes viennent désormais du serveur, qui transmet celles du fichier.
 * Aucun libellé de données n'est traduit : ce sont les mots du client. Seuls
 * les libellés du produit passent par i18n.
 */
const HabilitationsModal = {
    /** Vue courante, conservée pour la pagination. */
    etat: null,

    VUES: {
        'ID_utilisateur': {
            chemin: 'user', titre: 'habilitations.title_user',
            liste: 'habilitations', orphelin: 'habilitations.orphan_right',
        },
        'ID_application': {
            chemin: 'application', titre: 'habilitations.title_application',
            liste: 'rights', orphelin: null,
        },
        'ID_droit': {
            chemin: 'right', titre: 'habilitations.title_right',
            liste: 'holders', orphelin: 'habilitations.orphan_user',
        },
    },

    async show(colonne, valeur) {
        const vue = HabilitationsModal.VUES[colonne];
        if (!vue) return;

        const contenu = document.getElementById('habilitations-modal-content');
        const titre = document.getElementById('habilitations-modal-title');
        if (!contenu) return;

        if (titre) titre.textContent = `${I18n.t(vue.titre)} : ${valeur}`;
        contenu.innerHTML = `<div class="habilitations-chargement">
                <i class="fas fa-circle-notch fa-spin" aria-hidden="true"></i>
                <span>${Utils.escapeHtml(I18n.t('common.loading'))}</span>
            </div>`;
        Modal.open('habilitations-modal');

        HabilitationsModal.etat = { vue, valeur, elements: [], donnees: null };
        // Le panneau des constats ne concerne qu'une identité : ouvert sur un
        // droit ou une application, il montrerait la personne précédente.
        const panneau = typeof ConstatsIdentite === 'undefined' ? null : ConstatsIdentite;
        if (panneau && vue.chemin === 'user') panneau.afficher(valeur);
        else if (panneau) panneau.masquer();
        await HabilitationsModal.charger(0);
    },

    async charger(offset) {
        const etat = HabilitationsModal.etat;
        const contenu = document.getElementById('habilitations-modal-content');
        if (!etat || !contenu) return;

        try {
            const donnees = await API.get(
                `/habilitations/${etat.vue.chemin}/${encodeURIComponent(etat.valeur)}`,
                { offset, limit: 50 });
            etat.donnees = donnees;
            etat.elements = offset === 0
                ? donnees[etat.vue.liste]
                : [...etat.elements, ...donnees[etat.vue.liste]];
            HabilitationsModal.render(contenu);
        } catch (erreur) {
            contenu.innerHTML = `<div class="alert alert-danger">
                    <i class="fas fa-triangle-exclamation" aria-hidden="true"></i>
                    <span>${Utils.escapeHtml(erreur.message)}</span>
                </div>`;
        }
    },

    /** Indicateurs de tête, propres à chaque vue. */
    indicateurs(donnees) {
        const cartes = [];
        const ajouter = (cle, valeur) => {
            if (valeur === undefined || valeur === null) return;
            cartes.push(`<div class="habilitations-indicateur">
                    <span class="habilitations-indicateur__label">${
                        Utils.escapeHtml(I18n.t(cle))}</span>
                    <span class="habilitations-indicateur__valeur">${
                        Utils.escapeHtml(String(valeur))}</span>
                </div>`);
        };

        ajouter('habilitations.total', donnees.total_habilitations);
        ajouter('habilitations.users', donnees.total_users);
        ajouter('habilitations.rights_declared', donnees.total_rights);
        ajouter('habilitations.rights_held', donnees.rights_with_holders);
        ajouter('habilitations.holders', donnees.total_holders);

        return cartes.length
            ? `<div class="habilitations-indicateurs">${cartes.join('')}</div>`
            : '';
    },

    /**
     * En-têtes du tableau : l'identifiant, puis les colonnes du fichier.
     *
     * Les noms de colonnes ne sont pas traduits — ce sont ceux du référentiel
     * du client. Les traduire reviendrait à afficher autre chose que ce que
     * son fichier contient.
     */
    entetes(donnees, vue) {
        const colonnes = donnees.columns || [];
        const identifiant = vue.chemin === 'right'
            ? 'ID_utilisateur'
            : (vue.chemin === 'user' ? 'ID_droit' : 'ID_droit');

        const supplementaires = vue.chemin === 'application'
            ? [`<th scope="col">${Utils.escapeHtml(I18n.t('habilitations.user_count'))}</th>`]
            : [];

        return `<th scope="col">${Utils.escapeHtml(identifiant)}</th>`
             + supplementaires.join('')
             + colonnes.map(c => `<th scope="col">${Utils.escapeHtml(c)}</th>`).join('');
    },

    ligne(element, donnees, vue) {
        const cellules = (element.attributes || []).map(attribut => {
            const renseigne = attribut.value !== null && attribut.value !== undefined
                && String(attribut.value).length > 0;
            return `<td class="${renseigne ? '' : 'habilitations-vide'}">${
                renseigne ? Utils.escapeHtml(String(attribut.value))
                          : Utils.escapeHtml(I18n.t('common.not_provided'))}</td>`;
        }).join('');

        const marque = element.orphan && vue.orphelin
            ? ` <span class="habilitations-orphelin"
                       title="${Utils.escapeHtml(I18n.t(vue.orphelin))}">
                    <i class="fas fa-triangle-exclamation" aria-hidden="true"></i>
                </span>`
            : '';

        const compte = vue.chemin === 'application'
            ? `<td>${Number(element.user_count || 0)}</td>`
            : '';

        return `<tr><td>${Utils.escapeHtml(String(element.id ?? ''))}${marque}</td>${compte}${cellules}</tr>`;
    },

    render(contenu) {
        const { vue, donnees, elements } = HabilitationsModal.etat;
        const page = donnees.page || {};

        const suite = page.has_more
            ? `<button class="btn btn-secondary btn-sm" id="habilitations-suite">
                   ${Utils.escapeHtml(I18n.t('habilitations.load_more'))}</button>`
            : '';

        contenu.innerHTML = `
            ${HabilitationsModal.indicateurs(donnees)}
            <div class="habilitations-tableau">
                <table class="data-table">
                    <thead><tr>${HabilitationsModal.entetes(donnees, vue)}</tr></thead>
                    <tbody>${elements.map(
                        e => HabilitationsModal.ligne(e, donnees, vue)).join('')}</tbody>
                </table>
            </div>
            <footer class="habilitations-pied">
                <span>${Utils.escapeHtml(I18n.t('habilitations.shown_of_total', {
                    shown: elements.length, total: page.total ?? elements.length }))}</span>
                ${suite}
            </footer>`;

        const bouton = document.getElementById('habilitations-suite');
        if (bouton) {
            bouton.addEventListener('click',
                () => HabilitationsModal.charger(elements.length));
        }
    },
};

window.HabilitationsModal = HabilitationsModal;

/**
 * Définitions au survol.
 *
 * Les tuiles d'indicateurs portent le vocabulaire du role mining —
 * compression, redondance, sur-octroi, complexité du modèle. Leur survol
 * s'allumait déjà, ce qui promet une interaction, et ne livrait rien. Un
 * analyste qui ne sait pas ce que « compression 2,33 » veut dire ne peut pas
 * s'en servir pour décider, et c'est pourtant sur ces chiffres qu'un comité de
 * gouvernance tranche.
 *
 * Trois partis pris :
 *
 * - **déclaratif** : un élément porte `data-definition="<clé>"`, rien d'autre.
 *   Le texte vient du catalogue, donc il suit la langue comme le reste ;
 * - **délégué** : un seul jeu d'écouteurs sur le document. Les cartes de rôle
 *   sont écrites après coup par le JavaScript, et un écouteur posé au
 *   démarrage ne les aurait jamais vues ;
 * - **atteignable au clavier** : la définition s'ouvre aussi à la tabulation
 *   et se ferme par Échap. Une information qui n'existe qu'au survol n'existe
 *   pas pour qui n'a pas de souris.
 */
const Definitions = {
    //: Délai avant affichage. Sans lui, traverser une rangée de tuiles fait
    //  clignoter quatre bulles.
    DELAI_MS: 350,

    bulle: null,
    declencheur: null,
    minuteur: null,
    compteur: 0,

    init() {
        if (this.bulle) return;

        this.bulle = document.createElement('div');
        this.bulle.className = 'definition-bulle';
        this.bulle.setAttribute('role', 'tooltip');
        this.bulle.hidden = true;
        document.body.appendChild(this.bulle);

        document.addEventListener('mouseover', (evenement) => {
            const cible = evenement.target.closest?.('[data-definition]');
            if (cible) this.programmer(cible);
        });
        document.addEventListener('mouseout', (evenement) => {
            const cible = evenement.target.closest?.('[data-definition]');
            if (cible && cible === this.declencheur) this.masquer();
            else if (cible) this.annuler();
        });

        // La tabulation ouvre sans délai : l'intention y est explicite.
        document.addEventListener('focusin', (evenement) => {
            const cible = evenement.target.closest?.('[data-definition]');
            if (cible) this.afficher(cible);
        });
        document.addEventListener('focusout', (evenement) => {
            if (evenement.target.closest?.('[data-definition]')) this.masquer();
        });

        document.addEventListener('keydown', (evenement) => {
            if (evenement.key === 'Escape') this.masquer();
        });

        // La bulle suit sa tuile plutôt que de disparaître. Elle se fermait au
        // moindre défilement — et atteindre une tuile à la tabulation la fait
        // justement défiler dans la vue : la définition s'ouvrait puis se
        // refermait dans le même geste, donc n'existait pas au clavier.
        window.addEventListener('scroll', () => this.suivre(), true);
        window.addEventListener('resize', () => this.suivre());
    },

    /**
     * Rend une tuile atteignable au clavier et annonce qu'elle porte une
     * définition. Appelé après chaque rendu : les cartes de rôle et les
     * bandeaux d'indicateurs sont réécrits à chaque analyse.
     */
    preparer(racine = document) {
        racine.querySelectorAll('[data-definition]').forEach(element => {
            if (!element.hasAttribute('tabindex')) element.tabIndex = 0;
        });
    },

    programmer(element) {
        this.annuler();
        this.minuteur = setTimeout(() => this.afficher(element), this.DELAI_MS);
    },

    annuler() {
        if (this.minuteur) {
            clearTimeout(this.minuteur);
            this.minuteur = null;
        }
    },

    /**
     * Replace la bulle sous sa tuile, ou la ferme si la tuile a quitté l'écran.
     */
    suivre() {
        if (!this.declencheur || this.bulle.hidden) return;
        const cadre = this.declencheur.getBoundingClientRect();
        const dehors = cadre.bottom < 0 || cadre.top > window.innerHeight;
        if (dehors) this.masquer();
        else this.positionner(this.declencheur);
    },

    afficher(element) {
        this.annuler();
        const cle = element.getAttribute('data-definition');
        const texte = I18n.t(cle);
        // Une clé sans traduction rend la clé elle-même : afficher
        // « definition.stats.wsc » à un analyste ne l'avance à rien.
        if (!texte || texte === cle) return;

        this.declencheur = element;
        this.bulle.textContent = texte;
        this.bulle.hidden = false;

        if (!this.bulle.id) this.bulle.id = `definition-${++this.compteur}`;
        element.setAttribute('aria-describedby', this.bulle.id);

        this.positionner(element);
    },

    positionner(element) {
        const cadre = element.getBoundingClientRect();
        const bulle = this.bulle.getBoundingClientRect();
        const marge = 8;

        let gauche = cadre.left + (cadre.width - bulle.width) / 2;
        gauche = Math.max(marge, Math.min(gauche, window.innerWidth - bulle.width - marge));

        // Sous la tuile par défaut ; au-dessus quand le bas de la fenêtre est
        // trop proche, sans quoi la bulle sort de l'écran.
        const dessous = cadre.bottom + marge;
        const place = dessous + bulle.height <= window.innerHeight - marge;
        const haut = place ? dessous : cadre.top - bulle.height - marge;

        this.bulle.style.left = `${Math.round(gauche)}px`;
        this.bulle.style.top = `${Math.round(Math.max(marge, haut))}px`;
        this.bulle.classList.toggle('definition-bulle--dessus', !place);
    },

    masquer() {
        this.annuler();
        if (!this.bulle || this.bulle.hidden) return;
        this.bulle.hidden = true;
        if (this.declencheur) {
            this.declencheur.removeAttribute('aria-describedby');
            this.declencheur = null;
        }
    },
};

window.Definitions = Definitions;
