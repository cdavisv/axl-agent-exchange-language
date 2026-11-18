"""Acceptance/value differential tests against pre-refactor decoder bodies."""

import json
import random
import unittest
from typed_rows import encode, decode
from axl3 import Error, Schema, dump, load, pack, registry, unpack, MAX_BYTES, MAX_DEPTH
from decoder_baseline import old_json, old_typed, old_pack, old_encode
from heldout_corpus import build


class EnvelopeDifferentialTests(unittest.TestCase):
    def setUp(self):
        self.schema = Schema("decoder.differential", (("s", "string", True), ("v", "any", True)))
        self.schemas = registry(self.schema)

    def equivalent(self, wire, old, new, schemas=None):
        outcomes = []
        for fn in (old, new):
            try:
                value = fn(wire, schemas or self.schemas)
                outcomes.append(("accepted", json.dumps(value, ensure_ascii=True, sort_keys=True)))
            except Error:
                outcomes.append(("rejected", None))
        self.assertEqual(*outcomes)
        return outcomes[0][0]

    def test_generated_values_and_detachment(self):
        rng = random.Random(82341)
        values = [
            None,
            True,
            False,
            0,
            -1,
            1.0,
            -0.0,
            1e-200,
            1e200,
            [],
            {},
            [1, "1", False],
            {"x": "\x00\U0001f680"},
        ]
        for i in range(250):
            records = [
                {"s": str(rng.randrange(20)) + "\t\n\\\x00", "v": rng.choice(values)}
                for _ in range(rng.randrange(1, 9))
            ]
            for encoder, old, new in ((pack, old_json, unpack), (encode, old_typed, decode)):
                wire = encoder(records, self.schema)
                self.assertEqual(self.equivalent(wire, old, new), "accepted")
        records = [{"s": "same", "v": {"a": [1]}} for _ in range(2)]
        for encoder, old, new in ((pack, old_json, unpack), (encode, old_typed, decode)):
            wire = encoder(records, self.schema, ("s", "v"))
            self.equivalent(wire, old, new)
            result = new(wire, self.schemas)
            result[0]["v"]["a"].append(2)
            self.assertEqual(result[1]["v"], {"a": [1]})

    def test_numeric_duplicate_and_envelope_guards(self):
        fingerprint = self.schema.fingerprint
        literals = [
            "-0",
            "-0.0",
            "0.10000000000000001",
            "1e9999",
            "1e-9999",
            "NaN",
            "Infinity",
            '{"x":1,"x":2}',
            "1.25",
            "true",
            "null",
        ]
        for literal in literals:
            jw = '[3,"' + fingerprint + '",{},[["s",' + literal + "]]]"
            tw = "@axl3t " + fingerprint + "\n={}\n>s\t" + literal
            self.equivalent(jw, old_json, unpack)
            self.equivalent(tw, old_typed, decode)
        for envelope in (
            [True, fingerprint, {}, []],
            [3, fingerprint, {"00": "x"}, []],
            [3, fingerprint, {"0": 1}, []],
            [3, fingerprint, {}, [["s"]]],
            [3, fingerprint, {}, ["s"]],
            [3, "bad", {}, []],
        ):
            self.equivalent(json.dumps(envelope), old_json, unpack)
        self.equivalent("@axl3t " + fingerprint + '\n={"0":"a","0":"b"}', old_typed, decode)

    def test_resource_edges(self):
        schema = Schema("resource", (("v", "any", True),))
        schemas = registry(schema)
        for depth in range(MAX_DEPTH - 5, MAX_DEPTH + 3):
            value = 0
            for _ in range(depth):
                value = [value]
            envelope = [3, schema.fingerprint, {}, [[value]]]
            jw = json.dumps(envelope, separators=(",", ":"))
            tw = (
                "@axl3t "
                + schema.fingerprint
                + "\n={}\n>"
                + json.dumps(value, separators=(",", ":"))
            )
            self.equivalent(jw, old_json, unpack, schemas)
            self.equivalent(tw, old_typed, decode, schemas)
        for size in (32750, 32760, 32767, 32768, 32769):
            value = [None] * size
            self.equivalent(
                json.dumps([3, schema.fingerprint, {}, [[value]]]), old_json, unpack, schemas
            )
            self.equivalent(
                "@axl3t " + schema.fingerprint + "\n={}\n>" + json.dumps(value),
                old_typed,
                decode,
                schemas,
            )
        for count in (1024, 1025):
            self.equivalent(
                json.dumps([3, schema.fingerprint, {}, [[0]] * count]), old_json, unpack, schemas
            )
            self.equivalent(
                "@axl3t " + schema.fingerprint + "\n={}" + ("\n>0" * count),
                old_typed,
                decode,
                schemas,
            )
        for size in (MAX_BYTES - 100, MAX_BYTES - 80, MAX_BYTES, MAX_BYTES + 1):
            value = "x" * size
            self.equivalent(
                json.dumps([3, schema.fingerprint, {}, [[value]]]), old_json, unpack, schemas
            )
            self.equivalent(
                "@axl3t " + schema.fingerprint + "\n={}\n>" + json.dumps(value),
                old_typed,
                decode,
                schemas,
            )
        self.equivalent(
            "@axl3t " + schema.fingerprint + '\n={"0":' + json.dumps("x" * 150000) + "}\n>\n>",
            old_typed,
            decode,
            schemas,
        )

    def test_seeded_wire_mutations(self):
        rng = random.Random(7138)
        records = [{"s": 'quote"\n\t\\', "v": {"nested": [1, True, None, -0.0]}}]
        for encoder, old, new in ((pack, old_json, unpack), (encode, old_typed, decode)):
            wire = encoder(records, self.schema)
            for _ in range(1500):
                pos = rng.randrange(len(wire))
                replacement = rng.choice(
                    ["", "0", "\n", "\r", "\t", "\\", '"', "\x00", "\ud800", "{}", "[]", "a"]
                )
                changed = wire[:pos] + replacement + wire[pos + 1 :]
                self.equivalent(changed, old, new)

    def test_frozen_corpus_encoder_and_decoder_parity(self):
        for case in build()["cases"]:
            schema = Schema(
                "heldout." + case["family"] + ".v1",
                tuple((name, kind, True) for name, kind in case["fields"]),
            )
            schemas = registry(schema)
            for records in case["turns"]:
                for oldenc, newenc, olddec, newdec in (
                    (old_pack, pack, old_json, unpack),
                    (old_encode, encode, old_typed, decode),
                ):
                    before = oldenc(records, schema, tuple(case["shared"]))
                    self.assertEqual(before, newenc(records, schema, tuple(case["shared"])))
                    self.assertEqual(self.equivalent(before, olddec, newdec, schemas), "accepted")

    def test_dump_implies_load_nesting_for_generated_envelopes(self):
        # validate_value rejects a container at depth >=32, while load's scan
        # allows at most32 open containers. Every dump-accepted envelope is
        # therefore within load's nesting bound, including empty containers.
        for empty in ([], {}):
            for depth in range(MAX_DEPTH + 2):
                value = empty
                for _ in range(depth):
                    value = [value]
                envelope = [3, self.schema.fingerprint, {}, [["s", value]]]
                try:
                    wire = dump(envelope)
                except Error:
                    continue
                self.assertEqual(json.dumps(load(wire)), json.dumps(envelope))


if __name__ == "__main__":
    unittest.main()
