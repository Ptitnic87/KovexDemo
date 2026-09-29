/**
 * PyGIA Frontend - Workspaces Management Page
 * Page de gestion des workspaces (création, édition, suppression)
 */

const WorkspacesPage = {
    // Les noms de champs de l'envoi d'import, par champ de saisie. La route
    // déclare `habs` ; le formulaire lisait `import-habilitations` et
    // envoyait `habilitations`. Une table unique, vérifiée par un test contre
    // la signature de la route, ferme la classe de défaut.
    CHAMPS_DE_FICHIER: {
        'import-identities': 'identities',
        'import-applications': 'applications',
        'import-rights': 'rights',
        'import-habilitations': 'habs',
    },

    // Extrait envoyé pour inspection. Assez pour l'en-tête et quelques
    // lignes, assez peu pour que le geste reste instantané sur un fichier de
    // plusieurs centaines de mégaoctets.
    TAILLE_EXTRAIT: 64 * 1024,

    // Ce que la dernière inspection a rendu, ou null.
    inspection: null,

    workspaces: [],
    
    /**
     * Initialise la page
     */
    async init() {
        await this.loadWorkspaces();
        this.bindEvents();
    },
    
    /**
     * Charge les workspaces
     */
    async loadWorkspaces() {
        try {
            const response = await API.get('/workspaces');
            this.workspaces = response.workspaces || [];
            this.activeWorkspaceId = response.active_workspace;
            this.render();
        } catch (error) {
            this.renderError();
        }
    },
    
    /** Réaffiche les cartes déjà rendues, dans la langue courante. */
    rafraichirLangue() {
        if (this.workspaces.length) this.render();
    },

    /**
     * Bindage des événements
     */
    bindEvents() {
        // Délégation sur le document : les cartes de workspace sont
        // reconstruites à chaque chargement, un écouteur posé sur chacune
        // serait perdu. Les actions sont déclarées par attribut de données —
        // jamais par `onclick`, qui insère la valeur dans un contexte
        // JavaScript où l'échappement HTML ne protège de rien.
        if (WorkspacesPage._delegationPosee) return;
        WorkspacesPage._delegationPosee = true;

        const actions = {
            create: () => WorkspaceManager.openCreateModal(),
            reload: () => WorkspacesPage.loadWorkspaces(),
            'close-import': () => WorkspacesPage.closeImportModal(),
            'inspect-import': () => WorkspacesPage.inspecterLesFichiers(),
            'do-import': () => WorkspacesPage.doImport(),
            activate: (id) => WorkspacesPage.activateWorkspace(id),
            import: (id) => WorkspacesPage.openImportModal(id),
            export: (id) => WorkspacesPage.exportWorkspace(id),
            theme: (id) => WorkspacesPage.openThemeModal(id),
            'close-theme': () => WorkspacesPage.closeThemeModal(),
            'apply-theme': () => WorkspacesPage.applyTheme(),
            delete: (id) => WorkspacesPage.deleteWorkspace(id),
        };

        document.addEventListener('click', (evenement) => {
            const porteur = evenement.target.closest('[data-ws-action]');
            if (!porteur) return;
            const action = actions[porteur.dataset.wsAction];
            if (!action) return;
            evenement.preventDefault();
            action(porteur.dataset.wsId);
        });
    },

    _delegationPosee: false,
    
    /**
     * Affiche les workspaces
     */
    render() {
        const container = document.getElementById('workspaces-management-grid');
        if (!container) {
            return;
        }
        
        if (this.workspaces.length === 0) {
            container.innerHTML = `
                <div class="empty-state empty-state--pleine-largeur">
                    <div class="empty-state-icon">
                        <i class="fas fa-briefcase empty-state__icone-large" aria-hidden="true"></i>
                    </div>
                    <h2 class="empty-state__titre">${Utils.escapeHtml(I18n.t('workspace.none'))}</h2>
                    <p class="empty-state__texte">
                        ${Utils.escapeHtml(I18n.t('workspace.none_detail'))}
                    </p>
                    <button class="btn btn-primary" data-ws-action="create">
                        <i class="fas fa-plus" aria-hidden="true"></i>
                        ${Utils.escapeHtml(I18n.t('action.create_workspace'))}
                    </button>
                </div>
            `;
            return;
        }
        
        container.innerHTML = this.workspaces.map(ws => this.renderWorkspaceCard(ws)).join('');
        this.poserLesLogos(container);
    },

    /** URL d'objet des logos posés sur les cartes, à révoquer au rendu suivant. */
    adressesDesLogos: [],

    /** Numéro du rendu en cours : un logo lu pour un rendu dépassé est jeté. */
    rendu: 0,

    /**
     * Remplace l'icône d'une carte par le logo du thème de son espace.
     *
     * Une carte ne disait pas de quel client elle parlait autrement que par
     * son nom : sur un écran qui en aligne dix, l'œil cherche une marque. Le
     * logo est celui que le thème de l'espace porte déjà — le même que
     * l'en-tête affiche pour l'espace actif —, lu par un appel authentifié et
     * posé en URL d'objet, pour la même raison que là-bas : une balise
     * `<img src>` vers l'API ne porte pas le jeton.
     *
     * Un espace sans thème, sur le thème d'origine ou dont le logo ne se lit
     * pas garde son icône : une marque absente vaut mieux qu'une image brisée.
     * Les adresses du rendu précédent sont révoquées ; un logo qui arrive
     * après un nouveau rendu est révoqué aussitôt au lieu d'être posé sur une
     * carte qui n'est plus affichée.
     */
    poserLesLogos(container) {
        this.adressesDesLogos.forEach((adresse) => URL.revokeObjectURL(adresse));
        this.adressesDesLogos = [];
        this.rendu += 1;
        const rendu = this.rendu;
        const icones = container.querySelectorAll('.workspace-card-icon[data-logo-theme]');
        return Promise.all(Array.from(icones).map(async (icone) => {
            const carte = icone.closest('[data-workspace-id]');
            if (!carte) return;
            let contenu;
            try {
                contenu = await API.blob(
                    `/workspaces/${encodeURIComponent(carte.dataset.workspaceId)}`
                    + `/themes/${encodeURIComponent(icone.dataset.logoTheme)}/logo`);
            } catch (erreur) {
                return;
            }
            const adresse = URL.createObjectURL(contenu);
            if (rendu !== this.rendu) {
                URL.revokeObjectURL(adresse);
                return;
            }
            this.adressesDesLogos.push(adresse);
            const image = document.createElement('img');
            image.className = 'workspace-card-logo';
            image.src = adresse;
            // Le nom de l'espace est écrit à côté : l'image n'ajoute rien à
            // ce qu'un lecteur d'écran annonce déjà.
            image.alt = '';
            icone.replaceChildren(image);
            icone.classList.add('workspace-card-icon--logo');
        }));
    },
    
    /**
     * Génère le HTML d'une carte workspace
     */
    renderWorkspaceCard(ws) {
        const isActive = ws.id === this.activeWorkspaceId;
        // La couleur d'un environnement appartient au thème : elle était
        // écrite en dur ici, en hexadécimal, alors que la feuille de style
        // porte déjà `.workspace-badge.dev`, `.prod`, `.test`, `.uat`. Deux
        // définitions de la même couleur finissent toujours par diverger.
        const environnement = ws.environment || '';
        const classeEnv = environnement.toLowerCase();
        // Le thème d'origine n'a pas de logo : inutile de le demander.
        const aUnTheme = Boolean(ws.theme) && ws.theme !== ThemeVisuel.IDENTIFIANT_PAR_DEFAUT;

        return `
            <div class="workspace-card ${isActive ? 'active' : ''}" data-workspace-id="${Utils.escapeHtml(ws.id)}">
                <div class="workspace-card-header">
                    <div class="workspace-card-icon workspace-card-icon--${Utils.escapeHtml(classeEnv)}"${
                        aUnTheme ? ` data-logo-theme="${Utils.escapeHtml(ws.theme)}"` : ''}>
                        <i class="fas fa-briefcase" aria-hidden="true"></i>
                    </div>
                    <div class="workspace-card-title">
                        <h3>${Utils.escapeHtml(ws.name)}</h3>
                        ${isActive ? `<span class="badge badge-success">${
                            Utils.escapeHtml(I18n.t('workspace.active'))}</span>` : ''}
                    </div>
                </div>

                <div class="workspace-card-meta">
                    <span class="workspace-badge ${Utils.escapeHtml(classeEnv)}">
                        ${Utils.escapeHtml(environnement || I18n.t('common.not_provided'))}
                    </span>
                    <span class="workspace-client">
                        <i class="fas fa-building" aria-hidden="true"></i>
                        ${Utils.escapeHtml(ws.client || I18n.t('common.not_provided'))}
                    </span>
                </div>

                <div class="workspace-card-stats">
                    ${[['fa-users', 'users', 'stats.identities'],
                       ['fa-cubes', 'apps', 'stats.applications'],
                       ['fa-key', 'rights', 'stats.rights']].map(([icone, cle, libelle]) => `
                        <div class="stat-item">
                            <i class="fas ${icone}" aria-hidden="true"></i>
                            <span class="stat-value">${Utils.escapeHtml(
                                Utils.formatNumber((ws.data_stats && ws.data_stats[cle]) || 0))}</span>
                            <span class="stat-label">${Utils.escapeHtml(I18n.t(libelle))}</span>
                        </div>`).join('')}
                </div>

                <div class="workspace-card-info">
                    <div class="info-item">
                        <i class="fas fa-calendar" aria-hidden="true"></i>
                        <span>${Utils.escapeHtml(I18n.t('workspace.created_on',
                            { date: WorkspacesPage.formatDate(ws.created_at) }))}</span>
                    </div>
                    <div class="info-item">
                        <i class="fas fa-clock" aria-hidden="true"></i>
                        <span>${Utils.escapeHtml(I18n.t('workspace.last_access',
                            { date: WorkspacesPage.formatRelativeDate(ws.last_accessed) }))}</span>
                    </div>
                </div>

                <div class="workspace-card-actions">
                    ${isActive ? `
                        <button class="btn btn-secondary btn-sm" disabled>
                            <i class="fas fa-check" aria-hidden="true"></i>
                            ${Utils.escapeHtml(I18n.t('workspace.active'))}
                        </button>
                    ` : `
                        <button class="btn btn-primary btn-sm" data-ws-action="activate" data-ws-id="${Utils.escapeHtml(ws.id)}">
                            <i class="fas fa-play" aria-hidden="true"></i>
                            ${Utils.escapeHtml(I18n.t('workspace.activate'))}
                        </button>
                    `}
                    <button class="btn btn-secondary btn-sm" data-ws-action="import" data-ws-id="${Utils.escapeHtml(ws.id)}">
                        <i class="fas fa-upload" aria-hidden="true"></i>
                        ${Utils.escapeHtml(I18n.t('workspace.import'))}
                    </button>
                    <button class="btn btn-secondary btn-sm" data-ws-action="export" data-ws-id="${Utils.escapeHtml(ws.id)}">
                        <i class="fas fa-download" aria-hidden="true"></i>
                        ${Utils.escapeHtml(I18n.t('workspace.export'))}
                    </button>
                    <button class="btn btn-secondary btn-sm" data-ws-action="theme" data-ws-id="${Utils.escapeHtml(ws.id)}">
                        <i class="fas fa-palette" aria-hidden="true"></i>
                        ${Utils.escapeHtml(I18n.t('workspace.theme'))}
                    </button>
                    <button class="btn btn-danger btn-sm" data-ws-action="delete" data-ws-id="${Utils.escapeHtml(ws.id)}"
                            title="${Utils.escapeHtml(isActive ? I18n.t('workspace.cannot_delete_active')
                                                              : I18n.t('workspace.delete'))}"
                            ${isActive ? 'disabled' : ''}>
                        <i class="fas fa-trash" aria-hidden="true"></i>
                    </button>
                </div>
            </div>
        `;
    },
    
    /**
     * Affiche une erreur
     */
    renderError() {
        const container = document.getElementById('workspaces-management-grid');
        if (container) {
            container.innerHTML = `
                <div class="empty-state error empty-state--pleine-largeur">
                    <div class="empty-state-icon">
                        <i class="fas fa-exclamation-triangle empty-state__icone-large empty-state__icone-large--danger" aria-hidden="true"></i>
                    </div>
                    <h2>${Utils.escapeHtml(I18n.t('error.load_failed'))}</h2>
                    <p>${Utils.escapeHtml(I18n.t('workspace.load_failed'))}</p>
                    <button class="btn btn-primary" data-ws-action="reload">
                        <i class="fas fa-refresh" aria-hidden="true"></i>
                        ${Utils.escapeHtml(I18n.t('action.retry'))}
                    </button>
                </div>
            `;
        }
    },
    
    /**
     * Active un workspace
     */
    async activateWorkspace(workspaceId) {
        if (typeof WorkspaceManager !== 'undefined') {
            await WorkspaceManager.switchWorkspace(workspaceId);
        }
    },
    
    /** Workspace dont on règle le thème, et thèmes lus pour lui. */
    themeWorkspaceId: null,
    themesLus: null,

    /**
     * Ouvre la modale de choix du thème d'un workspace.
     *
     * Le choix ne peut pas se faire à la création : le dossier du workspace
     * vient d'être créé, donc aucun thème n'y est encore déposé. Il se fait
     * ici, une fois les fichiers en place.
     */
    async openThemeModal(workspaceId) {
        this.themeWorkspaceId = workspaceId;
        let modal = document.getElementById('theme-workspace-modal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'theme-workspace-modal';
            modal.className = 'modal-overlay';
            modal.innerHTML = `
                <div class="modal">
                    <div class="modal-header">
                        <h2><i class="fas fa-palette" aria-hidden="true"></i> ${
                            Utils.escapeHtml(I18n.t('workspace.theme_title'))}</h2>
                        <button class="modal-close" data-ws-action="close-theme"
                                aria-label="${Utils.escapeHtml(I18n.t('action.close'))}">
                            <i class="fas fa-times" aria-hidden="true"></i>
                        </button>
                    </div>
                    <div class="modal-body" id="theme-workspace-body"></div>
                    <div class="modal-footer">
                        <button class="btn btn-secondary" data-ws-action="close-theme">
                            ${Utils.escapeHtml(I18n.t('action.cancel'))}
                        </button>
                        <button class="btn btn-primary" data-ws-action="apply-theme">
                            <i class="fas fa-check" aria-hidden="true"></i>
                            ${Utils.escapeHtml(I18n.t('action.apply'))}
                        </button>
                    </div>
                </div>`;
            document.body.appendChild(modal);
        }

        const corps = document.getElementById('theme-workspace-body');
        corps.innerHTML = `<p class="text-muted">${
            Utils.escapeHtml(I18n.t('common.loading'))}</p>`;
        Modal.open('theme-workspace-modal');

        try {
            this.themesLus = await API.get(
                `/workspaces/${encodeURIComponent(workspaceId)}/themes`);
        } catch (erreur) {
            this.themesLus = null;
            corps.innerHTML = `<p class="text-muted">${
                Utils.escapeHtml(I18n.t('workspace.theme_load_failed'))}</p>`;
            return;
        }
        this.renderThemeChoices();
    },

    /** Dessine la liste des thèmes, et les dépôts écartés avec leur motif. */
    renderThemeChoices() {
        const corps = document.getElementById('theme-workspace-body');
        if (!corps || !this.themesLus) return;
        const workspace = this.workspaces.find(ws => ws.id === this.themeWorkspaceId);
        const courant = (workspace && workspace.theme) || ThemeVisuel.IDENTIFIANT_PAR_DEFAUT;

        const choix = this.themesLus.themes.map((theme) => {
            const identifiant = Utils.escapeHtml(theme.identifiant);
            const teintes = Object.values(
                (theme.variantes && theme.variantes.dark) || {}).slice(0, 5);
            return `
                <label class="theme-choix" for="theme-choix-${identifiant}">
                    <input type="radio" name="theme-workspace" id="theme-choix-${identifiant}"
                           value="${identifiant}"
                           ${theme.identifiant === courant ? 'checked' : ''}>
                    <span class="theme-choix__libelle">${
                        Utils.escapeHtml(ThemeVisuel.libelle(theme))}</span>
                    <span class="theme-choix__teintes" aria-hidden="true">${
                        teintes.map((teinte) => `<span class="theme-choix__teinte"
                             style="background-color: ${
                                 ThemeVisuel.MOTIF_COULEUR.test(teinte) ? teinte : 'transparent'}"
                             ></span>`).join('')}</span>
                </label>`;
        }).join('');

        const refuses = this.themesLus.refuses.map((refus) => `
            <li class="theme-refus">${
                Utils.escapeHtml(I18n.t(refus.code, refus.params || {}))}</li>`).join('');

        corps.innerHTML = `
            <fieldset class="theme-choix-groupe">
                <legend class="form-label">${
                    Utils.escapeHtml(I18n.t('workspace.theme_choose'))}</legend>
                ${choix}
            </fieldset>
            <p class="form-hint">${Utils.escapeHtml(I18n.t('workspace.theme_deposit', {
                dossier: this.themesLus.dossier, document: this.themesLus.document }))}</p>
            ${refuses ? `<div class="theme-refus-groupe">
                <p class="form-label">${
                    Utils.escapeHtml(I18n.t('workspace.theme_refused'))}</p>
                <ul class="theme-refus-liste">${refuses}</ul>
            </div>` : ''}`;
    },

    /** Ferme la modale de thème. */
    closeThemeModal() {
        Modal.close();
    },

    /**
     * Enregistre le thème choisi.
     *
     * Le serveur revalide : c'est lui qui décide, l'interface ne fait que
     * proposer ce qu'il a déjà accepté.
     */
    async applyTheme() {
        const choisi = document.querySelector('input[name="theme-workspace"]:checked');
        if (!choisi) return;
        try {
            await API.put(`/workspaces/${encodeURIComponent(this.themeWorkspaceId)}`,
                          { theme: choisi.value });
        } catch (erreur) {
            Toast.error(I18n.t('common.error'),
                        erreur.message || I18n.t('workspace.theme_failed'));
            return;
        }
        Toast.success(I18n.t('workspace.theme_applied'),
                      I18n.t('workspace.theme_applied_detail'));
        this.closeThemeModal();
        await this.loadWorkspaces();
        // L'habillage n'est repeint que si c'est le workspace ouvert : régler
        // le thème d'un autre client ne doit rien changer à l'écran courant.
        if (this.themeWorkspaceId === this.activeWorkspaceId) {
            await ThemeVisuel.charger(this.themeWorkspaceId, choisi.value);
        }
    },

    /**
     * Ouvre la modale d'import
     */
    openImportModal(workspaceId) {
        // La modale est montée une seule fois, puis réutilisée.
        let modal = document.getElementById('import-workspace-modal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'import-workspace-modal';
            modal.className = 'modal-overlay';
            modal.innerHTML = `
                <div class="modal">
                    <div class="modal-header">
                        <h2><i class="fas fa-upload" aria-hidden="true"></i> ${
                            Utils.escapeHtml(I18n.t('workspace.import_title'))}</h2>
                        <button class="modal-close" data-ws-action="close-import">
                            <i class="fas fa-times" aria-hidden="true"></i>
                        </button>
                    </div>
                    <div class="modal-body">
                        <input type="hidden" id="import-workspace-id">
                        <p class="text-muted mb-4">
                            ${Utils.escapeHtml(I18n.t('workspace.import_hint'))}
                        </p>
                        <h2 id="import-correspondance-titre" class="sr-only">
                            ${Utils.escapeHtml(I18n.t('workspace.inspect_title'))}
                        </h2>
                        
                        <div class="form-group">
                            <label class="form-label">${Utils.escapeHtml(I18n.t('workspace.import_identities'))}</label>
                            <input type="file" id="import-identities" class="form-input" accept=".csv">
                        </div>
                        
                        <div class="form-group">
                            <label class="form-label">${Utils.escapeHtml(I18n.t('workspace.import_applications'))}</label>
                            <input type="file" id="import-applications" class="form-input" accept=".csv">
                        </div>
                        
                        <div class="form-group">
                            <label class="form-label">${Utils.escapeHtml(I18n.t('workspace.import_rights'))}</label>
                            <input type="file" id="import-rights" class="form-input" accept=".csv">
                        </div>
                        
                        <div class="form-group">
                            <label class="form-label">${Utils.escapeHtml(I18n.t('workspace.import_habilitations'))}</label>
                            <input type="file" id="import-habilitations" class="form-input" accept=".csv">
                        </div>

                        <!-- Kovex ne connaît pas les colonnes à l'avance : il lit
                             un extrait, montre ce qu'il y a vu, et la personne
                             confirme. Rien n'est deviné en silence. -->
                        <button class="btn btn-secondary" data-ws-action="inspect-import">
                            <i class="fas fa-magnifying-glass" aria-hidden="true"></i>
                            ${Utils.escapeHtml(I18n.t('workspace.import_step_inspect'))}
                        </button>
                        <section id="import-correspondance" class="import-correspondance"
                                 aria-labelledby="import-correspondance-titre" hidden>
                        </section>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-secondary" data-ws-action="close-import">
                            ${Utils.escapeHtml(I18n.t('action.cancel'))}
                        </button>
                        <button class="btn btn-primary" data-ws-action="do-import">
                            <i class="fas fa-upload" aria-hidden="true"></i>
                            ${Utils.escapeHtml(I18n.t('workspace.import_step_confirm'))}
                        </button>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);
        }
        
        document.getElementById('import-workspace-id').value = workspaceId;
        // Une modale rouverte ne doit pas montrer ce qu'on a lu la fois
        // d'avant : la correspondance porterait sur d'autres fichiers.
        this.inspection = null;
        const correspondance = document.getElementById('import-correspondance');
        if (correspondance) {
            correspondance.innerHTML = '';
            correspondance.hidden = true;
        }

        // Elle s'ouvrait par `style.display = 'flex'`. La feuille de style
        // pose `opacity: 0; visibility: hidden` sur toute `.modal-overlay` et
        // ne les lève que sur `.active` : la modale existait dans la page,
        // occupait l'écran, et restait invisible. Le bouton « Importer »
        // paraissait sans effet.
        //
        // Le gestionnaire de modales pose cette classe, verrouille le
        // défilement de la page et gère la fermeture par Échap.
        Modal.open('import-workspace-modal');
    },
    
    /**
     * Ferme la modale d'import
     */
    closeImportModal() {
        Modal.close();
    },
    
    /**
     * Les fichiers choisis, rangés sous le nom que la route attend.
     *
     * Une seule table, et c'est nécessaire : le fichier des habilitations
     * partait sous le nom `habilitations` alors que la route le déclare sous
     * `habs`. Il n'arrivait donc jamais — importé seul, l'import répondait
     * « aucun fichier fourni » ; importé avec les autres, il était perdu en
     * silence et la réponse annonçait un succès, sans la matière première du
     * mining.
     */
    fichiersChoisis() {
        const choisis = {};
        Object.entries(WorkspacesPage.CHAMPS_DE_FICHIER).forEach(([champ, nom]) => {
            const fichier = document.getElementById(champ)?.files?.[0];
            if (fichier) choisis[nom] = fichier;
        });
        return choisis;
    },

    /**
     * Lit un extrait des fichiers choisis et propose une correspondance.
     *
     * Kovex ne connaît pas les colonnes à l'avance. Plutôt que de supposer une
     * convention — `ID_utilisateur`, point-virgule — il lit le début du
     * fichier et montre ce qu'il y a vu. Seul l'extrait part sur le réseau :
     * inspecter quatre référentiels ne doit rien coûter, même sur des fichiers
     * de plusieurs centaines de mégaoctets.
     */
    async inspecterLesFichiers() {
        const workspaceId = document.getElementById('import-workspace-id').value;
        const choisis = this.fichiersChoisis();
        if (!Object.keys(choisis).length) {
            Toast.warning(I18n.t('common.warning'),
                          I18n.t('workspace.import_select_file'));
            return;
        }

        const formData = new FormData();
        Object.entries(choisis).forEach(([nom, fichier]) => {
            formData.append(nom, fichier.slice(0, WorkspacesPage.TAILLE_EXTRAIT),
                            fichier.name);
        });

        try {
            const reponse = await fetch(
                `${Config.API_URL}/workspaces/${workspaceId}/inspecter-fichiers`, {
                    method: 'POST',
                    headers: typeof Auth !== 'undefined' ? Auth.getAuthHeaders() : {},
                    body: formData,
                });
            if (!reponse.ok) {
                throw new Error(await WorkspacesPage.messageDErreur(reponse));
            }
            this.inspection = await reponse.json();
            this.rendreLaCorrespondance();
        } catch (erreur) {
            this.inspection = null;
            Toast.error(I18n.t('workspace.inspect_failed'), erreur.message);
        }
    },

    /** Les clés qu'un référentiel donné peut porter. */
    clesDuFichier(nom) {
        if (nom === 'habs') return ['user_id_column', 'right_id_column'];
        if (nom === 'rights') return ['id_column', 'app_id_column'];
        return ['id_column'];
    },

    /**
     * Ce que l'inspection a lu, et les choix qui restent à faire.
     *
     * Rien n'est décidé ici : les listes proposent les colonnes du fichier, et
     * ce qui était déjà configuré est reproposé **s'il existe encore dans le
     * fichier**. Une colonne configurée que le fichier ne porte plus ne doit
     * pas être resélectionnée en silence : c'est précisément le cas qui donne
     * un référentiel vide.
     */
    rendreLaCorrespondance() {
        const zone = document.getElementById('import-correspondance');
        if (!zone) return;
        const lu = (this.inspection || {}).fichiers || {};
        const actuelle = (this.inspection || {}).correspondance_actuelle || {};

        zone.innerHTML = Object.entries(lu).map(([nom, vu]) => {
            const configure = actuelle[nom] || {};
            const options = (cle) => [
                `<option value="">${Utils.escapeHtml(
                    I18n.t('workspace.import_column_none'))}</option>`,
                ...vu.colonnes.map(colonne => {
                    const retenue = configure[cle] === colonne ? ' selected' : '';
                    const valeur = Utils.escapeHtml(colonne);
                    return `<option value="${valeur}"${retenue}>${valeur}</option>`;
                })].join('');

            return `
                <div class="import-fichier" data-fichier="${Utils.escapeHtml(nom)}">
                    <h3>${Utils.escapeHtml(I18n.t(`workspace.import_${nom}`))}</h3>
                    <p class="text-muted">${Utils.escapeHtml(I18n.t(
                        'workspace.inspect_columns',
                        {colonnes: vu.colonnes.join(', ')}))}</p>
                    <div class="form-group">
                        <label for="import-${nom}-separateur" class="form-label">${
                            Utils.escapeHtml(I18n.t('workspace.import_separator'))}</label>
                        <input type="text" class="form-input" id="import-${nom}-separateur"
                               value="${Utils.escapeHtml(vu.separateur)}" maxlength="1">
                    </div>
                    <div class="form-group">
                        <label for="import-${nom}-encodage" class="form-label">${
                            Utils.escapeHtml(I18n.t('workspace.import_encoding'))}</label>
                        <input type="text" class="form-input" id="import-${nom}-encodage"
                               value="${Utils.escapeHtml(vu.encodage)}">
                    </div>
                    ${this.clesDuFichier(nom).map(cle => `
                        <div class="form-group">
                            <label for="import-${nom}-${cle}" class="form-label">${
                                Utils.escapeHtml(I18n.t(`form.${cle}.label`))}</label>
                            <select class="form-input" id="import-${nom}-${cle}"
                                    data-cle="${cle}">${options(cle)}</select>
                        </div>
                    `).join('')}
                    <table class="import-apercu">
                        <caption>${Utils.escapeHtml(I18n.t('workspace.inspect_preview'))}</caption>
                        <thead><tr>${vu.colonnes.map(colonne =>
                            `<th scope="col">${Utils.escapeHtml(colonne)}</th>`).join('')}</tr></thead>
                        <tbody>${vu.apercu.map(ligne =>
                            `<tr>${ligne.map(valeur =>
                                `<td>${Utils.escapeHtml(valeur)}</td>`).join('')}</tr>`).join('')}</tbody>
                    </table>
                </div>
            `;
        }).join('');
        zone.hidden = false;
    },

    /** La correspondance telle que la personne l'a laissée à l'écran. */
    correspondanceDeclaree() {
        const declaree = {};
        document.querySelectorAll('#import-correspondance .import-fichier')
            .forEach(bloc => {
                const nom = bloc.dataset.fichier;
                const declaration = {
                    separateur: document.getElementById(`import-${nom}-separateur`).value,
                    encodage: document.getElementById(`import-${nom}-encodage`).value,
                };
                this.clesDuFichier(nom).forEach(cle => {
                    declaration[cle] = document.getElementById(`import-${nom}-${cle}`).value;
                });
                declaree[nom] = declaration;
            });
        return declaree;
    },

    /**
     * Effectue l'import
     */
    async doImport() {
        const workspaceId = document.getElementById('import-workspace-id').value;
        const formData = new FormData();
        const choisis = this.fichiersChoisis();

        Object.entries(choisis).forEach(([nom, fichier]) => {
            formData.append(nom, fichier);
        });

        if (!Object.keys(choisis).length) {
            Toast.warning(I18n.t('common.warning'),
                          I18n.t('workspace.import_select_file'));
            return;
        }

        // La correspondance ne part que si la personne a vu ce qu'elle
        // déclarait. Sans inspection préalable, l'import se comporte comme
        // avant : on ajoute une possibilité, on n'impose pas une étape.
        const declaree = this.correspondanceDeclaree();
        if (Object.keys(declaree).length) {
            formData.append('correspondance', JSON.stringify(declaree));
        }

        try {
            // L'appel passait par `fetch` sans en-tête d'authentification :
            // l'authentification étant active par défaut, l'import répondait
            // 401 et le bouton paraissait sans effet.
            const response = await fetch(
                `${Config.API_URL}/workspaces/${workspaceId}/import-data`, {
                    method: 'POST',
                    headers: typeof Auth !== 'undefined' ? Auth.getAuthHeaders() : {},
                    body: formData,
                });

            if (!response.ok) {
                // Le serveur nomme la cause — chemin hors périmètre, fichier
                // trop volumineux — et la perdre affichait « Erreur import »
                // pour trois refus différents.
                throw new Error(await WorkspacesPage.messageDErreur(response));
            }

            Toast.success(I18n.t('workspace.import_done'),
                          I18n.t('workspace.import_done_detail'));
            this.closeImportModal();
            await this.loadWorkspaces();

        } catch (error) {
            Toast.error(I18n.t('common.error'), error.message);
        }
    },

    /** Message d'un refus du serveur, traduit depuis son code. */
    async messageDErreur(response) {
        try {
            const charge = await response.json();
            const detail = charge && charge.detail;
            if (detail && typeof detail === 'object' && detail.code) {
                return I18n.t(detail.code, detail.params || {});
            }
            if (typeof detail === 'string' && detail) return detail;
        } catch (erreur) {
            // Réponse non JSON : on retombe sur le code HTTP.
        }
        return I18n.t('error.http_status', { status: response.status });
    },
    
    /**
     * Exporte un workspace
     */
    async exportWorkspace(workspaceId) {
        try {
            Toast.info(I18n.t('workspace.export'),
                       I18n.t('workspace.export_preparing'));

            const response = await fetch(
                `${Config.API_URL}/workspaces/${workspaceId}/export`, {
                    method: 'POST',
                    headers: typeof Auth !== 'undefined' ? Auth.getAuthHeaders() : {},
                });

            if (!response.ok) {
                throw new Error(await WorkspacesPage.messageDErreur(response));
            }
            
            // Le nom du fichier est celui que le serveur annonce.
            await Utils.enregistrerReponse(
                response, `${workspaceId}_export.zip`);

            Toast.success(I18n.t('workspace.export_done'),
                          I18n.t('workspace.export_downloaded'));

        } catch (error) {
            Toast.error(I18n.t('common.error'), error.message);
        }
    },
    
    /**
     * Supprime un workspace
     */
    async deleteWorkspace(workspaceId) {
        if (typeof WorkspaceManager !== 'undefined') {
            await WorkspaceManager.deleteWorkspace(workspaceId);
            await this.loadWorkspaces();
        }
    },
    
    // === HELPERS ===
    //
    // Ces fonctions existaient ici en double : un `escapeHtml` identique à
    // celui de `Utils`, un `formatNumber` qui abrégeait en « 1.2K », et deux
    // formats de date qui imposaient `fr-FR` quelle que soit la langue
    // choisie — avec « N/A » et « jamais » écrits en français dans le code.

    formatDate(dateStr) {
        if (!dateStr) return I18n.t('common.not_provided');
        return I18n.formatDate(dateStr, { day: '2-digit', month: '2-digit', year: 'numeric' });
    },

    formatRelativeDate(dateStr) {
        if (!dateStr) return I18n.t('workspace.never_accessed');
        return I18n.formatRelativeDate(dateStr);
    },
};

// Export global
window.WorkspacesPage = WorkspacesPage;
