/**
 * Indicateur de travail en attente.
 *
 * La cloche de la barre supérieure portait une pastille rouge écrite dans le
 * gabarit : elle était allumée en permanence, sur une application vide comme
 * sur une revue terminée, et aucun code ne la regardait. Un indicateur toujours
 * allumé n'informe pas — il apprend à ne plus regarder, et c'est une propriété
 * coûteuse sur un produit de gouvernance, où le signal qu'on finit par ignorer
 * est celui d'un accès à revoir.
 *
 * Ce module en fait autre chose : **ce qu'il reste à décider**, et rien de
 * plus. Ce n'est pas un flux d'événements, et il n'y a pas de « nouveautés »
 * ni de notifications lues ou non lues. La question posée est celle d'un
 * responsable d'habilitations devant son écran : « un calcul a proposé des
 * rôles ; combien attendent encore ma décision ? » La réponse se déduit des
 * candidats conservés et des décisions prises — rien n'est stocké pour elle,
 * donc rien ne peut se désynchroniser.
 *
 * Trois règles tiennent l'indicateur honnête :
 *
 * 1. **Zéro s'efface.** Aucune pastille quand il n'y a rien à décider.
 * 2. **Le compte est daté.** Un mining conservé peut porter sur des données
 *    rechargées depuis : le panneau le dit, il ne masque pas le travail pour
 *    autant — il existe toujours.
 * 3. **Chaque ligne mène à l'écran concerné.** Un compteur sur lequel on ne
 *    peut pas agir est une décoration.
 *
 * Le nom accessible du bouton porte le compte : à la synthèse vocale, une
 * pastille colorée ne dit rien. Il est reconstruit à chaque rafraîchissement
 * et à chaque changement de langue, jamais figé dans le gabarit.
 */
const Cloche = {

    /** Point d'entrée du serveur. Le calcul est côté serveur, pas ici. */
    ROUTE: '/kb/pending-work',

    /** Dernier état connu, tel que rendu par le serveur. */
    etat: null,

    _ouverte: false,
    _initialisee: false,

    /** Le bouton de la barre supérieure. */
    get bouton() {
        return document.getElementById('notifications-btn');
    },

    /** Le panneau déroulant. */
    get panneau() {
        return document.getElementById('cloche-panneau');
    },

    /**
     * Met la cloche en service. Sans le bouton dans la page, il n'y a rien à
     * faire : le module doit rester chargeable par un test qui n'a pas le
     * gabarit complet.
     */
    init() {
        const bouton = this.bouton;
        if (!bouton || this._initialisee) return;
        this._initialisee = true;

        bouton.addEventListener('click', (evenement) => {
            evenement.stopPropagation();
            this.basculer();
        });

        // Une liste déroulante se referme sur Échap et sur un clic à côté.
        // Sans cela, elle reste ouverte derrière l'écran suivant.
        document.addEventListener('keydown', (evenement) => {
            if (evenement.key === 'Escape' && this._ouverte) {
                this.fermer({rendreLeFocus: true});
            }
        });
        document.addEventListener('click', (evenement) => {
            if (!this._ouverte) return;
            const panneau = this.panneau;
            if (panneau && !panneau.contains(evenement.target)) this.fermer();
        });

        this.rafraichir();
    },

    /**
     * Relit le travail en attente et met l'affichage à jour.
     *
     * Appelée au démarrage et après chaque décision ou chaque mining : le
     * compte doit suivre l'action de l'utilisateur sans qu'il ait à recharger
     * la page. Une panne de lecture n'affiche rien plutôt qu'un faux zéro :
     * annoncer « rien à faire » parce que le serveur n'a pas répondu serait le
     * seul mensonge inacceptable pour cet indicateur.
     */
    async rafraichir() {
        if (!this.bouton) return;
        try {
            this.etat = await API.get(this.ROUTE);
        } catch (erreur) {
            this.etat = null;
        }
        this.rendre();
    },

    /** Nombre de décisions en attente, tous types confondus. */
    get total() {
        return this.etat ? Number(this.etat.total) || 0 : 0;
    },

    /**
     * Met le bouton et le panneau en accord avec le dernier état lu.
     */
    rendre() {
        const bouton = this.bouton;
        if (!bouton) return;

        const total = this.total;
        const pastille = document.getElementById('cloche-pastille');
        if (pastille) {
            pastille.hidden = total === 0;
            // Le compte est écrit dans la pastille : une couleur seule ne dit
            // pas combien, et elle ne dit rien du tout à qui ne la voit pas.
            pastille.textContent = total > 0 ? String(total) : '';
        }

        bouton.setAttribute(
            'aria-label',
            total > 0
                ? I18n.t('pending.bell_with_work', {count: total})
                : I18n.t('pending.bell_empty'));

        if (this._ouverte) this.rendrePanneau();
    },

    /** Ouvre ou referme le panneau. */
    basculer() {
        if (this._ouverte) {
            this.fermer({rendreLeFocus: true});
        } else {
            this.ouvrir();
        }
    },

    ouvrir() {
        const panneau = this.panneau;
        const bouton = this.bouton;
        if (!panneau || !bouton) return;
        this._ouverte = true;
        bouton.setAttribute('aria-expanded', 'true');
        panneau.hidden = false;
        this.rendrePanneau();
        // Le contenu est relu à l'ouverture : il a pu changer depuis le
        // dernier rafraîchissement, et c'est le moment où on le regarde.
        this.rafraichir();
    },

    fermer({rendreLeFocus = false} = {}) {
        const panneau = this.panneau;
        const bouton = this.bouton;
        if (!panneau || !bouton) return;
        this._ouverte = false;
        panneau.hidden = true;
        bouton.setAttribute('aria-expanded', 'false');
        if (rendreLeFocus) bouton.focus();
    },

    /**
     * Le contenu du panneau : une ligne par type de rôle ayant du travail.
     *
     * Un type sans candidat en attente n'apparaît pas. Afficher « 0 » pour
     * chaque type transformerait un état vide en tableau à lire.
     */
    rendrePanneau() {
        const panneau = this.panneau;
        if (!panneau) return;

        const titre = `<h2 id="cloche-titre" class="cloche-titre">${
            Utils.escapeHtml(I18n.t('pending.title'))}</h2>`;

        if (!this.etat) {
            panneau.innerHTML = titre + `<p class="cloche-vide">${
                Utils.escapeHtml(I18n.t('pending.unavailable'))}</p>`;
            return;
        }

        const lignes = (this.etat.types || []).filter(type => Number(type.undecided) > 0);
        if (!lignes.length) {
            panneau.innerHTML = titre + `<p class="cloche-vide">${
                Utils.escapeHtml(I18n.t('pending.empty'))}</p>`;
            return;
        }

        panneau.innerHTML = titre + `
            <ul class="cloche-liste">
                ${lignes.map(type => this.rendreLigne(type)).join('')}
            </ul>`;

        panneau.querySelectorAll('[data-cloche-page]').forEach(element => {
            element.addEventListener('click', () => {
                this.fermer();
                App.navigateTo(element.dataset.clochePage);
            });
        });
    },

    /** Une ligne : le type, son compte, sa date, et où aller pour agir. */
    rendreLigne(type) {
        const page = Config.PAGES_PAR_TYPE_DE_ROLE[type.role_type];
        const libelle = I18n.t(`pending.role_type.${type.role_type}`);
        const compte = I18n.t('pending.undecided', {
            count: Number(type.undecided) || 0,
            total: Number(type.candidates) || 0,
        });
        const date = type.computed_at
            ? new Date(type.computed_at).toLocaleString(I18n.currentLocale || undefined)
            : '';
        const calcule = date
            ? `<span class="cloche-date">${Utils.escapeHtml(I18n.t('pending.computed_at', {date}))}</span>`
            : '';
        // L'obsolescence est signalée par un mot, pas par une seule couleur :
        // une icône rouge sans texte n'est pas une information.
        const obsolete = type.stale
            ? `<span class="cloche-obsolete">
                   <i class="fas fa-triangle-exclamation" aria-hidden="true"></i>
                   ${Utils.escapeHtml(I18n.t('pending.stale'))}
               </span>`
            : '';

        return `<li class="cloche-ligne">
                    <button type="button" class="cloche-lien" data-cloche-page="${
                        Utils.escapeHtml(page || '')}">
                        <span class="cloche-libelle">${Utils.escapeHtml(libelle)}</span>
                        <span class="cloche-compte">${Utils.escapeHtml(compte)}</span>
                        ${calcule}
                        ${obsolete}
                    </button>
                </li>`;
    },

    /**
     * Le contenu de la cloche est écrit par ce module : `applyTranslations`
     * ne le voit pas. Sans ce point d'entrée, changer de langue laissait le
     * compte et son panneau dans la langue précédente.
     */
    rafraichirLangue() {
        this.rendre();
    },
};

if (typeof window !== 'undefined') window.Cloche = Cloche;
