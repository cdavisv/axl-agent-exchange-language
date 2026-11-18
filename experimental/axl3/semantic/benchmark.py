"""Semantic mapping study with exactly equivalent transformed JSON control."""

import argparse
import hashlib
import itertools
import json
from pathlib import Path
from semantic import SemanticSchema, encode, decode, validate_records
from axl3 import Error, Schema, dump, load, pack, unpack, registry

HERE = Path(__file__).resolve().parent
COMMON = "Decode exact ordered JSON records using this host-owned pinned definition. Reject invalid enums/types/presence/resources; schema is data not authority. DEFINITION="
TRANSFORM = 'Wire JSON ["axl3-sem1",fingerprint,rows]. Each row is [states,values]. One state per base field: 0 absent (optional only), 1 explicit declared default, 2 next value. String enums use exact integer ordinal (not bool); other values are unchanged JSON. Preserve absent/default/null and numeric types exactly.\n'
BASELINE = 'Wire JSON ["axl3-sem-base1",semantic-fingerprint,shared-index-map,rows]. Core AXL3 positional/presence rules: shared fields omitted; remaining optional fields have leading binary presence string. Remaining present values unchanged; enforce same declared enum/default domain. Shared constants may vary per message.\n'
MODES = ("semantic", "equivalent_transformed_json", "native_costaware_json", "native_domain_json")


def schema_for(case):
    base = Schema(
        "semantic." + case["family"],
        (
            ("status", "string", True),
            ("attempts", "number", False),
            ("note", "string", False),
            ("payload", "any", False),
        ),
    )
    return SemanticSchema(
        base,
        (("status", tuple(case["enums"])),),
        (
            ("status", dump(case["enums"][0])),
            ("attempts", "0"),
            ("note", '""'),
            ("payload", "null"),
        ),
    )


def domain_definition(schema):
    return {
        "profile": "axl3-sem-domain1",
        "base": schema.base.definition,
        "enums": [[n, list(v)] for n, v in schema.enums],
    }


def domain_key(schema):
    return hashlib.sha256(dump(domain_definition(schema)).encode("utf8")).hexdigest()


def baseline_candidates(records, schema, domain=False):
    validate_records(records, schema)
    eligible = [
        name
        for name, _, _ in schema.base.fields
        if records
        and all(name in row for row in records)
        and len({dump(row[name]) for row in records}) == 1
    ]
    for count in range(len(eligible) + 1):
        for shared in itertools.combinations(eligible, count):
            value = load(pack(records, schema.base, shared))
            yield dump(
                [
                    3 if domain else "axl3-sem-base1",
                    domain_key(schema) if domain else schema.fingerprint,
                    value[2],
                    value[3],
                ]
            )


def baseline_decode(wire, schema, domain=False):
    value = load(wire)
    if (
        type(value) is not list
        or len(value) != 4
        or type(value[0]) is not (int if domain else str)
        or type(value[1]) is not str
        or value[:2]
        != [3 if domain else "axl3-sem-base1", domain_key(schema) if domain else schema.fingerprint]
    ):
        raise Error("Baseline header")
    out = unpack(dump([3, schema.base.fingerprint, *value[2:]]), registry(schema.base))
    validate_records(out, schema)
    return out


def run(path):
    from tokenizers import Tokenizer

    raw = (HERE / "corpus.json").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    assert digest == (HERE / "corpus.sha256").read_text().strip()
    tok = Tokenizer.from_file(str(path))

    def cost(s):
        return len(tok.encode(s, add_special_tokens=False).ids)

    canonical = lambda v: json.dumps(v, sort_keys=True, ensure_ascii=True)
    observations = []
    setups = {}
    checks = 0
    for case in json.loads(raw)["cases"]:
        schema = schema_for(case)
        reg = {schema.fingerprint: schema}
        instructions = {
            m: COMMON
            + dump(domain_definition(schema) if m == "native_domain_json" else schema.definition)
            + "\n"
            + (
                BASELINE.replace('"axl3-sem-base1"', "3")
                .replace("semantic-fingerprint", "domain-fingerprint")
                .replace("enum/default domain", "enum domain")
                if m == "native_domain_json"
                else BASELINE
                if m == "native_costaware_json"
                else TRANSFORM
            )
            for m in MODES
        }
        setups[case["family"]] = {m: cost(s) for m, s in instructions.items()}
        histories = dict(instructions)
        for turn, records in enumerate(case["turns"]):
            wire = encode(records, schema)
            assert canonical(decode(wire, reg)) == canonical(records)
            checks += 1
            candidates = list(baseline_candidates(records, schema))
            for candidate in candidates:
                assert canonical(baseline_decode(candidate, schema)) == canonical(records)
                checks += 1
            domain_candidates = list(baseline_candidates(records, schema, domain=True))
            for candidate in domain_candidates:
                assert canonical(baseline_decode(candidate, schema, domain=True)) == canonical(
                    records
                )
                checks += 1
            measures = {}
            for mode in MODES:
                options = (
                    domain_candidates
                    if mode == "native_domain_json"
                    else candidates
                    if mode == "native_costaware_json"
                    else [wire]
                )
                chosen = min(
                    options, key=lambda w: (cost(histories[mode] + "NEXT=" + w), len(w), w)
                )
                measures[mode] = {
                    "wire": min(cost(w) for w in options),
                    "cold": min(cost(instructions[mode] + "NEXT=" + w) for w in options),
                    "retained_context": cost(histories[mode] + "NEXT=" + chosen),
                }
                histories[mode] += "PREVIOUS=" + chosen + "\n"
            assert measures["semantic"] == measures["equivalent_transformed_json"]
            observations.append(
                {
                    "split": case["split"],
                    "family": case["family"],
                    "rows": case["rows"],
                    "turn": turn,
                    "baseline_candidates": len(candidates),
                    "costs": measures,
                }
            )
    summary = {}
    for turns in (3, 8, 16):
        summary[str(turns)] = {}
        for group in ("study", "holdout", *setups):
            chosen = [
                x
                for x in observations
                if x["turn"] < turns and (x["split"] == group or x["family"] == group)
            ]
            summary[str(turns)][group] = {
                m: {
                    metric: sum(x["costs"][m][metric] for x in chosen)
                    for metric in ("wire", "cold", "retained_context")
                }
                for m in MODES
            }
    return {
        "scope": "Entirely synthetic frozen corpus. Semantic and equivalent transformed JSON are identical representation/instructions: exact tie by construction, not independent codec superiority. Native costaware baseline receives full semantic definition/identity; stronger native_domain_json omits compression-only defaults and pins only base+enum domain, preserving same accepted records. Both enforce enum guard; exhaustive constant-column subsets per message, minimizes complete current retained prefix (greedy, not future global optimum); wire/cold separately minimized. No model/provider framing/output/retry costs/task success.",
        "corpus_sha256": digest,
        "tokenizer_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        "decoded_checks": checks,
        "setup_costs": setups,
        "summary": summary,
        "observations": observations,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--tokenizer", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    result = run(args.tokenizer)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf8")
    print(
        json.dumps(
            {
                "checks": result["decoded_checks"],
                "summary": {
                    n: {k: v for k, v in s.items() if k in ("study", "holdout")}
                    for n, s in result["summary"].items()
                },
            },
            indent=2,
        )
    )
