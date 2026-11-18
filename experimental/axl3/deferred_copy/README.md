# Guard-preserving deferred row detachment

This is a rejection-cost optimization, not a new codec or relaxed limit.

For exact immutable native schemas, retain validated row references while running all existing
guards in their original order. Only after the batch passes, deep-copy each row independently.
Invalid batches no longer pay for copies that will be discarded. Subclasses retain eager
snapshots. Public validation/check returns remain None, and rows retain mutable isolation.

Incremental early node rejection was not adopted because it changed error priority on multiply
invalid inputs. Deferral retains byte/node/row validation order and diagnostic text. It assumes
immutable policy/schema behavior during a call, as existing caching does. Runtime monkeypatches
of validation or copying are not supported.

## Evidence

Baseline: commit 8743a6839fe5dcb96731564ed29d8fe8f2312773, Git blob
d2b8587fbc732f8e6281dfbc651786d71fa1a0bf. Benchmark also records source SHA256.
Run `python experimental/axl3/deferred_copy/benchmark.py` and
`python experimental/axl3/run_tests.py` from the repository root. No downloads/model needed.

Benchmark: 206 exact serialized-output or Error-text comparisons, eleven shuffled repetitions
for six selected cases. Four invalid shared-array batches reject 1.35–1.52x faster in the
recorded cloud Python run, with zero deep copies versus 33, 65, 16 and 8. Valid controls retain
copy counts; their small timing differences do not establish normal-throughput improvement.
Timing is noisy and workload-dependent, not model latency, token savings or a security proof.

Four regression tests cover 500 seeded envelopes, mixed-invalid precedence, expanded limits,
public None returns, isolation, subclass behavior and no copies before rejection. Independent
review added 3,300 matching outcome probes. Latest experimental suite: 180 passed on Linux,
including POSIX fixture. Existing v2 suite: 137 passed. No merge or deployment.
