/**
 * PyGIA Frontend - State Manager
 * Gestionnaire d'état centralisé simple (inspiré de Redux mais sans dépendance).
 */

const Store = {
    // État global
    _state: {
        user: null,
        data: { users: [], applications: [], rights: [], roles: [] },
        stats: { totalUsers: 0, totalApplications: 0, totalRights: 0, healthScore: null, healthStatusKey: null },
        ui: { currentPage: 'dashboard', sidebarCollapsed: false, theme: 'dark', loading: {}, errors: {} },
        mining: { results: [], businessResults: [], isRunning: false, lastParams: null },
        config: { miningMinUsers: 5, miningGammaMin: 0.5, miningMaxDepth: 6 }
    },
    
    _subscribers: {},
    
    get(path) {
        return path.split('.').reduce((obj, key) => obj && obj[key], this._state);
    },
    
    set(path, value, silent = false) {
        const keys = path.split('.');
        const lastKey = keys.pop();
        const target = keys.reduce((obj, key) => {
            if (!obj[key]) obj[key] = {};
            return obj[key];
        }, this._state);
        
        const oldValue = target[lastKey];
        target[lastKey] = value;
        
        if (!silent) this._notify(path, value, oldValue);
    },
    
    subscribe(path, callback) {
        if (!this._subscribers[path]) this._subscribers[path] = [];
        this._subscribers[path].push(callback);
        return () => {
            const idx = this._subscribers[path].indexOf(callback);
            if (idx > -1) this._subscribers[path].splice(idx, 1);
        };
    },
    
    setLoading(key, isLoading) {
        const loading = { ...this.get('ui.loading'), [key]: isLoading };
        this.set('ui.loading', loading);
    },
    
    isLoading(key) {
        const loading = this.get('ui.loading') || {};
        return key ? loading[key] === true : Object.values(loading).some(v => v);
    },
    
    setError(key, error) {
        const errors = { ...this.get('ui.errors'), [key]: error };
        this.set('ui.errors', errors);
    },
    
    _notify(path, newValue, oldValue) {
        if (this._subscribers[path]) {
            this._subscribers[path].forEach(cb => cb(newValue, oldValue));
        }
        // Notifier les parents
        const parts = path.split('.');
        for (let i = parts.length - 1; i > 0; i--) {
            const parent = parts.slice(0, i).join('.');
            if (this._subscribers[parent]) {
                this._subscribers[parent].forEach(cb => cb(this.get(parent)));
            }
        }
    }
};

/**
 * Actions - Fonctions métier pour modifier l'état.
 */
const Actions = {
    async loadDashboardStats() {
        Store.setLoading('dashboard', true);
        try {
            const data = await API.getDashboardStats();
            Store.set('stats.totalUsers', data.total_users);
            Store.set('stats.totalApplications', data.total_applications);
            Store.set('stats.totalRights', data.total_rights);
            Store.set('stats.healthScore', data.health_score);
            Store.set('stats.healthStatusKey', data.health_status_key);
        } catch (e) {
            Store.setError('dashboard', e.message);
        } finally {
            Store.setLoading('dashboard', false);
        }
    },
    
    async loadRoles() {
        Store.setLoading('roles', true);
        try {
            const roles = await API.getRoles();
            Store.set('data.roles', roles);
            return roles;
        } catch (e) {
            Store.setError('roles', e.message);
        } finally {
            Store.setLoading('roles', false);
        }
    },
    
    navigateTo(page) {
        Store.set('ui.currentPage', page);
        window.location.hash = page;
    },
    
    toggleTheme() {
        const current = Store.get('ui.theme');
        const newTheme = current === 'dark' ? 'light' : 'dark';
        Store.set('ui.theme', newTheme);
        document.documentElement.setAttribute('data-theme', newTheme);
        Utils.storage.set('pygia_theme', newTheme);
    }
};

window.Store = Store;
window.Actions = Actions;
