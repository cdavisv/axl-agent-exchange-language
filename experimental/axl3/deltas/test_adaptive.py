import unittest, random, copy, math
from adaptive import *


class AdaptiveTests(unittest.TestCase):
    def test_all_modes_preserve_state_and_revision(self):
        for a, b, r, n in [
            ({"x": 1}, {"x": 2}, 0, 1),
            ({"x": [1]}, {"x": [1, 2]}, 4, 5),
            ({"x": None}, {"x": None}, 7, 7),
        ]:
            saved = copy.deepcopy(a)
            for wire in candidates(a, b, r, n).values():
                actual, new = receive(a, r, wire)
                self.assertTrue(equal(actual, b))
                self.assertEqual(new, n)
                self.assertEqual(a, saved)

    def test_noop_and_small_snapshot(self):
        self.assertEqual(select({"x": 1}, {"x": 1}, 0, 0).mode, "unchanged")
        self.assertEqual(select({"x": 1}, {"x": 2}, 0, 1).mode, "snapshot")

    def test_sparse_large_delta(self):
        a = {str(i): "z" * 200 for i in range(100)}
        b = {**a, "0": "changed"}
        self.assertIn(select(a, b, 0, 1).mode, ("delta", "opcodes"))

    def test_costs_and_ties(self):
        a = {"x": 1}
        b = {"x": 2}
        self.assertEqual(select(a, b, 0, 1, measure=lambda _: 1).mode, "snapshot")
        for bad in [-1, float("inf"), float("nan"), True, "1", None]:
            with self.assertRaises(Error):
                select(a, b, 0, 1, measure=lambda _, bad=bad: bad)

    def test_stale_all_modes(self):
        a = {"x": 1}
        for wire in candidates(a, a, 1, 1).values():
            for before, rev in [({"x": 2}, 1), (a, 0), (a, True)]:
                with self.assertRaises(Error):
                    receive(before, rev, wire)

    def test_receipt_shapes(self):
        for obj in [
            ["unchanged", [True, 1, sha({})]],
            ["unchanged", [3, True, sha({})]],
            ["unchanged", [3, 1, "x"]],
            ["bad", []],
            {},
            ["snapshot"],
        ]:
            with self.assertRaises(Error):
                receive({}, 1, dump(obj))

    def test_target_tampering_atomic(self):
        a = {"x": [1]}
        saved = copy.deepcopy(a)
        for mode, wire in candidates(a, {"x": [2]}, 1, 2).items():
            obj = load(wire)
            obj[1][4] = "0" * 64
            with self.assertRaises(Error):
                receive(a, 1, dump(obj))
            self.assertEqual(a, saved)

    def test_output_aliases_detached(self):
        a = {"x": [1]}
        for wire in candidates(a, a, 0, 0).values():
            b, _ = receive(a, 0, wire)
            b["x"].append(2)
            self.assertEqual(a, {"x": [1]})

    def test_large_cost_integer(self):
        self.assertEqual(select({}, {}, 0, 0, measure=lambda _: 10**1000).cost, 10**1000)

    def test_near_limit_snapshot_not_required(self):
        a = {"x": "z" * 262000}
        self.assertEqual(select(a, a, 0, 0).mode, "unchanged")
        b = {**a, "v": 1}
        chosen = select(a, b, 0, 1)
        self.assertNotEqual(chosen.mode, "snapshot")
        self.assertTrue(equal(receive(a, 0, chosen.wire)[0], b))

    def test_deep_delta_not_required(self):
        b = 1
        for _ in range(30):
            b = {"x": b}
        chosen = select({}, b, 0, 1)
        self.assertEqual(chosen.mode, "snapshot")
        self.assertTrue(equal(receive({}, 0, chosen.wire)[0], b))

    def test_invalid_revisions_still_reject(self):
        for old, new in [(True, 1), (0, True), (0, 2), (0, 0), (-1, 0)]:
            with self.assertRaises(Error):
                select({}, {"x": 1}, old, new)

    def test_generated_minimum_and_equivalence(self):
        rng = random.Random(17112026)
        for i in range(500):
            a = {
                str(j): rng.choice([None, True, False, j, str(j), [j]])
                for j in range(rng.randrange(20))
            }
            b = copy.deepcopy(a)
            if b and i % 3:
                b[rng.choice(list(b))] = rng.randrange(100)
            n = 0 if equal(a, b) else 1
            chosen = select(a, b, 0, n)
            self.assertEqual(chosen.cost, min(dict(chosen.candidate_costs).values()))
            actual, rev = receive(a, 0, chosen.wire)
            self.assertTrue(equal(actual, b))
            self.assertEqual(rev, n)


if __name__ == "__main__":
    unittest.main()
