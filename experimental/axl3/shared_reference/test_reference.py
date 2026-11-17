import json
import random
import hashlib
import unittest
from pathlib import Path
from unittest.mock import patch
import axl3 as new
import baseline_axl3 as old


def schema(module):
    return module.Schema(
        "shared.reference.test", (("id", "integer", True), ("value", "any", False))
    )


def outcome(fn):
    try:
        return ("ok", fn())
    except Exception as exc:
        return (type(exc).__name__, str(exc))


class ReferenceTests(unittest.TestCase):
    def assert_pack_same(self, records, shared=("value",)):
        a = outcome(lambda: old.pack(records, schema(old), shared))
        b = outcome(lambda: new.pack(records, schema(new), shared))
        self.assertEqual(a, b)
        if a[0] == "ok":
            self.assertEqual(new.unpack(a[1], new.registry(schema(new))), records)

    def test_spelling_and_errors(self):
        values = [
            None,
            True,
            False,
            0,
            0.0,
            -0.0,
            1,
            1.0,
            "1",
            "true",
            "\ud800",
            float("inf"),
            [],
            {},
            [1],
            {"a": 1, "b": 2},
            {"b": 2, "a": 1},
        ]
        for a in values:
            for b in values:
                self.assert_pack_same([{"id": 0, "value": a}, {"id": 1, "value": b}])
        for records in [
            [],
            [{"id": 0}],
            [{"id": 0, "value": 0}, {"id": 1}],
            [{"id": 0, "value": [], "unknown": 1}],
            [{"id": "bad", "value": 0}],
            [{"id": 0, "value": object()}],
        ]:
            self.assert_pack_same(records)

    def test_one_shot_sharing_and_subclass(self):
        records = [{"id": 0, "value": [1]}, {"id": 1, "value": [1]}]
        self.assertEqual(
            old.pack(records, schema(old), (x for x in ["value"])),
            new.pack(records, schema(new), (x for x in ["value"])),
        )
        outputs = []
        for m in (old, new):

            class Sub(m.Schema):
                def check(self, obj):
                    super().check(obj)

            s = Sub("sub", (("id", "integer", True), ("value", "any", True)))
            outputs.append(m.pack(records, s, ["value"]))
        self.assertEqual(*outputs)

    def test_frozen_corpus(self):
        path = Path(__file__).resolve().parents[1] / "typed_rows" / "heldout-corpus.json"
        for case in json.loads(path.read_text())["cases"]:
            schemas = [
                m.Schema(
                    "heldout." + case["family"] + ".v1",
                    tuple((name, kind, True) for name, kind in case["fields"]),
                )
                for m in (old, new)
            ]
            for records in case["turns"]:
                self.assertEqual(
                    old.pack(records, schemas[0], tuple(case["shared"])),
                    new.pack(records, schemas[1], tuple(case["shared"])),
                )

    def test_dump_call_reduction(self):
        counts = []
        for m in (old, new):
            s = schema(m)
            records = [{"id": i, "value": "same"} for i in range(8)]
            s.fingerprint
            real = m.dump
            with patch.object(m, "dump", wraps=real) as mocked:
                m.pack(records, s, ["value"])
                counts.append(mocked.call_count)
        self.assertEqual(counts[0] - counts[1], 7)

    def test_baseline_pin(self):
        expected = json.loads(Path(__file__).with_name("results.json").read_text())[
            "baseline_sha256"
        ]
        self.assertEqual(
            hashlib.sha256(Path(__file__).with_name("baseline_axl3.py").read_bytes()).hexdigest(),
            expected,
        )


if __name__ == "__main__":
    unittest.main()
