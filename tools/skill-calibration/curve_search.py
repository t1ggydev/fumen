"""Exhaustive finite grid collection. No winner, ranking, or active rating changes."""
import argparse
import collections
from contextlib import closing
from decimal import Decimal
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import itertools
import json
from pathlib import Path
import sqlite3
import sys
import time
from urllib.parse import parse_qs, urlsplit
import zlib

from curve_preview import curve, eligible, family, weighted_quantile

HERE = Path(__file__).resolve().parent


def axis(spec):
    lo, hi, step = (Decimal(str(spec[k])) for k in ('min', 'max', 'step'))
    if not all(x.is_finite() for x in [lo, hi, step]) or lo <= 0 or hi < lo or step <= 0:
        raise ValueError('Ranges require finite 0 < min <= max and step > 0.')
    count = int((hi - lo) // step) + 1
    if count > 100000:
        raise ValueError('An axis exceeds 100,000 values; use a coarser step.')
    return [lo + i * step for i in range(count)]


def combinations(config):
    a, b, c = (axis(config['targets'][k]) for k in ['p50', 'p75', 'p90'])
    for x, y, z in itertools.product(a, b, c):
        if x < y < z:
            yield float(x), float(y), float(z)


def combination_count(config):
    # Count without iterating the full three-dimensional grid.
    import bisect
    a, b, c = (axis(config['targets'][k]) for k in ['p50', 'p75', 'p90'])
    return sum(bisect.bisect_left(a, y) * (len(c) - bisect.bisect_right(c, y)) for y in b)


def anchors_for(ref, targets):
    return [(0.0, 0.0)] + [(point['raw'], targets[point['targetIndex']]) for point in ref['points']]


def prepare(samples, metadata, config):
    refs = []
    for k, (skill, label) in enumerate(metadata['skills']):
        cells = collections.defaultdict(list)
        for s in samples:
            if not s['holdout'] and eligible(s['pattern'], k):
                cells[family(s['pattern'])].append(s['pattern']['raw'][k])
        cells = {key: values for key, values in cells.items() if len(values) >= config['minCellMaps']}
        if len(cells) < config['minCells'] or sum(map(len, cells.values())) < config['minTrainingMaps']:
            raise ValueError(f'Insufficient training reference for {skill}; no candidate has been fitted.')
        points = []
        for index, q in enumerate([.5, .75, .9]):
            raw = weighted_quantile(cells, q)
            if raw > (points[-1]['raw'] if points else 0) + 1e-12:
                points.append({'raw': raw, 'targetIndex': index, 'quantile': q})
        refs.append({'id': skill, 'label': label, 'points': points,
                     'trainingMaps': sum(map(len, cells.values())), 'cells': len(cells),
                     'rawQuantiles': [weighted_quantile(cells, q) for q in config['quantilesToRecord']]})
    return refs


def stats_for(refs, targets):
    result = []
    for ref in refs:
        anchors = anchors_for(ref, targets)
        slopes = [(y1 - y0) / (x1 - x0) for (x0, y0), (x1, y1) in zip(anchors, anchors[1:])]
        result.append({'trainingRatings': [curve(x, anchors) for x in ref['rawQuantiles']], 'slopes': slopes})
    return result


def input_fingerprint(raw, metadata, config):
    return hashlib.sha256(raw + json.dumps(metadata, sort_keys=True).encode() + json.dumps(config, sort_keys=True).encode() + b'curve-grid-v1').hexdigest()


def collect(data, output, config, limit=None, max_candidates=1000000, estimate=False):
    total = combination_count(config)
    print(f'{total:,} valid combinations (0 < P50 < P75 < P90).', flush=True)
    if total == 0:
        raise ValueError('The configured grid contains no valid combinations.')
    if estimate:
        return total
    if total > max_candidates:
        raise ValueError(f'{total:,} exceeds --max-candidates {max_candidates:,}. Narrow the grid or explicitly raise this limit.')
    if limit is not None and limit <= 0:
        raise ValueError('--limit must be positive.')
    raw = (data / 'maps.jsonl').read_bytes()
    metadata = json.loads((data / 'export.json').read_text(encoding='utf-8'))
    fingerprint = input_fingerprint(raw, metadata, config)
    output.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(output / 'search.sqlite', timeout=2)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS manifest(id INTEGER PRIMARY KEY CHECK(id=1), fingerprint TEXT, data TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS candidates(id INTEGER PRIMARY KEY, p50 REAL, p75 REAL, p90 REAL, stats BLOB)')
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS candidate_targets ON candidates(p50,p75,p90)')
    existing = db.execute('SELECT fingerprint,data FROM manifest WHERE id=1').fetchone()
    if existing and existing[0] != fingerprint:
        db.close()
        raise ValueError('Config, model, or map export changed. Choose a new --out directory; existing results were preserved.')
    samples = [json.loads(line) for line in raw.splitlines()]
    if existing:
        manifest = json.loads(existing[1])
    else:
        manifest = {'fingerprint': fingerprint, 'model': metadata['model'], 'total': total, 'config': config,
                    'references': prepare(samples, metadata, config), 'dataDirectory': str(data.resolve()),
                    'notes': ['No ranking or winner. Only the configured finite grid is enumerated.',
                              'P50 sets the common numeric unit; proportional target triples have identical normalized shape.',
                              'Only training maps fit the curves. Holdout maps do not enter search statistics.',
                              'These are map-only perfect-play demands, not observed player scores.',
                              'Equal distributions do not establish equal human difficulty. Accuracy remains a map proxy.']}
        db.execute('INSERT INTO manifest VALUES(1,?,?)', (fingerprint, json.dumps(manifest)))
        db.commit()
    # Resume from committed rows, not a separate progress file that can get out of sync.
    last = db.execute('SELECT COALESCE(MAX(id),0) FROM candidates').fetchone()[0]
    count = db.execute('SELECT COUNT(*) FROM candidates').fetchone()[0]
    if last != count:
        raise ValueError('Candidate IDs are not contiguous; database must be inspected before resuming.')
    start_time, added = time.monotonic(), 0
    print(f'Resume: {count:,}/{total:,} already saved. Stop with Ctrl+C; rerun the same command to continue.', flush=True)
    try:
        # Keep a writer transaction; concurrent viewers may read committed rows through WAL.
        db.execute('BEGIN IMMEDIATE')
        for index, targets in enumerate(itertools.islice(combinations(config), last, None), last + 1):
            blob = zlib.compress(json.dumps(stats_for(manifest['references'], targets), separators=(',', ':')).encode())
            db.execute('INSERT INTO candidates VALUES(?,?,?,?,?)', (index, *targets, blob))
            added += 1
            if added % 250 == 0:
                db.commit()
                elapsed = time.monotonic() - start_time
                print(f'{index:,}/{total:,} saved · {added / max(elapsed,.001):.0f} combinations/s', flush=True)
                db.execute('BEGIN IMMEDIATE')
            if limit is not None and added >= limit:
                break
    except KeyboardInterrupt:
        print('\nInterrupted; saving completed candidates.', flush=True)
    finally:
        db.commit()
        saved = db.execute('SELECT COUNT(*) FROM candidates').fetchone()[0]
        db.close()
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{saved:,}/{total:,} saved. View with: npm run calibrate:search -- --serve --out "{output}"', flush=True)
    return saved


def serve(output, port):
    def database():
        return sqlite3.connect((output / 'search.sqlite').resolve().as_uri() + '?mode=ro', uri=True)
    with closing(database()) as db:
        manifest = json.loads(db.execute('SELECT data FROM manifest WHERE id=1').fetchone()[0])
    data = Path(manifest['dataDirectory'])
    raw = (data / 'maps.jsonl').read_bytes()
    metadata = json.loads((data / 'export.json').read_text(encoding='utf-8'))
    if input_fingerprint(raw, metadata, manifest['config']) != manifest['fingerprint']:
        raise ValueError('The source export has changed. Do not mix old candidates with new map values; create a new search directory.')
    maps = [json.loads(line) for line in raw.splitlines()]
    by_hash = {s['hash']: s for s in maps}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass

        def do_GET(self):
            url = urlsplit(self.path)
            args = parse_qs(url.query)
            try:
                if url.path == '/':
                    body = HERE.joinpath('search_view.html').read_bytes()
                    self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.end_headers(); self.wfile.write(body)
                    return
                if url.path == '/api/info':
                    with closing(database()) as db:
                        result = dict(manifest, saved=db.execute('SELECT COUNT(*) FROM candidates').fetchone()[0])
                elif url.path == '/api/candidate':
                    with closing(database()) as db:
                        if 'targets' in args:
                            targets = json.loads(args['targets'][0])
                            row = db.execute('SELECT * FROM candidates WHERE p50=? AND p75=? AND p90=?', targets).fetchone()
                        else:
                            row = db.execute('SELECT * FROM candidates WHERE id=?', (int(args.get('id', ['1'])[0]),)).fetchone()
                    if not row: raise ValueError('Diese Kombination ist nicht gespeichert.')
                    result = {'id': row[0], 'targets': row[1:4], 'stats': json.loads(zlib.decompress(row[4])),
                              'curves': [anchors_for(r, row[1:4]) for r in manifest['references']]}
                elif url.path == '/api/maps':
                    query = args.get('q', [''])[0].casefold()
                    selected = [s for s in maps if len(query) >= 2 and query in (s['artist']+' '+s['title']+' '+s['version']).casefold()][:50]
                    result = [{'hash': s['hash'], 'label': s['artist']+' – '+s['title']+' ['+s['version']+']'} for s in selected]
                elif url.path == '/api/map':
                    result = by_hash[args['hash'][0]]
                else:
                    self.send_error(404); return
                payload = json.dumps(result, ensure_ascii=False).encode()
                self.send_response(200); self.send_header('Content-Type', 'application/json; charset=utf-8'); self.end_headers(); self.wfile.write(payload)
            except (KeyError, ValueError, TypeError) as error:
                self.send_error(400, str(error).encode('ascii', errors='replace').decode())
    print(f'Local viewer: http://127.0.0.1:{port} · stop with Ctrl+C. Ratings unchanged.', flush=True)
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=HERE / 'search-config.json')
    parser.add_argument('--data', type=Path, default=HERE / '.cache')
    parser.add_argument('--out', type=Path, default=HERE / '.cache/search')
    parser.add_argument('--estimate', action='store_true', help='Only count valid combinations; no files changed.')
    parser.add_argument('--serve', action='store_true', help='Open local read-only exploration server; no search runs.')
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--limit', type=int, help='Process this many NEW combinations, then save; rerun to continue.')
    parser.add_argument('--max-candidates', type=int, default=1000000, help='Explicit finite-grid size guard; raise for larger grids.')
    args = parser.parse_args()
    if args.serve:
        serve(args.out.resolve(), args.port)
    else:
        config = json.loads(args.config.read_text(encoding='utf-8'))
        collect(args.data.resolve(), args.out.resolve(), config, args.limit, args.max_candidates, args.estimate)


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, sqlite3.Error) as error:
        print(f'Error: {error}', file=sys.stderr)
        sys.exit(1)
