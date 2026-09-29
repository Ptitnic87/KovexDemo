/**
 * Graphe des accès, en colonnes successives.
 *
 *     Identités → Rôles métier → Rôles applicatifs → Droits → Applications
 *
 * Deux principes :
 *
 * 1. Rien n'est chargé d'avance. Chaque colonne est une requête distincte,
 *    paginée. Sur un référentiel de plusieurs milliers d'identités, un graphe
 *    complet n'est ni calculable ni lisible.
 *
 * 2. La lecture va dans les deux sens. Sélectionner un rôle métier montre ses
 *    identités à gauche autant que ses droits et applications à droite : une
 *    chaîne d'accès se lit du porteur vers la ressource comme l'inverse. La
 *    colonne sur laquelle on vient d'agir pilote toutes les autres.
 *
 * Le backend ne renvoie ni couleur ni libellé : la mise en forme vient des
 * variables du thème et les textes des catalogues i18n.
 */

//: Nom de la colonne des droits, le seul endroit où les deux filtres
//: d'affichage s'appliquent. Écrit une fois plutôt que répété quatre fois.
const DROIT_COLONNE = 'right';

//: Colonnes qui portent des rôles, donc les seules dont l'origine se décide.
//: Le serveur les nomme de la même façon dans l'état des rôles.
const COLONNES_DE_ROLE = ['business_role', 'application_role'];

const GraphView = {
    columns: [],
    transitions: {},
    state: {},
    /** Colonne dont la sélection pilote actuellement les autres. */
    driver: null,
    pageSize: 25,
    /** Taille maximale d'un catalogue chargé pour une liste déroulante. */
    catalogSize: 500,

    /** La première colonne se parcourt par recherche : trop d'identités pour
     *  une liste déroulante. Les autres sont des listes de choix. */
    SEARCHABLE: ['identity'],

    async init() {
        const container = document.getElementById('graph-container');
        if (!container) return;

        container.innerHTML = `<div class="graph-loader">
            <i class="fas fa-circle-notch fa-spin fa-2x" aria-hidden="true"></i>
            <div>${Utils.escapeHtml(I18n.t('common.loading'))}</div>
        </div>`;

        try {
            const description = await API.client.get('/graph/columns');
            GraphView.columns = description.columns;
            GraphView.transitions = description.transitions;
        } catch (error) {
            container.innerHTML = `<div class="graph-error">${Utils.escapeHtml(error.message)}</div>`;
            return;
        }

        GraphView.driver = null;
        GraphView.state = {};
        GraphView.columns.forEach(colonne => {
            GraphView.state[colonne] = {
                items: [], links: [], total: 0, offset: 0,
                selection: new Set(), search: '',
                catalog: [], catalogTotal: 0, loaded: false,
            };
        });

        GraphView.renderShell(container);
        await GraphView.chargerEtatDesRoles();
        await Promise.all(GraphView.columns.map(c => GraphView.loadCatalog(c)));
        await GraphView.loadColumn(GraphView.columns[0]);
    },

    /** Origines affichées. Les validés seuls au départ : c'est l'« avant ». */
    origines: { validated: true, suggested: false, rejected: false },

    /**
     * Droits socles affichés dans la colonne des droits. Masqués au départ.
     *
     * Un droit socle est détenu par la quasi-totalité de la population. Le
     * dessiner produit un graphe biparti quasi complet — illisible, et sans
     * information puisqu'il est identique pour tout le monde. Il reste
     * accessible d'un clic : le masquer par défaut n'est pas le cacher.
     */
    socles: false,

    /**
     * N'afficher que les droits que le rôle sélectionné ajouterait.
     *
     * C'est la question du valideur — « qu'est-ce que ça coûte » — et elle
     * n'avait pas de réponse : le graphe montrait ce qu'un rôle apporte sans
     * jamais montrer ce qu'il accorde en trop.
     */
    ajoutesSeulement: false,
    droitsNonCouverts: false,
    etatRoles: null,

    async chargerEtatDesRoles() {
        try {
            GraphView.etatRoles = await API.get('/graph/roles-status');
        } catch (error) {
            GraphView.etatRoles = null;
        }
        GraphView.renderFiltres();
    },

    /** Réaffiche filtres, listes et colonnes dans la langue courante. */
    rafraichirLangue() {
        if (!GraphView.columns.length) return;
        GraphView.renderFiltres();
        GraphView.columns.forEach(colonne => {
            GraphView.renderPickerOptions(colonne);
            GraphView.renderColumn(colonne);
        });
        GraphView.syncPickers();
    },

    /** Origines demandées au serveur, sous forme de paramètre de requête. */
    originesDemandees() {
        return Object.entries(GraphView.origines)
            .filter(([, actif]) => actif)
            .map(([nom]) => nom);
    },

    renderFiltres() {
        const conteneur = document.getElementById('graph-filtres');
        if (!conteneur) return;

        const etat = GraphView.etatRoles;
        const total = (origine) => {
            if (!etat) return null;
            return Object.values(etat.types || {})
                .reduce((somme, t) => somme + (t[origine] || 0), 0);
        };

        // Le détail par type de rôle. Le total seul additionne les métiers et
        // les applicatifs : devant une colonne de rôles métiers vide et un
        // filtre annonçant « Suggérés (1 751) », on ne peut pas savoir si ces
        // 1 751 concernent la colonne qu'on regarde ou l'autre. C'est
        // exactement la question qui est restée sans réponse.
        const detail = (origine) => {
            if (!etat || !etat.types) return '';
            const parType = COLONNES_DE_ROLE
                .filter(colonne => (etat.types[colonne] || {})[origine])
                .map(colonne => `${I18n.t(`graph.column.${colonne}`)} ${
                    Utils.formatNumber(etat.types[colonne][origine])}`);
            return parType.length > 1 ? ` — ${parType.join(', ')}` : '';
        };

        const cases = [
            ['validated', 'graph.origin.validated'],
            ['suggested', 'graph.origin.suggested'],
            ['rejected', 'graph.origin.rejected'],
        ].map(([nom, cle]) => {
            const nombre = total(nom);
            const libelle = nombre === null
                ? I18n.t(cle)
                : `${I18n.t(cle)} (${Utils.formatNumber(nombre)})${detail(nom)}`;
            return `
                <label class="graph-filtre graph-filtre--${nom}">
                    <input type="checkbox" data-origine="${nom}"
                           ${GraphView.origines[nom] ? 'checked' : ''}>
                    <span>${Utils.escapeHtml(libelle)}</span>
                </label>`;
        }).join('');

        const nonCouverts = `
            <label class="graph-filtre graph-filtre--uncovered">
                <input type="checkbox" id="graph-non-couverts"
                       ${GraphView.droitsNonCouverts ? 'checked' : ''}>
                <span>${Utils.escapeHtml(I18n.t('graph.uncovered_rights'))}</span>
            </label>`;

        const socles = `
            <label class="graph-filtre graph-filtre--socles">
                <input type="checkbox" id="graph-socles"
                       ${GraphView.socles ? 'checked' : ''}>
                <span>${Utils.escapeHtml(I18n.t('graph.birth_rights_shown'))}</span>
            </label>`;

        const ajoutes = `
            <label class="graph-filtre graph-filtre--ajoutes">
                <input type="checkbox" id="graph-ajoutes"
                       ${GraphView.ajoutesSeulement ? 'checked' : ''}>
                <span>${Utils.escapeHtml(I18n.t('graph.added_only'))}</span>
            </label>`;

        conteneur.innerHTML = cases + nonCouverts + socles + ajoutes
            + GraphView.renderPeremption();
    },

    /**
     * Avertissement de péremption.
     *
     * Un mining conservé peut porter sur des données depuis modifiées. On
     * l'affiche quand même — une comparaison sur des données légèrement
     * différentes reste souvent utile — mais jamais sans le dire : comparer
     * sans savoir sur quoi porte la comparaison est le piège à éviter.
     */
    renderPeremption() {
        const etat = GraphView.etatRoles;
        if (!etat || !GraphView.origines.suggested && !GraphView.origines.rejected) {
            return '';
        }
        const perimes = Object.values(etat.types || {}).filter(t => t.stale);
        if (!perimes.length) return '';

        const date = perimes[0].computed_at
            ? new Date(perimes[0].computed_at).toLocaleString(I18n.currentLocale || undefined)
            : '';
        return `<span class="graph-peremption">
                    <i class="fas fa-triangle-exclamation" aria-hidden="true"></i>
                    ${Utils.escapeHtml(I18n.t('graph.stale_mining', { date }))}
                </span>`;
    },

    // ------------------------------------------------------------ rendu

    renderShell(container) {
        container.innerHTML = `
            <div class="access-graph">
                <div class="access-graph__header">
                    <label class="access-graph__page-size">
                        <span>${Utils.escapeHtml(I18n.t('graph.page_size'))}</span>
                        <input type="number" id="graph-page-size" class="form-input"
                               min="1" max="500" step="5" value="${GraphView.pageSize}">
                    </label>
                    <button id="graph-clear" class="btn btn-secondary btn-sm">
                        <i class="fas fa-rotate-left" aria-hidden="true"></i>
                        ${Utils.escapeHtml(I18n.t('graph.clear_selection'))}
                    </button>
                    <div class="graph-filtres" id="graph-filtres"></div>
                </div>
                <div class="access-graph__board">
                    <svg class="access-graph__links" id="graph-links" aria-hidden="true"></svg>
                    <div class="access-graph__columns">
                        ${GraphView.columns.map(colonne => `
                            <section class="access-column" data-column="${colonne}">
                                <h3 class="access-column__title">
                                    ${Utils.escapeHtml(I18n.t(`graph.column.${colonne}`))}
                                </h3>
                                ${GraphView.renderPicker(colonne)}
                                <ul class="access-column__list" data-column="${colonne}"></ul>
                                <footer class="access-column__footer" data-column="${colonne}"></footer>
                            </section>`).join('')}
                    </div>
                </div>
            </div>`;

        GraphView.columns.forEach(colonne => {
            const controle = document.querySelector(`[data-picker="${colonne}"]`);
            if (!controle) return;
            if (GraphView.SEARCHABLE.includes(colonne)) {
                const reagir = () => GraphView.onSearch(colonne, controle.value);
                controle.addEventListener('input',
                    Utils.debounce ? Utils.debounce(reagir, 250) : reagir);
            } else {
                controle.addEventListener('change',
                    () => GraphView.onPick(colonne, controle.value));
            }
        });

        document.getElementById('graph-page-size').addEventListener('change', event => {
            const valeur = parseInt(event.target.value, 10);
            if (!Number.isFinite(valeur) || valeur < 1) return;
            GraphView.pageSize = valeur;
            GraphView.refresh();
        });

        document.getElementById('graph-clear').addEventListener('click', () => GraphView.clear());

        // Délégation sur le bloc de filtres : il est reconstruit à chaque
        // changement d'état pour remettre les compteurs à jour.
        document.getElementById('graph-filtres').addEventListener('change', (evenement) => {
            const origine = evenement.target.dataset.origine;
            if (origine) {
                GraphView.origines[origine] = evenement.target.checked;
                GraphView.renderFiltres();
                GraphView.rechargerTout();
                return;
            }
            if (evenement.target.id === 'graph-non-couverts') {
                GraphView.droitsNonCouverts = evenement.target.checked;
                GraphView.renderFiltres();
                GraphView.rechargerTout();
                return;
            }
            // Ces deux-là ne rechargent rien : ils portent sur ce qui est déjà
            // là. Une colonne de droits vient d'un rôle sélectionné et compte
            // quelques dizaines d'éléments — les filtrer côté serveur
            // coûterait un aller-retour pour rien.
            if (evenement.target.id === 'graph-socles') {
                GraphView.socles = evenement.target.checked;
                GraphView.renderFiltres();
                GraphView.renderColumn(DROIT_COLONNE);
                return;
            }
            if (evenement.target.id === 'graph-ajoutes') {
                GraphView.ajoutesSeulement = evenement.target.checked;
                GraphView.renderFiltres();
                GraphView.renderColumn(DROIT_COLONNE);
            }
        });

        window.addEventListener('resize', () => {
            GraphView.hideTooltip();
            GraphView.drawLinks();
        });
        container.querySelector('.access-graph__columns')
                 .addEventListener('scroll', () => {
                     GraphView.hideTooltip();
                     GraphView.drawLinks();
                 }, true);
    },

    /** Champ de recherche pour les identités, liste déroulante ailleurs. */
    renderPicker(colonne) {
        if (GraphView.SEARCHABLE.includes(colonne)) {
            return `<input type="search" class="form-input access-column__picker"
                           data-picker="${colonne}"
                           placeholder="${Utils.escapeHtml(I18n.t('graph.search_placeholder'))}">`;
        }
        return `<select class="form-select access-column__picker" data-picker="${colonne}">
                    <option value="">${Utils.escapeHtml(I18n.t('graph.column.all'))}</option>
                </select>`;
    },

    /** Alimente une liste déroulante avec le catalogue de sa colonne. */
    async loadCatalog(colonne) {
        if (GraphView.SEARCHABLE.includes(colonne)) return;
        const etat = GraphView.state[colonne];

        try {
            const parametres = { layer: colonne, limit: GraphView.catalogSize };
            const origines = GraphView.originesDemandees();
            if (origines.length) parametres.origins = origines.join(',');
            const reponse = await API.client.get('/graph/layer', parametres);
            etat.catalog = reponse.items;
            etat.catalogTotal = reponse.total;
        } catch (error) {
            etat.catalog = [];
            etat.catalogTotal = 0;
        }
        GraphView.renderPickerOptions(colonne);
    },

    renderPickerOptions(colonne) {
        const liste = document.querySelector(`select[data-picker="${colonne}"]`);
        if (!liste) return;
        const etat = GraphView.state[colonne];

        const choix = etat.catalog.map(item =>
            `<option value="${Utils.escapeHtml(item.id)}">${Utils.escapeHtml(item.label)}</option>`
        ).join('');

        // Le catalogue peut dépasser ce qu'une liste déroulante supporte
        // confortablement : on le dit plutôt que de tronquer en silence.
        const partiel = etat.catalogTotal > etat.catalog.length
            ? `<option value="" disabled>${Utils.escapeHtml(
                   I18n.t('graph.column.partial_list', { shown: etat.catalog.length,
                                                         total: etat.catalogTotal }))}</option>`
            : '';

        liste.innerHTML =
            `<option value="">${Utils.escapeHtml(I18n.t('graph.column.all'))}</option>${choix}${partiel}`;
    },

    /**
     * Pourquoi cette colonne est vide.
     *
     * « Vide » et « il y en a, mais leur origine n'est pas cochée » se
     * ressemblent à l'écran, et seul le second se répare. Une colonne de rôles
     * qui tait l'existence de mille candidats non décidés laisse croire que le
     * mining n'a rien trouvé.
     */
    raisonDuVide(colonne) {
        const etat = GraphView.etatRoles;
        const compte = etat && etat.types && etat.types[colonne];
        if (!compte) return I18n.t('graph.column.empty');
        const decochees = ['suggested', 'rejected', 'validated']
            .filter(origine => compte[origine] && !GraphView.origines[origine]);
        if (!decochees.length) return I18n.t('graph.column.empty');
        return I18n.t('graph.column.empty_origin_unchecked', {
            nombre: Utils.formatNumber(
                decochees.reduce((somme, origine) => somme + compte[origine], 0)),
            origines: decochees.map(origine => I18n.t(`graph.origin.${origine}`)).join(', '),
        });
    },

    renderColumn(colonne) {
        const etat = GraphView.state[colonne];
        const liste = document.querySelector(`.access-column__list[data-column="${colonne}"]`);
        const pied = document.querySelector(`.access-column__footer[data-column="${colonne}"]`);
        if (!liste || !pied) return;

        if (!etat.loaded) {
            liste.innerHTML = `<li class="access-column__hint">${
                Utils.escapeHtml(I18n.t('graph.column.select_anywhere'))}</li>`;
            pied.innerHTML = '';
            return;
        }

        if (!etat.items.length) {
            liste.innerHTML = `<li class="access-column__hint">${
                Utils.escapeHtml(GraphView.raisonDuVide(colonne))}</li>`;
            pied.innerHTML = '';
            return;
        }

        const affiches = GraphView.itemsAffiches(colonne, etat);
        const masques = etat.items.length - affiches.length;

        if (!affiches.length) {
            liste.innerHTML = `<li class="access-column__hint">${
                Utils.escapeHtml(I18n.t('graph.column.empty'))}</li>`;
            pied.innerHTML = `<span class="access-column__count">${Utils.escapeHtml(
                I18n.t('graph.column.hidden', { count: masques }))}</span>`;
            GraphView.drawLinks();
            return;
        }

        liste.innerHTML = affiches.map(item => `
            <li class="access-item${etat.selection.has(item.id) ? ' access-item--selected' : ''}${
                    item.meta && item.meta.origin ? ` access-item--${item.meta.origin}` : ''}${
                    item.meta && item.meta.detenu === false ? ' access-item--a-recevoir' : ''}"
                data-column="${colonne}" data-id="${Utils.escapeHtml(item.id)}">
                <span class="access-item__marker access-item__marker--${colonne}"></span>
                <span class="access-item__label">${Utils.escapeHtml(item.label)}</span>
                ${GraphView.marqueDeReception(item)}
                ${GraphView.itemBadge(item, colonne, etat)}
            </li>`).join('');

        liste.querySelectorAll('.access-item').forEach(element => {
            const item = affiches.find(i => i.id === element.dataset.id);
            element.addEventListener('click', () => GraphView.toggle(colonne, element.dataset.id));
            // Les identifiants de droits sont souvent trop longs pour la
            // colonne : l'infobulle donne la valeur entière. Elle est posée
            // sur le document et non dans la colonne, dont le défilement la
            // rognerait.
            element.addEventListener('mouseenter', event =>
                GraphView.showTooltip(event, colonne, item));
            element.addEventListener('mousemove', event => GraphView.moveTooltip(event));
            element.addEventListener('mouseleave', () => GraphView.hideTooltip());
        });

        const suite = etat.offset + etat.items.length < etat.total
            ? `<button class="btn btn-secondary btn-sm access-column__more" data-column="${colonne}">
                   ${Utils.escapeHtml(I18n.t('graph.load_more'))}</button>`
            : '';
        // Ce qu'un filtre retire est annoncé : une liste raccourcie sans un
        // mot se lit comme une liste complète, et c'est ainsi qu'on conclut
        // qu'un droit n'existe pas.
        const retires = masques
            ? ` ${I18n.t('graph.column.hidden', { count: masques })}`
            : '';
        // Ce que la sélection ajouterait, dit une fois pour la colonne. Un
        // badge « +1 » sur une ligne se lit comme un défaut d'affichage tant
        // que rien n'a énoncé ce qu'il compte.
        const ajoutes = GraphView.phraseAjoutes(colonne, etat, affiches);
        pied.innerHTML = `<span class="access-column__count">${Utils.escapeHtml(
            I18n.t('graph.column.total', { shown: affiches.length, total: etat.total })
            + retires)}</span>${ajoutes}${suite}`;

        const bouton = pied.querySelector('.access-column__more');
        if (bouton) bouton.addEventListener('click', () => GraphView.loadMore(colonne));

        GraphView.drawLinks();
    },

    /**
     * Ce que la colonne montre réellement, une fois les filtres appliqués.
     *
     * Les deux filtres ne portent que sur la colonne des droits, et seulement
     * sur ce qui est déjà chargé : ils répondent à des questions de lecture,
     * pas de périmètre.
     */
    itemsAffiches(colonne, etat) {
        if (colonne !== DROIT_COLONNE) return etat.items;
        let items = etat.items;
        if (!GraphView.socles) {
            items = items.filter(item => !item.meta?.socle);
        }
        if (GraphView.ajoutesSeulement) {
            items = items.filter(item => GraphView.nouveauxPour(etat, item.id) > 0);
        }
        return items;
    },

    /**
     * Nombre de membres du rôle sélectionné qui recevraient ce droit.
     *
     * L'information vient du lien, pas de l'élément : c'est le couple
     * (rôle, droit) qui a un coût, pas le droit seul. Un droit atteint par
     * plusieurs rôles sélectionnés cumule leurs apports — c'est bien ce que
     * l'attribution de tous ces rôles produirait.
     */
    nouveauxPour(etat, identifiant) {
        return (etat.links || []).reduce((somme, lien) => (
            lien.to === identifiant && typeof lien.meta?.nouveaux === 'number'
                ? somme + lien.meta.nouveaux
                : somme
        ), 0);
    },

    /**
     * Ce que la sélection accorderait, énoncé pour la colonne entière.
     *
     * Sélectionner une identité puis un rôle fait apparaître des droits que
     * cette personne ne détient pas : c'est le sur-octroi du rôle, et c'est
     * l'information la plus utile de l'écran. Elle n'était portée que par un
     * badge « +1 » sur la ligne, qui se lit comme un défaut d'affichage tant
     * que rien n'a dit ce qu'il compte.
     */
    phraseAjoutes(colonne, etat, affiches) {
        if (!etat) return '';
        // Ce que la sélection ne détient pas encore, toutes colonnes
        // confondues : un rôle applicatif porté par un rôle métier compte
        // autant qu'un droit accordé.
        const aRecevoir = affiches.filter(
            item => item.meta && item.meta.detenu === false).length;
        if (aRecevoir) {
            return `<span class="access-column__ajoutes">${Utils.escapeHtml(
                I18n.t('graph.column.to_receive', { count: aRecevoir }))}</span>`;
        }
        if (colonne !== DROIT_COLONNE) return '';
        const concernes = affiches.filter(
            item => GraphView.nouveauxPour(etat, item.id) > 0).length;
        if (!concernes) return '';
        return `<span class="access-column__ajoutes">${Utils.escapeHtml(
            I18n.t('graph.column.would_grant', { count: concernes }))}</span>`;
    },

    /**
     * Marque un élément que la sélection ne détient pas encore.
     *
     * Sélectionner une personne montrait ce qu'elle a. Ce que ses rôles lui
     * donneraient — le rôle applicatif porté par l'un de ses rôles métier, le
     * droit que ce rôle accorde et qu'elle n'a pas — n'apparaissait nulle part,
     * alors que c'est la question d'une revue d'accès.
     *
     * La marque est un mot, pas une couleur : c'est la règle que ce module
     * s'est donnée pour les origines, et elle vaut ici pour la même raison.
     */
    marqueDeReception(item) {
        if (!item.meta || item.meta.detenu !== false) return '';
        return `<span class="access-item__marque">${
            Utils.escapeHtml(I18n.t('graph.item.to_receive'))}</span>`;
    },

    itemBadge(item, colonne, etat) {
        // Le coût d'abord : c'est lui qu'on cherchait et qui manquait. Il
        // n'est pas coloré en rouge — un droit accordé à trois personnes qui
        // ne l'avaient pas corrige peut-être un sous-provisionnement, et c'est
        // au valideur de le dire, pas au graphe.
        if (colonne === DROIT_COLONNE && etat) {
            const nouveaux = GraphView.nouveauxPour(etat, item.id);
            if (nouveaux > 0) {
                // « +3 » seul se lit comme une anomalie, et une synthèse vocale
                // n'en dit que « plus trois ». Le badge porte donc son sens :
                // ce droit n'est pas détenu, la sélection le donnerait.
                return `<span class="access-item__badge access-item__badge--ajoute"
                              data-definition="graph.badge.added_hint"
                              title="${Utils.escapeHtml(I18n.t('graph.badge.added_label', {count: nouveaux}))}"
                              aria-label="${Utils.escapeHtml(I18n.t('graph.badge.added_label', {count: nouveaux}))}"
                              >+${nouveaux}</span>`;
            }
        }
        if (typeof item.meta?.right_count === 'number') {
            return `<span class="access-item__badge">${item.meta.right_count}</span>`;
        }
        return '';
    },

    /** Lignes de détail affichées sous la valeur complète. */
    itemDetails(colonne, item) {
        const lignes = [];
        if (item.meta?.application) {
            lignes.push([I18n.t('graph.tooltip.application'), item.meta.application]);
        }
        if (item.meta?.role_type) {
            lignes.push([I18n.t('graph.role_type'), item.meta.role_type]);
        }
        if (typeof item.meta?.right_count === 'number') {
            lignes.push([I18n.t('graph.tooltip.right_count'), item.meta.right_count]);
        }
        if (typeof item.meta?.user_count === 'number') {
            lignes.push([I18n.t('graph.tooltip.user_count'), item.meta.user_count]);
        }
        if (item.meta?.socle) {
            // La valeur dit la conséquence, pas « oui » : c'est parce qu'il
            // est exclu du mining qu'aucun rôle ne l'explique.
            lignes.push([I18n.t('graph.tooltip.birth_right'),
                         I18n.t('graph.tooltip.birth_right_excluded')]);
        }
        // Les deux moitiés de l'arbitrage, côte à côte : qui l'a déjà, qui le
        // recevrait. Leur somme est l'effectif du rôle.
        const etat = GraphView.state[colonne];
        if (colonne === DROIT_COLONNE && etat) {
            const detenteurs = (etat.links || []).reduce((somme, lien) => (
                lien.to === item.id && typeof lien.meta?.detenteurs === 'number'
                    ? somme + lien.meta.detenteurs
                    : somme
            ), 0);
            const nouveaux = GraphView.nouveauxPour(etat, item.id);
            if (detenteurs || nouveaux) {
                lignes.push([I18n.t('graph.tooltip.already_held'), detenteurs]);
                lignes.push([I18n.t('graph.tooltip.would_receive'), nouveaux]);
            }
        }
        return lignes;
    },

    /** Infobulle unique, réutilisée d'un survol à l'autre. */
    tooltipElement() {
        let bulle = document.getElementById('graph-tooltip');
        if (!bulle) {
            bulle = document.createElement('div');
            bulle.id = 'graph-tooltip';
            bulle.className = 'access-tooltip';
            bulle.setAttribute('role', 'tooltip');
            document.body.appendChild(bulle);
        }
        return bulle;
    },

    /** Tableau des attributs d'une identité, tels qu'ils sont dans le fichier. */
    attributeTable(item) {
        const attributs = item.meta?.attributes;
        if (!attributs || !attributs.length) return '';

        const lignes = attributs.map(attribut => {
            const renseigne = attribut.value !== null && attribut.value !== undefined
                && String(attribut.value).length > 0;
            return `
                <tr>
                    <th scope="row">${Utils.escapeHtml(attribut.name)}</th>
                    <td class="${renseigne ? '' : 'access-tooltip__empty'}">${
                        renseigne ? Utils.escapeHtml(String(attribut.value))
                                  : Utils.escapeHtml(I18n.t('common.not_provided'))}</td>
                </tr>`;
        }).join('');

        return `<table class="access-tooltip__table"><tbody>${lignes}</tbody></table>`;
    },

    showTooltip(event, colonne, item) {
        if (!item) return;
        const bulle = GraphView.tooltipElement();
        const details = GraphView.itemDetails(colonne, item).map(([cle, valeur]) => `
            <div class="access-tooltip__line">
                <span class="access-tooltip__key">${Utils.escapeHtml(cle)}</span>
                <span class="access-tooltip__value">${Utils.escapeHtml(String(valeur))}</span>
            </div>`).join('');

        bulle.innerHTML = `
            <div class="access-tooltip__column">${Utils.escapeHtml(I18n.t(`graph.column.${colonne}`))}</div>
            <div class="access-tooltip__label">${Utils.escapeHtml(item.label)}</div>
            ${details}
            ${GraphView.attributeTable(item)}`;
        bulle.classList.add('access-tooltip--visible');
        GraphView.moveTooltip(event);
    },

    moveTooltip(event) {
        const bulle = document.getElementById('graph-tooltip');
        if (!bulle || !bulle.classList.contains('access-tooltip--visible')) return;

        const marge = 14;
        const boite = bulle.getBoundingClientRect();
        // Bascule à gauche ou au-dessus du curseur quand le bord de la fenêtre
        // est proche : une infobulle qui déborde ne se lit pas.
        const x = event.clientX + marge + boite.width > window.innerWidth
            ? event.clientX - marge - boite.width
            : event.clientX + marge;
        const y = event.clientY + marge + boite.height > window.innerHeight
            ? event.clientY - marge - boite.height
            : event.clientY + marge;

        bulle.style.left = `${Math.max(marge / 2, x)}px`;
        bulle.style.top = `${Math.max(marge / 2, y)}px`;
    },

    hideTooltip() {
        const bulle = document.getElementById('graph-tooltip');
        if (bulle) bulle.classList.remove('access-tooltip--visible');
    },

    // ------------------------------------------------------- chargement

    async loadColumn(colonne, { append = false } = {}) {
        const etat = GraphView.state[colonne];
        const pilote = GraphView.driver;

        const params = {
            layer: colonne,
            limit: GraphView.pageSize,
            offset: append ? etat.offset + etat.items.length : 0,
        };
        if (etat.search) params.search = etat.search;
        const origines = GraphView.originesDemandees();
        if (origines.length) params.origins = origines.join(',');
        if (colonne === 'right' && GraphView.droitsNonCouverts) {
            params.uncovered_only = true;
        }
        if (pilote && pilote !== colonne && GraphView.state[pilote].selection.size) {
            params.parent_layer = pilote;
            params.parents = [...GraphView.state[pilote].selection];
        }

        try {
            const reponse = await API.client.get('/graph/layer', params);
            etat.items = append ? [...etat.items, ...reponse.items] : reponse.items;
            etat.links = append ? [...etat.links, ...reponse.links] : reponse.links;
            etat.total = reponse.total;
            etat.offset = append ? etat.offset : reponse.offset;
            etat.loaded = true;
        } catch (error) {
            Object.assign(etat, { items: [], links: [], total: 0, loaded: true });
            Toast.error(I18n.t('common.error'), error.message);
        }
        GraphView.renderColumn(colonne);
    },

    loadMore(colonne) {
        return GraphView.loadColumn(colonne, { append: true });
    },

    /** Recharge toutes les colonnes autres que celle qui pilote. */
    async refresh() {
        const pilote = GraphView.driver;
        const cibles = pilote
            ? GraphView.columns.filter(c => c !== pilote)
            : [GraphView.columns[0]];

        if (!pilote) {
            // Sans sélection, seule la première colonne est peuplée : les
            // autres attendent un choix plutôt que de déverser le référentiel.
            GraphView.columns.slice(1).forEach(colonne => {
                Object.assign(GraphView.state[colonne],
                    { items: [], links: [], total: 0, offset: 0, loaded: false });
                GraphView.renderColumn(colonne);
            });
        }

        await Promise.all(cibles.map(c => GraphView.loadColumn(c)));
        GraphView.drawLinks();
    },

    // ------------------------------------------------------- interactions

    /** Un clic dans une colonne fait d'elle le pilote de toutes les autres. */
    async toggle(colonne, identifiant) {
        const etat = GraphView.state[colonne];

        if (GraphView.driver !== colonne) {
            GraphView.columns.forEach(c => {
                if (c !== colonne) GraphView.state[c].selection.clear();
            });
            GraphView.driver = colonne;
        }

        if (etat.selection.has(identifiant)) etat.selection.delete(identifiant);
        else etat.selection.add(identifiant);

        if (!etat.selection.size) GraphView.driver = null;

        GraphView.syncPickers();
        GraphView.renderColumn(colonne);
        GraphView.refreshDifferee();
    },

    /**
     * Recharge catalogues et colonnes après un changement de filtre.
     *
     * Les listes déroulantes viennent du même point d'entrée que les
     * colonnes : ne recharger que ces dernières laisserait un catalogue
     * proposant des rôles que le graphe ne montre plus.
     */
    async rechargerTout() {
        await Promise.all(GraphView.columns.map(c => GraphView.loadCatalog(c)));
        GraphView.elaguerSelections();

        // La colonne pilote n'est pas rechargée par `refresh` : c'est elle qui
        // pilote les autres. Elle affiche pourtant l'élément choisi, dont
        // l'origine vient peut-être d'être décochée — il faut la redessiner.
        const pilote = GraphView.driver;
        if (pilote) GraphView.repositionnerPilote(pilote);
        await GraphView.refresh();
    },

    /**
     * Retire des sélections ce que les origines cochées ne montrent plus.
     *
     * Sans cela, décocher « validés » laissait à l'écran le rôle validé
     * sélectionné, et le graphe entier restait filtré par lui : on croyait
     * regarder les seules suggestions en regardant celles d'un rôle qu'on
     * venait de masquer.
     *
     * L'élagage ne s'applique qu'aux catalogues complets : tronqué, un
     * catalogue ne prouve pas l'absence d'un identifiant.
     */
    elaguerSelections() {
        GraphView.columns.forEach(colonne => {
            const etat = GraphView.state[colonne];
            if (GraphView.SEARCHABLE.includes(colonne)) return;
            if (etat.catalogTotal > etat.catalog.length) return;

            const connus = new Set(etat.catalog.map(item => item.id));
            [...etat.selection].forEach(identifiant => {
                if (!connus.has(identifiant)) etat.selection.delete(identifiant);
            });
        });

        if (GraphView.driver && !GraphView.state[GraphView.driver].selection.size) {
            GraphView.driver = null;
        }
        GraphView.syncPickers();
    },

    /** Réaffiche la colonne pilote à partir du catalogue rechargé. */
    repositionnerPilote(colonne) {
        const etat = GraphView.state[colonne];
        if (GraphView.SEARCHABLE.includes(colonne)) return;
        etat.items = etat.catalog.filter(item => etat.selection.has(item.id));
        etat.total = etat.items.length;
        etat.offset = 0;
        etat.loaded = true;
        GraphView.renderColumn(colonne);
    },

    /**
     * Regroupe les rafraîchissements rapprochés en un seul.
     *
     * Chaque sélection interroge les quatre autres colonnes. Trois clics
     * enchaînés produisaient douze requêtes, dont les deux premières séries
     * étaient déjà obsolètes en arrivant — et suffisaient à faire refuser la
     * troisième par le limiteur de débit. On ne lance que la dernière.
     */
    refreshDifferee() {
        clearTimeout(GraphView._minuterieRefresh);
        GraphView._minuterieRefresh = setTimeout(() => {
            GraphView.refresh();
        }, 250);
    },

    _minuterieRefresh: null,

    /** Choix dans une liste déroulante : équivaut à sélectionner l'élément. */
    async onPick(colonne, identifiant) {
        const etat = GraphView.state[colonne];
        GraphView.columns.forEach(c => GraphView.state[c].selection.clear());

        if (!identifiant) {
            GraphView.driver = null;
            await GraphView.refresh();
            GraphView.renderColumn(colonne);
            return;
        }

        etat.selection.add(identifiant);
        GraphView.driver = colonne;
        GraphView.syncPickers(colonne);

        // La colonne pilote doit montrer l'élément choisi, même s'il ne
        // figurait pas dans la page affichée.
        etat.items = etat.catalog.filter(item => item.id === identifiant);
        etat.links = [];
        etat.total = etat.items.length;
        etat.offset = 0;
        etat.loaded = true;
        GraphView.renderColumn(colonne);

        await GraphView.refresh();
    },

    onSearch(colonne, valeur) {
        GraphView.state[colonne].search = valeur.trim();
        GraphView.loadColumn(colonne);
    },

    /** Remet les listes déroulantes en cohérence avec les sélections. */
    syncPickers(sauf = null) {
        GraphView.columns.forEach(colonne => {
            if (colonne === sauf || GraphView.SEARCHABLE.includes(colonne)) return;
            const liste = document.querySelector(`select[data-picker="${colonne}"]`);
            if (!liste) return;
            const selection = [...GraphView.state[colonne].selection];
            liste.value = selection.length === 1 ? selection[0] : '';
        });
    },

    async clear() {
        GraphView.driver = null;
        GraphView.columns.forEach(colonne => {
            GraphView.state[colonne].selection.clear();
            GraphView.state[colonne].search = '';
        });
        document.querySelectorAll('.access-column__picker').forEach(controle => {
            controle.value = '';
        });
        await GraphView.refresh();
    },

    // ---------------------------------------------------- connecteurs

    /** Trace les liaisons entre colonnes, d'après les positions réelles. */
    drawLinks() {
        const svg = document.getElementById('graph-links');
        const planche = document.querySelector('.access-graph__board');
        if (!svg || !planche) return;

        const repere = planche.getBoundingClientRect();
        svg.setAttribute('viewBox', `0 0 ${repere.width} ${repere.height}`);
        svg.setAttribute('width', repere.width);
        svg.setAttribute('height', repere.height);

        const pilote = GraphView.driver;
        if (!pilote) { svg.innerHTML = ''; return; }

        const indexPilote = GraphView.columns.indexOf(pilote);

        const ancrage = (colonne, identifiant, cote) => {
            const element = document.querySelector(
                `.access-item[data-column="${colonne}"][data-id="${CSS.escape(identifiant)}"]`);
            if (!element) return null;
            const boite = element.getBoundingClientRect();
            return {
                x: (cote === 'right' ? boite.right : boite.left) - repere.left,
                y: boite.top + boite.height / 2 - repere.top,
            };
        };

        const chemins = [];
        GraphView.columns.forEach((colonne, index) => {
            if (colonne === pilote) return;
            // Le pilote est à gauche ou à droite de la cible : le connecteur
            // part du bord tourné vers elle.
            const aDroite = index > indexPilote;
            GraphView.state[colonne].links.forEach(lien => {
                const depart = ancrage(pilote, lien.from, aDroite ? 'right' : 'left');
                const arrivee = ancrage(colonne, lien.to, aDroite ? 'left' : 'right');
                if (!depart || !arrivee) return;
                const milieu = (depart.x + arrivee.x) / 2;
                chemins.push(`<path d="M ${depart.x} ${depart.y} C ${milieu} ${depart.y}, ` +
                             `${milieu} ${arrivee.y}, ${arrivee.x} ${arrivee.y}" />`);
            });
        });

        svg.innerHTML = chemins.join('');
    },
};

window.GraphView = GraphView;
