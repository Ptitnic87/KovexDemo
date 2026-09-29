# Methode des Role Mining

Dieses Dokument erklärt, was Kovex berechnet, warum, und wie die Richtigkeit
des Ergebnisses überprüft wird. Es richtet sich an alle, die die Methode vor
einer Prüferin oder einem anspruchsvollen Kunden vertreten müssen.

## Das Problem

Gegeben ist eine boolesche Matrix: in den Zeilen die Identitäten, in den
Spalten die Rechte, eine Zelle wahr, wenn die Person das Recht besitzt.
Gesucht ist eine Menge von Rollen — Teilmengen von Rechten — und eine Zuordnung
der Personen zu diesen Rollen, sodass das Ergebnis die Matrix wiedergibt.

In seiner exakten Form ist das die **boolesche Matrixzerlegung**, von der
bekannt ist, dass sie NP-schwer ist. Kein Werkzeug löst sie im Maßstab von
20 000 Identitäten und 8 000 Rechten exakt; alle verwenden Heuristiken. Die
ehrliche Frage lautet daher nicht „ist das optimal", sondern „was garantiert
die Heuristik, und was kostet sie".

## Die drei gegenläufigen Kriterien

Jede Lösung wird an drei Achsen gemessen, und eine zu verbessern verschlechtert
die anderen.

**Abdeckung.** Der Anteil der tatsächlichen Berechtigungen, den die Rollen
erklären. Eine Abdeckung von 100 % mit einer Rolle je Person ist trivial und
wertlos.

**Überberechtigung.** Die Rechte, die die Rollen Personen zuteilen würden, die sie
nicht besitzen. Das ist der Sicherheitspreis der Vereinfachung. Eine hohe
Überberechtigung macht aus einem Rationalisierungsvorhaben eine Ausweitung von
Zugriffen.

**Strukturelle Komplexität.** Die Anzahl der Rollen, ihre Größe, die Anzahl der
Zuordnungen. Eine Lösung, die niemand durchlesen kann, hat keinen
betrieblichen Wert, wie hoch ihre Abdeckung auch sei.

Kovex gibt alle drei Größen für jede Konfiguration aus. Ein Werkzeug, das nur
eine davon anzeigt, verbirgt die Abwägung vor Ihnen.

## Die Algorithmen

### Exakte Gruppierung

Identitäten, die genau dieselbe Menge an Rechten besitzen, bilden eine Gruppe.
Jede Gruppe ergibt eine Kandidatenrolle.

Kein Parameter, nichts Willkürliches, Überberechtigung null von Bauart. Im Gegenzug
ist die Abdeckung niedrig: in echten Daten haben sehr wenige Personen ein
streng identisches Rechteportfolio.

Das ist die Referenz: jede so erzeugte Rolle ist unstrittig.

### Näherungsweise Gruppierung

Zwei Identitäten werden zusammengeführt, wenn ihre Rechtemengen bis auf eine
Schwelle θ ähnlich sind. Als Rolle wird je nach Variante die Schnittmenge oder
eine Hülle der Rechte der Gruppe genommen.

θ ist **der** Parameter des Produkts. Es hat keinen guten allgemeingültigen
Wert: es kodiert die Toleranz Ihrer Sicherheitsrichtlinie gegenüber
Überberechtigung. Deshalb legt Kovex es nicht fest, sondern liefert stattdessen die
vollständige Kurve.

### Mengenüberdeckung

Sind die Kandidaten erzeugt, muss eine Teilmenge gewählt werden, die die
meisten Berechtigungen mit den wenigsten Rollen abdeckt. Das ist ein Problem
der **Mengenüberdeckung**, ebenfalls NP-schwer.

Kovex verwendet eine träge Greedy-Heuristik: in jedem Schritt die Rolle, die
die meisten neuen Berechtigungen beiträgt. Diese Heuristik hat eine bekannte
theoretische Garantie — das Ergebnis liegt schlimmstenfalls um einen
logarithmischen Faktor über dem Optimum. Das ist nicht das Optimum, es ist
eine Schranke, und das ist, was sich ehrlich behaupten lässt.

Die träge Variante nutzt die Submodularität des Zugewinns, um nicht in jedem
Schritt alle Kandidaten neu bewerten zu müssen. Das Ergebnis ist mit dem des
naiven Greedy identisch; nur die Rechenzeit ändert sich.

### Konsolidierung

Zwei sehr ähnliche Rollen werden verschmolzen, oder die eine nimmt die andere
auf. Das senkt die strukturelle Komplexität, ohne die Abdeckung anzutasten oder
nur wenig.

Dieser Punkt wurde durch Messung entschieden, nicht aus Prinzip. Drei
Strategien wurden an einem Bestand mit bekannter Wahrheit verglichen:

- **Verschmelzung über die Schnittmenge**: bricht die Richtigkeit ein — 4 von
  15 exakten Rollen wiedergefunden, gegenüber 12 ohne Konsolidierung.
  Verworfen.
- **Aufnahme**: hält die Trefferquote unverändert bei 0,973 und halbiert dabei
  die strukturelle Komplexität. Beibehalten.
- **Wahl des Vertreters**: den bestplatzierten zu nehmen hält die Trefferquote;
  einen anderen zu nehmen lässt sie auf 0,797 oder 0,830 fallen. Der Vertreter
  ist daher stets der bestplatzierte.

Auch die Konsolidierungsschwelle hat ihren eigenen Erkundungsbildschirm. Die
Grenzeffizienz — der Komplexitätsgewinn je verlorenem Punkt Trefferquote —
weist ein deutliches Maximum auf, was einen vertretbaren Ausgangspunkt liefert.

## Basisrechte

Ein Recht, das nahezu alle Identitäten besitzen, trägt keine unterscheidende
Information. Es in der Matrix zu belassen hat zwei Wirkungen: es bläht die
Abdeckung künstlich auf, und es lässt alle Rollen einander gleichen.

Kovex erkennt sie über eine einstellbare Häufigkeitsschwelle und erlaubt, sie
vor dem Geschäfts-Mining zu entfernen. Die Schwelle bleibt der Benutzerin
überlassen: je nach Organisation beginnt „nahezu alle" bei 80 % oder bei 98 %.

## Prüfung der Richtigkeit

Ein Role-Mining-Werkzeug, das sich nur an Kundendaten prüft, prüft sich
nicht: an echten Daten kennt niemand die richtige Antwort.

Kovex bringt einen Generator für **Bestände mit bekannter Wahrheit** mit. Er
baut eine Population, deren Rollen von Bauart bekannt sind, fügt Rauschen hinzu
— überzählige Vergaben, fehlende Vergaben — und lässt dann das Mining auf dem
Ergebnis laufen.

Die erzeugten Rollen werden den gepflanzten Rollen über die Jaccard-Ähnlichkeit
zugeordnet, was eine gemessene Genauigkeit und Trefferquote ergibt, keine
geschätzte.

Ein Prüfstand auf der Kommandozeile spielt diese Validierung nach, synthetisch
oder auf lokal gelesenen öffentlichen Matrizen. Er läuft offline, auf einem
isolierten Server, ohne Kundendaten.

Dieser Aufbau hat es erlaubt, die obigen Entscheidungen zur Konsolidierung
durch Messung zu treffen. Er erlaubt außerdem, vor jeder Auslieferung
festzustellen, dass eine Änderung die Richtigkeit nicht verschlechtert hat.

## Was Kovex nicht tut

Aus Ehrlichkeit, und weil ein Werkzeug, das alles zu können behauptet, in
nichts glaubwürdig ist:

- es garantiert keine Optimalität — in diesem Maßstab kann das kein Werkzeug;
- es benennt Rollen nicht von sich aus: Ein Name wird nur vorgeschlagen, wenn
  ein Sprachmodell angebunden und seine Nutzung vom Administrator freigegeben
  ist, und die Analysten übernehmen oder verwerfen ihn;
- es erkennt nicht, dass ein Wert im Bestand ein Füllwert ist („Angabe fehlt"
  als echte Anwendung behandelt);
- es ersetzt keine menschliche Prüfung. Es macht sie durchführbar.
