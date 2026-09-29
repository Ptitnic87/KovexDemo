"""Serveur de fichiers pour l'interface Kovex.

`python -m http.server` faisait le travail, à un défaut près qui coûtait cher :
il n'envoie aucun en-tête de cache, et les navigateurs appliquent alors une
heuristique. Résultat, après une livraison, `index.html` était resservi depuis
le cache et l'interface restait à l'ancienne version — un défaut corrigé
paraissait présent, ce qui fait chercher au mauvais endroit.

Les ressources portent bien un numéro de version dans leur URL, mais c'est
`index.html` qui déclare ce numéro : s'il est périmé, tout l'est.

Ce serveur sert donc l'interface avec `Cache-Control: no-store`. C'est du
service local d'une application interne : le coût est nul, la propriété est
acquise.
"""

import hashlib
import io
import os
import re
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from src.infrastructure.branding import VERSION_PRODUIT

RACINE = Path(__file__).resolve().parent / "frontend"

#: Port d'écoute. Réglable, comme tout le reste, par variable d'environnement.
PORT_PAR_DEFAUT = 3000

#: Balise du gabarit qui porte l'adresse de l'API.
BALISE_API = re.compile(
    rb'(<meta\s+name="kovex-api-url"\s+content=")[^"]*(">)', re.I)

#: Numéro de cache accolé aux feuilles de style et aux scripts.
#:
#: Il était figé dans le gabarit et n'avait jamais suivi les versions du
#: produit : une mise à jour laissait chaque poste sur l'ancienne interface
#: jusqu'à ce que son utilisateur vide son cache — et rien ne le lui disait.
#: Le serveur y reporte désormais la version, comme il reporte l'adresse de
#: l'API : le gabarit livré n'a plus à être exact, il a à être remplaçable.
#: Le numéro de cache est désormais une empreinte : un hexadécimal, jamais un
#: numéro de version. Le motif accepte les deux — le gabarit livré porte encore
#: une version, et c'est sans conséquence puisqu'il est réécrit au service.
NUMERO_DE_CACHE = re.compile(rb'(\?v=)[0-9a-zA-Z][0-9A-Za-z.\-]*')

#: Extensions des ressources dont le navigateur garde une copie. Le gabarit
#: lui-même n'y figure pas : il est servi sans cache, et c'est lui qui porte
#: les clés des autres.
EXTENSIONS_SERVIES = (".js", ".css", ".svg", ".woff", ".woff2", ".ttf", ".png",
                      ".jpg", ".jpeg", ".webp", ".ico")

#: Longueur de l'empreinte. Douze hexadécimaux suffisent à distinguer deux
#: états du produit ; l'allonger n'ajoute qu'à la longueur des adresses.
LONGUEUR_DE_L_EMPREINTE = 12

#: Emplacement où la version s'affiche, en bas de la barre latérale.
VERSION_AFFICHEE = re.compile(rb'(<span data-kovex-version>)[^<]*(</span>)')


class ServeurInterface(SimpleHTTPRequestHandler):
    """Sert le dossier `frontend/` sans jamais autoriser la mise en cache.

    Il reporte aussi l'adresse de l'API dans le gabarit. Elle était écrite en
    dur dans `frontend/js/config.js` : déplacer l'API sur un autre hôte ou un
    autre port obligeait à modifier un fichier livré, et l'interface se
    contentait de ne plus répondre.
    """

    def guess_type(self, path):
        """Déclare l'encodage des ressources textuelles.

        Sans `charset`, le navigateur retombe sur l'encodage du document pour
        les scripts classiques : cela fonctionne tant que la page le déclare,
        et cesse dès qu'un script est chargé seul.
        """
        type_devine = super().guess_type(path)
        if (type_devine.startswith(("text/", "application/javascript"))
                and "charset=" not in type_devine):
            return f"{type_devine}; charset=utf-8"
        return type_devine

    def send_head(self):
        """Sert le gabarit avec l'adresse de l'API du moment."""
        chemin = self.translate_path(self.path)
        if not sert_le_gabarit(chemin):
            return super().send_head()

        gabarit = Path(chemin)
        if gabarit.is_dir():
            gabarit = gabarit / "index.html"
        if not gabarit.is_file():
            return super().send_head()

        contenu = version_reportee(adresse_reportee(gabarit.read_bytes()))
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(contenu)))
        self.end_headers()
        return io.BytesIO(contenu)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        # L'interface est servie à un navigateur local : rien ne justifie
        # qu'elle soit encadrable par une autre page.
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def log_message(self, format, *args):
        # Une ligne par ressource noierait la console de démarrage ; seules
        # les erreurs méritent d'y figurer.
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(format, *args)


def sert_le_gabarit(chemin: str) -> bool:
    """Cette requête doit-elle recevoir `index.html` réécrit ?

    La demande d'un dossier était reconnue par `chemin.endswith(os.sep)`, ce
    qui est faux sous Windows : `translate_path` compose le chemin avec des
    contre-obliques, puis ajoute une **barre oblique** littérale pour marquer
    le dossier — le code de la bibliothèque standard écrit `path += '/'`, pas
    `os.sep`.

    Conséquence, sous Windows uniquement : ouvrir `http://localhost:3000/`,
    c'est-à-dire la façon normale d'accéder à l'interface, servait le gabarit
    **sans** y reporter l'adresse de l'API. Seul `/index.html` fonctionnait.
    L'interface visait alors l'adresse écrite dans le fichier livré, et le
    réglage par variable d'environnement restait sans effet.
    """
    return chemin.endswith("index.html") or chemin.endswith(("/", os.sep))


def adresse_de_l_api() -> str:
    """Adresse déclarée par l'exploitant, ou rien.

    Rien signifie « ne touche pas au gabarit » : la valeur qu'il porte fait
    foi, et un déploiement derrière un relais peut la vider pour que
    l'interface vise sa propre origine.
    """
    return os.environ.get("KOVEX_API_URL", "").strip()


def adresse_reportee(gabarit: bytes) -> bytes:
    """Remplace le contenu de la balise `kovex-api-url` par l'adresse déclarée."""
    adresse = adresse_de_l_api()
    if not adresse:
        return gabarit
    # `re.sub` avec une fonction : une adresse contenant une barre oblique
    # inverse serait autrement interprétée comme une référence de groupe.
    valeur = adresse.encode("utf-8")
    return BALISE_API.sub(lambda trouve: trouve.group(1) + valeur + trouve.group(2),
                          gabarit, count=1)


def empreinte_des_ressources(racine: Path = None) -> str:
    """Empreinte courte du contenu réellement servi au navigateur.

    Le numéro de cache était la version du produit. C'était juste dans
    l'intention et faux en pratique : `VERSION_PRODUIT` n'a pas bougé pendant
    treize lots consécutifs, dont trois qui ont refait la barre latérale, la
    palette et le chargement du logo. Toutes ces feuilles de style et tous ces
    scripts ont donc été servis sous la même clé, et un navigateur qui avait
    déjà ouvert la page n'avait aucune raison de les redemander. Les postes
    restaient sur l'ancienne interface, silencieusement, jusqu'à ce que
    quelqu'un vide son cache — ce qui n'arrive que si quelqu'un soupçonne le
    problème.

    Le remède n'est pas plus de discipline. Personne n'a oublié treize fois par
    négligence : c'est que faire dépendre la justesse du cache d'un geste
    humain était le mauvais montage. La clé est donc dérivée du contenu — nom
    et octets de chaque ressource servie. Elle change exactement quand un
    fichier change, et jamais autrement.

    `VERSION_PRODUIT` retrouve son seul rôle légitime : un numéro qui parle aux
    humains, affiché en bas de la barre, qu'on fait monter quand on a quelque
    chose à leur dire.
    """
    racine = RACINE if racine is None else racine
    condensat = hashlib.sha256()
    for chemin in sorted(racine.rglob("*")):
        if not chemin.is_file():
            continue
        if chemin.suffix.lower() not in EXTENSIONS_SERVIES:
            continue
        # Le nom entre dans l'empreinte : renommer un fichier change ce que le
        # navigateur doit aller chercher, au même titre que le modifier.
        condensat.update(chemin.relative_to(racine).as_posix().encode("utf-8"))
        condensat.update(chemin.read_bytes())
    return condensat.hexdigest()[:LONGUEUR_DE_L_EMPREINTE]


def version_reportee(gabarit: bytes, empreinte: str = None) -> bytes:
    """Aligne l'affichage sur la version du produit, et le cache sur le contenu.

    Les deux disaient autre chose, et pas la même : « 4.4.0 » pour le cache,
    « 2.1.0 » en bas de la barre latérale. Un utilisateur qui lit la seconde ne
    peut pas savoir que son navigateur lui sert encore la première. Ils ne
    disent plus la même chose non plus, mais désormais c'est voulu : l'un
    nomme une livraison, l'autre identifie un contenu.
    """
    if empreinte is None:
        empreinte = empreinte_des_ressources()
    cle = empreinte.encode("utf-8")
    valeur = VERSION_PRODUIT.encode("utf-8")
    gabarit = NUMERO_DE_CACHE.sub(lambda trouve: trouve.group(1) + cle, gabarit)
    return VERSION_AFFICHEE.sub(
        lambda trouve: trouve.group(1) + b"v" + valeur + trouve.group(2), gabarit)


def main() -> int:
    if not RACINE.is_dir():
        print(f"[ERREUR] Dossier introuvable : {RACINE}", file=sys.stderr)
        return 1

    port = int(os.environ.get("KOVEX_FRONTEND_PORT", PORT_PAR_DEFAUT))
    adresse = os.environ.get("KOVEX_FRONTEND_HOST", "127.0.0.1")

    gestionnaire = partial(ServeurInterface, directory=str(RACINE))
    with ThreadingHTTPServer((adresse, port), gestionnaire) as serveur:
        print(f"Interface Kovex servie sur http://{adresse}:{port}")
        declaree = adresse_de_l_api()
        if declaree:
            print(f"API declaree : {declaree}")
        print("Ctrl+C pour arreter.")
        try:
            serveur.serve_forever()
        except KeyboardInterrupt:
            print("\nArret de l'interface.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
