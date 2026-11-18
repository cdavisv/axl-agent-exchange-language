"""Bounded local decoder CPU diagnostic, not model or network latency."""

import argparse
import json
import platform
import random
import statistics
import time
from pathlib import Path
from benchmark import FAMILIES, record
from typed_rows import encode, decode
from axl3 import Schema, pack, registry, unpack


def run(repetitions=30):
    schema = Schema(
        "typed.rows.study.v1",
        (
            ("kind", "string", True),
            ("id", "string", True),
            ("text", "string", True),
            ("value", "any", True),
        ),
    )
    schemas = registry(schema)
    rng = random.Random(20261122)
    rows = []
    for family in FAMILIES:
        for count in (1, 16, 64):
            for sharing in (False, True):
                expected = [record(family, i) for i in range(count)]
                canon = json.dumps(expected, sort_keys=True)
                shared = ("kind",) if sharing else ()
                wires = {
                    "typed_rows": encode(expected, schema, shared),
                    "guarded_packed_json": pack(expected, schema, shared),
                }
                receivers = {"typed_rows": decode, "guarded_packed_json": unpack}
                times = {mode: [] for mode in receivers}
                for mode, receiver in receivers.items():
                    for _ in range(3):
                        assert json.dumps(receiver(wires[mode], schemas), sort_keys=True) == canon
                for _ in range(repetitions):
                    order = list(receivers)
                    rng.shuffle(order)
                    for mode in order:
                        start = time.perf_counter_ns()
                        actual = receivers[mode](wires[mode], schemas)
                        elapsed = time.perf_counter_ns() - start
                        assert json.dumps(actual, sort_keys=True) == canon
                        times[mode].append(elapsed / 1e6)
                rows.append(
                    {
                        "family": family,
                        "rows": count,
                        "shared_kind": sharing,
                        "timing_ms": {
                            mode: {
                                "median": statistics.median(values),
                                "p95": sorted(values)[int(0.95 * (len(values) - 1))],
                            }
                            for mode, values in times.items()
                        },
                    }
                )
    return {
        "scope": "Local implementation decode-only timing. Three warmups; shuffled mode order each repetition; correctness checked outside timing on every result. Synthetic data, no inference/network/I/O. Background machine load and interpreter affect values; no universal speed claim.",
        "python": platform.python_version(),
        "os": platform.system(),
        "repetitions": repetitions,
        "p95_estimator": "Sorted sample at zero-based floor(0.95*(n-1)); not interpolated or nearest-rank.",
        "median_case_ratio_typed_over_json": statistics.median(
            row["timing_ms"]["typed_rows"]["median"]
            / row["timing_ms"]["guarded_packed_json"]["median"]
            for row in rows
        ),
        "sum_case_median_ms": {
            mode: sum(row["timing_ms"][mode]["median"] for row in rows)
            for mode in ("typed_rows", "guarded_packed_json")
        },
        "cases": rows,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf8")
    print(json.dumps({key: value for key, value in result.items() if key != "cases"}, indent=2))
