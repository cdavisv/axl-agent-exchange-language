# Bounded auxiliary traversal of Python JSON values

Baseline core: `f4696e7bf9b7c45feffeb02d237f72ea33809ae7` (pinned copy and SHA256 in this directory).
This is implementation hardening for already-materialized Python inputs, not a new wire format,
novel compression scheme, inference improvement, or claim that the wire parser was unbounded.
The existing wire byte limit remains effective.

## Implementation and contract

`validate_value` previously extended a tuple work-stack for every child before reaching its
node cap. The revised validator retains that path for lists through 4,096 elements and dictionaries
through 2,048 entries. Larger containers suspend the parent stack and yield children lazily in
1,024-node chunks. Reverse traversal, reverse chunk insertion and LIFO popping preserve the exact
original visitation order. Dictionary key-type scanning still happens before child visitation.
Successful return remains `None`; error classes, messages and validation order remain unchanged.

Inputs must not be concurrently mutated during validation. Auxiliary allocation is bounded by
chunk size, eager thresholds and maximum nesting depth, not solely a universal 21 KB ceiling.
The million-element fixture below is preconstructed; its input memory is not eliminated.

## Experiment and tradeoffs

Initial all-lazy traversal improved wide rejection but slowed tiny objects by about 35% and
record batches by 22%. A 256-child hybrid retained a substantial cliff just past its threshold.
The published hybrid uses a larger eager threshold and amortized chunks. These thresholds were
chosen using the initial diagnostic; do not call those initial cases held-out evidence.
`holdout.py` adds 750 subsequent threshold/error-precedence cases and separate end-to-end workloads.
All losses are retained. Synthetic CPU tests, not production workload evidence.

The final recorded run uses 21 randomized interleaved repetitions per arm, with multiple operations
per timing for small cases. Allocation is measured separately using `tracemalloc`, not whole-process
RSS. Exact outputs/errors are checked before timing. Files retain every timing sample.

- Rejected million-element list: 64,337,304 -> 21,432 auxiliary bytes; 18.09x faster rejection.
- Rejected 100,000-key dictionary: 12,712,832 -> 21,568 bytes; 1.74x faster rejection.
- Valid 10,000-element list: 533,920 -> 21,488 bytes; 1.16x validation speed.
- Small validation controls range from 0.94x to 1.01x baseline speed; 1,000-record case 0.97x.
- Subsequent full dump/load/raw-capsule controls for scalar/small/nested objects range 0.976x–1.012x.
- The two wider full-API cases range 1.07x–1.11x faster.

These measurements support bounded memory on wide inputs with a small ordinary-input cost, not
universal throughput improvement. Repeats on a shared host vary, especially short operations.
No token counts, model generation, security proof, or user workload distribution is established.

## Verification

10,181 diagnostic cases and 750 additional boundary cases matched exact success values or exception
class/text. Independent review matched 2,704 further cases including exception-cause type, nested
resume and chunk boundaries. Six regression tests include generated differential cases and a generous
auxiliary-allocation cap. Full profile suite: 186 tests passed; unchanged v2 suite: 137 passed.

Run from repository root:

```sh
python experimental/axl3/run_tests.py
python experimental/axl3/hybrid_validation/benchmark.py
python experimental/axl3/hybrid_validation/holdout.py
```

Benchmark commands overwrite their local result JSON files; they make no network or model calls.
