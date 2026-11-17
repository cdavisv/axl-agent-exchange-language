from test_axl3 import *

del Tests


class ReviewRegression(unittest.TestCase):
    def test_unshared_alias(self):
        s = Schema("alias", (("x", "object", True),))
        out = unpack(pack([{"x": {"a": []}}] * 2, s, ("x",)), registry(s))
        out[0]["x"]["a"].append(1)
        self.assertEqual(out[1]["x"]["a"], [])

    def test_decimal_reject(self):
        for text in ["1.2345678901234567890123456789", "1e-999", "-0"]:
            with self.assertRaises(Error):
                json_to_axl(text)

    def test_bound_roundtrip(self):
        for n in range(30, 35):
            text = "[" * n + "]" * n
            try:
                value = load(text)
            except Error:
                continue
            self.assertEqual(load(dump(value)), value)

    def test_expansion(self):
        s = Schema("wide", (("x", "string", True),))
        with self.assertRaises(Error):
            unpack(dump([3, s.fingerprint, {"0": "x" * 200000}, [[]] * 1024]), registry(s))

    def test_v2_order(self):
        wire = 'NT: to=@fixer; id=a\n  summary="hello"'
        out = export_v2(import_v2([wire]))
        self.assertEqual(len(out), 1)

    def test_v2_bytes(self):
        with self.assertRaises(Error):
            import_v2(['NT: id=a; to=@fixer\n  summary="' + "😀" * 3000 + '"'])

    def test_schema_types(self):
        for t in [[], {}, 1]:
            with self.assertRaises(Error):
                Schema("bad", (("x", t, True),))

    def test_registry_immutable(self):
        with self.assertRaises(TypeError):
            registry(JSON)["bad"] = JSON

    def test_raw_json_exact(self):
        text = ' { "x":1.2345678901234567890123456789, "y":1e-999, "z":-0 } '
        self.assertEqual(axl_to_json_text(json_text_to_axl(text)), text)

    def test_decimal_huge_exponent(self):
        with self.assertRaises(Error):
            load("1e-" + 60 * "9")

    def test_export_v2_bytes(self):
        wire = pack(
            [
                {
                    "prefix": "NT",
                    "fields": {"id": "a", "to": "@fixer"},
                    "payload": {"summary": "😀" * 3000},
                }
            ],
            V2,
        )
        with self.assertRaises(Error):
            export_v2(wire)

    def test_exact_expanded_limit(self):
        s = Schema("edge", (("x", "string", True), ("i", "integer", True)))
        records = [{"x": "a" * 131056, "i": 0}, {"x": "a" * 131056, "i": 10}]
        self.assertEqual(len(dump(records)), MAX_BYTES)
        self.assertEqual(unpack(pack(records, s, ("x",)), registry(s)), records)

    def test_v2_delta_pointer_utf8(self):
        from axl import build_axl_message

        for pointer_key in ("path", "from"):
            op = {"op": "move", "path": "/target", "from": "/source"}
            op[pointer_key] = "/" + "😀" * 300
            fields = {"id": "delta1", "mode": "delta", "ref": "upp:p"}
            payload = {"operations": [op]}
            raw = build_axl_message("SY", fields=fields, payload=payload, strict=True)
            with self.assertRaises(Error):
                import_v2([raw])
            wire = pack([{"prefix": "SY", "fields": fields, "payload": payload}], V2)
            with self.assertRaises(Error):
                export_v2(wire)

    def test_integer_runtime_limit(self):
        with self.assertRaises(Error):
            dump(10**5000)

    def test_v2_delta_operations_utf8(self):
        from axl import build_axl_message

        operations = [{"op": "set", "path": "/x", "value": "😀" * 17000}]
        for value in (operations, dump(operations)):
            fields = {"id": "delta1", "mode": "delta", "ref": "upp:p", "operations": value}
            raw = "SY: id=delta1; mode=delta; ref=upp:p; operations=" + json.dumps(
                dump(operations), ensure_ascii=False
            )
            with self.assertRaises(Error):
                import_v2([raw])
            wire = pack([{"prefix": "SY", "fields": fields, "payload": {}}], V2)
            with self.assertRaises(Error):
                export_v2(wire)
