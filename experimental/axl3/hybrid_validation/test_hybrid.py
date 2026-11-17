import hashlib
import random
import tracemalloc
import unittest
from pathlib import Path
import axl3
import baseline_axl3 as old


def outcome(fn, value):
    try:
        return ("ok", fn(value))
    except Exception as exc:
        return (type(exc).__name__, str(exc))


class HybridTests(unittest.TestCase):
    def assert_same(self, value):
        self.assertEqual(outcome(old.validate_value, value), outcome(axl3.validate_value, value))

    def test_success_return_and_types(self):
        for value in [None, True, 1, 1.25, "", [], {}, [1, {"x": 2}], object(), (1,), {1: 2}]:
            self.assert_same(value)
        self.assertIsNone(axl3.validate_value({"x": list(range(5000))}))

    def test_thresholds_and_error_order(self):
        for n in [2047, 2048, 2049, 4095, 4096, 4097, 32766, 32767, 32768, 32769]:
            for mode in ["list", "dict"]:
                for pos in [0, n // 2, n - 1]:
                    v = [0] * n if mode == "list" else {str(i): 0 for i in range(n)}
                    v[pos if mode == "list" else str(pos)] = object()
                    for outer in [v, [object(), v], [v, object()], {"first": object(), "wide": v}]:
                        self.assert_same(outer)

    def test_depth_cycle_and_nested_resume(self):
        for depth in [0, 1, 30, 31, 32, 33]:
            v = [0] * 5000
            for _ in range(depth):
                v = [v]
            self.assert_same(v)
        v = []
        v.append(v)
        self.assert_same(v)
        for position in [0, 100, 4096]:
            v = [0] * 4097
            v[position] = [1] * 5000
            self.assert_same([v, {"x": v}, False])

    def test_large_auxiliary_allocation(self):
        value = [0] * 200000
        tracemalloc.start()
        try:
            self.assertEqual(outcome(axl3.validate_value, value), ("Error", "JSON resource limit"))
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 1024 * 1024)

    def test_generated_differential(self):
        rng = random.Random(34015)

        def gen(depth=0):
            if depth > 4 or rng.random() < 0.6:
                return rng.choice([None, True, 42, "hello", 1.25, float("inf"), "\ud800", object()])
            if rng.random() < 0.5:
                return [gen(depth + 1) for _ in range(rng.randrange(8))]
            return {str(i): gen(depth + 1) for i in range(rng.randrange(8))}

        for _ in range(1000):
            self.assert_same(gen())

    def test_baseline_pin(self):
        import json

        baseline = Path(__file__).with_name("baseline_axl3.py").read_bytes()
        pin = json.loads(Path(__file__).with_name("provenance.json").read_text())
        self.assertEqual(hashlib.sha256(baseline).hexdigest(), pin["baseline_sha256"])


if __name__ == "__main__":
    unittest.main()
