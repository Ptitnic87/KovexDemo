/**
 * PyGIA Frontend Internationalization Module
 * Gestion des traductions côté client
 */

const I18n = {
    currentLocale: 'fr',
    translations: {},
    // Langue de démarrage, avant tout échange avec le serveur : une page
    // statique doit bien en choisir une. Elle reprend la langue de référence
    // du serveur (`langue_de_reference`). La liste des langues réellement
    // installées, elle, vient de `/i18n/locales` et n'est écrite nulle part.
    fallbackLocale: 'fr',
    // Langues annoncées par le serveur, remplies au démarrage.
    languesDisponibles: [],
    
    /**
     * Initialise le module i18n
     */
    async init() {
        // Langue retenue au dernier passage, sinon celle de repli du produit.
        this.currentLocale = localStorage.getItem('pygia_locale') || this.fallbackLocale;

        await this.loadTranslations(this.currentLocale);

        // La liste des langues vient du serveur : c'est lui qui sait quels
        // catalogues sont installés. Elle était écrite en dur dans le
        // gabarit, si bien qu'ajouter un catalogue ne suffisait pas à le
        // rendre choisissable.
        await this.chargerLanguesDisponibles();

        this.applyTranslations();
        this.bindEvents();
    },

    /**
     * Langues installées sur le serveur, avec leur nom dans leur propre
     * langue. Une panne de cette route ne doit pas empêcher l'interface de
     * fonctionner dans la langue déjà chargée.
     */
    async chargerLanguesDisponibles() {
        this.languesDisponibles = await this.getAvailableLocales();
        this.peuplerSelecteur();
    },

    /**
     * Remplit le sélecteur de langue à partir de ce que le serveur annonce.
     */
    peuplerSelecteur() {
        const selecteur = document.getElementById('locale-selector');
        if (!selecteur || !this.languesDisponibles.length) return;

        selecteur.innerHTML = this.languesDisponibles.map(langue =>
            `<option value="${Utils.escapeHtml(langue.code)}">${
                Utils.escapeHtml(langue.native_name || langue.code)}</option>`).join('');
        selecteur.value = this.currentLocale;
    },
    
    /**
     * Charge les traductions depuis l'API
     * @param {string} locale - Code de langue (ex: 'fr', 'en')
     */
    async loadTranslations(locale) {
        try {
            
            const data = await API.get(`/i18n/translations/${locale}`);
            
            // 🔍 DEBUG : Voir ce qui est reçu
            
            this.translations = data;
            this.currentLocale = locale;

            // La langue du document suit la langue du produit.
            //
            // `<html lang="fr">` était écrit une fois dans le gabarit et ne
            // bougeait plus : basculer l'interface en anglais ou en allemand
            // laissait la page annoncer du français. Une synthèse vocale
            // prononce alors le contenu avec la phonétique de la mauvaise
            // langue — le texte reste juste à l'écran, et devient
            // incompréhensible à l'oreille. Critère RGAA 8.3 et 8.4.
            document.documentElement.setAttribute('lang', locale);

            // Sauvegarder dans localStorage
            localStorage.setItem('pygia_locale', locale);
            
            
        } catch (error) {
            // Essayer la langue de repli.
            if (locale !== this.fallbackLocale) {
                await this.loadTranslations(this.fallbackLocale);
                return;
            }

            // Ni la langue demandée ni celle de repli. L'échec était avalé
            // ici : l'interface affichait alors ses clés brutes, sans que
            // rien n'explique pourquoi. Le signaler laisse l'appelant
            // prévenir l'utilisateur ; l'interface reste utilisable.
            throw error;
        }
    },
    
    /**
     * Traduit une clé
     * @param {string} key - Clé de traduction (ex: 'common.save')
     * @param {Object} params - Paramètres de substitution (ex: {count: 5})
     * @returns {string} Traduction ou clé si introuvable
     */
    t(key, params = {}) {
        // NOUVEAU : Essayer d'abord l'accès direct (clés plates)
        if (this.translations[key] !== undefined) {
            let result = this.translations[key];
            
            // Remplacer les placeholders {variable}
            for (const [param, val] of Object.entries(params)) {
                result = result.replace(`{${param}}`, val);
            }
            
            return result;
        }
        
        // Sinon, naviguer dans l'arbre (clés hiérarchiques)
        const keys = key.split('.');
        let value = this.translations;
        
        for (const k of keys) {
            if (value && typeof value === 'object') {
                value = value[k];
            } else {
                return key; // Fallback sur la clé
            }
        }
        
        if (!value) {
            return key;
        }
        
        // Remplacer les placeholders {variable}
        let result = value;
        for (const [param, val] of Object.entries(params)) {
            result = result.replace(`{${param}}`, val);
        }
        
        return result;
    },
    
    /**
     * Applique les traductions sur toute la page
     */
    applyTranslations() {
        
        // Traduire tous les éléments avec data-i18n
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.dataset.i18n;
            const translation = this.t(key);
            
            // 🔧 FIX: Support HTML si data-i18n-html="true"
            if (el.dataset.i18nHtml === 'true') {
                el.innerHTML = translation;
                return;
            }
            
            // Vérifier si l'élément a des enfants complexes
            if (el.children.length === 0 || el.dataset.i18nTextOnly === 'true') {
                el.textContent = translation;
            } else {
                // Élément avec une icône : seul le libellé change. Le premier
                // nœud texte est souvent l'indentation qui précède l'icône ;
                // y écrire la traduction laissait le libellé d'origine à la
                // suite, et le titre s'affichait deux fois (« Créer un Nouveau
                // Workspace ⊕ Nouveau Workspace »). On vise donc le premier
                // nœud qui porte du texte, et on vide les suivants.
                const pleins = Array.from(el.childNodes).filter(node =>
                    node.nodeType === Node.TEXT_NODE && node.textContent.trim() !== '');
                if (pleins.length > 0) {
                    // Les blancs autour du libellé séparent l'icône et ce
                    // qui suit : ils restent.
                    const brut = pleins[0].textContent;
                    pleins[0].textContent = brut.match(/^\s*/)[0] + translation
                        + brut.match(/\s*$/)[0];
                    pleins.slice(1).forEach(node => { node.textContent = ''; });
                }
            }
        });
        
        // ✨ NOUVEAU : Support de data-i18n-key (ancien format)
        document.querySelectorAll('[data-i18n-key]').forEach(el => {
            const key = el.dataset.i18nKey;
            const translation = this.t(key);
            
            // 🔧 FIX: Support HTML si data-i18n-html="true"
            if (el.dataset.i18nHtml === 'true') {
                el.innerHTML = translation;
                return;
            }
            
            // Vérifier si l'élément a des enfants complexes
            if (el.children.length === 0 || el.dataset.i18nTextOnly === 'true') {
                el.textContent = translation;
            } else {
                // Élément avec une icône : seul le libellé change. Le premier
                // nœud texte est souvent l'indentation qui précède l'icône ;
                // y écrire la traduction laissait le libellé d'origine à la
                // suite, et le titre s'affichait deux fois (« Créer un Nouveau
                // Workspace ⊕ Nouveau Workspace »). On vise donc le premier
                // nœud qui porte du texte, et on vide les suivants.
                const pleins = Array.from(el.childNodes).filter(node =>
                    node.nodeType === Node.TEXT_NODE && node.textContent.trim() !== '');
                if (pleins.length > 0) {
                    // Les blancs autour du libellé séparent l'icône et ce
                    // qui suit : ils restent.
                    const brut = pleins[0].textContent;
                    pleins[0].textContent = brut.match(/^\s*/)[0] + translation
                        + brut.match(/\s*$/)[0];
                    pleins.slice(1).forEach(node => { node.textContent = ''; });
                }
            }
        });
        
        // Traduire les placeholders
        document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
            const key = el.dataset.i18nPlaceholder;
            el.placeholder = this.t(key);
        });
        
        // Traduire les attributs title (tooltips)
        document.querySelectorAll('[data-i18n-title]').forEach(el => {
            const key = el.dataset.i18nTitle;
            el.title = this.t(key);
        });
        
        // Traduire les aria-label (accessibilité)
        document.querySelectorAll('[data-i18n-aria-label]').forEach(el => {
            const key = el.dataset.i18nAriaLabel;
            el.setAttribute('aria-label', this.t(key));
        });
        
        // Traduire les valeurs (boutons, options, etc.)
        document.querySelectorAll('[data-i18n-value]').forEach(el => {
            const key = el.dataset.i18nValue;
            el.value = this.t(key);
        });
        
    },
    
    /**
     * Change la langue active
     * @param {string} locale - Code de langue
     */
    async switchLocale(locale) {
        if (locale === this.currentLocale) {
            return;
        }
        
        
        try {
            // Charger les nouvelles traductions
            await this.loadTranslations(locale);
            
            // Ré-appliquer les traductions
            this.applyTranslations();
            
            // Notifier les autres modules
            this.notifyLocaleChange(locale);
            
            // Recharger les données de la page actuelle si nécessaire
            if (App.currentPage) {
                await App.loadPageData(App.currentPage);
            }
            
            Toast.success(
                this.t('common.success'),
                this.t('settings.language_changed', {language: this.getLanguageName(locale)})
            );
            
        } catch (error) {
            Toast.error(
                this.t('common.error'),
                this.t('i18n.catalogue_unavailable')
            );
        }
    },
    
    /**
     * Lie les événements i18n
     */
    bindEvents() {
        
        // Sélecteur de langue
        const selector = document.getElementById('locale-selector');
        if (selector) {
            selector.value = this.currentLocale;
            selector.addEventListener('change', (e) => {
                this.switchLocale(e.target.value);
            });
        } else {
            // Retry après un délai (au cas où le DOM n'est pas prêt)
            setTimeout(() => {
                const retrySelector = document.getElementById('locale-selector');
                if (retrySelector) {
                    retrySelector.value = this.currentLocale;
                    retrySelector.addEventListener('change', (e) => {
                        this.switchLocale(e.target.value);
                    });
                }
            }, 500);
        }
    },
    
    /**
     * Notifie les autres modules du changement de langue
     * @param {string} locale - Nouvelle langue
     */
    notifyLocaleChange(locale) {
        // Dispatcher un événement custom
        window.dispatchEvent(new CustomEvent('localeChanged', {
            detail: {locale}
        }));
    },
    
    /**
     * Charge les langues disponibles depuis l'API
     * @returns {Promise<Array>} Liste des langues
     */
    async getAvailableLocales() {
        try {
            const data = await API.get('/i18n/locales');
            return data.locales || [];
        } catch (error) {
            // Le sélecteur gardera les langues déjà connues : une panne de
            // cette route ne doit pas priver l'utilisateur de son choix.
            return [];
        }
    },
    
    /**
     * Retourne le nom d'une langue
     * @param {string} locale - Code de langue
     * @returns {string} Nom de la langue
     */
    getLanguageName(locale) {
        const connue = this.languesDisponibles.find(langue => langue.code === locale);
        return (connue && connue.native_name) || locale.toUpperCase();
    },
    
    /**
     * Formatte une date selon la locale
     * @param {Date|string} date - Date à formatter
     * @param {Object} options - Options de formatage
     * @returns {string} Date formatée
     */
    formatDate(date, options = {}) {
        const dateObj = date instanceof Date ? date : new Date(date);
        return new Intl.DateTimeFormat(this.currentLocale, options).format(dateObj);
    },
    
    /**
     * Formatte une date relative (ex: "il y a 2 jours")
     * @param {Date|string} date - Date
     * @returns {string} Date relative
     */
    formatRelativeDate(date) {
        const dateObj = date instanceof Date ? date : new Date(date);
        const now = new Date();
        const diff = now - dateObj;
        
        const seconds = Math.floor(diff / 1000);
        const minutes = Math.floor(seconds / 60);
        const hours = Math.floor(minutes / 60);
        const days = Math.floor(hours / 24);
        
        // Le préfixe des clés était `date.` ; les catalogues portent `time.`.
        // Aucune de ces quatre traductions n'existait : la fonction rendait
        // « date.hours_ago » à l'utilisateur.
        if (days > 7) {
            return this.formatDate(dateObj, {dateStyle: 'short'});
        } else if (days > 0) {
            return this.t('time.days_ago', {count: days});
        } else if (hours > 0) {
            return this.t('time.hours_ago', {count: hours});
        } else if (minutes > 0) {
            return this.t('time.minutes_ago', {count: minutes});
        } else {
            return this.t('time.just_now');
        }
    }
};

// Export global
window.I18n = I18n;

// Helper global pour templates
window.t = (key, params) => I18n.t(key, params);

