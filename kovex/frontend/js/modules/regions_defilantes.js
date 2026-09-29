/**
 * Zones défilantes atteignables au clavier.
 *
 * Un conteneur qui défile est un contenu que l'on ne voit pas entièrement.
 * À la souris on le fait glisser ; au clavier, s'il n'est pas focusable et
 * qu'il ne contient rien qui le soit, la partie cachée est **inatteignable**.
 * C'est le critère WCAG 2.1.1, et le produit l'échouait sur ses tableaux de
 * données : vingt colonnes dans une enveloppe qui défile, remplie de texte
 * seul, donc sans un seul arrêt de tabulation à l'intérieur.
 *
 * Deux précautions gouvernent ce module, et ce sont elles qui font la
 * différence entre une correction et une gêne :
 *
 * 1. **Seulement quand ça déborde vraiment.** Une enveloppe qui tient dans sa
 *    largeur n'a rien de caché ; lui donner un arrêt de tabulation ajoute un
 *    obstacle sans rien rendre accessible. L'attribut est donc posé et retiré
 *    au gré de la mise en page, pas écrit dans le gabarit.
 *
 * 2. **Seulement s'il n'y a rien de focusable dedans.** Un panneau rempli de
 *    boutons se parcourt déjà : la tabulation y amène le focus, et le
 *    navigateur fait défiler pour le montrer. Le rendre focusable lui-même
 *    n'ajoute qu'un arrêt de plus avant les boutons.
 *
 * Le nom accessible, lui, n'est pas ici : il vient de `data-i18n-aria-label`,
 * que `I18n.applyTranslations` pose déjà et met à jour à chaque changement de
 * langue. Ce module ne connaît donc pas les traductions, et un libellé ne peut
 * pas se figer dans la langue de son premier affichage.
 */
const RegionsDefilantes = {

    /** Ce qui, dans une zone, se prend déjà le focus. */
    SELECTEUR_FOCUSABLE: 'a[href], button, input, select, textarea, [tabindex]',

    /** Marque posée sur une zone déjà prise en charge. */
    ATTRIBUT_SUIVIE: 'data-zone-defilante-suivie',

    /** Délai de regroupement des modifications du document, en millisecondes. */
    DELAI_REGROUPEMENT: 120,

    _observateurTaille: null,
    _observateurArbre: null,
    _minuteur: null,
    _zones: null,

    /**
     * Met le module en service sur une racine du document.
     * @param {Element} racine
     */
    init(racine) {
        this._zones = new Set();
        this._observateurTaille = new ResizeObserver(() => this.reevaluer());
        this._observateurArbre = new MutationObserver(() => this._programmer(racine));
        this._observateurArbre.observe(racine, {childList: true, subtree: true});
        this.recenser(racine);
        this.reevaluer();
    },

    /** Arrête les observateurs. Utile aux tests et à un rechargement de vue. */
    arreter() {
        if (this._observateurTaille) {
            this._observateurTaille.disconnect();
        }
        if (this._observateurArbre) {
            this._observateurArbre.disconnect();
        }
        clearTimeout(this._minuteur);
        this._zones = new Set();
    },

    /**
     * Regroupe les modifications du document : remplir un tableau ligne à
     * ligne en produit des dizaines, et recenser à chacune coûterait bien plus
     * cher que le recensement lui-même.
     */
    _programmer(racine) {
        clearTimeout(this._minuteur);
        this._minuteur = setTimeout(() => {
            this.recenser(racine);
            this.reevaluer();
        }, this.DELAI_REGROUPEMENT);
    },

    /**
     * Repère les zones défilantes apparues depuis le dernier passage.
     * @param {Element|Document} racine
     */
    recenser(racine) {
        const candidates = racine.querySelectorAll(`*:not([${this.ATTRIBUT_SUIVIE}])`);
        candidates.forEach(element => {
            if (!this.defilante(element)) {
                return;
            }
            element.setAttribute(this.ATTRIBUT_SUIVIE, '');
            this._zones.add(element);
            this.accorder(element);
        });
    },

    /**
     * Rejoue la décision sur toutes les zones connues.
     *
     * Une vue remplacée emporte ses zones : sans cet oubli, la liste et
     * l'observateur de taille retiendraient indéfiniment des éléments qui ne
     * sont plus dans le document — une session de travail longue les
     * accumulerait par centaines.
     */
    reevaluer() {
        this._zones.forEach(element => {
            if (!element.isConnected) {
                this._zones.delete(element);
                this._observateurTaille.unobserve(element);
                return;
            }
            this.surveiller(element);
            this.accorder(element);
        });
    },

    /**
     * Surveille la taille d'une zone **et celle de son contenu**.
     *
     * La zone seule ne suffit pas : un tableau qui s'élargit ne change pas la
     * boîte de son enveloppe. Le cas n'est pas théorique — une police de
     * caractères qui finit de charger modifie la largeur de tout le tableau,
     * après le rendu, sans toucher au document. Observer un élément déjà
     * observé ne fait rien : l'appel est donc sans coût à la répétition.
     * @param {Element} element
     */
    surveiller(element) {
        this._observateurTaille.observe(element);
        Array.from(element.children).forEach(
            enfant => this._observateurTaille.observe(enfant));
    },

    /**
     * Une zone défile si son style calculé l'y autorise.
     * @param {Element} element
     * @returns {boolean}
     */
    defilante(element) {
        const style = getComputedStyle(element);
        return ['auto', 'scroll'].includes(style.overflowX)
            || ['auto', 'scroll'].includes(style.overflowY);
    },

    /**
     * Une zone cache du contenu si son contenu dépasse sa boîte.
     *
     * Le pixel de tolérance n'est pas un confort : une bordure ou un arrondi
     * suffit à créer un écart d'un pixel entre `scrollWidth` et `clientWidth`
     * sans que rien ne soit caché.
     * @param {Element} element
     * @returns {boolean}
     */
    deborde(element) {
        return element.scrollWidth > element.clientWidth + 1
            || element.scrollHeight > element.clientHeight + 1;
    },

    /**
     * Un élément focusable **épinglé** ne fait pas défiler la zone.
     *
     * La règle « il y a des boutons dedans, donc la tabulation y mène » vaut
     * tant que ces boutons défilent avec le contenu. Un en-tête de tableau
     * collant est l'exception : ses poignées de colonne restent en vue quoi
     * qu'il arrive, la tabulation ne fait donc jamais descendre la zone, et
     * les lignes du bas redeviennent inatteignables au clavier. Elles ne
     * comptent pas.
     * @param {Element} element
     * @param {Element} zone
     * @returns {boolean}
     */
    epingle(element, zone) {
        for (let noeud = element; noeud && noeud !== zone; noeud = noeud.parentElement) {
            if (getComputedStyle(noeud).position === 'sticky') {
                return true;
            }
        }
        return false;
    },

    /**
     * La zone contient-elle de quoi s'y déplacer au clavier ?
     * @param {Element} element
     * @returns {boolean}
     */
    parcourable(element) {
        return Array.from(element.querySelectorAll(this.SELECTEUR_FOCUSABLE))
            .some(focusable => !this.epingle(focusable, element));
    },

    /**
     * Pose ou retire l'arrêt de tabulation d'une zone, selon son état.
     * @param {Element} element
     */
    accorder(element) {
        const atteignable = this.deborde(element) && !this.parcourable(element);
        if (atteignable) {
            element.setAttribute('tabindex', '0');
        } else {
            element.removeAttribute('tabindex');
        }
    },
};
