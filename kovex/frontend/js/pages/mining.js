/**
 * PyGIA Frontend - Mining Page - VERSION FINALE UNIFIÉE
 * Mining Applicatif et Métier avec UI identique et logique correcte
 */

const MiningPage = {
    results: [],
    businessAttributes: [],
    appMiningResults: [],
    //: Derniers indicateurs reçus, conservés pour pouvoir les réafficher dans
    //  une autre langue sans relancer un mining.
    dernieresStatsApp: null,
    dernieresStatsBiz: null,
    //: Lignes par page des tableaux de la fenêtre de validation. Une fenêtre
    //  en montre moins qu'un écran d'exploration : la place y est comptée, et
    //  la liste n'est pas l'objet de l'écran.
    LIGNES_PAR_PAGE_VALIDATION: 25,

    //: Combien de fois une ligne du nommage en lot attend que le serveur
    //  rouvre le débit avant d'abandonner. Un serveur qui refuse
    //  indéfiniment doit finir par rendre la main : une fenêtre qui tourne
    //  sans fin devant quelqu'un qui ne sait pas pourquoi est pire qu'un
    //  échec annoncé.
    ATTENTES_MAX: 5,

    //: Plafond d'une attente, en secondes. Le serveur annonce un délai ; s'il
    //  en annonçait un très long, l'écran resterait bloqué dessus. Passé ce
    //  plafond, la ligne est rendue à l'utilisateur, qui relancera quand il
    //  voudra.
    ATTENTE_MAX_S: 90,

    //: Jusqu'où chercher un nom libre en numérotant. Au-delà, le produit rend
    //  le nom d'origine et laisse le serveur refuser : fabriquer une vingtième
    //  variante d'un nom que personne n'a voulu n'aide personne.
    SUFFIXES_MAX: 20,

    //: Nombre de droits socles écartés par le dernier mining applicatif. Le
    //  bandeau qui l'annonce est écrit en JavaScript : sans mémoriser le
    //  compte, un changement de langue le laissait dans l'ancienne.
    derniersSoclesExclus: 0,

    async init() {
        // Les écouteurs se posent en premier, avant le moindre appel réseau.
        //
        // Ils l'étaient après trois allers-retours avec le serveur. Le gabarit
        // est pourtant déjà là : pendant ces quelques centaines de
        // millisecondes, l'écran avait l'air prêt — les champs s'affichaient —
        // et un clic tombait dans le vide sans que rien ne le dise. Sur un
        // poste chargé, ces centaines de millisecondes deviennent des
        // secondes.
        //
        // Aucun écouteur ne dépend des données : ils se posent sur des
        // éléments du gabarit, et ce qu'ils déclenchent lit l'état au moment
        // du clic, pas à celui de la liaison.
        this.bindEvents();
        await this.appliquerLesReglagesDuWorkspace();
        await this.loadBusinessAttributes();
        await this.loadKBStats();
        this.ajusterLaProfondeur();
        this.recapitulerMetier();
    },

    /**
     * Remplit les seuils des deux formulaires avec les réglages du workspace.
     *
     * Les champs portaient une valeur écrite dans le gabarit — cinq
     * utilisateurs, deux droits. L'administrateur pouvait donc régler l'effectif
     * minimal de son workspace sans que l'écran de mining n'en tienne compte :
     * il annonçait un seuil, en envoyait un autre, et rien ne le disait. Les
     * chiffres du gabarit ne sont plus que le repli d'un serveur muet.
     *
     * L'échec n'est pas fatal : sans réglages, l'écran reste utilisable avec
     * ses valeurs de repli, et l'utilisateur les corrige à la main.
     */
    async appliquerLesReglagesDuWorkspace() {
        let reglages;
        try {
            reglages = await API.getSettings();
        } catch (erreur) {
            return;
        }
        const champs = [
            ['mining-min-users', 'mining_min_users'],
            ['mining-min-rights', 'mining_min_rights'],
            ['biz-min-users', 'mining_min_users'],
            ['biz-min-rights', 'mining_min_rights'],
            // L'apport minimal vient du workspace : le champ n'a aucune valeur
            // dans le gabarit, parce qu'un plancher écrit là écarterait des
            // rôles sans que personne ne l'ait décidé.
            ['mining-apport-minimal', 'mining_apport_minimal'],
        ];
        champs.forEach(([identifiant, cle]) => {
            const champ = document.getElementById(identifiant);
            const valeur = reglages && reglages[cle];
            if (champ && Number.isFinite(Number(valeur)) && valeur !== null
                && valeur !== undefined && valeur !== '') {
                champ.value = String(valeur);
            }
        });

        // La sélection des rôles vient du workspace, comme l'apport minimal :
        // le gabarit ne présélectionne rien de lui-même, faute de quoi un
        // workspace réglé autrement verrait son choix écrasé par l'écran.
        const selection = document.getElementById('mining-selection');
        const choisie = reglages && reglages.mining_selection;
        if (selection && Array.from(selection.options).some((option) => option.value === choisie)) {
            selection.value = choisie;
        }

        // Le plafond du nombre de rôles borne la **saisie**, il ne la
        // remplit pas : la valeur demandée reste celle de l'utilisateur.
        //
        // Il était écrit `max="5000"` dans le gabarit. Sur un référentiel qui
        // porte plus de rôles candidats que cela, l'avertissement « plafond
        // atteint » de la courbe ne pouvait plus jamais disparaître — et il
        // parlait d'une limite du produit en se faisant passer pour un fait
        // sur la donnée.
        const plafond = reglages && reglages.mining_max_roles_plafond;
        const saisie = document.getElementById('mining-max-roles');
        if (saisie && Number.isFinite(Number(plafond)) && Number(plafond) >= 1) {
            saisie.max = String(plafond);
        }
    },

    /**
     * L'apport minimal saisi, ou rien.
     *
     * Rien signifie « le réglage du workspace » : le champ vide ne doit pas
     * devenir un plancher de un posé par l'écran, sans quoi un workspace
     * réglé plus haut verrait son réglage écrasé par un formulaire.
     */
    selectionChoisie() {
        const valeur = document.getElementById('mining-selection')?.value;
        return valeur ? valeur : undefined;
    },

    /**
     * Ce que la sélection exacte a fait, en une phrase, ou rien.
     *
     * Le glouton ne dit rien : c'est le calcul de toujours. La sélection
     * exacte, elle, dit toujours quelque chose — combien de rôles le glouton
     * aurait retenus, et pourquoi la recherche s'est arrêtée. Un modèle plus
     * court présenté sans le chiffre qu'il remplace ne se vérifierait pas.
     */
    compteRenduDeSelection(engine, roles) {
        if (!engine || engine.selection !== 'exacte' || !engine.selection_arret
            || typeof roles !== 'number') return '';
        const arret = engine.selection_arret;
        const valeurs = {
            roles: Utils.formatNumber(roles),
            glouton: Utils.formatNumber(engine.selection_roles_glouton ?? roles)
        };
        const plusCourt = typeof engine.selection_roles_glouton === 'number'
            && roles < engine.selection_roles_glouton;
        const cle = (arret === 'effort' || arret === 'delai') && !plusCourt
            ? `mining.selection.arret.${arret}_sans_gain`
            : `mining.selection.arret.${arret}`;
        let phrase = I18n.t(cle, valeurs);
        if (typeof engine.selection_borne === 'number'
            && (arret === 'effort' || arret === 'delai')) {
            phrase += ' ' + I18n.t('mining.selection.borne', {
                borne: Utils.formatNumber(engine.selection_borne)
            });
        }
        return phrase;
    },

    apportMinimalSaisi() {
        const brut = document.getElementById('mining-apport-minimal')?.value;
        if (brut === undefined || String(brut).trim() === '') return undefined;
        const valeur = parseInt(brut, 10);
        return Number.isFinite(valeur) && valeur >= 1 ? valeur : undefined;
    },

    /**
    * Générer un ID de rôle unique basé sur les DROITS (pas le nom)
    * Utilise SHA-256 via Web Crypto API (identique au backend)
    */
    bindEvents() {
        // L'état de l'annotateur est lu une fois, et c'est voulu. Mais il se
        // règle maintenant dans les paramètres, en cours de séance : quand
        // l'écran des paramètres dit qu'il a changé, on l'oublie, et le
        // prochain rôle ouvert le relit.
        document.addEventListener('kovex:assistance-modifiee', () => {
            this.etatAnnotateur = null;
        });

        // Le récapitulatif suit la saisie. Délégation plutôt qu'un écouteur par
        // champ : le formulaire en compte huit, et un neuvième ajouté demain
        // serait sinon absent de la phrase sans que rien ne le dise.
        const formulaireMetier = document.getElementById('biz-recapitulatif')?.closest('.card-body');
        if (formulaireMetier) {
            ['input', 'change'].forEach(evenement =>
                formulaireMetier.addEventListener(evenement, () => {
                    this.recapitulerMetier();
                    // Changer la profondeur change le nombre de combinaisons,
                    // sans toucher aux attributs cochés.
                    this.annoncerLeCoutDuCroisement();
                }));
        }

        // La profondeur ne peut pas dépasser le nombre d'attributs cochés :
        // croiser trois critères quand on en a coché deux ne veut rien dire, et
        // le moteur bornait en silence. Les choix suivent donc les cases.
        const attributs = document.getElementById('biz-attributes-container');
        if (attributs) {
            attributs.addEventListener('change', () => this.ajusterLaProfondeur());
        }

        const proposerAttributs = document.getElementById('biz-attributs-proposer');
        if (proposerAttributs) {
            proposerAttributs.addEventListener('click', () => this.proposerLesAttributs());
        }

        // Mining Applicatif
        const launchAppBtn = document.getElementById('launch-mining');
        if (launchAppBtn) {
            launchAppBtn.addEventListener('click', () => this.launchMining());
        }

        // Les parametres du mode approche ne concernent que ce mode.
        const modeSelect = document.getElementById('mining-mode');
        if (modeSelect) {
            modeSelect.addEventListener('change', () => this.syncMiningModeFields());
            this.syncMiningModeFields();
        }

        const scanBtn = document.getElementById('run-threshold-scan');
        if (scanBtn) {
            scanBtn.addEventListener('click', () => this.runThresholdScan());
        }

        const nameBtn = document.getElementById('ask-role-name');
        if (nameBtn) {
            nameBtn.addEventListener('click', () => this.proposerUnNomDeRole('app'));
        }

        const bizNameBtn = document.getElementById('ask-biz-role-name');
        if (bizNameBtn) {
            bizNameBtn.addEventListener('click', () => this.proposerUnNomDeRole('biz'));
        }

        const bizExplication = document.getElementById('ask-biz-explication');
        if (bizExplication) {
            bizExplication.addEventListener('click', () => this.expliquerLeRole('biz'));
        }

        ['app', 'biz'].forEach((prefixe) => {
            const lot = document.getElementById(`${prefixe}-nommage-lot`);
            if (lot) {
                lot.addEventListener('click', () => this.ouvrirLeNommageEnLot(prefixe));
            }
        });

        const departLot = document.getElementById('batch-naming-start');
        if (departLot) departLot.addEventListener('click', () => this.lancerLeLot());

        const arretLot = document.getElementById('batch-naming-stop');
        if (arretLot) arretLot.addEventListener('click', () => this.arreterLeLot());

        const garderLot = document.getElementById('batch-naming-keep');
        if (garderLot) {
            garderLot.addEventListener('click', () => this.conserverLesNomsDuLot());
        }

        // Délégation : le tableau du lot est réécrit ligne par ligne à chaque
        // réponse, un écouteur posé sur chaque champ serait perdu.
        const lignesDuLot = document.getElementById('batch-naming-rows');
        if (lignesDuLot) {
            lignesDuLot.addEventListener('change', (evenement) => {
                const cible = evenement.target;
                if (cible.dataset.lotDemandee !== undefined) {
                    this.modifierLaLigneDuLot(Number(cible.dataset.lotDemandee),
                                              'demandee', cible.checked);
                }
            });
            lignesDuLot.addEventListener('input', (evenement) => {
                const cible = evenement.target;
                if (cible.dataset.lotNom !== undefined) {
                    this.modifierLaLigneDuLot(Number(cible.dataset.lotNom),
                                              'nom', cible.value);
                } else if (cible.dataset.lotDescription !== undefined) {
                    this.modifierLaLigneDuLot(Number(cible.dataset.lotDescription),
                                              'description', cible.value);
                }
            });
        }

        const explainBtn = document.getElementById('explain-app-role');
        if (explainBtn) {
            explainBtn.addEventListener('click', () => this.expliquerRoleApplicatif());
        }

        const consolidationBtn = document.getElementById('run-consolidation-scan');
        if (consolidationBtn) {
            consolidationBtn.addEventListener('click', () => this.runConsolidationScan());
        }

        const confirmAppBtn = document.getElementById('confirm-create-app-role');
        if (confirmAppBtn) {
            confirmAppBtn.addEventListener('click', () => this.confirmCreateAppRole());
        }

        const rejectAppBtn = document.getElementById('btn-reject-app-role');
        if (rejectAppBtn) {
            rejectAppBtn.addEventListener('click', () => this.rejectAppRole());
        }

        // Mining Métier
        const launchBizBtn = document.getElementById('launch-business-mining');
        if (launchBizBtn) {
            launchBizBtn.addEventListener('click', () => this.launchBusinessMining());
        }

        const tradeoffBtn = document.getElementById('biz-explore-tradeoff');
        if (tradeoffBtn) {
            tradeoffBtn.addEventListener('click', () => this.explorerArbitrage());
        }

        const detail = document.getElementById('biz-population-detail');
        if (detail) {
            detail.addEventListener('click', () => this.ouvrirDetailPopulation());
        }

        // Délégation : le tableau est reconstruit à chaque ouverture.
        const corpsDetail = document.getElementById('population-detail-body');
        if (corpsDetail) {
            corpsDetail.addEventListener('click', (evenement) => {
                const bouton = evenement.target.closest('[data-exclure-groupe]');
                if (!bouton) return;
                evenement.preventDefault();
                this.exclureGroupe(Number(bouton.dataset.exclureGroupe));
            });
        }

        // Délégation : les points d'arbitrage sont reconstruits à chaque calcul.
        const tradeoffBody = document.getElementById('biz-tradeoff-body');
        if (tradeoffBody) {
            tradeoffBody.addEventListener('click', (evenement) => {
                const bouton = evenement.target.closest('[data-arbitrage]');
                if (!bouton) return;
                evenement.preventDefault();
                this.retenirArbitrage(parseFloat(bouton.dataset.arbitrage));
            });
        }

        document.querySelectorAll('[data-impact]').forEach((bouton) => {
            bouton.addEventListener('click', (evenement) => {
                evenement.preventDefault();
                this.mesurerImpact(bouton.dataset.impact);
            });
        });

        const confirmBizCreationBtn = document.getElementById('btn-confirm-biz-creation');
        if (confirmBizCreationBtn) {
            confirmBizCreationBtn.addEventListener('click', () => this.confirmCreateBusinessRole());
        }

        const rejectBizBtn = document.getElementById('btn-reject-biz-role');
        if (rejectBizBtn) {
            rejectBizBtn.addEventListener('click', () => this.rejectBusinessRole());
        }

        // Fermeture modales
        const modalAppCloseBtn = document.querySelector('#app-role-modal .modal-close');
        if (modalAppCloseBtn) {
            modalAppCloseBtn.addEventListener('click', () => this.closeAppRoleModal());
        }

        // Désigné par son identifiant, jamais par sa classe d'apparence : le
        // premier `.btn-secondary` de la modale change dès qu'on y ajoute un
        // bouton, et « Proposer un nom » a ainsi fermé la fenêtre.
        const modalAppCancelBtn = document.getElementById('cancel-app-role');
        if (modalAppCancelBtn) {
            modalAppCancelBtn.addEventListener('click', () => this.closeAppRoleModal());
        }

        const modalBizCloseBtn = document.querySelector('#biz-role-modal .modal-close');
        if (modalBizCloseBtn) {
            modalBizCloseBtn.addEventListener('click', () => this.closeBusinessRoleModal());
        }

        const modalBizCancelBtn = document.getElementById('cancel-biz-role');
        if (modalBizCancelBtn) {
            modalBizCancelBtn.addEventListener('click', () => this.closeBusinessRoleModal());
        }

        // La recherche des onglets de validation est tenue par le tableau
        // lui-même : elle porte sur toutes les colonnes du référentiel, et
        // côté serveur. Le filtre qui masquait des lignes déjà écrites ne
        // pouvait rien trouver dans une colonne qui n'était pas affichée.

        // Recherche Métier
    },

    /**
     * Réaffiche dans la langue courante ce qui est déjà à l'écran.
     *
     * Les bandeaux, les cartes de rôles et les indicateurs sont écrits par ce
     * module : ils ne portent aucune clé de traduction, et `applyTranslations`
     * ne les voit pas. Sans cela, changer de langue laissait la page du mining
     * en français jusqu'au rechargement.
     */
    rafraichirLangue() {
        this.loadKBStats();
        this.loadBusinessAttributes();
        if (this.dernieresStatsBiz) this.renderGlobalStats(this.dernieresStatsBiz);
        if (this.results.length) this.renderBusinessResults(this.results);
        if (this.dernieresStatsApp) this.showGlobalStatsGrid(this.dernieresStatsApp);
        if (this.appMiningResults.length) this.renderAppResults(this.appMiningResults);
        this.showBirthRightsBanner(this.derniersSoclesExclus);
        this.rendreRunConserve('APPLICATIF');
        this.rendreRunConserve('METIER');
        this.majBoutonDeNommageEnLot('app', this.appMiningResults.length);
        this.majBoutonDeNommageEnLot('biz', this.results.length);
        // Le classement proposé est une phrase : elle reste dans l'ancienne
        // langue si personne ne la réécrit. Sans proposition en cours, il n'y
        // a rien à réécrire — et la fonction le dit plutôt que de laisser un
        // panneau d'une session précédente.
        this.renderLesAttributsProposes();
        if (this.lot) this.renderLeLot();

        const compteur = document.getElementById('mining-results-count');
        if (compteur && this.appMiningResults.length) {
            compteur.textContent = I18n.t('mining.results_count',
                                          { count: this.appMiningResults.length });
        }
    },

    async loadKBStats() {
        try {
            const stats = await KnowledgeBase.getStats();
            const brInfo = await KnowledgeBase.getBirthRightsInfo();
            
            // 🔧 FIX: Toujours afficher le bandeau, même si count = 0
            if (brInfo) {
                this.showBirthRightsInfo(brInfo);
            }
            
            this.showValidatedRolesInfo(stats);

        } catch (error) {
            Toast.error(I18n.t('common.error'), error.message);
        }
    },

    showBirthRightsInfo(brInfo) {
        const container = document.getElementById('mining-kb-info');
        if (!container) return;

        // Les deux bandeaux portaient leur texte en français dans le code —
        // émoticônes comprises — et leur mise en forme en styles en ligne.
        const detecte = brInfo.count > 0;
        const bandeau = {
            classe: detecte ? 'kb-info-banner--info' : 'kb-info-banner--warning',
            icone: detecte ? 'fa-info-circle' : 'fa-exclamation-triangle',
            titre: detecte ? 'mining.birth_rights.detected_title'
                           : 'mining.birth_rights.none_title',
            detail: detecte ? 'mining.birth_rights.detected_detail'
                            : 'mining.birth_rights.none_detail',
            action: detecte ? 'mining.birth_rights.see' : 'mining.birth_rights.detect',
            icoteAction: detecte ? 'fa-eye' : 'fa-sliders-h',
        };

        container.innerHTML = `
            <div class="kb-info-banner ${bandeau.classe}">
                <i class="fas ${bandeau.icone} kb-info-banner__icone" aria-hidden="true"></i>
                <div class="kb-info-banner__texte">
                    <strong>${Utils.escapeHtml(I18n.t(bandeau.titre))}</strong>
                    <p>${Utils.escapeHtml(I18n.t(bandeau.detail, {
                        count: brInfo.count, threshold: brInfo.threshold }))}</p>
                </div>
                <button class="btn btn-sm btn-secondary" data-goto-page="birth-rights">
                    <i class="fas ${bandeau.icoteAction}" aria-hidden="true"></i>
                    ${Utils.escapeHtml(I18n.t(bandeau.action))}
                </button>
            </div>`;
    },

    /**
     * Rappelle ce qui est déjà validé, et se taise quand il ne sait pas.
     *
     * `KnowledgeBase.getStats()` rattrape tout et rend `null` : avant qu'un
     * espace de travail ne soit actif, la base répond 409. Lire
     * `null.validated_app_roles` jetait alors, l'écran affichait « Cannot read
     * properties of null » à la place de l'information, et l'exception coupait
     * le reste du chargement — le bandeau ne revenait plus, même une fois les
     * données chargées.
     *
     * Une base qu'on n'a pas su lire n'est pas une base sans rôle validé : on
     * n'affiche rien plutôt que d'affirmer zéro.
     */
    showValidatedRolesInfo(stats) {
        const container = document.getElementById('mining-validated-info');
        if (!container) return;

        if (!stats) {
            container.innerHTML = '';
            return;
        }

        const applicatifs = stats.validated_app_roles || 0;
        const metiers = stats.validated_business_roles || 0;
        if (applicatifs + metiers === 0) {
            container.innerHTML = '';
            return;
        }

        container.innerHTML = `
            <div class="kb-info-banner kb-info-banner--success">
                <i class="fas fa-check-circle kb-info-banner__icone" aria-hidden="true"></i>
                <div class="kb-info-banner__texte">
                    <strong>${Utils.escapeHtml(I18n.t('mining.validated_roles.title'))}</strong>
                    <p>${Utils.escapeHtml(I18n.t('mining.validated_roles.detail', {
                        app: applicatifs, business: metiers }))}</p>
                </div>
            </div>`;
    },


    // ------------------------------------------- les attributs pertinents

    //: Classement proposé par le modèle, par colonne. Il ne coche rien : la
    //  règle de cardinalité reste le garde-fou, et l'écran montre les deux.
    classementDesAttributs: null,

    //: Noms des rôles déjà validés, par préfixe d'écran, tels que le dernier
    //  mining les a rendus — complétés par ceux que cet écran vient de créer.
    nomsDuCatalogue: { biz: [], app: [] },

    //: Ce que la lecture de la réponse a écarté, et pourquoi.
    lectureDesAttributs: null,

    /**
     * Demande au modèle ce que chaque colonne est.
     *
     * Parmi quarante colonnes, l'analyste cherche aujourd'hui par essais
     * successifs, à plusieurs minutes la tentative. La proposition lui épargne
     * ce tour — elle ne décide rien.
     */
    async proposerLesAttributs() {
        const bouton = document.getElementById('biz-attributs-proposer');
        if (!bouton) return;
        const libelle = bouton.innerHTML;
        bouton.disabled = true;
        bouton.innerHTML = `<i class="fas fa-spinner fa-spin" aria-hidden="true"></i> ${
            Utils.escapeHtml(I18n.t('annotator.asking'))}`;
        try {
            const proposition = await API.proposerLesAttributs(I18n.currentLocale);
            this.classementDesAttributs = {};
            (proposition.colonnes || []).forEach((colonne) => {
                this.classementDesAttributs[colonne.colonne] = colonne;
            });
            // Ce que la lecture n'a pas su rattacher au référentiel. Sans lui,
            // une réponse illisible et un modèle qui ne trouve rien donnaient
            // le même écran, et on cherchait du côté du référentiel un défaut
            // qui était du côté de la réponse.
            this.lectureDesAttributs = proposition.ecartees || null;
            this.renderLesAttributsProposes();
            this.loadBusinessAttributes();
        } catch (erreur) {
            Toast.error(I18n.t('common.error'),
                        erreur.message || I18n.t('annotator.unavailable'));
        } finally {
            bouton.disabled = false;
            bouton.innerHTML = libelle;
        }
    },

    /**
     * Ce que le classement propose, et ce que le calcul en dit.
     *
     * Les deux sont montrés parce qu'ils ne disent pas la même chose : le
     * modèle lit des mots, la cardinalité compte des valeurs. Quand ils se
     * contredisent — une colonne jugée « métier » mais qui porte une valeur
     * par identité —, c'est le compte qui tranche, et l'écran le dit.
     */
    renderLesAttributsProposes() {
        const zone = document.getElementById('biz-attributs-proposition');
        if (!zone) return;
        if (!this.classementDesAttributs) {
            zone.innerHTML = '';
            return;
        }
        const proposees = this.businessAttributes.filter(
            (attribut) => this.classeDe(attribut.name) === 'metier');
        const desaccords = proposees.filter(
            (attribut) => attribut.recommended === false);
        // Jugées métier par le modèle, mais absentes de la liste des attributs
        // proposables : la règle de cardinalité les a écartées en amont. Les
        // taire ferait passer l'avis du modèle pour inexistant.
        const connues = new Set(this.businessAttributes.map((a) => a.name));
        const horsListe = Object.values(this.classementDesAttributs)
            .filter((c) => c.classe === 'metier' && !connues.has(c.colonne))
            .map((c) => c.colonne);

        const ecartees = this.lectureDesAttributs || {};
        const illisibles = (ecartees.colonnes_inconnues || 0)
            + (ecartees.classes_inconnues || 0);
        const rienDeLu = Object.keys(this.classementDesAttributs).length === 0;
        // « Le modèle n'a jugé aucune colonne porteuse de métier » est un avis.
        // « Rien de sa réponse n'a pu être utilisé » est une panne de lecture.
        // Les deux envoient chercher à deux endroits opposés.
        const lignes = [`<p class="form-hint">${Utils.escapeHtml(
            proposees.length
                ? I18n.t('attributs.suggested', {
                    colonnes: proposees.map((a) => a.name).join(', ') })
                : (rienDeLu && illisibles
                    ? I18n.t('attributs.nothing_read')
                    : I18n.t('attributs.none')))}</p>`];
        if (horsListe.length) {
            lignes.push(`<p class="form-hint">${Utils.escapeHtml(
                I18n.t('attributs.metier_hors_liste', {
                    colonnes: horsListe.join(', ') }))}</p>`);
        }
        if (desaccords.length) {
            lignes.push(`<p class="alert alert-warning">${Utils.escapeHtml(
                I18n.t('attributs.disagreement', {
                    colonnes: desaccords.map((a) => a.name).join(', ') }))}</p>`);
        }
        if (illisibles) {
            // Les mots que le modèle a employés là où trois étaient admis. Ils
            // disent en un coup d'œil que c'est le modèle qu'il faut changer,
            // et évitent d'aller lire le journal du serveur.
            const exemples = (ecartees.exemples || []).join(', ');
            lignes.push(`<p class="alert alert-warning">${Utils.escapeHtml(
                I18n.t(exemples ? 'attributs.unreadable_examples'
                                : 'attributs.unreadable',
                       { nombre: illisibles, exemples }))}</p>`);
        }
        if (ecartees.champs_intervertis) {
            lignes.push(`<p class="form-hint">${Utils.escapeHtml(
                I18n.t('attributs.swapped',
                       { nombre: ecartees.champs_intervertis }))}</p>`);
        }
        zone.innerHTML = lignes.join('');
    },

    /** La classe proposée pour une colonne, ou rien si aucune proposition. */
    classeDe(colonne) {
        const propose = this.classementDesAttributs
            && this.classementDesAttributs[colonne];
        return propose ? propose.classe : '';
    },

    async loadBusinessAttributes() {
        const container = document.getElementById('biz-attributes-container');
        if (!container) return;
        
        try {
            const data = await API.getIdentityAttributes(); 
            this.businessAttributes = data.attributes || [];
            
            let html = '';
            if (this.businessAttributes.length === 0) {
                html = `<div class="attribute-empty">${Utils.escapeHtml(I18n.t('mining.no_usable_attribute'))}</div>`;
            } else {
                this.businessAttributes.forEach(attr => {
                    // Le libelle vient d'une cle i18n renvoyee par l'API, jamais
                    // d'un texte construit cote serveur.
                    const label = attr.description_key
                        ? I18n.t(attr.description_key, Utils.parametresDansLaLangue(attr.description_params))
                        : '';
                    // Un attribut trop discriminant (ex : un nom de famille) reste
                    // proposable, mais il est signale : c'est l'utilisateur qui tranche.
                    const warn = attr.recommended === false
                        ? `<i class="fas fa-triangle-exclamation" data-definition="mining.attribute.too_discriminant" aria-hidden="true"></i>`
                        : '';
                    // La classe proposée, quand elle l'a été. Elle s'affiche à
                    // côté du compte et ne le remplace pas : le modèle lit des
                    // mots, la cardinalité compte des valeurs, et c'est le
                    // compte qui tranche.
                    const classe = MiningPage.classeDe(attr.name);
                    const propose = classe
                        ? `<span class="attribute-choice__classe">${Utils.escapeHtml(
                            I18n.t(`attributs.classe.${classe}`))}</span>`
                        : '';
                    html += `
                        <label class="attribute-choice${attr.recommended === false ? ' attribute-choice--warned' : ''}">
                            <input type="checkbox" name="biz_attribute" value="${Utils.escapeHtml(attr.name)}">
                            <span>${Utils.escapeHtml(attr.name)}</span>
                            <small class="attribute-choice__hint">${propose} ${warn} ${Utils.escapeHtml(label)}</small>
                        </label>
                    `;
                });
            }
            container.innerHTML = html;
        } catch (error) {
            container.innerHTML = `<div class="attribute-error">${Utils.escapeHtml(error.message)}</div>`;
        }
    },

    // ============================================
    // MINING MÉTIER - AVEC TABS IDENTIQUES
    // ============================================

    //: Libellé de chaque paramètre mesurable, dans les mots du formulaire.
    //  Le serveur nomme `min_coverage_pct` ; l'utilisateur lit « Couverture
    //  minimum », qui est ce qu'il a sous les yeux.
    LIBELLES_PARAMETRES: {
        min_coverage_pct: 'form.min_coverage.label',
        min_users: 'form.min_users.label',
        min_rights: 'form.min_rights.label',
        mining_depth: 'form.mining_depth.label',
        parcimonie_pct: 'form.parcimonie.label',
    },

    //: Arbitrage retenu par l'utilisateur. Il ne le saisit pas : il désigne un
    //  point de la courbe, et la valeur s'en déduit.
    arbitrageRetenu: 0.0,

    /**
     * Attributs cochés pour le mining métier.
     *
     * @returns {Array<string>} les colonnes d'identité sélectionnées.
     */
    attributsMetier() {
        return Array.from(
            document.querySelectorAll('#biz-attributes-container input:checked'))
            .map((cb) => cb.value);
    },

    /**
     * Paramètres du mining métier, tels que le formulaire les porte.
     *
     * Les bornes viennent du formulaire, jamais du code. L'objectif de
     * couverture est facultatif : vide, il vaut « aucun objectif », et non
     * zéro — ce qui n'aurait pas le même sens.
     *
     * @param {Array<string>} attributs colonnes retenues.
     * @returns {Object} le corps de la requête.
     */
    /**
     * Les profondeurs proposées suivent les attributs cochés.
     *
     * La liste était écrite dans le gabarit : trois choix, quel que soit le
     * nombre d'attributs. Cocher cinq colonnes ne permettait donc pas d'aller
     * au-delà du triplet — et n'en cocher que deux laissait proposer un
     * triplet, que le moteur bornait ensuite en silence. Un réglage qui ne fait
     * pas ce qu'il annonce est pire qu'un réglage absent.
     *
     * Le plafond du produit borne encore la liste : au-delà, le nombre de
     * combinaisons explose sans qu'aucun rôle lisible n'en sorte.
     */
    ajusterLaProfondeur() {
        const choix = document.getElementById('biz-mining-depth');
        const conteneur = document.getElementById('biz-attributes-container');
        if (!choix || !conteneur) return;

        const coches = conteneur.querySelectorAll('input:checked').length;
        // Sans attribut coché, le lancement est refusé de toute façon : une
        // liste vide ne se réparerait pas, on garde donc un choix.
        const maximum = Math.min(Math.max(1, coches), Config.MINING_MAX_DEPTH);
        const voulue = Math.min(parseInt(choix.value, 10) || 1, maximum);

        choix.innerHTML = Array.from({ length: maximum }, (_, rang) => {
            const profondeur = rang + 1;
            const libelle = profondeur === 1
                ? I18n.t('form.mining_depth.single')
                : I18n.t('form.mining_depth.crossed', { count: profondeur });
            return `<option value="${profondeur}">${Utils.escapeHtml(libelle)}</option>`;
        }).join('');
        choix.value = String(voulue);

        this.annoncerLeCoutDuCroisement();
    },

    /**
     * Combien de combinaisons d'attributs le calcul va parcourir.
     *
     * Un triplet sur cinq attributs a demandé cinq minutes sur onze mille
     * identités. Le chiffre qui explique cette durée — le nombre de
     * combinaisons — n'était nulle part, et l'utilisateur découvrait le coût
     * après l'avoir engagé.
     */
    annoncerLeCoutDuCroisement() {
        const zone = document.getElementById('biz-mining-depth-cout');
        const conteneur = document.getElementById('biz-attributes-container');
        const choix = document.getElementById('biz-mining-depth');
        if (!zone || !conteneur || !choix) return;
        const coches = conteneur.querySelectorAll('input:checked').length;
        const profondeur = parseInt(choix.value, 10) || 1;
        if (coches === 0) {
            zone.textContent = '';
            return;
        }
        let combinaisons = 0;
        let parmi = 1;
        for (let taille = 1; taille <= profondeur; taille += 1) {
            parmi = parmi * (coches - taille + 1) / taille;
            combinaisons += parmi;
        }
        zone.textContent = I18n.t('form.mining_depth.combinations',
                                  { count: Utils.formatNumber(Math.round(combinaisons)) });
    },

    /**
     * Ce que le calcul va faire, en une phrase.
     *
     * Les huit réglages du formulaire sont justes pris un par un et illisibles
     * ensemble. Un effectif minimal à trois personnes, sur un référentiel de
     * vingt et un mille identités, a produit un modèle de cinq cent
     * soixante-dix-neuf rôles de moins de cinq porteurs — et le chiffre était à
     * l'écran, dans un champ que personne n'avait relu avant de lancer.
     *
     * La phrase est assemblée depuis les valeurs saisies et réécrite à chaque
     * frappe. Elle ne dit rien que le formulaire ne dise déjà : elle le dit
     * dans l'ordre où on y pense, et en une seule fois.
     */
    recapitulerMetier() {
        const cible = document.getElementById('biz-recapitulatif');
        if (!cible) return;
        const params = this.parametresMetier([]);
        const nombre = (valeur) => Utils.formatNumber(valeur);
        const phrases = [I18n.t('mining.recap.discover', {
            personnes: nombre(params.min_users || 0),
            droits: nombre(params.min_rights || 0),
            attributs: nombre(params.mining_depth || 0),
            couverture: Utils.formatPercent(params.min_coverage || 0),
        })];
        phrases.push(typeof params.couverture_visee === 'number'
            ? I18n.t('mining.recap.keep_target',
                     { objectif: Utils.formatPercent(params.couverture_visee) })
            : I18n.t('mining.recap.keep_all'));
        if (params.parcimonie > 0) {
            phrases.push(I18n.t('mining.recap.parcimonie',
                                { part: Utils.formatPercent(params.parcimonie) }));
        }
        if (params.inclure_sans_droit) {
            phrases.push(I18n.t('mining.recap.sans_droit'));
        }
        cible.textContent = phrases.join(' ');
    },

    parametresMetier(attributs) {
        const objectif = document.getElementById('biz-couverture-visee')?.value;
        const params = {
            attributes: attributs,
            min_coverage: parseFloat(document.getElementById('biz-min-coverage')?.value),
            mining_depth: parseInt(document.getElementById('biz-mining-depth')?.value, 10),
            // Les champs de cet écran, et non ceux de l'écran applicatif. Ces
            // deux seuils décident du modèle métier — un effectif minimal à 3
            // sur 21 000 identités produit des milliers de rôles de six
            // personnes — et ils étaient lus sur un formulaire que
            // l'utilisateur n'avait pas sous les yeux.
            min_users: parseInt(document.getElementById('biz-min-users')?.value, 10),
            min_rights: parseInt(document.getElementById('biz-min-rights')?.value, 10),
            arbitrage: this.arbitrageRetenu,
            // Parcimonie : ce qu'un sous-rôle doit expliquer, en part de ce
            // qu'explique son parent, pour être retenu à côté de lui.
            parcimonie: parseFloat(
                document.getElementById('biz-parcimonie')?.value) || 0,
            // Population du calcul. Le référentiel ne dit pas si une identité
            // sans droit est un arrivant ou un partant : c'est l'utilisateur
            // qui tranche, et le défaut reproduit le comportement historique.
            inclure_sans_droit: Boolean(
                document.getElementById('biz-inclure-sans-droit')?.checked),
        };
        if (objectif) params.couverture_visee = parseFloat(objectif);
        return params;
    },

    /**
     * Calcule et affiche les compromis possibles.
     *
     * Sans objectif de couverture, tous les points se valent : le glouton
     * épuise ses candidats quel que soit l'arbitrage et seul l'ordre change.
     * L'écran le dit plutôt que de laisser croire à un choix — c'est une
     * mesure qui l'a établi, pas une intuition.
     */
    async explorerArbitrage() {
        const attributs = this.attributsMetier();
        if (attributs.length === 0) {
            Toast.warning(I18n.t('common.warning'), I18n.t('validation.select_attribute'));
            return;
        }

        const panneau = document.getElementById('biz-tradeoff-panel');
        const corps = document.getElementById('biz-tradeoff-body');
        if (!panneau || !corps) return;
        panneau.hidden = false;
        corps.innerHTML = `<p class="form-hint">${
            Utils.escapeHtml(I18n.t('mining.tradeoff.computing'))}</p>`;

        const bouton = document.getElementById('biz-explore-tradeoff');
        if (bouton) bouton.disabled = true;

        try {
            const params = this.parametresMetier(attributs);
            const reponse = await API.getTradeoffPoints(params);
            this.renderArbitrage(reponse, params.couverture_visee);
        } catch (erreur) {
            corps.innerHTML = `<p class="text-danger">${
                Utils.escapeHtml(erreur.message || I18n.t('common.error'))}</p>`;
        } finally {
            if (bouton) bouton.disabled = false;
        }
    },

    renderArbitrage(reponse, objectif) {
        const corps = document.getElementById('biz-tradeoff-body');
        if (!corps) return;

        const points = (reponse && reponse.points) || [];
        const avertissement = objectif
            ? ''
            : `<p class="key-policy-alert severity-info">${
                Utils.escapeHtml(I18n.t('mining.tradeoff.needs_target'))}</p>`;

        const entetes = ['roles', 'coverage', 'over_granted']
            .map((cle) => `<th scope="col">${Utils.escapeHtml(
                I18n.t(`mining.tradeoff.col.${cle}`))}</th>`).join('')
            // Comparer deux positions du curseur sur le seul coût du calcul
            // conduirait à retenir la mauvaise quand les identités sans droit
            // ne sont pas comptées : la colonne du coût réel est à côté.
            + `<th scope="col">${Utils.escapeHtml(
                I18n.t('mining.stat.over_granted_if_applied'))}</th>`;

        const lignes = points.map((point) => {
            const courant = point.arbitrage === this.arbitrageRetenu;
            const action = courant
                ? `<span class="tradeoff-current">${Utils.escapeHtml(
                    I18n.t('mining.tradeoff.current'))}</span>`
                : `<button type="button" class="btn-link btn-sm"
                        data-arbitrage="${Utils.escapeHtml(String(point.arbitrage))}">${
                    Utils.escapeHtml(I18n.t('mining.tradeoff.choose'))}</button>`;
            const alerte = point.objectif_atteint ? '' : `<div class="form-hint">${
                Utils.escapeHtml(I18n.t('mining.tradeoff.not_reached'))}</div>`;
            return `<tr class="${courant ? 'tradeoff-row current' : 'tradeoff-row'}">
                <td>${Utils.escapeHtml(String(Utils.valeurDansLaLangue(point.roles)))}</td>
                <td>${Utils.escapeHtml(Utils.formatPercent(point.habs_coverage_pct))}</td>
                <td>${Utils.escapeHtml(Utils.formatNumber(point.over_provisioning_distinct))}</td>
                <td>${Utils.escapeHtml(Utils.formatNumber(
                    point.over_provisioning_if_applied || 0))}</td>
                <td>${action}${alerte}</td>
            </tr>`;
        }).join('');

        corps.innerHTML = `${avertissement}
            <table class="key-policy-table">
                <thead><tr>${entetes}<th scope="col"></th></tr></thead>
                <tbody>${lignes}</tbody>
            </table>`;
    },

    /**
     * Retient un compromis et relance l'analyse avec.
     *
     * Le nombre n'est jamais saisi : il vient du point désigné.
     */
    retenirArbitrage(valeur) {
        this.arbitrageRetenu = valeur;
        return this.launchBusinessMining();
    },

    /**
     * Mesure l'effet d'un paramètre sur les données chargées.
     *
     * Une définition dit ce qu'un paramètre signifie ; elle ne dira jamais ce
     * que 70 % plutôt que 80 % change sur le référentiel qu'on a sous les yeux.
     *
     * @param {string} parametre nom du paramètre, dans le vocabulaire du moteur.
     */
    async mesurerImpact(parametre) {
        const attributs = this.attributsMetier();
        if (attributs.length === 0) {
            Toast.warning(I18n.t('common.warning'), I18n.t('validation.select_attribute'));
            return;
        }

        const panneau = document.getElementById('biz-impact-panel');
        if (!panneau) return;
        panneau.innerHTML = `<p class="form-hint">${
            Utils.escapeHtml(I18n.t('mining.impact.computing'))}</p>`;

        try {
            const params = this.parametresMetier(attributs);
            const actuelle = this.valeurActuelle(parametre, params);
            const reponse = await API.getParameterImpact(Object.assign({}, params, {
                parameter: parametre,
                values: this.valeursAEssayer(parametre, actuelle),
            }));
            this.renderImpact(reponse, actuelle);
        } catch (erreur) {
            panneau.innerHTML = `<p class="text-danger">${
                Utils.escapeHtml(erreur.message || I18n.t('common.error'))}</p>`;
        }
    },

    /** Valeur en vigueur d'un paramètre, dans le vocabulaire du moteur. */
    valeurActuelle(parametre, params) {
        const correspondance = {
            min_coverage_pct: params.min_coverage,
            min_users: params.min_users,
            min_rights: params.min_rights,
            mining_depth: params.mining_depth,
            parcimonie_pct: params.parcimonie,
        };
        return correspondance[parametre];
    },

    /**
     * Trois valeurs à essayer autour de celle en vigueur.
     *
     * Encadrer plutôt que balayer : l'utilisateur veut savoir ce qu'il gagne
     * ou perd à bouger d'un cran, pas explorer tout le domaine — et chaque
     * valeur coûte une analyse complète.
     */
    valeursAEssayer(parametre, actuelle) {
        // La parcimonie se joue dans les premiers pour-cent : mesuré, tout
        // se passe entre zéro et cinq, et au-delà le réglage cesse de retirer
        // des raffinements pour commencer à manger de vraies règles. Un pas
        // d'un point y balaierait le domaine utile en trois essais et
        // n'apprendrait rien à l'utilisateur.
        // Un seuil d'effectif est une grandeur d'échelle : passer de 3 à 4
        // est un changement d'un tiers, de 30 à 31 de trois pour cent. Un pas
        // additif y balaie l'insignifiant en bas et le rien en haut, et il
        // fallait quatre mesures — quatre minings complets — pour aller de 3 à
        // 24. L'encadrement se fait donc en doublant.
        if (parametre === 'min_users') {
            const essais = [Math.max(2, Math.floor(actuelle / 2)), actuelle, actuelle * 2];
            return Array.from(new Set(essais));
        }
        const pas = {min_coverage_pct: 10, parcimonie_pct: 1.5}[parametre] || 1;
        const minimum = 0;
        const essais = [actuelle - pas, actuelle, actuelle + pas]
            .filter((v) => v >= (parametre === 'parcimonie_pct' ? minimum : 1))
            .filter((v) => parametre !== 'min_coverage_pct' || v <= 100);
        return Array.from(new Set(essais));
    },

    renderImpact(reponse, actuelle) {
        const panneau = document.getElementById('biz-impact-panel');
        if (!panneau) return;

        const points = (reponse && reponse.points) || [];
        const titre = I18n.t('mining.impact.title',
                             { parameter: I18n.t(this.LIBELLES_PARAMETRES[reponse.parameter]) });

        const entetes = [
            I18n.t('mining.impact.col.value'),
            I18n.t('mining.tradeoff.col.roles'),
            I18n.t('mining.tradeoff.col.coverage'),
            I18n.t('mining.tradeoff.col.over_granted'),
            I18n.t('mining.stat.over_granted_if_applied'),
            // Le chiffre que la parcimonie fait bouger. Il figure pour tous
            // les paramètres : un seuil de couverture change lui aussi le
            // nombre de sous-rôles, et l'utilisateur n'avait aucun moyen de
            // le voir.
            I18n.t('mining.impact.col.stratifications'),
        ].map((libelle) => `<th scope="col">${Utils.escapeHtml(libelle)}</th>`).join('');

        const lignes = points.map((point) => {
            const courant = Number(point.value) === Number(actuelle);
            return `<tr class="${courant ? 'tradeoff-row current' : 'tradeoff-row'}">
                <td>${Utils.escapeHtml(String(Utils.valeurDansLaLangue(point.value)))}${courant
                    ? ` <span class="tradeoff-current">${Utils.escapeHtml(
                        I18n.t('mining.impact.current'))}</span>` : ''}</td>
                <td>${Utils.escapeHtml(String(Utils.valeurDansLaLangue(point.roles)))}</td>
                <td>${Utils.escapeHtml(Utils.formatPercent(point.habs_coverage_pct))}</td>
                <td>${Utils.escapeHtml(Utils.formatNumber(point.over_provisioning_distinct))}</td>
                <td>${Utils.escapeHtml(Utils.formatNumber(
                    point.over_provisioning_if_applied || 0))}</td>
                <td>${Utils.escapeHtml(Utils.formatNumber(
                    point.stratifications || 0))}</td>
            </tr>`;
        }).join('');

        panneau.innerHTML = `<h3 class="file-config-title">${Utils.escapeHtml(titre)}</h3>
            <table class="key-policy-table">
                <thead><tr>${entetes}</tr></thead>
                <tbody>${lignes}</tbody>
            </table>`;
    },

    async launchBusinessMining() {
        const btn = document.getElementById('launch-business-mining');
        if (!btn) return;
        
        const originalText = btn.innerHTML;
        const selectedAttributes = Array.from(document.querySelectorAll('#biz-attributes-container input:checked'))
                                      .map(cb => cb.value);
        
        if (selectedAttributes.length === 0) {
            Toast.warning(I18n.t('common.warning'), I18n.t('validation.select_attribute'));
            return;
        }

        try {
            btn.innerHTML = `<i class="fas fa-spinner fa-spin" aria-hidden="true"></i> ${
                Utils.escapeHtml(I18n.t('mining.analysing'))}`;
            btn.disabled = true;

            // Les bornes viennent du formulaire, jamais du code : `min_users`
            // et `min_rights` y étaient écrits en dur (5 et 1) et
            // contredisaient les valeurs saisies dans les paramètres du
            // workspace, que le mining applicatif respecte pourtant.
            const params = this.parametresMetier(selectedAttributes);

            const data = await API.launchBusinessMining(params); 
            this.handleBusinessMiningSuccess(data);

            // Un mining renouvelle les candidats : ce qu'il reste à décider aussi.
            if (typeof Cloche !== 'undefined') Cloche.rafraichir();
            this.annoncerRunConserve('METIER');

        } catch (error) {
            Toast.error(I18n.t('common.error'), error.message);
        } finally {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    },

    /**
     * Affiche un résultat de mining métier.
     *
     * `annoncer` : voir `handleAppMiningSuccess`. Un mining qui se termine est
     * une nouvelle ; un résultat repris n'en est pas une.
     */
    handleBusinessMiningSuccess(data, { annoncer = true } = {}) {
        // Ce que l'affichage coûte, mesuré ici et nulle part ailleurs : le
        // serveur rend sa propre décomposition, et c'est la comparaison des
        // deux qui dit où part l'attente. Sans elle, « c'est lent » ne
        // distingue pas un calcul long d'un écran qui peine à dessiner mille
        // sept cents cartes.
        const departAffichage = performance.now();
        this.results = data.top_roles || [];
        // Les noms déjà pris. Ils servent à prévenir avant de faire relire des
        // centaines d'identités ; le serveur reste seul juge et refusera de
        // toute façon un nom pris.
        this.nomsDuCatalogue.biz = data.noms_du_catalogue || [];

        // Les indicateurs viennent du serveur. Ils étaient recalculés ici à
        // partir des rôles reçus, et la « couverture moyenne » affichée était
        // la moyenne non pondérée des couvertures de chaque rôle — pas la
        // couverture du modèle. Un chiffre de gouvernance ne se calcule pas
        // dans la page.
        this.dernieresStatsBiz = data.global_stats || {};
        this.renderGlobalStats(this.dernieresStatsBiz);
        
        const resultsContainer = document.getElementById('business-mining-results');
        if (!resultsContainer) return;
        
        const kbIntegration = data.global_stats?.kb_integration;
        if (annoncer && kbIntegration) {
            Toast.info(I18n.t('mining.kb_filtering'), I18n.t('mining.kb_integration', { birthrights: kbIntegration.birth_rights_excluded, validated: kbIntegration.validated_roles_filtered }));
        }
        
        if (this.results.length === 0) {
            resultsContainer.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon"><i class="fas fa-sitemap" aria-hidden="true"></i></div>
                    <h3>${I18n.t('empty.no_roles_found')}</h3>
                    <p>${I18n.t('validation.try_lower_coverage')}</p>
                </div>
            `;
            if (annoncer) Toast.warning(I18n.t('common.warning'), I18n.t('empty.no_roles_found'));
        } else {
            this.renderBusinessResults(this.results);
            if (annoncer) Toast.success(I18n.t('common.success'), I18n.t('success.roles_found', { count: this.results.length }));
        }
        this.majBoutonDeNommageEnLot('biz', this.results.length);

        this.annoncerLesDurees(this.dernieresStatsBiz.durees_ms,
                               performance.now() - departAffichage);
    },

    /**
     * Le temps du calcul et celui de l'affichage, côte à côte.
     *
     * Une lenteur qu'on ne sait pas situer se discute au lieu de se corriger.
     * Les deux chiffres répondent à la seule question qui compte quand on
     * attend : est-ce le serveur, ou est-ce l'écran ?
     */
    annoncerLesDurees(dureesServeur, dureeAffichage) {
        const zone = document.getElementById('biz-durees');
        if (!zone) return;
        const calcul = (dureesServeur || {}).total;
        if (calcul === undefined || calcul === null) {
            zone.hidden = true;
            return;
        }
        zone.hidden = false;
        zone.textContent = I18n.t('mining.durees', {
            calcul: MiningPage.dureeLisible(calcul),
            affichage: MiningPage.dureeLisible(dureeAffichage),
        });
    },

    /** Une durée en millisecondes, dans l'unité qui se lit. */
    dureeLisible(millisecondes) {
        const valeur = Number(millisecondes) || 0;
        return valeur >= 1000
            ? `${Utils.formatDecimal(valeur / 1000, 1)} s`
            : `${Math.round(valeur)} ms`;
    },

    /**
     * Bandeau d'indicateurs du mining métier.
     *
     * La fonction acceptait un paramètre `type` et portait une seconde
     * branche pour le mining applicatif — que rien n'appelait : celui-ci
     * remplit `showGlobalStatsGrid`, une grille distincte du gabarit. Deux
     * rendus pour le même besoin, dont un mort.
     */
    /**
     * Indicateurs du modèle métier.
     *
     * Ils étaient fabriqués ici, dans une famille de classes propre à cet
     * écran, et insérés dans le DOM au rendu. Ils sont désormais déclarés dans
     * le gabarit, avec les mêmes tuiles que l'écran applicatif : cette
     * fonction ne fait plus que les renseigner.
     */
    renderGlobalStats(stats) {
        const conteneur = document.getElementById('biz-global-stats');
        if (conteneur) conteneur.style.display = '';

        const ecrire = (identifiant, valeur) => {
            const cible = document.getElementById(identifiant);
            if (cible) cible.textContent = valeur;
        };

        ecrire('biz-roles-count', Utils.formatNumber(stats.total_roles_found || 0));
        ecrire('biz-users-impacted', Utils.formatNumber(stats.total_users || 0));
        ecrire('biz-rights-covered', Utils.formatNumber(stats.total_rights || 0));
        ecrire('biz-avg-coverage', Utils.formatPercent(stats.avg_coverage || 0));
        // La couverture sans son coût ne dit que la moitié de l'arbitrage :
        // cet écran n'affichait pas le sur-octroi, que le serveur calcule
        // pourtant depuis toujours.
        //
        // Le chiffre affiché était celui des agrégats, additionné rôle par
        // rôle et rapporté à ce que le modèle accorde : deux rôles octroyant
        // le même couple le comptaient deux fois, et le pourcentage ne se
        // comparait pas à la couverture posée juste à côté. On prend celui de
        // la mesure du modèle, dédupliqué et rapporté aux habilitations
        // existantes.
        const qualiteMetier = stats.quality || {};
        ecrire('biz-over-granted', typeof qualiteMetier.over_granted_pct === 'number'
            ? Utils.formatPercent(qualiteMetier.over_granted_pct)
            : '-');

        // Coût d'une attribution réelle. Il ne se déduit pas du pourcentage
        // voisin : celui-ci porte sur la population calculée, celui-là sur
        // celle que la règle RH désignera le jour de l'attribution.
        ecrire('biz-over-granted-applied',
               Utils.formatNumber(stats.over_provisioning_if_applied || 0));

        this.renderBusinessSummary(stats);
        this.renderPopulationSummary(stats);
        ecrire('biz-results-count',
               I18n.t('mining.results_count', { count: stats.total_roles_found || 0 }));
    },

    /**
     * Ouvre le détail des identités sans droit, règle par règle.
     *
     * Le serveur le calcule sur les candidats **conservés** : le tableau doit
     * décrire le modèle affiché, et un mining relancé rendrait autre chose dès
     * qu'un paramètre a bougé.
     */
    async ouvrirDetailPopulation() {
        const corps = document.getElementById('population-detail-body');
        const alerte = document.getElementById('population-detail-alert');
        if (!corps) return;

        // Son propre message : celui de la mesure d'impact annonce que « chaque
        // valeur relance une analyse complète », ce que ce panneau ne fait pas
        // — il relit les candidats conservés. Emprunter un texte, c'est dire
        // au lecteur qu'il attend autre chose que ce qu'il attend.
        corps.innerHTML = `<p class="form-hint">${
            Utils.escapeHtml(I18n.t('mining.population.detail_loading'))}</p>`;
        if (alerte) alerte.hidden = true;
        Modal.open('population-detail-modal');

        try {
            const reponse = await API.getPopulationDetail();
            this.renderDetailPopulation(reponse);
        } catch (erreur) {
            corps.innerHTML = `<p class="text-danger">${
                Utils.escapeHtml(I18n.t('mining.population.detail_failed'))}</p>`;
        }
    },

    //: Groupes du dernier détail affiché. Le bouton d'une ligne agit sur eux.
    groupesDetail: [],

    /**
     * Écarte du périmètre les identités sans droit d'un groupe.
     *
     * L'exclusion est **nominative** et non une règle : une règle sur les
     * critères du groupe en écarterait tous les membres, y compris ceux qui
     * détiennent des droits et que le modèle explique très bien.
     *
     * Le motif est exigé. Écarter une population sans dire pourquoi est
     * précisément ce qu'une piste d'audit existe pour empêcher, et c'est le
     * genre de décision qu'on relit des mois plus tard.
     *
     * @param {number} index rang du groupe dans le détail affiché.
     */
    async exclureGroupe(index) {
        const groupe = this.groupesDetail[index];
        if (!groupe || !(groupe.identities || []).length) return;

        const motif = await Confirm.demander({
            titre: I18n.t('perimeter.excluded.title'),
            message: I18n.t('perimeter.exclude_group_confirm',
                            { count: Utils.formatNumber(groupe.identities.length) }),
            details: Object.entries(groupe.criteria || {})
                .map(([nom, valeur]) => `${nom} = ${valeur}`),
            danger: true,
            saisie: { label: I18n.t('perimeter.excluded.title') },
        });
        if (motif === false) return;

        try {
            const reponse = await API.excludeUsers(groupe.identities, motif);
            const ajoutees = (reponse && reponse.added) || [];
            if (ajoutees.length) {
                Toast.success(I18n.t('common.success'), I18n.t('perimeter.exclude_done',
                              { count: Utils.formatNumber(ajoutees.length) }));
            } else {
                // Ne rien annoncer serait pire : l'utilisateur croirait avoir
                // agi. Le dire évite qu'il relance une analyse pour rien.
                Toast.warning(I18n.t('common.warning'), I18n.t('perimeter.exclude_none'));
            }
        } catch (erreur) {
            Toast.error(I18n.t('common.error'), I18n.t('perimeter.exclude_failed'));
        }
    },

    renderDetailPopulation(reponse) {
        const corps = document.getElementById('population-detail-body');
        const alerte = document.getElementById('population-detail-alert');
        if (!corps) return;

        // Un tableau qui décrit un référentiel rechargé depuis induirait en
        // erreur au moment précis où il sert à décider.
        if (alerte) {
            alerte.hidden = !(reponse && reponse.stale);
            if (reponse && reponse.stale) {
                alerte.textContent = I18n.t('mining.population.detail_stale');
            }
        }

        const groupes = (reponse && reponse.groups) || [];
        if (groupes.length === 0) {
            corps.innerHTML = `<p class="form-hint">${Utils.escapeHtml(I18n.t(
                reponse && reponse.computed_at
                    ? 'mining.population.detail_empty'
                    : 'mining.population.detail_none'))}</p>`;
            return;
        }

        const entetes = ['criteria', 'group', 'without_rights', 'share', 'rights', 'cost']
            .map((cle) => `<th scope="col">${Utils.escapeHtml(
                I18n.t(`mining.population.col.${cle}`))}</th>`).join('') + '<th scope="col"></th>';

        // Conservés pour l'action : le bouton d'une ligne doit écarter les
        // identités de cette ligne, et non les rechercher dans le DOM.
        this.groupesDetail = groupes;

        const lignes = groupes.map((groupe, index) => {
            const criteres = Object.entries(groupe.criteria || {})
                .map(([nom, valeur]) => `${nom} = ${valeur}`).join(', ');
            return `<tr class="tradeoff-row">
                <td>${Utils.escapeHtml(criteres)}</td>
                <td>${Utils.escapeHtml(Utils.formatNumber(groupe.group_size))}</td>
                <td>${Utils.escapeHtml(Utils.formatNumber(groupe.without_rights))}</td>
                <td>${Utils.escapeHtml(Utils.formatPercent(groupe.share_pct))}</td>
                <td>${Utils.escapeHtml(Utils.formatNumber(groupe.rights_count))}</td>
                <td>${Utils.escapeHtml(Utils.formatNumber(groupe.over_provisioning))}</td>
                <td>${groupe.identities && groupe.identities.length
                    ? `<button type="button" class="btn-link btn-sm"
                               data-exclure-groupe="${index}">${Utils.escapeHtml(
                           I18n.t('perimeter.exclude_group'))}</button>`
                    : ''}</td>
            </tr>`;
        }).join('');

        corps.innerHTML = `<table class="key-policy-table">
                <thead><tr>${entetes}</tr></thead>
                <tbody>${lignes}</tbody>
            </table>`;
    },

    /**
     * Ce que le choix de population laisse de côté, en une phrase.
     *
     * Rendue que la case soit cochée ou non : l'utilisateur doit savoir
     * combien d'identités son choix concerne, et ce que le sur-octroi affiché
     * compte ou ne compte pas. Une omission silencieuse est précisément ce que
     * ce produit corrige partout ailleurs.
     *
     * @param {Object} stats indicateurs du modèle, tels que le serveur les rend.
     */
    renderPopulationSummary(stats) {
        const resume = document.getElementById('biz-population-summary');
        if (!resume) return;

        const sansDroit = stats.identities_without_rights || 0;
        if (!sansDroit) {
            resume.textContent = '';
            const vide = document.getElementById('biz-population-detail');
            if (vide) vide.hidden = true;
            return;
        }

        const touchees = stats.identities_without_rights_in_roles || 0;
        const phrases = [I18n.t('mining.population.without_rights', {
            count: Utils.formatNumber(sansDroit),
        })];
        if (touchees) {
            phrases.push(I18n.t('mining.population.touched', {
                count: Utils.formatNumber(touchees),
            }));
        }

        // Le bouton n'apparaît que si une règle touche vraiment quelqu'un :
        // ouvrir un tableau vide n'apprend rien.
        const bouton = document.getElementById('biz-population-detail');
        if (bouton) bouton.hidden = !touchees;

        const compte = stats.over_provisioning_distinct || 0;
        const applique = stats.over_provisioning_if_applied || 0;
        // L'écart, et non la case, décide de la phrase : c'est lui que
        // l'utilisateur doit lire, et il vaut zéro dès que le calcul porte
        // déjà sur tout le monde.
        phrases.push(applique > compte
            ? I18n.t('mining.population.uncounted', {
                applied: Utils.formatNumber(applique),
                counted: Utils.formatNumber(compte),
            })
            : I18n.t('mining.population.counted'));
        resume.textContent = phrases.join(' ');
    },

    /**
     * Phrase de synthèse du modèle métier.
     *
     * L'écran applicatif en avait une, l'écran métier non : le même travail
     * était rendu une fois en toutes lettres et une fois en tuiles muettes.
     */
    renderBusinessSummary(stats) {
        const resume = document.getElementById('biz-model-summary');
        if (!resume) return;

        const roles = stats.total_roles_found || 0;
        if (!roles) {
            resume.textContent = '';
            return;
        }

        // Le sur-octroi dédupliqué, et le pourcentage qui va avec — celui
        // de la tuile voisine. La phrase annonçait la somme rôle par rôle
        // rapportée à ce que le modèle accorde : deux chiffres différents pour
        // la même question, à deux endroits du même écran, 12,4 % ici et
        // 6,06 % à côté sur le même modèle.
        const qualite = stats.quality || {};
        const phrases = [I18n.t('mining.business_summary', {
            roles: Utils.formatNumber(roles),
            users: Utils.formatNumber(stats.total_users || 0),
            rights: Utils.formatNumber(stats.total_rights || 0),
            over: Utils.formatNumber(stats.over_provisioning_distinct || 0),
            pct: Utils.formatPercent(qualite.over_granted_pct || 0),
        })];
        const effet = this.phraseEffetDuModele(stats.quality);
        if (effet) phrases.push(effet);
        const acquis = this.phraseModeleComplet(stats);
        if (acquis) phrases.push(acquis);
        const forme = this.phraseFormeDuModele(stats.forme);
        if (forme) phrases.push(forme);
        resume.textContent = phrases.join(' ');
        this.renderPaliers(stats.forme);
    },

    /**
     * Les paliers du modèle, reportables dans la couverture visée.
     *
     * L'écran applicatif reporte déjà un seuil de sa courbe dans son
     * formulaire ; l'écran métier annonçait ses paliers en toutes lettres sans
     * qu'on puisse les saisir. Le chiffre reporté est celui que le serveur a
     * traduit dans l'unité du champ — une part du référentiel, et non du
     * modèle : les deux dénominateurs diffèrent, et la conversion n'appartient
     * pas à la page.
     */
    renderPaliers(forme) {
        const zone = document.getElementById('biz-paliers');
        if (!zone) return;

        const paliers = (forme?.paliers || [])
            .filter((palier) => palier.couverture !== null
                             && palier.couverture !== undefined);
        // Un modèle qu'aucun palier n'abrège n'a rien à proposer.
        if (!paliers.length || !forme.total_roles
            || paliers[paliers.length - 1].roles >= forme.total_roles) {
            zone.hidden = true;
            zone.innerHTML = '';
            return;
        }

        zone.hidden = false;
        zone.innerHTML = `
            <span class="paliers__intitule">${
                Utils.escapeHtml(I18n.t('mining.steps.label'))}</span>
            ${paliers.map((palier) => `
                <button type="button" class="btn btn-secondary btn-sm"
                        data-palier="${Utils.escapeHtml(String(palier.couverture))}">
                    ${Utils.escapeHtml(I18n.t('mining.steps.option', {
                        part: Utils.formatPercent(palier.part * 100),
                        roles: Utils.formatNumber(palier.roles),
                    }))}
                </button>`).join('')}`;

        zone.querySelectorAll('[data-palier]').forEach((bouton) => {
            bouton.addEventListener('click',
                () => this.retenirPalier(bouton.dataset.palier));
        });
    },

    /** Reporte un palier dans la couverture visée du formulaire. */
    retenirPalier(couverture) {
        const champ = document.getElementById('biz-couverture-visee');
        if (!champ) return;
        champ.value = couverture;
        Toast.success(I18n.t('common.success'),
                      I18n.t('mining.steps.applied', {
                          value: Utils.formatPercent(parseFloat(couverture)),
                      }));
    },

    /**
     * La forme du modèle, en une phrase.
     *
     * « 1 751 rôles » est un compte, pas une information : il ne dit ni par où
     * commencer, ni si ces rôles sont des règles ou des poignées de gens. Les
     * deux chiffres ci-dessous répondent aux deux questions, et chacun mène à
     * un réglage différent — la couverture visée pour le premier, l'effectif
     * minimal pour le second.
     *
     * La part est celle **du modèle**, pas celle du référentiel : elle dit
     * quelle fraction de ce que ce modèle explique est portée par ses premiers
     * rôles. Ce qu'il explique du référentiel entier est la couverture, rendue
     * dans la tuile voisine.
     */
    /**
     * Où en est le modèle **complet**, catalogue compris.
     *
     * La couverture annoncée ne décrivait que les candidats. Après avoir
     * validé la moitié de son catalogue, l'utilisateur lisait encore un
     * chiffre calculé comme s'il n'avait rien décidé — sur l'indicateur
     * central du produit.
     *
     * Rien à dire sur un espace de travail neuf : sans catalogue, la phrase
     * répéterait la précédente.
     */
    phraseModeleComplet(stats) {
        const acquise = stats.acquired_coverage_pct;
        if (!acquise) return '';
        return I18n.t('mining.model_with_catalogue', {
            acquise: Utils.formatPercent(acquise),
            complete: Utils.formatPercent(stats.model_coverage_pct || acquise),
        });
    },

    phraseFormeDuModele(forme) {
        if (!forme || !forme.total_roles) return '';
        const phrases = [];

        const paliers = forme.paliers || [];
        const moitie = paliers.find(palier => palier.part === 0.5);
        const essentiel = paliers.find(palier => palier.part === 0.9);
        if (moitie && essentiel && forme.total_roles > essentiel.roles) {
            phrases.push(I18n.t('mining.model_shape', {
                half: Utils.formatNumber(moitie.roles),
                most: Utils.formatNumber(essentiel.roles),
                total: Utils.formatNumber(forme.total_roles),
            }));
        }

        // La médiane des effectifs, quand elle est basse, ne dit pas que le
        // modèle est trop grand : elle dit que le seuil d'effectif est trop
        // bas. C'est une autre correction, et il faut le distinguer.
        const effectifs = forme.effectifs || {};
        if (effectifs.mediane !== undefined) {
            phrases.push(I18n.t('mining.model_sizes', {
                median: Utils.formatNumber(effectifs.mediane),
                q3: Utils.formatNumber(effectifs.q3),
            }));
        }
        return phrases.join(' ');
    },

    /**
     * Ce que le modèle change réellement, en une phrase.
     *
     * C'est l'objectif du produit — diminuer les attributions données en
     * direct — et il n'apparaissait sur aucun écran. Les deux chiffres sont
     * dédupliqués et rapportés au même dénominateur : les habilitations qui
     * existent aujourd'hui.
     *
     * @param {Object} qualite mesure du modèle rendue par le serveur.
     * @returns {string} la phrase, ou une chaîne vide si la mesure est absente
     *   ou incomplète — mieux vaut ne rien dire qu'un chiffre approché.
     */
    phraseEffetDuModele(qualite) {
        const q = qualite || {};
        if (typeof q.covered_assignments !== 'number'
            || typeof q.over_granted !== 'number'
            || typeof q.coverage_pct !== 'number'
            || typeof q.over_granted_pct !== 'number') {
            return '';
        }
        return I18n.t('mining.model.effet', {
            reprises: Utils.formatNumber(q.covered_assignments),
            couverture: Utils.formatPercent(q.coverage_pct),
            creees: Utils.formatNumber(q.over_granted),
            sur_octroi: Utils.formatPercent(q.over_granted_pct),
        });
    },

    renderBusinessResults(results) {
        const container = document.getElementById('business-mining-results');
        if (!container) return;
        
        container.innerHTML = '';
        
        results.forEach((role, index) => {
            const card = document.createElement('div');
            // Toute la carte porte l'action, pas seulement son bouton : c'est
            // une cible de vingt fois la surface, et l'écran répond alors au
            // survol comme le reste du produit. Le bouton reste — c'est lui qui
            // rend l'action atteignable au clavier, ce qu'une carte ne peut pas
            // faire sans emprisonner les marqueurs de définition qu'elle
            // contient dans un élément focusable.
            card.className = 'mining-role-card surface-actionnable';
            card.dataset.index = index;
            card.dataset.miningRole = 'biz';
            card.dataset.miningIndex = index;
            // Ce que la règle accorderait à des membres qui ne le détiennent
            // pas : le coût du rôle, affiché comme sur la carte applicative.
            const enTrop = role.stats_over_provisioning || 0;
            const surOctroi = enTrop > 0
                ? `<span class="mining-role-stat mining-role-stat--warned" data-definition="mining.role.over_granted_hint"><i class="fas fa-triangle-exclamation" aria-hidden="true"></i> ${Utils.escapeHtml(I18n.t('mining.role.over_granted_count', { count: Utils.formatNumber(enTrop) }))}</span>`
                : '';
            card.innerHTML = `
                <div class="mining-role-header">
                    <span class="mining-role-title">${Utils.escapeHtml(role.name || I18n.t('role.unnamed'))}</span>
                    <span class="badge badge-role-biz">${Utils.escapeHtml(I18n.t('role.type.business'))}</span>
                </div>
                <div class="mining-role-description">${Utils.escapeHtml(this.roleDescription(role))}</div>
                <div class="mining-role-stats">
                    <span class="mining-role-stat"><i class="fas fa-users" aria-hidden="true"></i> ${Utils.escapeHtml(I18n.t('unit.users', { count: Utils.formatNumber(role.user_count || 0) }))}</span>
                    <span class="mining-role-stat"><i class="fas fa-key" aria-hidden="true"></i> ${Utils.escapeHtml(I18n.t('unit.rights', { count: Utils.formatNumber(role.right_count || role.rights?.length || 0) }))}</span>
                    <span class="mining-role-stat"><i class="fas fa-percentage" aria-hidden="true"></i> ${Utils.escapeHtml(I18n.t('unit.coverage', { value: Utils.formatDecimal(role.coverage_pct || 0) }))}</span>
                    ${surOctroi}
                </div>
                <div class="mining-role-criteria">
                    <strong class="mining-role-criteria__label">${Utils.escapeHtml(I18n.t('mining.role.criteria'))}</strong>
                    ${this.renderAttributeCriteria(role.attributes)}
                </div>
                ${this.renderHeritage(role)}
                ${this.renderDecisionPrise(role)}
                <button class="btn btn-primary btn-sm mining-role-action" data-mining-role="biz" data-mining-index="${index}">
                    <i class="fas fa-certificate" aria-hidden="true"></i> ${Utils.escapeHtml(I18n.t('action.validate_role'))}
                </button>
            `;
            container.appendChild(card);
        });

        // Les cartes viennent d'être écrites : leurs indices
        // portent une définition, qui doit être atteignable
        // autrement qu'à la souris.
        if (typeof Definitions !== 'undefined') Definitions.preparer(container);
        this.marquerLesCartes(container, results);
        this.scorerLesCartes(container, results);
    },

    /**
     * Marque les candidats qui enfreignent une règle de séparation.
     *
     * Avant même qu'on ouvre la fenêtre : un candidat en conflit ne se
     * découvre pas au moment de le valider, sinon on a déjà relu sa population
     * pour rien.
     *
     * Les candidats partent par paquets, à la taille que le serveur accepte,
     * tous en même temps. Contrôler carte par carte ferait autant d'allers et
     * retours que de candidats ; tout envoyer d'un bloc faisait refuser la
     * demande au-delà de 200 candidats, et le marqueur disparaissait sans un
     * mot sur les résultats les plus fournis — là où il sert le plus. Un
     * paquet refusé ne prive que ses propres cartes du marqueur.
     *
     * Les membres ne partent pas : la carte n'a besoin que de savoir s'il y a
     * conflit, et relever les détenteurs pour le chiffrer coûterait le prix
     * d'un mining pour décorer une liste.
     */
    async marquerLesCartes(container, roles) {
        const ensembles = (roles || [])
            .map((role, index) => ({cle: String(index),
                                    droits: (role.rights || []).map(String)}))
            .filter((ensemble) => ensemble.droits.length);
        if (!ensembles.length) return;
        const jeton = (this.jetonDesCartes = (this.jetonDesCartes || 0) + 1);
        const taille = Config.SEPARATION_ENSEMBLES_PAR_APPEL;
        const paquets = [];
        for (let debut = 0; debut < ensembles.length; debut += taille) {
            paquets.push(ensembles.slice(debut, debut + taille));
        }
        const rendus = await Promise.allSettled(
            paquets.map((paquet) => API.controlerLaSeparation(paquet)));
        // La liste a pu être réécrite par un autre calcul entre-temps : marquer
        // alors des cartes qui ne sont plus les mêmes désignerait les mauvaises.
        if (jeton !== this.jetonDesCartes || !container.isConnected) return;
        rendus
            .filter((issue) => issue.status === 'fulfilled')
            .flatMap((issue) => issue.value.ensembles || [])
            .forEach((ensemble) => {
                if (!(ensemble.regles || []).length) return;
                const carte = container.querySelector(
                    `.mining-role-card[data-index="${ensemble.cle}"]`);
                if (!carte || carte.querySelector('.mining-role-sod')) return;
                const stats = carte.querySelector('.mining-role-stats');
                if (!stats) return;
                stats.insertAdjacentHTML('beforeend', `
                    <span class="mining-role-stat mining-role-stat--warned mining-role-sod">
                        <i class="fas fa-scale-balanced" aria-hidden="true"></i>
                        ${Utils.escapeHtml(I18n.t('mining.separation_flagged',
                                                  {count: ensemble.regles.length}))}
                    </span>`);
            });
    },

    /**
     * « Ressemble à ce que vous validez » : le score appris des décisions du
     * workspace, posé sur chaque carte à côté des chiffres, jamais à leur place.
     *
     * Seuls les chiffres de la carte partent vers le serveur — ni porteurs ni
     * droits. Sans assez de décisions, aucune carte n'est marquée, et une
     * phrase dit combien il en manque : un score appris sur six décisions se
     * lirait comme un avis. Le score ordonne l'attention ; il ne décide rien.
     */
    async scorerLesCartes(container, roles) {
        const candidats = (roles || []).map((role, index) => ({
            cle: String(index),
            indicateurs: this.indicateursDuScore(role),
        }));
        if (!candidats.length) return;
        const jeton = (this.jetonDuScore = (this.jetonDuScore || 0) + 1);
        let rendu;
        try {
            rendu = await API.post('/apprentissage/ressemblance', {candidats});
        } catch (erreur) {
            return;
        }
        if (jeton !== this.jetonDuScore || !container.isConnected) return;
        container.querySelector('.mining-apprentissage')?.remove();
        container.insertAdjacentHTML('afterbegin', `<div class="mining-apprentissage form-hint">${
            rendu.pret
                ? Utils.escapeHtml(I18n.t('apprentissage.bandeau', {decisions: rendu.decisions}))
                : ApprentissagePage.phraseDEtat(rendu)}</div>`);
        (rendu.candidats || []).forEach((score) => {
            if (!score.comparable) return;
            const carte = container.querySelector(
                `.mining-role-card[data-index="${score.cle}"]`);
            const stats = carte?.querySelector('.mining-role-stats');
            if (!stats || carte.querySelector('.mining-role-ressemblance')) return;
            stats.insertAdjacentHTML('beforeend', `
                <span class="mining-role-stat mining-role-ressemblance"
                      title="${Utils.escapeHtml(this.raisonsDuScore(score))}">
                    <i class="fas fa-graduation-cap" aria-hidden="true"></i>
                    ${Utils.escapeHtml(I18n.t('apprentissage.carte',
                                              {pct: Utils.formatNumber(score.probabilite_pct)}))}
                    <span class="mining-role-ressemblance__raisons">${
                        Utils.escapeHtml(this.raisonsDuScore(score))}</span>
                    ${score.toile ? `<span class="mining-role-toile">${Toile.svg(
                        rendu.axes_de_la_toile, score.toile, rendu.toile_des_validees)}${Toile.legende(
                        rendu.axes_de_la_toile, score.toile, rendu.toile_des_validees)}</span>` : ''}
                </span>`);
        });
    },

    /** Les seuls chiffres que le score connaît, pris sur la carte. */
    indicateursDuScore(role) {
        const indicateurs = this.indicateursDeDecision(role) || {};
        const retenus = {};
        ['right_count', 'user_count', 'over_granted', 'fit_pct', 'redundancy_pct']
            .forEach((cle) => {
                if (typeof indicateurs[cle] === 'number') retenus[cle] = indicateurs[cle];
            });
        return retenus;
    },

    /** Les deux raisons les plus fortes, dans le sens où elles tirent. */
    raisonsDuScore(score) {
        return (score.contributions || []).slice(0, 2)
            .filter((une) => une.contribution !== 0)
            .map((une) => I18n.t(une.contribution > 0 ? 'apprentissage.raison.pour'
                                                      : 'apprentissage.raison.contre',
                                 {grandeur: I18n.t(`apprentissage.grandeur.${une.grandeur}`)}))
            .join(' · ');
    },

    /**
     * Ce que ce candidat est déjà devenu, s'il a déjà été tranché.
     *
     * Un candidat validé revient identique à chaque calcul. Sans cette
     * mention, on le revalide — et la collision de nom se découvre au moment
     * d'enregistrer, après avoir relu des centaines d'identités.
     *
     * La carte reste dans la liste et l'action reste ouverte : le candidat a
     * pu donner un rôle qu'on a depuis dévalidé, ou l'organisation peut
     * vouloir en tirer un second rôle. Retirer la ligne serait décider à la
     * place de quelqu'un, et le faire en silence serait pire.
     */
    renderDecisionPrise(role) {
        const decision = role.decision;
        if (!decision || decision.verdict !== 'validee') return '';
        const cle = decision.role_name ? 'mining.already_validated'
                                       : 'mining.already_validated_gone';
        return `<div class="alert alert-warning mining-role-decision">${
            Utils.escapeHtml(I18n.t(cle, { nom: decision.role_name || '' }))}</div>`;
    },

    /**
     * Un nom que le catalogue ne porte pas encore.
     *
     * Le nom proposé venait du calcul et n'était jamais confronté au
     * catalogue : le produit proposait un nom qu'il savait pris, et la
     * collision se découvrait au clic sur « Valider et enregistrer », après la
     * relecture de centaines d'identités.
     *
     * Le suffixe est un numéro et non un mot. Le produit ne sait pas ce qui
     * distingue ce candidat du rôle qui porte déjà ce nom — sur un cas réel,
     * deux rôles de même intitulé portaient des droits entièrement différents
     * — et inventer un qualificatif lui ferait dire quelque chose de faux.
     * L'utilisateur corrige, et l'avertissement lui dit pourquoi.
     */
    nomLibrePour(role, prefixe) {
        const propose = role.name || '';
        const pris = new Set(this.nomsDuCatalogue[prefixe] || []);
        if (!propose || !pris.has(propose)) return propose;
        for (let suffixe = 2; suffixe <= MiningPage.SUFFIXES_MAX; suffixe += 1) {
            const essai = `${propose}_${suffixe}`;
            if (!pris.has(essai)) return essai;
        }
        // Le catalogue porte déjà toutes les variantes : mieux vaut rendre le
        // nom d'origine et laisser le serveur refuser, que d'en fabriquer un
        // que personne n'a voulu.
        return propose;
    },

    /**
     * Ce qu'il faut savoir **avant** de relire la population.
     *
     * Deux faits distincts, qui ne se règlent pas au même endroit : ce
     * candidat a déjà été tranché, et le nom que le calcul propose est déjà
     * porté par un autre rôle. Les annoncer au moment d'enregistrer revient à
     * faire travailler quelqu'un pour rien — sur un cas réel, sept cent
     * soixante-deux identités relues avant le refus.
     */
    renderAvertissementDuCandidat(prefixe, role, nomPropose) {
        const zone = document.getElementById(`${prefixe}-role-avertissement`);
        if (!zone) return;
        const lignes = [];
        // Seule une validation est annoncée, et c'est tout ce qui peut
        // arriver ici : un candidat refusé est écarté des résultats en amont,
        // et une dévalidation détache le candidat de sa décision pour qu'il
        // redevienne à décider. Une branche pour un cas qui ne se produit pas
        // est une branche que personne ne peut éprouver.
        const decision = role.decision;
        if (decision && decision.verdict === 'validee') {
            lignes.push(I18n.t(decision.role_name ? 'mining.already_validated'
                                                  : 'mining.already_validated_gone',
                               { nom: decision.role_name || '' }));
        }
        if (nomPropose && nomPropose !== (role.name || '')) {
            lignes.push(I18n.t('mining.name_taken', { nom: role.name || '' }));
        }
        zone.innerHTML = lignes.map(
            (texte) => `<div class="alert alert-warning">${
                Utils.escapeHtml(texte)}</div>`).join('');
        zone.hidden = lignes.length === 0;
        this.controlerLaSeparation(prefixe, role);
    },

    /**
     * Signale les règles de séparation des tâches que ce candidat enfreindrait.
     *
     * Posé **avant** la validation plutôt qu'après : un rôle qui réunit deux
     * pouvoirs incompatibles donnera le conflit à tous ses porteurs, présents
     * et futurs, et le moment où cela coûte le moins cher à corriger est celui
     * où on le regarde.
     *
     * Le signalement s'ajoute au bloc d'avertissements sans le remplacer, et
     * **ne bloque rien** : un rôle peut légitimement réunir deux droits qu'une
     * règle sépare — parce que la règle est trop large, parce que la population
     * visée est contrôlée autrement. Refuser à la place de l'analyste ferait
     * contourner le contrôle plutôt que le respecter.
     *
     * L'appel est asynchrone et le candidat peut changer entre-temps : le rang
     * retenu au départ est comparé à celui de l'écran avant d'écrire, sans quoi
     * l'avertissement d'un candidat s'afficherait sur le suivant.
     */
    async controlerLaSeparation(prefixe, role) {
        const zone = document.getElementById(`${prefixe}-role-avertissement`);
        const droits = (role.rights || []).map(String);
        if (!zone || !droits.length) return;
        const jeton = (this.jetonDeSeparation = (this.jetonDeSeparation || 0) + 1);
        let rendu;
        try {
            // Les membres partent avec : c'est ce qui permet de chiffrer chaque
            // retrait possible, et la fenêtre est le seul endroit où ce chiffre
            // sert — la liste des cartes, elle, n'envoie que les droits.
            rendu = await API.controlerLaSeparation([{
                cle: String(role.id || prefixe),
                droits,
                membres: (role.users || []).map(String),
            }]);
        } catch (erreur) {
            // Un contrôle indisponible n'affiche rien : écrire « aucun
            // conflit » alors qu'on n'a pas pu regarder est le seul mensonge
            // que cet écran puisse produire.
            return;
        }
        if (jeton !== this.jetonDeSeparation) return;
        const enfreintes = ((rendu.ensembles || [])[0] || {}).regles || [];
        if (!enfreintes.length) return;
        zone.insertAdjacentHTML('beforeend', enfreintes.map((regle) => `
            <div class="alert alert-danger">
                <p>${Utils.escapeHtml(I18n.t('mining.separation_breached', {
                    regle: regle.libelle,
                    gauche: regle.gauche.join(', '),
                    droite: regle.droite.join(', ')}))}</p>
                ${this.renderLesRetraits(regle)}
            </div>`).join(''));
        zone.hidden = false;
    },

    /**
     * Les deux retraits possibles, avec ce que chacun coûterait.
     *
     * Le produit ne choisit pas : il ne sait pas de quel pouvoir le rôle est
     * censé parler. Les deux chiffres côte à côte rendent la décision évidente
     * sans qu'il ait à trancher — « sans celui-ci, le rôle cesse d'expliquer
     * douze habilitations ; sans celui-là, trois cent quarante ».
     *
     * Le coût n'est pas un accès perdu : le rôle n'est pas appliqué, et un
     * porteur qui détient le droit directement le garde. C'est **ce que le rôle
     * explique** qui change, et c'est la grandeur employée partout ailleurs.
     */
    renderLesRetraits(regle) {
        const retraits = regle.retraits || [];
        if (retraits.length !== 2) return '';
        return `<ul class="mining-retraits">${retraits.map((retrait) => `
            <li>${Utils.escapeHtml(I18n.t('mining.separation_removal', {
                droits: retrait.droits.join(', '),
                habilitations: Utils.formatNumber(retrait.habilitations),
                membres: Utils.formatNumber(retrait.membres)}))}</li>`).join('')}</ul>`;
    },

    /**
     * Libelle d'un role. Le backend renvoie une cle i18n et ses parametres :
     * aucun texte lisible n'est construit cote serveur.
     */
    roleDescription(role) {
        if (role.description_key) {
            return I18n.t(role.description_key, Utils.parametresDansLaLangue(role.description_params));
        }
        return role.description || '';
    },

    /**
     * Ce que le catalogue octroyait déjà, et de qui ce rôle hérite.
     *
     * Un droit retiré sans qu'on puisse dire lequel est pire que le droit en
     * trop : la carte nomme les droits retirés et, quand il existe, le rôle
     * validé dont celui-ci hérite. Sans cette mention, l'utilisateur qui
     * connaît son référentiel croit à un défaut du calcul.
     */
    renderHeritage(role) {
        const retires = role.droits_deja_octroyes || [];
        const parents = role.parent_role_names || [];
        if (retires.length === 0 && parents.length === 0
            && !Number(role.redondance_pct)) return '';

        const lignes = [];
        const redondance = Number(role.redondance_pct) || 0;
        if (redondance > 0) {
            // Une grandeur continue, et non un verdict. Le filtre d'avant ne
            // voyait qu'un cas — la redondance totale — et écartait le
            // candidat en silence ; à quatre-vingts pour cent, un rôle qui
            // recouvre un rôle validé se discute, il ne se supprime pas.
            lignes.push(`<span class="mining-role-heritage__redondance">
                <i class="fas fa-clone" aria-hidden="true"></i>
                ${Utils.escapeHtml(I18n.t('mining.role.redundant',
                                          { part: Utils.formatPercent(redondance) }))}</span>`);
        }
        if (parents.length > 0) {
            lignes.push(`<span class="mining-role-heritage__parent">
                <i class="fas fa-sitemap" aria-hidden="true"></i>
                ${Utils.escapeHtml(I18n.t('mining.role.inherits',
                                          { roles: parents.join(', ') }))}</span>`);
        }
        if (retires.length > 0) {
            lignes.push(`<span class="mining-role-heritage__retires"
                               title="${Utils.escapeHtml(retires.join(', '))}">
                <i class="fas fa-scissors" aria-hidden="true"></i>
                ${Utils.escapeHtml(I18n.t('mining.role.already_granted',
                                          { count: Utils.formatNumber(retires.length) }))}</span>`);
        }
        return `<div class="mining-role-heritage">${lignes.join('')}</div>`;
    },

    renderAttributeCriteria(attributes) {
        if (!attributes || Object.keys(attributes).length === 0) {
            return `<span class="mining-role-criteria__empty">${Utils.escapeHtml(I18n.t('mining.role.no_criteria'))}</span>`;
        }
        return Object.entries(attributes).map(([key, value]) =>
            `<span class="badge badge-neutral mining-role-criteria__badge">${Utils.escapeHtml(key)} = ${Utils.escapeHtml(String(value))}</span>`
        ).join('');
    },
    
    // MODIFIÉ: Switch entre tabs (unifié app + biz)
    /**
     * Bascule l'onglet actif d'une fenêtre de validation.
     *
     * L'état passait par `style.display`, écrit sur chaque volet : un état
     * d'interface vivait donc dans un attribut, hors de la feuille de style,
     * et le bouton actif était marqué par une classe pendant que le volet
     * l'était par un style. Une seule mécanique désormais — la classe — et la
     * feuille décide de ce que « actif » veut dire.
     */
    switchTab(modalPrefix, tabName) {
        const fenetre = document.getElementById(`${modalPrefix}-role-modal`);
        if (!fenetre) return;

        fenetre.querySelectorAll('.tab-button, .tab-content')
            .forEach(element => element.classList.remove('active'));
        document.getElementById(`${modalPrefix}-tab-btn-${tabName}`)?.classList.add('active');
        document.getElementById(`${modalPrefix}-tab-content-${tabName}`)?.classList.add('active');
    },

    // MODIFIÉ: Ouvrir modale métier avec TABS
    openBusinessRoleModal(index) {
        const role = this.results[index]; 
        if (!role) {
            Toast.error(I18n.t('common.error'), I18n.t('validation.role_not_found'));
            return;
        }

        const idxInput = document.getElementById('biz-role-idx');
        const nameInput = document.getElementById('biz-role-name');
        const descInput = document.getElementById('biz-role-desc');
        const userCountEl = document.getElementById('biz-role-user-count-display');
        const criteriaEl = document.getElementById('biz-role-criteria');
        
        // Stocker les valeurs originales
        const originalRightsInput = document.getElementById('biz-role-original-rights');
        const originalUsersInput = document.getElementById('biz-role-original-users');
        
        if (idxInput) idxInput.value = index;
        if (nameInput) nameInput.value = this.nomLibrePour(role, 'biz');
        // L'explication d'un autre rôle resterait à l'écran et se lirait comme
        // celle de celui-ci.
        const explication = document.getElementById('biz-explication');
        if (explication) { explication.hidden = true; explication.innerHTML = ''; }
        this.renderAvertissementDuCandidat('biz', role,
                                           nameInput ? nameInput.value : '');
        // Le backend ne construit plus de libelle : il renvoie une cle i18n et
        // ses parametres, la traduction se fait ici.
        if (descInput) {
            descInput.value = role.description_key
                ? I18n.t(role.description_key, Utils.parametresDansLaLangue(role.description_params))
                : (role.description || '');
        }
        if (userCountEl) userCountEl.textContent = Utils.formatNumber(role.user_count || 0);
        if (criteriaEl) criteriaEl.innerHTML = this.renderAttributeCriteria(role.attributes);
        
        // Stocker les originaux
        if (originalRightsInput) originalRightsInput.value = JSON.stringify(role.rights || []);
        if (originalUsersInput) originalUsersInput.value = JSON.stringify(role.users || []);
        
        this.renderRightsList(role.rights || [], 'biz');
        this.renderUsersList(role.users || [], 'biz');
        
        // Reset tabs
        this.switchTab('biz', 'rights');

        this.propositionDeNom = null;
        this.renderDiagnosticMetier(role);
        this.renderProposition('biz');
        this.chargerEtatDeLAnnotateur('biz');
        
        // Cacher le warning
        const warning = document.getElementById('biz-role-modification-warning');
        if (warning) warning.hidden = true;
        
        Modal.open('biz-role-modal');
    },

    closeBusinessRoleModal() {
        Modal.close();
    },

    // ------------------------------- droits et identités de la validation

    //: Les quatre tableaux de la validation, créés au premier besoin.
    //
    //  `DataTable` pose ses écouteurs à la construction : en refaire un à
    //  chaque ouverture de fenêtre empilerait les écouteurs sur les mêmes
    //  boutons, et un clic sur « suivant » ferait deux pages d'un coup.
    tableauxDeValidation: {},

    //: Ce que l'utilisateur retient, par fenêtre et par onglet.
    //
    //  **Hors du DOM, et c'est la condition du lot.** La sélection se lisait
    //  dans les cases cochées ; elle tenait tant que la liste entière était
    //  écrite d'un coup. Dès qu'un tableau trie et pagine, une case non rendue
    //  n'existe plus : lire le DOM viderait le rôle au premier tri, et ce qui
    //  serait validé ne serait pas ce que l'écran a montré.
    retenus: {},

    /**
     * Identifiants retenus d'un onglet, dans l'ordre où le rôle les portait.
     *
     * L'ordre compte : un rôle dont les droits changeraient d'ordre à chaque
     * tri produirait des exports différents pour une même décision.
     */
    selectionDe(prefix, kind) {
        const etat = this.retenus[`${prefix}-${kind}`];
        if (!etat) return [];
        return etat.tous.filter((identifiant) => etat.gardes.has(identifiant));
    },

    /**
     * Prépare un onglet : ce que le rôle porte, et ce qui est retenu.
     *
     * Tout est retenu à l'ouverture. Décocher est une soustraction explicite,
     * et c'est ce que la fenêtre demande : on valide un rôle proposé, on ne le
     * compose pas de zéro.
     */
    preparerLaSelection(prefix, kind, identifiants) {
        const tous = identifiants.map((identifiant) => String(identifiant));
        this.retenus[`${prefix}-${kind}`] = {
            tous,
            gardes: new Set(tous),
        };
        return tous;
    },

    /**
     * Le tableau d'un onglet, construit une seule fois.
     *
     * Le corps de la requête porte les identifiants du rôle ouvert : ils
     * changent d'une fenêtre à l'autre, et le tableau les relit à chaque
     * chargement plutôt que de les figer à la construction.
     */
    tableauDeValidation(prefix, kind) {
        const cle = `${prefix}-${kind}`;
        if (this.tableauxDeValidation[cle]) return this.tableauxDeValidation[cle];

        const referentiel = kind === 'rights' ? 'rights' : 'identities';
        const tableau = new DataTable({
            // Le type sert de clé aux colonnes masquées et aux largeurs
            // retenues sur le poste. Il est commun aux deux fenêtres : c'est
            // le même référentiel, et un analyste qui a masqué six colonnes
            // pour lire un rôle applicatif ne veut pas les remasquer pour un
            // rôle métier.
            type: `validation-${referentiel}`,
            endpoint: `/referentiels/${referentiel}/lignes`,
            theadId: `${prefix}-role-${kind}-thead`,
            tbodyId: `${prefix}-role-${kind}-list`,
            searchId: `${prefix}-${kind === 'rights' ? 'rights' : 'users'}-search`,
            paginationPrefix: `${prefix}-${kind}`,
            // Une fenêtre en montre moins qu'un écran d'exploration : la place
            // y est comptée, et la liste n'est pas l'objet de l'écran.
            pageSize: MiningPage.LIGNES_PAR_PAGE_VALIDATION,
            // L'accès au détail ouvrirait une fenêtre par-dessus la fenêtre de
            // validation, et le travail en cours passerait derrière.
            detail: false,
            // Un rôle sans droit n'est pas un référentiel vide : le message
            // du domaine dit ce qu'il faut comprendre.
            messageVide: kind === 'rights'
                ? 'mining.no_right_identified' : 'mining.no_user_identified',
            corps: () => ({
                identifiants: (this.retenus[cle] || {tous: []}).tous,
            }),
            selection: {
                // Un droit signalé doit se voir sur sa ligne : c'est le seul
                // endroit où la décision de le retirer se prend.
                marqueur: kind !== 'rights' ? null : (identifiant) =>
                    (MiningPage.estDroitSensible(identifiant)
                        ? `<span class="mining-choix__alerte" title="${
                            Utils.escapeHtml(I18n.t('mining.right.sensitive'))}"><i class="fas fa-exclamation-triangle" aria-hidden="true"></i></span>`
                        : ''),
                contient: (identifiant) =>
                    (this.retenus[cle] || {gardes: new Set()}).gardes.has(identifiant),
                basculer: (identifiant, coche) => {
                    const etat = this.retenus[cle];
                    if (!etat) return;
                    if (coche) { etat.gardes.add(identifiant); }
                    else { etat.gardes.delete(identifiant); }
                    this.detectModification(prefix);
                },
                // Tout le rôle, pas la page : décocher cinq cents porteurs
                // un par un n'était pas une option.
                tout: (coche) => {
                    const etat = this.retenus[cle];
                    if (!etat) return;
                    etat.gardes = new Set(coche ? etat.tous : []);
                    this.detectModification(prefix);
                },
                etat: () => {
                    const etat = this.retenus[cle];
                    if (!etat || etat.gardes.size === 0) return 'aucun';
                    return etat.gardes.size === etat.tous.length ? 'tous' : 'partiel';
                },
            },
        });
        this.tableauxDeValidation[cle] = tableau;
        return tableau;
    },

    /**
     * Charge un onglet de la fenêtre de validation.
     *
     * La recherche et le tri repartent de zéro à chaque ouverture : ils
     * portaient sur un autre rôle, et les garder ferait croire à un référentiel
     * qui aurait changé.
     */
    chargerLeTableauDeValidation(prefix, kind, identifiants) {
        this.preparerLaSelection(prefix, kind, identifiants);
        const tableau = this.tableauDeValidation(prefix, kind);
        tableau.state.page = 1;
        tableau.state.search = '';
        tableau.state.sortCol = null;
        tableau.state.sortDesc = false;
        const recherche = document.getElementById(tableau.searchId);
        if (recherche) recherche.value = '';
        tableau.load().then(() => this.signalerLesOrphelins(prefix, kind));
        this.detectModification(prefix);
    },

    /**
     * Dit combien d'identifiants le référentiel ne connaît pas.
     *
     * Un droit présent dans les habilitations et absent du référentiel des
     * droits n'a aucune colonne à montrer : sa ligne est vide, et sans cette
     * phrase l'utilisateur croit à un défaut d'affichage. Il reste dans le
     * rôle — c'est la règle : cette liste décide de ce qui sera validé.
     */
    signalerLesOrphelins(prefix, kind) {
        const zone = document.getElementById(`${prefix}-${kind}-orphelins`);
        if (!zone) return;
        const tableau = this.tableauxDeValidation[`${prefix}-${kind}`];
        const inconnus = (tableau && tableau.state.inconnus) || [];
        zone.hidden = inconnus.length === 0;
        zone.textContent = inconnus.length
            ? I18n.t('validation.orphans', { count: inconnus.length }) : '';
    },

    /**
     * Les droits du rôle, avec les colonnes du référentiel.
     *
     * La fenêtre ne montrait que l'identifiant. C'est la seule colonne que le
     * produit connaisse par construction, et c'est justement celle qui ne dit
     * rien : personne ne décoche `D_FIN_0042` en connaissance de cause.
     */
    renderRightsList(rights, prefix) {
        const corps = document.getElementById(`${prefix}-role-rights-list`);
        if (!corps) return;
        this.chargerLeTableauDeValidation(prefix, 'rights', rights || []);
    },

    /**
     * Un droit est signalé si son nom contient l'un des fragments déclarés
     * par le client dans les paramètres du workspace.
     *
     * La règle était écrite ici : « ADMIN » ou « SUPPRESSION ». Elle suppose
     * une convention de nommage et une langue, et se trompe dans les deux
     * sens — un droit « ADMINistratif » était signalé, un droit
     * « DELETE_ALL » ne l'était pas. Sans liste déclarée, rien n'est signalé.
     */
    estDroitSensible(nomDuDroit) {
        const fragments = (typeof SettingsPage !== 'undefined' && SettingsPage.config
            && SettingsPage.config.sensitive_right_keywords) || [];
        if (!fragments.length) return false;
        const nom = String(nomDuDroit).toUpperCase();
        return fragments.some((fragment) =>
            fragment && nom.includes(String(fragment).toUpperCase()));
    },

    /** Les porteurs du rôle, avec les colonnes du référentiel d'identités. */
    renderUsersList(users, prefix) {
        const corps = document.getElementById(`${prefix}-role-users-list`);
        if (!corps) return;
        this.chargerLeTableauDeValidation(prefix, 'users', users || []);
    },

    // UNIFIÉ: Détection modification (app ou biz)
    detectModification(prefix) {
        const originalRights = JSON.parse(document.getElementById(`${prefix}-role-original-rights`)?.value || '[]');
        const originalUsers = JSON.parse(document.getElementById(`${prefix}-role-original-users`)?.value || '[]');
        
        // Lus dans l'état, jamais dans les cases : une ligne d'une autre page
        // ou d'un autre tri n'est pas rendue, et le DOM ne la connaît pas.
        const currentRights = this.selectionDe(prefix, 'rights');
        const currentUsers = this.selectionDe(prefix, 'users');
        
        // Mettre à jour compteurs
        document.getElementById(`${prefix}-role-rights-count`).textContent = currentRights.length;
        document.getElementById(`${prefix}-role-users-count`).textContent = currentUsers.length;
        
        const userCountDisplay = document.getElementById(`${prefix}-role-user-count-display`);
        if (userCountDisplay) userCountDisplay.textContent = Utils.formatNumber(currentUsers.length);
        
        // Détecter si modifié
        const rightsModified = originalRights.length !== currentRights.length || 
                              !originalRights.every(r => currentRights.includes(r));
        const usersModified = originalUsers.length !== currentUsers.length ||
                             !originalUsers.every(u => currentUsers.includes(u));
        
        const isModified = rightsModified || usersModified;
        
        // Afficher/cacher warning
        const warning = document.getElementById(`${prefix}-role-modification-warning`);
        if (warning) warning.hidden = !isModified;
    },

    // MODIFIÉ: Validation métier avec logique de refus
    async confirmCreateBusinessRole() {
        const btn = document.getElementById('btn-confirm-biz-creation');
        if (!btn) return;
        
        const originalText = btn.innerHTML;
        const name = document.getElementById('biz-role-name')?.value?.trim();
        const idx = document.getElementById('biz-role-idx')?.value;
        
        if (!name) {
            Toast.error(I18n.t('common.error'), I18n.t('validation.role_name_required'));
            return;
        }

        const selectedRights = this.selectionDe('biz', 'rights');
        const selectedUsers = this.selectionDe('biz', 'users');
        
        if (selectedRights.length === 0) {
            Toast.error(I18n.t('common.error'), I18n.t('validation.select_at_least_one_right'));
            return;
        }

        if (selectedUsers.length === 0) {
            Toast.error(I18n.t('common.error'), I18n.t('validation.select_at_least_one_user'));
            return;
        }

        try {
            btn.innerHTML = `<i class="fas fa-circle-notch fa-spin" aria-hidden="true"></i> ${
                Utils.escapeHtml(I18n.t('mining.creating'))}`;
            btn.disabled = true;

            const role = this.results?.[idx];
            if (!role) throw new Error(I18n.t('validation.role_not_found'));

            // Détecter si modifié
            const originalRights = JSON.parse(document.getElementById('biz-role-original-rights')?.value || '[]');
            const originalUsers = JSON.parse(document.getElementById('biz-role-original-users')?.value || '[]');
            
            const rightsModified = originalRights.length !== selectedRights.length || 
                                  !originalRights.every(r => selectedRights.includes(r));
            const usersModified = originalUsers.length !== selectedUsers.length ||
                                 !originalUsers.every(u => selectedUsers.includes(u));
            
            const isModified = rightsModified || usersModified;

            // Modifier un candidat, c'est le refuser et en créer un autre :
            // le candidat d'origine est écarté sous son propre identifiant,
            // celui que le serveur lui a donné.
            if (isModified) {
                try {
                    await KnowledgeBase.rejectRole(role.id);
                } catch (err) {
                    // Le refus du rôle d'origine est un complément : son échec ne
                    // doit pas empêcher la création du rôle modifié.
                    Toast.warning(I18n.t('common.warning'), I18n.t('mining.original_role_reject_failed'));
                }
            }

            const payload = {
                name,
                description: document.getElementById('biz-role-desc')?.value || '',
                role_type: 'METIER',
                rights: selectedRights,
                users: selectedUsers,  // NOUVEAU
                sub_role_ids: [],
                additional_rights: [],
                rh_rule: role.rh_rule || '',
                source_attributes: role.attributes || {},
                // De quel candidat vient ce rôle. Sans ce lien, une validation
                // crée un rôle d'identifiant neuf et le candidat reste compté
                // comme à décider — indéfiniment.
                candidate_id: role.id,
                indicateurs: this.indicateursDeDecision(role),
            };

            await API.post('/roles/create', payload);
            // Un mining, une validation ou un refus changent ce qu'il reste
            // à décider : l'indicateur suit l'action, sans rechargement.
            if (typeof Cloche !== 'undefined') Cloche.rafraichir();

            const message = isModified
                ? I18n.t('success.business_role_created_modified', { name })
                : I18n.t('success.business_role_created', { name });

            // Le nom vient d'entrer au catalogue : la modale suivante doit le
            // savoir sans relancer le mining.
            this.nomsDuCatalogue.biz = [...this.nomsDuCatalogue.biz, name];
            Toast.success(I18n.t('common.success'), message);
            this.closeBusinessRoleModal();

            const card = document.querySelector(`.mining-role-card[data-index="${idx}"]`);
            if (card) {
                const cardBtn = card.querySelector('button');
                if (cardBtn) cardBtn.outerHTML =
                    `<div class="mining-verdict mining-verdict--valide">
                        <i class="fas fa-circle-check" aria-hidden="true"></i> ${
                            Utils.escapeHtml(I18n.t('graph.origin.validated'))}</div>`;
            }

        } catch (error) {
            Toast.error(I18n.t('common.error'), error.message);
        } finally {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    },

    // NOUVEAU: Refuser rôle métier
    async rejectBusinessRole() {
        const idx = document.getElementById('biz-role-idx')?.value;
        const role = this.results?.[idx];
        
        if (!role) return;
        
        // Le motif est exigé : un refus est définitif et se relit dans la
        // piste d'audit, où « motif : » vide ne dit rien à personne.
        const motif = await Confirm.demander({
            titre: I18n.t('confirm.reject_role_title'),
            message: I18n.t('confirm.reject_business_role'),
            confirmer: I18n.t('confirm.reject_action'),
            danger: true,
            saisie: {label: I18n.t('confirm.reject_reason')},
        });
        if (!motif) return;
        
        try {
            // Un refus d'analyste est une décision : ses indicateurs vont à
            // l'apprentissage, comme pour un rôle applicatif.
            await KnowledgeBase.rejectRole(
                role.id, motif, this.indicateursDeDecision(role));
            // Un mining, une validation ou un refus changent ce qu'il reste
            // à décider : l'indicateur suit l'action, sans rechargement.
            if (typeof Cloche !== 'undefined') Cloche.rafraichir();

            Toast.success(I18n.t('common.rejected'), I18n.t('success.business_role_rejected'));
            this.closeBusinessRoleModal();
            
            const card = document.querySelector(`.mining-role-card[data-index="${idx}"]`);
            if (card) {
                const cardBtn = card.querySelector('button');
                if (cardBtn) cardBtn.outerHTML =
                    `<div class="mining-verdict mining-verdict--rejete">
                        <i class="fas fa-circle-xmark" aria-hidden="true"></i> ${
                            Utils.escapeHtml(I18n.t('graph.origin.rejected'))}</div>`;
            }
            
        } catch (error) {
            Toast.error(I18n.t('common.error'), error.message);
        }
    },

    // ============================================
    // MINING APPLICATIF - IDENTIQUE AU MÉTIER
    // ============================================

    /**
     * Affiche les champs propres au mode approche (seuil de similarite,
     * nombre maximum de roles) uniquement lorsque ce mode est selectionne.
     */
    syncMiningModeFields() {
        const mode = document.getElementById('mining-mode')?.value;
        const approxParams = document.getElementById('mining-approx-params');
        if (approxParams) {
            approxParams.style.display = mode === 'APPROX' ? '' : 'none';
        }
        // L'exploration du seuil n'a de sens qu'en mode approche : c'est le
        // seul mode ou un seuil existe.
        const explorer = document.getElementById('threshold-explorer');
        if (explorer) {
            explorer.style.display = mode === 'APPROX' ? '' : 'none';
        }
        // Le choix des façons de chercher non plus : le mining exact n'a
        // qu'une façon, par construction.
        const generateurs = document.getElementById('mining-generateurs');
        if (generateurs) {
            generateurs.style.display = mode === 'APPROX' ? '' : 'none';
        }
    },

    /**
     * Les façons de chercher cochées.
     *
     * Rendues telles quelles, y compris vides : un choix vide est un choix, et
     * le remplacer par celui du produit reviendrait à décider à la place de
     * l'utilisateur — c'est précisément ce que cet écran refuse de faire
     * partout ailleurs.
     */
    generateursChoisis() {
        return Array.from(document.querySelectorAll('[data-generateur]'))
            .filter((case_) => case_.checked)
            .map((case_) => case_.value);
    },

    /**
     * Construit une liste de seuils a partir d'un intervalle et d'un pas saisis.
     * Aucune valeur par defaut : un champ vide est refuse, le balayage etant un
     * choix de l'utilisateur.
     * @param {string} idDebut identifiant du champ "seuil de depart"
     * @param {string} idFin identifiant du champ "seuil d'arrivee"
     * @param {string} idPas identifiant du champ "pas"
     * @returns {number[]|null} les seuils, ou null si la saisie est invalide.
     */
    buildRange(idDebut, idFin, idPas) {
        const lire = (id) => {
            const brut = document.getElementById(id)?.value;
            if (brut === undefined || brut === null || String(brut).trim() === '') return null;
            const valeur = parseFloat(brut);
            return Number.isFinite(valeur) ? valeur : null;
        };

        const debut = lire(idDebut);
        const fin = lire(idFin);
        const pas = lire(idPas);

        if (debut === null || fin === null || pas === null) {
            Toast.error(I18n.t('common.error'), I18n.t('threshold.range_required'));
            return null;
        }
        if (debut <= 0 || debut > 1 || fin <= 0 || fin > 1 || pas <= 0 || debut > fin) {
            Toast.error(I18n.t('common.error'), I18n.t('threshold.range_invalid'));
            return null;
        }

        const seuils = [];
        const ajouter = (valeur) => {
            const arrondi = Math.round(valeur * 10000) / 10000;
            if (arrondi > 0 && arrondi <= 1 && !seuils.includes(arrondi)) {
                seuils.push(arrondi);
            }
        };

        // Comparaison a une demi-tolerance pres : sans cela, 0,7 + 0,1 * 3
        // depasse 1,0 d'un epsilon flottant et le dernier seuil est perdu.
        for (let valeur = debut; valeur <= fin + pas / 2; valeur += pas) {
            ajouter(Math.min(valeur, fin));
        }
        // Le seuil d'arrivee est toujours evalue, meme quand le pas ne tombe
        // pas juste dessus : l'utilisateur l'a demande explicitement.
        ajouter(fin);
        return seuils.sort((a, b) => a - b);
    },

    /**
     * Evalue la serie de seuils sur les donnees du workspace et restitue la
     * courbe couverture / sur-octroi. Les bornes du mining (effectif minimal,
     * droits minimaux, plafond de roles) sont celles du formulaire : la courbe
     * doit etre comparable a l'execution reelle.
     */
    async runThresholdScan() {
        const btn = document.getElementById('run-threshold-scan');
        if (!btn) return;

        const seuils = this.buildRange('threshold-min', 'threshold-max', 'threshold-step');
        if (!seuils || seuils.length === 0) return;

        const originalText = btn.innerHTML;
        try {
            btn.innerHTML = `<i class="fas fa-spinner fa-spin" aria-hidden="true"></i> ${Utils.escapeHtml(I18n.t('threshold.running'))}`;
            btn.disabled = true;

            const params = {
                thresholds: seuils,
                min_users: parseInt(document.getElementById('mining-min-users')?.value, 10),
                min_rights: parseInt(document.getElementById('mining-min-rights')?.value, 10),
                max_roles: parseInt(document.getElementById('mining-max-roles')?.value, 10),
                excluded_rights: Utils.parseCSV(document.getElementById('mining-excluded-rights')?.value || ''),
                // La courbe doit décrire ce que produira l'exécution : sans
                // ces deux-là, le point choisi ne correspondait à aucun
                // mining que l'utilisateur puisse relancer.
                generateurs: this.generateursChoisis()
            };
            const apport = this.apportMinimalSaisi();
            if (apport !== undefined) params.apport_minimal = apport;
            const selection = this.selectionChoisie();
            if (selection !== undefined) params.selection = selection;

            const contrainte = document.getElementById('threshold-max-over-granted')?.value;
            if (contrainte !== undefined && String(contrainte).trim() !== '') {
                params.max_over_granted_pct = parseFloat(contrainte);
            }

            const data = await API.scanMiningThresholds(params);
            this.renderThresholdScan(data);
        } catch (error) {
            Toast.error(I18n.t('common.error'), error.message);
        } finally {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    },

    /** Lit une couleur du theme : la palette n'est ecrite que dans le CSS. */
    themeColor(name) {
        return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    },

    renderThresholdScan(data) {
        const zone = document.getElementById('threshold-scan-results');
        if (!zone) return;
        zone.style.display = '';

        const points = data.points || [];
        const nonDomines = new Set(data.undominated || []);
        const retenu = data.selected ? data.selected.threshold : null;

        const resume = document.getElementById('threshold-scan-summary');
        if (resume) {
            const messages = [I18n.t('threshold.summary', {
                points: Utils.valeurDansLaLangue(points.length),
                seconds: Utils.formatDecimal(data.elapsed_ms / 1000),
                assignments: Utils.valeurDansLaLangue(data.total_assignments)
            })];
            if (data.constraint && data.constraint.max_over_granted_pct !== null
                && data.constraint.max_over_granted_pct !== undefined) {
                messages.push(retenu !== null
                    ? I18n.t('threshold.selected', { threshold: Utils.valeurDansLaLangue(retenu) })
                    : I18n.t('threshold.no_selection'));
            } else {
                messages.push(I18n.t('threshold.no_constraint'));
            }
            resume.textContent = messages.join(' ');
        }

        this.renderThresholdChart(points);
        this.renderThresholdTable(points, nonDomines, retenu);
    },

    renderThresholdChart(points) {
        const canvas = document.getElementById('threshold-chart');
        if (!canvas || typeof Chart === 'undefined') return;

        if (this.thresholdChart) {
            this.thresholdChart.destroy();
        }

        // Les seuils arrivent du plus strict au plus lache ; la courbe se lit
        // dans l'autre sens, du plus permissif au plus strict.
        const ordonnes = [...points].sort((a, b) => a.threshold - b.threshold);
        const couverture = this.themeColor('--chart-coverage');
        const surOctroi = this.themeColor('--chart-over-granted');
        const roles = this.themeColor('--chart-roles');
        const grille = this.themeColor('--chart-grid');
        const graduation = this.themeColor('--chart-tick');

        this.thresholdChart = new Chart(canvas.getContext('2d'), {
            type: 'line',
            data: {
                labels: ordonnes.map((point) => point.threshold),
                datasets: [
                    {
                        label: I18n.t('threshold.chart.coverage'),
                        data: ordonnes.map((point) => point.coverage_pct),
                        borderColor: couverture,
                        backgroundColor: couverture,
                        yAxisID: 'y',
                        tension: 0.2
                    },
                    {
                        label: I18n.t('threshold.chart.over_granted'),
                        data: ordonnes.map((point) => point.over_granted_pct),
                        borderColor: surOctroi,
                        backgroundColor: surOctroi,
                        yAxisID: 'y',
                        tension: 0.2
                    },
                    {
                        label: I18n.t('threshold.chart.roles'),
                        data: ordonnes.map((point) => point.roles),
                        borderColor: roles,
                        backgroundColor: roles,
                        yAxisID: 'yRoles',
                        borderDash: [6, 4],
                        tension: 0.2
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { intersect: false, mode: 'index' },
                plugins: { legend: { labels: { color: graduation } } },
                scales: {
                    x: { grid: { color: grille }, ticks: { color: graduation } },
                    y: {
                        position: 'left',
                        beginAtZero: true,
                        grid: { color: grille },
                        ticks: { color: graduation }
                    },
                    yRoles: {
                        position: 'right',
                        beginAtZero: true,
                        grid: { display: false },
                        ticks: { color: graduation }
                    }
                }
            }
        });
    },

    renderThresholdTable(points, nonDomines, retenu) {
        const zone = document.getElementById('threshold-scan-table');
        if (!zone) return;

        const lignes = points.map((point) => {
            const estRetenu = retenu !== null && point.threshold === retenu;
            const estNonDomine = nonDomines.has(point.threshold);
            const classes = ['threshold-row'];
            if (estRetenu) classes.push('threshold-row-selected');
            const statut = estNonDomine
                ? `<span class="badge badge-success" data-definition="threshold.undominated_hint">${Utils.escapeHtml(I18n.t('threshold.undominated'))}</span>`
                : `<span class="badge badge-neutral">${Utils.escapeHtml(I18n.t('threshold.dominated'))}</span>`;
            const plafond = point.capped
                ? `<i class="fas fa-exclamation-triangle threshold-capped" title="${Utils.escapeHtml(I18n.t('threshold.capped'))}" aria-hidden="true"></i>`
                : '';
            // Le titre porte la phrase pour la souris, le texte masqué pour
            // un lecteur d'écran : l'icône seule n'est pas une information.
            const treillis = point.treillis_borne === true
                ? `<span class="threshold-treillis" title="${Utils.escapeHtml(I18n.t('threshold.treillis_borne'))}"><i class="fas fa-diagram-project" aria-hidden="true"></i><span class="sr-only">${Utils.escapeHtml(I18n.t('threshold.treillis_borne'))}</span></span>`
                : '';

            return `
                <tr class="${classes.join(' ')}">
                    <td>${Utils.escapeHtml(String(Utils.valeurDansLaLangue(point.threshold)))}</td>
                    <td>${Utils.escapeHtml(String(Utils.valeurDansLaLangue(point.roles)))} ${plafond}${treillis}</td>
                    <td>${Utils.escapeHtml(I18n.t('unit.percent', { value: Utils.valeurDansLaLangue(point.coverage_pct) }))}</td>
                    <td>${Utils.escapeHtml(I18n.t('unit.percent', { value: Utils.valeurDansLaLangue(point.over_granted_pct) }))}</td>
                    <td>${Utils.escapeHtml(String(Utils.valeurDansLaLangue(point.elapsed_ms)))} ms</td>
                    <td>${statut}</td>
                    <td>
                        <button class="btn btn-sm btn-secondary threshold-apply" data-threshold="${Utils.escapeHtml(String(point.threshold))}">
                            ${Utils.escapeHtml(I18n.t('threshold.apply'))}
                        </button>
                    </td>
                </tr>`;
        }).join('');

        zone.innerHTML = `
            <table class="data-table threshold-table">
                <thead>
                    <tr>
                        <th scope="col">${Utils.escapeHtml(I18n.t('threshold.column.threshold'))}</th>
                        <th scope="col">${Utils.escapeHtml(I18n.t('threshold.column.roles'))}</th>
                        <th scope="col">${Utils.escapeHtml(I18n.t('threshold.column.coverage'))}</th>
                        <th scope="col">${Utils.escapeHtml(I18n.t('threshold.column.over_granted'))}</th>
                        <th scope="col">${Utils.escapeHtml(I18n.t('threshold.column.time'))}</th>
                        <th scope="col">${Utils.escapeHtml(I18n.t('threshold.column.verdict'))}</th>
                        <th scope="col"></th>
                    </tr>
                </thead>
                <tbody>${lignes}</tbody>
            </table>`;

        zone.querySelectorAll('.threshold-apply').forEach((bouton) => {
            bouton.addEventListener('click', () => this.applyThreshold(bouton.dataset.threshold));
        });
    },

    /**
     * Balaie les seuils de consolidation sur le resultat du mining courant.
     * Le serveur ne joue le mining qu'une fois : un balayage complet coute a
     * peine plus qu'un mining seul.
     */
    async runConsolidationScan() {
        const btn = document.getElementById('run-consolidation-scan');
        if (!btn) return;

        const seuils = this.buildRange('consolidation-min', 'consolidation-max', 'consolidation-step');
        if (!seuils || seuils.length === 0) return;

        const originalText = btn.innerHTML;
        try {
            btn.innerHTML = `<i class="fas fa-spinner fa-spin" aria-hidden="true"></i> ${Utils.escapeHtml(I18n.t('threshold.running'))}`;
            btn.disabled = true;

            const mode = document.getElementById('mining-mode')?.value || 'EXACT';
            const params = {
                mining_mode: mode,
                min_users: parseInt(document.getElementById('mining-min-users')?.value, 10),
                min_rights: parseInt(document.getElementById('mining-min-rights')?.value, 10),
                excluded_rights: Utils.parseCSV(document.getElementById('mining-excluded-rights')?.value || ''),
                consolidation_thresholds: seuils
            };
            if (mode === 'APPROX') {
                params.similarity_threshold = parseFloat(document.getElementById('mining-similarity-threshold')?.value);
                params.max_roles = parseInt(document.getElementById('mining-max-roles')?.value, 10);
                params.generateurs = this.generateursChoisis();
                const apportMinimal = this.apportMinimalSaisi();
                if (apportMinimal !== undefined) params.apport_minimal = apportMinimal;
                const selection = this.selectionChoisie();
                if (selection !== undefined) params.selection = selection;
            }

            const perte = document.getElementById('consolidation-max-loss')?.value;
            if (perte !== undefined && String(perte).trim() !== '') {
                params.max_granted_loss_pct = parseFloat(perte);
            }

            this.renderConsolidationScan(await API.scanConsolidationThresholds(params));
        } catch (error) {
            Toast.error(I18n.t('common.error'), error.message);
        } finally {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    },

    renderConsolidationScan(data) {
        const zone = document.getElementById('consolidation-scan-results');
        if (!zone) return;
        zone.style.display = '';

        const reference = data.baseline || {};
        const points = data.points || [];
        const retenu = data.selected ? data.selected.threshold : null;

        const resume = document.getElementById('consolidation-scan-summary');
        if (resume) {
            const phrases = [I18n.t('consolidation.summary', {
                roles: reference.roles,
                pairs: Utils.formatNumber(reference.granted_pairs || 0),
                seconds: Utils.formatDecimal(data.elapsed_ms / 1000)
            })];
            if (data.constraint && data.constraint.max_granted_loss_pct !== null
                && data.constraint.max_granted_loss_pct !== undefined) {
                phrases.push(retenu !== null
                    ? I18n.t('consolidation.selected', { threshold: retenu })
                    : I18n.t('consolidation.no_selection'));
            } else {
                phrases.push(I18n.t('consolidation.no_constraint'));
            }
            resume.textContent = phrases.join(' ');
        }

        this.renderConsolidationChart(points);
        this.renderConsolidationTable(points, retenu);
    },

    renderConsolidationChart(points) {
        const canvas = document.getElementById('consolidation-chart');
        if (!canvas || typeof Chart === 'undefined') return;

        if (this.consolidationChart) {
            this.consolidationChart.destroy();
        }

        const ordonnes = [...points].sort((a, b) => a.threshold - b.threshold);
        const roles = this.themeColor('--chart-roles');
        const perte = this.themeColor('--chart-over-granted');
        const grille = this.themeColor('--chart-grid');
        const graduation = this.themeColor('--chart-tick');

        this.consolidationChart = new Chart(canvas.getContext('2d'), {
            type: 'line',
            data: {
                labels: ordonnes.map((point) => point.threshold),
                datasets: [
                    {
                        label: I18n.t('consolidation.chart.roles'),
                        data: ordonnes.map((point) => point.roles),
                        borderColor: roles,
                        backgroundColor: roles,
                        yAxisID: 'yRoles',
                        tension: 0.2
                    },
                    {
                        label: I18n.t('consolidation.chart.lost'),
                        data: ordonnes.map((point) => point.granted_pairs_lost_pct),
                        borderColor: perte,
                        backgroundColor: perte,
                        yAxisID: 'y',
                        tension: 0.2
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { intersect: false, mode: 'index' },
                plugins: { legend: { labels: { color: graduation } } },
                scales: {
                    x: { grid: { color: grille }, ticks: { color: graduation } },
                    y: {
                        position: 'left',
                        beginAtZero: true,
                        grid: { color: grille },
                        ticks: { color: graduation }
                    },
                    yRoles: {
                        position: 'right',
                        beginAtZero: true,
                        grid: { display: false },
                        ticks: { color: graduation }
                    }
                }
            }
        });
    },

    renderConsolidationTable(points, retenu) {
        const zone = document.getElementById('consolidation-scan-table');
        if (!zone) return;

        const lignes = points.map((point) => {
            const classes = ['threshold-row'];
            if (retenu !== null && point.threshold === retenu) classes.push('threshold-row-selected');
            const marginal = point.marginal_efficiency === null || point.marginal_efficiency === undefined
                ? '—'
                : Utils.escapeHtml(String(Utils.valeurDansLaLangue(point.marginal_efficiency)));

            return `
                <tr class="${classes.join(' ')}">
                    <td>${Utils.escapeHtml(String(Utils.valeurDansLaLangue(point.threshold)))}</td>
                    <td>${Utils.escapeHtml(String(Utils.valeurDansLaLangue(point.roles)))}</td>
                    <td>${Utils.escapeHtml(String(Utils.valeurDansLaLangue(point.roles_absorbed)))}</td>
                    <td>${Utils.escapeHtml(I18n.t('unit.percent', { value: Utils.valeurDansLaLangue(point.granted_pairs_lost_pct) }))}</td>
                    <td>${Utils.escapeHtml(String(Utils.valeurDansLaLangue(point.compression_ratio)))}</td>
                    <td>${Utils.escapeHtml(I18n.t('unit.percent', { value: Utils.valeurDansLaLangue(point.redundancy_pct) }))}</td>
                    <td>${Utils.escapeHtml(String(Utils.valeurDansLaLangue(point.wsc)))}</td>
                    <td data-definition="consolidation.column.marginal_hint">${marginal}</td>
                    <td>
                        <button class="btn btn-sm btn-secondary consolidation-apply" data-threshold="${Utils.escapeHtml(String(point.threshold))}">
                            ${Utils.escapeHtml(I18n.t('threshold.apply'))}
                        </button>
                    </td>
                </tr>`;
        }).join('');

        zone.innerHTML = `
            <table class="data-table threshold-table">
                <thead>
                    <tr>
                        <th scope="col">${Utils.escapeHtml(I18n.t('threshold.column.threshold'))}</th>
                        <th scope="col">${Utils.escapeHtml(I18n.t('threshold.column.roles'))}</th>
                        <th scope="col">${Utils.escapeHtml(I18n.t('consolidation.column.absorbed'))}</th>
                        <th scope="col">${Utils.escapeHtml(I18n.t('consolidation.column.lost'))}</th>
                        <th scope="col">${Utils.escapeHtml(I18n.t('stats.compression'))}</th>
                        <th scope="col">${Utils.escapeHtml(I18n.t('stats.redundancy'))}</th>
                        <th scope="col">${Utils.escapeHtml(I18n.t('stats.wsc'))}</th>
                        <th scope="col">${Utils.escapeHtml(I18n.t('consolidation.column.marginal'))}</th>
                        <th scope="col"></th>
                    </tr>
                </thead>
                <tbody>${lignes}</tbody>
            </table>`;

        zone.querySelectorAll('.consolidation-apply').forEach((bouton) => {
            bouton.addEventListener('click', () => this.applyConsolidation(bouton.dataset.threshold));
        });
    },

    /** Reporte un seuil de consolidation dans le formulaire de mining. */
    applyConsolidation(valeur) {
        const champ = document.getElementById('mining-consolidation-threshold');
        if (!champ) return;
        champ.value = valeur;
        Toast.success(I18n.t('common.success'), I18n.t('consolidation.applied', { threshold: valeur }));
    },

    /** Reporte un seuil de la courbe dans le formulaire de mining. */
    applyThreshold(valeur) {
        const champ = document.getElementById('mining-similarity-threshold');
        if (!champ) return;
        champ.value = valeur;
        Toast.success(I18n.t('common.success'), I18n.t('threshold.applied', { threshold: valeur }));
    },

    async launchMining() {
        const btn = document.getElementById('launch-mining');
        if (!btn) return;
        const originalText = btn.innerHTML;

        try {
            btn.innerHTML = `<i class="fas fa-spinner fa-spin" aria-hidden="true"></i> ${Utils.escapeHtml(I18n.t('action.mining_in_progress'))}`;
            btn.disabled = true;

            const mode = document.getElementById('mining-mode')?.value || 'EXACT';
            const params = {
                mining_mode: mode,
                min_users: parseInt(document.getElementById('mining-min-users')?.value, 10),
                min_rights: parseInt(document.getElementById('mining-min-rights')?.value, 10),
                excluded_rights: Utils.parseCSV(document.getElementById('mining-excluded-rights')?.value || '')
            };

            if (mode === 'APPROX') {
                // Le compromis couverture / sur-octroi est un choix de gouvernance :
                // aucune valeur par defaut n'est appliquee cote serveur.
                params.similarity_threshold = parseFloat(document.getElementById('mining-similarity-threshold')?.value);
                params.max_roles = parseInt(document.getElementById('mining-max-roles')?.value, 10);
                params.generateurs = this.generateursChoisis();
                const apportMinimal = this.apportMinimalSaisi();
                if (apportMinimal !== undefined) params.apport_minimal = apportMinimal;
                const selection = this.selectionChoisie();
                if (selection !== undefined) params.selection = selection;
            }

            // Consolidation : retirer des candidats est une decision. Sans
            // seuil saisi, rien n'est consolide.
            const consolidation = document.getElementById('mining-consolidation-threshold')?.value;
            if (consolidation !== undefined && String(consolidation).trim() !== '') {
                params.consolidation_threshold = parseFloat(consolidation);
            }

            const data = await API.launchMining(params);
            this.handleAppMiningSuccess(data);

            // Un mining renouvelle les candidats : ce qu'il reste à décider aussi.
            if (typeof Cloche !== 'undefined') Cloche.rafraichir();
            this.annoncerRunConserve('APPLICATIF');
        } catch (error) {
            Toast.error(I18n.t('common.error'), error.message);
        } finally {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    },

    // ============================================
    // RÉSULTAT CONSERVÉ D'UN MINING PRÉCÉDENT
    // ============================================

    /**
     * Où se pose le bandeau, et quel conteneur de résultats il gouverne.
     *
     * Une table plutôt qu'un `if` : les deux écrans se ressemblent assez pour
     * qu'une différence oubliée passe inaperçue.
     */
    RUNS_CONSERVES: {
        APPLICATIF: {bandeau: 'app-run-conserve', resultats: 'mining-results-container',
                     compteur: 'mining-results-count'},
        METIER: {bandeau: 'biz-run-conserve', resultats: 'business-mining-results',
                 compteur: 'biz-results-count'},
    },

    /** Ce que `pending-work` a rendu pour chaque type, à la dernière lecture. */
    runsConserves: {},

    /**
     * Annonce, sans le charger, le résultat conservé d'un mining précédent.
     *
     * Un mining sur vingt mille identités prend plusieurs minutes. Son
     * résultat était conservé côté serveur — le graphe s'en sert — mais
     * l'écran qui l'a produit ne le relisait jamais : y revenir affichait
     * « Aucun mining lancé », et retrouver son travail imposait de tout
     * recalculer.
     *
     * Le bandeau ne coûte qu'un comptage. La charge utile — plusieurs milliers
     * de rôles et leurs porteurs — n'est demandée que si l'utilisateur choisit
     * de l'afficher : la rapatrier à chaque ouverture de page ferait payer
     * plusieurs mégaoctets à qui vient seulement lancer un autre calcul.
     */
    async annoncerRunConserve(type) {
        const cibles = this.RUNS_CONSERVES[type];
        const bandeau = cibles && document.getElementById(cibles.bandeau);
        if (!bandeau) return;

        try {
            const etat = await API.get('/kb/pending-work');
            this.runsConserves[type] =
                (etat.types || []).find(ligne => ligne.role_type === type) || null;
        } catch (erreur) {
            // Le bandeau est un complément : son absence ne doit pas empêcher
            // de lancer un mining.
            this.runsConserves[type] = null;
        }
        this.rendreRunConserve(type);
    },

    /** Écrit le bandeau à partir du dernier comptage connu. */
    rendreRunConserve(type) {
        const cibles = this.RUNS_CONSERVES[type];
        const bandeau = cibles && document.getElementById(cibles.bandeau);
        if (!bandeau) return;

        const etat = this.runsConserves[type];
        const candidats = etat ? Number(etat.candidates) || 0 : 0;
        // Rien de conservé, ou déjà affiché : pas de bandeau. Le proposer
        // au-dessus du résultat qu'il décrit inviterait à recharger ce qui est
        // déjà là.
        const affiches = type === 'METIER' ? this.results.length : this.appMiningResults.length;
        if (!candidats || affiches) {
            bandeau.hidden = true;
            bandeau.innerHTML = '';
            return;
        }

        const date = etat.computed_at
            ? new Date(etat.computed_at).toLocaleString(I18n.currentLocale || undefined)
            : '';
        const obsolete = etat.stale
            ? `<span class="run-conserve__obsolete">
                   <i class="fas fa-triangle-exclamation" aria-hidden="true"></i>
                   ${Utils.escapeHtml(I18n.t('pending.stale'))}
               </span>`
            : '';

        bandeau.hidden = false;
        bandeau.innerHTML = `
            <p class="run-conserve__texte">
                ${Utils.escapeHtml(I18n.t('run.kept', {
                    count: candidats,
                    undecided: Number(etat.undecided) || 0,
                    date,
                }))}
            </p>
            ${obsolete}
            <div class="run-conserve__actions">
                <button type="button" class="btn btn-secondary btn-sm"
                        data-run-afficher="${Utils.escapeHtml(type)}">
                    <i class="fas fa-eye" aria-hidden="true"></i>
                    ${Utils.escapeHtml(I18n.t('run.show'))}
                </button>
                <button type="button" class="btn btn-ghost btn-sm"
                        data-run-oublier="${Utils.escapeHtml(type)}">
                    <i class="fas fa-eraser" aria-hidden="true"></i>
                    ${Utils.escapeHtml(I18n.t('run.forget'))}
                </button>
            </div>`;

        bandeau.querySelector('[data-run-afficher]')
            ?.addEventListener('click', () => this.afficherRunConserve(type));
        bandeau.querySelector('[data-run-oublier]')
            ?.addEventListener('click', () => this.oublierRunConserve(type));
    },

    /**
     * Charge et affiche le résultat conservé, à l'identique du calcul.
     *
     * Les indicateurs viennent du serveur avec les rôles : les recalculer dans
     * la page donnerait d'autres chiffres que ceux qu'on a montrés le jour du
     * mining, et c'est exactement ce que ce produit reproche aux outils du
     * marché.
     */
    async afficherRunConserve(type) {
        const bouton = document.querySelector(`[data-run-afficher="${type}"]`);
        const texteInitial = bouton ? bouton.innerHTML : '';
        try {
            if (bouton) {
                bouton.disabled = true;
                bouton.innerHTML = `<i class="fas fa-circle-notch fa-spin" aria-hidden="true"></i> ${
                    Utils.escapeHtml(I18n.t('common.loading'))}`;
            }
            const conserve = await API.get(`/kb/candidates/${encodeURIComponent(type)}`);
            const charge = {top_roles: conserve.roles || [],
                            global_stats: conserve.stats || {}};
            if (type === 'METIER') {
                this.handleBusinessMiningSuccess(charge, {annoncer: false});
            } else {
                this.handleAppMiningSuccess(charge, {annoncer: false});
            }
            this.rendreRunConserve(type);
        } catch (erreur) {
            Toast.error(I18n.t('common.error'), erreur.message);
            if (bouton) {
                bouton.disabled = false;
                bouton.innerHTML = texteInitial;
            }
        }
    },

    /**
     * Oublie le résultat conservé.
     *
     * Ce n'est pas une décision de gouvernance : rien n'est validé ni refusé,
     * et un mining ultérieur reproposera les mêmes rôles. C'est la sortie sans
     * laquelle un calcul lancé par erreur resterait annoncé comme du travail
     * en attente jusqu'à ce qu'un autre calcul le remplace.
     */
    async oublierRunConserve(type) {
        const confirme = await Confirm.demander({
            titre: I18n.t('run.forget_title'),
            message: I18n.t('run.forget_confirm'),
            confirmer: I18n.t('run.forget'),
            danger: true,
        });
        if (!confirme) return;

        try {
            await API.delete(`/kb/candidates/${encodeURIComponent(type)}`);
            this.runsConserves[type] = null;
            this.rendreRunConserve(type);
            if (typeof Cloche !== 'undefined') Cloche.rafraichir();
            Toast.success(I18n.t('common.success'), I18n.t('run.forgotten'));
        } catch (erreur) {
            Toast.error(I18n.t('common.error'), erreur.message);
        }
    },

    /**
     * Affiche un résultat de mining applicatif.
     *
     * Ce corps était écrit dans `launchMining`, donc atteignable seulement en
     * relançant un calcul de plusieurs minutes. Le résultat était pourtant
     * conservé côté serveur : c'est ce qui permet de le reprendre.
     *
     * `annoncer` distingue les deux cas. Un mining qui se termine mérite ses
     * bandeaux — c'est une nouvelle. Un résultat repris n'en est pas une : le
     * signaler comme tel apprendrait à ignorer les annonces.
     */
    handleAppMiningSuccess(data, { annoncer = true } = {}) {
        this.appMiningResults = data.top_roles || [];
        this.nomsDuCatalogue.app = data.noms_du_catalogue || [];

        const kbInfo = data.global_stats?.kb_integration;
        this.derniersSoclesExclus = (kbInfo && kbInfo.birth_rights_excluded) || 0;
        this.showBirthRightsBanner(this.derniersSoclesExclus);
        if (annoncer && this.derniersSoclesExclus > 0) {
            Toast.info(
                I18n.t('mining.kb_filtering'),
                I18n.t('mining.birth_rights_auto_excluded',
                       { count: this.derniersSoclesExclus })
            );
        }

        this.dernieresStatsApp = data.global_stats || {};
        this.showGlobalStatsGrid(this.dernieresStatsApp);

        const container = document.getElementById('mining-results-container');
        const countEl = document.getElementById('mining-results-count');
        if (countEl) countEl.textContent = I18n.t('mining.results_count', { count: this.appMiningResults.length });

        if (this.appMiningResults.length === 0) {
            if (container) container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon"><i class="fas fa-gem" aria-hidden="true"></i></div>
                    <h3>${Utils.escapeHtml(I18n.t('empty.no_roles_found'))}</h3>
                    <p>${Utils.escapeHtml(I18n.t('empty.no_roles_found_hint'))}</p>
                </div>
            `;
        } else {
            this.renderAppResults(this.appMiningResults);
            if (annoncer) {
                Toast.success(I18n.t('common.success'),
                              I18n.t('success.app_roles_found',
                                     { count: this.appMiningResults.length }));
            }
        }
        this.majBoutonDeNommageEnLot('app', this.appMiningResults.length);
    },

    /**
     * 🆕 SPRINT 1: Afficher le bandeau droits socles
     */
    showBirthRightsBanner(count) {
        const banner = document.getElementById('birth-rights-banner');
        if (!banner) return;

        // Un mining sans droit socle écarté doit effacer le bandeau du mining
        // précédent : laissé en place, il annonce une exclusion qui n'a pas eu
        // lieu.
        if (!count) {
            banner.style.display = 'none';
            return;
        }

        // La phrase entière passe par une clé : le gabarit portait « droits
        // universels automatiquement exclus du mining » en français autour
        // d'un compteur, et ce fragment ne se traduisait pas.
        const texte = document.getElementById('birth-rights-banner-text');
        if (texte) {
            texte.textContent = I18n.t('mining.birth_rights.excluded_banner', { count });
        }

        banner.style.display = 'flex';
    },

    /**
     * 🆕 SPRINT 1: Afficher les stats globales dans la grille moderne
     */
    showGlobalStatsGrid(stats) {
        const grid = document.getElementById('mining-global-stats');
        if (!grid) return;

        document.getElementById('mining-roles-count').textContent = stats.total_roles_found || 0;
        document.getElementById('mining-users-impacted').textContent = Utils.formatNumber(stats.users_impacted || 0);
        document.getElementById('mining-rights-covered').textContent = Utils.formatNumber(stats.rights_covered || 0);
        document.getElementById('mining-apps-covered').textContent = stats.apps_covered || 0;

        // Ce que ce modèle reprend de l'existant, et à quel prix. Trois
        // chiffres qui ne se lisent qu'ensemble : une couverture sans son coût
        // est une moitié d'arbitrage, et à sur-octroi nul — ce que le
        // croisement des profils rend atteignable — c'est la part laissée
        // dehors qui devient le seul coût restant.
        //
        // Ils viennent du **modèle final**, pas du moteur. Les compteurs du
        // moteur portent sur ce qu'il a produit : avant le retrait des
        // candidats déjà tranchés, avant la consolidation qui absorbe des
        // rôles, avant la hiérarchisation. Les cartes disaient le moteur, la
        // phrase juste en dessous disait le modèle, et les deux nombres se
        // contredisaient sur le même écran.
        //
        // Ils ne dépendent donc plus du mode : le mining exact n'octroie rien
        // en trop et couvre peu, ce qui est précisément la mesure qui justifie
        // le mode approché. Elle était cachée là où elle argumente le mieux.
        const qualite = stats.quality || {};
        const arbitrage = [
            ['mining-stat-coverage', 'mining-habs-coverage',
             qualite.coverage_pct, (valeur) => I18n.t('unit.percent', { value: Utils.valeurDansLaLangue(valeur) })],
            ['mining-stat-over-granted', 'mining-over-granted',
             qualite.over_granted_pct, (valeur) => I18n.t('unit.percent', { value: Utils.valeurDansLaLangue(valeur) })],
            // Un zéro affiché faute de mesure se lirait « rien hors du
            // modèle », l'exact contraire de « on ne sait pas » : la carte
            // disparaît plutôt que d'inventer.
            ['mining-stat-uncovered', 'mining-uncovered',
             qualite.uncovered_assignments, (valeur) => Utils.formatNumber(valeur)],
        ];
        arbitrage.forEach(([carte, valeur, mesure, ecrire]) => {
            const boite = document.getElementById(carte);
            const mesuree = typeof mesure === 'number';
            if (boite) boite.style.display = mesuree ? '' : 'none';
            const champ = document.getElementById(valeur);
            if (mesuree && champ) champ.textContent = ecrire(mesure);
        });

        // Le croisement des profils peut ne pas avoir été tenté : le dire, car
        // une couverture obtenue sans lui n'est pas celle qu'on aurait eue.
        const borne = document.getElementById('mining-croisement-borne');
        if (borne) {
            const nonTente = (stats.engine || {}).croisement_borne === true;
            borne.hidden = !nonTente;
            borne.textContent = nonTente ? I18n.t('mining.croisement_borne') : '';
        }

        // Le treillis s'est arrêté sur sa borne : le nombre de rôles n'est
        // pas le plus petit que ces données admettent, et le taire le ferait
        // lire comme tel.
        const treillis = document.getElementById('mining-treillis-borne');
        if (treillis) {
            const arrete = (stats.engine || {}).treillis_borne === true;
            treillis.hidden = !arrete;
            treillis.textContent = arrete ? I18n.t('mining.treillis_borne') : '';
        }

        // Des candidats écartés faute d'apport suffisant : le dire aussi. Un
        // modèle de cent trente-sept rôles là où le moteur en a trouvé trois
        // cent quatre-vingt-dix se lirait autrement comme un référentiel qui
        // ne porte que cela.
        const sousApport = document.getElementById('mining-sous-apport');
        if (sousApport) {
            const ecartes = (stats.engine || {}).candidats_sous_apport;
            const montrer = typeof ecartes === 'number' && ecartes > 0;
            sousApport.hidden = !montrer;
            sousApport.textContent = montrer
                ? I18n.t('mining.sous_apport', { count: Utils.formatNumber(ecartes) })
                : '';
        }

        // Ce que la sélection exacte a fait. Rien pour le glouton.
        const compteRendu = document.getElementById('mining-selection-compte-rendu');
        if (compteRendu) {
            const engine = stats.engine || {};
            const phrase = this.compteRenduDeSelection(engine, engine.selection_roles);
            compteRendu.hidden = !phrase;
            compteRendu.textContent = phrase;
        }

        // Qualite du modele : ce que valent les roles pris ensemble.
        const compression = document.getElementById('mining-compression');
        if (compression) compression.textContent = Utils.valeurDansLaLangue(qualite.compression_ratio ?? '-');
        const redondance = document.getElementById('mining-redundancy');
        if (redondance) {
            redondance.textContent = typeof qualite.redundancy_pct === 'number'
                ? I18n.t('unit.percent', { value: Utils.valeurDansLaLangue(qualite.redundancy_pct) })
                : '-';
        }
        const wsc = document.getElementById('mining-wsc');
        if (wsc) wsc.textContent = Utils.formatNumber(qualite.wsc ?? 0);
        // La même complexité, comptée avec l'héritage. Absente d'un serveur
        // d'avant ce lot : la carte disparaît plutôt que d'afficher zéro.
        const wscHierarchique = (stats.hierarchy || {}).wsc_hierarchique;
        const carteHierarchique = document.getElementById('mining-stat-wsc-hierarchique');
        if (carteHierarchique) {
            carteHierarchique.style.display = typeof wscHierarchique === 'number' ? '' : 'none';
        }
        const valeurHierarchique = document.getElementById('mining-wsc-hierarchique');
        if (valeurHierarchique && typeof wscHierarchique === 'number') {
            valeurHierarchique.textContent = Utils.formatNumber(wscHierarchique);
        }

        const resume = document.getElementById('mining-model-summary');
        if (resume) {
            const phrases = [];
            if (typeof qualite.compression_ratio === 'number') {
                phrases.push(I18n.t('mining.model.compression', {
                    ratio: Utils.valeurDansLaLangue(qualite.compression_ratio),
                    links: Utils.formatNumber(qualite.rbac_assignments || 0),
                    pairs: Utils.formatNumber(qualite.granted_pairs || 0)
                }));
            }
            const effet = this.phraseEffetDuModele(qualite);
            if (effet) phrases.push(effet);
            const hierarchie = stats.hierarchy || {};
            if (hierarchie.links > 0) {
                phrases.push(I18n.t('mining.model.hierarchy', {
                    links: Utils.valeurDansLaLangue(hierarchie.links),
                    depth: Utils.valeurDansLaLangue(hierarchie.max_depth)
                }));
            }
            const consolidation = stats.consolidation || {};
            if (consolidation.roles_absorbed > 0) {
                phrases.push(I18n.t('mining.model.consolidated', {
                    absorbed: Utils.valeurDansLaLangue(consolidation.roles_absorbed),
                    before: Utils.valeurDansLaLangue(consolidation.roles_before),
                    after: Utils.valeurDansLaLangue(consolidation.roles_after),
                    lost: Utils.formatNumber(consolidation.granted_pairs_lost || 0)
                }));
            }
            resume.textContent = phrases.join(' ');
        }

        grid.style.display = 'grid';
    },

    renderAppResults(results) {
        const container = document.getElementById('mining-results-container');
        if (!container) return;
        
        container.innerHTML = '';
        
        results.forEach((role, index) => {
            const card = document.createElement('div');
            // Toute la carte porte l'action, pas seulement son bouton : c'est
            // une cible de vingt fois la surface, et l'écran répond alors au
            // survol comme le reste du produit. Le bouton reste — c'est lui qui
            // rend l'action atteignable au clavier, ce qu'une carte ne peut pas
            // faire sans emprisonner les marqueurs de définition qu'elle
            // contient dans un élément focusable.
            card.className = 'mining-role-card surface-actionnable';
            card.dataset.index = index;
            card.dataset.miningRole = 'app';
            card.dataset.miningIndex = index;
            // Un role approche peut octroyer des droits que certains membres ne
            // detiennent pas encore : on l'affiche sur la carte, pas seulement
            // dans les statistiques globales.
            const overGranted = role.over_granted || 0;
            const fitBadge = overGranted > 0
                ? `<span class="mining-role-stat mining-role-stat--warned" data-definition="mining.role.over_granted_hint"><i class="fas fa-triangle-exclamation" aria-hidden="true"></i> ${Utils.escapeHtml(I18n.t('mining.role.fit', { value: role.fit_pct }))}</span>`
                : '';

            // Ce qu'apporte le role par rapport aux roles mieux classes, ce
            // qu'il remplace, et ce qu'il contient.
            const redundancyBadge = role.redundancy_pct > 0
                ? `<span class="mining-role-stat mining-role-stat--warned" data-definition="mining.role.redundancy_hint"><i class="fas fa-clone" aria-hidden="true"></i> ${Utils.escapeHtml(I18n.t('mining.role.redundancy', { value: role.redundancy_pct }))}</span>`
                : '';
            const absorbsBadge = role.absorbs?.length > 0
                ? `<span class="mining-role-stat" title="${Utils.escapeHtml(role.absorbs.join(', '))}"><i class="fas fa-object-group" aria-hidden="true"></i> ${Utils.escapeHtml(I18n.t('mining.role.absorbs', { count: role.absorbs.length }))}</span>`
                : '';
            const subRolesBadge = role.sub_roles?.length > 0
                ? `<span class="mining-role-stat" data-definition="mining.role.sub_roles_hint"><i class="fas fa-sitemap" aria-hidden="true"></i> ${Utils.escapeHtml(I18n.t('mining.role.sub_roles_count', { count: role.sub_roles.length }))}</span>`
                : '';
            // Ce que ce candidat compose déjà du catalogue. Sans cette
            // mention, l'intégrateur reçoit deux fois le même ensemble de
            // droits sans lien entre eux, et une évolution du rôle validé
            // cesse de se propager.
            const composesBadge = role.sub_roles_valides_names?.length > 0
                ? `<span class="mining-role-stat" title="${Utils.escapeHtml(role.sub_roles_valides_names.join(', '))}"><i class="fas fa-layer-group" aria-hidden="true"></i> ${Utils.escapeHtml(I18n.t('mining.role.composes_validated', { count: role.sub_roles_valides_names.length }))}</span>`
                : '';

            card.innerHTML = `
                <div class="mining-role-header">
                    <span class="mining-role-title">${Utils.escapeHtml(role.name || I18n.t('role.unnamed'))}</span>
                    <span class="badge badge-role-app">${Utils.escapeHtml(I18n.t('role.type.application'))}</span>
                </div>
                <div class="mining-role-stats">
                    <span class="mining-role-stat"><i class="fas fa-users" aria-hidden="true"></i> ${Utils.escapeHtml(I18n.t('unit.users', { count: Utils.formatNumber(role.user_count || 0) }))}</span>
                    <span class="mining-role-stat"><i class="fas fa-key" aria-hidden="true"></i> ${Utils.escapeHtml(I18n.t('unit.rights', { count: Utils.formatNumber(role.right_count || role.rights?.length || 0) }))}</span>
                    ${fitBadge}
                    ${redundancyBadge}
                    ${absorbsBadge}
                    ${subRolesBadge}
                    ${composesBadge}
                </div>
                ${this.renderDecisionPrise(role)}
                <button class="btn btn-primary btn-sm mining-role-action" data-mining-role="app" data-mining-index="${index}">
                    <i class="fas fa-certificate" aria-hidden="true"></i> ${Utils.escapeHtml(I18n.t('action.validate_role'))}
                </button>
            `;
            container.appendChild(card);
        });

        // Les cartes viennent d'être écrites : leurs indices
        // portent une définition, qui doit être atteignable
        // autrement qu'à la souris.
        if (typeof Definitions !== 'undefined') Definitions.preparer(container);
        // Le même marquage que pour le mining métier : un seul mécanisme, deux
        // moteurs. Deux marquages écrits séparément finiraient par ne pas dire
        // la même chose du même candidat.
        this.marquerLesCartes(container, results);
        this.scorerLesCartes(container, results);
    },

    /**
     * Les chiffres affichés au moment où quelqu'un décide.
     *
     * Ils accompagnent la validation et le refus pour que l'historique du
     * workspace dise sur quoi la décision s'est appuyée, et pas seulement
     * qu'elle a eu lieu. Ni porteurs ni valeurs d'attributs : ce sont des
     * données personnelles, et l'historique s'exporte avec le workspace.
     *
     * Leur présence distingue une décision sur un candidat d'une composition
     * manuelle, qui n'a pas de chiffres et n'est l'exemple de rien.
     */
    indicateursDeDecision(role) {
        if (!role) return null;
        const chiffres = {
            right_count: role.right_count ?? role.rights?.length ?? null,
            user_count: role.user_count ?? null,
            // `over_granted` côté applicatif, `stats_over_provisioning` côté
            // métier : le même coût, deux moteurs, deux noms.
            over_granted: role.over_granted ?? role.stats_over_provisioning ?? null,
            fit_pct: role.fit_pct ?? null,
            redundancy_pct: role.redundancy_pct ?? null,
            sub_roles: role.sub_roles?.length ?? null,
            absorbs: role.absorbs?.length ?? null,
        };
        const explication = this.explicationAffichee;
        if (explication) {
            Object.assign(chiffres, {
                explicable: explication.explicable,
                termes_de_regle: explication.regle.length,
                purete: explication.purete,
                couverture: explication.couverture,
                lift: explication.lift,
                p_valeur: explication.p_valeur,
                exceptions: explication.exceptions,
                sur_octroi: explication.sur_octroi,
            });
        }
        Object.keys(chiffres).forEach(cle => {
            if (chiffres[cle] === null || chiffres[cle] === undefined) delete chiffres[cle];
        });
        return chiffres;
    },

    /**
     * Affiche le diagnostic d'un rôle métier.
     *
     * Il n'y a pas d'explication à chercher : le rôle *est* une règle. Seuls
     * comptent les constats sur ce que cette règle coûterait appliquée telle
     * quelle, que le serveur a joints au candidat.
     */
    renderDiagnosticMetier(role) {
        const zone = document.getElementById('biz-diagnostic-result');
        if (!zone) return;
        const icones = { favorable: 'fa-circle-check', reserve: 'fa-triangle-exclamation',
                         bloquant: 'fa-circle-xmark' };
        zone.innerHTML = (role?.diagnostic || []).map(constat => `
            <li class="explication__constat explication__constat--${Utils.escapeHtml(constat.verdict)}">
                <i class="fas ${icones[constat.verdict] || icones.reserve}" aria-hidden="true"></i>
                <span>${Utils.escapeHtml(I18n.t(constat.code, this.parametresDuConstat(constat.params)))}</span>
            </li>`).join('');
    },

    // -------------------------------------------- annotateur sémantique

    /**
     * Lit une fois l'état de l'annotateur et dit ce qu'un envoi coûterait.
     *
     * L'écran annonce ce qui quittera le serveur **avant** de l'envoyer.
     * Découvrir après coup qu'un libellé de droit est parti chez un
     * fournisseur n'est pas un consentement.
     */
    async chargerEtatDeLAnnotateur(prefixe) {
        const zone = document.getElementById(`${prefixe}-annotator-state`);
        if (!zone) return;
        if (!this.etatAnnotateur) {
            try {
                this.etatAnnotateur = await API.getAnnotatorStatus();
            } catch (erreur) {
                this.etatAnnotateur = { actif: false };
            }
        }
        this.renderEtatDeLAnnotateur(prefixe);
    },

    renderEtatDeLAnnotateur(prefixe) {
        const zone = document.getElementById(`${prefixe}-annotator-state`);
        const actions = document.getElementById(`${prefixe}-annotator-actions`);
        const etat = this.etatAnnotateur;
        if (!zone || !actions || !etat) return;

        // L'explication rédigée est un autre usage, avec sa propre
        // autorisation : elle peut être ouverte quand le nommage est fermé, et
        // l'inverse. Son bouton suit son usage, pas celui du nommage.
        const explication = document.getElementById(`${prefixe}-explication-actions`);
        if (explication) {
            explication.hidden = !(etat.explication && etat.explication.actif);
        }

        if (!etat.actif) {
            zone.textContent = this.raisonDeLAnnotateurInactif(etat);
            actions.hidden = true;
            return;
        }

        const categories = [];
        if (etat.envoie_libelles_de_droits) categories.push(I18n.t('annotator.category.rights'));
        if (etat.envoie_regle_metier) categories.push(I18n.t('annotator.category.rule'));
        if (etat.envoie_noms_valides) categories.push(I18n.t('annotator.category.names'));

        const lignes = [Utils.escapeHtml(I18n.t('annotator.model', { modele: etat.modele }))];
        // Sans matière autorisée, le modèle ne verrait que deux nombres et
        // inventerait une finalité. Le produit ne pose pas la question.
        if (categories.length === 0) {
            zone.innerHTML = lignes.map(ligne => `<div>${ligne}</div>`).join('')
                + `<div class="annotateur__avertissement">
                       <i class="fas fa-triangle-exclamation" aria-hidden="true"></i>
                       <span>${Utils.escapeHtml(I18n.t('annotator.nothing_to_name'))}</span>
                   </div>`;
            actions.hidden = true;
            return;
        }
        lignes.push(Utils.escapeHtml(
            I18n.t('annotator.will_send', { categories: categories.join(', ') })));

        // Le trajet compte autant que le contenu : envoyer un libellé de droit
        // à 127.0.0.1 et l'envoyer sur Internet ne sont pas le même geste.
        const trajet = etat.locale
            ? `<div>${Utils.escapeHtml(I18n.t('annotator.stays_local', { hote: etat.hote }))}</div>`
            : `<div class="annotateur__avertissement">
                   <i class="fas fa-triangle-exclamation" aria-hidden="true"></i>
                   <span>${Utils.escapeHtml(I18n.t('annotator.leaves_machine', { hote: etat.hote }))}</span>
               </div>`;

        zone.innerHTML = lignes.map(ligne => `<div>${ligne}</div>`).join('') + trajet;
        actions.hidden = false;
    },

    /**
     * Demande une proposition pour le rôle ouvert.
     *
     * La charge est composée champ par champ : les porteurs ne sont pas
     * transmis, et l'API les refuserait de toute façon.
     */
    async proposerUnNomDeRole(prefixe) {
        const bouton = document.getElementById(
            prefixe === 'app' ? 'ask-role-name' : 'ask-biz-role-name');
        const index = Number(document.getElementById(`${prefixe}-role-idx`)?.value);
        const role = (prefixe === 'app' ? this.appMiningResults : this.results)?.[index];
        if (!bouton || !role) return;

        const libelle = bouton.innerHTML;
        bouton.innerHTML = `<i class="fas fa-spinner fa-spin" aria-hidden="true"></i> ${
            Utils.escapeHtml(I18n.t('annotator.asking'))}`;
        bouton.disabled = true;
        try {
            this.propositionDeNom = await API.suggestRoleName({
                role: {
                    id: role.id || String(index),
                    right_count: role.right_count ?? role.rights?.length ?? 0,
                    user_count: role.user_count ?? 0,
                    rights: role.rights || [],
                },
                // Un rôle métier porte déjà sa règle : c'est sa définition.
                // Un rôle applicatif n'en a une que si l'explication a été
                // demandée.
                regle: prefixe === 'biz'
                    ? Object.entries(role.attributes || {}).map(
                        ([attribut, valeur]) => ({ attribut, valeur: String(valeur) }))
                    : (this.explicationAffichee?.regle || []),
                locale: I18n.currentLocale,
            });
            this.renderProposition(prefixe);
        } catch (erreur) {
            Toast.error(I18n.t('common.error'), I18n.t('annotator.unavailable'));
        } finally {
            bouton.innerHTML = libelle;
            bouton.disabled = false;
        }
    },

    /**
     * Demande le paragraphe qui explique le rôle ouvert.
     *
     * C'est le livrable que le consultant rédige à la main, rôle par rôle, à
     * la fin du projet. Les chiffres viennent du calcul ; le modèle ne fait
     * que les mettre en phrase, et le serveur refuse une phrase qui en
     * inventerait un.
     */
    async expliquerLeRole(prefixe) {
        const bouton = document.getElementById(`ask-${prefixe}-explication`);
        const index = Number(document.getElementById(`${prefixe}-role-idx`)?.value);
        const role = (prefixe === 'app' ? this.appMiningResults : this.results)?.[index];
        if (!bouton || !role) return;

        const libelle = bouton.innerHTML;
        bouton.innerHTML = `<i class="fas fa-spinner fa-spin" aria-hidden="true"></i> ${
            Utils.escapeHtml(I18n.t('annotator.asking'))}`;
        bouton.disabled = true;
        try {
            const rendu = await API.post('/assistance/explication-de-role', {
                // Les grandeurs partent telles que l'écran les montre : c'est
                // sur elles que porte le contrôle des nombres, et c'est ce que
                // l'utilisateur a sous les yeux qu'il fait expliquer.
                role: {
                    name: role.name || '',
                    user_count: role.user_count ?? 0,
                    right_count: role.right_count ?? role.rights?.length ?? 0,
                    coverage_pct: role.coverage_pct ?? null,
                    stats_over_provisioning: role.stats_over_provisioning ?? null,
                    rights: role.rights || [],
                },
                explication: {
                    regle: prefixe === 'biz'
                        ? Object.entries(role.attributes || {}).map(
                            ([attribut, valeur]) => ({ attribut, valeur: String(valeur) }))
                        : (this.explicationAffichee?.regle || []),
                },
                locale: I18n.currentLocale,
            });
            this.renderExplicationRedigee(prefixe, rendu);
        } catch (erreur) {
            // Un refus de nombre inventé n'est pas une panne du modèle : c'est
            // le contrôle qui a fait son travail, et l'utilisateur doit
            // pouvoir le distinguer d'un serveur injoignable.
            // Le serveur compose déjà la phrase — code et paramètres — et le
            // client la traduit : elle nomme les chiffres inventés.
            Toast.error(I18n.t('common.error'),
                        erreur.message || I18n.t('annotator.unavailable'));
        } finally {
            bouton.innerHTML = libelle;
            bouton.disabled = false;
        }
    },

    /** Le paragraphe, tel que le serveur l'a validé. */
    renderExplicationRedigee(prefixe, rendu) {
        const zone = document.getElementById(`${prefixe}-explication`);
        if (!zone) return;
        zone.hidden = false;
        zone.innerHTML = `
            <p class="form-hint">${Utils.escapeHtml(I18n.t('explication.hint'))}</p>
            <p class="explication__texte">${Utils.escapeHtml(rendu.explication)}</p>`;
    },

    renderProposition(prefixe) {
        const zone = document.getElementById(`${prefixe}-annotator-proposal`);
        if (!zone) return;
        const proposition = this.propositionDeNom;
        if (!proposition) {
            zone.innerHTML = '';
            return;
        }
        zone.innerHTML = `
            <div class="annotateur__proposition">
                <div class="annotateur__nom">${Utils.escapeHtml(proposition.nom)}</div>
                <div class="annotateur__description">${
                    Utils.escapeHtml(proposition.description || '')}</div>
                <button class="btn btn-secondary btn-sm" data-apply-name="${
                    Utils.escapeHtml(prefixe)}">
                    <i class="fas fa-arrow-up" aria-hidden="true"></i> ${
                        Utils.escapeHtml(I18n.t('annotator.apply'))}</button>
                <div class="form-hint">${Utils.escapeHtml(I18n.t('annotator.review'))}</div>
            </div>`;
    },

    /** Recopie la proposition dans les champs. C'est le seul moment où elle agit. */
    appliquerLaProposition(prefixe) {
        const proposition = this.propositionDeNom;
        if (!proposition) return;
        const nom = document.getElementById(`${prefixe}-role-name`);
        const description = document.getElementById(`${prefixe}-role-desc`);
        if (nom) nom.value = proposition.nom;
        if (description && proposition.description) {
            description.value = proposition.description;
        }
        Toast.success(I18n.t('common.success'), I18n.t('annotator.applied'));
    },


    // ------------------------------------------------- nommage en lot

    //: Le lot en cours. Un objet plutôt que cinq champs épars : l'écran doit
    //  pouvoir dire, à tout instant, ce qu'il fait et où il en est.
    lot: null,

    /**
     * Ouvre le nommage en lot sur les candidats affichés.
     *
     * Le calcul d'un mining dure des minutes ; la mise en mots dure des jours.
     * C'est le poste le plus coûteux d'un projet de role mining, et le seul
     * que le produit laissait entièrement à la main — un consultant qui nomme
     * trois cents rôles y passe deux journées, et ses cinquante derniers
     * intitulés ne ressemblent pas aux cinquante premiers.
     */
    async ouvrirLeNommageEnLot(prefixe) {
        const roles = (prefixe === 'app' ? this.appMiningResults : this.results) || [];
        if (roles.length === 0) return;

        await this.chargerEtatDeLAnnotateur(prefixe);
        this.lot = {
            prefixe,
            // Une copie : tant que le lot n'est pas conservé, il ne touche pas
            // aux cartes affichées. Fermer la fenêtre sans conserver ne doit
            // rien changer à l'écran de résultats.
            lignes: roles.map((role, index) => ({
                index,
                id: role.id || String(index),
                nom: role.name || '',
                description: this.roleDescription(role) || '',
                // Cochée : le geste attendu est de tout nommer. Une ligne se
                // décoche dès qu'elle a reçu une proposition, pour qu'une
                // relance ne refasse pas le travail déjà payé.
                demandee: true,
                etat: 'attente',
            })),
            enCours: false,
            arret: false,
            faits: 0,
            echecs: 0,
            // Secondes restantes avant reprise, quand le serveur régule.
            attente: null,
            // Durées observées, en millisecondes. La durée restante s'estime
            // sur ce qui s'est réellement passé : aucune valeur de référence
            // n'est écrite ici, elle serait fausse sur la moitié des postes.
            durees: [],
        };
        this.renderLeLot();
        Modal.open('batch-naming-modal');
    },

    /**
     * Ce qui partira, et combien de fois.
     *
     * Envoyer une demande à un fournisseur et lui en envoyer trois cents ne
     * sont pas le même geste. L'écran unitaire annonce déjà les catégories ;
     * celui-ci doit annoncer le volume, parce que c'est lui qui change.
     */
    /**
     * Pourquoi le modèle n'est pas proposé, et où le régler.
     *
     * Deux conditions, deux cartes des paramètres : le point de terminaison dit
     * **où** part la question, la matrice d'assistance dit **ce qui** a le
     * droit de partir. Le même message pour les deux laissait chercher dans la
     * mauvaise carte.
     */
    raisonDeLAnnotateurInactif(etat) {
        if (etat && etat.point_de_terminaison === false) {
            // Le nom de la carte vient de son titre : il ne peut pas diverger.
            return I18n.t('annotator.no_endpoint', {
                carte: I18n.t('endpoints.title') });
        }
        if (etat && etat.usage_ouvert === false) {
            return I18n.t('annotator.usage_closed', {
                usage: I18n.t(`assistance.usage.${etat.usage}`),
                carte: I18n.t('assistance.title') });
        }
        return I18n.t('annotator.disabled');
    },

    annonceDuLot() {
        const etat = this.etatAnnotateur;
        if (!etat || !etat.actif) return this.raisonDeLAnnotateurInactif(etat);

        const categories = [];
        if (etat.envoie_libelles_de_droits) categories.push(I18n.t('annotator.category.rights'));
        if (etat.envoie_regle_metier) categories.push(I18n.t('annotator.category.rule'));
        if (etat.envoie_noms_valides) categories.push(I18n.t('annotator.category.names'));
        if (categories.length === 0) return I18n.t('annotator.nothing_to_name');

        const demandees = this.lot.lignes.filter((ligne) => ligne.demandee).length;
        const trajet = etat.locale
            ? I18n.t('batch.stays_local', { count: demandees, hote: etat.hote })
            : I18n.t('batch.leaves_machine', { count: demandees, hote: etat.hote });
        return `${I18n.t('annotator.will_send', { categories: categories.join(', ') })} ${trajet}`;
    },

    renderLeLot() {
        const corps = document.getElementById('batch-naming-rows');
        const annonce = document.getElementById('batch-naming-annonce');
        const depart = document.getElementById('batch-naming-start');
        const arret = document.getElementById('batch-naming-stop');
        if (!corps || !this.lot) return;

        if (annonce) annonce.textContent = this.annonceDuLot();
        corps.innerHTML = this.lot.lignes.map(
            (ligne) => this.ligneDuLot(ligne)).join('');
        if (depart) {
            depart.hidden = this.lot.enCours;
            depart.disabled = !this.lotPosable();
        }
        if (arret) arret.hidden = !this.lot.enCours;
        this.renderAvancementDuLot();
    },

    /**
     * Le lot peut-il partir ?
     *
     * Trois conditions, et l'écran doit pouvoir dire laquelle manque :
     * l'assistance est en place, une matière est autorisée, et au moins une
     * ligne est cochée. Un bouton inerte sans explication passe pour une panne.
     */
    lotPosable() {
        const etat = this.etatAnnotateur;
        if (!etat || !etat.actif) return false;
        if (!etat.envoie_libelles_de_droits && !etat.envoie_regle_metier
            && !etat.envoie_noms_valides) return false;
        return this.lot.lignes.some((ligne) => ligne.demandee);
    },

    ligneDuLot(ligne) {
        const role = this.roleDuLot(ligne);
        const mesures = [
            I18n.t('unit.users', { count: Utils.formatNumber(role.user_count || 0) }),
            I18n.t('unit.rights', {
                count: Utils.formatNumber(role.right_count || role.rights?.length || 0) }),
        ].join(' · ');
        return `
            <tr data-lot-ligne="${ligne.index}">
                <td>
                    <input type="checkbox" data-lot-demandee="${ligne.index}"
                           ${ligne.demandee ? 'checked' : ''}
                           aria-label="${Utils.escapeHtml(
                               I18n.t('batch.column.ask'))}">
                </td>
                <td>
                    <div>${Utils.escapeHtml(ligne.id)}</div>
                    <div class="form-hint">${Utils.escapeHtml(mesures)}</div>
                </td>
                <td>
                    <input type="text" class="form-input" data-lot-nom="${ligne.index}"
                           value="${Utils.escapeHtml(ligne.nom)}"
                           aria-label="${Utils.escapeHtml(I18n.t('batch.column.name'))}">
                </td>
                <td>
                    <input type="text" class="form-input" data-lot-description="${ligne.index}"
                           value="${Utils.escapeHtml(ligne.description)}"
                           aria-label="${Utils.escapeHtml(
                               I18n.t('batch.column.description'))}">
                </td>
                <td>${Utils.escapeHtml(I18n.t(`batch.state.${ligne.etat}`))}</td>
            </tr>`;
    },

    roleDuLot(ligne) {
        const roles = this.lot.prefixe === 'app'
            ? this.appMiningResults : this.results;
        return (roles || [])[ligne.index] || {};
    },

    /**
     * Où en est le lot, et combien de temps il reste.
     *
     * La durée restante n'est pas une constante du produit : elle se déduit
     * des réponses déjà obtenues. Un modèle local sur un poste à huit
     * gigaoctets et un fournisseur distant ne répondent pas au même rythme, et
     * annoncer une durée écrite dans le code serait mentir la moitié du temps.
     */
    renderAvancementDuLot() {
        const zone = document.getElementById('batch-naming-avancement');
        if (!zone || !this.lot) return;
        const total = this.lot.lignes.filter((ligne) => ligne.demandee).length
            + this.lot.faits;
        if (!this.lot.enCours && this.lot.faits === 0) {
            zone.textContent = '';
            return;
        }
        const morceaux = [I18n.t('batch.progress',
                                 { faits: this.lot.faits, total })];
        if (this.lot.echecs > 0) {
            morceaux.push(I18n.t('batch.failures', { count: this.lot.echecs }));
        }
        if (this.lot.attente) {
            morceaux.push(I18n.t('batch.waiting_server',
                                 { secondes: this.lot.attente }));
        }
        const restantes = total - this.lot.faits;
        if (this.lot.enCours && this.lot.durees.length >= 3 && restantes > 0) {
            const moyenne = this.lot.durees.reduce((a, b) => a + b, 0)
                / this.lot.durees.length;
            morceaux.push(I18n.t('batch.remaining', {
                minutes: Math.max(1, Math.round(moyenne * restantes / 60000)) }));
        }
        zone.textContent = morceaux.join(' — ');
    },

    /**
     * Lance la file. Une demande à la fois, jamais en parallèle.
     *
     * Un modèle local répond à une question à la fois : lui en envoyer trente
     * ensemble ne va pas trente fois plus vite, cela sature la mémoire du
     * poste — et chez un fournisseur distant, une rafale est un incident de
     * débit. La file est donc séquentielle, et c'est aussi ce qui rend la
     * piste d'audit lisible.
     */
    async lancerLeLot() {
        if (!this.lot || this.lot.enCours || !this.lotPosable()) return;
        this.lot.enCours = true;
        this.lot.arret = false;
        this.renderLeLot();

        const aFaire = this.lot.lignes.filter((ligne) => ligne.demandee);
        for (const ligne of aFaire) {
            if (this.lot.arret) break;
            await this.traiterUneLigneDuLot(ligne);
            this.lot.faits += 1;
            this.majLaLigneDuLot(ligne);
            this.renderAvancementDuLot();
        }

        this.lot.enCours = false;
        this.lot.attente = null;
        this.renderLeLot();
    },

    /**
     * Une ligne, et les attentes que le serveur demande.
     *
     * Le serveur borne le débit de l'assistance. Quand il refuse, il dit
     * combien de temps attendre : la file se cale dessus et reprend la même
     * ligne, au lieu de la perdre. Sans cela, un lot de trois cents rôles
     * perdait tout après les premiers — et l'écran annonçait « sans réponse du
     * modèle » alors que le modèle n'avait rien reçu.
     *
     * Le nombre d'attentes est borné : un serveur qui refuse indéfiniment doit
     * finir par rendre la main, sans quoi la fenêtre tourne sans fin devant
     * quelqu'un qui ne sait pas pourquoi.
     */
    async traiterUneLigneDuLot(ligne) {
        for (let attente = 0; attente <= MiningPage.ATTENTES_MAX; attente += 1) {
            if (this.lot.arret) return;
            ligne.etat = 'en_cours';
            this.majLaLigneDuLot(ligne);
            const depart = Date.now();
            try {
                const proposition = await this.demanderUnNom(this.roleDuLot(ligne));
                ligne.nom = proposition.nom;
                ligne.description = proposition.description || ligne.description;
                ligne.etat = 'propose';
                // La ligne sort de la file : une relance après un arrêt ne doit
                // pas repayer une demande déjà obtenue.
                ligne.demandee = false;
                this.lot.durees.push(Date.now() - depart);
                return;
            } catch (erreur) {
                const secondes = this.delaiDeReprise(erreur);
                if (secondes === null || attente === MiningPage.ATTENTES_MAX) {
                    // Deux causes, deux états. « Sans réponse » est le modèle
                    // qui n'a pas répondu ; « débit » est le serveur qui a
                    // refusé. Les confondre envoie chercher au mauvais endroit.
                    ligne.etat = secondes === null ? 'echec' : 'debit';
                    this.lot.echecs += 1;
                    return;
                }
                ligne.etat = 'attente_serveur';
                this.majLaLigneDuLot(ligne);
                await this.patienter(secondes);
            }
        }
    },

    /**
     * Combien de temps le serveur demande d'attendre, ou rien.
     *
     * Rien ne vaut « ce n'est pas une question de débit » : l'appelant
     * distingue alors le modèle muet du serveur qui régule.
     */
    delaiDeReprise(erreur) {
        if (!erreur || erreur.status !== 429) return null;
        const annonce = Number(erreur.details && erreur.details.retry_after);
        // Une seconde de marge : le seau se remplit de façon continue, et
        // repartir à la seconde exacte retombe parfois sur un refus.
        return Math.min(MiningPage.ATTENTE_MAX_S,
                        Math.max(1, Number.isFinite(annonce) ? annonce + 1 : 1));
    },

    /** Attend, en disant combien de temps il reste. */
    async patienter(secondes) {
        for (let reste = secondes; reste > 0 && !this.lot.arret; reste -= 1) {
            this.lot.attente = reste;
            this.renderAvancementDuLot();
            await new Promise((suite) => setTimeout(suite, 1000));
        }
        this.lot.attente = null;
        this.renderAvancementDuLot();
    },

    arreterLeLot() {
        if (!this.lot) return;
        // L'arrêt prend effet après la demande en cours : interrompre un appel
        // déjà parti ne l'empêche pas d'avoir quitté le serveur, et la piste
        // d'audit le dira. Mieux vaut une réponse de plus qu'une trace fausse.
        this.lot.arret = true;
    },

    /** Une demande, composée champ par champ. Les porteurs ne sortent pas. */
    async demanderUnNom(role) {
        return API.suggestRoleName({
            role: {
                id: role.id || '',
                right_count: role.right_count ?? role.rights?.length ?? 0,
                user_count: role.user_count ?? 0,
                rights: role.rights || [],
            },
            regle: this.lot.prefixe === 'biz'
                ? Object.entries(role.attributes || {}).map(
                    ([attribut, valeur]) => ({ attribut, valeur: String(valeur) }))
                : [],
            locale: I18n.currentLocale,
        });
    },

    /**
     * Redessine une seule ligne.
     *
     * Refaire tout le tableau à chaque réponse effacerait ce que l'utilisateur
     * est en train de corriger dans un champ, et ferait perdre le focus.
     */
    majLaLigneDuLot(ligne) {
        const rangee = document.querySelector(`[data-lot-ligne="${ligne.index}"]`);
        if (!rangee) return;
        rangee.outerHTML = this.ligneDuLot(ligne);
    },

    modifierLaLigneDuLot(index, champ, valeur) {
        const ligne = this.lot?.lignes[index];
        if (!ligne) return;
        ligne[champ] = valeur;
        if (champ === 'demandee') {
            this.renderAvancementDuLot();
            const annonce = document.getElementById('batch-naming-annonce');
            if (annonce) annonce.textContent = this.annonceDuLot();
            const depart = document.getElementById('batch-naming-start');
            if (depart) depart.disabled = !this.lotPosable();
        }
    },

    /**
     * Conserve les noms relus. C'est le seul moment où le lot agit.
     *
     * Ils sont écrits sur les candidats conservés — le travail de relecture
     * d'une heure ne doit pas se perdre à un rechargement de page — et repris
     * sur les cartes affichées, qui alimentent le formulaire de validation.
     * Rien n'est validé pour autant : un candidat nommé attend toujours qu'on
     * décide de lui.
     */
    async conserverLesNomsDuLot() {
        if (!this.lot) return;
        const roles = this.lot.prefixe === 'app'
            ? this.appMiningResults : this.results;
        const noms = {};
        this.lot.lignes.forEach((ligne) => {
            const nom = (ligne.nom || '').trim();
            if (!nom) return;
            noms[ligne.id] = { name: nom, description: (ligne.description || '').trim() };
            const role = (roles || [])[ligne.index];
            if (role) {
                role.name = nom;
                if (ligne.description) {
                    role.description = ligne.description;
                    delete role.description_key;
                    delete role.description_params;
                }
            }
        });

        if (Object.keys(noms).length === 0) {
            Toast.error(I18n.t('common.error'), I18n.t('batch.nothing_to_keep'));
            return;
        }

        try {
            await API.nommerLesCandidats(
                this.lot.prefixe === 'app' ? 'APPLICATIF' : 'METIER', { noms });
        } catch (erreur) {
            // Les cartes portent déjà les noms : le dire est indispensable,
            // sinon l'utilisateur croit son travail à l'abri d'un rechargement
            // alors qu'il ne vit que dans cette page.
            Toast.error(I18n.t('common.error'), I18n.t('batch.not_persisted'));
        }

        if (this.lot.prefixe === 'app') {
            this.renderAppResults(this.appMiningResults);
        } else {
            this.renderBusinessResults(this.results);
        }
        Toast.success(I18n.t('common.success'),
                      I18n.t('batch.kept', { count: Object.keys(noms).length }));
        Modal.close();
    },

    /** Montre le bouton de nommage en lot dès qu'il y a des candidats. */
    majBoutonDeNommageEnLot(prefixe, nombre) {
        const bouton = document.getElementById(`${prefixe}-nommage-lot`);
        if (bouton) bouton.hidden = nombre === 0;
    },

    // ------------------------------------------------ explication métier

    /**
     * Charge une fois les colonnes du référentiel d'identités.
     *
     * Les colonnes ne sont pas connues à l'avance : elles viennent des
     * fichiers du client, jamais d'une liste écrite ici.
     */
    async chargerAttributsDExplication() {
        const conteneur = document.getElementById('app-explanation-attributes');
        if (!conteneur || conteneur.dataset.charges === '1') return;

        try {
            const data = await API.getIdentityAttributes();
            const attributs = data.attributes || [];
            conteneur.innerHTML = attributs.length === 0
                ? `<div class="attribute-empty">${Utils.escapeHtml(I18n.t('mining.no_usable_attribute'))}</div>`
                : attributs.map(attribut => `
                    <label class="attribute-choice">
                        <input type="checkbox" name="explanation_attribute" value="${Utils.escapeHtml(attribut.name)}">
                        <span>${Utils.escapeHtml(attribut.name)}</span>
                    </label>`).join('');
            conteneur.dataset.charges = '1';
        } catch (erreur) {
            Toast.error(I18n.t('common.error'), I18n.t('mining.attributes_failed'));
        }
    },

    /** Demande au serveur la règle qui décrit les porteurs du rôle ouvert. */
    async expliquerRoleApplicatif() {
        const bouton = document.getElementById('explain-app-role');
        const index = Number(document.getElementById('app-role-idx')?.value);
        const role = this.appMiningResults?.[index];
        if (!bouton || !role) return;

        const attributs = Array.from(
            document.querySelectorAll('#app-explanation-attributes input:checked')
        ).map(case_ => case_.value);
        if (attributs.length === 0) {
            Toast.warning(I18n.t('common.warning'), I18n.t('validation.select_attribute'));
            return;
        }

        const libelle = bouton.innerHTML;
        bouton.innerHTML = `<i class="fas fa-spinner fa-spin" aria-hidden="true"></i> ${
            Utils.escapeHtml(I18n.t('explanation.running'))}`;
        bouton.disabled = true;
        try {
            const reponse = await API.explainRoles({
                roles: [{ id: role.id || String(index), users: role.users || [] }],
                attributes: attributs,
                min_coverage: Number(document.getElementById('app-explanation-coverage').value),
                min_reliability: Number(document.getElementById('app-explanation-reliability').value),
                min_lift: Number(document.getElementById('app-explanation-lift').value),
                max_p_value: Number(document.getElementById('app-explanation-pvalue').value),
                max_depth: Number(document.getElementById('app-explanation-depth').value),
            });
            this.explicationAffichee = reponse.explications?.[0] || null;
            this.renderExplication(this.explicationAffichee);
        } catch (erreur) {
            Toast.error(I18n.t('common.error'), I18n.t('explanation.failed'));
        } finally {
            bouton.innerHTML = libelle;
            bouton.disabled = false;
        }
    },

    /**
     * Met en forme les chiffres d'un constat dans la langue de l'interface.
     *
     * Le serveur rend des rapports bruts et nomme le constat ; la phrase est
     * composée ici. Une p-valeur infime s'écrirait « 0,000 » : en dessous du
     * seuil d'affichage, on écrit l'inégalité plutôt qu'un zéro qui ferait
     * croire à une certitude absolue.
     */
    parametresDuConstat(params) {
        const PLANCHER_P = 0.001;
        const mis = {};
        Object.entries(params || {}).forEach(([cle, valeur]) => {
            if (cle === 'part' || cle === 'attendu') {
                mis[cle] = Utils.formatPercent(valeur * 100);
            } else if (cle === 'lift') {
                mis[cle] = Utils.formatDecimal(valeur, 2);
            } else if (cle === 'p') {
                mis[cle] = valeur < PLANCHER_P
                    ? I18n.t('explanation.p_below', { value: Utils.formatDecimal(PLANCHER_P, 3) })
                    : I18n.t('explanation.p_equal', { value: Utils.formatDecimal(valeur, 3) });
            } else {
                mis[cle] = Utils.formatNumber(valeur);
            }
        });
        return mis;
    },

    /** Affiche la règle, ses quatre chiffres et le diagnostic. */
    renderExplication(explication) {
        const zone = document.getElementById('app-explanation-result');
        if (!zone) return;
        if (!explication) {
            zone.innerHTML = '';
            return;
        }

        const termes = explication.regle.length > 0
            ? explication.regle
                .map(terme => `<span class="explication__terme">${
                    Utils.escapeHtml(terme.attribut)} = ${Utils.escapeHtml(terme.valeur)}</span>`)
                .join(`<span class="explication__liaison">${
                    Utils.escapeHtml(I18n.t('explanation.rule.and'))}</span>`)
            : `<span class="explication__terme explication__terme--absent">${
                Utils.escapeHtml(I18n.t('explanation.rule.none'))}</span>`;

        const chiffres = [
            ['reliability', 'explanation.reliability.label',
             Utils.formatPercent(explication.purete * 100)],
            ['power', 'explanation.power.label',
             Utils.formatDecimal(explication.lift, 2)],
            ['exceptions', 'explanation.exceptions.label',
             Utils.formatNumber(explication.exceptions)],
            ['over_granting', 'explanation.over_granting.label',
             Utils.formatNumber(explication.sur_octroi)],
        ].map(([cle, libelle, valeur]) => `
            <div class="stat-card mini" data-definition="definition.explanation.${cle}">
                <div class="stat-card-content">
                    <span class="stat-label">${Utils.escapeHtml(I18n.t(libelle))}</span>
                    <span class="stat-value">${Utils.escapeHtml(valeur)}</span>
                </div>
            </div>`).join('');

        const icones = { favorable: 'fa-circle-check', reserve: 'fa-triangle-exclamation',
                         bloquant: 'fa-circle-xmark' };
        const constats = (explication.diagnostic || []).map(constat => `
            <li class="explication__constat explication__constat--${Utils.escapeHtml(constat.verdict)}">
                <i class="fas ${icones[constat.verdict] || icones.reserve}" aria-hidden="true"></i>
                <span>${Utils.escapeHtml(I18n.t(constat.code, this.parametresDuConstat(constat.params)))}</span>
            </li>`).join('');

        zone.innerHTML = `
            <div class="explication__titre" data-definition="definition.explanation.rule">${
                Utils.escapeHtml(I18n.t('explanation.rule.label'))}</div>
            <div class="explication__regle">${termes}</div>
            <div class="explication__chiffres">${chiffres}</div>
            <div class="explication__titre">${
                Utils.escapeHtml(I18n.t('explanation.diagnostic.label'))}</div>
            <ul class="explication__diagnostic">${constats}</ul>`;

        // Le contenu vient d'être écrit : ses définitions doivent être
        // atteignables autrement qu'à la souris.
        if (typeof Definitions !== 'undefined') Definitions.preparer(zone);
    },

    openAppRoleModal(index) {
        const role = this.appMiningResults[index];
        if (!role) {
            Toast.error(I18n.t('common.error'), I18n.t('validation.role_not_found'));
            return;
        }

        const idxInput = document.getElementById('app-role-idx');
        const nameInput = document.getElementById('app-role-name');
        const descInput = document.getElementById('app-role-desc');
        const userCountEl = document.getElementById('app-role-user-count-display');
        
        const originalRightsInput = document.getElementById('app-role-original-rights');
        const originalUsersInput = document.getElementById('app-role-original-users');
        
        if (idxInput) idxInput.value = index;
        if (nameInput) nameInput.value = this.nomLibrePour(role, 'app');
        this.renderAvertissementDuCandidat('app', role,
                                           nameInput ? nameInput.value : '');
        // Le backend ne construit plus de libelle : il renvoie une cle i18n et
        // ses parametres, la traduction se fait ici.
        if (descInput) {
            descInput.value = role.description_key
                ? I18n.t(role.description_key, Utils.parametresDansLaLangue(role.description_params))
                : (role.description || '');
        }
        if (userCountEl) userCountEl.textContent = Utils.formatNumber(role.user_count || 0);
        
        if (originalRightsInput) originalRightsInput.value = JSON.stringify(role.rights || []);
        if (originalUsersInput) originalUsersInput.value = JSON.stringify(role.users || []);
        
        this.renderRightsList(role.rights || [], 'app');
        this.renderUsersList(role.users || [], 'app');
        
        this.switchTab('app', 'rights');

        // Une explication laissée d'un rôle à l'autre se lirait comme celle du
        // rôle ouvert : la zone est vidée avant tout affichage.
        this.explicationAffichee = null;
        this.propositionDeNom = null;
        this.renderExplication(null);
        this.renderProposition('app');
        this.chargerAttributsDExplication();
        this.chargerEtatDeLAnnotateur('app');

        const warning = document.getElementById('app-role-modification-warning');
        if (warning) warning.hidden = true;
        
        Modal.open('app-role-modal');
    },

    closeAppRoleModal() {
        Modal.close();
    },

    // CORRIGÉ: Validation avec hash correct
    async confirmCreateAppRole() {
        const btn = document.getElementById('confirm-create-app-role');
        if (!btn) return;
        
        const originalText = btn.innerHTML;
        const name = document.getElementById('app-role-name')?.value?.trim();
        const idx = document.getElementById('app-role-idx')?.value;
        
        if (!name) {
            Toast.error(I18n.t('common.error'), I18n.t('validation.role_name_required'));
            return;
        }

        const selectedRights = this.selectionDe('app', 'rights');
        const selectedUsers = this.selectionDe('app', 'users');
        
        if (selectedRights.length === 0) {
            Toast.error(I18n.t('common.error'), I18n.t('validation.select_at_least_one_right'));
            return;
        }

        if (selectedUsers.length === 0) {
            Toast.error(I18n.t('common.error'), I18n.t('validation.select_at_least_one_user'));
            return;
        }

        try {
            btn.innerHTML = `<i class="fas fa-circle-notch fa-spin" aria-hidden="true"></i> ${
                Utils.escapeHtml(I18n.t('mining.creating'))}`;
            btn.disabled = true;

            const role = this.appMiningResults?.[idx];
            if (!role) throw new Error(I18n.t('validation.role_not_found'));

            // Détecter si modifié
            const originalRights = JSON.parse(document.getElementById('app-role-original-rights')?.value || '[]');
            const originalUsers = JSON.parse(document.getElementById('app-role-original-users')?.value || '[]');
            
            
            const rightsModified = originalRights.length !== selectedRights.length || 
                                !originalRights.every(r => selectedRights.includes(r));
            const usersModified = originalUsers.length !== selectedUsers.length ||
                                !originalUsers.every(u => selectedUsers.includes(u));
            
            const isModified = rightsModified || usersModified;
            

            // Modifier un candidat, c'est le refuser et en créer un autre :
            // le candidat d'origine est écarté sous son propre identifiant,
            // celui que le serveur lui a donné.
            if (isModified) {
                try {
                    await KnowledgeBase.rejectRole(role.id);
                } catch (err) {
                    // Le refus du rôle d'origine est un complément : son échec ne
                    // doit pas empêcher la création du rôle modifié.
                    Toast.warning(I18n.t('common.warning'), I18n.t('mining.original_role_reject_failed'));
                }
            }

            const payload = {
                name,
                description: document.getElementById('app-role-desc')?.value || '',
                role_type: 'APPLICATIF',
                rights: selectedRights,
                // La liste des membres n'est pas transmise : un rôle est une
                // règle, pas un instantané. Ses membres sont les identités
                // détenant l'intégralité de ses droits, recalculées à
                // l'affichage — elles ne se périment donc jamais.
                sub_role_ids: [],
                additional_rights: [],
                candidate_id: role.id,
                indicateurs: this.indicateursDeDecision(role),
            };
            

            await API.post('/roles/create', payload);
            // Un mining, une validation ou un refus changent ce qu'il reste
            // à décider : l'indicateur suit l'action, sans rechargement.
            if (typeof Cloche !== 'undefined') Cloche.rafraichir();

            const message = isModified
                ? I18n.t('success.app_role_created_modified', { name })
                : I18n.t('success.app_role_created', { name });

            Toast.success(I18n.t('common.success'), message);
            this.closeAppRoleModal();

            const card = document.querySelector(`.mining-role-card[data-index="${idx}"]`);
            if (card) {
                const cardBtn = card.querySelector('button');
                if (cardBtn) cardBtn.outerHTML =
                    `<div class="mining-verdict mining-verdict--valide">
                        <i class="fas fa-circle-check" aria-hidden="true"></i> ${
                            Utils.escapeHtml(I18n.t('graph.origin.validated'))}</div>`;
            }

        } catch (error) {
            Toast.error(I18n.t('common.error'), error.message);
        } finally {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    },

    async rejectAppRole() {
        const idx = document.getElementById('app-role-idx')?.value;
        const role = this.appMiningResults?.[idx];
        
        if (!role) return;
        
        const motif = await Confirm.demander({
            titre: I18n.t('confirm.reject_role_title'),
            message: I18n.t('confirm.reject_app_role'),
            confirmer: I18n.t('confirm.reject_action'),
            danger: true,
            saisie: {label: I18n.t('confirm.reject_reason')},
        });
        if (!motif) return;
        
        try {
            await KnowledgeBase.rejectRole(
                role.id, motif, this.indicateursDeDecision(role));
            // Un mining, une validation ou un refus changent ce qu'il reste
            // à décider : l'indicateur suit l'action, sans rechargement.
            if (typeof Cloche !== 'undefined') Cloche.rafraichir();

            Toast.success(I18n.t('common.rejected'), I18n.t('success.app_role_rejected'));
            this.closeAppRoleModal();
            
            const card = document.querySelector(`.mining-role-card[data-index="${idx}"]`);
            if (card) {
                const cardBtn = card.querySelector('button');
                if (cardBtn) cardBtn.outerHTML =
                    `<div class="mining-verdict mining-verdict--rejete">
                        <i class="fas fa-circle-xmark" aria-hidden="true"></i> ${
                            Utils.escapeHtml(I18n.t('graph.origin.rejected'))}</div>`;
            }
            
        } catch (error) {
            Toast.error(I18n.t('common.error'), error.message);
        }
    }
};

// Délégation pour les actions produites dans le HTML des résultats.
document.addEventListener('click', (evenement) => {
    // Le bouton de reprise est écrit par le JavaScript après la réponse du
    // modèle : la délégation le couvre sans qu'il faille le rebrancher.
    const reprise = evenement.target.closest('[data-apply-name]');
    if (reprise) {
        MiningPage.appliquerLaProposition(reprise.dataset.applyName);
        return;
    }

    const navigation = evenement.target.closest('[data-goto-page]');
    if (navigation && typeof App !== 'undefined') {
        evenement.preventDefault();
        App.navigateTo(navigation.dataset.gotoPage);
        return;
    }

    const role = evenement.target.closest('[data-mining-role]');
    // Un marqueur de définition explique un chiffre ; il n'ouvre pas la
    // fenêtre de validation. Sans cette réserve, cliquer sur une explication
    // déclencherait une action qu'on n'a pas demandée.
    if (role && !evenement.target.closest('[data-definition]')) {
        evenement.preventDefault();
        const indice = parseInt(role.dataset.miningIndex, 10);
        if (Number.isNaN(indice)) return;
        if (role.dataset.miningRole === 'biz') {
            MiningPage.openBusinessRoleModal(indice);
        } else {
            MiningPage.openAppRoleModal(indice);
        }
    }
});

// Délégation : une case décochée dans une modale de rôle signale une
// modification. Le préfixe passe par un attribut de données.
document.addEventListener('change', (evenement) => {
    const case_ = evenement.target.closest('[data-mining-modif]');
    if (case_) MiningPage.detectModification(case_.dataset.miningModif);
});

window.MiningPage = MiningPage;