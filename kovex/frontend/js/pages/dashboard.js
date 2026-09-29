/**
 * PyGIA Frontend - Dashboard Page
 */

const DashboardPage = {
    chart: null,
    //: Dernières statistiques reçues, pour pouvoir les réafficher dans une
    //  autre langue sans nouvel appel.
    dernieresStats: null,

    async init() {
        await this.loadStats();
        await this.initChart();
        this.animateCards();
    },

    async loadStats() {
        try {
            const data = await API.getDashboardStats();
            this.dernieresStats = data;
            
            // Update stat cards
            this.updateStat('stat-users', data.total_users);
            this.updateStat('stat-apps', data.total_applications);
            this.updateStat('stat-rights', data.total_rights);
            
            // Update nav counts
            document.getElementById('nav-count-users').textContent = Utils.formatNumber(data.total_users);
            document.getElementById('nav-count-apps').textContent = Utils.formatNumber(data.total_applications);
            document.getElementById('nav-count-rights').textContent = Utils.formatNumber(data.total_rights);
            
            // Update health
            this.updateHealth(data.health_score, data.health_status_key);
            
            // Update top apps
            this.renderTopApps(data.top_applications);

            this.renderEvolution(data.evolution);

        } catch (error) {
            Toast.error(I18n.t('common.error'), I18n.t('error.load_stats_failed'));
        }
    },

    /**
     * Quel compteur porte l'évolution de quel volume.
     *
     * Le serveur nomme les volumes comme le référentiel les compte ; l'écran
     * les affiche dans ses cartes. Une table plutôt qu'une suite de `if` :
     * ajouter un compteur ne doit pas demander de retrouver trois endroits.
     */
    EVOLUTIONS: {
        users: 'stat-users-trend',
        apps: 'stat-apps-trend',
        rights: 'stat-rights-trend',
    },

    /**
     * L'évolution du référentiel depuis le relevé précédent.
     *
     * Ces trois emplacements portaient « Actifs », « Stable » et « +12 % ».
     * Les trois étaient écrits dans le gabarit : aucun ne mesurait quoi que ce
     * soit, et le pourcentage se lisait pourtant comme une mesure. Sur un
     * produit qui reproche aux autres d'afficher des chiffres qu'ils ne savent
     * pas justifier, c'était le défaut le moins défendable — et il était en
     * première page.
     *
     * Mesurer une évolution demande deux relevés. Tant qu'il n'y en a qu'un,
     * il n'y a rien à dire, et la carte ne dit rien.
     */
    renderEvolution(evolution) {
        const comptes = evolution && evolution.counts ? evolution.counts : {};
        const date = evolution && evolution.since
            ? new Date(evolution.since).toLocaleDateString(I18n.currentLocale || undefined)
            : '';

        Object.entries(DashboardPage.EVOLUTIONS).forEach(([volume, identifiant]) => {
            const zone = document.getElementById(identifiant);
            if (!zone) return;
            const ecart = comptes[volume];

            if (!evolution || typeof ecart !== 'number') {
                zone.hidden = true;
                zone.textContent = '';
                zone.className = 'stat-trend';
                return;
            }

            // Le signe décide de l'icône et du sens ; zéro est une information
            // à part entière — le volume n'a pas bougé entre deux versions du
            // référentiel, et c'est ce qu'on voulait savoir.
            const sens = ecart > 0 ? 'up' : (ecart < 0 ? 'down' : 'neutral');
            const icone = {up: 'fa-arrow-up', down: 'fa-arrow-down',
                           neutral: 'fa-minus'}[sens];
            const cle = {up: 'stats.trend.gained', down: 'stats.trend.lost',
                         neutral: 'stats.trend.unchanged'}[sens];

            zone.className = `stat-trend ${sens}`;
            zone.hidden = false;
            zone.innerHTML = `<i class="fas ${icone}" aria-hidden="true"></i> ${
                Utils.escapeHtml(I18n.t(cle, {
                    count: Utils.formatNumber(Math.abs(ecart)), date,
                }))}`;
        });
    },

    /** Réaffiche l'état de santé, le palmarès et le graphique traduits. */
    rafraichirLangue() {
        if (this.dernieresStats) {
            this.updateHealth(this.dernieresStats.health_score,
                              this.dernieresStats.health_status_key);
            this.renderTopApps(this.dernieresStats.top_applications);
            this.renderEvolution(this.dernieresStats.evolution);
        }
        if (this.distribution) this.renderDistribution();
    },

    updateStat(elementId, value) {
        const el = document.getElementById(elementId);
        if (el) {
            el.innerHTML = Utils.formatNumber(value);
        }
    },

    /**
     * Affiche le score de sante. L'etat arrive du backend sous forme de cle
     * i18n : le frontend ne redefinit ni les seuils ni les libelles.
     */
    updateHealth(score, statusKey) {
        const scoreEl = document.getElementById('stat-health-score');
        const statusEl = document.getElementById('stat-health-status');
        const iconEl = document.getElementById('health-icon');
        const ringFill = document.querySelector('.progress-ring-fill');

        const severites = {
            'health.status.healthy': { texte: 'text-success', icone: null, anneau: 'var(--accent-success)' },
            'health.status.alert': { texte: 'text-warning', icone: 'warning', anneau: 'var(--accent-warning)' },
            'health.status.critical': { texte: 'text-danger', icone: 'danger', anneau: 'var(--accent-danger)' }
        };
        const severite = severites[statusKey] || null;

        // Par défaut, jamais au plus proche : 99,8 affiché « 100 » faisait
        // lire un jeu parfait là où le serveur comptait des anomalies.
        if (scoreEl) scoreEl.textContent = score !== undefined && score !== null ? Math.floor(score) : '-';

        if (statusEl) {
            statusEl.textContent = statusKey ? I18n.t(statusKey) : I18n.t('common.unknown');
            statusEl.className = 'stat-status';
            if (severite) statusEl.classList.add(severite.texte);
        }

        if (iconEl) {
            iconEl.classList.remove('warning', 'danger');
            if (severite && severite.icone) iconEl.classList.add(severite.icone);
        }

        if (ringFill && score !== undefined && score !== null) {
            ringFill.style.strokeDasharray = `${score}, 100`;
            if (severite) ringFill.style.stroke = severite.anneau;
        }
    },

    renderTopApps(topApps) {
        const container = document.getElementById('top-apps-list');
        if (!container || !topApps) return;

        const entries = Object.entries(topApps);
        if (entries.length === 0) {
            container.innerHTML = `<div class="empty-state mini"><p>${Utils.escapeHtml(I18n.t('empty.no_data'))}</p></div>`;
            return;
        }

        const maxCount = Math.max(...entries.map(([, count]) => count));
        
        container.innerHTML = entries.slice(0, 5).map(([name, count], index) => {
            const rankClass = index === 0 ? 'gold' : index === 1 ? 'silver' : index === 2 ? 'bronze' : '';
            const percentage = (count / maxCount) * 100;
            
            return `
                <div class="top-app-item">
                    <div class="top-app-rank ${rankClass}">${index + 1}</div>
                    <div class="top-app-info">
                        <div class="top-app-name" title="${Utils.escapeHtml(name)}">${Utils.escapeHtml(Utils.truncate(name, 30))}</div>
                        <div class="top-app-bar">
                            <div class="top-app-bar-fill" style="width: ${percentage}%"></div>
                        </div>
                    </div>
                    <div class="top-app-count">${Utils.formatNumber(count)}</div>
                </div>
            `;
        }).join('');
    },

    /**
     * Distribution du nombre de droits par identite, calculee sur les donnees
     * du workspace.
     *
     * Ce graphique remplace une courbe d'activite qui etait alimentee par des
     * valeurs aleatoires generees dans le navigateur : le referentiel est un
     * instantane, il ne porte aucune dimension temporelle, aucune activite ne
     * pouvait donc en etre tiree.
     *
     * La forme de cette distribution decide de ce que le mining peut faire :
     * plus elle est etalee, moins il existe de signatures de droits partagees,
     * donc moins il existe de regroupements exacts.
     */
    async initChart() {
        const canvas = document.getElementById('rights-distribution-chart');
        if (!canvas || !window.Chart) return;

        let data;
        try {
            data = await API.getRightsDistribution();
        } catch (error) {
            Toast.error(I18n.t('common.error'), error.message);
            return;
        }
        this.distribution = data;

        const bascule = document.getElementById('rights-distribution-log');
        if (bascule && !bascule.dataset.lie) {
            bascule.dataset.lie = '1';
            bascule.addEventListener('change', () => this.renderDistribution());
        }

        this.renderDistribution();
    },

    /**
     * Distribution du nombre de droits par identite, calculee sur les donnees
     * du workspace.
     *
     * Ce graphique remplace une courbe d'activite alimentee par des valeurs
     * aleatoires : le referentiel est un instantane, il ne porte aucune
     * dimension temporelle.
     *
     * La forme de cette distribution decide de ce que le mining peut faire :
     * plus elle est etalee, moins il existe de signatures de droits partagees,
     * donc moins il existe de regroupements exacts.
     *
     * Deux difficultes de lecture, propres a ce type de distribution :
     *
     * - l'effectif s'etale sur plusieurs ordres de grandeur (sur un referentiel
     *   reel : de 1 a 2796 identites par barre). En echelle lineaire, tout ce
     *   qui suit les premieres barres est ecrase contre l'axe et illisible.
     *   D'ou l'echelle logarithmique par defaut, que l'utilisateur peut lever.
     * - la queue de distribution occupe la majeure partie de l'axe pour une
     *   poignee d'identites. La courbe cumulee, en second axe, la rend
     *   exploitable : elle repond directement a « quelle part des identites
     *   detient moins de N droits ».
     */
    renderDistribution() {
        const canvas = document.getElementById('rights-distribution-chart');
        const data = this.distribution;
        if (!canvas || !data) return;

        if (this.chart) {
            this.chart.destroy();
            this.chart = null;
        }

        const points = data.distribution || [];
        const legende = document.getElementById('rights-distribution-summary');
        if (legende) {
            legende.textContent = points.length === 0
                ? I18n.t('empty.no_data')
                : I18n.t('chart.rights_distribution.summary', {
                    identities: Utils.formatNumber(data.identities_total),
                    median: data.median_rights,
                    max: Utils.formatNumber(data.max_rights),
                    without: Utils.formatNumber(data.identities_without_rights)
                });
        }
        if (points.length === 0) return;

        // Part des identites detenant au plus N droits.
        const total = points.reduce((somme, point) => somme + point.identities, 0);
        let cumul = 0;
        const cumulees = points.map((point) => {
            cumul += point.identities;
            return Math.round((1000 * cumul) / total) / 10;
        });

        const lire = (nom) => getComputedStyle(document.documentElement).getPropertyValue(nom).trim();
        const barre = lire('--chart-roles');
        const courbe = lire('--chart-coverage');
        const grille = lire('--chart-grid');
        const graduation = lire('--chart-tick');

        const logarithmique = document.getElementById('rights-distribution-log')?.checked !== false;

        this.chart = new Chart(canvas.getContext('2d'), {
            data: {
                labels: points.map((point) => point.rights),
                datasets: [
                    {
                        type: 'bar',
                        label: I18n.t('chart.rights_distribution.identities'),
                        data: points.map((point) => point.identities),
                        backgroundColor: barre,
                        borderColor: barre,
                        borderWidth: 0,
                        yAxisID: 'y',
                        order: 2
                    },
                    {
                        type: 'line',
                        label: I18n.t('chart.rights_distribution.cumulative'),
                        data: cumulees,
                        borderColor: courbe,
                        backgroundColor: courbe,
                        yAxisID: 'yCumul',
                        pointRadius: 0,
                        borderWidth: 2,
                        tension: 0.2,
                        order: 1
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { intersect: false, mode: 'index' },
                plugins: {
                    legend: { labels: { color: graduation } },
                    tooltip: {
                        callbacks: {
                            title: (elements) => I18n.t('chart.rights_distribution.tooltip_title', {
                                rights: elements[0].label
                            })
                        }
                    }
                },
                scales: {
                    x: {
                        title: { display: true, text: I18n.t('chart.rights_distribution.x'), color: graduation },
                        grid: { display: false },
                        ticks: { color: graduation, maxTicksLimit: 20, autoSkip: true }
                    },
                    y: {
                        type: logarithmique ? 'logarithmic' : 'linear',
                        position: 'left',
                        beginAtZero: !logarithmique,
                        title: { display: true, text: I18n.t('chart.rights_distribution.y'), color: graduation },
                        grid: { color: grille },
                        ticks: { color: graduation }
                    },
                    yCumul: {
                        type: 'linear',
                        position: 'right',
                        min: 0,
                        max: 100,
                        title: { display: true, text: I18n.t('chart.rights_distribution.cumulative'), color: graduation },
                        grid: { display: false },
                        ticks: { color: graduation, callback: (valeur) => `${valeur} %` }
                    }
                }
            }
        });
    },

    animateCards() {
        const cards = document.querySelectorAll('[data-animate]');
        setTimeout(() => Utils.animateIn(cards), 100);
    }
};

window.DashboardPage = DashboardPage;
