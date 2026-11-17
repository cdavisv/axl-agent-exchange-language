import itertools
import random
import unittest
from shared import plan_shared
from axl3 import Error, Schema, dump, pack, registry, unpack


class PlanningTests(unittest.TestCase):
    def test_exact_small_search(self):
        rng = random.Random(20261121)
        schema = Schema("plan", tuple(("f" + str(i), "any", True) for i in range(5)))
        for _ in range(100):
            row = {"f" + str(i): rng.choice([0, "001", "x" * 30, None]) for i in range(5)}
            rows = [row.copy() for _ in range(rng.randrange(1, 12))]
            plan = plan_shared(rows, schema)
            oracle = min(
                len(pack(rows, schema, subset).encode())
                for width in range(6)
                for subset in itertools.combinations(row, width)
            )
            self.assertEqual(plan.cost, oracle)
            self.assertEqual(unpack(plan.wire, registry(schema)), rows)
            self.assertTrue(plan.exhaustive)

    def test_types_and_optional_presence(self):
        schema = Schema("optional", (("a", "any", True), ("b", "any", False)))
        for rows in [
            [{"a": True}, {"a": 1}],
            [{"a": 1}, {"a": 1.0}],
            [{"a": 1}, {"a": 1, "b": None}],
        ]:
            plan = plan_shared(rows, schema)
            self.assertEqual(dump(unpack(plan.wire, registry(schema))), dump(rows))
            self.assertNotIn("b", plan.shared)

    def test_budget(self):
        schema = Schema("wide", tuple(("f" + str(i), "integer", True) for i in range(128)))
        rows = [{"f" + str(i): i for i in range(128)}] * 2
        plan = plan_shared(rows, schema, max_evaluations=7)
        self.assertLessEqual(plan.evaluations, 7)
        self.assertFalse(plan.exhaustive)
        self.assertLessEqual(
            plan.cost, min(len(pack(rows, schema, s).encode()) for s in [(), tuple(rows[0])])
        )

    def test_oversized_unshared_does_not_block_valid_shared(self):
        schema = Schema("near_limit", (("a", "string", True),))
        rows = [{"a": "x" * 131030}, {"a": "x" * 131030}]
        with self.assertRaises(Error):
            pack(rows, schema)
        plan = plan_shared(rows, schema)
        self.assertEqual(plan.shared, ("a",))
        self.assertEqual(unpack(plan.wire, registry(schema)), rows)

    def test_empty(self):
        schema = Schema("empty", (("a", "any", True),))
        plan = plan_shared([], schema)
        self.assertEqual(unpack(plan.wire, registry(schema)), [])
        self.assertEqual(plan.evaluations, 1)

    def test_invalid_inputs(self):
        schema = Schema("bad", (("a", "integer", True),))
        for budget in [True, 0, 1, 1025, 1.5]:
            with self.assertRaises(Error):
                plan_shared([], schema, max_evaluations=budget)
        for cost in [True, -1, None, "1", float("nan"), float("inf")]:
            with self.assertRaises(Error):
                plan_shared([{"a": 1}], schema, measure=lambda _, c=cost: c)
        with self.assertRaises(Error):
            plan_shared([{"a": "1"}], schema)

    def test_huge_cost_and_snapshot(self):
        schema = Schema("snapshot", (("a", "array", True),))
        rows = [{"a": [1]}]

        def measure(wire):
            rows[0]["a"].append(2)
            return 10**1000

        plan = plan_shared(rows, schema, measure=measure)
        self.assertEqual(unpack(plan.wire, registry(schema)), [{"a": [1]}])
        self.assertEqual(plan.cost, 10**1000)

    def test_equal_cost_prefers_unshared(self):
        schema = Schema("tie", (("a", "integer", True),))
        self.assertEqual(plan_shared([{"a": 1}], schema, measure=lambda _: 1).shared, ())


if __name__ == "__main__":
    unittest.main()
