"""Reproducible synthetic adaptive handoff comparison; never calls a model."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "deltas"))
from adaptive import candidates, receive, select
from delta import equal


def run(tokenizer_path=None):
    tokenizer = None
    if tokenizer_path:
        from tokenizers import Tokenizer

        tokenizer = Tokenizer.from_file(str(tokenizer_path))

    def cost(wire):
        return (
            len(tokenizer.encode(wire, add_special_tokens=False).ids)
            if tokenizer
            else len(wire.encode("utf-8"))
        )

    rows = []
    for fields in (4, 16, 64, 128):
        for length in (8, 64, 256):
            for fraction in (0, 0.0625, 0.25, 0.5, 1):
                before = {
                    f"field{i}": ("old value " + str(i) + " ")[:length].ljust(length, "x")
                    for i in range(fields)
                }
                after = dict(before)
                changed = 0 if fraction == 0 else max(1, int(fields * fraction))
                for i in range(changed):
                    after[f"field{i}"] = ("new value " + str(i) + " ")[:length].ljust(length, "y")
                revision = int(changed > 0)
                wires = candidates(before, after, 0, revision)
                costs = {mode: cost(wire) for mode, wire in wires.items()}
                choice = select(before, after, 0, revision)
                for wire in wires.values():
                    result, actual_revision = receive(before, 0, wire)
                    assert equal(result, after) and actual_revision == revision
                rows.append(
                    {
                        "fields": fields,
                        "length": length,
                        "change_fraction": fraction,
                        "costs": costs,
                        "byte_selected_mode": choice.mode,
                        "byte_selected_cost": costs[choice.mode],
                        "minimum_cost": min(costs.values()),
                    }
                )
    summary = {"cases": len(rows)}
    for mode in ("snapshot", "delta", "opcodes"):
        summary[mode] = sum(row["costs"][mode] for row in rows)
        summary[mode + "_with_receipts"] = sum(
            min(row["costs"][mode], row["costs"].get("unchanged", float("inf"))) for row in rows
        )
    summary["byte_selected"] = sum(row["byte_selected_cost"] for row in rows)
    summary["minimum"] = sum(row["minimum_cost"] for row in rows)
    return {
        "unit": "tokenizer_tokens" if tokenizer else "utf8_bytes",
        "tokenizer_sha256": hashlib.sha256(Path(tokenizer_path).read_bytes()).hexdigest()
        if tokenizer
        else None,
        "scope": "60 synthetic stress cases, not independent real tasks. Actual matching warm base required. Complete tagged wires counted; no prompt, schema provisioning, model generation or provider billing. All candidates use identical guards. Minimum is among offered representable candidates; no novel syntax or learned strategy claim.",
        "summary": summary,
        "rows": rows,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tokenizer", type=Path, help="Optional local Hugging Face tokenizer.json; no downloads"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.tokenizer)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))
