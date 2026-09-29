/**
 * PyGIA Frontend - Application Principale
 * Point d'entrée avec gestion de l'authentification.
 */

const App = {
    currentPage: 'dashboard',
    isInitialized: false,

    /**
     * Initialise l'application.
     */
    async init() {
        
        // 1. Initialiser l'authentification
        Auth.init();

        // 2. Charger le catalogue de traductions, avant l'authentification.
        //
        // La page de connexion est la première vue du produit et c'était la
        // seule à rester en français quelle que soit la langue choisie : le
        // catalogue n'était chargé qu'une fois l'utilisateur entré. Le
        // catalogue ne contient que des libellés d'interface, aucune donnée
        // client — c'est ce qui permet de le lire sans être authentifié.
        await this.chargerTraductions();

        // 3. Vérifier si l'utilisateur est connecté
        if (!Auth.isAuthenticated()) {
            this.hideLoader();
            LoginPage.show();
            return;
        }
        
        // 4. Vérifier la validité du token
        const tokenValid = await Auth.verifyToken();
        if (!tokenValid) {
            Auth.logout();
            return;
        }
        
        // 5. Initialiser l'application complète
        await this.initializeApp();
    },

    /**
     * Charge le catalogue de traductions sans interrompre le démarrage.
     *
     * Sans catalogue, l'interface affiche les clés brutes : c'est laid, mais
     * lisible et diagnostiquable. Refuser de démarrer le serait moins.
     */
    async chargerTraductions() {
        try {
            await I18n.init();
        } catch (error) {
            Toast.error(I18n.t('i18n.catalogue_unavailable'), error.message);
        }
    },

    /**
     * Initialise l'application après authentification.
     */
    async initializeApp() {
        // Afficher les infos utilisateur
        this.displayUserInfo();
        
        // Thème
        this.initTheme();

        // Zones défilantes : ce qui déborde doit rester atteignable au
        // clavier. Le module s'installe avant la navigation, pour que le
        // premier écran affiché soit déjà pris en compte.
        RegionsDefilantes.init(document.body);

        // Navigation
        this.initNavigation();

        // Modules de pages
        // Les définitions du vocabulaire suivent le survol et la
        // tabulation. Un seul jeu d'écouteurs sur le document : les cartes de
        // rôle sont écrites après coup, et un écouteur posé sur elles au
        // démarrage ne les aurait jamais vues.
        if (typeof Definitions !== 'undefined') {
            Definitions.init();
            Definitions.preparer();
        }

        if (typeof ExplorerPage !== 'undefined') ExplorerPage.init();
        if (typeof MiningPage !== 'undefined') MiningPage.init();
        if (typeof RolesPage !== 'undefined') RolesPage.init();
        if (typeof QualityPage !== 'undefined') QualityPage.init();
        if (typeof AuditPage !== 'undefined') AuditPage.init();
        if (typeof DocumentationPage !== 'undefined') DocumentationPage.init();
        if (typeof SettingsPage !== 'undefined') SettingsPage.init();
        
        // Gestion des droits socles
        // L'assistant ne vit dans aucune page : il se monte une fois, et il
        // suit l'utilisateur d'un écran à l'autre.
        if (typeof AgentPanneau !== 'undefined') {
            AgentPanneau.init();
        }

        if (typeof BirthRightsManager !== 'undefined') {
            BirthRightsManager.init();
        }
        
        // Workspace Manager
        //
        // `init` rattrape ses propres pannes et bascule le sélecteur en état
        // « aucun workspace ». L'entourer d'un second `try/catch` était du
        // code que rien ne pouvait atteindre, et qui laissait croire que le
        // démarrage traitait un cas déjà traité ailleurs.
        if (typeof WorkspaceManager !== 'undefined') {
            await WorkspaceManager.init();
        }
        
        // Travail en attente. Après le workspace : le compte porte sur les
        // candidats du workspace actif, et le lire avant n'aurait décrit
        // aucun.
        if (typeof Cloche !== 'undefined') Cloche.init();

        // Données initiales
        await this.loadInitialData();

        // Navigation par hash
        this.handleHashChange();
        window.addEventListener('hashchange', () => this.handleHashChange());

        // Changement de langue : ce que le JavaScript a déjà écrit dans la
        // page ne porte aucune clé de traduction, donc `applyTranslations`
        // ne le voit pas. Sans ce rafraîchissement, changer de langue
        // laissait en français tout ce qui avait déjà été rendu — bandeaux
        // du mining, cartes de rôles, colonnes du graphe — jusqu'au
        // rechargement de la page.
        window.addEventListener('localeChanged', () => this.rafraichirLangue());

        // Actions rapides et autres
        this.initQuickActions();
        this.initGlobalSearch();
        this.initRefreshButton();
        this.initLogoutButton();

        // Cacher le loader
        this.hideLoader();
        
        this.isInitialized = true;
    },

    /**
     * Affiche les informations de l'utilisateur connecté.
     */
    displayUserInfo() {
        const user = Auth.getUser();
        if (!user) return;
        
        const sidebarFooter = document.querySelector('.sidebar-footer');
        if (sidebarFooter) {
            let userInfo = sidebarFooter.querySelector('.user-info');
            if (!userInfo) {
                userInfo = document.createElement('div');
                userInfo.className = 'user-info';
                sidebarFooter.insertBefore(userInfo, sidebarFooter.firstChild);
            }

            // La couleur du rôle vient du thème. Elle était une carte
            // d'hexadécimaux écrite ici, avec une teinte de repli qui
            // n'existait nulle part ailleurs dans le produit.
            const rolesConnus = ['admin', 'analyst', 'viewer'];
            const teinte = rolesConnus.includes(user.role)
                ? ` user-info__pastille--${user.role}`
                : '';

            userInfo.innerHTML = `
                <div class="user-info__ligne">
                    <div class="user-info__pastille${teinte}">
                        ${Utils.escapeHtml(user.username.charAt(0).toUpperCase())}
                    </div>
                    <div class="user-info__textes">
                        <div class="user-info__nom">
                            ${Utils.escapeHtml(user.full_name || user.username)}
                        </div>
                        <div class="user-info__role">
                            ${Utils.escapeHtml(user.role)}
                        </div>
                    </div>
                </div>
            `;
        }
    },

    /**
     * Ajoute le bouton de déconnexion.
     */
    initLogoutButton() {
        const sidebarFooter = document.querySelector('.sidebar-footer');
        if (!sidebarFooter) return;
        
        if (sidebarFooter.querySelector('.logout-btn')) return;
        
        const logoutBtn = document.createElement('button');
        logoutBtn.className = 'nav-link logout-btn sidebar-logout';
        logoutBtn.innerHTML = '<i class="fas fa-sign-out-alt" aria-hidden="true"></i>'
            + `<span>${I18n.t('confirm.logout_title')}</span>`;
        logoutBtn.addEventListener('click', async () => {
            const confirme = await Confirm.demander({
                titre: I18n.t('confirm.logout_title'),
                message: I18n.t('confirm.logout'),
            });
            if (confirme) Auth.logout();
        });
        
        const versionDiv = sidebarFooter.querySelector('.sidebar-version');
        if (versionDiv) {
            sidebarFooter.insertBefore(logoutBtn, versionDiv);
        } else {
            sidebarFooter.appendChild(logoutBtn);
        }
    },

    async loadInitialData() {
        try {
            await Promise.all([
                typeof DashboardPage !== 'undefined' ? DashboardPage.init() : Promise.resolve(),
                // La configuration seule : les autres écrans y lisent des
                // seuils et des fragments de droits sensibles. Le reste de la
                // page des paramètres se charge quand on l'ouvre.
                typeof SettingsPage !== 'undefined'
                    ? SettingsPage.chargerLaConfiguration() : Promise.resolve()
            ]);
        } catch (error) {
            if (error.status === 401) {
                Auth.logout();
            }
        }
    },

    initTheme() {
        const savedTheme = Utils.storage.get(Config.STORAGE_THEME, 'dark');
        document.documentElement.setAttribute('data-theme', savedTheme);

        const themeToggle = document.getElementById('theme-toggle');
        if (themeToggle) {
            this.updateThemeIcon(savedTheme);
            themeToggle.addEventListener('click', () => this.toggleTheme());
        }
    },

    toggleTheme() {
        const currentTheme = document.documentElement.getAttribute('data-theme');
        const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', newTheme);
        Utils.storage.set(Config.STORAGE_THEME, newTheme);
        this.updateThemeIcon(newTheme);
        // Un thème de workspace porte les deux variantes. Sans ce repeint, la
        // bascule laissait en place les couleurs de l'autre variante : les
        // jetons du thème gagnent contre la feuille de style, donc l'affichage
        // clair restait peint en sombre par endroits.
        ThemeVisuel.peindre();
    },

    updateThemeIcon(theme) {
        const icon = document.querySelector('#theme-toggle i');
        if (icon) {
            icon.className = theme === 'dark' ? 'fas fa-moon' : 'fas fa-sun';
        }
    },

    initNavigation() {
        document.querySelectorAll('.nav-link[data-page]').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                this.navigateTo(link.dataset.page);
            });
        });

        document.querySelectorAll('[data-goto]').forEach(el => {
            el.addEventListener('click', () => this.navigateTo(el.dataset.goto));
        });

        this.initActionsDeleguees();
    },

    /**
     * Actions déclarées par attribut de données, résolues par délégation.
     *
     * Elles remplaçaient des `onclick="Module.methode()"` écrits dans le
     * gabarit. Un gestionnaire en attribut oblige à exposer la méthode en
     * global, s'exécute avant que le module soit prêt, et interdit toute
     * politique de sécurité de contenu stricte — laquelle est la première
     * barrière contre l'injection de script.
     */
    initActionsDeleguees() {
        const actions = {
            'workspace-create-open': () => WorkspaceManager.openCreateModal(),
            'workspace-create-close': () => WorkspaceManager.closeCreateModal(),
        };

        document.addEventListener('click', (evenement) => {
            const porteur = evenement.target.closest('[data-action]');
            if (porteur) {
                const action = actions[porteur.dataset.action];
                if (action) {
                    evenement.preventDefault();
                    action();
                }
                return;
            }

            const onglet = evenement.target.closest('[data-mining-tab]');
            if (onglet && typeof MiningPage !== 'undefined') {
                evenement.preventDefault();
                const [prefixe, nom] = onglet.dataset.miningTab.split(':');
                MiningPage.switchTab(prefixe, nom);
            }
        });
    },

    /**
     * Demande à chaque module de réafficher ce qu'il a déjà rendu.
     *
     * Un module qui garde un état affiché expose `rafraichirLangue()` ; les
     * autres n'ont rien à faire. `I18n.switchLocale` recharge par ailleurs
     * les données de la page courante, ce qui couvre les écrans dont le
     * contenu vient du serveur dans la langue demandée — la documentation,
     * notamment.
     */
    rafraichirLangue() {
        const modules = [
            typeof MiningPage !== 'undefined' ? MiningPage : null,
            typeof RolesPage !== 'undefined' ? RolesPage : null,
            typeof QualityPage !== 'undefined' ? QualityPage : null,
            typeof GraphView !== 'undefined' ? GraphView : null,
            typeof ExportModelePage !== 'undefined' ? ExportModelePage : null,
            typeof SeparationPage !== 'undefined' ? SeparationPage : null,
            typeof MouvementPage !== 'undefined' ? MouvementPage : null,
            typeof UsagePage !== 'undefined' ? UsagePage : null,
            typeof ControlesPage !== 'undefined' ? ControlesPage : null,
            typeof ConstatsIdentite !== 'undefined' ? ConstatsIdentite : null,
            typeof ApprentissagePage !== 'undefined' ? ApprentissagePage : null,
            typeof DashboardPage !== 'undefined' ? DashboardPage : null,
            typeof WorkspacesPage !== 'undefined' ? WorkspacesPage : null,
            typeof WorkspaceManager !== 'undefined' ? WorkspaceManager : null,
            typeof Cloche !== 'undefined' ? Cloche : null,
        ];
        modules
            .filter(module => module && typeof module.rafraichirLangue === 'function')
            .forEach(module => module.rafraichirLangue());
        this.displayUserInfo();
    },

    navigateTo(pageName) {
        if (pageName === this.currentPage) return;
        window.location.hash = pageName;
    },

    handleHashChange() {
        const hash = window.location.hash.slice(1) || 'dashboard';
        this.showPage(hash);
    },
    
    // --- SUPPRESSION DU BLOC ERRONE ICI ---

    showPage(pageName) {
        document.querySelectorAll('.page').forEach(page => page.classList.remove('active'));

        const targetPage = document.getElementById(`page-${pageName}`);
        if (targetPage) {
            targetPage.classList.add('active');
            this.currentPage = pageName;

            document.querySelectorAll('.nav-link').forEach(link => {
                link.classList.remove('active');
                if (link.dataset.page === pageName) link.classList.add('active');
            });

            // `title` est une clé de traduction : le fil d'Ariane restait en
            // français quelle que soit la langue choisie.
            const cle = Config.ROUTES[pageName]?.title;
            const breadcrumb = document.getElementById('current-page-title');
            if (breadcrumb) breadcrumb.textContent = cle ? I18n.t(cle) : pageName;

            this.loadPageData(pageName);
        }
    },

    loadPageData(pageName) {
        switch (pageName) {
            case 'dashboard':
                if (typeof DashboardPage !== 'undefined') DashboardPage.init();
                break;
            case 'users':
                if (typeof ExplorerPage !== 'undefined') ExplorerPage.loadTable('users');
                break;
            case 'applications':
                if (typeof ExplorerPage !== 'undefined') ExplorerPage.loadTable('applications');
                break;
            case 'rights':
                if (typeof ExplorerPage !== 'undefined') ExplorerPage.loadTable('rights');
                break;
            case 'mining':
                // Un mining conservé attend peut-être sur cet écran : l'annoncer
                // est ce qui évite de relancer un calcul de plusieurs minutes
                // pour retrouver un travail déjà fait.
                if (typeof MiningPage !== 'undefined') MiningPage.annoncerRunConserve('APPLICATIF');
                break;
            case 'mining-business':
                if (typeof MiningPage !== 'undefined') {
                    MiningPage.loadBusinessAttributes();
                    MiningPage.annoncerRunConserve('METIER');
                }
                break;
            case 'birth-rights':
                // Le nom du socle vient de la base, pas de la session : on le
                // relit à chaque ouverture, sinon le champ paraîtrait vide
                // pour un socle qui porte déjà un nom.
                if (typeof BirthRightsManager !== 'undefined') {
                    BirthRightsManager.chargerLeSocle();
                }
                break;
            case 'roles-catalog':
                if (typeof RolesPage !== 'undefined') RolesPage.loadCatalog();
                break;
            case 'composer':
                if (typeof RolesPage !== 'undefined') RolesPage.loadComposer();
                break;
            case 'data-quality':
                if (typeof QualityPage !== 'undefined') QualityPage.load();
                break;
            case 'audit':
                if (typeof AuditPage !== 'undefined') AuditPage.load();
                break;
            case 'documentation':
                if (typeof DocumentationPage !== 'undefined') DocumentationPage.load();
                break;
            case 'settings':
                if (typeof SettingsPage !== 'undefined') SettingsPage.loadSettings();
                break;
            case 'workspaces':
                if (typeof WorkspacesPage !== 'undefined') WorkspacesPage.init();
                break;
            case 'graph':
                if (typeof GraphView !== 'undefined') GraphView.init();
                break;
            case 'export-modele':
                if (typeof ExportModelePage !== 'undefined') ExportModelePage.init();
                break;
            case 'separation':
                if (typeof SeparationPage !== 'undefined') SeparationPage.init();
                break;
            case 'separation-conflits':
                if (typeof SeparationPage !== 'undefined') SeparationPage.initConflits();
                if (typeof ControlesPage !== 'undefined') ControlesPage.init();
                break;
            case 'mouvement':
                if (typeof MouvementPage !== 'undefined') MouvementPage.init();
                break;
            case 'usage':
                if (typeof UsagePage !== 'undefined') UsagePage.init();
                break;
            case 'apprentissage':
                if (typeof ApprentissagePage !== 'undefined') ApprentissagePage.init();
                break;
        }
    },

    initQuickActions() {
        document.querySelectorAll('.quick-action[data-goto]').forEach(btn => {
            btn.addEventListener('click', () => this.navigateTo(btn.dataset.goto));
        });

        document.querySelectorAll('.quick-action[data-action]').forEach(btn => {
            btn.addEventListener('click', () => {
                if (btn.dataset.action === 'export-all') {
                    // L'export global n'existe pas ; l'export du modèle, si.
                    // Annoncer « en développement » là où une page répond
                    // déjà à la demande fait chercher ailleurs.
                    App.navigateTo('export-modele');
                }
            });
        });
    },

    initGlobalSearch() {
        const searchInput = document.getElementById('global-search');
        if (searchInput) {
            searchInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    const query = searchInput.value.trim();
                    if (query) {
                        Toast.info(I18n.t('search.title'),
                                   I18n.t('search.not_available', { query }));
                    }
                }
            });
        }

        document.addEventListener('keydown', (e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
                e.preventDefault();
                searchInput?.focus();
            }
        });
    },

    initRefreshButton() {
        const refreshBtn = document.getElementById('refresh-btn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => {
                const icon = refreshBtn.querySelector('i');
                icon.classList.add('icon-spin');
                this.loadPageData(this.currentPage);
                setTimeout(() => {
                    icon.classList.remove('icon-spin');
                    Toast.success(I18n.t('common.refreshed'),
                                  I18n.t('common.data_reloaded'));
                }, 1000);
            });
        }
    },

    hideLoader() {
        const loader = document.getElementById('app-loader');
        if (loader) {
            setTimeout(() => loader.classList.add('hidden'), 300);
        }
    }
};

Utils.ready(() => App.init());
window.App = App;