# Handbuch für Entwickler

## Architektur

```
src/
  api/          HTTP-Endpunkte (FastAPI), Zugriffsrichtlinie, Schemata
  core/
    data/       CSV-Einlesen, Aufbau der Matrix, Qualität
    mining/     Algorithmen zur Rollenfindung und Schwellenerkundung
    knowledge/  Wissensbasis: freigegebene und abgelehnte Rollen, Ausschlüsse
    audit/      Verketteter Prüfpfad
    security/   Authentifizierung, Kennwörter, Ratenbegrenzung
    workspaces/ Trennung nach Kunde oder Umgebung
  infrastructure/ Protokollierung, serverseitige i18n, Produktidentität
frontend/       Webanwendung ohne externe Abhängigkeit
tests/          pytest-Suite, darunter tests/ihm für den Browser
docs/           Dokumentation, darunter das von der Anwendung ausgelieferte docs/manuel
```

Eine Regel durchzieht den gesamten Code: **der Server baut niemals eine
angezeigte Beschriftung**. Er gibt einen Code und dessen Parameter zurück; der
Client übersetzt. Ein Server kennt die Sprache seiner Benutzerin nicht.

## Konventionen

**Kein fest verdrahteter Wert.** Schwellen, Pfade, Spaltennamen: alles kommt
aus der Konfiguration. Ein in den Code geschriebener Wert ist ein Mangel, keine
Abkürzung.

**Kein vorausgesetzter Spaltenname.** Kundendateien haben die Spalten, die sie
haben. Nur die Konfiguration verbindet sie mit den internen Kennungen.

**Verweigerung als Vorgabe.** Jede Route muss in
`src/api/security_policy.py` deklariert sein. Eine nicht deklarierte Route wird
abgelehnt, und ein Test prüft das über sämtliche Routen der Anwendung.

**Kommentare erklären das Warum.** Ein Kommentar, der den Code umschreibt, ist
Lärm. Ein Kommentar, der sagt, welchen Mangel die Zeile vermeidet, ist noch
Jahre später wertvoll.

## Tests

```
python -m venv .venv                    # eine eigene Umgebung: die Sperrdatei
.venv\Scripts\activate                  # gilt nur, wenn sie allein entscheidet
pip install -r requirements-dev.txt     # erbt die Sperrdatei, nicht die Grenzen
python -m playwright install chromium   # einmalig, lädt den Browser herunter

python -m pytest                        # alles
python -m pytest tests/ihm              # Browser
python -m pytest --cov --cov-report=term-missing   # Abdeckung des Backends
python couverture_frontend.py           # Abdeckung des JavaScript
```

Ohne Playwright werden die Oberflächentests **stillschweigend übersprungen**:
`tests/ihm/conftest.py` gibt seinen Import an `pytest.importorskip` weiter. Der
Durchlauf gelingt, ohne die Hälfte dessen, was er zu prüfen vorgibt, und die
Abdeckung des Frontends misst nichts. `python -m playwright install chromium`
benötigt Netzwerkzugang; holen Sie den Browser auf einer isolierten Maschine
anderswo und setzen Sie `PLAYWRIGHT_BROWSERS_PATH` auf seinen Ort. Nichts davon
betrifft das ausgelieferte Produkt: Playwright dient allein dazu, es zu testen.

Drei Familien:

- **Unit- und Integrationstests**: die Mehrzahl, auf erzeugten Datensätzen —
  nie auf Kundendaten, damit sie auf einer leeren Maschine laufen.
- **Struktureller Art**: ausgeglichene HTML-Vorlage, kein verschachtelter
  Dialog, keine vom JavaScript gelesene Kennung, die nirgends existiert, kein
  Ereignisbehandler in einem Attribut, Parität der Übersetzungskataloge. Sie
  fangen eine ganze Klasse sonst unsichtbarer Mängel ab.
- **Oberflächentests**: ein echter Browser, eine simulierte API. Es gibt sie,
  weil ein Mangel in der HTML-Struktur eine Funktion stillschweigend
  wirkungslos machte, ohne dass ein Servertest das hätte sehen können.

## Erster Start

Kein Passwort steht im Quelltext: Der erste Start legt das einzige Konto
`admin` an, mit dem Passwort aus der Umgebung.

```
set PYGIA_SECRET_KEY=...                   # Signatur der Token
set PYGIA_BOOTSTRAP_ADMIN_PASSWORD=...     # Passwort des ersten Kontos
python run_api.py
```

Fehlt die zweite Variable in der Entwicklung, wird ein Zufallspasswort erzeugt
und beim Start **einmalig protokolliert**. Es wird nie erneut angezeigt: Die
Zeile läuft im Strom der Meldungen durch, und sobald `config/users.json`
besteht, reproduziert nichts sie mehr. Ist es verloren, diese Datei löschen und
mit gesetzter Variablen neu starten — sie enthält nur Prüfsummen, keine
Governance-Daten.

In der Produktion wird ohne die Variable kein Konto angelegt: Die Installation
bleibt geschlossen, statt durch eine allgemein bekannte Kennung geöffnet zu
werden.

## Versionen der Abhängigkeiten

`requirements.txt` trägt Untergrenzen und beschreibt, was der Code verlangt.
`requirements.lock` fixiert genau die Versionen, die die Suite ausgeführt hat,
und daraus wird ein Server installiert. Er wird erhoben, nicht verfasst:

```
python -m tools.verrou_dependances            # meldet die Abweichung, ändert nichts
python -m tools.verrou_dependances --ecrire   # schreibt die Datei fort
```

Ohne `--ecrire` gibt der Befehl 1 zurück, wenn die Sperrdatei von der
installierten Umgebung abweicht, was ihn unverändert in einer CI-Kette nutzbar
macht. Erzeugen Sie die Sperrdatei erst neu, nachdem die gesamte Suite
durchgelaufen ist: eine Version zu fixieren, die nichts ausgeführt hat, ist
genau das, was diese Datei verhindern soll.

## Einen Endpunkt hinzufügen

1. Die Route in einem Router unter `src/api/routers/` schreiben.
2. **Sie in `security_policy.py` deklarieren**, mit der erforderlichen
   Berechtigung. Andernfalls antwortet sie mit 403.
3. Ändert sie den Governance-Zustand, `journal: Journal =
   Depends(get_journal)` ergänzen und die Aktion mit einem `Action`-Code
   festhalten.
4. Übersetzungscodes zurückgeben, niemals Sätze.
5. Die zugehörigen Schlüssel in allen drei Katalogen ergänzen.

## Eine Sprache hinzufügen

`config/locales/fr.json` kopieren, die Werte übersetzen, alle Schlüssel
behalten. Die Tests prüfen die Parität der Schlüssel und die Stimmigkeit der
Einsetzungen: ein fehlender Schlüssel oder ein vergessener `{parameter}` lässt
die Suite scheitern.

Die eingebetteten Handbücher liegen in `docs/manuel/<Sprache>/`. Ein in einer
Sprache fehlender Abschnitt wird in der Referenzsprache ausgeliefert, und die
Oberfläche sagt es, statt eine leere Seite zu zeigen.

## Prüfpfad

`PisteAudit` schreibt JSON-Zeilen, eine nach der anderen angehängt, jede mit
dem Fingerabdruck der vorhergehenden. Das Modul stellt kein Löschen bereit und
die API keine Schreibroute — zwei Tests prüfen das.

Um aus einer Route heraus festzuhalten, fassen Sie den Pfad nicht direkt an:
deklarieren Sie die Abhängigkeit `Journal`. Sie leitet den Handelnden aus dem
Token und dem aktiven Workspace ab, was verhindert, dass ein Aufrufer eine
Entscheidung jemand anderem zuschreibt, indem er einen Namen in den
Anfragekörper schmuggelt.

## Frontend

Keine externe Abhängigkeit: die Bibliotheken sind in `frontend/vendor/`
eingebettet. Das Produkt muss auf einem Server ohne ausgehenden Zugang
funktionieren.

**Zwei Nummern, zwei Rollen.** `serve_frontend.py` schreibt die Vorlage im
Betrieb um: Es richtet die unten in der Leiste angezeigte Version an
`VERSION_PRODUIT` aus und den Cache-Schlüssel der Stylesheets und Skripte an
einem **Fingerabdruck des ausgelieferten Inhalts**. Letzterer ändert sich
genau dann, wenn sich eine Datei unter `frontend/` ändert, und sonst nie — bei
der Auslieferung ist also an nichts zu denken. Die in `index.html`
geschriebene Nummer macht die Datei nur unmittelbar öffenbar; sie erreicht den
Browser nie.

`VERSION_PRODUIT` wird aus nichts abgeleitet: Sie ist eine Nummer für
Menschen. Erhöhen Sie sie, wenn eine Lieferung einen Namen verdient, nicht bei
jeder Änderung.

Untersagt, und von den Tests geprüft:

- `onclick="..."` in der Vorlage — verwenden Sie Ereignisdelegation;
- `<a href="#">` zum Auslösen einer Aktion — der Hash-Router liest das als
  Rückkehr zur Übersicht;
- eine von `getElementById` gelesene Kennung, die weder in der Vorlage noch in
  erzeugtem HTML existiert;
- angezeigter Text, fest im Code geschrieben.

Die Ressourcen tragen eine Versionsnummer in ihrer URL. Erhöhen Sie sie bei
jeder Frontend-Auslieferung, sonst liefern Browser die alte Fassung aus.
