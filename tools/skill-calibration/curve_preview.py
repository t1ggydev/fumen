"""Offline curve simulation; never writes active skill factors or the library database."""
import argparse
import bisect
import collections
import html
import json
import math
from pathlib import Path
import sys


def weighted_quantile(cells, q):
    """Each cell has equal total weight; no cell's map count dominates the reference."""
    values = sorted((x, 1 / len(v)) for v in cells.values() for x in v)
    if not values:
        return None
    threshold = q * len(cells)
    total = 0
    for value, weight in values:
        total += weight
        if total + 1e-12 >= threshold:
            return value
    return values[-1][0]


def fit_curve(cells):
    # Keep the first target on ties: one raw demand cannot map to two different ratings.
    anchors, skipped = [(0.0, 0.0)], []
    for q, target in [(0.5, 15.0), (0.75, 22.0), (0.9, 30.0)]:
        raw = weighted_quantile(cells, q)
        if raw is None or raw <= anchors[-1][0] + 1e-12:
            skipped.append(q)
        else:
            anchors.append((raw, target))
    return anchors, skipped


def curve(raw, anchors):
    if not math.isfinite(raw) or raw <= 0 or len(anchors) < 2:
        return 0.0
    i = min(max(1, bisect.bisect_left([p[0] for p in anchors], raw)), len(anchors) - 1)
    x0, y0 = anchors[i - 1]
    x1, y1 = anchors[i]
    # Last slope continues beyond the final anchor: no rank conversion and no rating ceiling.
    return y0 + (raw - x0) * (y1 - y0) / (x1 - x0)


def family(p):
    labels = [name for k, threshold, name in [(6, .25, 'fast'), (9, .30, 'slider'), (3, .25, 'snap'), (4, .03, 'rhythm')] if p['coverage'][k] >= threshold]
    return f"{int(p['stars'])}★ / {'+'.join(labels) or 'other'}"


def eligible(p, k):
    count, coverage = (6, .03) if k == 4 else (12, .10)
    return math.isfinite(p['raw'][k]) and p['raw'][k] > 0 and p['support'][k] >= count and p['coverage'][k] >= coverage


def run(output):
    sys.path.insert(0, str(output / 'python'))
    try:
        import matplotlib
    except ModuleNotFoundError:
        raise SystemExit(f'Plot dependency missing. Install locally with:\npython -m pip install --target "{output / "python"}" -r "{Path(__file__).with_name("requirements.txt")}"')
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    meta = json.loads((output / 'export.json').read_text(encoding='utf-8'))
    samples = [json.loads(line) for line in (output / 'maps.jsonl').open(encoding='utf-8')]
    summaries, sections = [], []
    plt.style.use('dark_background')
    for k, (skill, label) in enumerate(meta['skills']):
        train, test = collections.defaultdict(list), collections.defaultdict(list)
        for s in samples:
            if eligible(s['pattern'], k):
                (test if s['holdout'] else train)[family(s['pattern'])].append(s['pattern']['raw'][k])
        cells = {c: v for c, v in train.items() if len(v) >= 10}
        if len(cells) < 3 or sum(map(len, cells.values())) < 100:
            summaries.append({'skill': skill, 'status': 'insufficient reference data'})
            sections.append(f'<h2>{html.escape(label)}</h2><p>Zu wenige Referenzdaten; keine Kurve angepasst.</p>')
            continue
        anchors, skipped = fit_curve(cells)
        median = weighted_quantile(cells, .5)
        factor = 15 / median
        matched = {c: v for c, v in cells.items() if len(test.get(c, [])) >= 3}
        matched_test = {c: test[c] for c in matched}
        evaluated = []
        for q in [.5, .75, .9]:
            tr, te = weighted_quantile(matched, q), weighted_quantile(matched_test, q)
            evaluated.append({'quantile': q, 'trainCurve': curve(tr, anchors) if tr is not None else None, 'testCurve': curve(te, anchors) if te is not None else None})
        summary = {'skill': skill, 'label': label, 'anchors': anchors, 'skippedQuantiles': skipped,
                   'linearFactor': factor, 'trainingMaps': sum(map(len, cells.values())), 'trainingCells': len(cells),
                   'testedCells': len(matched), 'evaluation': evaluated, 'accuracyProxy': k == 2}
        summaries.append(summary)
        xmax = max(anchors[-1][0] * 1.35, weighted_quantile(cells, .99))
        x = [xmax * i / 300 for i in range(301)]
        fig, ax = plt.subplots(figsize=(8, 4.3), layout='constrained')
        fig.patch.set_facecolor('#131916'); ax.set_facecolor('#131916')
        ax.plot(x, [5 * v for v in x], color='#a9adb4', linestyle=':', label='Referenz ×5')
        ax.plot(x, [factor * v for v in x], color='#62b5e5', linestyle='--', label='Nur Median-Faktor')
        ax.plot(x, [curve(v, anchors) for v in x], color='#c4eb90', label='Mehrpunkt-Vorschau')
        ax.scatter(*zip(*anchors), color='#c4eb90', zorder=4)
        ax.set(xlabel='Pattern-gewichteter Map-Rohwert', ylabel='Rating bei perfektem Play', title=label)
        ax.grid(alpha=.15); ax.legend(fontsize=9)
        ymax = max(curve(xmax, anchors), factor * xmax, 5 * xmax)
        ax.set_ylim(0, ymax * 1.05)
        fig.savefig(output / f'curve-{skill}.png', dpi=150); plt.close(fig)
        reference = [s for s in samples if s['holdout'] and family(s['pattern']) in matched and eligible(s['pattern'], k)]
        reference.sort(key=lambda s: (s['pattern']['raw'][k], s['hash']))
        examples, used = [], set()
        for q in [.1, .5, .75, .9, .99]:
            wanted = weighted_quantile(cells, q)
            if not reference: break
            item = min(reference, key=lambda s: abs(s['pattern']['raw'][k] - wanted))
            if item['hash'] in used: continue
            used.add(item['hash']); raw = item['pattern']['raw'][k]
            examples.append({'title': item['title'], 'version': item['version'], 'hash': item['hash'], 'stars': item['pattern']['stars'],
                             'raw': raw, 'current': raw * 5, 'linear': raw * factor, 'curve': curve(raw, anchors)})
        summary['referenceMaps'] = examples
        cells_html = ''.join(f'<tr><td>{raw:.4f}</td><td>{target:.2f}</td></tr>' for raw, target in anchors)
        example_html = ''.join(f'<tr><td>{html.escape(e["title"])} [{html.escape(e["version"])}]</td><td>{e["stars"]:.2f}★</td><td>{e["raw"]:.3f}</td><td>{e["current"]:.2f}</td><td>{e["linear"]:.2f}</td><td>{e["curve"]:.2f}</td></tr>' for e in examples)
        eval_html = ''.join(f'<tr><td>P{round(e["quantile"]*100)}</td><td>{e["trainCurve"]:.2f}</td><td>{e["testCurve"]:.2f}</td></tr>' for e in evaluated if e['trainCurve'] is not None)
        warning = '<p class="warning">Accuracy nutzt hier nur einen Map-Proxy; der tatsächliche Skill hängt von Judgements ab.</p>' if k == 2 else ''
        if skipped: warning += f'<p class="warning">Gleiche Rohwerte: Anker {skipped} ausgelassen. Eine Rohanforderung erhält immer denselben Wert.</p>'
        sections.append(f'''<section id="{skill}"><h2>{html.escape(label)}</h2>{warning}<p>{summary['trainingMaps']} Trainingsmaps · {len(cells)} Trainingsgruppen · {len(matched)} gepaarte Prüfgruppen · linearer Median-Faktor {factor:.3f}</p>
<img src="curve-{skill}.png" alt="Vergleich der drei Skalierungen für {html.escape(label)}">
<details><summary>Referenzpunkte</summary><table><tr><th>Rohwert</th><th>Ziel</th></tr>{cells_html}</table></details>
<h3>Dieselben Prüfmaps, drei Skalierungen</h3><div class="scroll"><table><tr><th>Map</th><th>Sterne</th><th>Rohwert</th><th>Referenz ×5</th><th>Median-Faktor</th><th>Kurve</th></tr>{example_html}</table></div>
<h3>Gleiche Gruppen: trainierte Kurve auf Training und Prüfmaps</h3><table><tr><th>Quantil</th><th>Training</th><th>Prüfmaps</th></tr>{eval_html}</table>
<p>Beispiel bei 90 % Spielqualität: Map-Anforderung {curve(anchors[-1][0], anchors):.2f} × 0,90 = {curve(anchors[-1][0], anchors)*.9:.2f}. Dies ist eine Simulation, kein tatsächlich gespielter Score.</p></section>''')
    result = {'model': meta['model'], 'previewOnly': True, 'targets': [[0, 0], [.5, 15], [.75, 22], [.9, 30]], 'skills': summaries}
    (output / 'curves.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    nav = ' · '.join(f'<a href="#{s[0]}">{html.escape(s[1])}</a>' for s in meta['skills'])
    page = f'''<!doctype html><html lang="de"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Skill-Kurven · Vorschau</title>
<style>body{{font:16px/1.55 system-ui;background:#131916;color:#e9ece8;max-width:1150px;margin:32px auto;padding:0 18px}}h1,h2,a{{color:#c4eb90}}section{{margin:40px 0;border-top:1px solid #354039}}img{{max-width:100%;height:auto}}table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}th,td{{padding:9px;text-align:left;border-bottom:1px solid #354039}}.scroll{{overflow:auto}}aside,.warning{{background:#293326;padding:12px;border-radius:8px}}</style>
<h1>Skill-Kurven · nur Vorschau</h1><p>{html.escape(meta['model'])} · {meta['analyzed']} eindeutige Analysen / {meta['total']} Maps · {meta['failed']} nicht bewertbar · {meta['unreadable']} nicht lesbar</p>
<aside>Die aktive Wertung bleibt unverändert. 0 → 0, P50 → 15, P75 → 22, P90 → 30 sind gesetzte Zielpunkte. Zwischen ihnen wird linear interpoliert; darüber läuft die letzte Steigung ohne Obergrenze weiter.</aside>
<h2>Methode und Grenzen</h2><ul><li>Vollständige Maps, NoMod 1.0×. Spieler-Accuracy und Misses gehen nicht in die Referenzverteilung ein.</li><li>80/20-Aufteilung über Datei-MD5. Nur Training passt die Kurven an. Identische Dateien zählen einmal; Metadaten-/Rate-Edits sind nicht automatisch identifiziert.</li><li>Gleiche Gewichtung pro 1★-/Pattern-Familien-Gruppe mit mindestens zehn geeigneten Trainingsmaps. Innerhalb der Gruppe gleiches Map-Gewicht. Gewichtete empirische Quantile statt ungewichteter Tabellenwerte.</li><li>Referenzen: mindestens zwölf Nachweise und zehn Prozent Pattern-Anteil, Finger control sechs und drei Prozent. Die Eignung der Referenz-Auswahl bleibt prüfbedürftig, besonders für Stamina.</li><li>Mindestens 100 Referenzmaps und drei Trainingsgruppen. Prüfung auf denselben Gruppen mit mindestens drei Prüfmaps.</li><li>Der Pool wurde bereits untersucht. Diese Gegenprüfung dient der explorativen Stabilitätskontrolle, nicht einer neuen unabhängigen Validierung.</li><li>Gleiche Verteilungsanker beweisen keine gleiche menschliche Schwierigkeit. Ob die Kurven sinnvoll unterscheiden, muss anhand konkreter Maps geprüft werden.</li><li>Vorschlag für spätere Plays: erst Map-Anforderung kalibrieren, danach Spielqualität multiplizieren. Die tatsächlichen Spielqualitätsregeln und der Accuracy-Sonderfall werden hier nicht geändert.</li></ul><nav>{nav}</nav>{''.join(sections)}</html>'''
    (output / 'curve-preview.html').write_text(page, encoding='utf-8')
    print(output / 'curve-preview.html')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path(__file__).parent / '.cache')
    run(parser.parse_args().out.resolve())
