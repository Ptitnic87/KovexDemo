/**
 * PyGIA Frontend - Roles Pages (Catalog + Composer) - CORRIGÉ SPRINT 0.1
 * 
 * FIX: API.getRoles() retourne {roles: [...], total: X}
 *      Mais le code s'attendait à recevoir directement l'array
 * 
 * CORRECTION: Extraire .roles de la réponse
 */

const RolesPage = {
    allRoles: [],
    selectedRoles: new Set(),
    
    // État pour les droits unitaires
    allUnitRights: [],
    selectedUnitRights: new Set(),
    
    // La revue du modèle, indexée par rôle. Elle arrive après le catalogue :
    // le catalogue s'affiche sans l'attendre, et la revue vient s'y poser.
    revue: null,
    revueParRole: {},
    constatsParRole: {},
    propositionsParRole: {},

    // Les règles de séparation qu'enfreint chaque rôle validé. `null` tant
    // qu'on n'a pas pu lire : l'absence de marque dirait « aucun conflit », et
    // c'est le seul mensonge que cet écran puisse produire.
    conflitsParRole: null,

    //: Délai avant que le compositeur confronte sa composition aux règles.
    //: La même valeur que les recherches de l'écran : c'est le temps au-delà
    //: duquel une frappe ne fait plus partie du même geste.
    DELAI_DE_CONTROLE: 300,

    currentFilter: 'all',
    rolesSearchValue: '', // Stocke la valeur de recherche des rôles applicatifs
    unitRightsSearchValue: '', // Stocke la valeur de recherche des droits unitaires

    init() {
        this.bindEvents();
    },

    /** Réaffiche les cartes et les listes déjà rendues, dans la langue courante. */
    rafraichirLangue() {
        this.renderRevue();
        this.renderCatalog();
        this.renderComposerRoles();
        this.renderUnitRightsSelector();
        this.updateComposerStats();
    },

    bindEvents() {
        // Filter tabs (pour le catalogue)
        document.querySelectorAll('.filter-tab').forEach(tab => {
            tab.addEventListener('click', (e) => {
                document.querySelectorAll('.filter-tab').forEach(t => t.classList.remove('active'));
                e.target.classList.add('active');
                this.currentFilter = e.target.dataset.filter;
                this.renderCatalog();
            });
        });

        // Roles search (pour le catalogue)
        const searchInput = document.getElementById('roles-search');
        if (searchInput) {
            searchInput.addEventListener('input', Utils.debounce(() => {
                this.renderCatalog();
            }, 300));
        }
        
        // Recherche de rôles dans le Composer
        const composerRolesSearch = document.getElementById('search-app-roles');
        if (composerRolesSearch) {
            composerRolesSearch.addEventListener('input', Utils.debounce((e) => {
                this.rolesSearchValue = e.target.value.toLowerCase();
                this.renderComposerRoles();
            }, 300));
        }

        // Recherche de droits unitaires dans le Composer
        const composerUnitRightsSearch = document.getElementById('search-unit-rights');
        if (composerUnitRightsSearch) {
            composerUnitRightsSearch.addEventListener('input', Utils.debounce((e) => {
                this.unitRightsSearchValue = e.target.value.toLowerCase();
                this.renderUnitRightsSelector();
            }, 300));
        }

        // Composer extra rights (exceptions manuelles)
        const extraRightsInput = document.getElementById('composer-extra-rights');
        if (extraRightsInput) {
            extraRightsInput.addEventListener('input', () => this.updateComposerStats());
        }

        // Les cartes du catalogue sont réécrites à chaque rendu : le clic est
        // écouté sur le conteneur, qui, lui, ne disparaît pas.
        const catalogue = document.getElementById('roles-catalog-container');
        if (catalogue) {
            catalogue.addEventListener('click', (evenement) => {
                const applique = evenement.target.closest('.revue-appliquer');
                if (applique) {
                    this.appliquerLaProposition(applique);
                    return;
                }
                const ancrage = evenement.target.closest('[data-ancrer]');
                if (ancrage) {
                    this.ancrerLeRole(ancrage.dataset.ancrer, ancrage);
                    return;
                }
                const detail = evenement.target.closest('.role-detail');
                if (detail) this.ouvrirLeDetail(detail.dataset.roleId);
            });
        }

        // La fenêtre de détail est réécrite à chaque rendu : ses boutons sont
        // écoutés sur la fenêtre, qui, elle, reste en place.
        const detail = document.getElementById('role-detail-modal');
        if (detail) {
            detail.addEventListener('click', (evenement) => {
                const bouton = evenement.target.closest('button');
                if (!bouton) return;
                if (bouton.dataset.ancrer) {
                    // La fenêtre se referme : le catalogue derrière elle se
                    // relit, et le rôle y passe des « non comparés » aux
                    // « comparés ». La laisser ouverte afficherait encore
                    // l'invitation à poser une référence déjà posée.
                    Modal.close();
                    this.ancrerLeRole(bouton.dataset.ancrer, bouton);
                    return;
                }
                if (bouton.id === 'role-detail-ia') this.proposerUnNom();
                if (bouton.id === 'role-detail-renommer') this.renommerLeRole();
                if (bouton.id === 'role-detail-devalider') this.devaliderLeRole();
                if (bouton.id === 'role-proches-calculer') this.chercherLesAccesProches();
                if (bouton.dataset.prochesDroit) {
                    this.montrerLaPopulation(bouton.dataset.prochesDroit,
                                             bouton.dataset.prochesPopulation);
                }
            });
        }

        // Create business role
        const createBtn = document.getElementById('create-business-role');
        if (createBtn) {
            createBtn.addEventListener('click', () => this.createBusinessRole());
        }
    },

    async loadCatalog() {
        const container = document.getElementById('roles-catalog-container');
        if (!container) return;

        container.innerHTML = `
            <div class="empty-state">
                <div class="loading-spinner"></div>
                <span>${I18n.t('common.loading')}</span>
            </div>
        `;

        try {
            // 🔧 FIX: Extraire .roles de la réponse API
            const response = await API.getRoles();
            
            // Backend retourne {roles: [...], total: X}
            if (response && response.roles) {
                this.allRoles = response.roles;
            } else if (Array.isArray(response)) {
                // Fallback si l'API change et retourne directement un array
                this.allRoles = response;
            } else {
                this.allRoles = [];
            }
            
            this.renderCatalog();
            await this.chargerLaRevue();
            await this.chargerLaSeparation();
        } catch (error) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon"><i class="fas fa-exclamation-triangle" aria-hidden="true"></i></div>
                    <h2>${I18n.t('error.load_failed')}</h2>
                    <p>${I18n.t('roles.load_error')}</p>
                </div>
            `;
        }
    },

    /**
     * La revue du modèle : ce que le catalogue est devenu depuis sa validation.
     *
     * Elle est chargée **après** le catalogue et son échec n'emporte pas
     * l'écran : un rôle validé reste consultable même si la comparaison avec
     * les chiffres du jour de la décision n'a pas pu être faite. La revue est
     * une lecture, pas une condition d'affichage.
     */
    async chargerLaRevue() {
        try {
            this.revue = await API.get('/kb/revue');
        } catch (error) {
            this.revue = null;
        }
        this.indexerLaRevue();
        this.renderRevue();
        this.renderCatalog();
    },

    /**
     * Les rôles du catalogue qui enfreignent une règle de séparation.
     *
     * Chargée **après** le catalogue et son échec n'emporte pas l'écran : un
     * rôle validé reste consultable même si le contrôle n'a pas pu être fait.
     *
     * En revanche l'échec se dit. Une marque absente se lit « ce rôle ne pose
     * pas de problème » ; si personne n'a regardé, l'écran doit le dire, sans
     * quoi il rassure sur un contrôle qui n'a pas eu lieu.
     */
    async chargerLaSeparation() {
        try {
            const rendu = await API.lesRolesEnConflit();
            this.conflitsParRole = rendu.roles || {};
        } catch (error) {
            this.conflitsParRole = null;
        }
        this.renderRevue();
        this.renderCatalog();
    },

    /** Range la revue par rôle : les cartes la lisent, elles ne la cherchent pas. */
    indexerLaRevue() {
        this.revueParRole = {};
        this.constatsParRole = {};
        this.propositionsParRole = {};
        const revue = this.revue || {};
        (revue.roles || []).forEach(entree => {
            this.revueParRole[entree.role_id] = entree;
        });
        (revue.constats || []).forEach(constat => {
            const liste = this.constatsParRole[constat.role_id] || [];
            liste.push(constat);
            this.constatsParRole[constat.role_id] = liste;
        });
        (revue.propositions || []).forEach(proposition => {
            const liste = this.propositionsParRole[proposition.role_id] || [];
            liste.push(proposition);
            this.propositionsParRole[proposition.role_id] = liste;
        });
    },

    /**
     * La phrase d'un constat, avec ses deux chiffres.
     *
     * `avant` et `apres` sont passés ensemble à la traduction : un constat qui
     * dirait « la population a baissé » sans dire de combien à combien n'est
     * pas actionnable — c'est le reproche que ce produit fait aux outils du
     * marché, il ne va pas le reproduire ici.
     */
    phraseDeConstat(constat) {
        const parametres = {};
        Object.entries(constat.parametres || {}).forEach(([cle, valeur]) => {
            parametres[cle] = Utils.escapeHtml(String(Utils.valeurDansLaLangue(valeur)));
        });
        ['avant', 'apres'].forEach(cle => {
            if (constat[cle] !== null && constat[cle] !== undefined) {
                parametres[cle] = Utils.escapeHtml(String(Utils.valeurDansLaLangue(constat[cle])));
            }
        });
        return I18n.t(constat.code, parametres);
    },

    /**
     * La phrase d'une proposition, avec les deux chiffres de ce qu'elle change.
     *
     * Proposer de restreindre un rôle sans dire ce que le sur-octroi
     * deviendrait, c'est demander une décision à l'aveugle.
     */
    phraseDeProposition(proposition) {
        const parametres = {};
        Object.entries(proposition.parametres || {}).forEach(([cle, valeur]) => {
            parametres[cle] = Utils.escapeHtml(String(Utils.valeurDansLaLangue(valeur)));
        });
        ['avant', 'apres'].forEach(cle => {
            if (proposition[cle] !== null && proposition[cle] !== undefined) {
                parametres[cle] = Utils.escapeHtml(String(Utils.valeurDansLaLangue(proposition[cle])));
            }
        });
        return I18n.t(proposition.code, parametres);
    },

    /**
     * Le bloc d'une proposition : ce qu'elle ferait, sur quoi, et le geste.
     *
     * Le bouton n'apparaît que là où le produit sait appliquer. Faire
     * disparaître un rôle déjà provisionné chez le client se décide ailleurs :
     * la proposition est alors rendue et expliquée, sans bouton.
     */
    rendreLaProposition(proposition, rang) {
        const identifiant = `revue-proposition-${Utils.escapeHtml(proposition.role_id)}-${rang}`;
        const droits = (proposition.droits || [])
            .map(droit => Utils.escapeHtml(String(droit)));
        return `
            <li class="revue-proposition">
                <p id="${identifiant}">${this.phraseDeProposition(proposition)}</p>
                ${droits.length ? `
                    <p class="revue-proposition-droits">${Utils.escapeHtml(
                        I18n.t('revue.proposition.droits_concernes',
                               {droits: droits.join(', ')}))}</p>
                ` : ''}
                ${proposition.type === 'restreindre' ? `
                    <p class="revue-proposition-contrepartie">${Utils.escapeHtml(
                        I18n.t('revue.proposition.restreindre_contrepartie'))}</p>
                ` : ''}
                ${proposition.applicable ? `
                    <button type="button" class="btn btn-sm btn-secondary revue-appliquer"
                            data-empreinte="${Utils.escapeHtml(proposition.empreinte)}"
                            aria-describedby="${identifiant}">
                        ${Utils.escapeHtml(I18n.t('revue.proposition.appliquer'))}
                    </button>
                ` : `
                    <p class="revue-proposition-manuel">${Utils.escapeHtml(
                        I18n.t('revue.proposition.geste_manuel'))}</p>
                `}
            </li>
        `;
    },

    /**
     * Appliquer une proposition : le geste humain, et lui seul.
     *
     * Le client n'envoie que l'empreinte de ce qu'il a vu. Le serveur recalcule
     * la revue et n'applique que s'il retrouve la même proposition : une charge
     * forgée ne peut pas faire modifier un rôle validé par une route d'analyse.
     */
    async appliquerLaProposition(bouton) {
        const empreinte = bouton.dataset.empreinte;
        if (!empreinte || bouton.disabled) return;
        bouton.disabled = true;
        try {
            const reponse = await API.post('/kb/revue/appliquer', {empreinte});
            Toast.success(I18n.t('common.success'),
                          I18n.t('revue.proposition.appliquee',
                                 {version: reponse?.version ?? ''}));
            // Le catalogue **et** la revue : le rôle a changé, donc ce que la
            // revue en dit aussi. Réafficher l'un sans l'autre laisserait à
            // l'écran une proposition qui n'existe plus.
            await this.loadCatalog();
        } catch (erreur) {
            bouton.disabled = false;
            Toast.error(I18n.t('common.error'), erreur.message);
        }
    },

    /**
     * La note qui dit que le contrôle de séparation n'a pas pu être lu.
     *
     * Elle est distincte du bandeau de revue et ne dépend pas de lui : le
     * bandeau se cache quand aucun rôle n'a été validé, et l'échec du contrôle
     * doit se dire dans tous les cas où il se produit.
     */
    renderLaNoteDeSeparation() {
        const note = document.getElementById('catalogue-separation-note');
        if (!note) return;
        const muet = this.conflitsParRole === null && this.allRoles.length > 0;
        note.hidden = !muet;
        note.textContent = muet ? I18n.t('separation.catalogue_illisible') : '';
    },

    /** Le bandeau de tête : combien d'écarts, sur combien de rôles. */
    renderRevue() {
        this.renderLaNoteDeSeparation();
        const bandeau = document.getElementById('revue-modele');
        const resume = document.getElementById('revue-modele-resume');
        if (!bandeau || !resume) return;

        const stats = (this.revue || {}).stats || {};
        // Rien à revoir tant qu'aucun rôle n'a été validé : le bandeau
        // n'apprendrait rien et prendrait la place du catalogue.
        if (!stats.roles_examines) {
            bandeau.hidden = true;
            resume.textContent = '';
            return;
        }
        bandeau.hidden = false;
        resume.textContent = stats.constats
            ? I18n.t('revue.resume', {constats: stats.constats,
                                      roles: stats.roles_avec_constat,
                                      total: stats.roles_examines})
            : I18n.t('revue.aucun_constat');
    },

    renderCatalog() {
        const container = document.getElementById('roles-catalog-container');
        const searchValue = document.getElementById('roles-search')?.value?.toLowerCase() || '';
        
        if (!container) return;

        let filteredRoles = this.allRoles;

        // Apply type filter
        if (this.currentFilter !== 'all') {
            filteredRoles = filteredRoles.filter(r => r.role_type === this.currentFilter);
        }

        // Apply search filter
        if (searchValue) {
            filteredRoles = filteredRoles.filter(r => 
                r.name.toLowerCase().includes(searchValue) ||
                r.description?.toLowerCase().includes(searchValue)
            );
        }

        if (filteredRoles.length === 0) {
            const emptyMessage = this.allRoles.length === 0 
                ? I18n.t('roles.start_mining')
                : I18n.t('roles.no_match');
                
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon"><i class="fas fa-layer-group" aria-hidden="true"></i></div>
                    <h2>${I18n.t('roles.no_roles')}</h2>
                    <p>${emptyMessage}</p>
                </div>
            `;
            return;
        }

        container.innerHTML = filteredRoles.map(role => {
            // Le catalogue et le mining désignent les mêmes objets : ils
            // portent désormais la même pastille, donc la même couleur.
            // Le socle est un troisième type : il ne sort d'aucun mining, il
            // vient de la décision de détection. Le peindre comme un rôle
            // applicatif laisserait croire qu'il a été proposé puis validé.
            const socle = role.is_socle === true;
            const metier = role.role_type === 'METIER';
            const typeClass = socle ? 'badge-role-socle'
                : (metier ? 'badge-role-biz' : 'badge-role-app');
            const typeName = socle ? I18n.t('role.type.socle')
                : (metier ? I18n.t('role.type.business')
                          : I18n.t('role.type.application'));
            
            // Ce que la revue dit de ce rôle. La carte la lit ; elle ne la
            // calcule pas, et elle ne corrige rien : un rôle validé a peut-être
            // déjà été provisionné dans l'IGA du client.
            const constats = this.constatsParRole[role.id] || [];
            const propositions = this.propositionsParRole[role.id] || [];
            const entree = this.revueParRole[role.id];
            const derive = constats.length > 0;
            // Un rôle validé qui enfreint une règle de séparation donne le
            // conflit à quiconque le reçoit, y compris à ceux qui ne l'ont pas
            // encore : le corriger corrige tous ses porteurs d'un coup. C'est
            // le constat le plus lourd qu'une carte puisse porter.
            const separation = this.rendreLaSeparation(role);
            const version = entree?.version || 1;
            const revue = (derive || (entree && !entree.compare)) ? `
                    <div class="role-card-revue">
                        ${version > 1 ? `
                            <p class="revue-version">${Utils.escapeHtml(
                                I18n.t('revue.version', {version}))}</p>
                        ` : ''}
                        ${derive ? `
                            <p class="revue-pastille">
                                <i class="fas fa-triangle-exclamation" aria-hidden="true"></i>
                                ${Utils.escapeHtml(I18n.t('revue.derive'))}
                            </p>
                            <ul class="revue-constats">
                                ${constats.map(constat =>
                                    `<li>${this.phraseDeConstat(constat)}</li>`).join('')}
                            </ul>
                        ` : ''}
                        ${propositions.length ? `
                            <ul class="revue-propositions">
                                ${propositions.map((proposition, rang) =>
                                    this.rendreLaProposition(proposition, rang)).join('')}
                            </ul>
                        ` : ''}
                        ${entree && !entree.compare && !socle ? `
                            <p class="revue-note">${Utils.escapeHtml(
                                I18n.t('revue.sans_reference'))}</p>
                            <button type="button" class="btn btn-sm btn-secondary"
                                    data-ancrer="${Utils.escapeHtml(role.id)}">
                                ${Utils.escapeHtml(I18n.t('role.anchor'))}
                            </button>
                        ` : ''}
                    </div>
            ` : '';

            return `
                <div class="role-card${derive ? ' role-card--derive' : ''}${
                    separation ? ' role-card--conflit' : ''}">
                    <div class="role-card-header">
                        <span class="badge ${typeClass}">${Utils.escapeHtml(typeName)}</span>
                        <span class="role-card-users">
                            <i class="fas fa-users" aria-hidden="true"></i>
                            ${role.user_count_potential || role.user_count || 0}
                        </span>
                    </div>
                    <h3 class="role-card-title">${Utils.escapeHtml(
                        role.name || I18n.t('role.socle.default_name'))}</h3>
                    <p class="role-card-desc">${Utils.escapeHtml(
                        socle
                            ? I18n.t('role.socle.description', {seuil: role.threshold})
                            : (role.description || I18n.t('common.no_description')))}</p>
                    <div class="role-card-actions">
                        <button type="button" class="btn btn-sm btn-secondary role-detail"
                                data-role-id="${Utils.escapeHtml(role.id)}">
                            ${Utils.escapeHtml(I18n.t('role.detail.open'))}
                        </button>
                    </div>
                    <div class="role-card-footer">
                        <span class="role-card-stat">
                            <strong>${role.rights?.length || 0}</strong> ${I18n.t('common.rights')}
                        </span>
                        ${role.sub_roles?.length > 0 ? `
                            <span class="role-card-stat">
                                <strong>${role.sub_roles.length}</strong> ${I18n.t('role.sub_roles')}
                            </span>
                        ` : ''}
                    </div>
                    ${separation}
                    ${revue}
                </div>
            `;
        }).join('');
    },

    /**
     * Ce que ce rôle enfreint, s'il enfreint quelque chose.
     *
     * Les règles sont **nommées**, et pas seulement comptées : « ce rôle
     * enfreint deux règles » n'aide personne à décider, là où « il réunit la
     * saisie et la validation d'un paiement » se traite.
     *
     * Rien n'est rendu tant que le contrôle n'a pas été lu — `conflitsParRole`
     * vaut alors `null`, et la note de tête dit pourquoi l'écran se tait.
     */
    rendreLaSeparation(role) {
        const enfreintes = (this.conflitsParRole || {})[role.id] || [];
        if (!enfreintes.length) return '';
        return `
            <div class="role-card-sod">
                <p class="role-card-sod-titre">
                    <i class="fas fa-scale-balanced" aria-hidden="true"></i>
                    ${Utils.escapeHtml(I18n.t('separation.role_flagged',
                                              {count: enfreintes.length}))}
                </p>
                <ul class="role-card-sod-regles">
                    ${enfreintes.map((enfreinte) => `
                        <li>${Utils.escapeHtml(I18n.t('separation.role_flagged_rule', {
                            regle: enfreinte.libelle,
                            gauche: enfreinte.gauche.join(', '),
                            droite: enfreinte.droite.join(', ')}))}</li>
                    `).join('')}
                </ul>
            </div>
        `;
    },

    // === DÉTAIL D'UN RÔLE VALIDÉ ===
    //
    // Le catalogue n'affichait qu'un nom et deux compteurs. Décider de garder,
    // de corriger ou de retirer un rôle demandait d'ouvrir à la main le fichier
    // de la base de connaissance — c'est-à-dire de sortir de l'outil pour
    // prendre une décision de gouvernance.

    /** Rôle ouvert dans la fenêtre de détail, et ce que le serveur en dit. */
    detail: null,

    async ouvrirLeDetail(roleId) {
        if (!roleId) return;
        const contenu = document.getElementById('role-detail-content');
        if (!contenu) return;

        contenu.innerHTML = `<div class="empty-state mini">
                <div class="loading-spinner"></div>
                <span>${Utils.escapeHtml(I18n.t('common.loading'))}</span>
            </div>`;
        Modal.open('role-detail-modal');
        this.detail = {roleId};
        this.effacerLesAccesProches();
        this.chargerLesPorteurs(roleId);
        await this.chargerLeDetail();
    },

    async chargerLeDetail() {
        const etat = this.detail;
        const contenu = document.getElementById('role-detail-content');
        if (!etat || !contenu) return;
        try {
            // La liste des porteurs ne passe plus par ici : le tableau la
            // demande lui-même, page par page. Ne restent que les mesures, les
            // droits et l'historique.
            const detail = await API.get(
                `/kb/validated-roles/${encodeURIComponent(etat.roleId)}/detail`);
            etat.donnees = detail;
            this.rendreLeDetail();
        } catch (erreur) {
            contenu.innerHTML = `<div class="empty-state mini">
                    <p>${Utils.escapeHtml(I18n.t('role.detail.load_error'))}</p>
                    <p class="text-muted">${Utils.escapeHtml(erreur.message)}</p>
                </div>`;
        }
    },

    rendreLeDetail() {
        const etat = this.detail;
        const contenu = document.getElementById('role-detail-content');
        if (!etat || !etat.donnees || !contenu) return;

        const suite = document.getElementById('role-detail-suite');
        const {role, mesures, droits, versions} = etat.donnees;
        const socle = role.is_socle === true;
        // Ce que la revue sait de ce rôle : elle est chargée avec le
        // catalogue, d'où cette fenêtre s'ouvre. Un rôle sans point de
        // comparaison peut en recevoir un ici même — c'est l'endroit où l'on
        // constate le manque.
        const revue = this.revueParRole[etat.roleId];
        const sansReference = !socle && revue !== undefined && !revue.compare;
        const nom = role.name || (socle ? I18n.t('role.socle.default_name') : '');
        const titre = document.getElementById('role-detail-modal-title');
        if (titre) {
            titre.textContent = role.version > 1
                ? `${nom} — ${I18n.t('revue.version', {version: role.version})}`
                : nom;
        }
        // Le socle ne se sort pas du catalogue : il disparaît en effaçant la
        // détection qui le produit. Un bouton qui ne peut pas aboutir est
        // pire qu'un bouton absent.
        const sortir = document.getElementById('role-detail-devalider');
        if (sortir) sortir.hidden = socle;
        // Le socle est détenu par tous : ses « accès proches » seraient ceux
        // de toute la population, et la question d'y faire entrer un accès ne
        // se pose pas — le socle se règle par sa détection.
        const proches = document.getElementById('role-proches');
        if (proches) proches.hidden = socle;

        contenu.innerHTML = `
            <div class="role-detail-mesures">
                ${[['stats.users', mesures.user_count],
                   ['common.rights', mesures.right_count],
                   ['stats.over_granted', mesures.over_granted],
                   ['role.detail.adherence_pct', I18n.t('unit.percent', { value: Utils.valeurDansLaLangue(mesures.fit_pct) })]].map(([cle, valeur]) => `
                    <div class="role-detail-mesure">
                        <strong>${Utils.escapeHtml(String(Utils.valeurDansLaLangue(valeur)))}</strong>
                        <span>${Utils.escapeHtml(I18n.t(cle))}</span>
                    </div>
                `).join('')}
            </div>

            <h3>${Utils.escapeHtml(I18n.t('role.detail.rights'))}</h3>
            <table class="role-detail-table">
                <thead><tr>
                    <th scope="col">${Utils.escapeHtml(I18n.t('common.rights'))}</th>
                    <th scope="col">${Utils.escapeHtml(I18n.t('role.detail.adherence'))}</th>
                    <th scope="col">${Utils.escapeHtml(I18n.t('role.detail.adherence_pct'))}</th>
                </tr></thead>
                <tbody>${droits.map(entree => `
                    <tr>
                        <td>${Utils.escapeHtml(entree.droit)}</td>
                        <td>${Utils.escapeHtml(String(Utils.valeurDansLaLangue(entree.detenteurs)))}</td>
                        <td>${Utils.escapeHtml(I18n.t('unit.percent', { value: Utils.valeurDansLaLangue(entree.adherence_pct) }))}</td>
                    </tr>
                `).join('')}</tbody>
            </table>

        `;

        // Le tableau des porteurs s'intercale ici, dans le gabarit. Ce qui
        // suit est écrit après lui.
        if (!suite) return;
        suite.innerHTML = `
            ${socle ? '' : `
            <h3>${Utils.escapeHtml(I18n.t('role.detail.versions'))}</h3>
            ${versions.length ? `
                <ul class="role-detail-versions">${versions.map(entree => `
                    <li>${Utils.escapeHtml(I18n.t('role.detail.version_line', {
                        version: entree.version,
                        date: RolesPage.dateLisible(entree.remplacee_le),
                        droits: entree.droits,
                    }))}${entree.constat
                        ? ` — ${Utils.escapeHtml(I18n.t(entree.constat))}` : ''}</li>
                `).join('')}</ul>
            ` : `<p class="text-muted">${Utils.escapeHtml(
                    I18n.t('role.detail.no_version'))}</p>`}
            `}

            ${sansReference ? `
                <h3>${Utils.escapeHtml(I18n.t('revue.sans_reference'))}</h3>
                <p class="form-hint">${Utils.escapeHtml(
                    I18n.t('role.anchor.explain'))}</p>
                <div class="role-detail-actions">
                    <button type="button" class="btn btn-sm btn-secondary"
                            data-ancrer="${Utils.escapeHtml(role.id)}">
                        ${Utils.escapeHtml(I18n.t('role.anchor'))}
                    </button>
                </div>
            ` : ''}

            ${socle ? `
                <p class="form-hint">${Utils.escapeHtml(
                    I18n.t('role.socle.no_rename'))}</p>
            ` : `
            <h3>${Utils.escapeHtml(I18n.t('role.detail.rename'))}</h3>
            <div class="form-group">
                <label class="form-label" for="role-detail-nom">${
                    Utils.escapeHtml(I18n.t('form.role_name.label'))}</label>
                <input type="text" class="form-input" id="role-detail-nom"
                       value="${Utils.escapeHtml(role.name || '')}">
            </div>
            <div class="form-group">
                <label class="form-label" for="role-detail-description">${
                    Utils.escapeHtml(I18n.t('form.description.label'))}</label>
                <input type="text" class="form-input" id="role-detail-description"
                       value="${Utils.escapeHtml(role.description || '')}">
            </div>
            <div class="role-detail-actions">
                <button type="button" class="btn btn-sm btn-secondary" id="role-detail-ia">
                    ${Utils.escapeHtml(I18n.t('role.rename.suggest'))}
                </button>
                <button type="button" class="btn btn-sm btn-primary" id="role-detail-renommer">
                    ${Utils.escapeHtml(I18n.t('action.save'))}
                </button>
            </div>
            `}
        `;
    },

    /**
     * Retient les mesures du jour comme point de comparaison du rôle.
     *
     * Un rôle composé à la main n'est passé par aucune validation de candidat :
     * rien n'a été mesuré à sa création. La revue le disait — « ce rôle n'a pas
     * de point de comparaison » — et s'arrêtait là. Le produit mesurait le rôle
     * chaque jour sans jamais pouvoir dire s'il avait bougé : une impasse.
     *
     * Le geste ne modifie pas le rôle et ne juge rien. Il écrit les chiffres
     * d'aujourd'hui pour que ceux de demain puissent s'y comparer.
     */
    async ancrerLeRole(roleId, bouton) {
        if (!roleId) return;
        if (bouton) bouton.disabled = true;
        try {
            const reponse = await API.post(
                `/kb/validated-roles/${encodeURIComponent(roleId)}/ancrer`, {});
            const mesures = reponse.mesures || {};
            Toast.success(I18n.t('common.success'), I18n.t('role.anchor.done', {
                porteurs: Utils.formatNumber(mesures.user_count || 0),
                droits: Utils.formatNumber(mesures.right_count || 0),
                sur_octroi: Utils.formatNumber(mesures.over_granted || 0),
            }));
            // La revue se relit entièrement : le rôle change de camp, il passe
            // des « non comparés » aux « comparés », et le compte de l'écran
            // suit.
            await this.loadCatalog();
        } catch (erreur) {
            if (bouton) bouton.disabled = false;
            Toast.error(I18n.t('common.error'),
                        erreur.message || I18n.t('role.anchor.failed'));
        }
    },

    /** Une date d'historique, dans la langue de l'utilisateur. */
    dateLisible(iso) {
        if (!iso) return '';
        const date = new Date(iso);
        return Number.isNaN(date.getTime())
            ? String(iso)
            : date.toLocaleDateString(I18n.currentLocale || undefined);
    },

    /**
     * Oublie les accès proches du rôle précédent.
     *
     * La fenêtre sert à tous les rôles : sans cela, les voisins d'un rôle
     * s'afficheraient sous le nom du suivant.
     */
    effacerLesAccesProches() {
        const resume = document.getElementById('role-proches-resume');
        if (resume) { resume.hidden = true; resume.textContent = ''; }
        const resultats = document.getElementById('role-proches-resultats');
        if (resultats) resultats.innerHTML = '';
        const population = document.getElementById('role-proches-population');
        if (population) population.hidden = true;
    },

    /**
     * Les accès hors du rôle les plus proches de sa population.
     *
     * Rien n'est calculé tant que la ressemblance minimale et le nombre
     * d'accès ne sont pas saisis : le produit ne décide pas à partir de quand
     * deux populations se ressemblent.
     */
    async chercherLesAccesProches() {
        const etat = this.detail;
        if (!etat) return;
        const jaccard = parseFloat(document.getElementById('role-proches-jaccard')?.value);
        const limite = parseInt(document.getElementById('role-proches-limite')?.value, 10);
        const resume = document.getElementById('role-proches-resume');
        const resultats = document.getElementById('role-proches-resultats');
        if (!Number.isFinite(jaccard) || jaccard < 0 || jaccard > 1
            || !Number.isFinite(limite) || limite < 1) {
            Toast.error(I18n.t('common.error'), I18n.t('role.proches.saisie_requise'));
            return;
        }
        this.effacerLesAccesProches();
        try {
            const reponse = await API.get(
                `/kb/validated-roles/${encodeURIComponent(etat.roleId)}/acces-proches`,
                {jaccard_min: jaccard, limite});
            etat.proches = reponse;
            if (resume) {
                resume.hidden = false;
                resume.textContent = reponse.acces.length
                    ? I18n.t('role.proches.resume', {
                        montres: Utils.formatNumber(reponse.acces.length),
                        candidats: Utils.formatNumber(reponse.candidats),
                        sous_le_seuil: Utils.formatNumber(reponse.sous_le_seuil),
                        au_dela: Utils.formatNumber(reponse.au_dela_de_la_limite),
                    })
                    : I18n.t('role.proches.aucun', {
                        candidats: Utils.formatNumber(reponse.candidats)});
            }
            if (resultats && reponse.acces.length) {
                resultats.innerHTML = this.tableauDesAccesProches(reponse.acces);
            }
        } catch (erreur) {
            Toast.error(I18n.t('common.error'), erreur.message);
        }
    },

    /** Les trois populations de chaque accès : des comptes qui se déplient. */
    tableauDesAccesProches(acces) {
        const populations = ['avec_le_role', 'hors_du_role', 'sans_l_acces'];
        return `
            <table class="role-detail-table">
                <thead><tr>
                    <th scope="col">${Utils.escapeHtml(I18n.t('role.proches.colonne.droit'))}</th>
                    <th scope="col">${Utils.escapeHtml(I18n.t('role.proches.colonne.jaccard'))}</th>
                    ${populations.map(code => `<th scope="col">${Utils.escapeHtml(
                        I18n.t(`role.proches.population.${code}`))}</th>`).join('')}
                </tr></thead>
                <tbody>${acces.map(ligne => `
                    <tr>
                        <td>${Utils.escapeHtml(ligne.droit)}</td>
                        <td>${Utils.escapeHtml(Utils.formatNumber(ligne.jaccard))}</td>
                        ${populations.map(code => `<td><button type="button"
                                class="btn btn-sm btn-link"
                                data-proches-droit="${Utils.escapeHtml(ligne.droit)}"
                                data-proches-population="${code}">${
                                Utils.escapeHtml(Utils.formatNumber(ligne[code]))}</button></td>`).join('')}
                    </tr>
                `).join('')}</tbody>
            </table>`;
    },

    /** Le tableau d'une population, construit une fois pour toutes les fenêtres. */
    tableauDeLaPopulation: null,

    /** L'une des trois populations d'un couple (rôle, accès), nommée. */
    montrerLaPopulation(droit, population) {
        const etat = this.detail;
        if (!etat) return;
        etat.population = {droit, population};
        const zone = document.getElementById('role-proches-population');
        if (zone) zone.hidden = false;
        const titre = document.getElementById('role-proches-population-titre');
        if (titre) {
            titre.textContent = I18n.t('role.proches.population_titre', {
                population: I18n.t(`role.proches.population.${population}`), droit});
        }
        if (!this.tableauDeLaPopulation) {
            this.tableauDeLaPopulation = new DataTable({
                type: 'validation-identities',
                endpoint: '',
                theadId: 'role-proches-pop-thead',
                tbodyId: 'role-proches-pop-list',
                searchId: 'role-proches-pop-search',
                countId: 'role-proches-pop-count',
                paginationPrefix: 'role-proches-pop',
                pageSize: this.PORTEURS_PAR_PAGE,
                detail: false,
                parametres: () => Object.assign({}, this.detail.population),
            });
        }
        const tableau = this.tableauDeLaPopulation;
        tableau.endpoint =
            `/kb/validated-roles/${encodeURIComponent(etat.roleId)}/acces-proches/population`;
        tableau.state.page = 1;
        tableau.state.search = '';
        const recherche = document.getElementById(tableau.searchId);
        if (recherche) recherche.value = '';
        return tableau.load();
    },

    /** Lignes de porteurs par page. Une fenêtre en montre moins qu'un écran. */
    PORTEURS_PAR_PAGE: 25,

    /** Le tableau des porteurs, construit une fois pour toutes les fenêtres. */
    tableauDesPorteurs: null,

    /**
     * Le tableau des porteurs du rôle ouvert.
     *
     * L'adresse change d'un rôle à l'autre, l'objet non : reconstruire le
     * tableau à chaque ouverture reposerait ses écouteurs sur les mêmes
     * éléments, et la recherche répondrait deux fois au bout de deux rôles.
     */
    porteurs() {
        if (this.tableauDesPorteurs) return this.tableauDesPorteurs;
        this.tableauDesPorteurs = new DataTable({
            // Même clé de réglages que les fenêtres de validation : c'est le
            // même référentiel d'identités, et quelqu'un qui a masqué six
            // colonnes pour valider un rôle ne veut pas les remasquer pour en
            // consulter un autre.
            type: 'validation-identities',
            endpoint: '',
            theadId: 'role-porteurs-thead',
            tbodyId: 'role-porteurs-list',
            searchId: 'role-porteurs-search',
            countId: 'role-porteurs-count',
            paginationPrefix: 'role-porteurs',
            pageSize: this.PORTEURS_PAR_PAGE,
            // Le détail d'une identité ouvrirait une fenêtre par-dessus la
            // fenêtre du rôle, et le rôle passerait derrière.
            detail: false,
            messageVide: 'role.detail.no_member',
        });
        return this.tableauDesPorteurs;
    },

    /**
     * Montre les porteurs d'un rôle, depuis le début.
     *
     * La fenêtre affichait « 100 porteurs affichés sur 6 269 » suivis d'une
     * liste d'identifiants et d'un bouton pour en voir cent de plus. Six mille
     * identifiants ne se lisent pas : on ne cherche personne dedans, on ne
     * reconnaît personne, et la question qu'on se pose devant un rôle — qui
     * est concerné ? — restait sans réponse.
     */
    chargerLesPorteurs(roleId) {
        const tableau = this.porteurs();
        tableau.endpoint =
            `/kb/validated-roles/${encodeURIComponent(roleId)}/porteurs`;
        // La recherche et le tri repartent de zéro : ils portaient sur un
        // autre rôle, et les garder ferait croire à un référentiel qui aurait
        // changé.
        tableau.state.page = 1;
        tableau.state.search = '';
        tableau.state.sortCol = null;
        tableau.state.sortDesc = false;
        const recherche = document.getElementById(tableau.searchId);
        if (recherche) recherche.value = '';
        return tableau.load().then(() => this.signalerLesPorteursInconnus());
    },

    /**
     * Dit combien de porteurs le référentiel d'identités ne connaît pas.
     *
     * Une identité présente dans les habilitations et absente du référentiel
     * des identités n'a aucune colonne à montrer : sa ligne est vide, et sans
     * cette phrase l'utilisateur croit à un défaut d'affichage. Elle compte
     * pourtant dans le nombre de porteurs du rôle — la taire ferait mentir
     * un chiffre.
     */
    signalerLesPorteursInconnus() {
        const zone = document.getElementById('role-porteurs-orphelins');
        if (!zone) return;
        const inconnus = (this.tableauDesPorteurs
            && this.tableauDesPorteurs.state.inconnus) || [];
        zone.hidden = inconnus.length === 0;
        zone.textContent = inconnus.length
            ? I18n.t('validation.orphans', {count: inconnus.length}) : '';
    },

    /**
     * Demande un nom à un modèle. Il ne s'applique jamais seul : il remplit un
     * champ que quelqu'un valide, et l'enregistrement reste un geste à part.
     */
    async proposerUnNom() {
        const etat = this.detail;
        const champ = document.getElementById('role-detail-nom');
        if (!etat || !etat.donnees || !champ) return;
        const {role, mesures} = etat.donnees;
        try {
            const proposition = await API.suggestRoleName({
                role: {id: role.id, rights: role.rights || [],
                       right_count: mesures.right_count,
                       user_count: mesures.user_count},
                regle: [],
                locale: I18n.currentLocale,
            });
            champ.value = proposition.nom || proposition.name || champ.value;
        } catch (erreur) {
            Toast.error(I18n.t('common.error'), erreur.message);
        }
    },

    async renommerLeRole() {
        const etat = this.detail;
        const nom = document.getElementById('role-detail-nom');
        const description = document.getElementById('role-detail-description');
        if (!etat || !nom) return;
        if (!nom.value.trim()) {
            Toast.error(I18n.t('common.error'), I18n.t('validation.name_required'));
            return;
        }
        try {
            const reponse = await API.post(
                `/kb/validated-roles/${encodeURIComponent(etat.roleId)}/renommer`,
                {name: nom.value.trim(),
                 description: description ? description.value.trim() : ''});
            Toast.success(I18n.t('common.success'),
                          I18n.t('role.rename.done', {version: reponse.version}));
            await this.chargerLeDetail(0);
            await this.loadCatalog();
        } catch (erreur) {
            Toast.error(I18n.t('common.error'), erreur.message);
        }
    },

    /**
     * Sort un rôle du catalogue. Le motif est obligatoire : c'est lui qui, dans
     * six mois, expliquera pourquoi ce rôle n'existe plus.
     */
    async devaliderLeRole() {
        const etat = this.detail;
        if (!etat || !etat.donnees) return;
        const nom = etat.donnees.role.name || etat.roleId;

        const motif = await Confirm.demander({
            titre: I18n.t('role.devalidate.confirm_title'),
            message: I18n.t('role.devalidate.confirm', {nom}),
            danger: true,
            confirmer: I18n.t('role.devalidate'),
            saisie: {label: I18n.t('role.devalidate.reason')},
        });
        if (motif === false) return;

        try {
            await API.post(
                `/kb/validated-roles/${encodeURIComponent(etat.roleId)}/devalider`,
                {motif});
            Modal.close();
            Toast.success(I18n.t('common.success'),
                          I18n.t('role.devalidate.done', {nom}));
            // Le candidat correspondant redevient à décider : la cloche doit
            // le dire sans attendre un rechargement de page.
            if (typeof Cloche !== 'undefined') Cloche.rafraichir();
            await this.loadCatalog();
        } catch (erreur) {
            Toast.error(I18n.t('common.error'), erreur.message);
        }
    },

    // === COMPOSER ===

    async loadComposer() {
        
        try {
            // 🔧 FIX: Extraire .roles de la réponse
            const response = await API.getRoles();
            
            if (response && response.roles) {
                this.allRoles = response.roles.filter(r => r.role_type === 'APPLICATIF');
            } else if (Array.isArray(response)) {
                this.allRoles = response.filter(r => r.role_type === 'APPLICATIF');
            } else {
                this.allRoles = [];
            }
            
            this.renderComposerRoles();
            
            // Charger les droits unitaires
            await this.loadUnitRights();
            
        } catch (error) {
            Toast.error(I18n.t('common.error'), I18n.t('roles.composer_load_error'));
        }
    },

    async loadUnitRights() {
        try {
            const rights = await API.get('/rights');
            this.allUnitRights = rights.data || rights || [];
            this.renderUnitRightsSelector();
        } catch (error) {
            Toast.error(I18n.t('common.error'), error.message);
        }
    },

    renderComposerRoles() {
        const container = document.getElementById('composer-roles-list');
        if (!container) return;

        const filteredRoles = this.rolesSearchValue
            ? this.allRoles.filter(r => 
                r.name.toLowerCase().includes(this.rolesSearchValue) ||
                r.description?.toLowerCase().includes(this.rolesSearchValue)
              )
            : this.allRoles;

        if (filteredRoles.length === 0) {
            container.innerHTML = `
                <div class="empty-state-mini">
                    <p>${I18n.t('roles.no_app_roles')}</p>
                </div>
            `;
            return;
        }

        container.innerHTML = filteredRoles.map(role => {
            const isSelected = this.selectedRoles.has(role.id);
            return `
                <label class="composer-item ${isSelected ? 'selected' : ''}">
                    <input 
                        type="checkbox" 
                        value="${Utils.escapeHtml(role.id)}"
                        ${isSelected ? 'checked' : ''}
                        data-role-toggle="${Utils.escapeHtml(role.id)}"
                    >
                    <div class="composer-item-content">
                        <strong>${Utils.escapeHtml(role.name)}</strong>
                        <span class="composer-item-meta">
                            ${role.rights?.length || 0} ${I18n.t('common.rights')}
                        </span>
                    </div>
                </label>
            `;
        }).join('');
    },

    renderUnitRightsSelector() {
        const container = document.getElementById('composer-unit-rights-selector');
        if (!container) return;

        const filteredRights = this.unitRightsSearchValue
            ? this.allUnitRights.filter(r => {
                const rightId = r.ID_droit || r.id || '';
                const rightName = r.Nom || r.name || '';
                const search = this.unitRightsSearchValue;
                return rightId.toLowerCase().includes(search) || 
                       rightName.toLowerCase().includes(search);
              })
            : this.allUnitRights;

        if (filteredRights.length === 0) {
            container.innerHTML = `
                <div class="empty-state-mini">
                    <p>${I18n.t('rights.no_rights')}</p>
                </div>
            `;
            return;
        }

        container.innerHTML = filteredRights.map(right => {
            const rightId = right.ID_droit || right.id || '';
            const rightName = right.Nom || right.name || rightId;
            const isSelected = this.selectedUnitRights.has(rightId);
            
            return `
                <label class="composer-item ${isSelected ? 'selected' : ''}">
                    <input 
                        type="checkbox" 
                        value="${rightId}"
                        ${isSelected ? 'checked' : ''}
                        data-right-toggle="${Utils.escapeHtml(rightId)}"
                    >
                    <div class="composer-item-content">
                        <strong>${Utils.escapeHtml(rightId)}</strong>
                        ${rightName !== rightId ? `<span class="composer-item-meta">${Utils.escapeHtml(rightName)}</span>` : ''}
                    </div>
                </label>
            `;
        }).join('');
    },

    toggleRoleSelection(roleId) {
        if (this.selectedRoles.has(roleId)) {
            this.selectedRoles.delete(roleId);
        } else {
            this.selectedRoles.add(roleId);
        }
        this.updateComposerStats();
    },

    toggleUnitRightSelection(rightId) {
        if (this.selectedUnitRights.has(rightId)) {
            this.selectedUnitRights.delete(rightId);
        } else {
            this.selectedUnitRights.add(rightId);
        }
        this.updateComposerStats();
    },

    /**
     * Met à jour les cinq compteurs du compositeur.
     *
     * La version précédente écrivait du HTML dans un conteneur
     * `composer-stats` qui n'existe nulle part, pendant que les compteurs du
     * gabarit restaient à zéro quoi qu'on sélectionne — sans la moindre
     * erreur en console, puisque `getElementById` rend `null` sans broncher.
     */
    updateComposerStats() {
        let droitsHerites = 0;
        this.selectedRoles.forEach(roleId => {
            const role = this.allRoles.find(r => r.id === roleId);
            if (role && role.rights) {
                droitsHerites += role.rights.length;
            }
        });

        const droitsAjoutes = this.selectedUnitRights.size
            + this.exceptionsSaisies().length;

        const compteurs = {
            'selected-roles-count': this.selectedRoles.size,
            'extra-rights-count': droitsAjoutes,
            'summary-app-roles': this.selectedRoles.size,
            'summary-extra-rights': droitsAjoutes,
            'summary-total-rights': droitsHerites + droitsAjoutes,
        };
        Object.entries(compteurs).forEach(([identifiant, valeur]) => {
            const element = document.getElementById(identifiant);
            if (element) element.textContent = valeur;
        });

        // Le contrôle suit la composition, à chaque changement : découvrir au
        // moment d'enregistrer qu'un rôle réunit deux pouvoirs incompatibles
        // revient à le découvrir après l'avoir composé.
        this.planifierLeControleDeSeparation();
    },

    /**
     * Les droits saisis à la main, séparés par des virgules.
     *
     * Lus à un seul endroit : la composition et son contrôle doivent porter sur
     * le même ensemble, et deux lectures finissent par diverger.
     */
    exceptionsSaisies() {
        const champ = document.getElementById('composer-extra-rights');
        if (!champ || !champ.value.trim()) return [];
        return champ.value.split(',').map((droit) => droit.trim()).filter(Boolean);
    },

    /**
     * Ce que le rôle composé accorderait : l'union, et non la somme.
     *
     * Deux sous-rôles partagent souvent des droits ; les compter deux fois
     * n'aurait aucune importance pour un compteur, mais en aurait une ici — une
     * règle se juge sur un ensemble, pas sur une liste.
     */
    droitsDuComposeur() {
        const droits = new Set();
        this.selectedRoles.forEach((roleId) => {
            const role = this.allRoles.find((candidat) => candidat.id === roleId);
            (role?.rights || []).forEach((droit) => droits.add(String(droit)));
        });
        this.selectedUnitRights.forEach((droit) => droits.add(String(droit)));
        this.exceptionsSaisies().forEach((droit) => droits.add(String(droit)));
        return Array.from(droits);
    },

    /**
     * Retarde le contrôle : la saisie des exceptions frappe une touche à la
     * fois, et un appel par caractère ferait travailler le serveur pour des
     * états que personne ne regarde.
     */
    planifierLeControleDeSeparation() {
        if (!this.controleRetarde) {
            this.controleRetarde = Utils.debounce(
                () => this.controlerLaSeparationDuComposeur(),
                RolesPage.DELAI_DE_CONTROLE);
        }
        this.controleRetarde();
    },

    /**
     * Signale les règles de séparation que le rôle composé enfreindrait.
     *
     * Le produit **signale et ne refuse pas** : un rôle peut légitimement
     * réunir deux droits qu'une règle sépare — parce que la règle est trop
     * large, parce que la population visée est contrôlée autrement. Refuser à
     * la place de l'analyste ferait contourner le contrôle plutôt que le
     * respecter, et le produit perdrait la trace de la décision.
     *
     * Aucun coût de retrait n'est demandé, et c'est exact : le rôle n'existe
     * pas encore, il n'a aucun porteur, et il n'y a donc rien à chiffrer.
     */
    async controlerLaSeparationDuComposeur() {
        const zone = document.getElementById('composer-separation');
        if (!zone) return;
        const droits = this.droitsDuComposeur();
        const jeton = (this.jetonDuComposeur = (this.jetonDuComposeur || 0) + 1);
        if (!droits.length) {
            this.renderLaSeparationDuComposeur([]);
            return;
        }
        let rendu;
        try {
            rendu = await API.controlerLaSeparation([{cle: 'composeur', droits}]);
        } catch (erreur) {
            if (jeton !== this.jetonDuComposeur) return;
            // L'écran le dit plutôt que de se taire : une zone vide se lit
            // « aucun conflit », et rassurer sur un contrôle qui n'a pas eu
            // lieu est pire que de ne rien annoncer.
            zone.hidden = false;
            zone.innerHTML = `<div class="alert alert-warning">${
                Utils.escapeHtml(I18n.t('separation.composer_illisible'))}</div>`;
            return;
        }
        // La composition a pu changer pendant l'appel : afficher le résultat
        // d'un ensemble qu'on ne compose plus désignerait les mauvais droits.
        if (jeton !== this.jetonDuComposeur) return;
        this.renderLaSeparationDuComposeur(
            ((rendu.ensembles || [])[0] || {}).regles || []);
    },

    renderLaSeparationDuComposeur(enfreintes) {
        const zone = document.getElementById('composer-separation');
        if (!zone) return;
        zone.hidden = enfreintes.length === 0;
        zone.innerHTML = enfreintes.map((regle) => `
            <div class="alert alert-danger">
                ${Utils.escapeHtml(I18n.t('separation.composer_breached', {
                    regle: regle.libelle,
                    gauche: regle.gauche.join(', '),
                    droite: regle.droite.join(', ')}))}
            </div>`).join('');
    },

    async createBusinessRole() {
        const nameInput = document.getElementById('composer-role-name');
        const descInput = document.getElementById('composer-role-desc');

        if (!nameInput || !descInput) {
            Toast.error(I18n.t('common.error'), I18n.t('validation.fields_missing'));
            return;
        }

        const name = nameInput.value.trim();
        const description = descInput.value.trim();

        if (!name) {
            Toast.error(I18n.t('common.error'), I18n.t('validation.name_required'));
            nameInput.focus();
            return;
        }

        if (this.selectedRoles.size === 0 && this.selectedUnitRights.size === 0) {
            Toast.error(I18n.t('common.error'), I18n.t('validation.select_rights'));
            return;
        }

        try {
            // Construire liste des droits additionnels
            const additionalRights = Array.from(this.selectedUnitRights);
            
            // Ajouter exceptions
            const extraRightsInput = document.getElementById('composer-extra-rights');
            additionalRights.push(...this.exceptionsSaisies());

            const roleData = {
                name,
                description,
                role_type: 'METIER',
                sub_role_ids: Array.from(this.selectedRoles),
                additional_rights: additionalRights,
                rights: [] // Les droits seront calculés par le backend
            };


            await API.post('/roles/create', roleData);

            // Un rôle composé à la main peut porter le même ensemble de droits
            // qu'un candidat en attente : celui-ci n'est alors plus à décider.
            if (typeof Cloche !== 'undefined') Cloche.rafraichir();

            Toast.success(
                I18n.t('common.success'),
                I18n.t('roles.created_success', { name })
            );

            // Reset
            nameInput.value = '';
            descInput.value = '';
            this.selectedRoles.clear();
            this.selectedUnitRights.clear();
            if (extraRightsInput) extraRightsInput.value = '';
            
            this.renderComposerRoles();
            this.renderUnitRightsSelector();
            this.updateComposerStats();

        } catch (error) {
            Toast.error(I18n.t('common.error'), error.message || I18n.t('roles.create_error'));
        }
    }
};

// Délégation des cases à cocher du compositeur. Un identifiant de rôle ou de
// droit inséré dans un `onchange` s'exécuterait s'il contenait une apostrophe :
// ces valeurs viennent des fichiers du client.
document.addEventListener('change', (evenement) => {
    const role = evenement.target.closest('[data-role-toggle]');
    if (role) {
        RolesPage.toggleRoleSelection(role.dataset.roleToggle);
        return;
    }
    const droit = evenement.target.closest('[data-right-toggle]');
    if (droit) {
        RolesPage.toggleUnitRightSelection(droit.dataset.rightToggle);
    }
});

window.RolesPage = RolesPage;
