/**
 * Le panneau d'une identité : ce que le produit constate sur elle, rassemblé.
 *
 * Il s'ouvre dans la fenêtre de détail d'une identité, au-dessus de ses
 * droits. Chaque constat garde son chiffre et sa définition ; aucun n'est
 * additionné aux autres. Un score dirait « 73 » et ne dirait pas quoi retirer.
 *
 * Chaque section dit aussi quand elle n'a pas pu être établie : sans colonne
 * de pairs choisie, sans marqueur de comptes à privilèges, sans règle de
 * séparation, sans rôle validé. Une section vide se lirait « rien à signaler »,
 * et ce serait faux.
 *
 * La colonne de pairs n'a pas de valeur par défaut. Une fois choisie, elle est
 * conservée pour les identités ouvertes ensuite : on compare une population,
 * pas une personne à la fois.
 */
const ConstatsIdentite = {
    //: Les colonnes d'identités proposées comme groupe de pairs.
    attributs: [],
    attributsCharges: false,
    //: La colonne retenue, gardée d'une identité à l'autre.
    attribut: '',
    identite: null,
    rendu: null,
    //: La dernière demande : une réponse dépassée ne remplace pas la bonne.
    jeton: 0,
    branche: false,

    brancher() {
        if (this.branche) return;
        this.branche = true;
        const choix = document.getElementById('identite-constats-pairs');
        if (choix) {
            choix.addEventListener('change', () => {
                this.attribut = choix.value;
                this.charger();
            });
        }
        const corps = document.getElementById('identite-constats-corps');
        if (corps) {
            corps.addEventListener('click', (evenement) => this.cliquer(evenement));
            corps.addEventListener('input', (evenement) => {
                const cible = evenement.target;
                if (this.saisie && cible.dataset.justification) {
                    this.saisie[cible.dataset.justification] = cible.value;
                } else if (this.refus && cible.dataset.refusMotif) {
                    this.refus.motif = cible.value;
                }
            });
        }
    },

    // -- justifier un écart ------------------------------------------------

    //: Le droit dont la justification est en cours de saisie, et ce qui a été
    //  saisi. Un seul à la fois : dix formulaires ouverts ne se relisent pas.
    saisie: null,
    //: Les bornes des dérogations et les contrôles du workspace, lus à la
    //  première justification : l'échéance se borne avant la saisie.
    bornes: null,
    controles: [],
    //: La dérogation dont le refus est en cours de saisie.
    refus: null,

    cliquer(evenement) {
        const bouton = evenement.target.closest('button');
        if (!bouton) return;
        const donnees = bouton.dataset;
        if (donnees.justifier) this.ouvrirLaJustification(donnees.justifier);
        else if (donnees.justifierAnnuler) this.fermerLaJustification();
        else if (donnees.justifierValider) this.justifier();
        else if (donnees.ecartApprouver) this.trancher(donnees.ecartApprouver, true);
        else if (donnees.ecartRefuser) {
            this.refus = {id: donnees.ecartRefuser, motif: ''};
            this.renderLeCorps();
        } else if (donnees.ecartConfirmerRefus) this.trancher(donnees.ecartConfirmerRefus, false);
    },

    async ouvrirLaJustification(droit) {
        if (!this.bornes) {
            try {
                this.bornes = await API.get('/derogations');
                this.controles = (await API.get('/controles')).controles || [];
            } catch (erreur) {
                this.bornes = null;
                Toast.error(I18n.t('common.error'), erreur.message);
                return;
            }
        }
        this.saisie = {droit, motif: '', echeance: '', controle: ''};
        this.renderLeCorps();
        document.getElementById('identite-justification-motif')?.focus();
    },

    fermerLaJustification() {
        this.saisie = null;
        this.renderLeCorps();
    },

    async justifier() {
        const saisie = this.saisie;
        try {
            await API.post('/derogations', {
                famille: 'ecart_au_pair',
                cible: {identite: this.identite, droit: saisie.droit},
                motif: saisie.motif, echeance: saisie.echeance,
                controle: saisie.controle,
            });
        } catch (erreur) {
            Toast.error(I18n.t('common.error'), erreur.message);
            return;
        }
        this.saisie = null;
        Toast.success(I18n.t('common.success'), I18n.t('ecart.justification_enregistree'));
        await this.charger();
    },

    async trancher(identifiant, accorder) {
        try {
            if (accorder) {
                await API.post(`/derogations/${encodeURIComponent(identifiant)}/approuver`, {});
            } else {
                await API.post(`/derogations/${encodeURIComponent(identifiant)}/refuser`,
                               {motif: this.refus.motif});
            }
        } catch (erreur) {
            Toast.error(I18n.t('common.error'), erreur.message);
            return;
        }
        this.refus = null;
        await this.charger();
    },

    echeanceMaximale() {
        const bornes = this.bornes;
        const limite = new Date(`${bornes.aujourdhui}T00:00:00Z`);
        limite.setUTCDate(limite.getUTCDate() + Number(bornes.duree_max_jours));
        return limite.toISOString().slice(0, 10);
    },

    async afficher(identite) {
        this.brancher();
        this.identite = identite;
        this.rendu = null;
        this.saisie = null;
        this.refus = null;
        const section = document.getElementById('identite-constats');
        if (section) section.hidden = false;
        this.renderLeCorps();
        await this.chargerLesAttributs();
        await this.charger();
    },

    masquer() {
        this.identite = null;
        this.rendu = null;
        const section = document.getElementById('identite-constats');
        if (section) section.hidden = true;
    },

    rafraichirLangue() {
        this.renderLesAttributs();
        this.renderLeCorps();
    },

    /** Les mêmes colonnes que l'écran des droits conservés, par la même route. */
    async chargerLesAttributs() {
        if (this.attributsCharges) return;
        try {
            const rendu = await API.get('/mining-metiers/attributes/identity/business');
            this.attributs = rendu.attributes || [];
            this.attributsCharges = true;
        } catch (erreur) {
            this.attributs = [];
        }
        this.renderLesAttributs();
    },

    renderLesAttributs() {
        const choix = document.getElementById('identite-constats-pairs');
        if (!choix) return;
        choix.innerHTML = `<option value="">${Utils.escapeHtml(
            I18n.t('mouvement.attribut.none'))}</option>`
            + this.attributs.map((attribut) => `<option value="${
                Utils.escapeHtml(attribut.name)}">${Utils.escapeHtml(attribut.name)}</option>`).join('');
        choix.value = this.attributs.some((un) => un.name === this.attribut) ? this.attribut : '';
    },

    async charger() {
        if (this.identite === null) return;
        const jeton = (this.jeton += 1);
        const identite = this.identite;
        const parametres = this.attribut ? {attribut_pairs: this.attribut} : {};
        let rendu;
        try {
            rendu = await API.get(`/identites/${encodeURIComponent(identite)}/constats`,
                                  parametres);
        } catch (erreur) {
            if (jeton !== this.jeton) return;
            this.rendu = {erreur: erreur.message};
            this.renderLeCorps();
            return;
        }
        if (jeton !== this.jeton) return;
        this.rendu = rendu;
        this.renderLeCorps();
    },

    renderLeCorps() {
        const corps = document.getElementById('identite-constats-corps');
        if (!corps) return;
        const rendu = this.rendu;
        if (!rendu) {
            corps.innerHTML = `<p class="form-hint">${Utils.escapeHtml(I18n.t('common.loading'))}</p>`;
            return;
        }
        if (rendu.erreur !== undefined) {
            corps.innerHTML = `<div class="alert alert-danger" role="alert">${
                Utils.escapeHtml(rendu.erreur)}</div>`;
            return;
        }
        // Une réponse sans panneau — un serveur plus ancien, un bouchon — ne
        // doit pas faire croire à une identité sans constat.
        if (!rendu.referentiel) {
            corps.innerHTML = `<p class="form-hint">${Utils.escapeHtml(
                I18n.t('identite.constats.indisponible'))}</p>`;
            return;
        }
        corps.innerHTML = [
            this.section('referentiel', this.leReferentiel(rendu)),
            this.section('privileges', this.lesPrivileges(rendu.privileges)),
            this.section('separation', this.laSeparation(rendu.separation)),
            this.section('pairs', this.lesPairs(rendu.pairs)),
            this.section('roles', this.lesRoles(rendu)),
            this.section('hors_referentiel', this.leHorsReferentiel(rendu)),
        ].join('');
    },

    section(cle, contenu) {
        return `<section class="identite-constat" data-constat="${cle}">
                <h4>${Utils.escapeHtml(I18n.t(`identite.${cle}.title`))}</h4>${contenu}</section>`;
    },

    phrase(cle, parametres) {
        return `<p>${Utils.escapeHtml(I18n.t(cle, parametres || {}))}</p>`;
    },

    codes(liste) {
        return liste.length
            ? `<p class="identite-constat__codes">${liste.map((code) => `<code>${
                Utils.escapeHtml(code)}</code>`).join(' ')}</p>`
            : '';
    },

    leReferentiel(rendu) {
        const referentiel = rendu.referentiel;
        return [
            referentiel.connue ? '' : this.phrase('identite.referentiel.inconnue'),
            referentiel.hors_perimetre ? this.phrase('identite.referentiel.hors_perimetre') : '',
            this.phrase('identite.referentiel.detenus',
                        {nombre: Utils.formatNumber(referentiel.droits_detenus)}),
        ].join('');
    },

    lesPrivileges(privileges) {
        if (!privileges.declare) return this.phrase('identite.privileges.non_declare');
        if (privileges.colonne_absente) {
            return this.phrase('identite.privileges.colonne_absente', {colonne: privileges.colonne});
        }
        if (privileges.fragments.length) {
            return this.phrase('identite.privileges.marque', {
                colonne: privileges.colonne, fragments: privileges.fragments.join(', ')});
        }
        return this.phrase('identite.privileges.non_marque', {colonne: privileges.colonne});
    },

    laSeparation(separation) {
        if (!separation.regles_applicables) return this.phrase('identite.separation.aucune_regle');
        if (!separation.conflits.length) {
            return this.phrase('identite.separation.aucun',
                               {regles: Utils.formatNumber(separation.regles_applicables)});
        }
        return `<ul class="identite-constat__liste">${separation.conflits.map((conflit) => `
            <li>
                <strong>${Utils.escapeHtml(conflit.libelle)}</strong>${conflit.severite
                    ? ` <span class="badge badge-warning">${Utils.escapeHtml(conflit.severite)}</span>` : ''}
                ${this.phrase('identite.separation.cotes', {
                    gauche: conflit.gauche.join(', '), droite: conflit.droite.join(', ')})}
                ${this.laDecision(conflit)}
            </li>`).join('')}</ul>`;
    },

    laDecision(conflit) {
        if (conflit.derogation) {
            return this.phrase('derogation.until', {echeance: conflit.derogation.echeance});
        }
        if (conflit.derogation_inoperante) {
            return `<ul class="controle__raisons">${(conflit.derogation_inoperante.raisons || [])
                .map((raison) => `<li>${Utils.escapeHtml(I18n.t(`derogation.raison.${raison.code}`,
                                                              raison.params || {}))}</li>`).join('')}</ul>`;
        }
        return this.phrase('identite.separation.a_traiter');
    },

    lesPairs(pairs) {
        if (!pairs.declare) return this.phrase('identite.pairs.non_declare');
        if (!pairs.examinee) {
            return this.phrase('identite.pairs.non_examinee', {
                groupe: pairs.groupe || '—', effectif: Utils.formatNumber(pairs.effectif),
                minimum: Utils.formatNumber(pairs.reglages.groupe_min)});
        }
        const autres = pairs.effectif - 1;
        const resume = this.phrase('identite.pairs.resume', {
            groupe: pairs.groupe, effectif: Utils.formatNumber(pairs.effectif),
            nombre: Utils.formatNumber(pairs.atypiques.length),
            seuil: Utils.formatNumber(pairs.reglages.rarete_max_pct)});
        const residuels = pairs.constats.map((constat) => this.phrase('identite.pairs.residuel', {
            origine: constat.origine, droits: Utils.formatNumber(constat.droits.length),
            part: Utils.formatNumber(constat.part_minimale)})).join('');
        if (!pairs.atypiques.length) return resume;
        return `${resume}${residuels}
            <table class="role-detail-table">
                <thead><tr>
                    <th scope="col">${Utils.escapeHtml(I18n.t('common.rights'))}</th>
                    <th scope="col">${Utils.escapeHtml(I18n.t('identite.pairs.colonne.groupe'))}</th>
                    <th scope="col">${Utils.escapeHtml(I18n.t('identite.pairs.colonne.ailleurs'))}</th>
                    <th scope="col">${Utils.escapeHtml(I18n.t('identite.pairs.colonne.reponse'))}</th>
                </tr></thead>
                <tbody>${pairs.atypiques.map((un) => `<tr>
                    <td>${Utils.escapeHtml(un.droit)}</td>
                    <td>${Utils.escapeHtml(I18n.t('identite.pairs.autres', {
                        autres: Utils.formatNumber(un.autres_du_groupe),
                        total: Utils.formatNumber(autres)}))}</td>
                    <td>${Utils.escapeHtml(un.origine
                        ? I18n.t('identite.pairs.origine', {
                            origine: un.origine, part: Utils.formatNumber(un.part_de_l_origine)})
                        : I18n.t('identite.pairs.nulle_part'))}</td>
                    <td>${this.laReponse(un)}</td>
                </tr>`).join('')}</tbody>
            </table>
            ${this.saisie ? this.leFormulaire() : ''}`;
    },

    /**
     * Ce qui a été répondu à cet écart : une justification qui vaut, une qui
     * ne vaut pas (et pourquoi), ou rien encore. Justifié, le droit reste
     * affiché : un auditeur doit voir ce qui a été assumé.
     */
    laReponse(atypique) {
        if (atypique.derogation) {
            return `<span class="badge badge-success">${Utils.escapeHtml(I18n.t('ecart.justifie'))}</span>
                ${this.phrase('derogation.until', {echeance: atypique.derogation.echeance})}
                <p class="form-hint">${Utils.escapeHtml(atypique.derogation.motif)}</p>`;
        }
        const inoperante = atypique.derogation_inoperante;
        if (inoperante) {
            const enAttente = inoperante.statut === 'demandee';
            return `<span class="badge badge-warning">${Utils.escapeHtml(
                    I18n.t(enAttente ? 'derogation.pending' : 'derogation.inoperative'))}</span>
                <ul class="controle__raisons">${(inoperante.raisons || []).map((raison) => `
                    <li>${Utils.escapeHtml(I18n.t(`derogation.raison.${raison.code}`,
                                                  raison.params || {}))}</li>`).join('')}</ul>
                ${enAttente ? this.laDecisionAttendue(inoperante) : ''}`;
        }
        return `<button type="button" class="btn btn-secondary btn-sm"
                        data-justifier="${Utils.escapeHtml(atypique.droit)}">${
                    Utils.escapeHtml(I18n.t('ecart.justifier'))}</button>`;
    },

    laDecisionAttendue(derogation) {
        const id = Utils.escapeHtml(derogation.id);
        if (this.refus && this.refus.id === derogation.id) {
            return `<div class="sod-acceptation">
                    <label class="form-label" for="identite-refus-motif">${
                        Utils.escapeHtml(I18n.t('derogation.refusal_reason'))}</label>
                    <input type="text" class="form-input" id="identite-refus-motif" maxlength="500"
                           data-refus-motif="1">
                    <button type="button" class="btn btn-danger btn-sm"
                            data-ecart-confirmer-refus="${id}">${
                        Utils.escapeHtml(I18n.t('derogation.refuse'))}</button>
                </div>`;
        }
        return `<button type="button" class="btn btn-primary btn-sm" data-ecart-approuver="${id}">${
                    Utils.escapeHtml(I18n.t('derogation.approve'))}</button>
                <button type="button" class="btn btn-secondary btn-sm" data-ecart-refuser="${id}">${
                    Utils.escapeHtml(I18n.t('derogation.refuse'))}</button>`;
    },

    /**
     * Le motif, l'échéance et, si le workspace en a, le contrôle cité. Ni
     * auteur ni date d'octroi : ils viennent du serveur. L'échéance est bornée
     * à la saisie par la durée maximale du workspace.
     */
    leFormulaire() {
        const saisie = this.saisie;
        const bornes = this.bornes;
        return `<div class="sod-acceptation identite-justification">
                <p><strong>${Utils.escapeHtml(I18n.t('ecart.justifier_le_droit',
                                                      {droit: saisie.droit}))}</strong></p>
                <label class="form-label" for="identite-justification-motif">${
                    Utils.escapeHtml(I18n.t('ecart.motif'))}</label>
                <input type="text" class="form-input" id="identite-justification-motif"
                       maxlength="500" data-justification="motif"
                       value="${Utils.escapeHtml(saisie.motif)}">
                <label class="form-label" for="identite-justification-echeance">${
                    Utils.escapeHtml(I18n.t('derogation.deadline'))}</label>
                <input type="date" class="form-input" id="identite-justification-echeance"
                       data-justification="echeance" value="${Utils.escapeHtml(saisie.echeance)}"
                       min="${Utils.escapeHtml(bornes.aujourdhui)}"
                       max="${Utils.escapeHtml(this.echeanceMaximale())}">
                <span class="form-hint">${Utils.escapeHtml(I18n.t('derogation.deadline.hint',
                                                                  {jours: bornes.duree_max_jours}))}</span>
                <label class="form-label" for="identite-justification-controle">${
                    Utils.escapeHtml(I18n.t('derogation.control'))}</label>
                <select class="form-input" id="identite-justification-controle"
                        data-justification="controle">
                    <option value="">${Utils.escapeHtml(I18n.t('derogation.control.none'))}</option>
                    ${this.controles.map((controle) => `<option value="${Utils.escapeHtml(controle.id)}"
                        ${controle.id === saisie.controle ? 'selected' : ''}>${
                        Utils.escapeHtml(controle.libelle)}</option>`).join('')}
                </select>
                ${bornes.controle_exige ? `<span class="form-hint">${Utils.escapeHtml(
                    I18n.t('derogation.control.required'))}</span>` : ''}
                <div class="form-actions">
                    <button type="button" class="btn btn-primary btn-sm" data-justifier-valider="1">${
                        Utils.escapeHtml(I18n.t('ecart.justifier'))}</button>
                    <button type="button" class="btn btn-secondary btn-sm" data-justifier-annuler="1">${
                        Utils.escapeHtml(I18n.t('action.cancel'))}</button>
                </div>
            </div>`;
    },

    lesRoles(rendu) {
        if (!rendu.roles_valides) return this.phrase('identite.roles.aucun_catalogue');
        const roles = rendu.roles.length
            ? `<ul class="identite-constat__liste">${rendu.roles.map((role) => `<li>
                ${this.phrase('identite.roles.ligne', {
                    nom: role.nom || role.id, droits: Utils.formatNumber(role.droits),
                    manquants: Utils.formatNumber(role.non_detenus.length)})}
                ${this.codes(role.non_detenus)}</li>`).join('')}</ul>`
            : this.phrase('identite.roles.aucun');
        return `${roles}${this.phrase('identite.roles.hors_modele', {
            nombre: Utils.formatNumber(rendu.hors_modele.length)})}${this.codes(rendu.hors_modele)}`;
    },

    leHorsReferentiel(rendu) {
        if (!rendu.referentiel.referentiel_des_droits) {
            return this.phrase('identite.hors_referentiel.sans_referentiel');
        }
        if (!rendu.hors_referentiel.length) return this.phrase('identite.hors_referentiel.aucun');
        return `${this.phrase('identite.hors_referentiel.nombre', {
            nombre: Utils.formatNumber(rendu.hors_referentiel.length)})}${this.codes(rendu.hors_referentiel)}`;
    },
};

window.ConstatsIdentite = ConstatsIdentite;
