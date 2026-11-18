"""Matched schema-cache cold and hot CPU diagnostic; no inference claims."""

import argparse
import hashlib
import json
import platform
import random
import statistics
import time
from pathlib import Path
from test_cache import new, old, typed, oldtyped

HERE = Path(__file__).resolve().parent


def stats(values):
    return {
        "median_ms": statistics.median(values),
        "p95_ms": sorted(values)[int(0.95 * (len(values) - 1))],
    }


def run(repetitions=30):
    rng = random.Random(9124)
    hot = []
    cold = []
    corpus_raw = (HERE.parent / "typed_rows/heldout-corpus.json").read_bytes()
    corpus_sha256 = hashlib.sha256(corpus_raw).hexdigest()
    assert (
        corpus_sha256
        == (HERE.parent / "typed_rows/heldout-corpus.sha256").read_text(encoding="ascii").strip()
    )
    cases = json.loads(corpus_raw)["cases"]
    for case in cases:
        fields = tuple((n, t, True) for n, t in case["fields"])
        name = "heldout." + case["family"] + ".v1"
        ns = new.Schema(name, fields)
        os = old.Schema(name, fields)
        nr = new.registry(ns)
        orr = old.registry(os)
        records = case["turns"][0]
        jw = new.pack(records, ns, tuple(case["shared"]))
        tw = typed.encode(records, ns, tuple(case["shared"]))
        assert jw == old.pack(records, os, tuple(case["shared"])) and tw == oldtyped.encode(
            records, os, tuple(case["shared"])
        )
        arms = {
            "old_json": lambda: old.unpack(jw, orr),
            "new_json": lambda: new.unpack(jw, nr),
            "old_typed": lambda: oldtyped.decode(tw, orr),
            "new_typed": lambda: typed.decode(tw, nr),
        }
        canonical = json.dumps(records, sort_keys=True)
        times = {m: [] for m in arms}
        for fn in arms.values():
            for _ in range(3):
                assert json.dumps(fn(), sort_keys=True) == canonical
        for _ in range(repetitions):
            order = list(arms)
            rng.shuffle(order)
            for mode in order:
                start = time.perf_counter_ns()
                result = arms[mode]()
                elapsed = time.perf_counter_ns() - start
                assert json.dumps(result, sort_keys=True) == canonical
                times[mode].append(elapsed / 1e6)
        hot.append(
            {
                "family": case["family"],
                "rows": case["rows"],
                "shared": case["shared"],
                "timing": {m: stats(v) for m, v in times.items()},
            }
        )
    for count in (1, 4, 16, 128):
        fields = tuple((f"f{i}", "any", True) for i in range(count))
        records = [{f[0]: i for i, f in enumerate(fields)}]
        wire = old.pack(records, old.Schema("cold", fields))
        for workload in (
            "constructor",
            "constructor_first_fingerprint",
            "constructor_first_decode",
        ):

            def invoke(mod):
                schema = mod.Schema("cold", fields)
                if workload == "constructor":
                    return schema
                if workload == "constructor_first_fingerprint":
                    return schema.fingerprint
                return mod.unpack(wire, mod.registry(schema))

            times = {"old": [], "new": []}
            for _ in range(100):
                order = ["old", "new"]
                rng.shuffle(order)
                for mode in order:
                    start = time.perf_counter_ns()
                    result = invoke(old if mode == "old" else new)
                    elapsed = time.perf_counter_ns() - start
                    if workload == "constructor":
                        assert result.fields == fields
                    elif workload == "constructor_first_decode":
                        assert result == records
                    else:
                        assert result == old.Schema("cold", fields).fingerprint
                    times[mode].append(elapsed / 1e6)
            cold.append(
                {
                    "fields": count,
                    "workload": workload,
                    "timing": {m: stats(v) for m, v in times.items()},
                    "new_over_old": statistics.median(times["new"])
                    / statistics.median(times["old"]),
                }
            )
    return {
        "scope": "Local CPU diagnostic on frozen heldout first turns. Four arms use full separate old/new core and typed modules, including their own Schema. Hot: three warmups,30shuffled paired repetitions, complete decode entrypoints and exact checks outside timing. Cold:100shuffled paired constructions, separately first fingerprint and first JSON decode including registry construction. No generation/token/network/billing measurement. Fixed policy constants; immutable Schema normal API only.",
        "corpus_sha256": corpus_sha256,
        "baseline_commit": "665ed1b159c8f3eb4376f4cce1e880cd8665dcc6",
        "python": platform.python_version(),
        "os": platform.system(),
        "hot_repetitions": repetitions,
        "hot_cases": hot,
        "cold_cases": cold,
        "hot_median_case_new_over_old": {
            kind: statistics.median(
                r["timing"]["new_" + kind]["median_ms"] / r["timing"]["old_" + kind]["median_ms"]
                for r in hot
            )
            for kind in ("json", "typed")
        },
        "hot_median_case_new_typed_over_new_json": statistics.median(
            r["timing"]["new_typed"]["median_ms"] / r["timing"]["new_json"]["median_ms"]
            for r in hot
        ),
        "hot_sum_case_medians_ms": {
            m: sum(r["timing"][m]["median_ms"] for r in hot)
            for m in ("old_json", "new_json", "old_typed", "new_typed")
        },
        "p95_estimator": "Sorted sample at zero-based floor(0.95*(n-1)); no interpolation.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = run()
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf8")
    print(
        json.dumps(
            {k: v for k, v in result.items() if k not in ("hot_cases", "cold_cases")}, indent=2
        )
    )
    print(json.dumps(result["cold_cases"], indent=2))
