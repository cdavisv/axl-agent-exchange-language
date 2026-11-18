"""Bounded local decoder CPU diagnostic, not model or network latency."""

import argparse
import hashlib
import json
import platform
import random
import statistics
import time
from pathlib import Path
from benchmark import FAMILIES, record
from typed_rows import encode, decode
from axl3 import Schema, pack, registry, unpack
from decoder_baseline import old_json, old_typed


def workloads(corpus):
    if corpus == "primary":
        schema = Schema(
            "typed.rows.study.v1",
            (
                ("kind", "string", True),
                ("id", "string", True),
                ("text", "string", True),
                ("value", "any", True),
            ),
        )
        for family in FAMILIES:
            for count in (1, 16, 64):
                for sharing in (False, True):
                    yield (
                        family,
                        count,
                        schema,
                        (("kind",) if sharing else ()),
                        [record(family, i) for i in range(count)],
                    )
    elif corpus == "heldout":
        here = Path(__file__).resolve().parent
        raw = (here / "heldout-corpus.json").read_bytes()
        assert (
            hashlib.sha256(raw).hexdigest() == (here / "heldout-corpus.sha256").read_text().strip()
        )
        for case in json.loads(raw)["cases"]:
            schema = Schema(
                "heldout." + case["family"] + ".v1",
                tuple((name, kind, True) for name, kind in case["fields"]),
            )
            yield case["family"], case["rows"], schema, tuple(case["shared"]), case["turns"][0]
    else:
        raise ValueError("Unknown corpus")


def run(repetitions=30, corpus="primary"):
    rng = random.Random(20261122)
    rows = []
    for family, count, schema, shared, expected in workloads(corpus):
        schemas = registry(schema)
        canon = json.dumps(expected, sort_keys=True)
        wires = {
            "typed_rows": encode(expected, schema, shared),
            "guarded_packed_json": pack(expected, schema, shared),
        }
        wires = {
            "old_typed": wires["typed_rows"],
            "new_typed": wires["typed_rows"],
            "old_json": wires["guarded_packed_json"],
            "new_json": wires["guarded_packed_json"],
        }
        receivers = {
            "old_typed": old_typed,
            "new_typed": decode,
            "old_json": old_json,
            "new_json": unpack,
        }
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
                **(
                    {"shared_kind": bool(shared)}
                    if corpus == "primary"
                    else {"shared_fields": list(shared)}
                ),
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
        "corpus": corpus,
        "scope": "Local implementation decode-only timing. Three warmups; shuffled mode order each repetition; correctness checked outside timing on every result. Synthetic data, no inference/network/I/O. Background machine load and interpreter affect values; no universal speed claim.",
        "optimization": "Both production formats use shared validated-envelope expansion. Typed retains dump for canonical-envelope byte/global bounds but skips reparse. Timings include full text entrypoint preprocessing, parsing, validation, expansion and detached copies. No wire/grammar/encoder change.",
        "baseline_commit": "f408c9024a108df7e6136798b013ab76a0e545c8",
        "median_case_new_over_old": {
            kind: statistics.median(
                row["timing_ms"]["new_" + kind]["median"]
                / row["timing_ms"]["old_" + kind]["median"]
                for row in rows
            )
            for kind in ("typed", "json")
        },
        "python": platform.python_version(),
        "os": platform.system(),
        "repetitions": repetitions,
        "p95_estimator": "Sorted sample at zero-based floor(0.95*(n-1)); not interpolated or nearest-rank.",
        "median_case_ratio_new_typed_over_new_json": statistics.median(
            row["timing_ms"]["new_typed"]["median"] / row["timing_ms"]["new_json"]["median"]
            for row in rows
        ),
        "sum_case_median_ms": {
            mode: sum(row["timing_ms"][mode]["median"] for row in rows)
            for mode in ("old_typed", "new_typed", "old_json", "new_json")
        },
        "cases": rows,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--corpus", choices=("primary", "heldout"), default="primary")
    args = parser.parse_args()
    result = run(corpus=args.corpus)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf8")
    print(json.dumps({key: value for key, value in result.items() if key != "cases"}, indent=2))
