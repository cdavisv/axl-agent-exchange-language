import hashlib
import json
from pathlib import Path
import unittest
from corpus import build
from benchmark import schema_for, baseline_candidates, baseline_decode
from semantic import encode, decode
from axl3 import Error, dump, load

HERE = Path(__file__).resolve().parent


class StudyIntegrityTests(unittest.TestCase):
    def test_frozen_corpus_and_summary(self):
        raw = (json.dumps(build(), ensure_ascii=True, separators=(",", ":")) + "\n").encode()
        self.assertEqual(raw, (HERE / "corpus.json").read_bytes())
        self.assertEqual(
            hashlib.sha256(raw).hexdigest(), (HERE / "corpus.sha256").read_text().strip()
        )
        results = json.loads((HERE / "results-llama31.json").read_text())
        self.assertEqual(results["corpus_sha256"], hashlib.sha256(raw).hexdigest())
        for turns, groups in results["summary"].items():
            for group, modes in groups.items():
                rows = [
                    r
                    for r in results["observations"]
                    if r["turn"] < int(turns) and (r["split"] == group or r["family"] == group)
                ]
                for mode, metrics in modes.items():
                    for metric, value in metrics.items():
                        self.assertEqual(value, sum(r["costs"][mode][metric] for r in rows))
        for row in results["observations"]:
            self.assertEqual(row["costs"]["semantic"], row["costs"]["equivalent_transformed_json"])

    def test_baselines_same_domain_and_strict_identity(self):
        case = build()["cases"][0]
        schema = schema_for(case)
        records = case["turns"][0]
        for domain in (False, True):
            for wire in baseline_candidates(records, schema, domain):
                self.assertEqual(baseline_decode(wire, schema, domain), records)
            value = load(next(baseline_candidates(records, schema, domain)))
            value[0] = 3.0 if domain else 3
            with self.assertRaises(Error):
                baseline_decode(dump(value), schema, domain)
            with self.assertRaises(Error):
                list(baseline_candidates([{"status": "not-declared"}], schema, domain))
        self.assertEqual(decode(encode(records, schema), {schema.fingerprint: schema}), records)


if __name__ == "__main__":
    unittest.main()
