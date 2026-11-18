# Experimental schema-aware enum/default mapping

This is an opt-in lossless mapping, not semantic inference and not a new AXL release. It requires host-provisioned immutable definitions. Its equally transformed JSON control ties exactly by construction. The stronger nontransformed JSON baseline also wins on every aggregate context result in this study. Do not claim AXL superiority over JSON or improved model task success.

## Contract

`SemanticSchema` pins the ordered base schema, finite string enum tables, JSON defaults, and profile tag `axl3-sem1` in one fingerprint. Enum tables are immutable tuples, unique, nonempty, at most 256 entries, and allowed only for declared string fields. Default JSON is parsed strictly, type-checked and canonicalized into immutable text; getters return fresh objects. Default values must belong to a declared enum when relevant. Duplicate/unknown mapping fields and invalid JSON/Unicode/types/resources reject. Definitions are bounded even for empty batches. No definition is learned from an untrusted message.

Wire: JSON `["axl3-sem1",fingerprint,rows]`. Each row is `[states,values]`, with one state character per base field: `0` means absent (only optional), `1` means explicitly present with the declared default, and `2` consumes one value. A declared string enum value is an exact integer ordinal, never a boolean or coerced string. Other cells remain JSON values. Required fields cannot be absent; default markers without defaults fail. Masks, widths, ordinals and fingerprint identity are strict. Unknown enum values reject rather than trigger fallback.

Default omission compares canonical JSON spelling, distinguishing int/float/bool and signed floating zero. Absence, default, explicit null, and nondefault values remain distinct record outcomes. A present default value may also be explicitly encoded without changing the decoded value; no canonical-input requirement is claimed. Shared/default containers are detached per record. Original wire, reconstructed records, depth and node limits are checked; expanded byte limits are accumulated per record so large defaults stop early instead of building an unbounded expanded batch. Fingerprints identify definitions, not authorization or authentication.

## Frozen study

The entirely synthetic corpus was authored and frozen before its first measurement. Study strata: default-heavy workflows, varied enums, mixed presence. Newly authored holdout strata: short enum codes, unmapped nested/code payloads, exact numeric-type variations. Both use rows 1/7/31 across 16 turns. The holdout is relative to the unchanged mapping, not independent naturalistic or model-generated evidence. No corpus or mapping tuning followed observed token outcomes. All strata and losses are retained.

Corpus SHA256: `cabd8ef2e60d8d1633eb321e201a031d629911e99135aefdee33322bb1f25963`. Git attributes preserve its exact bytes. Llama 3.1 tokenizer SHA256: `79e3e522635f3171300913bb421464a87de6222182a0570b9b2ccba2a964b2b4`.

### Controls and accounting

- `semantic` and `equivalent_transformed_json`: identical mapping, JSON wire and instructions. This is an explicit equality control, not two independent implementations. Any enum/default reduction is available equally to JSON.
- `native_costaware_json`: nontransformed native packed rows and optional presence bits; receives the full semantic definition and same domain checks. This conservative control pays unnecessary compression-only default metadata.
- `native_domain_json`: stronger fourth control added after the first measurement without changing the candidate or corpus. It pins only the base schema plus enum constraints, omits compression-only defaults from setup, and uses terse tag `3` in its single domain-fingerprint envelope. It has a different profile identity but accepts the same exact record domain. A trusted adapter reconstructs the native base-schema envelope and enforces enum restrictions. It does not reinterpret a domain fingerprint as a base fingerprint.

Both native controls enumerate every subset of columns constant and present in all rows (at most 16 subsets here), validate every candidate, and choose the smallest complete current retained-prefix token count. This is a greedy per-message optimizer, not a globally optimal future-history planner. Wire and cold counts choose their own minimum candidate separately; they need not describe the same chosen message as retained context. This gives JSON strong comparison conditions rather than only an unshared baseline.

All instructions, pinned definitions and prior messages are counted in constructed retained inputs. Cold counts include setup each time. Actual cached tokenizer counts exclude provider chat framing, generation, outputs, retries and task success. Setup wording and tokenization affect results. No inference, network downloads, resets or private data were used.

## Results

All 4548 decode checks passed, including each native sharing candidate. Equivalent transformed JSON ties every per-observation measurement exactly. The following table reports aggregate retained-context tokens; full wire/cold/stratum/setup measurements remain in `results-llama31.json`.

| Split | Turns | Semantic / equal JSON | Full-definition native | Strong domain-only native | Semantic change vs strong |
| --- | ---: | ---: | ---: | ---: | ---: |
| study | 3 | 13,273 | 13,292 | 12,248 | +8.37% |
| study | 8 | 62,422 | 63,359 | 59,615 | +4.71% |
| study | 16 | 211,330 | 216,035 | 205,475 | +2.85% |
| holdout | 3 | 40,344 | 40,030 | 39,076 | +3.24% |
| holdout | 8 | 225,565 | 224,430 | 221,046 | +2.04% |
| holdout | 16 | 828,570 | 825,370 | 815,914 | +1.55% |

The conservative full-definition native control suggested small study-only retained-context savings, but those disappear against the stronger domain-only baseline. Holdout losses persist. Definitions and repeated/default information can be useful application-level choices, but this experiment does not establish a language advantage over JSON.

## Verification and reproduction

Eight test methods cover 500 generated exact roundtrips, absence/default/null/numeric distinctions, immutable definitions and detached defaults, malformed presence/ordinals/identity, duplicate keys, invalid numeric lexemes, byte/row/expansion limits, frozen corpus/hash, every summary aggregate, exact transformed ties and native domain checks. Tests are bounded probes, not a formal proof.

```sh
python -m unittest discover -s experimental/axl3/semantic -p "test_*.py" -v
python experimental/axl3/semantic/benchmark.py --tokenizer /path/to/tokenizer.json --output semantic-results-reproduced.json
```

The existing codec is untouched. This directory remains an experimental module pending review; no production default or fallback is changed.
