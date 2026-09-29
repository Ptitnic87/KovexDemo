/**
 * La toile d'araignée : la forme d'un candidat, à côté de ses chiffres.
 *
 * Trois règles, qui sont celles de la note du 13 septembre :
 *
 * - **des axes de même sens**, tous sur 0-100, tous « plus haut = mieux ». Le
 *   serveur les rend ainsi ; ce module ne les retourne pas ;
 * - **les axes sont les grandeurs du score**, aucune inventée pour remplir ;
 * - **elle reste à côté des chiffres**, jamais à leur place. Elle se dessine
 *   en SVG, sans bibliothèque : le produit s'installe sur un serveur sans
 *   accès.
 *
 * La forme moyenne de ce que le workspace valide est dessinée en pointillé
 * sous celle du candidat : c'est l'écart entre les deux qui se lit.
 */
const Toile = {
    //: Géométrie du dessin, en unités de la boîte `viewBox` : le centre et le
    //  rayon de l'axe à 100. La taille affichée vient de la feuille de style.
    CENTRE: 50,
    RAYON: 42,
    //: Les anneaux intermédiaires, en valeur d'axe. Sans eux, un candidat
    //  proche de 100 sur tous les axes se confondait avec le cadre : rien ne
    //  disait où finissait l'un et où commençait l'autre.
    GRADUATIONS: [25, 50, 75],

    coordonnees(rang, total, valeur) {
        const angle = -Math.PI / 2 + (2 * Math.PI * rang) / total;
        const r = (Toile.RAYON * Math.max(0, Math.min(100, Number(valeur) || 0))) / 100;
        // Des coordonnées, pas un nombre affiché : arrondies au centième, et
        // toujours écrites avec un point, quelle que soit la langue.
        const arrondir = (valeur) => Math.round(valeur * 100) / 100;
        return [arrondir(Toile.CENTRE + r * Math.cos(angle)),
                arrondir(Toile.CENTRE + r * Math.sin(angle))];
    },

    polygone(axes, valeurs) {
        return axes.map((axe, rang) => Toile.coordonnees(rang, axes.length, valeurs[axe]).join(','))
            .join(' ');
    },

    /** La phrase qui dit la même chose que le dessin, pour qui ne le voit pas. */
    description(axes, candidat, reference) {
        return axes.map((axe) => I18n.t('apprentissage.toile.axe', {
            axe: I18n.t(`apprentissage.toile.${axe}`),
            valeur: Utils.formatNumber(candidat[axe]),
            reference: reference ? Utils.formatNumber(reference[axe]) : '—',
        })).join(' · ');
    },

    /**
     * Les axes écrits à côté du dessin, pour tous.
     *
     * Le dessin ne porte aucun libellé : à la taille d'une carte, un texte
     * dans le SVG serait illisible. Sans cette légende, seule la description
     * accessible nommait les axes — une forme sans axes nommés ne dit rien à
     * qui la regarde. La référence n'apparaît que lorsqu'il y en a une.
     */
    legende(axes, candidat, reference) {
        const lignes = axes.map((axe) => {
            const valeurs = {
                axe: I18n.t(`apprentissage.toile.${axe}`),
                valeur: Utils.formatNumber(candidat[axe]),
                reference: reference ? Utils.formatNumber(reference[axe]) : '',
            };
            const cle = reference ? 'apprentissage.toile.axe' : 'apprentissage.toile.axe_seul';
            return `<li>${Utils.escapeHtml(I18n.t(cle, valeurs))}</li>`;
        }).join('');
        return `<ul class="toile__legende" aria-label="${Utils.escapeHtml(
            I18n.t('apprentissage.toile.legende'))}">${lignes}</ul>`;
    },

    svg(axes, candidat, reference) {
        const description = Utils.escapeHtml(Toile.description(axes, candidat, reference));
        const rayons = axes.map((_, rang) => {
            const [x, y] = Toile.coordonnees(rang, axes.length, 100);
            return `<line class="toile__axe" x1="${Toile.CENTRE}" y1="${Toile.CENTRE}"
                x2="${x}" y2="${y}"></line>`;
        }).join('');
        const anneau = (valeur) => Toile.polygone(
            axes, Object.fromEntries(axes.map((axe) => [axe, valeur])));
        const graduations = Toile.GRADUATIONS.map((valeur) =>
            `<polygon class="toile__graduation" points="${anneau(valeur)}"></polygon>`).join('');
        // Les sommets du candidat sont marqués : sur le cadre ou sur un
        // anneau, un point reste lisible là où deux traits se superposent.
        const sommets = axes.map((axe, rang) => {
            const [x, y] = Toile.coordonnees(rang, axes.length, candidat[axe]);
            return `<circle class="toile__sommet" cx="${x}" cy="${y}"></circle>`;
        }).join('');
        return `<svg class="toile" viewBox="0 0 100 100" role="img" aria-label="${description}">
                <title>${description}</title>
                <polygon class="toile__cadre" points="${anneau(100)}"></polygon>
                ${graduations}
                ${rayons}
                ${reference ? `<polygon class="toile__reference" points="${
                    Toile.polygone(axes, reference)}"></polygon>` : ''}
                <polygon class="toile__candidat" points="${Toile.polygone(axes, candidat)}"></polygon>
                ${sommets}
            </svg>`;
    },
};

window.Toile = Toile;
