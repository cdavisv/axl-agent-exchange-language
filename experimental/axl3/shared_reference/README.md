# Reuse shared-field reference serialization

Baseline: core `2130df30837885af91cde693c6953cafc5cfc3f3`, frozen in `baseline_axl3.py`
and SHA256-pinned by `results.json` and a regression test.

When encoding a shared field, the original `pack` serialized both each row's value and the same
first-row reference on every iteration. The candidate serializes that reference once per field,
then retains every original row comparison, including the first. JSON spelling comparison stays
intact: bool/int/float, signed zero and dictionary insertion order are not silently coerced.
All initial record/type/resource checks and final wire checks remain unchanged.

This relies on stable input values during packing and the normal pure `dump` implementation.
Concurrent mutation or stateful monkeypatches are outside the tested contract. No cache persists
between calls. This optimization changes CPU work, not encoding decisions, wire bytes or tokens.

## Measured result

24 synthetic cases: four constant-value families (scalar, short string, long Unicode string,
nested object), three row counts (1/8/64), sharing on/off. Complete `pack` timing includes the
original guards, record validation and wire serialization. Reusable schemas are warmed equally.
31 randomized interleaved repetitions per arm, with multiple operations per timing for small cases.
Exact wire equality and decoded values are checked. All samples and controls are retained.

Eight multirow shared cases improved **1.11–1.31x** in this local Python run. Their median-case
speedup is 1.23x; sum-of-case-medians speedup 1.27x. No-sharing and one-row controls range
0.991–1.012x, approximately unchanged. These are synthetic CPU measurements, not model latency,
agent accuracy, token savings, billing evidence or general workload gains. Shared-host timings vary.

## Verification

- 409 diagnostic valid/invalid API cases match exact wires or error class/text.
- Five regression tests cover spelling distinctions, one-shot sharing, subclasses, exact frozen
  corpus wires across all 608 turns, call-count reduction and frozen baseline provenance.
- Independent review matched another 3,132 pack cases, including subclasses that mutate or
  invalidate records during `check`. Such checks finish before reference comparison in both arms.
- Full experimental profile suite: 191 passed. Unchanged v2 tests: 137 passed.

From repository root:

```sh
python experimental/axl3/run_tests.py
python experimental/axl3/shared_reference/benchmark.py
```

The benchmark overwrites its local `results.json`. It uses no network, tokenizer or model.
