import dataclasses
import json
import random
import unittest
from semantic import SemanticSchema, encode, decode, validate_records
from axl3 import Error, Schema, dump, load


class SemanticTests(unittest.TestCase):
    def setUp(self):
        self.s = SemanticSchema(
            Schema("sem.test", (("status", "string", True), ("value", "any", False))),
            (("status", ("queued", "ready")),),
            (("status", '"queued"'), ("value", "0")),
        )
        self.reg = {self.s.fingerprint: self.s}

    def test_absence_default_null_exact_types(self):
        rows = [
            {"status": "queued"},
            *({"status": "ready", "value": v} for v in (None, 0, 0.0, -0.0, False, "0", [], {})),
        ]
        wire = encode(rows, self.s)
        self.assertEqual(
            json.dumps(decode(wire, self.reg), sort_keys=True), json.dumps(rows, sort_keys=True)
        )
        states = [row[0] for row in load(wire)[2]]
        self.assertEqual(states[:4], ["10", "22", "21", "22"])
        self.assertEqual(states[4], "22")

    def test_invalid_definitions_and_immutability(self):
        bad = [
            {"enums": (("status", ("a", "a")),)},
            {"enums": (("status", ()),)},
            {"enums": (("value", ("x",)),)},
            {"defaults": (("value", "NaN"),)},
            {"defaults": (("status", "1"),)},
            {"enums": self.s.enums, "defaults": (("status", '"outside"'),)},
            {"defaults": (("value", "0"), ("value", "1"))},
            {"enums": [("status", ("a",))]},
        ]
        for kw in bad:
            with self.assertRaises(Error):
                SemanticSchema(self.s.base, **kw)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.s.enums = ()
        definition = self.s.definition
        definition["enums"][0][1].append("changed")
        self.assertEqual(self.s.enums[0][1], ("queued", "ready"))

    def test_malformed_presence_ordinals_and_duplicatekeys(self):
        cases = [
            ["02", [0]],
            ["12", []],
            ["13", [0]],
            ["222", [0]],
            ["22", [True, None]],
            ["22", [-1, None]],
            ["22", [2, None]],
            ["22", [0.0, None]],
            ["11", [1]],
        ]
        for row in cases:
            with self.assertRaises(Error):
                decode(dump(["axl3-sem1", self.s.fingerprint, [row]]), self.reg)
        with self.assertRaises(Error):
            decode(
                '["axl3-sem1","' + self.s.fingerprint + '",[["22",[0,{"x":1,"x":2}]]]]', self.reg
            )
        with self.assertRaises(Error):
            decode(dump([True, self.s.fingerprint, []]), self.reg)
        with self.assertRaises(Error):
            decode(dump(["axl3-sem1", "unknown", []]), self.reg)
        with self.assertRaises(Error):
            encode([{"status": "other"}], self.s)
        plain = SemanticSchema(self.s.base)
        with self.assertRaises(Error):
            decode(dump(["axl3-sem1", plain.fingerprint, [["11", []]]]), {plain.fingerprint: plain})

    def test_detached_default_and_expansion_bounds(self):
        schema = SemanticSchema(
            Schema("defaults", (("v", "any", True),)), defaults=(("v", '{"x":[]}'),)
        )
        out = decode(
            encode([{"v": {"x": []}}, {"v": {"x": []}}], schema), {schema.fingerprint: schema}
        )
        out[0]["v"]["x"].append(1)
        self.assertEqual(out[1]["v"], {"x": []})
        huge = SemanticSchema(schema.base, defaults=(("v", json.dumps("x" * 150000)),))
        with self.assertRaises(Error):
            decode(
                dump(["axl3-sem1", huge.fingerprint, [["1", []], ["1", []]]]),
                {huge.fingerprint: huge},
            )

    def test_generated_exact_roundtrips(self):
        rng = random.Random(717)
        choices = [None, 0, 0.0, -0.0, False, "0", {"a": [1, "1"]}, []]
        for _ in range(500):
            rows = []
            for _ in range(rng.randrange(9)):
                row = {"status": rng.choice(("queued", "ready"))}
                if rng.randrange(3):
                    row["value"] = rng.choice(choices)
                rows.append(row)
            self.assertEqual(
                json.dumps(decode(encode(rows, self.s), self.reg), sort_keys=True),
                json.dumps(rows, sort_keys=True),
            )

    def test_limits_and_numeric_lexemes(self):
        with self.assertRaises(Error):
            encode([{"status": "queued"}] * 1025, self.s)
        for literal in ("-0", "1e999", "0.10000000000000001"):
            wire = '["axl3-sem1","' + self.s.fingerprint + '",[["22",[0,' + literal + "]]]]"
            with self.assertRaises(Error):
                decode(wire, self.reg)
        with self.assertRaises(Error):
            decode(" " * 262145, self.reg)


if __name__ == "__main__":
    unittest.main()
