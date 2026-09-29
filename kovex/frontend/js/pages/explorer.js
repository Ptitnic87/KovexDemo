/**
 * PyGIA Frontend - Data Explorer Pages
 */

const ExplorerPage = {
    tables: {},

    init() {
        this.tables.users = new DataTable({
            type: 'users',
            endpoint: '/users/list',
            theadId: 'users-thead',
            tbodyId: 'users-tbody',
            searchId: 'search-users',
            countId: 'users-count',
            paginationPrefix: 'users'
        });

        this.tables.applications = new DataTable({
            type: 'applications',
            endpoint: '/applications/list',
            theadId: 'applications-thead',
            tbodyId: 'applications-tbody',
            searchId: 'search-applications',
            countId: 'applications-count',
            paginationPrefix: 'applications'
        });

        this.tables.rights = new DataTable({
            type: 'rights',
            endpoint: '/rights/list',
            theadId: 'rights-thead',
            tbodyId: 'rights-tbody',
            searchId: 'search-rights',
            countId: 'rights-count',
            paginationPrefix: 'rights'
        });
    },

    loadTable(type) {
        if (this.tables[type]) {
            this.tables[type].load();
        }
    }
};

window.ExplorerPage = ExplorerPage;
