"""Regression checks for retained counterexamples; full reproduction uses verify.py."""
import json
from pathlib import Path
import unittest

class SummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = json.loads(Path(__file__).with_name('summary.json').read_text())

    def test_checks_and_selections(self):
        for result in self.results.values():
            self.assertEqual(result['checks'], 1824)
            for counts in result['selection_counts'].values():
                self.assertEqual(sum(counts.values()), 608)

    def test_gemma_retained_loss(self):
        for modes in self.results['gemma']['summary'].values():
            self.assertGreater(modes['hybrid_context']['retained_context'], modes['guarded_packed_json']['retained_context'])
            self.assertLess(modes['hybrid_wire']['wire'], modes['guarded_packed_json']['wire'])

    def test_best_static_remains_better(self):
        for result in self.results.values():
            for modes in result['summary'].values():
                best = min(modes[name]['retained_context'] for name in ('typed_rows','guarded_packed_json'))
                self.assertGreater(modes['hybrid_context']['retained_context'], best)

if __name__ == '__main__':
    unittest.main()
