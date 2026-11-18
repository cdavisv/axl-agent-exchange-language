import copy, json, unittest
from benchmark import *
from chunking import split_record, reassemble

class ChunkTests(unittest.TestCase):

    def record(self, text):
        return {'prefix': 'NT', 'fields': {'id': 'original', 'to': '@fixer'}, 'payload': {'summary': text}}

    def test_large_lossless(self):
        for text in ['a' * 10000, '你好🦊"\\\n' * 3000, '', 'long path.py:1-900\n' + 'return 1\n' * 3000]:
            r = self.record(text)
            parts = split_record(r)
            self.assertEqual(reassemble(parts), r)
            for p in parts:
                for mode in SCHEMAS:
                    self.assertEqual(decode(encode(p, mode), mode), p)
                self.assertTrue(all((len(line.encode('utf-8')) <= 8192 for line in encode(p, 'axl').splitlines())))

    def test_tamper_drop_duplicate_reorder_rejected(self):
        p = split_record(self.record('x' * 15000))
        variants = [p[1:], p[:-1], p + p[-1:], list(reversed(p))]
        q = copy.deepcopy(p)
        m = json.loads(q[0]['payload']['summary'])
        m['text'] = 'z' + m['text'][1:]
        q[0]['payload']['summary'] = json.dumps(m)
        variants.append(q)
        for v in variants:
            with self.assertRaises(ValueError):
                reassemble(v)

    def test_trusted_manifest_rejects_rewritten_digest(self):
        import hashlib
        text = 'a' * 10000
        p = split_record(self.record(text))
        expected = hashlib.sha256(text.encode()).hexdigest()
        self.assertEqual(reassemble(p, expected_source_id='original', expected_sha256=expected, expected_to='@fixer'), self.record(text))
        for c in p:
            m = json.loads(c['payload']['summary'])
            m['text'] = m['text'].replace('a', 'b')
            m['sha256'] = hashlib.sha256(('b' * 10000).encode()).hexdigest()
            c['payload']['summary'] = json.dumps(m)
        with self.assertRaises(ValueError):
            reassemble(p, expected_sha256=expected)

    def test_shared_envelope_semantics(self):
        records = corpus()[:30]
        s = render('shared_json', [encode(r, 'shared_json') for r in records])
        o = json.loads(s.split('\n', 1)[1])
        rebuilt = [{'prefix': o['prefix'], 'fields': {'id': i, 'to': o['to']}, 'payload': {'summary': v}} for i, v in o['rows']]
        self.assertEqual(rebuilt, records)
if __name__ == '__main__':
    unittest.main()
