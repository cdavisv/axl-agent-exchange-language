import unittest
from benchmark import *

class Tests(unittest.TestCase):

    def test_edge_roundtrip(self):
        for value in ['', '; = : > {} []', '\n\t', '"\\quoted"', '你好 é 🦊', '  padding  ', 'x\r\ny', '{"value":1}', 'a' * 7000]:
            r = {'prefix': 'NT', 'fields': {'id': 'e0', 'to': '@fixer'}, 'payload': {'summary': value}}
            for mode in SCHEMAS:
                self.assertEqual(decode(encode(r, mode), mode), r)

    def test_axl_oversize_fails_closed(self):
        from axl import AxlParseError
        r = {'prefix': 'NT', 'fields': {'id': 'e0', 'to': '@fixer'}, 'payload': {'summary': 'a' * 10000}}
        with self.assertRaises(AxlParseError):
            encode(r, 'axl')
        self.assertEqual(decode(encode(r, 'flat_json'), 'flat_json'), r)

    def test_result_contract(self):
        rows = json.loads((ROOT / 'results.json').read_text())
        self.assertEqual(len(rows), 1800)
        for r in rows:
            self.assertIsNone(r['agent_success'])
            if r['budget']:
                self.assertLessEqual(r['tokens'], r['budget'])

    def test_corpus(self):
        records = corpus()
        self.assertEqual(len({r['fields']['id'] for r in records}), len(records))
        for r in records:
            for mode in SCHEMAS:
                self.assertEqual(decode(encode(r, mode), mode), r)
if __name__ == '__main__':
    unittest.main()
