# Refined result: AXL is not the token-efficiency winner

November15,2026. This is a deterministic serialization/context-capacity experiment, **not model inference or a coding-success benchmark**.

The original AXL benefit shrinks against flat JSON and reverses against schema-defined array JSON. Shared envelopes improve further, although that is an architectural batching control, not a pure syntax comparison.

## Gemma4 E2B results
Actual pinned tokenizer and official chat template; own instruction overhead included for each format, same20 records per paired fixed-evidence sample:

| Format | Mean input tokens | Mean snippets at8,192-token input cap |
|---|---:|---:|
| Nested compact JSON |3,400.33|48.27|
| Flat compact JSON |3,303.33|49.60|
| AXL |3,252.33|50.57|
| Schema-defined array JSON |3,141.33|52.20|
| Shared-envelope JSON |3,025.33|54.60|

Mean paired differences: AXL saves4.36% relative to nested JSON and1.55% to flat JSON, but costs3.54% more than array JSON and7.52% more than shared-envelope JSON. Percentages are averages of paired relative differences, not ratios of the above aggregate means.

Qwen2.5 Coder tokenizer sensitivity check agrees on ranking: AXL costs3.39% more than array JSON and7.83% more than shared-envelope JSON. Qwen is content-only, not native chat-framed; compare formats within each tokenizer, not raw totals between models.

## Scope and verification
- Expanded from156 AXL snippets to1,232 snippets:1,076 from independent public Pallets Click and156 from AXL. This convenience corpus is Click-heavy, not a representative coding benchmark.
- Thirty deterministic permutations of the same corpus, not30 independent coding tasks;1,800 observations total.
- All formats retain identical source text, source path/line references, IDs, recipient and message type. Shared JSON hoists repeated type/recipient into an envelope; array JSON has a charged positional schema.
- Same-ranked-prefix selection at each token cap; no skipping records to favor shorter evidence. Caps are input budgets; generation space must be reserved separately in real inference.
-137 upstream tests and8 local tests passed in isolated project environment. Independent review informed the stronger controls and trusted metadata checks.
- Exact source commits, tokenizer and result hashes, Python/dependency versions in provenance.json and requirements.lock.txt. Original pilot retained under pilot-v1.

## Lossless oversized-source transport
AXL nominally limits payload lines to8,192bytes, but upstream actually checks Unicode character counts. New splitter reduces chunk size until strict serialization and an explicit UTF-8 byte-per-line check succeed, preserves character offsets/full-text length/source ID/SHA256, and reassembles byte-equivalent UTF-8 content. Tests reject missing, duplicate, reordered and mutated chunks. Caller-supplied expected source ID/digest/recipient can bind reassembly to a trusted manifest; self-declared hashes alone do NOT authenticate provenance.

Chunking is not compression. In the16,500-byte synthetic source example, shared JSON uses6,579 unchunked input tokens versus8,093 chunked; AXL requires chunking and uses8,180. Chunk costs include metadata, extra instruction schema and nested escaping. The21,000-byte Unicode/escaping case also increases. No latency or model comprehension was measured.

## Recommended next experiment
Do not assume AXL itself expands useful context more than optimized JSON. Compare a model-facing **array/shared-envelope JSON baseline** with AXL, keeping evidence retrieval, reasoning topology and tool budgets fixed. AXL could still help structured routing, validation or model comprehension, but those benefits need measured model-generated outputs and executable task outcomes. Benchmark coding success separately from syntax/token count. No hidden tests or gold patches should enter the agent context.

No paid inference, repository publication, pushes or competition submissions were made.

Upstream nominal byte limits are character-count checks; our chunker now explicitly verifies UTF-8 bytes. Batch payload is limited to256lines. JSON-map order relies on Python insertion-order preservation; JSON rows is the portable ordered control.

## Final symmetric batching check

The earlier7.52% gap compared per-record AXL to batched JSON. That is not a pure format comparison. A final ablation now batches AXL too, using the unmodified v2 strict serializer: one shared NT/recipient header, source IDs as payload keys, exact source evidence as values. Both JSON rows and a same-shape JSON map control are included.

| Corpus | AXL batch mean tokens | JSON rows mean tokens | AXL increase vs rows | JSON map mean tokens |
|---|---:|---:|---:|---:|
|Mixed1,232 snippets|3,052.33|3,019.33|1.10%|3,003.33|
|AXL-only156 snippets|3,318.43|3,285.43|1.01%|3,269.43|
|Click-only1,076 snippets|3,041.50|3,008.50|1.10%|2,992.50|

Thirty paired permutations per corpus;1,620 observations. All format instructions and native Gemma chat framing counted. At8,192 input tokens on the mixed corpus: AXL batch54.17 snippets, JSON rows54.63, JSON map54.97. This substantially narrows the asymmetric gap but does not show AXL winning. Compare totals only within each experiment because instruction strings differ across experiments.

JSON map order relies on Python insertion order; the rows array is the stronger portable-order control. Batches require common message type/recipient and unique payload-safe IDs; duplicates or mixed envelopes are rejected. The current corpus/caps stay within v2 limits. These are findings for a restricted homogeneous evidence schema, not arbitrary agents or mixed messages. Eleven local tests now pass, plus137 unchanged upstream tests. No inference was run.

Reproducibility confirmed with project-local Python and Jinja2 3.1.6 under axl-benchmark/.venv; no cross-project runtime imports. Exact sources/dependencies/hashes are recorded. Optional trusted expectations protect provenance only when the caller supplies them from a trusted source.
