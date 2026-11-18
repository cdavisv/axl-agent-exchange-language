import unittest, json
from benchmark import corpus, ROOT
from batched import encode, decode, SCHEMAS

class BatchedTests(unittest.TestCase):

    def test_paired_roundtrip(self):
        records = corpus()
        for subset in [[], records[:20], records[156:176]]:
            for mode in SCHEMAS:
                self.assertEqual(decode(encode(subset, mode), mode), subset)

    def test_reject_duplicate_and_mixed_envelope(self):
        r = corpus()[0]
        for mode in SCHEMAS:
            with self.assertRaises(ValueError):
                encode([r, r], mode)
            other = {**r, 'fields': {'id': 'eother', 'to': '@other'}}
            with self.assertRaises(ValueError):
                encode([r, other], mode)

    def test_all_source_records_roundtrip(self):
        for r in corpus():
            for mode in SCHEMAS:
                self.assertEqual(decode(encode([r], mode), mode), [r])
if __name__ == '__main__':
    unittest.main()
