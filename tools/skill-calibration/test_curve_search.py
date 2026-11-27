from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zlib
from curve_search import axis, combinations, combination_count, collect, stats_for


CONFIG = {'targets': {'p50': {'min': 10, 'max': 11, 'step': 1}, 'p75': {'min': 12, 'max': 13, 'step': 1}, 'p90': {'min': 14, 'max': 15, 'step': 1}},
          'minCellMaps': 1, 'minTrainingMaps': 1, 'minCells': 1, 'quantilesToRecord': [.1, .5, .9]}


class SearchTests(unittest.TestCase):
    def test_grid_counts_and_decimal_steps(self):
        self.assertEqual(combination_count(CONFIG), len(list(combinations(CONFIG))))
        self.assertEqual(len(list(combinations(CONFIG))), 8)
        self.assertEqual(axis({'min': .1, 'max': .3, 'step': .1}), list(map(__import__('decimal').Decimal, ['.1', '.2', '.3'])))
        with self.assertRaises(ValueError): axis({'min': 1, 'max': 2, 'step': 0})
        c = dict(CONFIG, targets={k: {'min': 1, 'max': 3, 'step': 1} for k in ['p50', 'p75', 'p90']})
        self.assertEqual(list(combinations(c)), [(1., 2., 3.)])

    def test_resume_preserves_all_candidates_and_rejects_changed_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / 'data'; output = Path(tmp) / 'search'; data.mkdir()
            (data / 'export.json').write_text(json.dumps({'model': 'test', 'skills': [['speed', 'Speed']]}))
            rows = [{'hash': str(i), 'holdout': False, 'pattern': {'raw': [i+1], 'support': [20], 'coverage': [.5], 'stars': 5}} for i in range(10)]
            # This synthetic dataset has one skill; the feature-family helper expects eleven.
            for row in rows:
                row['pattern']['raw'] *= 11; row['pattern']['support'] *= 11; row['pattern']['coverage'] *= 11
            (data / 'maps.jsonl').write_text('\n'.join(map(json.dumps, rows)))
            self.assertEqual(collect(data, output, CONFIG, limit=3), 3)
            self.assertEqual(collect(data, output, CONFIG), 8)
            with closing(sqlite3.connect(output / 'search.sqlite')) as db:
                saved = db.execute('SELECT id,p50,p75,p90,stats FROM candidates ORDER BY id').fetchall()
            self.assertEqual([tuple(r[1:4]) for r in saved], list(combinations(CONFIG)))
            self.assertTrue(all(json.loads(zlib.decompress(r[4])) for r in saved))
            (data / 'maps.jsonl').write_text((data / 'maps.jsonl').read_text()+'\n')
            with self.assertRaises(ValueError): collect(data, output, CONFIG)

    def test_stats_follow_target_anchors_and_remain_monotone(self):
        ref = {'points': [{'raw': 2., 'targetIndex': 0}, {'raw': 3., 'targetIndex': 1}, {'raw': 4., 'targetIndex': 2}], 'rawQuantiles': [2., 3., 4., 8.]}
        stats = stats_for([ref], (15., 22., 30.))[0]
        self.assertEqual(stats['trainingRatings'][:3], [15., 22., 30.])
        self.assertGreater(stats['trainingRatings'][-1], 30)
        self.assertTrue(all(s > 0 for s in stats['slopes']))


if __name__ == '__main__': unittest.main()
