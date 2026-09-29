/**
 * Rendu Markdown minimal, sûr par construction.
 *
 * Aucune bibliothèque n'est embarquée pour cela : le produit doit tourner sur
 * un serveur sans accès sortant, et ajouter une dépendance de plusieurs
 * milliers de lignes pour afficher quatre manuels est un mauvais échange.
 *
 * La règle de sûreté tient en une phrase : **tout est échappé d'abord**, puis
 * seule une liste fermée de motifs réintroduit du balisage. Un rendu qui
 * laisse passer le HTML de la source, même « de confiance », finit toujours
 * par exécuter quelque chose ; ici c'est structurellement impossible.
 */

const Markdown = {
    echapper(texte) {
        return String(texte)
            // Le caractère nul sert de marqueur interne pendant le rendu en
            // ligne : le retirer de la source évite qu'un document forgé
            // n'aille s'y confondre.
            .replace(/\u0000/g, '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    },

    /** Motifs en ligne, appliqués sur du texte déjà échappé. */
    enLigne(texte) {
        // Le code littéral est mis de côté avant tout le reste : `**` dans un
        // exemple de code ne doit pas devenir du gras. La version précédente
        // l'annonçait sans le faire — elle produisait bien `<code>…</code>`,
        // puis appliquait les autres motifs à l'intérieur, si bien qu'un
        // extrait de documentation montrant la syntaxe Markdown la voyait
        // interprétée.
        const litteraux = [];
        let resultat = String(texte).replace(/`([^`]+)`/g, (_, contenu) => {
            litteraux.push(contenu);
            return `\u0000${litteraux.length - 1}\u0000`;
        });

        resultat = resultat
            .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
            .replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>')
            // Seules les cibles internes sont acceptées : une documentation
            // embarquée n'a aucune raison de pointer vers l'extérieur, et un
            // serveur isolé ne pourrait pas les atteindre.
            .replace(/\[([^\]]+)\]\((#[^)\s]*)\)/g, '<a href="$2">$1</a>');

        return resultat.replace(/\u0000(\d+)\u0000/g,
            (_, indice) => `<code>${litteraux[Number(indice)]}</code>`);
    },

    /**
     * Convertit un document Markdown en HTML.
     *
     * Sous-ensemble volontairement restreint : titres, paragraphes, listes à
     * puces et numérotées, blocs de code, tableaux, citations, séparateurs.
     * C'est ce que la documentation utilise, et rien de plus.
     */
    rendre(source) {
        const lignes = this.echapper(source || '').split('\n');
        const sortie = [];
        let dansCode = false;
        let liste = null;      // 'ul' | 'ol' | null
        let tableau = false;

        const fermerListe = () => {
            if (liste) { sortie.push(`</${liste}>`); liste = null; }
        };
        const fermerTableau = () => {
            if (tableau) { sortie.push('</tbody></table></div>'); tableau = false; }
        };

        for (let i = 0; i < lignes.length; i += 1) {
            const ligne = lignes[i];

            if (ligne.trim().startsWith('```')) {
                fermerListe(); fermerTableau();
                sortie.push(dansCode ? '</code></pre>' : '<pre><code>');
                dansCode = !dansCode;
                continue;
            }
            if (dansCode) { sortie.push(ligne); continue; }

            // Tableau : une ligne de cellules suivie d'une ligne de tirets.
            const suivante = lignes[i + 1] || '';
            if (!tableau && ligne.includes('|')
                && /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(suivante)) {
                fermerListe();
                const entetes = this.cellules(ligne);
                // Le rôle et la clé de libellé sont posés ici : une enveloppe
                // qui défile doit s'annoncer, et celle-ci n'existe pas dans le
                // gabarit. `I18n.applyTranslations` résout la clé, y compris
                // après un changement de langue.
                sortie.push('<div class="doc-table-wrapper" role="region"'
                    + ' data-i18n-aria-label="aria.region.table_documentation">'
                    + '<table class="doc-table"><thead><tr>'
                    + entetes.map((c) => `<th scope="col">${this.enLigne(c)}</th>`).join('')
                    + '</tr></thead><tbody>');
                tableau = true;
                i += 1;
                continue;
            }
            if (tableau) {
                if (ligne.includes('|')) {
                    sortie.push('<tr>' + this.cellules(ligne)
                        .map((c) => `<td>${this.enLigne(c)}</td>`).join('') + '</tr>');
                    continue;
                }
                fermerTableau();
            }

            const titre = ligne.match(/^(#{1,4})\s+(.*)$/);
            if (titre) {
                fermerListe();
                const niveau = titre[1].length;
                sortie.push(`<h${niveau}>${this.enLigne(titre[2])}</h${niveau}>`);
                continue;
            }

            if (/^\s*(---|\*\*\*)\s*$/.test(ligne)) {
                fermerListe();
                sortie.push('<hr>');
                continue;
            }

            const puce = ligne.match(/^\s*[-*]\s+(.*)$/);
            if (puce) {
                if (liste !== 'ul') { fermerListe(); sortie.push('<ul>'); liste = 'ul'; }
                sortie.push(`<li>${this.enLigne(puce[1])}</li>`);
                continue;
            }

            const numero = ligne.match(/^\s*\d+\.\s+(.*)$/);
            if (numero) {
                if (liste !== 'ol') { fermerListe(); sortie.push('<ol>'); liste = 'ol'; }
                sortie.push(`<li>${this.enLigne(numero[1])}</li>`);
                continue;
            }

            const citation = ligne.match(/^\s*&gt;\s?(.*)$/);
            if (citation) {
                fermerListe();
                sortie.push(`<blockquote>${this.enLigne(citation[1])}</blockquote>`);
                continue;
            }

            if (ligne.trim() === '') { fermerListe(); continue; }

            fermerListe();
            sortie.push(`<p>${this.enLigne(ligne)}</p>`);
        }

        fermerListe();
        fermerTableau();
        if (dansCode) sortie.push('</code></pre>');
        return sortie.join('\n');
    },

    cellules(ligne) {
        return ligne.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|')
            .map((cellule) => cellule.trim());
    },
};

window.Markdown = Markdown;
