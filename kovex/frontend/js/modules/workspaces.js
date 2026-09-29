/**
 * PyGIA Frontend - Workspace Manager Module
 * Gestion des workspaces multi-clients côté frontend
 * Version corrigée avec debugging amélioré
 */

const WorkspaceManager = {
    // État
    currentWorkspace: null,
    allWorkspaces: [],
    isInitialized: false,
    
    // Clé localStorage pour l'état sauvegardé
    STATE_KEY_PREFIX: 'pygia_workspace_state_',

    //: Période de la sauvegarde automatique de la position de travail.
    //  Nommée plutôt qu'écrite dans l'appel : c'est le genre de valeur qu'on
    //  veut pouvoir changer sans relire le corps de la fonction.
    INTERVALLE_SAUVEGARDE_MS: 30000,
    
    /**
     * Initialise le gestionnaire de workspaces
     */
    async init() {
        
        if (this.isInitialized) {
            return;
        }
        
        // `loadWorkspaces` rattrape ses propres pannes et bascule le
        // sélecteur en état dégradé. L'entourer d'un `try/catch` était du
        // code que rien ne pouvait atteindre, et qui laissait croire que le
        // démarrage traitait un cas déjà traité ailleurs.
        this.bindEvents();
        await this.loadWorkspaces();
        this.startAutoSave();
        this.isInitialized = true;
    },
    
    /** Réaffiche le sélecteur dans la langue courante. */
    rafraichirLangue() {
        this.renderWorkspaceSelector();
        this.updateCurrentWorkspaceDisplay();
        // L'alternative textuelle du logo est le libellé du thème : elle est
        // traduite, donc elle change de langue avec le reste.
        ThemeVisuel.rendreLogo();
    },

    /**
     * Charge la liste des workspaces depuis l'API
     */
    async loadWorkspaces() {
        
        try {
            const response = await API.get('/workspaces');
            
            this.allWorkspaces = response.workspaces || [];
            this.currentWorkspace = this.allWorkspaces.find(
                ws => ws.id === response.active_workspace
            ) || null;
            
            
            this.renderWorkspaceSelector();
            this.updateCurrentWorkspaceDisplay();

            // L'habillage suit le workspace actif : il est demandé ici et
            // nulle part ailleurs, pour qu'un écran ne puisse pas s'afficher
            // aux couleurs du client précédent.
            await ThemeVisuel.charger(this.currentWorkspace && this.currentWorkspace.id,
                                      this.currentWorkspace && this.currentWorkspace.theme);

            // Restaurer l'état si workspace actif
            if (this.currentWorkspace) {
                await this.restoreState();
            }
            
        } catch (error) {
            // Si erreur API, afficher un état "pas de workspace"
            this.renderNoWorkspaceState();
        }
    },
    
    /**
     * Bind les événements UI
     */
    bindEvents() {
        
        // Toggle dropdown
        const toggle = document.getElementById('workspace-toggle');
        if (toggle) {
            toggle.addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggleDropdown();
            });
        }
        
        // Fermer dropdown si clic ailleurs
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.workspace-selector')) {
                this.closeDropdown();
            }
        });
        
        // Bouton créer workspace (+)
        const createBtn = document.getElementById('create-workspace-btn');
        if (createBtn) {
            createBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.openCreateModal();
            });
        }
        
        // Bouton gérer workspaces
        const manageBtn = document.getElementById('manage-workspaces-btn');
        if (manageBtn) {
            manageBtn.addEventListener('click', () => {
                this.closeDropdown();
                App.navigateTo('workspaces');
            });
        }
        
        // Formulaire création workspace
        const createForm = document.getElementById('create-workspace-form');
        if (createForm) {
            createForm.addEventListener('submit', (e) => {
                e.preventDefault();
                this.createWorkspace();
            });
        }
        
        // Bouton confirmer création (dans la modale)
        const confirmCreateBtn = document.getElementById('btn-create-workspace');
        if (confirmCreateBtn) {
            confirmCreateBtn.addEventListener('click', (e) => {
                e.preventDefault();
                this.createWorkspace();
            });
        }
        
    },
    
    /**
     * Toggle le dropdown des workspaces
     */
    toggleDropdown() {
        const menu = document.getElementById('workspace-menu');
        if (menu) {
            const isVisible = menu.style.display !== 'none';
            menu.style.display = isVisible ? 'none' : 'block';
        }
    },
    
    /**
     * Ferme le dropdown
     */
    closeDropdown() {
        const menu = document.getElementById('workspace-menu');
        if (menu && menu.style.display !== 'none') {
            menu.style.display = 'none';
        }
    },
    
    /**
     * Render la liste des workspaces dans le dropdown
     */
    renderWorkspaceSelector() {
        const container = document.getElementById('workspace-list');
        if (!container) {
            return;
        }
        
        if (this.allWorkspaces.length === 0) {
            container.innerHTML = `
                <div class="workspace-empty">
                    <i class="fas fa-inbox panneau-vide__icone" aria-hidden="true"></i>
                    <p class="panneau-vide__texte">${
                        Utils.escapeHtml(I18n.t('workspace.none'))}</p>
                    <button class="btn btn-primary btn-sm" data-action="workspace-create-open">
                        <i class="fas fa-plus" aria-hidden="true"></i> ${
                            Utils.escapeHtml(I18n.t('workspace.create'))}
                    </button>
                </div>
            `;
            return;
        }
        
        // `DEV` était la valeur de repli d'un environnement non renseigné :
        // afficher un environnement que le workspace ne déclare pas est pire
        // que d'afficher qu'il n'en déclare pas.
        container.innerHTML = this.allWorkspaces.map(ws => {
            const actif = ws.id === (this.currentWorkspace && this.currentWorkspace.id);
            const environnement = ws.environment || '';
            const nombre = (ws.data_stats && ws.data_stats.users) || 0;
            return `
            <div class="workspace-item ${actif ? 'active' : ''}"
                 data-ws-switch="${Utils.escapeHtml(ws.id)}"
                 data-workspace-id="${Utils.escapeHtml(ws.id)}">
                <div class="workspace-icon">
                    <i class="fas fa-briefcase" aria-hidden="true"></i>
                </div>
                <div class="workspace-info">
                    <div class="workspace-name">${Utils.escapeHtml(ws.name)}</div>
                    <div class="workspace-meta">
                        <span class="workspace-badge ${Utils.escapeHtml(environnement.toLowerCase())}">
                            ${Utils.escapeHtml(environnement || I18n.t('common.not_provided'))}
                        </span>
                        <span class="workspace-stats">
                            ${Utils.escapeHtml(Utils.formatNumber(nombre))}
                            ${Utils.escapeHtml(I18n.t('stats.identities'))}
                        </span>
                    </div>
                </div>
                ${actif ? '<i class="fas fa-check workspace-active-check" aria-hidden="true"></i>' : ''}
            </div>`;
        }).join('');
    },
    
    /**
     * Met à jour l'affichage du workspace actuel dans la topbar
     */
    updateCurrentWorkspaceDisplay() {
        const nameEl = document.getElementById('current-workspace-name');
        
        if (nameEl) {
            if (this.currentWorkspace) {
                this.nommerLaBarre(nameEl, this.currentWorkspace.name, null);
            } else {
                this.nommerLaBarre(nameEl, I18n.t('workspace.select'), 'workspace.select');
            }
        }
    },

    /**
     * Écrit le libellé de la barre et dit à I18n s'il doit le retraduire.
     *
     * Le gabarit porte une clé de traduction pour l'état initial. Laissée en
     * place, elle faisait réécrire « Sélectionner un workspace » par-dessus
     * le nom du workspace actif à chaque passage d'`applyTranslations` —
     * un changement de langue, ou le premier rendu après le chargement.
     * Le nom d'un workspace ne se traduit pas : la clé ne reste que tant
     * que la barre affiche un message du produit.
     */
    nommerLaBarre(nameEl, texte, cle) {
        nameEl.textContent = texte;
        if (cle) {
            nameEl.setAttribute('data-i18n-key', cle);
        } else {
            nameEl.removeAttribute('data-i18n-key');
        }
    },
    
    /**
     * Affiche l'état "pas de workspace"
     */
    renderNoWorkspaceState() {
        // Aucun workspace lisible : aucun habillage client ne doit rester.
        ThemeVisuel.appliquer(null);
        const nameEl = document.getElementById('current-workspace-name');
        if (nameEl) {
            this.nommerLaBarre(nameEl, I18n.t('workspace.none'), 'workspace.none');
        }
        
        const container = document.getElementById('workspace-list');
        if (container) {
            container.innerHTML = `
                <div class="workspace-empty panneau-vide">
                    <i class="fas fa-exclamation-circle panneau-vide__icone panneau-vide__icone--alerte" aria-hidden="true"></i>
                    <p class="panneau-vide__texte panneau-vide__texte--sans-suite">${
                        Utils.escapeHtml(I18n.t('workspace.load_failed'))}</p>
                    <button class="btn btn-sm btn-secondary panneau-vide__action" data-ws-switch-reload="1">
                        <i class="fas fa-refresh" aria-hidden="true"></i> ${
                            Utils.escapeHtml(I18n.t('action.retry'))}
                    </button>
                </div>
            `;
        }
    },
    
    /**
     * Bascule vers un autre workspace
     */
    async switchWorkspace(workspaceId) {
        
        if (workspaceId === this.currentWorkspace?.id) {
            this.closeDropdown();
            return;
        }
        
        try {
            // Sauvegarder l'état actuel avant de switch
            await this.saveCurrentState();
            
            // Afficher loader
            this.showSwitchingLoader();
            
            // Appeler l'API pour switch
            const response = await API.post(`/workspaces/switch/${workspaceId}`);
            
            // Notifier l'utilisateur
            Toast.success(I18n.t('workspace.switched'),
                          I18n.t('workspace.switched_detail',
                                 { nom: response.name || workspaceId }));
            
            // Recharger la page pour reset tous les états
            setTimeout(() => {
                window.location.reload();
            }, 500);
            
        } catch (error) {
            Toast.error(I18n.t('common.error'),
                        error.message || I18n.t('workspace.switch_failed'));
            this.hideSwitchingLoader();
        }
    },
    
    /**
     * Affiche un loader pendant le switch
     */
    showSwitchingLoader() {
        const overlay = document.createElement('div');
        overlay.id = 'workspace-switching-overlay';
        overlay.className = 'workspace-switching-overlay';
        overlay.innerHTML = `
            <div class="workspace-switching-overlay__contenu">
                <div class="loading-spinner"></div>
                <p>${Utils.escapeHtml(I18n.t('workspace.switching'))}</p>
            </div>`;
        document.body.appendChild(overlay);
    },
    
    /**
     * Cache le loader de switch
     */
    hideSwitchingLoader() {
        const overlay = document.getElementById('workspace-switching-overlay');
        if (overlay) {
            overlay.remove();
        }
    },
    
    /**
     * Ouvre la modale de création de workspace
     */
    /**
     * Ouvre la modale de création de workspace
     */
    openCreateModal() {
        this.closeDropdown();
        
        // Reset le formulaire
        const form = document.getElementById('create-workspace-form');
        if (form) {
            form.reset();
        }
        
        // Ouvrir la modale
        const modal = document.getElementById('create-workspace-modal');
        if (!modal) {
            Toast.error(I18n.t('common.error'), I18n.t('workspace.modal_missing'));
            return;
        }

        // Le gestionnaire de modales pose la classe qui lève `opacity: 0` et
        // `visibility: hidden`, et rend la fermeture par Échap.
        Modal.open('create-workspace-modal');

        // Le focus va sur le premier champ, et **tout de suite**.
        //
        // Il était posé cent millisecondes plus tard, par un `setTimeout`. Ce
        // délai n'attendait rien : la fenêtre est déjà ouverte et déjà peuplée
        // quand `Modal.open` rend la main. En revanche, il permettait à ce
        // focus d'arriver **après** celui que la validation pose sur le champ
        // fautif — et le message « le client est obligatoire » se lisait alors
        // avec le curseur dans le champ du nom. L'utilisateur corrige le
        // mauvais champ.
        document.getElementById('new-ws-name')?.focus();
    },
    
    /**
     * Ferme la modale de création
     */
    closeCreateModal() {
        Modal.close();
    },
    
    /**
     * Crée un nouveau workspace
     */
    async createWorkspace() {
        
        const nameInput = document.getElementById('new-ws-name');
        const clientInput = document.getElementById('new-ws-client');
        const envSelect = document.getElementById('new-ws-env');

        const name = nameInput?.value?.trim();
        const client = clientInput?.value?.trim();
        const environment = envSelect?.value || 'DEV';
        // Un workspace naît avec le thème d'origine : son dossier vient d'être
        // créé, aucun thème client n'y est encore déposé. Le choix se fait
        // ensuite, depuis la carte du workspace.
        const theme = ThemeVisuel.IDENTIFIANT_PAR_DEFAUT;
        
        
        // Validation
        if (!name) {
            Toast.error(I18n.t('common.error'), I18n.t('workspace.name_required'));
            nameInput?.focus();
            return;
        }

        if (!client) {
            Toast.error(I18n.t('common.error'), I18n.t('workspace.client_required'));
            clientInput?.focus();
            return;
        }
        
        try {
            const response = await API.post('/workspaces', {
                name,
                client,
                environment,
                theme
            });
            
            
            Toast.success(I18n.t('workspace.created'),
                          I18n.t('workspace.created_detail',
                                 { nom: response.name || name }));

            WorkspaceManager.closeCreateModal();
            await this.loadWorkspaces();

            // Premier workspace : rien n'est actif tant qu'on n'active pas.
            if (this.allWorkspaces.length === 1 && response.id) {
                const activer = await Confirm.demander({
                    titre: I18n.t('confirm.workspace_activate_title'),
                    message: I18n.t('confirm.workspace_activate',
                                    { nom: response.name || name }),
                });
                if (activer) await this.switchWorkspace(response.id);
            }

        } catch (error) {
            Toast.error(I18n.t('common.error'),
                        error.message || I18n.t('workspace.create_failed'));
        }
    },
    
    /**
     * Supprime un workspace
     */
    async deleteWorkspace(workspaceId) {
        const workspace = this.allWorkspaces.find(ws => ws.id === workspaceId);
        
        const confirme = await Confirm.demander({
            titre: I18n.t('confirm.workspace_delete_title'),
            message: I18n.t('confirm.workspace_delete',
                            { nom: workspace?.name || workspaceId }),
            details: [I18n.t('confirm.workspace_delete_detail_data'),
                      I18n.t('confirm.workspace_delete_detail_kb'),
                      I18n.t('confirm.workspace_delete_detail_exports')],
            confirmer: I18n.t('confirm.delete_action'),
            danger: true,
        });
        if (!confirme) return;
        
        try {
            const response = await API.delete(`/workspaces/${workspaceId}`);
            
            Toast.success(I18n.t('workspace.deleted'),
                          I18n.t('workspace.deleted_detail'));
            
            // Recharger
            await this.loadWorkspaces();
            
            // Si c'était le workspace actif et qu'il y en a un nouveau
            if (response.new_active_workspace && workspaceId === this.currentWorkspace?.id) {
                window.location.reload();
            }
            
        } catch (error) {
            Toast.error(I18n.t('common.error'),
                        error.message || I18n.t('workspace.delete_failed'));
        }
    },
    
    /**
     * Sauvegarde l'état actuel (page, filtres, scroll)
     */
    async saveCurrentState() {
        if (!this.currentWorkspace) return;
        
        const state = {
            workspace_id: this.currentWorkspace.id,
            current_page: typeof App !== 'undefined' ? App.currentPage : null,
            scroll_position: window.scrollY,
            timestamp: Date.now()
        };
        
        try {
            localStorage.setItem(
                this.STATE_KEY_PREFIX + this.currentWorkspace.id,
                JSON.stringify(state)
            );
        } catch (e) {
            // Le stockage local peut etre refuse (navigation privee, quota) :
            // la position de l'utilisateur n'est alors pas memorisee, sans plus.
        }
    },
    
    /**
     * Restaure l'état sauvegardé
     */
    async restoreState() {
        if (!this.currentWorkspace) return;
        
        try {
            const stateKey = this.STATE_KEY_PREFIX + this.currentWorkspace.id;
            const savedState = localStorage.getItem(stateKey);
            
            if (savedState) {
                const state = JSON.parse(savedState);
                
                // Restaurer la page si App disponible
                if (state.current_page && typeof App !== 'undefined') {
                    // Délai pour laisser l'app s'initialiser
                    setTimeout(() => {
                        App.navigateTo(state.current_page);
                        
                        // Restaurer le scroll
                        if (state.scroll_position) {
                            setTimeout(() => {
                                window.scrollTo(0, state.scroll_position);
                            }, 100);
                        }
                    }, 200);
                }
            }
        } catch (e) {
            // Etat illisible ou stockage refuse : on repart d'un affichage neuf
            // plutot que d'interrompre le chargement de la page.
        }
    },
    
    /**
     * Auto-save périodique
     */
    startAutoSave() {
        setInterval(() => {
            this.saveCurrentState();
        }, this.INTERVALLE_SAUVEGARDE_MS);
        
        // Sauvegarder avant fermeture
        window.addEventListener('beforeunload', () => {
            this.saveCurrentState();
        });
    },
    
    /**
     * Retourne le workspace actif
     */
    getCurrentWorkspace() {
        return this.currentWorkspace;
    },
    
    /**
     * Vérifie si un workspace est actif
     */
    hasActiveWorkspace() {
        return this.currentWorkspace !== null;
    },
    
    // Les deux fonctions utilitaires qui vivaient ici — un `escapeHtml`
    // identique à celui de `Utils` et un `formatNumber` qui abrégeait en
    // « 17.9K » — ont été retirées. Un volume abrégé n'est pas lisible sur un
    // référentiel : « 17 881 » et « 17 881 » se distinguent, « 17.9K » et
    // « 17.9K » non.
};

// Export global
// Délégation du sélecteur de workspace. Comme ailleurs, les actions passent
// par des attributs de données : un identifiant de workspace inséré dans un
// `onclick` s'exécuterait s'il contenait une apostrophe.
document.addEventListener('click', (evenement) => {
    const bascule = evenement.target.closest('[data-ws-switch]');
    if (bascule) {
        evenement.preventDefault();
        WorkspaceManager.switchWorkspace(bascule.dataset.wsSwitch);
        return;
    }
    const rechargement = evenement.target.closest('[data-ws-switch-reload]');
    if (rechargement) {
        evenement.preventDefault();
        WorkspaceManager.loadWorkspaces();
    }
});

window.WorkspaceManager = WorkspaceManager;
