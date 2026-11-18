import unittest
from dictionary import *
from axl3 import Schema, registry

S = Schema(
    "evidence.dictionary.v1",
    (
        ("kind", "string", True),
        ("id", "string", True),
        ("sender", "string", True),
        ("to", "string", True),
        ("body", "any", True),
        ("unknown", "any", False),
    ),
)


class DictTests(unittest.TestCase):
    def records(self):
        return [
            {
                "kind": "evidence",
                "id": str(i),
                "sender": "a",
                "to": "b",
                "body": {
                    "text": "Original😀source " * 40,
                    "source": "file:///source",
                    "timestamp": "2026-01-01",
                    "claim": "unverified",
                },
            }
            for i in range(4)
        ]

    def test_cold_warm(self):
        rs = self.records()
        w, c = encode(rs, S, ("sender", "to"), scope="s1")
        back, c2, stats = decode(w, registry(S), expected_scope="s1")
        self.assertEqual(back, rs)
        self.assertEqual(c, c2)
        self.assertEqual(stats["references"], 4)
        warm, c3 = encode(rs, S, ("sender", "to"), scope="s1", cache=c)
        self.assertNotIn("\n&", warm)
        self.assertEqual(decode(warm, registry(S), expected_scope="s1", cache=c)[0], rs)

    def test_literal_not_reference(self):
        rs = self.records()
        rs[0]["body"] = "^e0"
        w, c = encode(rs, S)
        self.assertEqual(decode(w, registry(S), expected_scope="batch")[0], rs)

    def test_invalid(self):
        rs = self.records()
        w, c = encode(rs, S)
        for bad in [
            w.replace("^e0", "^missing"),
            w.replace("&e0", "&bad-name"),
            w + "\n&e9 " + ("0" * 64) + " null",
            w.replace(" batch", " other", 1),
        ]:
            with self.assertRaises(Error):
                decode(bad, registry(S), expected_scope="batch")

    def test_stale_hash(self):
        w, c = encode(self.records(), S)
        name, h, text = c.entries[0]
        bad = Cache("batch", ((name, "0" * 64, text),))
        with self.assertRaises(Error):
            decode(w, registry(S), expected_scope="batch", cache=bad)
        with self.assertRaises(Error):
            decode(w.replace(h, "0" * 64), registry(S), expected_scope="batch")

    def test_scope(self):
        w, c = encode(self.records(), S)
        with self.assertRaises(Error):
            decode(w, registry(S), expected_scope="other", cache=c)

    def test_mutation_alias(self):
        w, c = encode(self.records(), S)
        rows, _, _ = decode(w, registry(S), expected_scope="batch")
        rows[0]["body"]["text"] = "changed"
        self.assertNotEqual(rows[1]["body"]["text"], "changed")

    def test_no_repeat(self):
        rs = [{**r, "body": {"text": str(i)}} for i, r in enumerate(self.records())]
        w, c = encode(rs, S)
        self.assertEqual(c.entries, ())
        self.assertEqual(decode(w, registry(S), expected_scope="batch")[0], rs)

    def test_wrong_valid_cache_rejected(self):
        rs = self.records()
        _, a = encode(rs, S)
        other = [{**r, "body": {"text": "different " * 100}} for r in rs]
        _, b = encode(other, S)
        warm, _ = encode(rs, S, cache=a)
        with self.assertRaisesRegex(Error, "Stale cache manifest"):
            decode(warm, registry(S), expected_scope="batch", cache=b)

    def test_type_fidelity(self):
        vals = [True, 1, 1.0, -0.0, "^e0"] * 2
        rs = [
            {"kind": "evidence", "id": str(i), "sender": "a", "to": "b", "body": v}
            for i, v in enumerate(vals)
        ]
        w, c = encode(rs, S, min_bytes=0)
        back, _, _ = decode(w, registry(S), expected_scope="batch")
        self.assertEqual(dump(back), dump(rs))


if __name__ == "__main__":
    unittest.main()
