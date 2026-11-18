import random, unittest
from pipes import *
from axl3 import Schema

S = Schema(
    "pipe.test.v1",
    (
        ("kind", "string", True),
        ("id", "string", True),
        ("body", "any", True),
        ("optional", "any", False),
    ),
)


class PipeTests(unittest.TestCase):
    def rows(self):
        return [
            {
                "kind": "result",
                "id": "a",
                "body": {
                    "text": 'literal | content and \\"quotes"\nresult | fake',
                    "state": [True, 1, 1.0, None],
                },
                "optional": "~",
            }
        ]

    def test_pipe_profile(self):
        rows = self.rows()
        self.assertEqual(decode(encode(rows, S), registry(S)), rows)

    def test_opt_in(self):
        bad = encode(self.rows(), S).replace("@axl3p ", "@axl3 ", 1)
        with self.assertRaises(Error):
            normalize_extra_separators(bad, registry(S))
        result = normalize_extra_separators(bad, registry(S), allow=True)
        self.assertEqual(old_decode(result.wire, registry(S)), self.rows())
        self.assertEqual(result.removed_separators, 2)

    def test_mixed(self):
        row = {"kind": "need", "id": "a", "body": None}
        bad = old_encode([row], S).replace('"a" null ~', '"a" | null ~')
        n = normalize_extra_separators(bad, registry(S), allow=True)
        self.assertEqual(old_decode(n.wire, registry(S)), [row])

    def test_missing_ambiguous_rejected(self):
        header = "@axl3 " + S.fingerprint + "\nresult | "
        for text in [
            '"a" | | null | ~',
            '"a" || null | ~',
            '"a" | null |',
            '"a" | null',
            '"a"|null|~',
            '"a" | [1 | 2] | ~',
            '"a" | NaN | ~',
        ]:
            with self.assertRaises(Error):
                normalize_extra_separators(header + text, registry(S), allow=True)

    def test_strict_profile_rejects_old(self):
        old = old_encode(self.rows(), S).replace("@axl3 ", "@axl3p ", 1)
        with self.assertRaises(Error):
            decode(old, registry(S))

    def test_early_column_cap(self):
        with self.assertRaisesRegex(Error, "Too many columns"):
            split_top_level_pipes("0 | " * 50000 + "0")

    def test_valid_wire_unchanged(self):
        wire = old_encode(self.rows(), S)
        n = normalize_extra_separators(wire, registry(S), allow=True)
        self.assertEqual(n.wire, wire)
        self.assertEqual(n.original_sha256, n.normalized_sha256)

    def test_valid_compact_wire_unchanged(self):
        wire = old_encode(self.rows(), S, compact_optional=True)
        n = normalize_extra_separators(wire, registry(S), allow=True)
        self.assertEqual(n.wire, wire)
        self.assertEqual(n.removed_separators, 0)

    def test_random(self):
        rng = random.Random(5)
        for _ in range(1500):
            rows = [
                {
                    "kind": rng.choice(sorted(ACTS)),
                    "id": str(i),
                    "body": rng.choice(
                        ["|", " | ", '\\" | \n', None, False, 1, 1.0, {"a|b": ["|", None]}]
                    ),
                    **({"optional": None} if rng.random() < 0.5 else {}),
                }
                for i in range(rng.randrange(1, 6))
            ]
            wire = encode(rows, S)
            self.assertEqual(dump(decode(wire, registry(S))), dump(rows))
            altered = wire.replace("@axl3p ", "@axl3 ", 1)
            fixed = normalize_extra_separators(altered, registry(S), allow=True)
            self.assertEqual(dump(old_decode(fixed.wire, registry(S))), dump(rows))


if __name__ == "__main__":
    unittest.main()
