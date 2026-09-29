# Handbuch für Administratoren

Dieses Handbuch richtet sich an die Person, die Kovex installiert,
konfiguriert und betreibt.

## Entwurfsvorgabe

Kovex ist dafür gedacht, **vollständig lokal auf einem Server ohne
ausgehenden Zugang** zu laufen. Keine Funktion ruft einen externen Dienst auf.
Das hat zwei Folgen: die Abhängigkeiten müssen installiert werden, bevor der
Server isoliert wird, und nichts im Produkt „aktualisiert sich von selbst".

## Installation

1. Python 3.11 oder neuer.
2. `pip install -r requirements.lock` — **auf einer Maschine mit
   Netzwerkzugang** oder aus einem internen Paketbestand. Auf dem isolierten
   Server schlägt dieser Befehl mangels Netzwerk fehl; verwenden Sie dann
   `pip install --no-index --find-links <Ordner> -r requirements.lock`.
   `requirements.lock` fixiert genau die Versionen, die die Testsuite
   ausgeführt hat; `requirements.txt` trägt nur Untergrenzen und dient der
   Entwicklung.
3. `.env.example` nach `.env` kopieren. `START_KOVEX.bat` legt die Datei
   automatisch an, wenn sie fehlt, mit einem zufällig gezogenen
   Signaturschlüssel.
4. `START_KOVEX.bat` starten. `STOP_KOVEX.bat` hält beide Server an.

## Starten ohne das Skript

Das Windows-Skript reiht nur zwei Befehle aneinander. Auf einem anderen System
oder um beide Hälften getrennt zu starten:

```
python run_api.py            # API,            http://127.0.0.1:8000
python serve_frontend.py     # Benutzeroberfläche, http://127.0.0.1:3000
```

Beide müssen gleichzeitig laufen, in zwei Terminals. Ports und Adressen werden
über `KOVEX_API_PORT`, `KOVEX_API_HOST`, `KOVEX_FRONTEND_PORT` und
`KOVEX_FRONTEND_HOST` eingestellt.

`serve_frontend.py` ist kein einfacher Dateiserver: er liefert die Oberfläche
mit `Cache-Control: no-store` aus. Andernfalls liefert der Browser nach einer
Aktualisierung eine zwischengespeicherte `index.html`, und die Oberfläche
bleibt auf der alten Fassung, obwohl die Korrektur ausgeliefert ist — was die
Fehlersuche an die falsche Stelle führt.

Beim ersten Start wird ein Administratorkonto mit einem **einmalig
angezeigten Zufallskennwort** in der API-Konsole angelegt. Notieren Sie es. Es
gibt kein Standardkonto, und das ist gewollt: ein Standardkennwort in einem
Produkt für Identitätsverwaltung ist ein Widerspruch.

## Konfiguration

Alles wird über Umgebungsvariablen in `.env` eingestellt. Jede einzelne ist in
`docs/02-parametres.md` beschrieben. Die wichtigsten:

| Variable | Wirkung |
|---|---|
| `PYGIA_SECRET_KEY` | Signaturschlüssel der Token. **Je Installation eindeutig.** Ein geteilter Schlüssel erlaubt es, anderswo ein gültiges Administrator-Token zu erzeugen. |
| `PYGIA_ENV` | `production` weist gefährliche Kombinationen beim Start zurück. |
| `PYGIA_AUTH_DISABLED` | Schaltet die Authentifizierung ab. In Produktion abgelehnt. Niemals auf einer ausgelieferten Instanz aktivieren. |
| `PYGIA_RATE_LIMIT` | Ratenbegrenzung. Sie abzuschalten nimmt die einzige Bremse gegen einen Brute-Force-Angriff auf die Anmeldung. |
| `PYGIA_ALLOWED_ORIGINS` | Von CORS zugelassene Ursprünge. |
| `PYGIA_AUDIT_FILE` | Ablageort des Prüfpfads. |

## Workspaces

Ein Workspace isoliert die Daten, die Konfiguration und die Wissensbasis eines
Kunden oder einer Umgebung. Einen Workspace anzulegen erzeugt seinen
Verzeichnisbaum; ihn zu löschen archiviert seine Wissensbasis, bevor der Rest
gelöscht wird.

Der Prüfpfad lebt **außerhalb der Workspaces**. Einen Workspace zu löschen darf
die Geschichte der darauf getroffenen Entscheidungen nicht löschen.

## Visuelle Themen

Die Anwendung öffnet sich in den Farben des Produkts. Ein Workspace kann die
seines Kunden tragen: Ein **Thema** ist ein Ordner unter `themes/` im Ordner
des Workspace, der eine Datei `theme.json` und bei Bedarf ein Logo enthält.

```
workspaces/<workspace>/themes/<themenname>/theme.json
workspaces/<workspace>/themes/<themenname>/logo.png
```

Die Datei deklariert ihre Bezeichnungen je Sprache, ihre Farben je
Anzeigevariante und den Namen ihres Logos:

```json
{
  "libelles": { "fr": "Nom affiché", "en": "Displayed name", "de": "Angezeigter Name" },
  "logo": "logo.png",
  "variantes": {
    "dark":  { "accent-primary": "#6d28d9", "encre-primary": "#c4b5fd" },
    "light": { "accent-primary": "#5b21b6", "encre-primary": "#5b21b6" }
  }
}
```

Drei Regeln, und eine Ablehnung nennt stets die verfehlte:

- **Beide Varianten sind erforderlich**, mit denselben Token auf beiden
  Seiten. Ein Thema, das nur die dunkle Anzeige gestaltet, ließe die helle in
  den Farben des Produkts, und der Bildschirm wechselte je nach persönlicher
  Einstellung die Identität.
- **Nur die Farbtoken des Stylesheets sind neu definierbar**, mit einem
  sechsstelligen Hexadezimalwert. Ein Verlauf, ein transluzenter Schleier oder
  eine berechnete Mischung bleiben außer Reichweite: Sie durch eine Volltonfarbe
  zu ersetzen würde ihre Wirkung zerstören.
- **Der Kontrast wird neu berechnet**, auf der entstehenden Palette und nach
  demselben WCAG-AA-Vertrag wie die ursprüngliche Palette. Ein Thema, das einen
  Text unlesbar macht, wird abgelehnt, und der Grund nennt das fehlerhafte Paar
  mit seinem Verhältnis.

Das Logo wird nach seinen Bytes beurteilt, nicht nach seinem Namen. Akzeptiert
werden PNG, JPEG und WebP; das Vektorformat nicht, denn ein SVG ist ein
Dokument, das Skript enthalten kann und aus der Herkunft der Anwendung
ausgeliefert würde.

Eine kopierfertige Vorlage wird mit dem Produkt ausgeliefert, unter
`docs/exemples/theme-exemple/`. Ihre Farben gehören niemandem: Das Produkt
enthält keine fremde Marke, und die Farben eines Kunden werden auf der
Installation abgelegt, die sie benötigt.

Das Thema wird auf der Karte des Workspace gewählt, Bildschirm **Workspaces**,
sobald der Ordner abgelegt ist — nie bei der Erstellung, bei der der Ordner des
Workspace gerade erst angelegt wurde und noch nichts enthält. Abgelehnte
Ablagen werden dort mit ihrem Grund aufgeführt: Eine falsch abgelegte Datei
verschwindet nicht stillschweigend.

Farben und Logos eines Kunden werden nicht mit dem Produkt ausgeliefert. Sie
werden auf der Installation abgelegt, die sie benötigt.

## Die Spalten der Quelldateien zuordnen

Kovex setzt keinen Spaltennamen voraus. Vier CSV-Dateien werden erwartet:
Identitäten, Anwendungen, Rechte, Berechtigungen. Für jede gibt die
Konfiguration an, welche Spalte welche Kennung trägt.

Was zwingend gefüllt sein muss:

- Identitäten: die Spalte der Personenkennung;
- Rechte: die Spalte der Rechtekennung und die der zugehörigen Anwendung;
- Anwendungen: die Spalte der Anwendungskennung;
- Berechtigungen: die beiden Spalten, die eine Person mit einem Recht
  verbinden.

Eine nicht zugeordnete Spalte ist kein Fehler: die davon abhängigen Prüfungen
werden schlicht als nicht verfügbar ausgewiesen, und der Qualitätsbildschirm
zeigt „—" statt null.

Trennzeichen und Zeichensatz sind je Datei einstellbar. Im Zweifel sind bei
einem Windows-Export `;` und `utf-8` die häufigsten Werte.

**Am einfachsten erklären Sie alles beim Laden.** Im Importfenster liest die
Schaltfläche „Dateien prüfen" den Anfang jeder gewählten Datei und zeigt, was
sie gesehen hat: den Zeichensatz, der sie dekodiert, das Trennzeichen, das sie
regelmäßig teilt, die Spaltennamen und einige Zeilen. Die Listen bieten dann nur
Spalten an, die es wirklich gibt, und Ihre Wahl wird in die Konfiguration des
Workspace geschrieben.

Eine angegebene Spalte, die die Datei nicht enthält, führt zur **Ablehnung** des
Ladevorgangs — die Spalte wird benannt, und der vorhandene Bestand wird nicht
ersetzt. Das war der teuerste Fehler: Der Lader benennt nur die Spalten um, die
er findet, und schweigt zu den anderen; eine Datei mit elftausend Identitäten
lud damit ohne Fehler und zeigte null Identitäten.

## Konten und Rollen

Drei Rollen mit festen Berechtigungen:

| Rolle | Berechtigungen |
|---|---|
| `admin` | lesen, schreiben, löschen, verwalten, Mining, Rollen |
| `analyst` | lesen, schreiben, Mining, Rollen |
| `viewer` | lesen |

Drei Rollen, aber **nur ein Konto bei der Installation**. Der erste Start
legt `admin` an und sonst nichts: Die Demonstrationskonten und ihre Passwörter
wurden aus dem Quelltext entfernt, wo sie jede Installation offline berechenbar
machten. Es gibt daher kein Standardpasswort.

- In der Produktion stammt das erste Passwort aus der Variablen
  `PYGIA_BOOTSTRAP_ADMIN_PASSWORD`. Ohne sie wird kein Konto angelegt und
  niemand kann sich anmelden: Die Installation bleibt geschlossen, statt durch
  eine allgemein bekannte Kennung geöffnet zu werden.
- In der Entwicklung wird bei fehlender Variablen ein Zufallspasswort erzeugt
  und **einmalig protokolliert**, beim Start, als Warnung. Es wird nie erneut
  angezeigt.

Ist dieses Passwort verloren — die Zeile läuft beim ersten Start schnell
durch —, ist nichts zu reparieren: `config/users.json` löschen,
`PYGIA_BOOTSTRAP_ADMIN_PASSWORD` setzen, neu starten. Das Konto wird mit
diesem Passwort neu angelegt. Die Datei enthält nur Prüfsummen; ihr Löschen
verliert keine Governance-Daten.

Das Lesen des **Prüfpfads erfordert `admin`**. Ein Konto, das geprüft werden
kann, entscheidet nicht darüber, was die Prüfung zeigt.

Die Zugriffskontrolle arbeitet nach **Verweigerung als Vorgabe**: eine in der
Richtlinie nicht deklarierte Route wird abgelehnt, nicht geöffnet. Einen
Endpunkt hinzuzufügen, ohne ihn zu deklarieren, macht ihn unerreichbar — das
ist das gewollte Verhalten.

## Prüfpfad

Der Pfad hält Governance-Entscheidungen fest: Freigabe und Ablehnung von
Rollen, Mining-Läufe mit ihren Parametern, Exporte, Änderungen an der
Konfiguration, Anlegen und Löschen von Workspaces.

Drei Eigenschaften sollten Sie kennen:

- **Er wird nie neu geschrieben.** Jede Entscheidung ist eine angehängte
  Zeile. Keine API-Route erlaubt, eine davon zu entfernen.
- **Er ist verkettet.** Jeder Eintrag trägt den Fingerabdruck des
  vorhergehenden. Eine Zeile zu ändern oder zu löschen bricht die Kette, und
  der Bildschirm meldet es unter Nennung des schuldigen Eintrags. Das macht
  eine Fälschung nicht unmöglich — auf einer erreichbaren Datei kann das
  nichts — es macht sie **erkennbar**.
- **Er rotiert nicht.** Er wächst. Nehmen Sie ihn in die Sicherung auf und
  schließen Sie ihn von jeder automatischen Bereinigung aus.

Prüfen Sie die Unversehrtheit regelmäßig: der Bildschirm zeigt den Befund bei
jedem Öffnen an, ohne Ihr Zutun.

## Sicherung

Zu sichern:

- `workspaces/` — Daten, Konfiguration und Wissensbasen;
- die Datei des Prüfpfads;
- `config/` — Konten und Übersetzungskataloge;
- `.env` — **enthält den Signaturschlüssel**. Sein Verlust macht alle
  ausgegebenen Token ungültig; seine Offenlegung erlaubt, welche zu erzeugen.

Nicht zu sichern: `output/`, wiederherstellbar.

## Diagnose

**Die Anwendung antwortet auf einer Route mit 403.** Die Route ist nicht in der
Zugriffsrichtlinie deklariert, oder dem Konto fehlt die Berechtigung. Das
Serverprotokoll nennt die zu deklarierende Route.

**Das Mining findet keine Rolle.** Prüfen Sie zuerst die Anzahl der nutzbaren
Berechtigungen im Reiter Qualität. Eine leere Matrix erzeugt null Rollen, ohne
einen Fehler auszulösen.

**Eine Qualitätsprüfung zeigt „—".** Die entsprechende Spalte ist in der
Konfiguration des Workspace nicht zugeordnet.

**Änderungen am Frontend greifen nicht.** Der Browser liefert eine
zwischengespeicherte Fassung. Die Ressourcen tragen eine Versionsnummer in
ihrer URL; ein erzwungenes Neuladen genügt.

**Der Prüfpfad wird als gebrochen gemeldet.** Die Datei wurde außerhalb der
Anwendung geändert. Der Bildschirm nennt den Eintrag, ab dem die Geschichte
nicht mehr belastbar ist. Bewahren Sie die Datei unverändert auf: sie ist ein
Beweismittel.
