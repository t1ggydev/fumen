# Kurvenkombinationen sammeln und vergleichen

Die Suche verändert keine aktiven Skill-Wertungen. Sie sammelt alle gültigen Kombinationen
im konfigurierten endlichen Raster. Es gibt keine automatische Rangliste und keinen Gewinner.

## Starten

Im Repository-Verzeichnis:

```powershell
npm run calibrate:search -- --estimate
npm run calibrate:search
```

Mit dem aktuellen [Raster](search-config.json) werden 49.435 Kombinationen gespeichert:

| Zielpunkt | Minimum | Maximum | Schritt |
|---|---:|---:|---:|
| P50 | 10 | 30 | 1 |
| P75 | 15 | 60 | 1 |
| P90 | 20 | 100 | 1 |

Nur `0 < P50 < P75 < P90` zählt. Die drei Zielwerte gelten gemeinsam für alle Skills;
jeder Skill hat seine eigenen aus Trainingsmaps bestimmten Rohwert-Anker.
Proportional vergrößerte Zieltripel haben dieselbe normalisierte Form, aber eine andere Zahleneinheit.

Die Suche nutzt den vorhandenen NoMod-Export in `.cache/maps.jsonl` und `.cache/export.json`.
Map-Dateien und rosu-Schwierigkeiten werden nicht für jede Kombination erneut analysiert.
Die Formeln sind dadurch vollständig durch Rohwert-Anker und Zieltripel beschrieben.
Pro Kombination werden zusätzlich die resultierenden Trainingsquantile und Segment-Steigungen
aller Skills gespeichert. Einzelne Map-Werte werden bei der Auswahl exakt daraus berechnet.

## Ergebnisse ansehen

```powershell
npm run calibrate:search -- --serve
```

Dann <http://127.0.0.1:8766> öffnen. Die Ansicht erlaubt:

- Auswahl über eine laufende Nummer oder ein gespeichertes Zieltripel.
- Suche nach Artist, Titel oder Difficulty aus der gesamten exportierten Bibliothek.
- Vergleich derselben Map mit aktuellem ×5, einem passenden Median-Faktor und der gewählten Kurve.
- Download der ausgewählten Kurven als JSON, ohne sie im Rating zu aktivieren.

Die Ansicht ist lokal und liest die Ergebnisdatenbank. Sie kann während der Suche bereits
gespeicherte Kombinationen anzeigen. Neue Ergebnisse erscheinen nach Neuladen der Seite.
Bei belegtem Port lässt sich mit `--port 8767` ein anderer Port verwenden.

## Abbrechen und fortsetzen

`Strg+C` beendet den Lauf. Derselbe Startbefehl setzt ihn fort. Es wird spätestens alle
250 Kombinationen committed; bei einem erzwungenen Prozessabbruch können die letzten
unbestätigten Kandidaten erneut gerechnet werden. Bereits bestätigte Ergebnisse bleiben erhalten.

Ein begrenzter Probelauf schreibt in einen separaten Ordner:

```powershell
npm run calibrate:search -- --out tools/skill-calibration/.cache/search-test --limit 100
npm run calibrate:search -- --out tools/skill-calibration/.cache/search-test --limit 100
```

Der zweite Befehl verarbeitet die **nächsten** 100 Kombinationen.

## Bereiche ändern

Eine Kopie von `search-config.json` bearbeiten, beispielsweise mit Schritt `0.5` oder weiteren Bereichen:

```powershell
npm run calibrate:search -- --config tools/skill-calibration/my-grid.json --estimate
npm run calibrate:search -- --config tools/skill-calibration/my-grid.json --out tools/skill-calibration/.cache/search-my-grid
npm run calibrate:search -- --serve --out tools/skill-calibration/.cache/search-my-grid
```

Ein Lauf mit geänderter Konfiguration oder geändertem Map-Export benötigt einen neuen Ausgabeordner.
Ein Fingerabdruck verhindert das Vermischen verschiedener Modelle und Exporte beim Fortsetzen
und Anzeigen. Mehr als eine Million Kombinationen erfordern ein ausdrücklich höheres
`--max-candidates`; `--estimate` zählt auch größere Raster ohne die Suche zu starten.

## Dateien und Voraussetzungen

- Python 3.10 oder neuer; die Suche selbst benötigt nur die Standardbibliothek.
- Node/npm für die Kurzbefehle. Alternativ `python tools/skill-calibration/curve_search.py` verwenden.
- `.cache/search/search.sqlite`: Kombinationen und komprimierte Statistiken.
- `.cache/search/manifest.json`: Modell, Eingabefingerabdruck, Konfiguration und Referenzpunkte.
- Ausgaben in `.cache` sind vom Git-Tracking ausgeschlossen.

Ist der Map-Export nicht vorhanden oder das Modell geändert, zuerst `npm run calibrate:preview`
ausführen. Dafür werden Rust/Cargo, die bereits importierte Fumen-Bibliothek und für die
Vorschaugrafiken Matplotlib benötigt. Matplotlib kann lokal installiert werden:

```powershell
python -m pip install --target tools/skill-calibration/.cache/python -r tools/skill-calibration/requirements.txt
```

## Interpretation

### Mathematischer Vergleich aller Kombinationen

Nach einer ausdrücklich gewünschten automatischen Gegenüberstellung:

```powershell
npm run calibrate:compare
```

Standardmäßig wird `.cache/search-1-100` ausgewertet; ein anderer Lauf lässt sich über
`--search PATH` wählen. Die Ergebnisse stehen im gewählten Suchordner in `comparison.html`,
`comparison.json` und `all-comparison-metrics.npz`.

Der Vergleich normiert die Kandidaten auf dieselbe Median-Einheit und betrachtet vier Kriterien:
Angleichung der Skill-Verteilungen, Stabilität zwischen gepaarten Trainings-/Prüfgruppen,
Verzerrung der Werte aller Maps gegenüber linearer Median-Skalierung und Verzerrung der lokalen
Segment-Steigungen. Die Fehler werden relativ zum Beispiel 15/22/30 normiert und gleich gewichtet.
Diese Gewichtung ist eine Designentscheidung. Der Bericht zeigt deshalb auch die Empfindlichkeit
gegenüber anderen Gewichtungen, alternative Kandidaten und dieselben Maps vorher/nachher.

Die Wirkung auf alle Maps wird algebraisch exakt zusammengefasst: Eine stückweise lineare Kurve
ist bei festen Rohwert-Ankern linear in ihren Zielwerten. Fehlerquadrate können deshalb über
vorberechnete Koeffizienten für jede Kombination exakt berechnet werden. Es ist nicht nötig,
Milliarden einzelne Ergebniszeilen zu speichern. Die Implementierung prüft die Reduktion zusätzlich
gegen direkte Einzelmap-Rechnungen. Alle Kandidaten-Kennzahlen bleiben in der NPZ-Datei verfügbar.

Diese Bewertung begründet nur ein mathematisches Optimum **unter den angegebenen Kriterien**,
keine optimal gemessene menschliche Schwierigkeit. Der erneut genutzte Prüfpool dient jetzt auch
zur Auswahl und darf nicht als unabhängige Abschlussvalidierung ausgegeben werden.
Die Vorschläge werden nicht automatisch aktiviert.

Die Suche bewertet perfekte NoMod-Map-Anforderungen, keine tatsächlich erzielten Plays.
Nur Trainingsmaps bestimmen die Rohwert-Anker und Suchstatistiken. Prüfmaps können in der
Ansicht ausgewählt werden und sind gekennzeichnet; nach manueller Auswahl anhand dieser Maps
sind sie keine unabhängige Abschlussprüfung mehr. Accuracy basiert hier auf einem Map-Proxy.

Gleiche Quantile garantieren keine gleiche menschliche Schwierigkeit. Das Raster sammelt
Designvarianten, aus denen wir anhand konkreter Maps auswählen können. Neue Zielwerte
beeinflussen die Form zwischen den Ankern; oberhalb P90 läuft die letzte Steigung ohne Kappung weiter.


### Profil-Diagnose

`skill_profile_audit` arbeitet auf einer **separaten SQLite-Sicherung** der Bibliothek.
Die Originaldatenbank nicht als erstes Argument verwenden. Die Sicherung muss auch das
aktuelle WAL enthalten (SQLite-Backup verwenden, nicht nur die Datei kopieren).

```powershell
cargo run --manifest-path src-tauri/Cargo.toml --example skill_profile_audit -- SNAPSHOT_DB "$env:APPDATA/dev.fumen.app" "$env:LOCALAPPDATA/dev.fumen.app/osu-charts" OUTPUT mrekk Feeritas
python tools/skill-calibration/profile_audit.py OUTPUT
```

Der Export nutzt den bestehenden osu!-Login und die gespeicherten Online-Einstellungen.
Er lädt Vergleichsprofile mit demselben Verfahren wie die App und prüft zuerst Bibliothek und
Chart-Cache. Die vollständigen Vergleichs-Score-Eingaben werden im Nachbarordner
`profile-inputs` gespeichert und bei weiteren Varianten wiederverwendet. Für einen frischen
API-Abruf die jeweilige Eingabedatei dort entfernen; nach Modelländerungen werden die Scores
aus diesen Eingaben erneut berechnet. Für Vorher/Nachher einen neuen Ausgabeordner wählen. Die eigenen Plays entsprechen
dem Filter der Skillseite: Standard, vorhandene lokale Map, bestanden.

`audit.md` und `audit.html` zeigen je Skill die fünf tragenden Maps mit Rohanforderung,
Kalibrierung, Spielqualitätsfaktor, Endwert und modifizierten Sternen. Sterne werden hier nur
zur Diagnose angezeigt. Für Accuracy ist die Rohanforderung bereits vom Timing der erzielten
Treffer abhängig. Mittelwerte beschreiben die jeweils ausgewählten Top-Maps und keine identische
Map-Stichprobe zwischen Spielern. Der Export ändert keine Bewertungsformel.


### Aktive Vergleichsvariante: Rohwert-Verhältnisse und Reading (v7)

Die alte Kurve 136083 ist als `reference-curves-136083.json` erhalten. Ihr oberer
Referenzwert (P90, 21,8478) bleibt erhalten. Frühere Ziel-Anker werden nur soweit gesenkt,
dass `Ausgabewert / Rohwert` entlang der Anker nicht abnimmt. Zwischen den Ankern wird
linear interpoliert; oberhalb P90 proportional vom Ursprung weitergerechnet. Damit kann
ein höherer positiver Rohwert bei gleicher Spielqualität relativ nicht mehr näher an einen
niedrigeren herangezogen werden. Die Mediane sind dadurch bewusst nicht mehr alle gleich.
Diese Regel ist eine Designentscheidung, keine aus menschlichen Labels gelernte Kalibrierung.

Die unveränderten zehn Roh-Skills behalten ihre bisherigen Rohwert-Anker. Für das neue Reading
werden P50/P75/P90 auf Trainingsmaps des vollständigen Neu-Exports bestimmt, mit demselben
Zellgewichtungsverfahren wie die Suche; Holdout-Maps bestimmen keine Anker.

```powershell
python tools/skill-calibration/constrain_curves.py --density-export tools/skill-calibration/.cache/reading-v7 --out src/lib/osu-skill-curves.json
```

Reading berechnet für jedes auftauchende Objekt eine gemeinsame Last aus:

- Anzahl zu diesem Zeitpunkt sichtbarer Köpfe und noch laufender Slider;
- nahen Überlagerungen am neuen Kopf (Bonus wie bisher bis vier Überlagerungen);
- strikten Kreuzungen der chronologischen Kopfverbindungen im aktuellen Sichtfenster,
  geteilt durch die Anzahl sichtbarer Verbindungen;
- `(600 ms / tatsächliche AR-Sichtzeit)^0,25` als moderatem Zeitdruck;
- bestehendem HD-Faktor 1,05.

Die Last lautet `sqrt(sichtbar)/1,3 × (1 + 0,06×min(Überlagerungen,4)
+ 0,35×sqrt(Kreuzungen/Verbindungen)) × Zeitdruck × HD`.
Das 90. Perzentil dieser gemeinsamen Last ersetzt die zuvor getrennten Quantile.
600 ms ist eine Einheit (AR9 NoMod), keine Sichtzeit-Untergrenze. Shared Endpoints,
kollineare Stapel und künstliche Verbindungen über bereits verschwundene Köpfe zählen
nicht als Kreuzungen. Slider bleiben bis zum echten Ende sichtbar. Der neue Kreuzungsbonus
und der Zeitdruck-Exponent sind vorläufige Modellgewichte und brauchen Map-Feedback.
Sterne, Spielerrang und Spielername beeinflussen die Berechnung nicht.

Die Pattern-Cache-Version ist 17; die Goal-Skala ist `pattern-reading-ratios-v4`.
Ziele alter Skalen bleiben gespeichert und werden wie zuvor als inkompatibel ausgeblendet.


Vorher/Nachher-Bericht aus zwei vollständigen Profil-Neuberechnungen:

```powershell
python tools/skill-calibration/compare_profile_audits.py tools/skill-calibration/.cache/profile-audit tools/skill-calibration/.cache/profile-audit-v7
```

Der Bericht steht im zweiten Ordner als `comparison.html`, `comparison.md` und `comparison.json`.
