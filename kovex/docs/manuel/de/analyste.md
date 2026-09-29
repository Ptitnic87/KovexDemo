# Handbuch für Analysten

Dieses Handbuch richtet sich an die Person, die mit Kovex arbeitet: die
Analysen startet, die vorgeschlagenen Rollen liest und über Freigabe oder
Ablehnung entscheidet. Kenntnisse der Algorithmen werden nicht vorausgesetzt.

## Was Kovex tut, in einem Satz

Kovex liest, wer welche Rechte besitzt, sucht Gruppen von Personen mit den
gleichen Rechten und schlägt vor, diese Gruppen in Rollen zu überführen. Eine
Rolle ersetzt Dutzende einzelner Vergaben durch eine einzige Entscheidung.

## Die Begriffe

**Identität.** Eine Person mit ihren Attributen: Funktion, Abteilung,
Vertragsart. Kovex setzt keines dieser Attribute voraus: es sind die Spalten
Ihrer Datei, welche auch immer das sind.

**Recht.** Eine elementare Berechtigung in einer Anwendung: eine
Sicherheitsgruppe, ein Profil, eine Berechtigung.

**Berechtigung.** Die Tatsache, dass eine Identität ein Recht besitzt. Das ist
der Rohstoff: ohne sie gibt es nichts zu analysieren.

**Anwendungsrolle.** Eine Menge von Rechten, die technisch zusammengehören.
Vom Mining entdeckt.

**Geschäftsrolle.** Eine Menge von Anwendungsrollen und Rechten, vergeben über
eine Regel auf Identitätsattributen — zum Beispiel „jede Pflegekraft der
Abteilung X". Das ist es, was die automatische Vergabe möglich macht.

**Geschäftsregel einer Rolle.** Was die Träger einer Rolle gemeinsam haben,
ausgedrückt über die Attribute Ihres Bestands — „Abteilung = Buchhaltung *und*
Status = Führungskraft“. Kovex sucht sie im Nachhinein, an einer bereits
gefundenen Rolle: das Mining kann sagen, welche Rechte zusammengehören, nicht
warum.

**Zuverlässigkeit der Regel.** Unter den von der Regel benannten Personen der
Anteil, der die Rolle tatsächlich trägt. Was bis 100 % fehlt, ist die
Überberechtigung, die Sie mit der Regel in Kauf nähmen.

**Aussagekraft.** Um wie viel besser die Regel die Träger benennt als eine
zufällige Auswahl. Bei 1 bringt sie keine Erkenntnis — und das ist eine häufige
Falle: in einem großen Bestand wird eine winzige Regelmäßigkeit statistisch
sicher, ohne irgendeinen Wert zu haben. „51 % der Träger tragen dieses Merkmal,
gegenüber 50 % in der Population“ ist eine unbestreitbare Tatsache und eine
nutzlose Regel.

**Basisrecht. Ein Recht, das nahezu alle besitzen: Mailzugang,
Netzwerkzugang. Es trägt keine Information bei, um einen Beruf von einem
anderen zu unterscheiden, und überlagert die Analyse, wenn man es darin lässt.

## Der normale Ablauf

### 1. Zuerst die Datenqualität prüfen

Der Reiter **Datenqualität** ist keine Formsache. Ein Mining auf
widersprüchlichen Daten erzeugt widersprüchliche Rollen, und nichts im
Ergebnis weist darauf hin.

Sehen Sie sich vorrangig an:

- **Verwaiste Rechte** und **verwaiste Benutzer**: Berechtigungen, die auf ein
  Recht oder eine Person zeigen, die im Bestand fehlen. Sie nehmen an keiner
  Analyse teil.
- **Fehlerhafte Berechtigungen**: die Anzahl unbrauchbarer *Zeilen*.
- **Nicht vergebene Rechte**: Kandidaten für die Stilllegung, ohne Wirkung auf
  das Mining, aber nützlich für die Governance.
- **Dubletten im Bestand**: eine doppelt vorhandene Kennung verfälscht jede
  Zählung.

Eine mit „—" angezeigte Prüfung steht nicht auf null: sie konnte mangels einer
zugeordneten Spalte in der Konfiguration nicht berechnet werden. Lesen Sie das
nicht als „keine Auffälligkeit".

Die Schaltfläche **Details anzeigen** öffnet zu jeder Auffälligkeit die
vollständige Liste der betroffenen Kennungen, filterbar und als CSV
exportierbar. Diese Liste geben Sie an die für den Bestand verantwortliche
Person weiter.

### 2. Basisrechte erkennen

Starten Sie vor dem Geschäfts-Mining die Erkennung der Basisrechte. Ein Recht,
das 95 % der Identitäten besitzen, hilft nicht, Berufe zu unterscheiden: bleibt
es in der Analyse, entstehen riesige Rollen, die einander alle gleichen.

Die Schwelle bestimmen Sie. Je niedriger sie ist, desto mehr Rechte entfernen
Sie, desto unterscheidungskräftiger sind die verbleibenden Rollen — aber desto
größer ist das Risiko, ein Recht zu entfernen, das eine große Gruppe
tatsächlich kennzeichnete.

### 3. Anwendungs-Mining starten

Zwei Modi.

**Exakt**: fasst die Identitäten zusammen, die *genau* dieselbe Menge an
Rechten besitzen. Kein Parameter, nichts Willkürliches. Ergebnis: wenige, sehr
reine Rollen und eine niedrige Abdeckung — die Wirklichkeit ist selten so
sauber.

**Näherungsweise**: fasst die Identitäten zusammen, deren Rechtemengen bis auf
eine Schwelle θ *ähnlich* sind. Deckt weit mehr Personen ab, um den Preis
überschüssiger Vergaben.

Zwei Parameter rahmen das Ergebnis:

- **Mindestanzahl Benutzer**: darunter ist eine Gruppe keine Rolle, sondern ein
  Zufall. Drei ist eine vernünftige Untergrenze.
- **Mindestanzahl Rechte**: eine „Rolle" mit einem einzigen Recht bringt nichts,
  was eine direkte Vergabe nicht schon brächte.

### 4. θ wählen, statt es zu erleiden

An dieser Stelle lassen die meisten Werkzeuge Sie mit einem Vorgabewert
allein. Kovex gibt Ihnen die Kurve.

Der Bildschirm zur **Wahl von θ** durchläuft eine Reihe von Schwellen und
zeichnet für jede zwei gegenläufige Größen:

- die **Abdeckung**: der Anteil der tatsächlichen Berechtigungen, den die
  Rollen erklären;
- die **Überberechtigung**: die Rechte, die die Rollen Personen geben würden, die
  sie heute nicht besitzen.

θ = 1 vergibt keine Berechtigung zu viel. Ein niedrigeres θ erhöht die
Abdeckung *und* die Überberechtigung. Es gibt keinen guten Wert an sich: es gibt den
Wert, den Ihre Sicherheitsrichtlinie toleriert. Lesen Sie die Kurve, legen Sie
zuerst die höchste hinnehmbare Überberechtigung fest und nehmen Sie dann die
Schwelle, die am meisten abdeckt, ohne diese Grenze zu überschreiten — meist
das kleinste θ, das sie einhält. Geben Sie die Grenze am Bildschirm ein: Diese
Schwelle wird dort ausgewiesen.

### 5. Eine vorgeschlagene Rolle lesen

Für jede Rolle zählen vier Zahlen:

- **Anzahl Benutzer**: die Population, die die Rolle abdecken würde.
- **Anzahl Rechte**: die Größe der Rolle. Eine Rolle mit 200 Rechten ist keine
  Rolle, sondern eine ganze Abteilung.
- **Abdeckung**: der Anteil der Berechtigungen dieser Benutzer, den die Rolle
  erklärt.
- **Überberechtigung**: was die Rolle zu viel geben würde.

Eine Rolle mit einer Überberechtigung größer null ist deshalb allein noch nicht
disqualifiziert. Die Frage lautet: sind diese überschüssigen Rechte harmlos
oder sensibel? Eine Rolle, die zu viel Lesezugriff auf ein Verzeichnis gibt,
ist keine Rolle, die zu viel Zugriff auf eine Patientenakte gibt.

### 5b. Die fachliche Erklärung einer Rolle anfordern

Die Registerkarte **Erklärung** im Freigabefenster beantwortet die Frage, die
die Anwendungsverantwortlichen stellen werden: *Was haben diese Personen
gemeinsam?*

Wählen Sie die zu kombinierenden Attribute — es sind die Spalten Ihrer Dateien
— und legen Sie Ihre Anforderungen fest. Es sind Ihre, nicht die des Produkts:

| Einstellung | Worüber sie entscheidet |
|---|---|
| Erwartete Zuverlässigkeit | Darunter wird die Regel als nicht vertretbar gekennzeichnet. |
| Mindestanteil erklärter Träger | Je mehr Sie verlangen, desto breiter die Regel und desto weniger zuverlässig. |
| Mindestaussagekraft | Verwirft Attribute, die keine Erkenntnis bringen. |
| Akzeptiertes Zufallsrisiko | Höchstwahrscheinlichkeit, dass die Übereinstimmung zufällig ist. |
| Anzahl kombinierter Kriterien | Eine längere Regel ist genauer und weniger lesbar. |

Kovex liefert **die zuverlässigste Regel, die noch den von Ihnen verlangten
Anteil der Träger erklärt**. Den Kompromiss entscheidet es nicht für Sie: ein
weiteres Kriterium erhöht die Zuverlässigkeit und senkt die Zahl der erklärten
Träger.

Die Übersicht **was dafür spricht, was dagegen spricht** führt die Befunde
einzeln auf, vom blockierendsten bis zum beruhigendsten, jeweils mit ihrer
Zahl. Bewusst ist es keine Gesamtnote: einem einzelnen Prozentwert lässt sich
nicht widersprechen, ein Gremium muss aber Punkt für Punkt widersprechen
können.

Zwei Befunde verdienen besondere Aufmerksamkeit:

- **Ausnahmen** sind die Träger, die die Regel nicht beschreibt. Genau sie
  prüft ein Gremium einzeln.
- **Überberechtigung** zählt die Personen, die die Regel benennen würde, obwohl
  sie die Rolle heute nicht tragen. Das sind die Sicherheitskosten der
  Vereinfachung.

Eine Rolle ohne Regel ist keine schlechte Rolle: es ist eine Rolle, die Ihre
Attribute nicht beschreiben. Das geschieht, wenn der Identitätsbestand die
Dimension nicht trägt, die diese Berechtigungen tatsächlich strukturiert — ein
Projekt, eine Rufbereitschaft, eine Betriebszugehörigkeit.

### 5c. Der von einem Modell vorgeschlagene Name

Wenn Ihre Administration den semantischen Annotator aktiviert hat, schlägt die
Registerkarte Erklärung einen Namen und eine Beschreibung vor. **Nichts wird
übernommen, solange Sie den Vorschlag nicht übernehmen**: er füllt die Felder
nur auf Ihre Anforderung, und Sie bleiben für das verantwortlich, was Sie
freigeben.

Vor jeder Anfrage zeigt der Bildschirm, welches Modell befragt wird, was ihm
übermittelt wird, und **ob diese Daten den Server verlassen**. Standardmäßig
sieht das Modell nur die Anzahl der Rechte und Träger: keine Bezeichnungen,
keine Attributwerte, keine bereits vergebenen Namen. Was angekündigt wird, ist
genau das, was hinausgeht.

Wenn Ihre Administration bereits freigegebene Namen erlaubt, erhält das Modell
einige Rollen aus Ihrem Katalog als Beispiele und folgt Ihrer
Namenskonvention. Sie werden unter den Rollen ausgewählt, die dieser am
nächsten stehen — eine Berechnung, die auf dem Server bleibt.

Ohne konfigurierten Annotator sagt der Bereich dies, und Sie benennen die Rolle
von Hand — das ist der Normalbetrieb, keine Störung.

### 6. Freigeben oder ablehnen

**Freigeben** legt die Rolle in der Wissensbasis ab. Sie wird in der
Kartografie sichtbar und dient späteren Analysen als Grundlage.

**Ablehnen** stellt sie dauerhaft zurück. Die Ablehnung wird über den
Fingerabdruck der Rechte der Rolle gemerkt, nicht über ihren Namen: dieselbe
Rolle wird Ihnen beim nächsten Mining nicht unter einer anderen Bezeichnung
erneut vorgeschlagen.

Begründen Sie Ihre Ablehnungen. Der Grund wird im Prüfpfad festgehalten, und er
ist es, der in sechs Monaten erklärt, warum diese Rolle nicht existiert.

### 7. Eine Geschäftsrolle zusammenstellen

Der Kompositor fügt freigegebene Anwendungsrollen zusammen, ergänzt einzelne
Rechte und Ausnahmen und erzeugt eine Geschäftsrolle, die über eine
HR-Regel vergeben werden kann.

Die Regel ist eine strikte Gleichheit auf Identitätsattributen. Eine Identität
mit leerem Attribut entspricht nichts — und das ist Absicht: ein fehlender Wert
darf niemals als „entspricht allem" verstanden werden.

### 8. Den Katalog später überprüfen

Eine Rolle ist eine Regel, und eine Regel altert mit den Daten. Sechs Monate
nach der Freigabe hat sich die Population, die die Regel bezeichnet, verändert
— und ebenso die Berechtigungen, die ihre Mitglieder besitzen.

Über den Rollen zeigt der Katalog deshalb eine **Modellrevision**: den
Vergleich zwischen den Zahlen, die Sie bei der Entscheidung vor Augen hatten,
und denen von heute. Eine geschrumpfte Population, eine gewachsene, eine Rolle
unter der Mindestzahl an Personen, eine neu entstandene Überberechtigung, zwei
Rollen, die sich nun überschneiden. Jede Feststellung trägt beide Zahlen — die
alte und die neue —, denn über eine Abweichung ohne ihren Ausgangswert lässt
sich nicht entscheiden.

Für eine manuell zusammengestellte Rolle wurden bei der Erstellung keine Zahlen
erfasst: Ihre Karte zeigt die heutigen Messwerte und weist darauf hin, dass es
keine Abweichung zu messen gibt.

Diese Revision **korrigiert nichts**. Sie stellt fest. Eine freigegebene Rolle
ist eine Governance-Entscheidung, und sie wurde vielleicht bereits in Ihrem
Identitätsmanagement bereitgestellt: Diese Entscheidung erneut zu treffen,
bleibt Ihnen überlassen.

Die Schwelle, ab der eine Abweichung zur Feststellung wird, wird in der
Konfiguration des Workspace eingestellt: Ein Bestand von dreihundert Identitäten
und einer von dreihunderttausend bewegen sich nicht im selben Maßstab.

### 9. Einen Vorschlag anwenden — und was der Export darüber sagt

Eine Feststellung kann einen **Vorschlag** tragen: Berechtigungen aus der Rolle
entfernen, die ihre Mitglieder nicht besitzen; Berechtigungen hinzufügen, die
bereits alle besitzen; zwei sich überschneidende Rollen zusammenführen; eine
Rolle entfernen, die unter die Mindestzahl gefallen ist. Jeder Vorschlag nennt,
was aus der betroffenen Zahl würde — ohne das entscheidet man blind.

Zwei davon lassen sich vom Bildschirm aus anwenden, weil sie nur die
Berechtigungen einer Rolle betreffen. Die beiden anderen lassen eine Rolle
verschwinden, die in Ihrem Identitätsmanagement bereits bereitgestellt sein
kann: Sie werden gezeigt und erklärt, aber nie von hier aus angewendet.

Eine Rolle einzuschränken hat eine Kehrseite, und der Bildschirm nennt sie:
Eine Rolle darf zu Recht vergeben, was ihre Mitglieder noch nicht besitzen —
genau das tut ein vereinheitlichendes Modell. Die Schwelle, ab der Kovex eine
Abweichung nicht mehr als Vereinheitlichung liest, wird in der Konfiguration
des Workspace eingestellt.

**Eine angewendete Rolle behält ihre Kennung und erhält eine Version.** Die
vorherige Version wird mit Datum, Urheber und der auslösenden Feststellung
aufbewahrt, und das Prüfprotokoll trägt dieselben Angaben: „Warum hat sich
diese Rolle am 3. März geändert?" lässt sich ohne erneutes Öffnen der Daten
beantworten.

Das gibt Ihnen auch der Export: Jede Rolle trägt ihre Version und das, was seit
dem zuletzt erzeugten Dokument aus ihr geworden ist — neu, geändert,
unverändert. Ohne diesen Hinweis erhält der Integrator eine geänderte Rolle,
die er für neu hält, und legt ein Duplikat an. Eine Vorschau verschiebt diese
Marke nicht; nur ein tatsächlich erzeugtes Dokument tut das.

### 10. Eine Rolle aus dem Katalog erneut öffnen

Der Katalog zeigte nur einen Namen und zwei Zähler. Die Schaltfläche **Details
ansehen** öffnet, was die Rolle wirklich enthält: ihre Träger, ihre
Berechtigungen und zu jeder den Anteil ihrer Mitglieder, die sie bereits
besitzen.

Auf diese letzte Spalte kommt es an. „Diese Rolle vergibt 340 Berechtigungen zu
viel" lässt sich nicht korrigieren; „diese Berechtigung besitzen vier von
hundert Mitgliedern" lässt sich entscheiden.

Dasselbe Fenster trägt Name und Beschreibung — sie zu ändern **versioniert** die
Rolle, aus demselben Grund wie eine Änderung der Berechtigungen — sowie eine
Schaltfläche, die ein Modell um einen Namensvorschlag bittet, sofern eines
konfiguriert ist. Der Vorschlag füllt das Feld; er speichert sich nicht selbst.

**Eine Rolle aus dem Katalog nehmen** geschieht ebenfalls hier. Eine Begründung
ist erforderlich. Die Rolle wird nicht gelöscht: Sie bleibt mit Ihrer
Begründung, Ihrem Namen und ihrem Datum einsehbar, und der Kandidat, aus dem sie
stammt, ist wieder zu entscheiden — er wird Ihnen beim nächsten Mining erneut
vorgeschlagen.

## Was aufgezeichnet wird

Jede Governance-Entscheidung wird im **Prüfpfad** festgehalten: Freigabe,
Ablehnung, Mining-Läufe mit ihren Parametern, Exporte, Änderungen an der
Konfiguration. Der Pfad ist über Fingerabdrücke verkettet: eine nachträgliche
Änderung ist erkennbar.

Für Sie bedeutet das zweierlei. Ihre Entscheidungen sind belegbar — Sie können
zeigen, wann und mit welchen Parametern eine Rolle freigegeben wurde. Und sie
sind zurechenbar — der Pfad trägt Ihren Namen.

## Häufige Fehler

**Das Mining starten, bevor man die Datenqualität angesehen hat.** Das Ergebnis
wird sauber aussehen und im Kern falsch sein.

**Das „optimale" θ suchen.** Es gibt keines. Es gibt eine Abwägung, und sie
liegt bei Ihnen.

**Eine Rolle freigeben, ohne ihre Überberechtigung anzusehen.** So endet ein
Role-Mining-Projekt damit, Zugriffe auszuweiten statt sie einzuschränken.

**Basisrechte ignorieren.** Sie lassen alle Rollen einander gleichen und blähen
die Abdeckung künstlich auf.
