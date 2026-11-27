"""Compare full recalculations, including changes in the five selected maps."""
import argparse
import html
import json
from pathlib import Path


def compare(before, after):
    names = [('own', 'Du'), ('Feeritas', 'Feeritas'), ('mrekk', 'mrekk')]
    old = {key: json.loads((before / f'{key}.json').read_text(encoding='utf-8')) for key, _ in names}
    new = {key: json.loads((after / f'{key}.json').read_text(encoding='utf-8')) for key, _ in names}
    rows = [('Overall', [(old[k]['overall'], new[k]['overall']) for k, _ in names])]
    for i, s in enumerate(new['own']['skills']):
        values = []
        for k, _ in names:
            a, b = old[k]['skills'][i], new[k]['skills'][i]
            assert a['id'] == b['id'] == s['id']
            values.append((a['value'] if a['evidence'] else None, b['value'] if b['evidence'] else None))
        rows.append((s['label'], values))
    fmt = lambda x: '–' if x is None else f'{x:.2f}'.replace('.', ',')
    lines = ['# Vorher / Nachher: Reading und Skalierung', '',
             'Alle Profile wurden vollständig neu berechnet; die fünf tragenden Maps können sich ändern. Die Score-Stichproben der Vergleichsspieler sind identisch. Keine fehlenden Charts.', '',
             '| Skill | Du vorher | Du jetzt | Feeritas vorher | Feeritas jetzt | mrekk vorher | mrekk jetzt |',
             '|---|---:|---:|---:|---:|---:|---:|']
    for label, values in rows:
        lines.append('| ' + label + ' | ' + ' | '.join(fmt(x) for pair in values for x in pair) + ' |')
    explanation = ('Die Skalierung erhält mindestens die relativen Rohwert-Unterschiede bei gleicher Spielqualität. '
                   'Der obere Referenzanker bleibt fest, frühere Anker werden bei Bedarf gesenkt und oberhalb des letzten Ankers proportional fortgesetzt. '
                   'Die Mediane sind damit nicht mehr zwingend gleich. Reading ergänzt kreuzende Notenfolgen und Zeitdruck im tatsächlichen AR-Fenster. '
                   'Die Gewichte (Kreuzungen 0,35; Sichtzeit-Exponent 0,25) sind vorläufig und nicht anhand dieser drei Spieler optimiert. '
                   'Sterne und Spielernamen fließen nicht in die Bewertung ein. Slider-Control ohne Detailnachweise ist unbekannt, nicht null. '
                   'Alte Skill-Ziele bleiben gespeichert, werden auf der neuen Skala aber nicht angezeigt.')
    validation = ('25.874 eindeutige Maps vollständig neu analysiert. Die anderen zehn Roh-Skills sind exakt unverändert. '
                  'Die überarbeitete Reading-Referenz nutzt nur Trainingsmaps.')
    lines += ['', explanation, '', validation]
    (after / 'comparison.md').write_text('\n'.join(lines), encoding='utf-8')
    body = ['<h1>Vorher / Nachher</h1><p>Reading und Skalierung · gleiche Score-Stichproben · vollständige Neuberechnung</p><table><thead><tr><th>Skill</th>']
    for _, label in names:
        body.append(f'<th>{label} vorher</th><th>{label} jetzt</th>')
    body.append('</tr></thead><tbody>')
    for label, values in rows:
        body.append('<tr><th>' + html.escape(label) + '</th>')
        for a, b in values:
            body.append('<td>' + fmt(a) + '</td><td class="new">' + fmt(b) + '</td>')
        body.append('</tr>')
    body.append('</tbody></table><p>' + html.escape(explanation) + '</p><p>' + html.escape(validation)
                + '</p><p><a href="audit.html">Neue tragende Maps und alle Faktoren</a> · '
                '<a href="../profile-audit/audit.html">Vorherige tragende Maps</a></p>')
    style = ('body{background:#141819;color:#eee;max-width:1200px;margin:40px auto;padding:20px;font:16px/1.6 system-ui}'
             'table{border-collapse:collapse;width:100%;margin:30px 0}td,th{padding:10px;text-align:right;border-bottom:1px solid #394344}'
             'th:first-child{text-align:left}.new{color:#c4eb90;background:#202a21}a{color:#b8df7a}p{color:#bbc2c2}')
    (after / 'comparison.html').write_text('<!doctype html><meta charset="utf-8"><title>Skills – Vorher / Nachher</title><style>'
                                          + style + '</style>' + ''.join(body), encoding='utf-8')
    (after / 'comparison.json').write_text(json.dumps({'before': str(before), 'after': str(after),
                                                     'rows': [{'skill': label, 'values': values} for label, values in rows]},
                                                    ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('before', type=Path)
    p.add_argument('after', type=Path)
    a = p.parse_args()
    compare(a.before, a.after)
