/**
 * Séparation des tâches : ce que la même personne ne doit pas pouvoir faire.
 *
 * **Le module sert deux écrans, et leur séparation est la conception.**
 *
 * En prétraitement, *avant le mining* : les règles qu'on déclare, et les couples
 * candidats que les données proposent. Les deux n'ont besoin que des
 * habilitations, et ils servent là où ils empêchent quelque chose — un rôle qui
 * réunit deux pouvoirs incompatibles ne doit pas naître.
 *
 * En gouvernance, *après* : les conflits constatés sur la population. C'est un
 * constat d'audit ; il se recalcule à chaque chargement et il y reste.
 *
 * **Une règle ne nomme pas des droits, elle nomme des pouvoirs.** Un côté est
 * une liste de références typées — un droit, une application, un rôle du
 * catalogue — choisies dans le référentiel et non saisies de mémoire. Ce n'est
 * pas une commodité : une règle qui nomme une application se réévalue, une
 * règle qui énumère des droits se périme.
 *
 * Rien ne s'enregistre tout seul. Les règles vivent en mémoire jusqu'à ce que
 * quelqu'un clique sur Enregistrer — c'est une décision de gouvernance, elle
 * ne se prend pas par effet de bord d'un clic sur une proposition.
 */

const SeparationPage = {
    //: Résultats rendus par une recherche. Une liste plus longue ne se relit
    //  pas, et on affine plutôt que de faire défiler.
    RESULTATS_MAX: 25,
    //: Longueur du libellé composé des colonnes du client. Au-delà, la pastille
    //  déborde et le tableau devient illisible.
    LIBELLE_MAX: 120,
    //: Délai de frappe avant d'interroger le serveur. Une requête par caractère
    //  le saturerait pour des résultats que personne ne lit.
    FRAPPE_MS: 250,

    //: Les règles telles qu'elles sont à l'écran, enregistrées ou non.
    regles: [],
    //: La synthèse rendue par le serveur, règle par règle.
    conflits: null,
    //: Les couples proposés, en attente d'être retenus.
    candidats: [],
    //: Règle dont le détail est ouvert. Une seule à la fois : ouvrir les
    //  douze ferait descendre l'écran sur des milliers de lignes.
    ouverte: '',

    //: Le sélecteur ouvert : sur quelle règle, quel côté, quel type, et ce que
    //  la recherche a rendu. Un seul à la fois — douze listes de résultats
    //  ouvertes en même temps ne se lisent pas.
    selecteur: null,
    //: Le chronomètre de la frappe. Une requête par caractère saturerait le
    //  serveur pour des résultats que personne ne lit.
    frappe: null,

    /** L'écran de déclaration, en prétraitement. */
    async init() {
        this.brancher();
        await this.charger();
    },

    /**
     * L'écran des conflits, en gouvernance.
     *
     * Il ne charge pas les règles ni les candidats : ce ne sont pas ses
     * données, et les relire ici ferait deux requêtes pour un écran qui n'en
     * montre rien.
     */
    async initConflits() {
        this.brancherLesConflits();
        await this.chargerLesConflits();
    },

    //: Les contrôles compensatoires qu'une dérogation peut citer.
    controles: [],

    brancher() {
        if (this.branche) return;
        this.branche = true;

        const ajouter = document.getElementById('separation-ajouter');
        if (ajouter) ajouter.addEventListener('click', () => this.ajouterUneRegle());

        const enregistrer = document.getElementById('separation-enregistrer');
        if (enregistrer) enregistrer.addEventListener('click', () => this.enregistrer());

        // Délégation : les trois zones sont réécrites à chaque rendu, et des
        // écouteurs posés sur leurs éléments disparaîtraient avec eux.
        const regles = document.getElementById('separation-regles');
        if (regles) {
            regles.addEventListener('input', (evenement) => {
                if (evenement.target.id === 'sod-selecteur-recherche') {
                    this.frapper(evenement.target.value);
                    return;
                }
                const champ = evenement.target.closest('[data-sod-champ]');
                if (champ) this.modifier(champ.dataset.sodRegle,
                                         champ.dataset.sodChamp, champ);
            });
            regles.addEventListener('change', (evenement) => {
                if (evenement.target.id === 'sod-selecteur-type') {
                    this.changerDeType(evenement.target.value);
                    return;
                }
                const champ = evenement.target.closest('[data-sod-champ]');
                if (champ) this.modifier(champ.dataset.sodRegle,
                                         champ.dataset.sodChamp, champ);
            });
            regles.addEventListener('click', (evenement) => {
                const retirer = evenement.target.closest('[data-sod-retirer]');
                if (retirer) {
                    evenement.preventDefault();
                    this.retirer(retirer.dataset.sodRetirer);
                    return;
                }
                const ouvrir = evenement.target.closest('[data-sod-ouvrir-selecteur]');
                if (ouvrir) {
                    evenement.preventDefault();
                    this.ouvrirLeSelecteur(ouvrir.dataset.sodRegle,
                                           ouvrir.dataset.sodOuvrirSelecteur);
                    return;
                }
                const choisir = evenement.target.closest('[data-sod-choisir]');
                if (choisir) {
                    evenement.preventDefault();
                    this.choisir(choisir.dataset.sodChoisir);
                    return;
                }
                const oter = evenement.target.closest('[data-sod-oter]');
                if (oter) {
                    evenement.preventDefault();
                    this.oter(oter.dataset.sodRegle, oter.dataset.sodCote,
                              Number(oter.dataset.sodOter));
                }
            });
        }

        const candidats = document.getElementById('separation-candidats');
        if (candidats) {
            candidats.addEventListener('click', (evenement) => {
                const bouton = evenement.target.closest('[data-sod-couple]');
                if (!bouton) return;
                evenement.preventDefault();
                this.retenirLeCouple(Number(bouton.dataset.sodCouple));
            });
        }
    },

    brancherLesConflits() {
        if (this.brancheConflits) return;
        this.brancheConflits = true;
        const conflits = document.getElementById('separation-conflits');
        if (!conflits) return;
        conflits.addEventListener('input', (evenement) => {
            if (evenement.target.id === 'sod-motif-refus') {
                this.motifDeRefus = evenement.target.value;
            } else if (evenement.target.id === 'sod-motif') {
                this.motifSaisi = evenement.target.value;
            } else if (evenement.target.id === 'sod-echeance') {
                this.echeanceSaisie = evenement.target.value;
            }
        });
        conflits.addEventListener('change', (evenement) => {
            if (evenement.target.id === 'sod-controle') {
                this.controleSaisi = evenement.target.value;
            }
        });
        // Une exécution consignée peut rendre sa couverture à une dérogation,
        // un contrôle retiré la lui ôter : les conflits se relisent.
        document.addEventListener('kovex:controles-modifies', async () => {
            await this.chargerLesConflits();
            if (this.ouverte) await this.ouvrir(this.ouverte);
        });
        conflits.addEventListener('click', (evenement) => {
            const detail = evenement.target.closest('[data-sod-detail]');
            if (detail) {
                evenement.preventDefault();
                this.ouvrir(detail.dataset.sodDetail);
                return;
            }
            const accepter = evenement.target.closest('[data-sod-accepter]');
            if (accepter) {
                evenement.preventDefault();
                this.ouvrirLAcceptation(accepter.dataset.sodRegleAcceptee,
                                        accepter.dataset.sodAccepter);
                return;
            }
            if (evenement.target.closest('[data-sod-annuler-derogation]')) {
                evenement.preventDefault();
                this.fermerLAcceptation();
                return;
            }
            if (evenement.target.closest('[data-sod-valider-derogation]')) {
                evenement.preventDefault();
                this.accorder();
                return;
            }
            const approuver = evenement.target.closest('[data-sod-approuver]');
            if (approuver) {
                evenement.preventDefault();
                this.trancher(approuver.dataset.sodApprouver, true);
                return;
            }
            const refuser = evenement.target.closest('[data-sod-refuser]');
            if (refuser) {
                evenement.preventDefault();
                this.refusEnCours = refuser.dataset.sodRefuser;
                this.motifDeRefus = '';
                this.renderLeDetail();
                return;
            }
            const confirmer = evenement.target.closest('[data-sod-confirmer-refus]');
            if (confirmer) {
                evenement.preventDefault();
                this.trancher(confirmer.dataset.sodConfirmerRefus, false);
                return;
            }
            const retirer = evenement.target.closest('[data-sod-retirer-derogation]');
            if (retirer) {
                evenement.preventDefault();
                this.retirerLaDerogation(retirer.dataset.sodRetirerDerogation);
                return;
            }
            const expliquer = evenement.target.closest('[data-sod-expliquer]');
            if (expliquer) {
                evenement.preventDefault();
                this.expliquer(expliquer.dataset.sodExpliquer, expliquer);
            }
        });
    },

    // -- l'explication rédigée ---------------------------------------------

    //: Le paragraphe rédigé pour la règle ouverte, tel que le serveur l'a
    //  contrôlé. Effacé à chaque relecture du détail : il cite des comptes,
    //  et des comptes qui ont changé le rendraient faux.
    explication: null,

    /**
     * Fait rédiger le paragraphe qui explique la règle en conflit.
     *
     * Seule la règle part de l'écran : le serveur relit les comptes et les
     * libellés, et refuse une phrase qui inventerait un nombre. Aucune
     * identité ne quitte la machine, quelle que soit la configuration.
     */
    async expliquer(regle, bouton) {
        const libelle = bouton.innerHTML;
        bouton.innerHTML = `<i class="fas fa-spinner fa-spin" aria-hidden="true"></i> ${
            Utils.escapeHtml(I18n.t('annotator.asking'))}`;
        bouton.disabled = true;
        try {
            const rendu = await API.post('/assistance/explication-de-conflit', {
                regle, locale: I18n.currentLocale,
            });
            this.explication = {regle, texte: rendu.explication, modele: rendu.modele};
            this.renderLeDetail();
        } catch (erreur) {
            Toast.error(I18n.t('common.error'),
                        erreur.message || I18n.t('annotator.unavailable'));
            bouton.innerHTML = libelle;
            bouton.disabled = false;
        }
    },

    renderLExplication(regle) {
        const explication = this.explication && this.explication.regle === regle
            ? this.explication : null;
        return `<div class="sod-explication">
                <button type="button" class="btn btn-secondary btn-sm"
                        data-sod-expliquer="${Utils.escapeHtml(regle)}">
                    <i class="fas fa-pen-nib" aria-hidden="true"></i> ${
                        Utils.escapeHtml(I18n.t('separation.explain'))}</button>
                ${explication ? `
                    <p class="form-hint">${Utils.escapeHtml(I18n.t('separation.explain.hint',
                                                                   {modele: explication.modele}))}</p>
                    <p class="explication__texte">${Utils.escapeHtml(explication.texte)}</p>` : ''}
            </div>`;
    },

    // -- l'exception assumée -----------------------------------------------

    //: Le conflit dont le formulaire d'acceptation est ouvert, sous la forme
    //  `règle--identité`. Un seul à la fois : douze formulaires ouverts sur une
    //  liste de conflits ne se lisent pas.
    acceptation: '',
    motifSaisi: '',
    echeanceSaisie: '',
    controleSaisi: '',
    //: Les bornes du workspace, rendues par le serveur. L'écran s'en sert pour
    //  refuser **avant** la saisie plutôt qu'après.
    bornes: null,

    ouvrirLAcceptation(regle, identite) {
        this.acceptation = `${regle}--${identite}`;
        this.motifSaisi = '';
        this.echeanceSaisie = '';
        this.controleSaisi = '';
        this.renderLeDetail();
        const motif = document.getElementById('sod-motif');
        if (motif) motif.focus();
    },

    fermerLAcceptation() {
        this.acceptation = '';
        this.renderLeDetail();
    },

    async accorder() {
        const [regle, identite] = (this.acceptation || '').split('--');
        if (!regle || !identite) return;
        try {
            await API.post('/derogations', {
                famille: 'separation',
                cible: {regle, identite},
                motif: this.motifSaisi,
                echeance: this.echeanceSaisie,
                controle: this.controleSaisi,
            });
        } catch (erreur) {
            // Le serveur rend un refus structuré : le message se compose ici,
            // parce que lui ne connaît pas la langue de l'utilisateur.
            Toast.error(I18n.t('common.error'), erreur.message);
            return;
        }
        Toast.success(I18n.t('common.success'), I18n.t('derogation.granted'));
        this.acceptation = '';
        await this.rafraichirApresDerogation(regle);
    },

    async retirerLaDerogation(identifiant) {
        try {
            await API.delete(`/derogations/${encodeURIComponent(identifiant)}`);
        } catch (erreur) {
            Toast.error(I18n.t('common.error'), erreur.message);
            return;
        }
        Toast.success(I18n.t('common.success'), I18n.t('derogation.revoked'));
        await this.rafraichirApresDerogation(this.ouverte);
    },

    /**
     * Relit ce qui a changé, et rien d'autre.
     *
     * Les deux : le détail, parce que la ligne change d'état, et la synthèse,
     * parce que le compte des conflits couverts en dépend. Ne relire que l'un
     * des deux laisserait un total qui contredit la liste qu'il surplombe.
     */
    async rafraichirApresDerogation(regle) {
        await this.chargerLesConflits();
        await this.ouvrir(regle);
    },

    async charger() {
        try {
            const rendu = await API.get('/separation/regles');
            // Les niveaux viennent du workspace, dans les mots du client : le
            // produit n'en livre aucun, et n'en traduit aucun.
            this.severites = (rendu.severites || []).map(String);
            this.regles = (rendu.regles || []).map((regle) => ({
                id: String(regle.id || ''),
                libelle: String(regle.libelle || ''),
                gauche: this.lireLeCote(regle.gauche),
                droite: this.lireLeCote(regle.droite),
                active: regle.active !== false,
                severite: String(regle.severite || ''),
                processus: String(regle.processus || ''),
                proprietaire: String(regle.proprietaire || ''),
            }));
        } catch (erreur) {
            Toast.error(I18n.t('common.error'), erreur.message);
            return;
        }
        this.renderLesRegles();
        await this.chargerLesCandidats();
    },

    async chargerLesConflits() {
        try {
            this.conflits = await API.get('/separation/conflits');
        } catch (erreur) {
            this.conflits = null;
        }
        try {
            // Les bornes de l'exception : la durée maximale et le jour du
            // serveur. Les calculer côté client ferait diverger l'écran du
            // refus que le serveur opposerait.
            this.bornes = await API.get('/derogations');
        } catch (erreur) {
            this.bornes = null;
        }
        try {
            this.controles = (await API.get('/controles')).controles || [];
        } catch (erreur) {
            this.controles = [];
        }
        this.renderLesConflits();
    },

    async chargerLesCandidats() {
        try {
            this.candidats = (await API.get('/separation/candidats')).couples || [];
        } catch (erreur) {
            this.candidats = [];
        }
        this.renderLesCandidats();
    },

    // -- les règles --------------------------------------------------------

    /**
     * Un identifiant qui ne ressemble à rien de métier.
     *
     * Il n'est jamais montré : ce que l'utilisateur lit est le libellé qu'il a
     * écrit. Le dériver du libellé aurait fait changer d'identité une règle
     * qu'on renomme — et une piste d'audit y aurait vu deux règles.
     */
    nouvelIdentifiant() {
        const pris = new Set(this.regles.map((regle) => regle.id));
        let rang = this.regles.length + 1;
        while (pris.has(`SOD${rang}`)) rang += 1;
        return `SOD${rang}`;
    },

    ajouterUneRegle(gauche = [], droite = []) {
        this.regles.push({id: this.nouvelIdentifiant(), libelle: '',
                          gauche, droite, active: true,
                          severite: '', processus: '', proprietaire: ''});
        this.selecteur = null;
        this.renderLesRegles();
    },

    /**
     * Lit un côté rendu par le serveur.
     *
     * Une chaîne nue se lit comme un droit : c'est la forme qu'écrivait le lot
     * précédent, et un workspace qui la porte doit continuer de s'afficher.
     */
    lireLeCote(brut) {
        return (brut || []).map((reference) => (
            typeof reference === 'string'
                ? {type: 'droit', id: reference, libelle: ''}
                : {type: String(reference.type || 'droit'),
                   id: String(reference.id || ''),
                   libelle: String(reference.libelle || '')}));
    },

    /**
     * Reporte une saisie dans l'état, et redessine quand l'écran doit changer.
     *
     * Le libellé ne redessine pas : réécrire le bloc à chaque frappe ferait
     * perdre le curseur. Suspendre une règle, si — sans cela on décoche et
     * rien ne dit qu'elle a cessé de calculer, ce qui est précisément ce
     * qu'on venait de demander.
     *
     * Le focus est rendu à la case après le rendu : le bloc est reconstruit,
     * et un utilisateur au clavier se retrouverait sinon au début du document.
     */
    modifier(identifiant, champ, element) {
        const regle = this.regles.find((candidate) => candidate.id === identifiant);
        if (!regle) return;
        if (champ !== 'active') {
            regle[champ] = element.value;
            return;
        }
        regle.active = element.checked;
        this.renderLesRegles();
        const case_ = document.getElementById(`sod-actif-${identifiant}`);
        if (case_) case_.focus();
    },

    retirer(identifiant) {
        this.regles = this.regles.filter((regle) => regle.id !== identifiant);
        this.renderLesRegles();
    },

    renderLesRegles() {
        const zone = document.getElementById('separation-regles');
        if (!zone) return;
        if (!this.regles.length) {
            zone.innerHTML = `<p class="form-hint">${
                Utils.escapeHtml(I18n.t('separation.empty'))}</p>`;
            return;
        }
        zone.innerHTML = this.regles.map((regle) => `
            <div class="sod-regle" data-sod-bloc="${Utils.escapeHtml(regle.id)}">
                <div class="form-group">
                    <label class="form-label" for="sod-libelle-${Utils.escapeHtml(regle.id)}"
                           >${Utils.escapeHtml(I18n.t('separation.rule.label'))}</label>
                    <input type="text" class="form-input"
                           id="sod-libelle-${Utils.escapeHtml(regle.id)}"
                           data-sod-regle="${Utils.escapeHtml(regle.id)}"
                           data-sod-champ="libelle"
                           placeholder="${Utils.escapeHtml(I18n.t('separation.rule.placeholder'))}"
                           value="${Utils.escapeHtml(regle.libelle)}">
                </div>
                <div class="form-row">
                    ${this.renderLeCote(regle, 'gauche')}
                    ${this.renderLeCote(regle, 'droite')}
                </div>
                ${this.renderLaQualification(regle)}
                <div class="form-actions">
                    <label class="chart-option" for="sod-actif-${Utils.escapeHtml(regle.id)}">
                        <input type="checkbox" id="sod-actif-${Utils.escapeHtml(regle.id)}"
                               data-sod-regle="${Utils.escapeHtml(regle.id)}"
                               data-sod-champ="active" ${regle.active ? 'checked' : ''}>
                        <span>${Utils.escapeHtml(I18n.t('separation.rule.active'))}</span>
                    </label>
                    <button type="button" class="btn btn-secondary btn-sm"
                            data-sod-retirer="${Utils.escapeHtml(regle.id)}">
                        <i class="fas fa-trash" aria-hidden="true"></i>
                        <span>${Utils.escapeHtml(I18n.t('separation.rule.remove'))}</span>
                    </button>
                </div>
                ${regle.active ? '' : `<p class="form-hint">${
                    Utils.escapeHtml(I18n.t('separation.rule.suspended'))}</p>`}
            </div>`).join('');
    },

    /**
     * Sévérité, processus, propriétaire : ce qui fait d'une règle un risque.
     *
     * Sans sévérité, quarante conflits se lisent tous pareil ; sans
     * propriétaire, personne ne répond du risque. Les niveaux sont ceux du
     * workspace ; tant qu'il n'en déclare aucun, l'écran dit où les écrire
     * plutôt que de proposer une échelle que personne n'a décidée.
     */
    renderLaQualification(regle) {
        const id = Utils.escapeHtml(regle.id);
        const champ = (nom, cle) => `
            <div class="form-group">
                <label class="form-label" for="sod-${nom}-${id}"
                       >${Utils.escapeHtml(I18n.t(cle))}</label>
                <input type="text" class="form-input" id="sod-${nom}-${id}"
                       data-sod-regle="${id}" data-sod-champ="${nom}"
                       maxlength="200" value="${Utils.escapeHtml(regle[nom])}">
            </div>`;
        const niveaux = this.severites || [];
        // Un niveau retiré de la liste depuis l'enregistrement reste montré :
        // le faire disparaître du menu changerait la règle sans qu'on y touche.
        const proposes = regle.severite && !niveaux.includes(regle.severite)
            ? [...niveaux, regle.severite] : niveaux;
        const severite = niveaux.length || regle.severite ? `
            <div class="form-group">
                <label class="form-label" for="sod-severite-${id}"
                       >${Utils.escapeHtml(I18n.t('separation.rule.severity'))}</label>
                <select class="form-input" id="sod-severite-${id}"
                        data-sod-regle="${id}" data-sod-champ="severite">
                    <option value="">${Utils.escapeHtml(
                        I18n.t('separation.rule.severity_none'))}</option>
                    ${proposes.map((niveau) => `<option value="${Utils.escapeHtml(niveau)}"
                        ${niveau === regle.severite ? 'selected' : ''}>${
                        Utils.escapeHtml(niveau)}</option>`).join('')}
                </select>
            </div>` : `
            <p class="form-hint">${Utils.escapeHtml(
                I18n.t('separation.rule.severity_undeclared'))}</p>`;
        return `
            <div class="form-row">
                ${severite}
                ${champ('processus', 'separation.rule.process')}
                ${champ('proprietaire', 'separation.rule.owner')}
            </div>`;
    },

    /**
     * Un côté de règle : ses références, et de quoi en ajouter une.
     *
     * Les références sont des **pastilles** et non un champ de texte. La
     * saisie libre demandait de connaître `D_FIN_0042` de mémoire — c'est
     * précisément la colonne qui ne dit rien, et la seule que le produit
     * connaisse par construction.
     */
    renderLeCote(regle, cote) {
        const references = regle[cote] || [];
        const ouvert = this.selecteur && this.selecteur.regle === regle.id
            && this.selecteur.cote === cote;
        return `
            <div class="form-group">
                <span class="form-label">${Utils.escapeHtml(
                    I18n.t(`separation.rule.${cote === 'gauche' ? 'left' : 'right'}`))}</span>
                <div class="sod-references">
                    ${references.length ? references.map((reference, rang) => `
                        <span class="sod-reference">
                            <span class="badge badge-neutral">${Utils.escapeHtml(
                                I18n.t(`separation.type.${reference.type}`))}</span>
                            <span>${Utils.escapeHtml(reference.libelle || reference.id)}</span>
                            <button type="button" class="sod-reference__retirer"
                                    data-sod-oter="${rang}"
                                    data-sod-regle="${Utils.escapeHtml(regle.id)}"
                                    data-sod-cote="${cote}"
                                    aria-label="${Utils.escapeHtml(
                                        I18n.t('separation.reference.remove'))}">
                                <i class="fas fa-xmark" aria-hidden="true"></i>
                            </button>
                        </span>`).join('')
                        : `<span class="form-hint">${Utils.escapeHtml(
                            I18n.t('separation.rule.side_empty'))}</span>`}
                </div>
                <button type="button" class="btn btn-secondary btn-sm"
                        data-sod-ouvrir-selecteur="${cote}"
                        data-sod-regle="${Utils.escapeHtml(regle.id)}">
                    <i class="fas fa-plus" aria-hidden="true"></i>
                    <span>${Utils.escapeHtml(I18n.t('separation.reference.add'))}</span>
                </button>
                ${ouvert ? this.renderLeSelecteur() : ''}
            </div>`;
    },

    /**
     * Le sélecteur : un type, une recherche, et ce que le référentiel rend.
     *
     * Les libellés viennent des colonnes du client et ne passent pas par i18n :
     * traduire `Paiement fournisseur` afficherait autre chose que ce que le
     * fichier contient.
     */
    renderLeSelecteur() {
        const selecteur = this.selecteur;
        const types = ['droit', 'application', 'role'];
        return `
            <div class="sod-selecteur">
                <div class="form-row">
                    <select class="form-input" id="sod-selecteur-type"
                            aria-label="${Utils.escapeHtml(
                                I18n.t('separation.reference.type'))}">
                        ${types.map((type) => `
                            <option value="${type}" ${
                                type === selecteur.type ? 'selected' : ''}
                                >${Utils.escapeHtml(
                                    I18n.t(`separation.type.${type}`))}</option>`).join('')}
                    </select>
                    <input type="search" class="form-input" id="sod-selecteur-recherche"
                           value="${Utils.escapeHtml(selecteur.terme || '')}"
                           placeholder="${Utils.escapeHtml(
                               I18n.t('separation.reference.search'))}"
                           aria-label="${Utils.escapeHtml(
                               I18n.t('separation.reference.search'))}">
                </div>
                ${selecteur.resultats.length ? `
                    <ul class="sod-resultats">${selecteur.resultats.map((resultat) => `
                        <li>
                            <button type="button" class="sod-resultat"
                                    data-sod-choisir="${Utils.escapeHtml(resultat.id)}">
                                <strong>${Utils.escapeHtml(resultat.id)}</strong>
                                <span>${Utils.escapeHtml(resultat.libelle)}</span>
                            </button>
                        </li>`).join('')}</ul>
                ` : `<p class="form-hint">${Utils.escapeHtml(I18n.t(
                        selecteur.type === 'role' && !selecteur.terme
                            ? 'separation.reference.no_role'
                            : 'separation.reference.none'))}</p>`}
            </div>`;
    },

    // -- le sélecteur ------------------------------------------------------

    ouvrirLeSelecteur(regle, cote) {
        // Rouvrir le même le referme : c'est le geste attendu d'un bouton qui
        // déplie, et cela évite d'avoir à chercher comment le fermer.
        if (this.selecteur && this.selecteur.regle === regle
                && this.selecteur.cote === cote) {
            this.selecteur = null;
        } else {
            this.selecteur = {regle, cote, type: 'droit', terme: '',
                              resultats: []};
        }
        this.renderLesRegles();
        if (this.selecteur) this.chercher();
    },

    /**
     * Cherche dans le référentiel du type choisi.
     *
     * Un jeton d'ordre protège le rendu : deux frappes rapides lancent deux
     * requêtes, et la première peut revenir la dernière — l'utilisateur verrait
     * alors les résultats d'un terme qu'il a fini d'effacer.
     */
    async chercher() {
        const selecteur = this.selecteur;
        if (!selecteur) return;
        const jeton = (this.jetonDeRecherche = (this.jetonDeRecherche || 0) + 1);
        let resultats = [];
        try {
            resultats = await this.interroger(selecteur.type, selecteur.terme);
        } catch (erreur) {
            resultats = [];
        }
        if (jeton !== this.jetonDeRecherche || this.selecteur !== selecteur) return;
        selecteur.resultats = resultats;
        this.renderLesRegles();
        const champ = document.getElementById('sod-selecteur-recherche');
        if (champ) {
            champ.focus();
            champ.setSelectionRange(champ.value.length, champ.value.length);
        }
    },

    /**
     * Un champ de rôle, vide quand le catalogue ne le porte pas.
     *
     * Un rôle composé à la main peut n'avoir jamais reçu de nom. Écrire
     * `String(role.name)` afficherait alors le mot « undefined » dans la liste
     * des résultats, et l'utilisateur choisirait un rôle qui s'appelle comme
     * une erreur de programmation.
     *
     * `== null` plutôt que deux comparaisons : les deux cas sont le même fait —
     * le champ n'est pas là — et les séparer ferait une branche que rien ne
     * distingue.
     */
    texteDuRole(valeur) {
        return valeur == null ? '' : String(valeur);
    },

    /** Ce que chaque type sait rendre, et sous quelles colonnes. */
    async interroger(type, terme) {
        const taille = SeparationPage.RESULTATS_MAX;
        if (type === 'role') {
            const rendu = await API.get('/kb/validated-roles');
            const cherche = String(terme || '').toLowerCase();
            const lu = SeparationPage.texteDuRole;
            return (rendu.roles || [])
                .filter((role) => {
                    if (!cherche) return true;
                    const identifiant = lu(role.id).toLowerCase();
                    const nom = lu(role.name).toLowerCase();
                    return identifiant.includes(cherche) || nom.includes(cherche);
                })
                .slice(0, taille)
                .map((role) => ({id: lu(role.id), libelle: lu(role.name)}));
        }
        const route = type === 'application' ? '/applications/list' : '/rights/list';
        const colonne = type === 'application' ? 'ID_application' : 'ID_droit';
        const rendu = await API.get(route, {page: 1, size: taille,
                                            search: terme || ''});
        return (rendu.data || []).map((ligne) => ({
            id: String(ligne[colonne] === undefined ? '' : ligne[colonne]),
            // Les autres colonnes du client, dans leur ordre : le produit n'en
            // connaît aucune par son nom, et c'est souvent l'une d'elles — pas
            // l'identifiant — qui dit ce que le droit permet.
            libelle: Object.keys(ligne)
                .filter((nom) => nom !== colonne)
                .map((nom) => ligne[nom])
                .filter((valeur) => valeur !== null && valeur !== undefined
                                    && String(valeur).trim() !== '')
                .join(' · ')
                .slice(0, SeparationPage.LIBELLE_MAX),
        })).filter((resultat) => resultat.id);
    },

    /** Attend que la frappe se pose avant d'interroger le serveur. */
    frapper(terme) {
        if (!this.selecteur) return;
        this.selecteur.terme = terme;
        if (this.frappe) clearTimeout(this.frappe);
        this.frappe = setTimeout(() => this.chercher(), SeparationPage.FRAPPE_MS);
    },

    changerDeType(type) {
        if (!this.selecteur) return;
        this.selecteur.type = type;
        // Les résultats de l'ancien type sont vidés tout de suite : les laisser
        // à l'écran le temps d'une requête ferait choisir un droit en croyant
        // choisir une application.
        this.selecteur.resultats = [];
        this.renderLesRegles();
        this.chercher();
    },

    choisir(identifiant) {
        const selecteur = this.selecteur;
        if (!selecteur) return;
        const regle = this.regles.find((une) => une.id === selecteur.regle);
        if (!regle) return;
        const resultat = selecteur.resultats.find((un) => un.id === identifiant);
        const cote = regle[selecteur.cote];
        // Deux fois la même référence est la même règle : l'ajouter deux fois
        // ferait deux pastilles qui disent la même chose.
        if (!cote.some((reference) => reference.type === selecteur.type
                                      && reference.id === identifiant)) {
            cote.push({type: selecteur.type, id: identifiant,
                       libelle: resultat ? resultat.libelle : ''});
        }
        this.renderLesRegles();
    },

    oter(identifiantDeRegle, cote, rang) {
        const regle = this.regles.find((une) => une.id === identifiantDeRegle);
        if (!regle) return;
        regle[cote].splice(rang, 1);
        this.renderLesRegles();
    },

    async enregistrer() {
        const envoi = this.regles.map((regle) => ({
            id: regle.id,
            libelle: regle.libelle,
            gauche: regle.gauche.map((reference) => ({type: reference.type,
                                                      id: reference.id})),
            droite: regle.droite.map((reference) => ({type: reference.type,
                                                      id: reference.id})),
            active: regle.active,
            severite: regle.severite,
            processus: regle.processus,
            proprietaire: regle.proprietaire,
        }));
        try {
            await API.put('/separation/regles', {regles: envoi});
        } catch (erreur) {
            // Le serveur rend un refus structuré : le message se compose ici,
            // parce que lui ne connaît pas la langue de l'utilisateur.
            Toast.error(I18n.t('common.error'), erreur.message);
            return;
        }
        Toast.success(I18n.t('common.success'), I18n.t('separation.saved'));
        // Les couples candidats se recalculent : une règle nouvellement
        // déclarée en retire ceux qu'elle couvre, et les laisser à l'écran
        // ferait reproposer ce qu'on vient d'écrire.
        await this.chargerLesCandidats();
    },

    // -- les conflits ------------------------------------------------------

    renderLesConflits() {
        const zone = document.getElementById('separation-conflits');
        const total = document.getElementById('separation-total');
        if (!zone) return;
        const rendu = this.conflits;
        // Trois états, et non deux. Ne pas avoir pu compter, n'avoir aucune
        // règle à appliquer, et n'avoir trouvé aucun conflit sont trois choses
        // différentes, et les confondre produit le seul mensonge que cet écran
        // puisse faire.
        if (!rendu) {
            // Le calcul a échoué : l'erreur est déjà annoncée, et écrire ici
            // « aucune règle déclarée » affirmerait un fait qu'on ignore.
            zone.innerHTML = '';
            if (total) total.textContent = '';
            return;
        }
        if (!(rendu.regles || []).length) {
            // La phrase existait, écrite pour l'écran de déclaration, et elle
            // manquait ici — c'est-à-dire sur le seul des deux écrans où
            // l'absence peut se lire comme un résultat. Un cadre blanc sous un
            // titre « Conflits constatés » dit « aucun conflit » à qui le
            // regarde, alors qu'il veut dire « aucun contrôle ».
            zone.innerHTML = `<p class="form-hint">${
                Utils.escapeHtml(I18n.t('separation.conflicts.no_rule'))}</p>`;
            if (total) total.textContent = '';
            return;
        }
        if (total) {
            // Deux nombres : ce qui reste à traiter, et ce qui a été accepté.
            // Un seul total ferait croire qu'il reste tout à faire, ou
            // cacherait à un auditeur ce qui a été assumé.
            const derogees = rendu.identites_derogees || 0;
            const orphelines = rendu.regles_sans_proprietaire || 0;
            total.textContent = [
                I18n.t('separation.conflicts.count', {
                    identites: Utils.formatNumber(rendu.identites_en_conflit),
                    population: Utils.formatNumber(rendu.population)}),
                derogees ? I18n.t('separation.conflicts.derogated',
                                  {derogees: Utils.formatNumber(derogees)}) : '',
                // Un défaut du programme lui-même, pas d'une habilitation :
                // personne n'est là pour répondre de ces risques.
                orphelines ? I18n.t('separation.conflicts.without_owner',
                                    {regles: Utils.formatNumber(orphelines)}) : '',
                rendu.derogations_en_attente ? I18n.t('separation.conflicts.pending', {
                    derogations: Utils.formatNumber(rendu.derogations_en_attente)}) : '',
                rendu.regles_suspendues ? I18n.t('separation.conflicts.suspended', {
                    regles: Utils.formatNumber(rendu.regles_suspendues)}) : '',
            ].filter(Boolean).join(' · ');
        }
        zone.innerHTML = rendu.regles.map((ligne) => `
            <div class="sod-conflit">
                <h3 class="sod-conflit__titre">${Utils.escapeHtml(ligne.libelle)}</h3>
                ${this.renderLaQualite(ligne)}
                ${this.renderLInapplicable(ligne)}
                ${ligne.identites ? `
                    <p>${Utils.escapeHtml(I18n.t('separation.conflicts.by_roles', {
                        par_les_roles: ligne.par_les_roles,
                        hors_role: ligne.hors_role}))}</p>
                    ${ligne.roles_en_conflit ? `
                        <p class="form-hint form-hint-error">${Utils.escapeHtml(
                            I18n.t('separation.conflicts.roles',
                                   {roles_en_conflit: ligne.roles_en_conflit}))}</p>
                        <p class="form-hint">${Utils.escapeHtml(
                            I18n.t('separation.conflicts.role_warning'))}</p>
                    ` : ''}
                    <button type="button" class="btn btn-secondary btn-sm"
                            data-sod-detail="${Utils.escapeHtml(ligne.regle)}">
                        <i class="fas fa-list" aria-hidden="true"></i>
                        <span>${Utils.escapeHtml(I18n.t('action.view_details'))}</span>
                    </button>
                ` : `<p class="form-hint">${Utils.escapeHtml(
                        I18n.t('separation.conflicts.none'))}</p>`}
                <div id="sod-detail-${Utils.escapeHtml(ligne.regle)}"></div>
            </div>`).join('');
        if (this.ouverte) this.renderLeDetail();
    },

    /**
     * Ce qui qualifie le risque, sous le titre du conflit.
     *
     * Chaque absence est dite : une règle sans sévérité n'est pas une règle
     * mineure, et une règle sans propriétaire est un risque dont personne ne
     * répond.
     */
    renderLaQualite(ligne) {
        const morceaux = [
            ligne.severite
                ? I18n.t('separation.conflicts.severity', {severite: ligne.severite})
                : I18n.t('separation.conflicts.no_severity'),
            ligne.processus
                ? I18n.t('separation.conflicts.process', {processus: ligne.processus})
                : '',
            ligne.proprietaire
                ? I18n.t('separation.conflicts.owner', {proprietaire: ligne.proprietaire})
                : I18n.t('separation.conflicts.no_owner'),
        ].filter(Boolean);
        return `<p class="sod-conflit__qualite">${Utils.escapeHtml(morceaux.join(' · '))}</p>`;
    },

    /**
     * Pourquoi une règle ne calcule rien, quand c'est le cas.
     *
     * Trois raisons, et l'écran les distingue : elle est suspendue, une de ses
     * références ne désigne plus rien, ou ses deux côtés se recouvrent. Les
     * confondre ferait chercher l'erreur au mauvais endroit — refaire sa liste
     * alors que c'est une application qui a disparu de l'export.
     */
    renderLInapplicable(ligne) {
        if (ligne.applicable) {
            // Une règle qui s'applique peut quand même avoir été tronquée :
            // le dire est le seul moyen qu'un chiffre partiel ne se lise pas
            // comme un chiffre complet.
            return ligne.tronquee ? `<p class="form-hint">${Utils.escapeHtml(
                I18n.t('separation.rule.truncated'))}</p>` : '';
        }
        const lignes = [];
        if (!ligne.active) lignes.push(I18n.t('separation.rule.suspended'));
        if ((ligne.introuvables || []).length) {
            lignes.push(I18n.t('separation.rule.unresolved', {
                references: ligne.introuvables
                    .map((reference) => reference.id).join(', ')}));
        }
        if ((ligne.chevauchement || []).length) {
            lignes.push(I18n.t('separation.rule.overlap', {
                droits: ligne.chevauchement.join(', ')}));
        }
        return lignes.map((texte) => `<p class="form-hint form-hint-error">${
            Utils.escapeHtml(texte)}</p>`).join('');
    },

    async ouvrir(identifiant) {
        this.ouverte = identifiant;
        this.explication = null;
        try {
            this.detail = await API.get(
                `/separation/conflits/${encodeURIComponent(identifiant)}`);
        } catch (erreur) {
            Toast.error(I18n.t('common.error'), erreur.message);
            this.ouverte = '';
            return;
        }
        this.renderLeDetail();
    },

    /**
     * Le détail d'une règle : les rôles d'abord, les identités ensuite.
     *
     * Les rôles qui portent les deux côtés ne se corrigent pas identité par
     * identité, et les noyer dans la liste des porteurs ferait traiter cent
     * fois un défaut unique.
     */
    renderLeDetail() {
        const detail = this.detail;
        if (!detail) return;
        const zone = document.getElementById(`sod-detail-${detail.regle}`);
        if (!zone) return;
        // Le serveur rend des identifiants de rôle, et leurs noms à part : un
        // rôle sans nom connu garde son identifiant plutôt que de disparaître.
        const noms = detail.noms_des_roles || {};
        const origine = (origines) => (origines || [])
            .map((identifiant) => identifiant === 'hors_role'
                ? I18n.t('separation.origin.hors_role')
                : noms[identifiant] || identifiant).join(', ');
        zone.innerHTML = `
            ${detail.identites ? this.renderLExplication(detail.regle) : ''}
            ${(detail.roles || []).length ? `
                <ul class="sod-roles">${detail.roles.map((role) => `
                    <li><strong>${Utils.escapeHtml(role.role || role.role_id)}</strong>
                        — ${Utils.escapeHtml(role.gauche.join(', '))}
                        / ${Utils.escapeHtml(role.droite.join(', '))}</li>`).join('')}
                </ul>` : ''}
            <div class="table-wrapper" role="region"
                 aria-label="${Utils.escapeHtml(detail.libelle)}">
                <table class="data-table">
                    <thead><tr>
                        <th scope="col">${Utils.escapeHtml(I18n.t('separation.column.identity'))}</th>
                        <th scope="col">${Utils.escapeHtml(I18n.t('separation.column.left'))}</th>
                        <th scope="col">${Utils.escapeHtml(I18n.t('separation.column.right'))}</th>
                        <th scope="col">${Utils.escapeHtml(I18n.t('separation.column.origin'))}</th>
                        <th scope="col">${Utils.escapeHtml(I18n.t('separation.column.derogation'))}</th>
                    </tr></thead>
                    <tbody>${(detail.lignes || []).map((ligne) => `
                        <tr${ligne.derogation ? ' class="sod-derogee"' : ''}>
                            <td>${this.marqueDePrivilege(ligne.identite)}${
                                Utils.escapeHtml(ligne.identite)}</td>
                            <td>${Utils.escapeHtml(ligne.gauche.join(', '))}</td>
                            <td>${Utils.escapeHtml(ligne.droite.join(', '))}</td>
                            <td>${Utils.escapeHtml(
                                [origine(ligne.origines_gauche),
                                 origine(ligne.origines_droite)].join(' / '))}</td>
                            <td>${this.renderLaDerogation(detail.regle, ligne)}</td>
                        </tr>`).join('')}
                    </tbody>
                </table>
            </div>
            ${detail.tronquee ? `<p class="form-hint">${Utils.escapeHtml(
                I18n.t('separation.conflicts.truncated',
                       {max: (detail.lignes || []).length}))}</p>` : ''}`;
    },

    /**
     * La marque d'un compte à privilèges, dans la colonne des identités.
     *
     * Un cumul porté par un compte d'administration ne se lit pas comme un
     * cumul porté par un compte nominatif : c'est le même constat sur une
     * personne et sur un pouvoir, et c'est la seule colonne de cet écran où
     * la distinction change la décision.
     *
     * Le titre porte la phrase et l'icône est décorative : un pictogramme seul
     * n'est pas une information.
     */
    marqueDePrivilege(identite) {
        const marques = this.detail && this.detail.comptes_a_privileges;
        if (!Array.isArray(marques) || !marques.includes(identite)) return '';
        const phrase = I18n.t('privileges.compte_marque');
        return `<span class="table-privilege" title="${Utils.escapeHtml(phrase)}">`
            + '<i class="fas fa-user-shield" aria-hidden="true"></i>'
            + `<span class="sr-only">${Utils.escapeHtml(phrase)}</span></span> `;
    },

    /**
     * La colonne de l'exception assumée : ce qui couvre ce conflit, ou de quoi
     * l'accepter.
     *
     * Un conflit couvert **reste affiché** — il est seulement rangé à part, et
     * dit par qui et jusqu'à quand. Le masquer cacherait à un auditeur ce qui a
     * été accepté, et c'est la première chose qu'il demande.
     */
    renderLaDerogation(regle, ligne) {
        const derogation = ligne.derogation;
        const cle = `${regle}--${ligne.identite}`;
        const inoperante = ligne.derogation_inoperante;
        if (!derogation && inoperante) {
            // Accordée, en cours, et sans effet : le conflit est revenu. Le
            // dire, et dire pourquoi — sans quoi l'auditeur lit « non traité »
            // là où une décision existe et a cessé de valoir.
            const enAttente = inoperante.statut === 'demandee';
            return `
                <span class="badge badge-warning">${Utils.escapeHtml(
                    I18n.t(enAttente ? 'derogation.pending' : 'derogation.inoperative'))}</span>
                <ul class="controle__raisons">${(inoperante.raisons || []).map((raison) => `
                    <li>${Utils.escapeHtml(I18n.t(`derogation.raison.${raison.code}`,
                                                  Utils.parametresDansLaLangue(raison.params)))}</li>`).join('')}</ul>
                ${enAttente ? this.renderLaDecision(inoperante) : ''}
                <button type="button" class="btn btn-secondary btn-sm"
                        data-sod-retirer-derogation="${Utils.escapeHtml(inoperante.id)}">
                    ${Utils.escapeHtml(I18n.t('derogation.revoke'))}
                </button>`;
        }
        if (derogation) {
            return `
                <span class="badge badge-neutral">${Utils.escapeHtml(
                    I18n.t('derogation.until',
                           {echeance: Utils.formatDate(derogation.echeance)}))}</span>
                <span class="form-hint">${Utils.escapeHtml(
                    [derogation.motif, derogation.auteur, this.libelleDuControle(derogation.controle)]
                        .filter(Boolean).join(' — '))}</span>
                <button type="button" class="btn btn-secondary btn-sm"
                        data-sod-retirer-derogation="${Utils.escapeHtml(derogation.id)}">
                    ${Utils.escapeHtml(I18n.t('derogation.revoke'))}
                </button>`;
        }
        if (this.acceptation === cle) return this.renderLAcceptation(regle, ligne);
        return `
            <button type="button" class="btn btn-secondary btn-sm"
                    data-sod-accepter="${Utils.escapeHtml(ligne.identite)}"
                    data-sod-regle-acceptee="${Utils.escapeHtml(regle)}">
                ${Utils.escapeHtml(I18n.t('derogation.accept'))}
            </button>`;
    },

    /**
     * Le formulaire d'acceptation : un motif, une échéance, et rien d'autre.
     *
     * Ni date d'octroi ni auteur — ils viennent du serveur. Les laisser saisir
     * permettrait d'antidater une décision ou de l'attribuer à quelqu'un
     * d'autre, et c'est l'objet qui fait taire un signalement.
     *
     * L'échéance est bornée à l'écran par la durée maximale du workspace, pour
     * que le refus arrive **avant** la saisie plutôt qu'après.
     */
    renderLAcceptation(regle, ligne) {
        const bornes = this.bornes || {};
        return `
            <div class="sod-acceptation">
                <label class="form-label" for="sod-motif"
                       >${Utils.escapeHtml(I18n.t('derogation.reason'))}</label>
                <input type="text" class="form-input" id="sod-motif"
                       value="${Utils.escapeHtml(this.motifSaisi || '')}"
                       placeholder="${Utils.escapeHtml(
                           I18n.t('derogation.reason.placeholder'))}">
                <label class="form-label" for="sod-echeance"
                       >${Utils.escapeHtml(I18n.t('derogation.deadline'))}</label>
                <input type="date" class="form-input" id="sod-echeance"
                       value="${Utils.escapeHtml(this.echeanceSaisie || '')}"
                       min="${Utils.escapeHtml(bornes.aujourdhui || '')}"
                       max="${Utils.escapeHtml(this.echeanceMaximale())}">
                <span class="form-hint">${Utils.escapeHtml(
                    I18n.t('derogation.deadline.hint',
                           {jours: bornes.duree_max_jours || 0}))}</span>
                ${this.renderLeChoixDuControle()}
                <div class="form-actions">
                    <button type="button" class="btn btn-primary btn-sm"
                            data-sod-valider-derogation="1">
                        ${Utils.escapeHtml(I18n.t('derogation.confirm'))}
                    </button>
                    <button type="button" class="btn btn-secondary btn-sm"
                            data-sod-annuler-derogation="1">
                        ${Utils.escapeHtml(I18n.t('action.cancel'))}
                    </button>
                </div>
            </div>`;
    },

    /**
     * Le contrôle compensatoire que la dérogation citera.
     *
     * Facultatif, sauf si le workspace l'exige — l'écran le dit alors, parce
     * qu'une dérogation accordée sans contrôle y serait enregistrée mais ne
     * couvrirait rien.
     */
    renderLeChoixDuControle() {
        const exige = (this.bornes || {}).controle_exige === true;
        return `
            <label class="form-label" for="sod-controle">${
                Utils.escapeHtml(I18n.t('derogation.control'))}</label>
            <select class="form-input" id="sod-controle">
                <option value="">${Utils.escapeHtml(I18n.t('derogation.control.none'))}</option>
                ${this.controles.map((controle) => `<option value="${Utils.escapeHtml(controle.id)}"
                    ${controle.id === this.controleSaisi ? 'selected' : ''}>${
                    Utils.escapeHtml(controle.libelle)}</option>`).join('')}
            </select>
            ${exige ? `<span class="form-hint">${Utils.escapeHtml(
                I18n.t('derogation.control.required'))}</span>` : ''}`;
    },

    //: La dérogation dont le refus est en cours de saisie. Un refus a un
    //  motif : il se saisit avant de partir.
    refusEnCours: '',
    motifDeRefus: '',

    /**
     * Approuver ou refuser une dérogation demandée.
     *
     * Le serveur refuse que ce soit celui qui l'a demandée : une exception
     * approuvée par la personne qui en profite ne sépare rien. L'écran ne le
     * cache pas pour autant — le refus du serveur dit pourquoi, et c'est plus
     * juste qu'un bouton qui disparaît sans explication.
     */
    renderLaDecision(derogation) {
        const id = Utils.escapeHtml(derogation.id);
        if (this.refusEnCours === derogation.id) {
            // La même boîte que l'acceptation : empilée, d'une largeur
            // minimale, pour que le champ ne déborde pas sur la cellule voisine.
            return `
                <div class="sod-acceptation">
                    <label class="form-label" for="sod-motif-refus">${
                        Utils.escapeHtml(I18n.t('derogation.refusal_reason'))}</label>
                    <input type="text" class="form-input" id="sod-motif-refus" maxlength="500"
                           value="${Utils.escapeHtml(this.motifDeRefus)}">
                    <button type="button" class="btn btn-danger btn-sm"
                            data-sod-confirmer-refus="${id}">${
                        Utils.escapeHtml(I18n.t('derogation.refuse'))}</button>
                </div>`;
        }
        return `
            <button type="button" class="btn btn-primary btn-sm"
                    data-sod-approuver="${id}">${Utils.escapeHtml(I18n.t('derogation.approve'))}</button>
            <button type="button" class="btn btn-secondary btn-sm"
                    data-sod-refuser="${id}">${Utils.escapeHtml(I18n.t('derogation.refuse'))}</button>`;
    },

    async trancher(identifiant, accorder) {
        try {
            if (accorder) {
                await API.post(`/derogations/${encodeURIComponent(identifiant)}/approuver`, {});
            } else {
                await API.post(`/derogations/${encodeURIComponent(identifiant)}/refuser`,
                               {motif: this.motifDeRefus});
            }
        } catch (erreur) {
            Toast.error(I18n.t('common.error'), erreur.message);
            return;
        }
        Toast.success(I18n.t('common.success'),
                      I18n.t(accorder ? 'derogation.approved' : 'derogation.refused'));
        this.refusEnCours = '';
        this.motifDeRefus = '';
        await this.rafraichirApresDerogation(this.ouverte);
    },

    /** Le libellé d'un contrôle cité, ou rien. */
    libelleDuControle(identifiant) {
        if (!identifiant) return '';
        const controle = this.controles.find((candidat) => candidat.id === identifiant);
        return I18n.t('derogation.control.cited', {controle: controle ? controle.libelle : identifiant});
    },

    /** La date la plus lointaine que le workspace autorise. */
    echeanceMaximale() {
        const bornes = this.bornes || {};
        if (!bornes.aujourdhui || !bornes.duree_max_jours) return '';
        const jour = new Date(`${bornes.aujourdhui}T00:00:00Z`);
        jour.setUTCDate(jour.getUTCDate() + Number(bornes.duree_max_jours));
        return jour.toISOString().slice(0, 10);
    },

    // -- les couples candidats ---------------------------------------------

    renderLesCandidats() {
        const zone = document.getElementById('separation-candidats');
        if (!zone) return;
        if (!this.candidats.length) {
            zone.innerHTML = `<p class="form-hint">${
                Utils.escapeHtml(I18n.t('separation.candidates.none'))}</p>`;
            return;
        }
        zone.innerHTML = `<ul class="sod-candidats">${
            this.candidats.map((couple, rang) => `
            <li>
                <strong>${Utils.escapeHtml(couple.gauche)}</strong>
                / <strong>${Utils.escapeHtml(couple.droite)}</strong>
                <span class="form-hint">${Utils.escapeHtml(
                    I18n.t('separation.candidates.evidence', {
                        porteurs_gauche: Utils.formatNumber(couple.porteurs_gauche),
                        porteurs_droite: Utils.formatNumber(couple.porteurs_droite),
                        cumuls_attendus: Utils.formatNumber(couple.cumuls_attendus),
                        cumuls_observes: Utils.formatNumber(couple.cumuls_observes)}))}</span>
                <button type="button" class="btn btn-secondary btn-sm"
                        data-sod-couple="${rang}">
                    <i class="fas fa-plus" aria-hidden="true"></i>
                    <span>${Utils.escapeHtml(I18n.t('separation.candidates.take'))}</span>
                </button>
            </li>`).join('')}</ul>`;
    },

    /**
     * Retient un couple comme règle à écrire — sans la nommer ni l'enregistrer.
     *
     * Le produit ne sait pas nommer le contrôle interne d'un client, et une
     * règle enregistrée sans libellé serait une règle que personne ne pourra
     * relire.
     */
    retenirLeCouple(rang) {
        const couple = this.candidats[rang];
        if (!couple) return;
        this.ajouterUneRegle([{type: 'droit', id: couple.gauche, libelle: ''}],
                             [{type: 'droit', id: couple.droite, libelle: ''}]);
        Toast.success(I18n.t('common.success'),
                      I18n.t('separation.candidates.taken'));
    },

    /** Réaffiche l'écran dans la langue courante, sans le recharger. */
    rafraichirLangue() {
        this.renderLesRegles();
        this.renderLesConflits();
        this.renderLesCandidats();
        if (this.detail) this.renderLeDetail();
    },
};

window.SeparationPage = SeparationPage;
