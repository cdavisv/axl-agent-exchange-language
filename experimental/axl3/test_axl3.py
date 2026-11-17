import json, random, sys, unittest
from axl3 import *


class Tests(unittest.TestCase):
    def test_json(self):
        for v in [
            None,
            True,
            False,
            0,
            -5,
            1.0,
            -0.0,
            10**100,
            "😀\n\x00é",
            [],
            {},
            [1, {"x": [None, False]}],
            {"a": 1, "b": 2},
        ]:
            s = dump(v)
            self.assertEqual(axl_to_json(json_to_axl(s)), s)

    def test_generated(self):
        rng = random.Random(41)

        def gen(n):
            if n == 0:
                return rng.choice([None, True, False, 0, -3, 1.2, '😀"\\\n'])
            return rng.choice(
                [
                    lambda: [gen(n - 1) for _ in range(3)],
                    lambda: {str(i): gen(n - 1) for i in range(3)},
                    lambda: gen(0),
                ]
            )()

        for _ in range(200):
            s = dump(gen(4))
            self.assertEqual(axl_to_json(json_to_axl(s)), s)

    def test_optional(self):
        s = Schema("x", (("id", "integer", True), ("x", "any", False), ("y", "any", False)))
        records = [
            {"id": 1},
            {"id": 1, "x": None},
            {"id": 1, "y": False},
            {"id": 1, "x": [], "y": {}},
        ]
        self.assertEqual(unpack(pack(records, s, ("id",)), registry(s)), records)

    def test_schema(self):
        for f in [
            (("a", "string", True), ("a", "integer", True)),
            (("a", "bad", True),),
            (("a", "string", 1),),
        ]:
            with self.assertRaises(Error):
                Schema("bad", f)

    def test_reject_json(self):
        for s in [
            '{"x":1,"x":2}',
            "NaN",
            "Infinity",
            "1e999",
            '"\\ud800"',
            "[" * 33 + "0" + "]" * 33,
            "[1,]",
        ]:
            with self.assertRaises(Error):
                load(s)

    def test_byte_limit(self):
        with self.assertRaises(Error):
            load('"' + "😀" * 70000 + '"')
        with self.assertRaises(Error):
            dump("😀" * 70000)

    def test_envelopes(self):
        s = Schema("x", (("a", "integer", True),))
        r = registry(s)
        for wire in [
            [True, s.fingerprint, {}, []],
            [4, s.fingerprint, {}, []],
            [3, "missing", {}, []],
            [3, s.fingerprint, {"01": 2}, []],
            [3, s.fingerprint, {}, [[True]]],
            [3, s.fingerprint, {}, [[1, 2]]],
            [3, s.fingerprint, {"0": True}, []],
        ]:
            with self.assertRaises(Error):
                unpack(dump(wire), r)

    def test_presence(self):
        s = Schema("x", (("a", "any", False),))
        r = registry(s)
        for row in [[], [""], ["2"], ["1"], ["0", None]]:
            with self.assertRaises(Error):
                unpack(dump([3, s.fingerprint, {}, [row]]), r)

    def test_shared(self):
        s = Schema("x", (("a", "any", True),))
        for rows in [[{"a": True}, {"a": 1}], [{"a": 1}, {"a": 1.0}], []]:
            with self.assertRaises(Error):
                pack(rows, s, ("a",))

    def test_unknown_missing(self):
        s = Schema("x", (("a", "integer", True),))
        for row in [{}, {"a": True}, {"a": 1, "b": 2}]:
            with self.assertRaises(Error):
                pack([row], s)

    def test_v2(self):
        wires = ['NT: id=e1; to=@fixer\n  summary="hello"', "ST: ref=t-qa; st=run; pct=50"]
        v = import_v2(wires)
        self.assertEqual(import_v2(export_v2(v)), v)

    def test_transport(self):
        m = {
            "id": "m1",
            "task": "t1",
            "sender": "worker",
            "to": "manager",
            "kind": "result",
            "seq": 0,
            "body": {"command": "do NOT execute"},
            "reply": "request1",
        }
        w = pack([m], MESSAGE, ("task", "sender", "to"))
        out, ids = accept_messages(
            w, authenticated_peer="worker", local_recipient="manager", task="t1", seen=set()
        )
        self.assertEqual(out, [m])
        self.assertEqual(ids, {"m1"})
        for peer, to, task, seen in [
            ("attacker", "manager", "t1", set()),
            ("worker", "other", "t1", set()),
            ("worker", "manager", "t2", set()),
            ("worker", "manager", "t1", {"m1"}),
        ]:
            with self.assertRaises(Error):
                accept_messages(
                    w, authenticated_peer=peer, local_recipient=to, task=task, seen=seen
                )
        with self.assertRaises(Error):
            accept_messages(
                pack([m, m], MESSAGE),
                authenticated_peer="worker",
                local_recipient="manager",
                task="t1",
                seen=set(),
            )

    def test_counts(self):
        with self.assertRaises(Error):
            pack([{"value": 0}] * 1025, JSON)
        with self.assertRaises(Error):
            dump([0] * 32769)


if __name__ == "__main__":
    unittest.main()
