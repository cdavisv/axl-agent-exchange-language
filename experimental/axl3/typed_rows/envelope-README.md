# Shared validated-envelope decoder

This implementation-only optimization shares the same internal envelope expansion between guarded
JSON and typed rows. JSON still enters through strict `load(wire)`. Typed rows still parse JSON
cells strictly and call `dump(envelope)` to enforce the identical canonical-envelope byte limit,
aggregate nodes/depth and scalar validation, but no longer reparse that serialized envelope.
Serialization remains. The private helper is not an untrusted Python-object entry point.

No encoder, grammar, instructions, wire bytes or token results change. This does not repair the
token losses documented in the Gemma and frozen-corpus studies. Existing v2 remains untouched.

## Correctness and controls

The test-only `decoder_baseline.py` preserves the old decoder/encoder bodies from the commit in
`decoder-baseline-provenance.json`, importing unchanged common primitives. Independent review
checked source hashes and AST equivalence after renaming. It is not a production fallback.

Six new differential tests cover generated values, numeric precision/nonfinite/negative-zero
rules, duplicate keys, malformed schemas/widths/indices, node/depth/row/byte/expanded bounds,
container isolation, 3,000 seeded wire mutations, and all 608 frozen-corpus observations with
byte-identical encoders and matching decoder outcomes. Independent review added 400 valid cases
and 6,000 mutations. Finite tests do not establish a universal equivalence proof; private helper
callers must honor the validated-input contract.

## Four-arm CPU diagnostic

Both old and new JSON are included alongside old and new typed rows. All four full text entry
points are timed, including preprocessing, parsing, validation, expansion and detached copies.
Inputs/wires are prepared outside decode timing; this is not encode/decode roundtrip timing.
Each case uses three warmups and 30 repetitions with seeded shuffled arm order. Exact correctness
is checked outside every timed interval. Python 3.14.2 on Windows; no model/network/I/O timing.

| Corpus | Cases | Median new typed / old typed | Median new JSON / old JSON | Median new typed / new JSON |
| --- | ---: | ---: | ---: | ---: |
| Original synthetic families | 36 | 0.8435 | 0.9987 | 1.3250 |
| Frozen varied-schema first turns | 38 | 0.8230 | 1.0000 | 1.4765 |

Typed decoding takes about 15.65% less time in the first study and 17.70% less in the frozen
first-turn study; JSON is effectively unchanged. Typed remains 32.50% and 47.65% slower than
respectively matched new JSON controls. This is a useful implementation improvement, not a speed
win over JSON or a language/token advantage. Ratios are medians of per-case median ratios, not
aggregate throughput. Per-case losses and p95 estimator details remain in the result files.
Background load/interpreter/workload matter; the frozen first-turn sample is not every session.

The earlier `decoder-results.json` is intentionally retained as pre-refactor history. Current
four-arm measurements are `envelope-cpu-results.json` and `envelope-cpu-heldout-results.json`.

```sh
python experimental/axl3/typed_rows/envelope_cpu_benchmark.py --corpus primary --output primary-cpu.json
python experimental/axl3/typed_rows/envelope_cpu_benchmark.py --corpus heldout --output heldout-cpu.json
python experimental/axl3/run_tests.py
```

The next riskier optimization would remove serialization while preserving exact canonical byte
accounting. It is not implemented. Do not replace bounds with approximate character counts or
skip guards to improve timing.
