/**
 * Export du modèle de rôles.
 *
 * Le produit savait montrer le modèle, jamais le sortir — alors que c'est le
 * livrable qu'on présente en comité de gouvernance.
 *
 * Les critères de filtrage **viennent du serveur**, qui les lit dans les
 * fichiers du client. Écrire ici « Fonction » ou « Département » aurait
 * proposé de filtrer sur des colonnes qu'un référentiel donné ne possède pas :
 * les colonnes ne sont pas connues à l'avance.
 *
 * Les valeurs affichées dans les listes sont celles des données : elles ne
 * passent pas par i18n. Traduire `jobtitle` afficherait autre chose que ce que
 * le fichier contient.
 *
 * Les identifiants HTML sont préfixés `export-modele-` : `export-applications`
 * désigne déjà un bouton de la page des applications, et `getElementById`
 * aurait rendu celui-là — un écran pilotant silencieusement les contrôles d'un
 * autre.
 */

const ExportModelePage = {
    filtres: null,
    // Les deux premiers jeux sont remplis par le serveur au chargement : lui
    // seul sait quels types et quelles origines existent. Écrits ici, ils
    // avaient déjà pris du retard — le socle est un type de rôle, et il serait
    // sorti décoché d'un écran qui ne le connaissait pas, donc absent de
    // l'export sans que personne ne l'ait demandé.
    etat: {
        origins: new Set(),
        role_types: new Set(),
        applications: new Set(),
        attribute: '',
        attribute_values: new Set(),
        identities: '',
    },

    async init() {
        const conteneur = document.getElementById('export-filtres');
        if (!conteneur) return;

        conteneur.innerHTML = `<div class="export-chargement">
                <i class="fas fa-circle-notch fa-spin" aria-hidden="true"></i>
                <span>${Utils.escapeHtml(I18n.t('common.loading'))}</span>
            </div>`;

        try {
            ExportModelePage.filtres = await API.get('/export/modele/filtres');
        } catch (erreur) {
            conteneur.innerHTML = `<div class="alert alert-danger">${
                Utils.escapeHtml(erreur.message)}</div>`;
            return;
        }

        // Tout est coché d'abord : un écran d'export s'ouvre sur le modèle
        // entier, et on retranche. L'inverse — ouvrir sur rien — se lit comme
        // un modèle vide.
        if (!ExportModelePage.etat.origins.size) {
            ExportModelePage.etat.origins = new Set(ExportModelePage.filtres.origins);
        }
        if (!ExportModelePage.etat.role_types.size) {
            ExportModelePage.etat.role_types = new Set(ExportModelePage.filtres.role_types);
        }

        ExportModelePage.render();
        ExportModelePage.brancher();
        ExportModelePage.chargerApercu();
    },

    /** Réaffiche les filtres et l'extrait dans la langue courante. */
    rafraichirLangue() {
        if (!ExportModelePage.filtres) return;
        ExportModelePage.render();
        ExportModelePage.brancher();
        ExportModelePage.chargerApercu();
    },

    _cases(nom, valeurs, choisies, traduire) {
        return valeurs.map(valeur => `
            <label class="export-case">
                <input type="checkbox" data-groupe="${nom}"
                       value="${Utils.escapeHtml(valeur)}"
                       ${choisies.has(valeur) ? 'checked' : ''}>
                <span>${Utils.escapeHtml(traduire ? I18n.t(traduire + valeur) : valeur)}</span>
            </label>`).join('');
    },

    render() {
        const conteneur = document.getElementById('export-filtres');
        const filtres = ExportModelePage.filtres;
        const etat = ExportModelePage.etat;

        const attribut = filtres.attributes.find(a => a.name === etat.attribute);

        conteneur.innerHTML = `
            <div class="export-groupe">
                <h3>${Utils.escapeHtml(I18n.t('export.filter.origins'))}</h3>
                <div class="export-cases">${ExportModelePage._cases(
                    'origins', filtres.origins, etat.origins, 'graph.origin.')}</div>
            </div>

            <div class="export-groupe">
                <h3>${Utils.escapeHtml(I18n.t('export.filter.role_types'))}</h3>
                <div class="export-cases">${ExportModelePage._cases(
                    'role_types', filtres.role_types, etat.role_types,
                    'export.role_type.')}</div>
            </div>

            <div class="export-groupe">
                <h3>${Utils.escapeHtml(I18n.t('export.filter.applications'))}</h3>
                <p class="export-aide">${Utils.escapeHtml(
                    I18n.t('export.all_applications'))}</p>
                <select multiple size="6" class="form-select" id="export-modele-applications">
                    ${filtres.applications.map(a => `
                        <option value="${Utils.escapeHtml(a)}"${
                            etat.applications.has(a) ? ' selected' : ''
                        }>${Utils.escapeHtml(a)}</option>`).join('')}
                </select>
            </div>

            <div class="export-groupe">
                <h3>${Utils.escapeHtml(I18n.t('export.filter.attribute'))}</h3>
                <select class="form-select" id="export-modele-attribut">
                    <option value="">${Utils.escapeHtml(I18n.t('export.no_attribute'))}</option>
                    ${filtres.attributes.map(a => `
                        <option value="${Utils.escapeHtml(a.name)}"${
                            a.name === etat.attribute ? ' selected' : ''
                        }>${Utils.escapeHtml(a.name)}</option>`).join('')}
                </select>
                ${attribut ? `
                    <label class="export-aide" for="export-modele-valeurs">${
                        Utils.escapeHtml(I18n.t('export.attribute_values'))}</label>
                    <select multiple size="6" class="form-select" id="export-modele-valeurs">
                        ${attribut.values.map(v => `
                            <option value="${Utils.escapeHtml(v)}"${
                                etat.attribute_values.has(v) ? ' selected' : ''
                            }>${Utils.escapeHtml(v)}</option>`).join('')}
                    </select>` : ''}
            </div>

            <div class="export-groupe">
                <h3>${Utils.escapeHtml(I18n.t('export.filter.identities'))}</h3>
                <input type="text" class="form-input" id="export-modele-identites"
                       value="${Utils.escapeHtml(etat.identities)}"
                       placeholder="U0001, U0002">
            </div>`;
    },

    brancher() {
        const conteneur = document.getElementById('export-filtres');

        conteneur.addEventListener('change', (evenement) => {
            const cible = evenement.target;
            const etat = ExportModelePage.etat;

            if (cible.dataset.groupe) {
                const ensemble = etat[cible.dataset.groupe];
                if (cible.checked) ensemble.add(cible.value);
                else ensemble.delete(cible.value);
                ExportModelePage.rafraichirApercu();
                return;
            }

            if (cible.id === 'export-modele-applications') {
                etat.applications = new Set(
                    [...cible.selectedOptions].map(o => o.value));
                ExportModelePage.rafraichirApercu();
                return;
            }

            if (cible.id === 'export-modele-attribut') {
                etat.attribute = cible.value;
                // Changer d'attribut vide les valeurs retenues : conservées,
                // elles filtreraient sur des valeurs d'une autre colonne, et
                // l'extrait sortirait vide sans qu'on comprenne pourquoi.
                etat.attribute_values = new Set();
                ExportModelePage.render();
                ExportModelePage.rafraichirApercu();
                return;
            }

            if (cible.id === 'export-modele-valeurs') {
                etat.attribute_values = new Set(
                    [...cible.selectedOptions].map(o => o.value));
                ExportModelePage.rafraichirApercu();
            }
        });

        conteneur.addEventListener('input', (evenement) => {
            if (evenement.target.id === 'export-modele-identites') {
                ExportModelePage.etat.identities = evenement.target.value;
                ExportModelePage.rafraichirApercu();
            }
        });

        const excel = document.getElementById('export-modele-excel');
        const pdf = document.getElementById('export-modele-pdf');
        if (excel) excel.addEventListener('click', () => ExportModelePage.telecharger('excel', 'xlsx'));
        if (pdf) pdf.addEventListener('click', () => ExportModelePage.telecharger('pdf', 'pdf'));
    },

    /**
     * Aperçu de ce que l'extrait contiendra.
     *
     * Un filtre trop étroit produit un document vide, et sans aperçu on ne le
     * découvre qu'en l'ouvrant. Les compteurs viennent de l'assemblage réel :
     * une estimation qui ne correspondrait pas au fichier serait pire que pas
     * d'aperçu du tout.
     *
     * Les frappes rapprochées dans le champ des identités sont regroupées :
     * une requête par caractère saturerait le limiteur de débit.
     */
    rafraichirApercu() {
        clearTimeout(ExportModelePage._minuterie);
        ExportModelePage._minuterie = setTimeout(
            () => ExportModelePage.chargerApercu(), 300);
    },

    _minuterie: null,

    async chargerApercu() {
        const zone = document.getElementById('export-apercu');
        if (!zone) return;

        const parametres = ExportModelePage.parametres();
        parametres.delete('langue');

        try {
            const apercu = await API.get(`/export/modele/apercu?${parametres}`);
            ExportModelePage.rendreApercu(zone, apercu);
        } catch (erreur) {
            zone.innerHTML = `<span class="export-apercu__erreur">${
                Utils.escapeHtml(erreur.message)}</span>`;
        }
    },

    rendreApercu(zone, apercu) {
        // Un extrait vide se dit avant le téléchargement, pas après.
        if (!apercu.roles) {
            zone.innerHTML = `<span class="export-apercu__vide">
                    <i class="fas fa-triangle-exclamation" aria-hidden="true"></i>
                    ${Utils.escapeHtml(I18n.t('export.preview_empty'))}
                </span>`;
            ExportModelePage.activerBoutons(false);
            return;
        }

        const tuile = (cle, valeur) => `
            <span class="export-apercu__tuile">
                <strong>${Utils.escapeHtml(String(valeur))}</strong>
                ${Utils.escapeHtml(I18n.t(cle))}
            </span>`;

        const ecartes = apercu.filtered_members
            ? `<span class="export-apercu__note">${Utils.escapeHtml(
                   I18n.t('export.preview_filtered_members',
                          { count: apercu.filtered_members }))}</span>`
            : '';

        zone.innerHTML = tuile('export.scope.total_roles', apercu.roles)
            + tuile('export.scope.total_rights', apercu.rights)
            + tuile('export.scope.total_identities', apercu.identities)
            + ecartes;
        ExportModelePage.activerBoutons(true);
    },

    activerBoutons(actifs) {
        ['excel', 'pdf'].forEach(format => {
            const bouton = document.getElementById(`export-modele-${format}`);
            if (bouton) bouton.disabled = !actifs;
        });
    },

    /** Paramètres de requête, dans l'ordre des filtres de l'écran. */
    parametres() {
        const etat = ExportModelePage.etat;
        const parametres = new URLSearchParams();

        parametres.set('langue', (typeof I18n !== 'undefined' && I18n.currentLocale) || 'fr');
        if (etat.origins.size) parametres.set('origins', [...etat.origins].join(','));
        if (etat.role_types.size) parametres.set('role_types', [...etat.role_types].join(','));
        if (etat.applications.size) {
            parametres.set('applications', [...etat.applications].join(','));
        }
        if (etat.attribute && etat.attribute_values.size) {
            parametres.set('attribute', etat.attribute);
            parametres.set('attribute_values', [...etat.attribute_values].join(','));
        }
        const identites = etat.identities.split(',').map(v => v.trim()).filter(Boolean);
        if (identites.length) parametres.set('identities', identites.join(','));

        return parametres;
    },

    async telecharger(format, extension) {
        const bouton = document.getElementById(`export-modele-${format}`);
        const initial = bouton ? bouton.innerHTML : '';
        if (bouton) {
            bouton.disabled = true;
            bouton.innerHTML = `<i class="fas fa-circle-notch fa-spin" aria-hidden="true"></i> ${
                Utils.escapeHtml(I18n.t('export.started'))}`;
        }

        try {
            const reponse = await fetch(
                `${Config.API_URL}/export/modele/${format}?${ExportModelePage.parametres()}`,
                {
                    headers: {
                        ...(typeof Auth !== 'undefined' ? Auth.getAuthHeaders() : {}),
                        'X-Workspace-Info': JSON.stringify(
                            ExportModelePage.contexteWorkspace()),
                    },
                });

            if (!reponse.ok) {
                // Le serveur nomme la cause — une origine inconnue, par
                // exemple. La perdre afficherait le même message pour tout.
                throw new Error(await ExportModelePage.messageDErreur(reponse));
            }

            // Le nom du fichier est celui que le serveur annonce : lui seul
            // connaît le nom du produit et l'horodatage retenus.
            await Utils.enregistrerReponse(reponse, `kovex_modele_roles.${extension}`);
            Toast.success(I18n.t('export.done'), I18n.t('export.title'));
        } catch (erreur) {
            Toast.error(I18n.t('common.error'), erreur.message || I18n.t('export.failed'));
        } finally {
            if (bouton) {
                bouton.disabled = false;
                bouton.innerHTML = initial;
            }
        }
    },

    contexteWorkspace() {
        if (typeof WorkspaceManager === 'undefined' || !WorkspaceManager.currentWorkspace) {
            return {};
        }
        const actif = WorkspaceManager.currentWorkspace;
        return {
            name: actif.name || '',
            client: actif.client || '',
            environment: actif.environment || '',
        };
    },

    async messageDErreur(reponse) {
        try {
            const charge = await reponse.json();
            const detail = charge && charge.detail;
            if (detail && typeof detail === 'object' && detail.code) {
                return I18n.t(detail.code, detail.params || {});
            }
        } catch (erreur) {
            // Réponse non JSON : on retombe sur le code HTTP.
        }
        return I18n.t('error.http_status', { status: reponse.status });
    },
};

window.ExportModelePage = ExportModelePage;
