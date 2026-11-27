"""Keep the upper reference scale while preventing compression of raw demand ratios.
This is a model constraint, not a fitted human difficulty ground truth.
"""
import argparse, collections, json
from pathlib import Path
from curve_preview import eligible, family, weighted_quantile


def preserve_ratios(points):
    points = [list(p) for p in points]
    for i in range(len(points)-2, 0, -1):
        x,y = points[i]; nx,ny = points[i+1]
        points[i][1] = min(y, ny*x/nx)
    return points


def build(reference, density_export=None):
    result = json.loads(json.dumps(reference))
    if density_export:
        cells = collections.defaultdict(list)
        for line in (density_export/'maps.jsonl').open(encoding='utf-8'):
            row=json.loads(line)
            if not row['holdout'] and eligible(row['pattern'],7):
                cells[family(row['pattern'])].append(row['pattern']['raw'][7])
        cells = {k:v for k,v in cells.items() if len(v)>=10}
        if len(cells)<3 or sum(map(len,cells.values()))<100:
            raise ValueError('Insufficient density reference data')
        targets = [p[1] for p in reference['curves']['density-reading'][1:]]
        result['curves']['density-reading'] = [[0.,0.]] + [[weighted_quantile(cells,q),y] for q,y in zip([.5,.75,.9],targets)]
        result['densityReference'] = {'model': json.loads((density_export/'export.json').read_text(encoding='utf-8'))['model'], 'trainingCells':len(cells),'trainingMaps':sum(map(len,cells.values()))}
    result['curves'] = {k:preserve_ratios(v) for k,v in result['curves'].items()}
    result.update(scale='pattern-reading-ratios-v4', patternVersion=17,
                  sourceModel='pattern-rosu-reading-ratios-v7/patterns-17',
                  extrapolation='proportional',minimumElasticity=1.0,
                  referenceCandidate=reference['candidate'])
    for key in ['candidate','gridTargets','targets','fingerprint']:
        result.pop(key,None)
    result['policy'] = 'Hold P90 output; lower earlier anchors only when necessary to preserve raw-demand ratios. Continue proportionally above P90.'
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--reference',type=Path,default=Path(__file__).with_name('reference-curves-136083.json'));p.add_argument('--density-export',type=Path);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    a.out.write_text(json.dumps(build(json.loads(a.reference.read_text(encoding='utf-8')),a.density_export),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
