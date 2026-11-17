# Per-instance immutable Schema metadata cache

This is a local runtime optimization, not a wire-language or token-count change. Both native JSON and typed rows benefit. Existing canonical fingerprints, schema definition bytes, encoder outputs and parser guards remain unchanged.

## Design and compatibility

Exact `Schema` instances are deeply immutable through the supported API: names/types are exact strings, fields are exact tuples and required flags are exact booleans. Three private lazy `cached_property` values retain the fingerprint, a frozenset of field names, and a frozenset of string indices. There is no global cache. At most 128 names and indices plus one fixed-size fingerprint are retained per instance, and they are collectible with it. This adds per-instance memory and first-access work; no precise resident-memory claim is made. Concurrent first access may perform benign duplicate computations of identical immutable metadata.

No dataclass fields or constructor validation steps were added. Dataclass `fields`, `asdict`, signature, repr, equality, hash and replacement behavior stay unchanged. The public `definition` property constructs a fresh defensive view every time. Copy/deepcopy/pickle preserve behavior; legacy objects restored without cached attributes populate them lazily. Subclasses take the original dynamic fingerprint and field-metadata path, preserving overrides of `definition` or initialization. The optimization applies to normal immutable instances under fixed module policy constants. Mutating `__dict__`, using `object.__setattr__` to bypass frozen fields, or changing resource-policy constants at runtime is not a supported cache-invalidation API.

The production diff is confined to `axl3.py`; typed/semantic codecs were not changed. Both hot controls use their own full core and typed modules, not old schemas passed into new code. Frozen baseline sources come from commit `665ed1b159c8f3eb4376f4cce1e880cd8665dcc6`; hashes and the typed import-only retargeting are documented in `provenance.json`. Snapshots are test/benchmark oracles, never production fallbacks.

## Evidence

Seven new test methods cover constructor acceptance and canonical ordering, exact dataclass API, defensive views, dynamic subclass behavior, lazy/bounded/collectible caches, copy/deepcopy/pickle/legacy state, 100 generated varying schemas with 2,000 mutations, all 608 frozen heldout observations across both codecs, expanded limits and detached output containers. Existing profiles and v2 suites also pass. Independent review additionally verified baseline provenance and real legacy pickle remapping across protocols 0 through 5.

The CPU benchmark uses all 38 first-turn heldout scenarios, including empty/all-shared batches and varying schema shapes. Hot arms use three warmups and 30 shuffled paired repetitions with correctness checks outside timing. Every hot timing includes the complete decoding entrypoint. Cold arms use 100 shuffled pairs per field count and separately measure construction, construction plus first fingerprint, and construction plus first JSON decode including registry creation. Timing is local Python implementation behavior, not model latency or a universal throughput claim. p95 is the sorted sample at zero-based floor(0.95*(n-1)).

### Recorded hot run

Median per-case new/old ratios:

- Native JSON: **0.9227**, about **7.73% faster**.
- Typed rows: **0.9055**, about **9.45% faster**.
- New typed/new JSON: **1.3575**, so typed remains about **35.75% slower**.

Summed per-case medians: old/new JSON 19.1374/18.7069 ms; old/new typed 25.4005/24.61295 ms. The summed medians improve only about 2.25% for JSON and 3.10% for typed. These sums are not one batch timing and need not show the same percentage as median case ratios. Larger payload work dominates some cases, so metadata caching does not uniformly improve all workloads.

### Cold tradeoff

Construction alone is approximately unchanged in this run. Construction plus first fingerprint is **0.26% to 4.81% slower**, because lazy metadata storage has a cost. Construction plus first decode is **8.94% to 19.00% faster** across 1/4/16/128 fields, since a decode otherwise repeats fingerprint/field work. Per-case medians and samples summarized by p95 are preserved in `results.json`. Tiny timings are sensitive to noise; use the local repeated measurements, not a universal promise.

## Reproduce

```sh
python -m unittest discover -s experimental/axl3/schema_cache -p "test_*.py" -v
python experimental/axl3/schema_cache/benchmark.py --output schema-cache-results-reproduced.json
```

No model calls, credentials, private transcripts, network transfers or credit resets are involved. This is a shared implementation gain for JSON and AXL profiles, not evidence that a custom language beats JSON.
