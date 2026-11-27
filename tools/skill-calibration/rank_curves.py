"""Exploratory mathematical comparison of all stored candidates; never activates ratings."""
import argparse
from contextlib import closing
import html
import json
from pathlib import Path
import sqlite3
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / '.cache/python'))
import numpy as np
from curve_preview import eligible, family, weighted_quantile
from curve_search import input_fingerprint


def basis(values, ref):
    """Exact piecewise-linear coefficients: curve(x, targets) == basis(x) @ targets."""
    points = [(0., -1)] + [(p['raw'], p['targetIndex']) for p in ref['points']]
    knots = np.array([p[0] for p in points])
    x = np.asarray(values, dtype=float)
    i = np.clip(np.searchsorted(knots, x, side='left'), 1, len(knots)-1)
    t = (x-knots[i-1])/(knots[i]-knots[i-1])
    result = np.zeros((len(x), 3))
    for j in range(3):
        result[:, j] = (1-t)*(np.array([points[v-1][1] for v in i]) == j) + t*(np.array([points[v][1] for v in i]) == j)
    result[x <= 0] = 0
    return result


def distortion_terms(values, ref):
    x = np.asarray(values, dtype=float)
    median = ref['points'][0]['raw']
    positive = x > 0
    b = basis(x, ref)
    b[positive] /= (x[positive]/median)[:, None]
    return b.T @ b / len(x), b.mean(axis=0), positive.mean()


def quadratic(targets, matrix):
    return np.einsum('ni,ij,nj->n', targets, matrix, targets)


def run(data, search):
    raw = (data/'maps.jsonl').read_bytes()
    metadata = json.loads((data/'export.json').read_text(encoding='utf-8'))
    with closing(sqlite3.connect((search/'search.sqlite').resolve().as_uri()+'?mode=ro', uri=True)) as db:
        fingerprint, manifest_json = db.execute('SELECT fingerprint,data FROM manifest WHERE id=1').fetchone()
        manifest = json.loads(manifest_json)
        if input_fingerprint(raw, metadata, manifest['config']) != fingerprint:
            raise ValueError('Search and current map export do not match.')
        rows = db.execute('SELECT id,p50,p75,p90 FROM candidates ORDER BY id').fetchall()
    if len(rows) != manifest['total']:
        raise ValueError('Finish the configured search before comparing all combinations.')
    samples = [json.loads(line) for line in raw.splitlines()]
    refs = manifest['references']; n = len(refs)
    a = np.zeros((3,3)); s = np.zeros((3,3)); d = np.zeros((3,3)); dv = np.zeros(3); dc = 0.
    quantiles = [.1,.25,.5,.75,.9,.95,.99]
    quantile_bases = []; cells_used = 0
    raw_by_skill = []
    for k, ref in enumerate(refs):
        values = np.array([sample['pattern']['raw'][k] for sample in samples])
        raw_by_skill.append(values)
        dm, v, c = distortion_terms(values, ref)
        d += dm/n; dv += v/n; dc += c/n
        train, test = {}, {}
        for sample in samples:
            if eligible(sample['pattern'], k):
                cells = test if sample['holdout'] else train
                cells.setdefault(family(sample['pattern']), []).append(sample['pattern']['raw'][k])
        fitted = {key: values for key, values in train.items() if len(values) >= manifest['config']['minCellMaps']}
        combined = {key: values + test.get(key, []) for key, values in fitted.items()}
        quantile_bases.append(basis([weighted_quantile(combined, q) for q in quantiles], ref))
        deltas = []
        for key, values in fitted.items():
            if len(test.get(key, [])) >= 3:
                delta = basis(test[key], ref).mean(axis=0)-basis(values, ref).mean(axis=0)
                deltas.append(delta)
        if not deltas: raise ValueError(f'No paired groups for {ref["id"]}')
        delta = np.array(deltas); s += delta.T@delta/len(delta)/n; cells_used += len(delta)
    qb = np.array(quantile_bases) # skills × quantiles × target coefficients
    centered = qb-qb.mean(axis=0)
    a = np.einsum('sqi,sqj->ij', centered, centered)/(n*len(quantiles))
    all_targets = np.array([r[1:] for r in rows], dtype=float)
    targets = all_targets/all_targets[:, :1] # global numeric scale is not a quality criterion
    baseline = np.array([[1.,22/15,2.]])
    # Preserve local spacing too: output slope relative to median-linear slope should stay near 1.
    # Otherwise a global value-error average can hide compression of the rare hardest maps.
    local = np.zeros((3,3)); lv = np.zeros(3); segments = 0
    for ref in refs:
        points = [(0.,-1)]+[(p['raw'],p['targetIndex']) for p in ref['points']]
        median=ref['points'][0]['raw']
        for (x0,j0),(x1,j1) in zip(points,points[1:]):
            coeff=np.zeros(3);coeff[j1]+=median/(x1-x0)
            if j0>=0:coeff[j0]-=median/(x1-x0)
            local+=np.outer(coeff,coeff);lv+=coeff;segments+=1
    local/=segments;lv/=segments
    def metrics(t):
        return np.stack([np.maximum(0,quadratic(t,a)),np.maximum(0,quadratic(t,s)),np.maximum(0,quadratic(t,d)-2*t@dv+dc),
                         np.maximum(0,quadratic(t,local)-2*t@lv+1)],axis=1)
    measurements = metrics(targets)
    reference = metrics(baseline)[0]
    if np.any(reference < 1e-12): raise ValueError('Degenerate comparison baseline; review metrics before ranking.')
    relative = measurements/reference
    score = relative.mean(axis=1)
    order = np.argsort(score, kind='stable')
    def describe(i):
        return {'id': rows[i][0], 'targets': list(rows[i][1:]), 'targetsAtMedian15': list(targets[i]*15),
                'score': float(score[i]), 'metricsRelativeTo15_22_30': relative[i].tolist(),
                'rmsMetricsInMedianUnits': np.sqrt(measurements[i]).tolist()}
    best = int(order[0]); median15_indices = np.where(all_targets[:,0]==15)[0]
    practical = int(median15_indices[np.argmin(score[median15_indices])]) if len(median15_indices) else best
    sensitivity = []
    for weights in [[1,1,1,1],[2,1,1,1],[1,2,1,1],[1,1,2,1],[1,1,1,2]]:
        weighted = relative@np.array(weights)/sum(weights)
        i = int(np.argmin(weighted))
        sensitivity.append({'weights': weights, 'candidate': describe(i), 'weightedScore': float(weighted[i])})
    # Exact quadratic reduction vs direct map-by-map evaluation on every map at three targets.
    # This validates the expensive all-map distortion part without materializing billions of rows.
    checks = []
    for target in [baseline[0], targets[best], targets[practical]]:
        brute = 0.
        for values, ref in zip(raw_by_skill, refs):
            median = ref['points'][0]['raw']; mask = values > 0
            error = np.zeros(len(values)); error[mask] = (basis(values,ref)@target)[mask]/(values[mask]/median)-1
            brute += np.mean(error**2)/n
        reduced = float(metrics(np.array([target]))[0,2])
        if abs(brute-reduced) > 1e-9: raise AssertionError('Quadratic reduction disagrees with direct map evaluation.')
        checks.append({'targetsAtMedian15': list(target*15), 'directAllMaps': brute, 'reduced': reduced})
    examples = []
    for k, ref in enumerate(refs):
        b = basis(raw_by_skill[k],ref)
        chosen = b@(targets[practical]*15); previous = b@np.array([15.,22.,30.])
        raw_values = raw_by_skill[k]; median=ref['points'][0]['raw']
        # Representative examples around several raw quantiles, not just extreme outliers.
        selected=[]
        for q in [.1,.5,.75,.9,.99]:
            wanted=np.quantile(raw_values[raw_values>0],q)
            index=int(np.argmin(np.where(raw_values>0,np.abs(raw_values-wanted),np.inf)))
            if index not in selected:selected.append(index)
        examples.append({'skill':ref['label'],'maps':[{'title':samples[i]['title'],'version':samples[i]['version'],
            'stars':samples[i]['pattern']['stars'],'raw':float(raw_values[i]),'currentX5':float(raw_values[i]*5),
            'medianLinear15':float(raw_values[i]/median*15),'curve15_22_30':float(previous[i]),'candidate':float(chosen[i])} for i in selected]})
    result={'model':metadata['model'],'searchFingerprint':fingerprint,'metricVersion':'exploratory-four-criteria-v1',
            'previewOnly':True,'evaluatedCandidates':len(rows),'maps':len(samples),
            'skills':n,'conceptualMapSkillCandidateValues':len(rows)*len(samples)*n,'pairedGroups':cells_used,
            'criteria':['Cross-skill dispersion of balanced map quantiles','Train/development-pool shifts of means within paired groups',
                        'Relative change of each map/skill demand against median-linear scaling','Local slope change against median-linear spacing'],
            'weights':[1,1,1,1],'baselineTargets':[15,22,30],'topCandidates':[describe(int(i)) for i in order[:30]],
            'practicalMedian15':describe(practical),'weightSensitivity':sensitivity,'exactReductionChecks':checks,'examples':examples,
            'limitations':['Mathematical preference under declared criteria; not a measured human difficulty optimum.',
                'The reused development pool is now used for selection, not independent final validation.',
                'Accuracy is a map proxy. Reference-pool eligibility remains a modeling assumption.',
                'Calibration cannot repair incorrect pattern recognition or prove skills independent.']}
    (search/'comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    np.savez_compressed(search/'all-comparison-metrics.npz',ids=np.array([r[0] for r in rows]),targets=all_targets,score=score,relative=relative,
                        alignment=a,stability=s,distortion=d,distortionLinear=dv,distortionConstant=dc,localSlope=local,localSlopeLinear=lv)
    def esc(x):return html.escape(str(x))
    def row(c):return '<tr>'+''.join('<td>'+esc(v)+'</td>' for v in [c['id'],' / '.join(f'{x:g}' for x in c['targets']),
        ' / '.join(f'{x:.3f}' for x in c['targetsAtMedian15']),f'{c["score"]:.4f}',*['%.3f'%v for v in c['metricsRelativeTo15_22_30']]])+'</tr>'
    body=''.join(row(c) for c in result['topCandidates'])
    example_html=''
    for section in examples:
        example_html+='<h2>'+esc(section['skill'])+'</h2><table><tr><th>Map</th><th>★</th><th>Referenz ×5</th><th>Median linear 15</th><th>15/22/30</th><th>Kandidat mit Median 15</th></tr>'
        for m in section['maps']:
            example_html+='<tr>'+''.join('<td>'+esc(v)+'</td>' for v in [m['title']+' ['+m['version']+']',f'{m["stars"]:.2f}',*[f'{m[key]:.2f}' for key in ['currentX5','medianLinear15','curve15_22_30','candidate']]])+'</tr>'
        example_html+='</table>'
    sensitivity_html=''.join('<li>'+esc(str(x['weights'])+' → '+str(x['candidate']['targetsAtMedian15']))+'</li>' for x in sensitivity)
    page=f'''<!doctype html><html lang="de"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Kurven · mathematischer Vergleich</title>
<style>body{{font:16px/1.5 system-ui;background:#131916;color:#e9ece8;margin:28px;}}h1,h2{{color:#c4eb90}}table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}th,td{{padding:9px;text-align:left;border-bottom:1px solid #354039}}aside{{background:#293326;padding:16px}}.scroll{{overflow:auto}}</style>
<h1>Alle gespeicherten Kurven vergleichen</h1><aside>Nur mathematischer Vergleich unter festgelegten Kriterien. Keine Aktivierung und kein Nachweis gleicher menschlicher Schwierigkeit.</aside>
<p>{len(samples)} Maps × {n} Skills × {len(rows)} Kombinationen. Die Wirkung aller Map-Rohwerte wird exakt durch vorberechnete Kurvenkoeffizienten erfasst; keine Milliarden Einzelscores werden gespeichert.</p>
<p>Alle Kandidaten werden für die Qualitätsbetrachtung auf Median 15 normiert. Die ursprünglichen Zielwerte und Kandidaten-IDs bleiben erhalten. Proportionale Tripel unterscheiden sich nur in der Einheit.</p>
<h2>Kriterien</h2><ol><li>Angleichung der ausgewogenen Skill-Verteilungen bei P10/P25/P50/P75/P90/P95/P99.</li><li>Stabilität der Gruppenmittelwerte zwischen Training und erneut verwendeten Prüfmaps.</li><li>Erhalt der ursprünglichen relativen Map-Werte gegenüber linearer Median-Skalierung; alle Maps und Skills gehen ein, fehlende Anforderungen bleiben null.</li><li>Erhalt der lokalen Abstände: Änderung der Segment-Steigungen gegenüber linearer Median-Skalierung. Das erfasst auch eine Stauchung der oberen Kurve.</li></ol>
<p>Alle vier Fehlermaße sind relativ zu 15/22/30 normiert und gleich gewichtet. Kleinerer Score bedeutet nur unter diesen Annahmen einen besseren Kompromiss. Gewichte und Kriterien sind gesetzte Designentscheidungen, keine aus Spielerurteilen erlernte Wahrheit. Keine menschlichen Referenzurteile vorhanden. Der Prüfpool wird zur Auswahl benutzt und ist damit keine unabhängige Abschlussprüfung mehr.</p>
<h2>Erste 30 Kandidaten</h2><div class="scroll"><table><tr><th>ID</th><th>Ziele im Raster</th><th>Auf Median 15 normiert</th><th>Score (Basis = 1)</th><th>Verteilungsfehler</th><th>Stabilitätsfehler</th><th>Wert-Verzerrung</th><th>Lokale Abstandsverzerrung</th></tr>{body}</table></div>
<h2>Praktischer Kandidat mit Median 15</h2><p>{esc(result['practicalMedian15'])}</p>
<h2>Empfindlichkeit gegenüber der Gewichtung</h2><p>Reihenfolge: Verteilung, Stabilität, Wert-Verzerrung, lokale Abstandsverzerrung.</p><ul>{sensitivity_html}</ul>
<h2>Dieselben Maps vorher/nachher</h2>{example_html}<p>Rohdaten: comparison.json und all-comparison-metrics.npz. Der aktive Rating-Code wurde nicht geändert.</p></html>'''
    (search/'comparison.html').write_text(page,encoding='utf-8')
    print(json.dumps({'best':describe(best),'practicalMedian15':describe(practical),'sensitivity':sensitivity},ensure_ascii=False,indent=2))
    print(search/'comparison.html')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,default=HERE/'.cache')
    parser.add_argument('--search',type=Path,default=HERE/'.cache/search-1-100')
    args=parser.parse_args();run(args.data.resolve(),args.search.resolve())
