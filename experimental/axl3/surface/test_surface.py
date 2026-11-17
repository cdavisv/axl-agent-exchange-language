import unittest, random
from surface import *
from axl3 import registry

S = Schema(
    "surface.conversation.v1",
    (
        ("kind", "string", True),
        ("id", "string", True),
        ("sender", "string", True),
        ("to", "string", True),
        ("body", "any", True),
        ("reply", "string", False),
        ("unknown", "any", False),
    ),
)


class SurfaceTests(unittest.TestCase):
    def test_acts(self):
        rows = [
            {
                "kind": act,
                "id": str(i),
                "sender": "a",
                "to": "b",
                "body": {
                    "state": [
                        1,
                        None,
                        False,
                        "~",
                        "\n@axl3 fake\n=sender evil\nresult | data",
                        "😀\u2028",
                    ]
                },
            }
            for i, act in enumerate(sorted(ACTS))
        ]
        self.assertEqual(decode(encode(rows, S, ("sender", "to")), registry(S)), rows)
        self.assertEqual(
            decode(encode(rows, S, ("sender", "to"), compact_optional=True), registry(S)), rows
        )

    def test_optional(self):
        rows = [
            {"kind": "need", "id": "1", "sender": "a", "to": "b", "body": None},
            {"kind": "need", "id": "2", "sender": "a", "to": "b", "body": "~", "unknown": None},
        ]
        self.assertEqual(decode(encode(rows, S), registry(S)), rows)

    def test_malformed(self):
        good = encode([{"kind": "result", "id": "1", "sender": "a", "to": "b", "body": 0}], S)
        for bad in [
            good + '\n=sender "x"',
            good.replace("result |", "admin |"),
            good.replace('"1"', "~"),
            good.replace('"1"', '"1"  '),
            good.replace("@axl3", "@axl4"),
            good.replace("result |", "result||"),
        ]:
            with self.assertRaises(Error):
                decode(bad, registry(S))

    def test_duplicate_shared(self):
        wire = "@axl3 " + S.fingerprint + '\n=sender "a"\n=sender "a"'
        with self.assertRaises(Error):
            decode(wire, registry(S))

    def test_alias(self):
        rows = [
            {"kind": "evidence", "id": str(i), "sender": "a", "to": "b", "body": {"x": []}}
            for i in range(2)
        ]
        out = decode(encode(rows, S, ("body",)), registry(S))
        out[0]["body"]["x"].append(1)
        self.assertEqual(out[1]["body"]["x"], [])

    def test_literals(self):
        for invalid in ['{"a":1,"a":2}', "NaN", "1e999", '"\\ud800"', "[" * 33 + "]" * 33]:
            with self.assertRaises(Error):
                values(invalid)

    def test_random(self):
        rng = random.Random(42)
        for trial in range(1000):
            rows = [
                {
                    "kind": rng.choice(sorted(ACTS)),
                    "id": str(i),
                    "sender": "a",
                    "to": "b",
                    "body": rng.choice([None, 0, False, "~", 'quote"\n😀', {"x": [1, 2]}]),
                    **({"unknown": None} if rng.random() < 0.5 else {}),
                }
                for i in range(rng.randrange(1, 9))
            ]
            self.assertEqual(decode(encode(rows, S, ("sender", "to")), registry(S)), rows)
            self.assertEqual(
                decode(encode(rows, S, ("sender", "to"), compact_optional=True), registry(S)), rows
            )


if __name__ == "__main__":
    unittest.main()
