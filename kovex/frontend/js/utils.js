/**
 * PyGIA Frontend - Utilities
 * Helper functions used across the application
 */

const Utils = {
    /**
     * Debounce function calls
     */
    debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    },

    /**
     * Throttle function calls
     */
    throttle(func, limit) {
        let inThrottle;
        return function(...args) {
            if (!inThrottle) {
                func.apply(this, args);
                inThrottle = true;
                setTimeout(() => inThrottle = false, limit);
            }
        };
    },

    /**
     * Format number with locale
     */
    formatNumber(num) {
        if (num === null || num === undefined || isNaN(num)) return '-';
        // La langue était écrite en dur (`fr-FR`) : un utilisateur en anglais
        // lisait ses volumes séparés par des espaces insécables. Sans langue
        // connue, `undefined` laisse le navigateur appliquer celle du poste.
        const langue = (typeof I18n !== 'undefined' && I18n.currentLocale) || undefined;
        return new Intl.NumberFormat(langue).format(num);
    },

    /**
     * Une date du serveur (`AAAA-MM-JJ`), écrite dans la langue de l'interface.
     *
     * Le serveur rend des dates ISO : c'est le seul format qui ne dépend
     * d'aucune langue. Affichées telles quelles, elles se lisaient
     * « 2026-02-10 » dans une interface en français. La date est construite
     * dans le fuseau du poste : lue comme un instant UTC, elle reculait d'un
     * jour à l'ouest de Greenwich. Ce qui n'est pas une date ISO passe tel quel.
     */
    formatDate(texte) {
        const correspondance = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(texte ?? ''));
        if (!correspondance) return texte;
        const [, annee, mois, jour] = correspondance.map(Number);
        const langue = (typeof I18n !== 'undefined' && I18n.currentLocale) || undefined;
        return new Intl.DateTimeFormat(langue, { dateStyle: 'short' })
            .format(new Date(annee, mois - 1, jour));
    },

    /**
     * Les paramètres d'un libellé rendu par le serveur, nombres écrits dans la
     * langue de l'interface.
     *
     * Le serveur rend une clé et ses paramètres, jamais un texte : il ne
     * connaît pas la langue. Mais un nombre passé tel quel au catalogue
     * s'écrit avec un point — « 0.1 % des identités » dans une interface en
     * français. Les entiers prennent le séparateur de milliers, les décimaux
     * le séparateur décimal, sans ajouter de décimale que le serveur n'a pas
     * donnée ; une date ISO s'écrit comme une date de la langue. Le reste
     * passe tel quel.
     */
    parametresDansLaLangue(parametres) {
        const rendus = {};
        Object.entries(parametres || {}).forEach(([cle, valeur]) => {
            rendus[cle] = Utils.valeurDansLaLangue(valeur);
        });
        return rendus;
    },

    /**
     * Une valeur à afficher : un nombre dans la langue de l'interface, sans
     * décimale ajoutée ni retirée ; une date ISO comme une date de la langue ;
     * le reste tel quel.
     *
     * `String(valeur)` écrivait « 63.73 % » et « 195668 » sur les écrans du
     * mining en français, à côté de phrases qui disaient « 63,7 % » : deux
     * écritures du même chiffre sur le même écran.
     */
    valeurDansLaLangue(valeur) {
        if (typeof valeur === 'number' && Number.isFinite(valeur)) {
            const langue = (typeof I18n !== 'undefined' && I18n.currentLocale) || undefined;
            return new Intl.NumberFormat(langue, { maximumFractionDigits: 20 }).format(valeur);
        }
        return typeof valeur === 'string' ? Utils.formatDate(valeur) : valeur;
    },

    /**
     * Nombre décimal, dans la langue de l'interface.
     *
     * `toFixed` écrit toujours un point : une couverture s'affichait « 91.4 »
     * dans une interface en français, à côté de volumes séparés par des
     * espaces insécables. Le séparateur décimal fait partie de la langue au
     * même titre que le séparateur de milliers.
     */
    formatDecimal(num, decimals = 1) {
        if (num === null || num === undefined || isNaN(num)) return '-';
        const langue = (typeof I18n !== 'undefined' && I18n.currentLocale) || undefined;
        return new Intl.NumberFormat(langue, {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals,
        }).format(num);
    },

    /**
     * Pourcentage complet, unité comprise.
     *
     * L'unité vient du catalogue : le « % » collé au nombre dans le code
     * était du texte affiché écrit en dur, et toutes les langues ne le
     * placent pas au même endroit ni avec la même espace.
     */
    formatPercent(num, decimals = 1) {
        if (num === null || num === undefined || isNaN(num)) return '-';
        return I18n.t('unit.percent', { value: this.formatDecimal(num, decimals) });
    },

    /**
     * Truncate string with ellipsis
     */
    truncate(str, maxLength = 50) {
        if (!str) return '';
        return str.length > maxLength ? str.substring(0, maxLength) + '...' : str;
    },

    /**
     * Escape HTML to prevent XSS
     */
    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    /**
     * Enregistre une réponse en téléchargement, sous le nom choisi par le
     * serveur.
     *
     * Le nom vient de l'en-tête `Content-Disposition`. Le réinventer côté
     * client, ce que faisait la version précédente, produit deux vérités : le
     * serveur nommait le rapport « kovex_… » et le navigateur l'enregistrait
     * « pygia_… ». `secours` ne sert que si l'en-tête est absent.
     */
    async enregistrerReponse(reponse, secours) {
        const entete = reponse.headers.get('Content-Disposition') || '';
        const correspondance = entete.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
        const nom = correspondance
            ? decodeURIComponent(correspondance[1].trim())
            : secours;

        const blob = await reponse.blob();
        const url = window.URL.createObjectURL(blob);
        const lien = document.createElement('a');
        lien.href = url;
        lien.download = nom;
        document.body.appendChild(lien);
        lien.click();
        document.body.removeChild(lien);
        window.URL.revokeObjectURL(url);
        return nom;
    },

    /**
     * Generate unique ID
     */
    generateId(prefix = 'id') {
        return `${prefix}_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    },

    /**
     * Deep clone object
     */
    deepClone(obj) {
        return JSON.parse(JSON.stringify(obj));
    },

    /**
     * Check if element is in viewport
     */
    isInViewport(element) {
        const rect = element.getBoundingClientRect();
        return (
            rect.top >= 0 &&
            rect.left >= 0 &&
            rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
            rect.right <= (window.innerWidth || document.documentElement.clientWidth)
        );
    },

    /**
     * Parse comma-separated values
     */
    parseCSV(str) {
        if (!str) return [];
        return str.split(',')
            .map(s => s.trim())
            .filter(s => s !== '');
    },

    /**
     * Local storage helpers with error handling
     */
    storage: {
        get(key, defaultValue = null) {
            try {
                const item = localStorage.getItem(key);
                return item ? JSON.parse(item) : defaultValue;
            } catch (e) {
                return defaultValue;
            }
        },
        
        set(key, value) {
            try {
                localStorage.setItem(key, JSON.stringify(value));
                return true;
            } catch (e) {
                return false;
            }
        },
        
        remove(key) {
            try {
                localStorage.removeItem(key);
                return true;
            } catch (e) {
                return false;
            }
        }
    },

    /**
     * Wait for specified milliseconds
     */
    sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    },

    /**
     * Run callback on DOM ready
     */
    ready(callback) {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', callback);
        } else {
            callback();
        }
    },

    /**
     * Query selector shortcuts
     */
    $(selector, context = document) {
        return context.querySelector(selector);
    },

    $$(selector, context = document) {
        return Array.from(context.querySelectorAll(selector));
    },

    /**
     * Add event listener with delegation support
     */
    on(element, event, selector, handler) {
        if (typeof selector === 'function') {
            handler = selector;
            element.addEventListener(event, handler);
        } else {
            element.addEventListener(event, (e) => {
                const target = e.target.closest(selector);
                if (target) {
                    handler.call(target, e, target);
                }
            });
        }
    },

    /**
     * Create element from HTML string
     */
    createElement(html) {
        const template = document.createElement('template');
        template.innerHTML = html.trim();
        return template.content.firstChild;
    },

    /**
     * Animate element entry
     */
    animateIn(elements, delay = 100) {
        const els = elements instanceof NodeList ? Array.from(elements) : [elements];
        els.forEach((el, index) => {
            setTimeout(() => {
                el.classList.add('animated');
            }, index * delay);
        });
    },

    /**
     * Get health status color class
     */
    getHealthClass(score) {
        if (score >= 90) return 'success';
        if (score >= 50) return 'warning';
        return 'danger';
    },

    // getHealthStatus() a ete supprime : il redefinissait, en francais et avec
    // ses propres seuils, un etat que le backend calcule deja a partir des
    // seuils du workspace et renvoie sous forme de cle i18n.
};

// Make Utils available globally
window.Utils = Utils;
