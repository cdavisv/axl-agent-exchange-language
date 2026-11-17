"""Regression checks for shared-field API parity and v2 numeric strings."""

import itertools
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / "surface"), str(ROOT / "separators")]
import surface
import pipes
from axl3 import Error, Schema, V2, export_v2, pack, unpack, registry


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.schema = Schema(
            "revision.shared",
            (("kind", "string", True), ("note", "string", True), ("detail", "any", False)),
        )
        self.rows = [
            {"kind": "status", "note": "001", "detail": {"a": [1, True]}},
            {"kind": "result", "note": "001"},
        ]
        self.encoders = (pack, surface.encode, pipes.encode)
        self.decoders = (unpack, surface.decode, pipes.decode)

    def test_shared_iterables_have_identical_wire(self):
        for encode, decode in zip(self.encoders, self.decoders):
            expected = encode(self.rows, self.schema, ("note",))
            for shared in [["note"], ("note",), iter(["note"]), (n for n in ["note"])]:
                wire = encode(self.rows, self.schema, shared)
                self.assertEqual(wire, expected)
                self.assertEqual(decode(wire, registry(self.schema)), self.rows)

    def test_empty_iterator_matches_empty_tuple(self):
        for encode in self.encoders:
            self.assertEqual(
                encode(self.rows, self.schema, iter(())), encode(self.rows, self.schema, ())
            )

    def test_maximum_shared_fields(self):
        schema = Schema("full", tuple(("f" + str(i), "integer", True) for i in range(128)))
        row = {"f" + str(i): i for i in range(128)}
        self.assertEqual(unpack(pack([row], schema, iter(row)), registry(schema)), [row])
        # Surface reserves one of the 128 schema columns for the act.
        schema = Schema("surface.full", (("kind", "string", True),) + schema.fields[:127])
        row = {name: 1 for name, _, _ in schema.fields if name != "kind"}
        row["kind"] = "status"
        for encode, decode in [(surface.encode, surface.decode), (pipes.encode, pipes.decode)]:
            wire = encode([row], schema, (name for name in row if name != "kind"))
            self.assertEqual(decode(wire, registry(schema)), [row])

    def test_invalid_configuration_uses_protocol_error(self):
        for encode in self.encoders:
            for shared in [
                None,
                42,
                "note",
                b"note",
                (["note"],),
                ({"x": 1},),
                ("missing",),
                ("note", "note"),
            ]:
                with self.subTest(encoder=encode.__module__, shared=repr(shared)):
                    with self.assertRaises(Error):
                        encode(self.rows, self.schema, shared)

    def test_infinite_duplicate_iterable_stops(self):
        for encode in self.encoders:
            with self.assertRaises(Error):
                encode(self.rows, self.schema, itertools.repeat("note"))

    def test_surface_kind_cannot_be_shared(self):
        for encode in (surface.encode, pipes.encode):
            with self.assertRaises(Error):
                encode(self.rows[:1], self.schema, iter(["kind"]))

    def test_numeric_strings_native_and_guarded_v2_export(self):
        for value in ["001", "1.0", "-001", "-1.", "0", "-0", 'quote"', "²", "١"]:
            rows = [{"kind": "status", "note": value}]
            for encode, decode in zip(self.encoders, self.decoders):
                self.assertEqual(decode(encode(rows, self.schema), registry(self.schema)), rows)
            wrapped = pack(
                [{"prefix": "NT", "fields": {"ref": "t-1", "note": value}, "payload": {}}], V2
            )
            # Upstream v2 may reject unusual glyphs or corrupt strings; adapter must
            # either preserve exact string values or reject, never silently coerce.
            try:
                wires = export_v2(wrapped)
            except (Error, ValueError):
                continue
            from axl import parse_axl_message

            actual = parse_axl_message(wires[0], strict=True).fields["note"]
            self.assertIs(type(actual), str)
            self.assertEqual(actual, value)

    def test_seeded_native_string_roundtrip(self):
        rng = random.Random(20261117)
        for _ in range(1000):
            value = rng.choice(
                [
                    f"{rng.randint(-999, 999):05d}",
                    "".join(rng.choices('abc0123 \\;,:"[]{}()\n\t', k=rng.randrange(30))),
                ]
            )
            rows = [{"kind": "status", "note": value}]
            for encode, decode in zip(self.encoders, self.decoders):
                self.assertEqual(
                    decode(encode(rows, self.schema, iter(["note"])), registry(self.schema)), rows
                )


if __name__ == "__main__":
    unittest.main()
