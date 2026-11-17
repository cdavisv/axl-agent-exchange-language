"""Schema metadata cache API, behavior and old/new codec differential checks."""

import copy
import gc
import weakref
import dataclasses
import hashlib
import inspect
import json
import pickle
import random
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent / "typed_rows")]
import axl3 as new
import typed_rows as typed
import baseline_axl3 as old
import baseline_typed_rows as oldtyped


class DynamicSchema(new.Schema):
    @property
    def definition(self):
        value = super().definition
        value["name"] += getattr(self, "suffix", "")
        return value


class CacheTests(unittest.TestCase):
    def test_constructor_parity_and_order(self):
        configs = [
            ("x", (("a", "string", True),)),
            ("x", (("a", "any", False), ("b", "number", True))),
            ("", (("a", "any", True),)),
            ("x", ()),
            ("x", [("a", "any", True)]),
            ("x", (("a", "any", 1),)),
            ("x", (("a", "unknown", True),)),
            ("x", (("a", "any", True), ("a", "any", False))),
            ("\ud800", (("a", "any", True),)),
            ("x", (("a", "string", True),) * 129),
        ]
        for name, fields in configs:
            outcomes = []
            for mod in (old, new):
                try:
                    s = mod.Schema(name, fields)
                    outcomes.append((s.definition, s.fingerprint))
                except mod.Error:
                    outcomes.append("Error")
            self.assertEqual(*outcomes)
        a = new.Schema("order", (("a", "any", True), ("b", "any", True)))
        b = new.Schema("order", tuple(reversed(a.fields)))
        self.assertNotEqual(a.fingerprint, b.fingerprint)

    def test_dataclass_api_copy_pickle_replace(self):
        fields = (("v", "any", True),)
        a = new.Schema("x", fields)
        before = repr(a)
        h = hash(a)
        self.assertEqual([f.name for f in dataclasses.fields(a)], ["name", "fields"])
        self.assertEqual(str(inspect.signature(new.Schema)), str(inspect.signature(old.Schema)))
        a.fingerprint
        a.check({"v": []})
        new.unpack(new.pack([{"v": []}], a), new.registry(a))
        self.assertEqual(repr(a), before)
        self.assertEqual(hash(a), h)
        self.assertEqual(dataclasses.asdict(a), {"name": "x", "fields": fields})
        for b in (
            copy.copy(a),
            copy.deepcopy(a),
            pickle.loads(pickle.dumps(a)),
            dataclasses.replace(a),
        ):
            self.assertEqual(a, b)
            self.assertEqual(a.fingerprint, b.fingerprint)
        replacement = dataclasses.replace(a, name="new")
        self.assertNotEqual(a.fingerprint, replacement.fingerprint)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            a.name = "changed"
        # Old pickled objects have only the two public fields. Equivalent state
        # restoration skips __init__/__post_init__, then lazily fills metadata.
        legacy = object.__new__(new.Schema)
        legacy.__dict__.update(name="x", fields=fields)
        restored = pickle.loads(pickle.dumps(legacy))
        self.assertEqual(restored.fingerprint, a.fingerprint)
        restored.check({"v": 1})

    def test_definition_fresh_and_subclass_dynamic(self):
        schema = new.Schema("x", (("v", "any", True),))
        fp = schema.fingerprint
        view = schema.definition
        view["fields"][0][0] = "changed"
        view["name"] = "changed"
        self.assertEqual(schema.fingerprint, fp)
        self.assertEqual(schema.definition["fields"][0][0], "v")
        child = DynamicSchema("dynamic", (("v", "any", True),))
        before = child.fingerprint
        child.suffix = "-later"
        self.assertNotEqual(child.fingerprint, before)
        self.assertNotIn("_fingerprint_cache", child.__dict__)

    def test_generated_and_mutated_codec_parity(self):
        rng = random.Random(621)
        for i in range(100):
            fields = tuple((f"f{j}", "any" if j else "string", True) for j in range(1 + i % 7))
            ns = new.Schema("case" + str(i), fields)
            os = old.Schema(ns.name, fields)
            records = [
                {
                    f[0]: ("str\n" + str(k) if j == 0 else [k, False, None, -0.0])
                    for j, f in enumerate(fields)
                }
                for k in range(i % 5)
            ]
            for enc1, enc2, dec1, dec2 in (
                (old.pack, new.pack, old.unpack, new.unpack),
                (oldtyped.encode, typed.encode, oldtyped.decode, typed.decode),
            ):
                wire = enc1(records, os)
                self.assertEqual(wire, enc2(records, ns))
                for candidate in [wire] + [
                    wire[: (pos := rng.randrange(len(wire)))]
                    + rng.choice(["", "\n", "0", '"', "\ud800"])
                    + wire[pos + 1 :]
                    for _ in range(10)
                ]:
                    out = []
                    for dec, reg, err in (
                        (dec1, old.registry(os), old.Error),
                        (dec2, new.registry(ns), new.Error),
                    ):
                        try:
                            out.append(json.dumps(dec(candidate, reg), sort_keys=True))
                        except err:
                            out.append("Error")
                    self.assertEqual(*out)

    def test_heldout_varying_schemas_parity(self):
        cases = json.loads((HERE.parent / "typed_rows/heldout-corpus.json").read_text())["cases"]
        for case in cases:
            fields = tuple((n, t, True) for n, t in case["fields"])
            ns = new.Schema("heldout." + case["family"] + ".v1", fields)
            os = old.Schema(ns.name, fields)
            for records in case["turns"]:
                for e1, e2, d1, d2 in (
                    (old.pack, new.pack, old.unpack, new.unpack),
                    (oldtyped.encode, typed.encode, oldtyped.decode, typed.decode),
                ):
                    a = e1(records, os, tuple(case["shared"]))
                    b = e2(records, ns, tuple(case["shared"]))
                    self.assertEqual(a, b)
                    self.assertEqual(
                        json.dumps(d1(a, old.registry(os)), sort_keys=True),
                        json.dumps(d2(b, new.registry(ns)), sort_keys=True),
                    )

    def test_lazy_bounded_cache_collectible(self):
        schema = new.Schema("bounded", tuple((f"f{i}", "any", True) for i in range(128)))
        self.assertEqual(set(schema.__dict__), {"name", "fields"})
        schema.fingerprint
        schema.check({f[0]: None for f in schema.fields})
        new.unpack(new.pack([], schema), new.registry(schema))
        self.assertIs(type(schema._field_name_set), frozenset)
        self.assertIs(type(schema._field_index_set), frozenset)
        self.assertEqual(len(schema._field_name_set), 128)
        self.assertEqual(len(schema._field_index_set), 128)
        reference = weakref.ref(schema)
        del schema
        gc.collect()
        self.assertIsNone(reference())

    def test_expansion_limits_and_detached_containers(self):
        os = old.Schema("x", (("v", "any", True),))
        ns = new.Schema("x", os.fields)
        for value in ([{"v": {"x": []}}] * 2, [{"v": "a" * 150000}] * 2):
            outcomes = []
            for mod, schema in ((old, os), (new, ns)):
                try:
                    wire = mod.pack(value, schema, ("v",))
                    out = mod.unpack(wire, mod.registry(schema))
                    if type(out[0]["v"]) is dict:
                        out[0]["v"]["x"].append(1)
                        self.assertEqual(out[1]["v"], {"x": []})
                    outcomes.append("accepted")
                except mod.Error:
                    outcomes.append("rejected")
            self.assertEqual(*outcomes)


if __name__ == "__main__":
    unittest.main()
