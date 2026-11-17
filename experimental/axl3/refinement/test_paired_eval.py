import unittest
from paired_eval import *


class EvaluatorTests(unittest.TestCase):
    def test_oracles(self):
        for task, _, expr in TASKS:
            for mode in ("v3", "equivalent_packed_json", "contract_json"):
                wire = (
                    dump([expected(task, expr)])
                    if mode == "contract_json"
                    else pack([expected(task, expr)], SCHEMA)
                )
                self.assertTrue(score({"task": task, "mode": mode, "text": wire})["success"])

    def test_no_execution(self):
        for expr in [
            '__import__("os").system("id")',
            "x**1000000000",
            "[x for x in range(3)]",
            "x.__class__",
            'open("x")',
        ]:
            with self.assertRaises(Error):
                expression(expr, 1, 2)

    def test_short_circuit(self):
        self.assertIs(expression("x==0 or 1//x>0", 0, 2), True)
        self.assertIs(expression("x!=0 and 1//x>0", 0, 2), False)
        self.assertEqual(expression("x or y", 3, 7), 3)
        self.assertEqual(expression("x or y", 0, 7), 7)
        self.assertEqual(expression("x and y", 3, 7), 7)
        self.assertEqual(expression("x and y", 0, 7), 0)

    def test_unreachable_syntax_rejected(self):
        for expr in [
            "1 if True else __import__('os').system('id')",
            'True or open("x")',
            "False and x.__class__",
            "0 if True else unknown",
            "1 if True else 1000000000000000",
        ]:
            with self.assertRaises(Error):
                expression(expr, 1, 2)

    def test_equivalent_prompts(self):
        p = prompts()
        for i in range(0, len(p), 3):
            self.assertEqual(p[i + 1]["prompt"], p[i + 2]["prompt"])

    def test_wrong_code(self):
        self.assertFalse(
            score({"task": "add", "mode": "v3", "text": pack([expected("add", "x-y")], SCHEMA)})[
                "success"
            ]
        )


if __name__ == "__main__":
    unittest.main()
