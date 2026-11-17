"""Measure a frozen held-out corpus; do not tune grammar from results."""

import argparse
import hashlib
import json
from pathlib import Path
from benchmark import COMMON, PROFILE, MODES
from typed_rows import encode, decode
from axl3 import Schema, dump, load, pack, registry, unpack

HERE = Path(__file__).resolve().parent


def run(tokenizer_path):
    from tokenizers import Tokenizer

    raw = (HERE / "heldout-corpus.json").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    assert digest == (HERE / "heldout-corpus.sha256").read_text().strip()
    corpus = json.loads(raw)
    tokenizer = Tokenizer.from_file(str(tokenizer_path))

    def cost(s):
        return len(tokenizer.encode(s, add_special_tokens=False).ids)

    def canonical(v):
        return json.dumps(v, sort_keys=True, ensure_ascii=True)

    observations = []
    setups = {}
    for case in corpus["cases"]:
        schema = Schema(
            "heldout." + case["family"] + ".v1",
            tuple((name, kind, True) for name, kind in case["fields"]),
        )
        schemas = registry(schema)
        instructions = {
            m: COMMON + PROFILE[m] + "SCHEMA=" + dump(schema.definition) + "\n" for m in MODES
        }
        setups[case["family"]] = {m: cost(s) for m, s in instructions.items()}
        histories = dict(instructions)
        for turn, records in enumerate(case["turns"]):
            packed = pack(records, schema, tuple(case["shared"]))
            wires = {
                "typed_rows": encode(records, schema, tuple(case["shared"])),
                "guarded_packed_json": packed,
                "negotiated_positional_json": dump(load(packed)[2:]),
            }
            measures = {}
            for mode, wire in wires.items():
                actual = (
                    decode(wire, schemas)
                    if mode == "typed_rows"
                    else unpack(
                        wire
                        if mode == "guarded_packed_json"
                        else dump([3, schema.fingerprint, *load(wire)]),
                        schemas,
                    )
                )
                assert canonical(actual) == canonical(records), (case["family"], turn, mode)
                measures[mode] = {
                    "wire": cost(wire),
                    "cold": cost(instructions[mode] + "NEXT=" + wire),
                    "retained_context": cost(histories[mode] + "NEXT=" + wire),
                }
                histories[mode] += "PREVIOUS=" + wire + "\n"
            observations.append(
                {
                    "family": case["family"],
                    "rows": case["rows"],
                    "shared": bool(case["shared"]),
                    "turn": turn,
                    "costs": measures,
                }
            )
    families = list(setups)
    summary = {}
    for turns in (3, 8, 16):
        summary[str(turns)] = {}
        for family in ("all", *families):
            chosen = [
                x
                for x in observations
                if x["turn"] < turns and (family == "all" or x["family"] == family)
            ]
            summary[str(turns)][family] = {
                m: {
                    metric: sum(x["costs"][m][metric] for x in chosen)
                    for metric in ("wire", "cold", "retained_context")
                }
                for m in MODES
            }
    return {
        "scope": "Frozen held-out deterministic synthetic study, not model inference. Same existing grammar/setup wording; full setup and retained history counted. No provider chat template/output/retry costs. Negotiated JSON trusts schema/version out of band, unlike equally guarded primary JSON. No task-success claim. All observations retained.",
        "corpus_sha256": digest,
        "tokenizer_sha256": hashlib.sha256(Path(tokenizer_path).read_bytes()).hexdigest(),
        "scenarios": len(corpus["cases"]),
        "exact_typed_checks": len(observations) * len(MODES),
        "setup_costs": setups,
        "summary": summary,
        "observations": observations,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tokenizer", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = run(args.tokenizer)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf8")
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k not in ("observations", "setup_costs", "summary")
            },
            indent=2,
        )
    )
    print(json.dumps({n: v["all"] for n, v in result["summary"].items()}, indent=2))
