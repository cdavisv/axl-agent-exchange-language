import json
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import axl3 as new
import baseline_axl3 as old


class DeferredTests(unittest.TestCase):
    def outcome(self, module, wire, fields=(("x", "any", True),)):
        schema = module.Schema("deferred", fields)
        try:
            result = module.unpack(wire, module.registry(schema))
            return ("ok", json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        except module.Error as exc:
            return ("error", str(exc))

    def parity(self, envelope, fields=(("x", "any", True),)):
        wire = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
        self.assertEqual(self.outcome(old, wire, fields), self.outcome(new, wire, fields))
        return wire

    def test_invalid_order_and_limits(self):
        key = old.Schema("deferred", (("x", "any", True),)).fingerprint
        for n in (1000, 2000, 8000, 16000):
            for tail in ([], ["bad"], [[0]], [[None, None]]):
                self.parity([3, key, {"0": [0] * n}, [[]] * 33 + tail])
        for n in (1019, 1020, 1021, 1022):
            self.parity([3, key, {"0": [0] * n}, [[]] * 32])
        for constants, rows in (
            ({"0": False}, [["bad"]]),
            ({"01": False}, [[]]),
            ({"0": None}, []),
        ):
            self.parity([3, key, constants, rows])

    def test_differential_mutations(self):
        rng = random.Random(17017)
        fields = (("x", "any", True), ("y", "string", False))
        key = old.Schema("deferred", fields).fingerprint
        values = [None, False, 0, 1.0, "001", {"nested": [None, True, "é"]}, [[], {}]]
        for i in range(500):
            constants = {"0": rng.choice(values)} if rng.randrange(2) else {}
            rows = []
            for j in range(rng.randrange(15)):
                bit = rng.randrange(2)
                row = (
                    [str(bit)]
                    + ([] if constants else [rng.choice(values)])
                    + (["x"] if bit else [])
                )
                rows.append(row)
            envelope = [3, key, constants, rows]
            if i % 3 == 0:
                mutation = rng.randrange(5)
                if mutation == 0:
                    envelope[0] = True
                if mutation == 1:
                    envelope[2]["nope"] = 0
                if mutation == 2:
                    envelope[3].append("bad")
                if mutation == 3:
                    envelope[1] = "unknown"
                if mutation == 4:
                    envelope[3].append(["00"])
            self.parity(envelope, fields)

    def test_returns_isolation_and_subclass(self):
        for module in (old, new):
            schema = module.Schema("deferred", (("x", "any", True),))
            self.assertIsNone(module.validate_value(1))
            self.assertIsNone(schema.check({"x": 1}))
            wire = module.pack([{"x": {"a": [0]}}, {"x": {"a": [0]}}], schema, ["x"])
            result = module.unpack(wire, module.registry(schema))
            result[0]["x"]["a"].append(1)
            self.assertEqual(result[1]["x"], {"a": [0]})

            class Sub(module.Schema):
                def check(self, obj):
                    super().check(obj)

            sub = Sub("sub", (("x", "any", True),))
            self.assertEqual(
                module.unpack(module.pack([{"x": []}], sub), module.registry(sub)), [{"x": []}]
            )

    def test_no_copy_before_rejection(self):
        from unittest.mock import patch

        schema = new.Schema("deferred", (("x", "any", True),))
        wire = new.dump([3, schema.fingerprint, {"0": [0] * 2000}, [[]] * 100])
        with patch.object(new.copy, "deepcopy", side_effect=AssertionError("unnecessary copy")):
            with self.assertRaisesRegex(new.Error, "Expanded output limit"):
                new.unpack(wire, new.registry(schema))


if __name__ == "__main__":
    unittest.main()
