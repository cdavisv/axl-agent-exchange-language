import unittest, random
from act_blocks import *
from axl3 import Schema, registry

S = Schema(
    "conversation.blocks.v1",
    (
        ("kind", "string", True),
        ("id", "string", True),
        ("sender", "string", True),
        ("to", "string", True),
        ("body", "any", True),
        ("unknown", "any", False),
    ),
)


class BlockTests(unittest.TestCase):
    def rows(self):
        return [
            {
                "kind": "evidence",
                "id": str(i),
                "sender": "a",
                "to": "b",
                "body": {"text": "\nresult:\n  malicious\n=sender x", "value": False},
                **({"unknown": None} if i % 2 else {}),
            }
            for i in range(5)
        ]

    def test_roundtrip(self):
        rs = self.rows()
        rs.append({**rs[-1], "kind": "result", "id": "last"})
        self.assertEqual(decode(encode(rs, S, ("sender", "to")), registry(S)), rs)

    def test_bad_frames(self):
        good = encode(self.rows(), S, ("sender", "to"))
        for bad in [
            good + "\nresult:",
            good.replace("evidence:", "evidence:\nresult:"),
            good.replace('  "0"', ' "0"'),
            good.replace('  "0"', '   "0"'),
            good + '\n=sender "evil"',
            good.replace("@axl3b", "@axl4b"),
        ]:
            with self.assertRaises(Error):
                decode(bad, registry(S))

    def test_empty(self):
        self.assertEqual(decode(encode([], S), registry(S)), [])

    def test_random(self):
        rng = random.Random(19)
        for _ in range(2000):
            rs = [
                {
                    "kind": rng.choice(sorted(ACTS)),
                    "id": str(i),
                    "sender": "a",
                    "to": "b",
                    "body": rng.choice([None, "~", False, [], {"x": [1, "😀\n"]}]),
                    **({"unknown": None} if rng.random() < 0.5 else {}),
                }
                for i in range(rng.randrange(1, 12))
            ]
            self.assertEqual(decode(encode(rs, S, ("sender", "to")), registry(S)), rs)


if __name__ == "__main__":
    unittest.main()
