"""Independent integrity checks for the frozen held-out diagnostic."""

import hashlib
import json
from pathlib import Path
import unittest
from heldout_corpus import build

HERE = Path(__file__).resolve().parent


class HeldoutIntegrityTests(unittest.TestCase):
    def test_generated_corpus_matches_frozen_bytes_and_hash(self):
        generated = (json.dumps(build(), ensure_ascii=True, separators=(",", ":")) + "\n").encode(
            "utf8"
        )
        frozen = (HERE / "heldout-corpus.json").read_bytes()
        self.assertEqual(generated, frozen)
        expected = (HERE / "heldout-corpus.sha256").read_text(encoding="ascii").strip()
        self.assertEqual(hashlib.sha256(frozen).hexdigest(), expected)
        results = json.loads((HERE / "heldout-results.json").read_text(encoding="utf8"))
        self.assertEqual(results["corpus_sha256"], expected)

    def test_recorded_summaries_independently_aggregate(self):
        results = json.loads((HERE / "heldout-results.json").read_text(encoding="utf8"))
        corpus = json.loads((HERE / "heldout-corpus.json").read_text(encoding="utf8"))
        observations = results["observations"]
        self.assertEqual(results["scenarios"], len(corpus["cases"]))
        self.assertEqual(len(observations), sum(len(case["turns"]) for case in corpus["cases"]))
        self.assertEqual(results["exact_typed_checks"], len(observations) * 3)
        expected_keys = {
            (case["family"], case["rows"], bool(case["shared"]), turn)
            for case in corpus["cases"]
            for turn in range(len(case["turns"]))
        }
        actual_keys = {
            (row["family"], row["rows"], row["shared"], row["turn"]) for row in observations
        }
        self.assertEqual(actual_keys, expected_keys)
        self.assertEqual(len(actual_keys), len(observations))
        for turns, strata in results["summary"].items():
            for family, formats in strata.items():
                chosen = [
                    row
                    for row in observations
                    if row["turn"] < int(turns) and (family == "all" or row["family"] == family)
                ]
                self.assertTrue(chosen)
                for mode, metrics in formats.items():
                    for metric, recorded in metrics.items():
                        with self.subTest(turns=turns, family=family, mode=mode, metric=metric):
                            independent = sum(row["costs"][mode][metric] for row in chosen)
                            self.assertEqual(recorded, independent)


if __name__ == "__main__":
    unittest.main()
