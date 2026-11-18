import json
import random
import unittest
from typed_rows import *
from axl3 import Schema, registry


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True)


class TypedRowTests(unittest.TestCase):
    def setUp(self):
        self.schema = Schema("typed.test", (("text", "string", True), ("value", "any", True)))

    def test_strings_keep_exact_type(self):
        for text in [
            "001",
            "1.0",
            "true",
            "null",
            "",
            'quote"',
            "\\n",
            "a\tb",
            "a\nb",
            "\r",
            "\x00",
            "\U0001f600\u6f22\u5b57",
            "\u00b2",
            "\u0661",
            ">",
            "={}",
        ]:
            rows = [{"text": text, "value": [True, 1, 1.0, "1"]}]
            self.assertEqual(
                canonical(decode(encode(rows, self.schema), registry(self.schema))), canonical(rows)
            )

    def test_empty_batch_all_shared_and_empty_strings(self):
        for rows, shared in [
            ([], ()),
            ([{"text": "", "value": None}], ("text", "value")),
            ([{"text": "", "value": 1}], ("value",)),
        ]:
            self.assertEqual(
                canonical(decode(encode(rows, self.schema, shared), registry(self.schema))),
                canonical(rows),
            )

    def test_generated_roundtrip(self):
        rng = random.Random(20261122)
        for _ in range(1000):
            rows = [
                {
                    "text": "".join(
                        rng.choices('abc012 \\t\n\t\r\x00"{}[]\U0001f600', k=rng.randrange(40))
                    ),
                    "value": rng.choice([None, True, 1, 1.0, [1, "1"], {"x": False}]),
                }
                for _ in range(rng.randrange(1, 8))
            ]
            self.assertEqual(
                canonical(decode(encode(rows, self.schema), registry(self.schema))), canonical(rows)
            )

    def test_unknown_escape_and_controls_rejected(self):
        wire = encode([{"text": "ok", "value": 1}], self.schema)
        for text in ["\\q", "\\", "\\x", "\\x0", "\\xzz", "\\x20", "\r", "\x01"]:
            with self.assertRaises(Error):
                decode(wire.replace(">ok\t", ">" + text + "\t"), registry(self.schema))

    def test_malformed_envelopes(self):
        wire = encode([{"text": "ok", "value": 1}], self.schema)
        for bad in [
            wire + "\n\n",
            wire.replace(">ok\t1", ">ok"),
            wire.replace(">ok\t1", ">ok\t1\textra"),
            wire.replace("={}", '={"0":"a","0":"b"}'),
            wire.replace("={}", '={"9":1}'),
            wire.replace("@axl3t", "@axl3x"),
            wire.replace(">ok\t1", ">ok\tNaN"),
        ]:
            with self.assertRaises(Error):
                decode(bad, registry(self.schema))

    def test_line_framing_without_cell_trimming(self):
        schema = Schema("framing", (("a", "string", True), ("b", "string", True)))
        for rows, shared in [
            ([], ()),
            ([{"a": " leading ", "b": ""}], ()),
            ([{"a": "x", "b": ""}], ("a", "b")),
        ]:
            wire = encode(rows, schema, shared)
            for ending in ["", "\n"]:
                self.assertEqual(decode(wire + ending, registry(schema)), rows)
                self.assertEqual(
                    decode((wire + ending).replace("\n", "\r\n"), registry(schema)), rows
                )
            with self.assertRaises(Error):
                decode(wire + "\n\n", registry(schema))
        wire = encode([{"a": "a", "b": ""}], schema)
        self.assertTrue(wire.endswith("\t"))
        self.assertEqual(decode(wire + "\n", registry(schema))[0]["b"], "")

    def test_optional_and_type_guards(self):
        optional = Schema("optional", (("x", "string", False),))
        with self.assertRaises(Error):
            encode([], optional)
        with self.assertRaises(Error):
            decode("@axl3t " + optional.fingerprint + "\n={}", registry(optional))
        with self.assertRaises(Error):
            encode([{"text": 1, "value": None}], self.schema)
        with self.assertRaises(Error):
            decode(encode([], self.schema), registry())

    def test_resource_bounds_and_unicode(self):
        with self.assertRaises(Error):
            decode("x" * (MAX_BYTES + 1), registry(self.schema))
        with self.assertRaises(Error):
            decode("\ud800", registry(self.schema))
        with self.assertRaises(Error):
            encode([{"text": "x", "value": 1}] * (MAX_ROWS + 1), self.schema)

    def test_expanded_and_nested_bounds_reject(self):
        schema = Schema("expanded", (("text", "string", True),))
        wire = "@axl3t " + schema.fingerprint + "\n=" + dump({"0": "x" * 150000}) + "\n>\n>"
        with self.assertRaises(Error):
            decode(wire, registry(schema))
        value = 1
        for _ in range(40):
            value = [value]
        with self.assertRaises(Error):
            encode([{"text": "x", "value": value}], self.schema)

    def test_shared_containers_detached(self):
        rows = [{"text": "a", "value": [1]}, {"text": "b", "value": [1]}]
        actual = decode(encode(rows, self.schema, ("value",)), registry(self.schema))
        actual[0]["value"].append(2)
        self.assertEqual(actual[1]["value"], [1])


if __name__ == "__main__":
    unittest.main()
