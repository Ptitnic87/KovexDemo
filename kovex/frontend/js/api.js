/**
 * PyGIA Frontend - API Client
 * Communication avec le backend
 */

/**
 * Traduit une cle i18n. Renvoie la cle si le module n'est pas encore charge :
 * aucun libelle n'est ecrit en dur dans ce fichier.
 */
function tr(key, params = {}) {
    if (typeof I18n !== 'undefined' && typeof I18n.t === 'function') {
        return I18n.t(key, params);
    }
    return key;
}

/**
 * Extrait un message lisible d'une reponse en erreur.
 * Le backend renvoie { detail: { code, params } } : le code est une cle i18n,
 * traduite ici. Les anciennes reponses { detail: "texte" } restent acceptees.
 */
async function parseErrorBody(response) {
    let payload = null;
    try {
        payload = await response.json();
    } catch {
        return { message: tr('error.http_status', { status: response.status }), details: null };
    }

    const detail = payload && payload.detail;

    if (detail && typeof detail === 'object' && detail.code) {
        return {
            message: tr(detail.code, detail.params || {}),
            details: { code: detail.code, params: detail.params || {} }
        };
    }

    if (typeof detail === 'string' && detail.length > 0) {
        return { message: detail, details: null };
    }

    return { message: tr('error.http_status', { status: response.status }), details: null };
}

class APIError extends Error {
    constructor(message, status, details = null) {
        super(message);
        this.name = 'APIError';
        this.status = status;
        this.details = details;
    }
}

class APIClient {
    constructor(baseUrl) {
        this.baseUrl = baseUrl;
    }

    /**
     * Envoie la requete authentifiee et rend la reponse, sans l'interpreter.
     *
     * Le corps n'est pas toujours du JSON : une image servie par l'API passe
     * par le meme chemin d'authentification et le meme traitement d'erreur,
     * mais se lit en binaire.
     */
    async _reponse(endpoint, options = {}) {
        const config = {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        };

        // Ajouter le token d'auth si disponible
        if (typeof Auth !== 'undefined' && Auth.isAuthenticated()) {
            const headers = Auth.getAuthHeaders();
            config.headers = { ...config.headers, ...headers };
        }

        const response = await fetch(`${this.baseUrl}${endpoint}`, config);

        if (response.status === 401) {
            if (typeof Auth !== 'undefined') {
                Auth.logout();
            }
            throw new APIError(tr('error.session_expired'), 401, { code: 'error.session_expired' });
        }

        if (!response.ok) {
            const { message, details } = await parseErrorBody(response);
            throw new APIError(message, response.status, details);
        }

        return response;
    }

    async request(endpoint, options = {}) {
        try {
            const response = await this._reponse(endpoint, options);
            return await response.json();
        } catch (error) {
            if (error instanceof APIError) throw error;
            throw new APIError(tr('error.network', { message: error.message }), 0, { code: 'error.network' });
        }
    }

    /**
     * Lit une ressource binaire servie par l'API.
     *
     * Une balise `<img src>` ne sait pas porter d'en-tete : sur une API qui
     * exige un jeton, elle recoit un 401 et le navigateur affiche le texte de
     * remplacement. Le logo d'un theme etait dans ce cas. Il est donc lu ici,
     * avec le jeton, puis pose dans le document sous forme d'URL d'objet.
     */
    async blob(endpoint) {
        try {
            const response = await this._reponse(endpoint, { method: 'GET' });
            return await response.blob();
        } catch (error) {
            if (error instanceof APIError) throw error;
            throw new APIError(tr('error.network', { message: error.message }), 0, { code: 'error.network' });
        }
    }

    get(endpoint, params = {}) {
        const queryString = new URLSearchParams(params).toString();
        const url = queryString ? `${endpoint}?${queryString}` : endpoint;
        return this.request(url, { method: 'GET' });
    }

    post(endpoint, data = {}) {
        return this.request(endpoint, {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }

    put(endpoint, data = {}) {
        return this.request(endpoint, {
            method: 'PUT',
            body: JSON.stringify(data)
        });
    }

    delete(endpoint) {
        return this.request(endpoint, { method: 'DELETE' });
    }
}

/**
 * API Service
 */
const API = {
    client: new APIClient(Config.API_URL),

    // === Dashboard ===
    async getDashboardStats() {
        return this.client.get('/stats/dashboard');
    },

    /**
     * Distribution du nombre de droits par identite, calculee sur les donnees
     * du workspace actif.
     */
    async getRightsDistribution() {
        return this.client.get('/stats/rights-distribution');
    },

    // === Settings ===
    async getSettings() {
        return this.client.get('/settings');
    },

    async saveSettings(config) {
        return this.client.post('/settings', config);
    },

    // Détail, règle par règle, des identités sans droit que le modèle
    // conservé toucherait. Le serveur le calcule sur les candidats du dernier
    // mining : ce doit être le modèle affiché, pas un nouveau calcul.
    async getPopulationDetail() {
        return this.client.get('/mining-metiers/population-detail');
    },

    // Écarte plusieurs identités en une écriture. Une par une, chacune
    // relirait et réécrirait la Knowledge Base sous verrou — le détail par
    // groupe en désigne parfois quelques centaines.
    async excludeUsers(userIds, reason) {
        return this.client.post('/kb/exclude-users',
                                { user_ids: userIds, reason });
    },

    async getExcludedUsers() {
        return this.client.get('/kb/excluded-users');
    },

    async restoreUser(userId) {
        return this.client.delete(`/kb/excluded-users/${encodeURIComponent(userId)}`);
    },

    // === Périmètre d'analyse ===
    // Les règles vivent dans la Knowledge Base et non dans la configuration :
    // ce sont des décisions de gouvernance, au même titre que les droits
    // socles et les exclusions nominatives, et elles s'appliquent au même
    // endroit — en amont de tous les moteurs.
    async getPerimeterRules() {
        return this.client.get('/kb/perimeter-rules');
    },

    async setPerimeterRules(rules) {
        return this.client.put('/kb/perimeter-rules', { rules });
    },

    // === Data Explorer ===
    async getUsers(params) {
        return this.client.get('/users/list', params);
    },

    async getApplications(params) {
        return this.client.get('/applications/list', params);
    },

    async getRights(params) {
        return this.client.get('/rights/list', params);
    },

    // === Data Quality ===
    async getDataStatus() {
        return this.client.get('/data-status');
    },

    /**
     * Valeurs que les transformations ont changées dans un référentiel.
     *
     * Paginé et filtré côté serveur : sur un fichier d'habilitations, la liste
     * des valeurs changées se compte en centaines de milliers, et la ramener
     * entière pour n'en montrer vingt figerait la page.
     */
    async getTransformationDifferences(referentiel, { page = 1, size = 50, search = '' } = {}) {
        const parametres = new URLSearchParams({ page, size });
        if (search) parametres.set('search', search);
        return this.client.get(
            `/reports/transformations/${encodeURIComponent(referentiel)}?${parametres}`);
    },

    async launchRecertification() {
        return this.client.post('/data-recertify');
    },

    // === Roles ===
    async getRoles() {
        return this.client.get('/roles/');
    },

    async createRole(roleData) {
        // '/roles' (sans barre finale) visait un fichier global, hors
        // workspace, tandis que la lecture ci-dessus vise la Knowledge Base :
        // la même methode d'API tapait deux magasins differents.
        return this.client.post('/roles/create', roleData);
    },

    // === Mining Applicatif ===
    async launchMining(params) {
        return this.client.post('/mining/launch', params);
    },

    /**
     * Evalue une serie de seuils de similarite et retourne, pour chacun,
     * la couverture obtenue et le sur-octroi induit.
     */
    async scanMiningThresholds(params) {
        return this.client.post('/mining/threshold-scan', params);
    },

    /**
     * Evalue une serie de seuils de consolidation. Le mining n'est joue qu'une
     * fois cote serveur : seule la consolidation est rejouee par seuil.
     */
    async scanConsolidationThresholds(params) {
        return this.client.post('/mining/consolidation-scan', params);
    },

    // === Mining Métier ===
    async getIdentityAttributes() {
        return this.client.get('/mining-metiers/attributes/identity/business');
    },

    /** Points d'arbitrage : ce que chaque compromis coûterait. */
    async getTradeoffPoints(params) {
        return this.client.post('/mining-metiers/arbitrage', params);
    },

    /** Effet d'un paramètre du mining sur les données chargées. */
    async getParameterImpact(params) {
        return this.client.post('/mining-metiers/impact', params);
    },

    async launchBusinessMining(params) {
        return this.client.post('/mining-metiers/find-roles-business', params);
    },

    /**
     * Explique des rôles par les attributs de leurs porteurs.
     *
     * L'appel est sans état : les rôles à expliquer sont envoyés par le
     * client, qui vient de les obtenir du mining. Le serveur ne garde aucun
     * résultat de mining d'une requête à l'autre.
     */
    async explainRoles(params) {
        return this.client.post('/mining/explain', params);
    },

    /**
     * La matrice usage × matière du workspace actif.
     *
     * Un seul appel rend tout ce qu'un administrateur doit savoir : les
     * usages, ce qui est ouvert pour chacun, et où part la demande.
     */
    async getAssistance() {
        return this.client.get('/assistance/');
    },

    /**
     * Propose les fragments qui signalent un droit sensible.
     *
     * Les mots viennent du modèle ; les chiffres sont comptés par le serveur
     * sur le référentiel entier. Rien n'est enregistré.
     */
    async proposerLesDroitsSensibles(locale) {
        return this.client.post('/assistance/droits-sensibles', { locale });
    },

    /**
     * Propose les conventions de nommage des comptes à privilèges.
     *
     * **Rien ne part.** La question posée au modèle ne parle pas de ce
     * référentiel : elle porte sur les conventions usuelles du métier. Les
     * fragments qui reviennent sont ensuite éprouvés côté serveur sur les
     * identités chargées, et ceux qui ne marquent personne sont écartés.
     */
    async proposerLesComptesAPrivileges(locale) {
        return this.client.post('/assistance/comptes-a-privileges', { locale });
    },

    /**
     * Ce que la déclaration de comptes à privilèges marque aujourd'hui.
     *
     * Recalculé à chaque appel : un identifiant renommé ou une colonne
     * disparue d'un export change le résultat, et un chiffre conservé dirait
     * le contraire de ce que le produit applique.
     */
    async getDenombrementDesPrivileges() {
        return this.client.get('/privileges');
    },

    /**
     * Les règles de séparation que des ensembles de droits enfreindraient.
     *
     * Les droits viennent de l'écran et non du serveur : l'utilisateur peut en
     * avoir décoché, et c'est ce qu'il a sous les yeux qu'il faut contrôler.
     *
     * Plusieurs ensembles en un appel : la liste des résultats marque toutes
     * ses cartes d'un coup, là où un appel par candidat ferait autant d'allers
     * et retours que de lignes. Un ensemble qui porte ses **membres** reçoit en
     * plus le coût de chaque retrait possible.
     */
    async controlerLaSeparation(ensembles) {
        return this.client.post('/separation/controler', { ensembles });
    },

    /**
     * Les rôles validés qui enfreignent une règle de séparation.
     *
     * Le catalogue est la donnée du serveur : le lui renvoyer pour qu'il le
     * contrôle coûterait un aller-retour proportionnel au référentiel, pour un
     * calcul qu'il fait seul et sans lire une habilitation.
     */
    async lesRolesEnConflit() {
        return this.client.get('/separation/roles');
    },

    /** Classe les colonnes d'identités. Seuls leurs noms quittent le serveur. */
    async proposerLesAttributs(locale) {
        return this.client.post('/assistance/attributs-pertinents', { locale });
    },

    /** Réécrit la matrice. Le document envoyé fait foi dans son entier. */
    async saveAssistance(payload) {
        return this.client.put('/assistance/', payload);
    },

    /**
     * Les points de terminaison configurés, et qui les a décidés.
     *
     * La réponse ne porte aucune clé : seulement le fait qu'un préréglage en
     * ait une. Une interface qui recevrait un secret le donnerait à tout ce
     * qui sait ouvrir les outils de développement.
     */
    async getPointsDeTerminaison() {
        return this.client.get('/points-de-terminaison/');
    },

    /** Réécrit les préréglages, le réglage commun et les surcharges par usage. */
    async savePointsDeTerminaison(payload) {
        return this.client.put('/points-de-terminaison/', payload);
    },

    /** Pose la clé d'un préréglage. Elle ne revient jamais ensuite. */
    async poserLaCle(prereglage, cle) {
        return this.client.put(
            `/points-de-terminaison/prereglages/${encodeURIComponent(prereglage)}/cle`,
            { cle });
    },

    /** Retire la clé d'un préréglage. */
    async retirerLaCle(prereglage) {
        return this.client.delete(
            `/points-de-terminaison/prereglages/${encodeURIComponent(prereglage)}/cle`);
    },

    /**
     * Les modèles que ce point de terminaison déclare servir.
     *
     * Lire la liste chez le fournisseur supprime une classe entière de fautes :
     * un nom saisi à la main ne se trompe qu'une fois, mais il se trompe en
     * silence — l'appel échoue plus tard, dans un écran qui parle d'autre chose.
     */
    async listerLesModeles(prereglage) {
        return this.client.get(
            `/points-de-terminaison/prereglages/${encodeURIComponent(prereglage)}/modeles`);
    },

    /** Un vrai aller-retour, et ce qu'il a coûté en temps. */
    async essayerLePointDeTerminaison(prereglage) {
        return this.client.post(
            `/points-de-terminaison/prereglages/${encodeURIComponent(prereglage)}/essai`, {});
    },

    /** État de l'annotateur sémantique et de ce qu'il aurait le droit d'envoyer. */
    async getAnnotatorStatus() {
        return this.client.get('/mining/annotator');
    },

    /**
     * Conserve les noms retenus sur les candidats d'un mining.
     *
     * Ce n'est pas une décision de gouvernance : un candidat nommé n'est ni
     * validé ni refusé. C'est le travail de relecture d'un lot, mis à l'abri
     * d'un rechargement de page.
     */
    async nommerLesCandidats(roleType, payload) {
        return this.client.post(`/kb/candidates/${roleType}/noms`, payload);
    },

    /** Demande une proposition de nom. Elle ne s'applique jamais seule. */
    async suggestRoleName(params) {
        return this.client.post('/mining/suggest-name', params);
    },

    async createBusinessRole(payload) {
        return this.client.post('/mining-metiers/create-role-business', payload);
    },
    // Méthodes génériques (requises par workspaces.js)
    get(endpoint, params) {
        return this.client.get(endpoint, params);
    },

    post(endpoint, data) {
        return this.client.post(endpoint, data);
    },

    put(endpoint, data) {
        return this.client.put(endpoint, data);
    },

    delete(endpoint) {
        return this.client.delete(endpoint);
    },

    blob(endpoint) {
        return this.client.blob(endpoint);
    }
};

window.API = API;
window.APIError = APIError;
