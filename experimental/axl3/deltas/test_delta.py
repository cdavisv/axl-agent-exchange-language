import unittest, random
from delta import *


class DeltaTests(unittest.TestCase):
    def test_types_paths_and_arrays(self):
        a = {"a/b": {"~key": None}, "list": [1], "bool": True, "gone": 1}
        b = {"a/b": {"~key": False}, "list": [1, 2, None], "bool": 1, "new": None}
        f = frame(a, b, 2, 3)
        self.assertEqual(canonical(apply(a, 2, parse_axl(emit_axl(f)))[0]), canonical(b))
        self.assertEqual(a["gone"], 1)

    def test_stale_target_atomic(self):
        a = {"x": [1]}
        f = frame(a, {"x": [1, 2]}, 0, 1)
        with self.assertRaisesRegex(Error, "STALE_BASE"):
            apply({"x": [9]}, 0, f)
        with self.assertRaisesRegex(Error, "STALE_BASE"):
            apply(a, 1, f)
        bad = load(dump(f))
        bad[4] = "0" * 64
        with self.assertRaisesRegex(Error, "TARGET_MISMATCH"):
            apply(a, 0, bad)
        self.assertEqual(a, {"x": [1]})

    def test_missing_unset(self):
        f = frame({}, {}, 0, 1)
        f[5] = [["unset", ["missing"]]]
        with self.assertRaisesRegex(Error, "Missing unset"):
            apply({}, 0, f)

    def test_duplicate_apply(self):
        a = {"x": 0}
        f = frame(a, {"x": 1}, 0, 1)
        b, r = apply(a, 0, f)
        with self.assertRaisesRegex(Error, "STALE_BASE"):
            apply(b, r, f)

    def test_limits(self):
        with self.assertRaises(Error):
            parse_axl("\ud800")
        with self.assertRaises(Error):
            frame(None, "x" * 262140, 0, 1)
        with self.assertRaises(Error):
            frame(None, 1, 2**53 - 1, 2**53)

    def test_parse_no_path_growth(self):
        import sys

        wire = emit_axl(frame({"a": 1}, {"a": 2}, 0, 1))
        n = len(sys.path)
        for _ in range(100):
            parse_axl(wire)
        self.assertEqual(len(sys.path), n)

    def test_random_mutations(self):
        rng = random.Random(57)
        for _ in range(1000):
            a = {str(i): rng.choice([None, True, 1, "|", [1], {"x": None}]) for i in range(8)}
            b = load(dump(a))
            b[str(rng.randrange(8))] = rng.choice([None, False, 1.0, [1, 2], {"x": False}])
            b.pop(str(rng.randrange(8)), None)
            f = frame(a, b, 0, 1)
            self.assertEqual(canonical(apply(a, 0, parse_axl(emit_axl(f)))[0]), canonical(b))


if __name__ == "__main__":
    unittest.main()
