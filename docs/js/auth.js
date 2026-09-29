/**
 * PyGIA Frontend - Module d'Authentification
 * Gère la connexion, les tokens JWT et la protection des routes.
 */

const Auth = {
    // Clés de stockage
    TOKEN_KEY: 'pygia_token',
    USER_KEY: 'pygia_user',
    
    // État
    _token: null,
    _user: null,
    _initialized: false,

    /**
     * Initialise le module d'authentification.
     * À appeler au démarrage de l'application.
     */
    init() {
        if (this._initialized) return;
        
        // Charger le token depuis le localStorage
        this._token = localStorage.getItem(this.TOKEN_KEY);
        const userJson = localStorage.getItem(this.USER_KEY);
        
        if (userJson) {
            try {
                this._user = JSON.parse(userJson);
            } catch (e) {
                this.logout();
            }
        }
        
        this._initialized = true;
    },

    /**
     * Vérifie si l'utilisateur est authentifié.
     */
    isAuthenticated() {
        return !!this._token && !!this._user;
    },

    /**
     * Retourne le token JWT actuel.
     */
    getToken() {
        return this._token;
    },

    /**
     * Retourne les informations de l'utilisateur.
     */
    getUser() {
        return this._user;
    },

    /**
     * Vérifie si l'utilisateur a une permission.
     */
    hasPermission(permission) {
        if (!this._user) return false;
        
        const permissionsMap = {
            'admin': ['read', 'write', 'delete', 'admin', 'mining', 'roles'],
            'analyst': ['read', 'write', 'mining', 'roles'],
            'viewer': ['read']
        };
        
        const userPermissions = permissionsMap[this._user.role] || [];
        return userPermissions.includes(permission);
    },

    /**
     * Connecte l'utilisateur.
     */
    async login(username, password) {
        try {
            const response = await fetch(`${Config.API_URL}/auth/login`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ username, password })
            });

            if (!response.ok) {
                const error = await response.json();
                // Le serveur rend `{code, params}` : la clé est traduite ici.
                const detail = error && error.detail;
                const message = (detail && typeof detail === 'object' && detail.code)
                    ? I18n.t(detail.code, detail.params || {})
                    : (typeof detail === 'string' && detail) || I18n.t('auth.login_failed');
                throw new Error(message);
            }

            const data = await response.json();
            
            // Stocker le token et l'utilisateur
            this._token = data.access_token;
            this._user = data.user;
            
            localStorage.setItem(this.TOKEN_KEY, this._token);
            localStorage.setItem(this.USER_KEY, JSON.stringify(this._user));
            
            return { success: true, user: this._user };
            
        } catch (error) {
            return { success: false, error: error.message };
        }
    },

    /**
     * Déconnecte l'utilisateur.
     */
    logout() {
        this._token = null;
        this._user = null;
        localStorage.removeItem(this.TOKEN_KEY);
        localStorage.removeItem(this.USER_KEY);
        
        // Recharger la page pour afficher le login
        window.location.reload();
    },

    /**
     * Rafraîchit le token.
     */
    async refreshToken() {
        if (!this._token) return false;
        
        try {
            const response = await fetch(`${Config.API_URL}/auth/refresh`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${this._token}`,
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                this.logout();
                return false;
            }

            const data = await response.json();
            this._token = data.access_token;
            localStorage.setItem(this.TOKEN_KEY, this._token);
            
            return true;
        } catch (error) {
            return false;
        }
    },

    /**
     * Vérifie la validité du token.
     */
    async verifyToken() {
        if (!this._token) return false;
        
        try {
            const response = await fetch(`${Config.API_URL}/auth/verify`, {
                headers: {
                    'Authorization': `Bearer ${this._token}`
                }
            });
            
            return response.ok;
        } catch (error) {
            return false;
        }
    },

    /**
     * Ajoute le header d'authentification à une requête.
     */
    getAuthHeaders() {
        if (!this._token) return {};
        return {
            'Authorization': `Bearer ${this._token}`
        };
    }
};

// Rendre Auth global
window.Auth = Auth;


/**
 * Composant de page de connexion.
 */
const LoginPage = {
    /**
     * Affiche la page de connexion.
     */
    show() {
        const app = document.getElementById('app');
        if (!app) return;
        
        // Aucun libellé n'est écrit ici : la page de connexion est la
        // première vue du produit, et c'était la seule à rester en français
        // quelle que soit la langue choisie.
        app.innerHTML = `
            <div class="login-container">
                <div class="login-card">
                    <div class="login-header">
                        <div class="login-logo">
                            <svg viewBox="0 0 40 40" fill="none" aria-hidden="true">
                                <rect x="4" y="4" width="14" height="14" rx="3" fill="currentColor" opacity="0.9"/>
                                <rect x="22" y="4" width="14" height="14" rx="3" fill="currentColor" opacity="0.6"/>
                                <rect x="4" y="22" width="14" height="14" rx="3" fill="currentColor" opacity="0.6"/>
                                <rect x="22" y="22" width="14" height="14" rx="3" fill="currentColor" opacity="0.3"/>
                            </svg>
                        </div>
                        <h1>${Utils.escapeHtml(I18n.t('app.name'))}</h1>
                        <p>${Utils.escapeHtml(I18n.t('app.title.long'))}</p>
                    </div>

                    <form id="login-form" class="login-form">
                        <div class="form-group">
                            <label class="form-label" for="username">${Utils.escapeHtml(I18n.t('auth.username.label'))}</label>
                            <input
                                type="text"
                                id="username"
                                name="username"
                                class="form-input"
                                placeholder="${Utils.escapeHtml(I18n.t('auth.username.placeholder'))}"
                                autocomplete="username"
                                required
                            >
                        </div>

                        <div class="form-group">
                            <label class="form-label" for="password">${Utils.escapeHtml(I18n.t('auth.password.label'))}</label>
                            <input
                                type="password"
                                id="password"
                                name="password"
                                class="form-input"
                                placeholder="${Utils.escapeHtml(I18n.t('auth.password.placeholder'))}"
                                autocomplete="current-password"
                                required
                            >
                        </div>

                        <div id="login-error" class="login-error" role="alert" style="display: none;"></div>

                        <button type="submit" class="btn btn-primary btn-lg btn-block" id="login-btn">
                            <i class="fas fa-sign-in-alt" aria-hidden="true"></i>
                            <span>${Utils.escapeHtml(I18n.t('action.login'))}</span>
                        </button>
                    </form>
                </div>
            </div>
        `;

        // Ajouter les styles de login si pas déjà présents
        this.addStyles();
        
        // Bind du formulaire
        const form = document.getElementById('login-form');
        form.addEventListener('submit', (e) => this.handleSubmit(e));
    },

    /**
     * Gère la soumission du formulaire.
     */
    async handleSubmit(e) {
        e.preventDefault();
        
        const username = document.getElementById('username').value.trim();
        const password = document.getElementById('password').value;
        const errorDiv = document.getElementById('login-error');
        const btn = document.getElementById('login-btn');
        
        if (!username || !password) {
            this.showError(I18n.t('auth.fill_all_fields'));
            return;
        }
        
        // Désactiver le bouton
        btn.disabled = true;
        btn.innerHTML = `<i class="fas fa-spinner fa-spin" aria-hidden="true"></i> <span>${Utils.escapeHtml(I18n.t('auth.signing_in'))}</span>`;
        errorDiv.style.display = 'none';
        
        // `Auth.login` ne rejette jamais : il rattrape tout et rend
        // `{success, error}`. Un `try/catch` supplémentaire ici était du code
        // que rien ne pouvait atteindre — et qui laissait croire que le cas
        // réseau était traité à deux endroits. Le contrat est vérifié par
        // `test_la_connexion_ne_rejette_jamais`.
        const result = await Auth.login(username, password);

        if (result.success) {
            // Recharger la page pour afficher l'app
            window.location.reload();
        } else {
            this.showError(result.error);
            this.reactiverBouton(btn);
        }
    },

    /**
     * Remet le bouton dans son état initial après un échec.
     */
    reactiverBouton(btn) {
        btn.disabled = false;
        btn.innerHTML = `<i class="fas fa-sign-in-alt" aria-hidden="true"></i> <span>${Utils.escapeHtml(I18n.t('action.login'))}</span>`;
    },

    /**
     * Affiche une erreur.
     */
    showError(message) {
        const errorDiv = document.getElementById('login-error');
        if (errorDiv) {
            errorDiv.textContent = message;
            errorDiv.style.display = 'block';
        }
    },

    /**
     * Ajoute les styles CSS pour la page de login.
     */
    addStyles() {
        if (document.getElementById('login-styles')) return;
        
        const styles = document.createElement('style');
        styles.id = 'login-styles';
        styles.textContent = `
            .login-container {
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 20px;
                background: linear-gradient(135deg, var(--bg-primary) 0%, var(--bg-secondary) 100%);
            }
            
            .login-card {
                width: 100%;
                max-width: 400px;
                background: var(--card-bg);
                border: 1px solid var(--card-border);
                border-radius: var(--radius-xl);
                padding: 40px;
                box-shadow: var(--shadow-xl);
            }
            
            .login-header {
                text-align: center;
                margin-bottom: 32px;
            }
            
            .login-logo {
                width: 64px;
                height: 64px;
                margin: 0 auto 16px;
                color: var(--accent-primary);
            }
            
            .login-header h1 {
                font-size: 28px;
                font-weight: 700;
                margin-bottom: 4px;
            }
            
            .login-header p {
                color: var(--text-secondary);
                font-size: 14px;
            }
            
            .login-form {
                display: flex;
                flex-direction: column;
                gap: 20px;
            }
            
            .login-error {
                padding: 12px;
                background: rgba(244, 63, 94, 0.1);
                border: 1px solid rgba(244, 63, 94, 0.3);
                border-radius: var(--radius-md);
                color: var(--accent-danger);
                font-size: 14px;
                text-align: center;
            }
            
            .btn-block {
                width: 100%;
            }
        `;
        document.head.appendChild(styles);
    }
};

window.LoginPage = LoginPage;
