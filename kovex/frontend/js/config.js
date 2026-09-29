/**
 * PyGIA Frontend - Configuration
 * Centralizes all configuration values
 */

/**
 * Adresse de l'API, résolue au chargement.
 *
 * Elle était écrite ici, en dur : déplacer l'API sur un autre hôte ou un
 * autre port obligeait à éditer un fichier livré, et rien ne le signalait —
 * l'interface se contentait de ne plus répondre.
 *
 * Deux sources, dans cet ordre :
 *
 * 1. la balise `<meta name="kovex-api-url">` du gabarit. `serve_frontend.py`
 *    y reporte la variable `KOVEX_API_URL` à chaque envoi de la page ;
 *    derrière un autre serveur, un exploitant la modifie à un seul endroit,
 *    visible, sans toucher au JavaScript ;
 * 2. à défaut, la même origine que la page — le cas d'un relais qui expose
 *    l'API et l'interface sous le même hôte.
 */
function resoudreAdresseApi() {
    const balise = document.querySelector('meta[name="kovex-api-url"]');
    const declaree = balise && (balise.getAttribute('content') || '').trim();
    if (declaree) {
        return declaree.replace(/\/+$/, '');
    }
    return `${window.location.origin}/api/v1`;
}

const Config = {
    // Adresse de l'API. Voir `resoudreAdresseApi` ci-dessus.
    API_URL: resoudreAdresseApi(),
    
    // Pagination
    DEFAULT_PAGE_SIZE: 50,
    
    // Debounce delays (ms)
    SEARCH_DEBOUNCE: 400,
    
    // Animation delays
    ANIMATION_DELAY: 100,
    
    // Toast duration (ms)
    TOAST_DURATION: 4000,
    
    // Health thresholds
    HEALTH_THRESHOLD_ALERT: 10,
    HEALTH_THRESHOLD_CRITICAL: 50,
    
    // Mining defaults
    MINING_MIN_USERS: 5,
    MINING_MODE_DEFAULT: 'EXACT',
	MINING_MAX_DEPTH: 6,

    // Ensembles de droits contrôlés par appel à `/separation/controler`.
    // C'est la borne du serveur (`ENSEMBLES_MAX`), qu'un test garde égale :
    // au-delà, la demande est refusée en bloc et aucune carte n'est marquée.
    SEPARATION_ENSEMBLES_PAR_APPEL: 200,
    
    // Local storage keys
    STORAGE_THEME: 'pygia_theme',
    STORAGE_SIDEBAR: 'pygia_sidebar_collapsed',
    
    /**
     * Pages de l'application.
     *
     * `title` portait le libellé en français. Il alimentait le fil d'Ariane,
     * qui restait donc en français quelle que soit la langue choisie — et il
     * n'existait pas de titre pour les pages ajoutées depuis. C'est une clé de
     * traduction, résolue à l'affichage.
     */
    ROUTES: {
        dashboard: { title: 'nav.link.dashboard', icon: 'fa-th-large' },
        users: { title: 'nav.link.identities', icon: 'fa-users' },
        applications: { title: 'nav.link.applications', icon: 'fa-cubes' },
        rights: { title: 'nav.link.rights', icon: 'fa-key' },
        'birth-rights': { title: 'nav.link.birth_rights', icon: 'fa-seedling' },
        separation: { title: 'nav.separation', icon: 'fa-scale-balanced' },
        'separation-conflits': { title: 'nav.separation_conflits', icon: 'fa-triangle-exclamation' },
        mouvement: { title: 'nav.mouvement', icon: 'fa-right-left' },
        usage: { title: 'nav.usage', icon: 'fa-hourglass-half' },
        apprentissage: { title: 'nav.apprentissage', icon: 'fa-graduation-cap' },
        mining: { title: 'nav.link.mining_app', icon: 'fa-gem' },
        'mining-business': { title: 'nav.link.mining_business', icon: 'fa-sitemap' },
        'roles-catalog': { title: 'nav.link.roles_catalog', icon: 'fa-layer-group' },
        composer: { title: 'nav.link.role_composer', icon: 'fa-magic' },
        'export-modele': { title: 'nav.link.export_model', icon: 'fa-file-export' },
        'data-quality': { title: 'nav.link.data_quality', icon: 'fa-heartbeat' },
        graph: { title: 'nav.link.graph', icon: 'fa-project-diagram' },
        audit: { title: 'nav.link.audit', icon: 'fa-clipboard-list' },
        workspaces: { title: 'nav.link.workspaces', icon: 'fa-folder-open' },
        documentation: { title: 'nav.link.documentation', icon: 'fa-book' },
        settings: { title: 'nav.link.settings', icon: 'fa-cog' }
    },

    /**
     * Où va-t-on pour décider des candidats d'un type de rôle.
     *
     * L'indicateur de travail en attente compte par type ; il doit pouvoir
     * mener à l'écran qui permet d'agir. Ce n'est pas un réglage métier — le
     * produit ne connaît que ces deux natures de rôle — mais une table, ici,
     * plutôt qu'un `if` au milieu du rendu.
     */
    PAGES_PAR_TYPE_DE_ROLE: {
        APPLICATIF: 'mining',
        METIER: 'mining-business'
    }
};

Object.freeze(Config.ROUTES);
Object.freeze(Config.PAGES_PAR_TYPE_DE_ROLE);

// Exposée pour que la résolution soit vérifiable, et pour qu'un
// diagnostic puisse la relancer après changement de la balise.
Config.resoudreAdresseApi = resoudreAdresseApi;
