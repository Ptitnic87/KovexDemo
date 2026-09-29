/**
 * Application d'un thème de workspace.
 *
 * Le thème arrive de l'API sous la forme de couples jeton/couleur, déjà
 * validés côté serveur — liste blanche de jetons dérivée de la feuille de
 * style, couleurs contraintes, contrat de contraste rejoué. Le même filtre est
 * réappliqué ici : c'est la barrière la moins coûteuse à tenir et la seule qui
 * protège si la réponse ne vient pas de là où on croit.
 *
 * Les jetons sont posés un par un sur l'élément racine avec `setProperty`.
 * Aucune feuille de style n'est fabriquée par concaténation : une valeur
 * inattendue ne peut donc rien fermer ni rien ouvrir, elle est simplement
 * refusée par le navigateur.
 *
 * La variante — sombre ou clair — reste un réglage personnel. Un thème client
 * porte les deux, et c'est la variante affichée qui décide laquelle est peinte
 * à chaque bascule.
 */
const ThemeVisuel = {
    /** Un nom de jeton : lettres minuscules, chiffres, traits d'union. */
    MOTIF_JETON: /^[a-z0-9][a-z0-9-]*$/,

    /** Une couleur pleine, six chiffres hexadécimaux. */
    MOTIF_COULEUR: /^#[0-9a-fA-F]{6}$/,

    /** Identifiant du thème d'origine : il n'a rien à peindre. */
    IDENTIFIANT_PAR_DEFAUT: 'default',

    /** Thème appliqué, tel que renvoyé par l'API. */
    themeCourant: null,

    /** Jetons effectivement posés, pour savoir quoi retirer à la bascule. */
    jetonsPoses: [],

    /**
     * Applique un thème, ou revient à la palette d'origine si `theme` est nul.
     */
    appliquer(theme) {
        this.retirer();
        // Le logo appartient au thème qu'on quitte : il part avec lui, sans
        // quoi la marque du client précédent resterait affichée le temps de la
        // lecture du nouveau logo — ou pour toujours, si le nouveau n'en a pas.
        this.effacerLogo(document.getElementById('theme-logo-client'));
        this.themeCourant = theme && theme.variantes ? theme : null;
        this.peindre();
        return this.rendreLogo();
    },

    /** Retire les jetons posés : la feuille de style reprend la main. */
    retirer() {
        const racine = document.documentElement;
        this.jetonsPoses.forEach((jeton) => racine.style.removeProperty(jeton));
        this.jetonsPoses = [];
    },

    /**
     * Peint la variante actuellement affichée.
     *
     * Appelée à chaque bascule sombre/clair : sans cela, un thème appliqué en
     * sombre resterait peint tel quel en clair, c'est-à-dire faux.
     */
    peindre() {
        if (!this.themeCourant) return;
        const racine = document.documentElement;
        const variante = racine.getAttribute('data-theme');
        const jetons = this.themeCourant.variantes[variante];
        if (!jetons) return;

        this.retirer();
        Object.keys(jetons).forEach((jeton) => {
            const couleur = jetons[jeton];
            if (!this.MOTIF_JETON.test(jeton)) return;
            if (typeof couleur !== 'string' || !this.MOTIF_COULEUR.test(couleur)) return;
            const propriete = `--${jeton}`;
            racine.style.setProperty(propriete, couleur);
            this.jetonsPoses.push(propriete);
        });
    },

    /** Le libellé du thème dans la langue courante, ou son identifiant. */
    libelle(theme) {
        if (!theme) return '';
        if (theme.cle_du_libelle) return I18n.t(theme.cle_du_libelle);
        const libelles = theme.libelles || {};
        return libelles[I18n.currentLocale] || libelles.en
            || libelles[Object.keys(libelles)[0]] || theme.identifiant;
    },

    /** URL d'objet du logo affiché, à révoquer avant d'en poser une autre. */
    adresseDuLogo: null,

    /** Retire le logo et libère l'URL d'objet qu'il occupait. */
    effacerLogo(image) {
        if (this.adresseDuLogo) {
            URL.revokeObjectURL(this.adresseDuLogo);
            this.adresseDuLogo = null;
        }
        if (!image) return;
        image.hidden = true;
        image.removeAttribute('src');
        image.alt = '';
    },

    /**
     * Affiche ou retire le logo du client.
     *
     * Le logo s'ajoute à la marque du produit, il ne la remplace pas : l'outil
     * reste identifiable par celui qui s'en sert.
     *
     * Il est lu par un appel authentifié, puis posé sous forme d'URL d'objet.
     * Une balise `<img src>` pointant directement sur l'API ne sait pas porter
     * le jeton : elle recevait un 401, et l'écran affichait le texte de
     * remplacement à la place du logo. L'URL précédente est révoquée à chaque
     * changement, sinon chaque bascule de thème laisserait une image en
     * mémoire pour toute la durée de la session.
     */
    async rendreLogo() {
        const image = document.getElementById('theme-logo-client');
        if (!image) return;
        const theme = this.themeCourant;
        if (!theme || !theme.logo || !this.workspaceCourant) {
            this.effacerLogo(image);
            return;
        }
        const libelle = this.libelle(theme);
        // Le libellé est traduit : un changement de langue repasse ici sans
        // que le thème ait bougé, et il ne faut pas relire l'image pour ça.
        if (this.adresseDuLogo) {
            image.alt = libelle;
            return;
        }
        try {
            const contenu = await API.blob(
                `/workspaces/${encodeURIComponent(this.workspaceCourant)}`
                + `/themes/${encodeURIComponent(theme.identifiant)}/logo`);
            this.adresseDuLogo = URL.createObjectURL(contenu);
        } catch (erreur) {
            // Un logo illisible n'empêche pas l'habillage : les couleurs sont
            // déjà posées, et une marque absente vaut mieux qu'une icône brisée.
            this.effacerLogo(image);
            return;
        }
        image.src = this.adresseDuLogo;
        image.alt = libelle;
        image.hidden = false;
    },

    /** Workspace dont le thème est appliqué. */
    workspaceCourant: null,

    /**
     * Charge et applique le thème d'un workspace.
     *
     * Une panne de lecture laisse la palette d'origine : un habillage absent
     * est un désagrément, un écran illisible est une panne.
     */
    async charger(workspaceId, identifiant) {
        this.workspaceCourant = workspaceId;
        if (!workspaceId || !identifiant || identifiant === this.IDENTIFIANT_PAR_DEFAUT) {
            this.appliquer(null);
            return null;
        }
        try {
            const reponse = await API.get(
                `/workspaces/${encodeURIComponent(workspaceId)}/themes`);
            const themes = (reponse && reponse.themes) || [];
            const theme = themes.find((candidat) => candidat.identifiant === identifiant);
            this.appliquer(theme || null);
            return theme || null;
        } catch (erreur) {
            this.appliquer(null);
            return null;
        }
    },
};

if (typeof window !== 'undefined') window.ThemeVisuel = ThemeVisuel;
