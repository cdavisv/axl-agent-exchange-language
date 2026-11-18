# Reproducible synthetic results

## Conditions

Sixty deterministic stress cases cross four field counts (4, 16, 64, 128), three string lengths
(8, 64, 256), and five change densities (0, 1/16, 1/4, 1/2, 1). These are not independent real tasks.
Each candidate is actually decoded and checked against the same target state and revision.

All modes require an actual matching warm base. Complete tagged wires are counted. Schema/prompt
provisioning, base hydration, model generation, provider billing and network time are excluded.
The selector's minimum is among offered, representable candidates, not every possible encoding.
No-op-aware baselines are included so routine receipts are not misattributed to a new language.

## Results

| Strategy | UTF-8 bytes | Llama 3.1 tokenizer tokens |
|---|---:|---:|
| Snapshot + unchanged receipts | 319,664 | 70,410 |
| Named JSON delta + unchanged receipts | 160,996 | 45,909 |
| Numeric-opcode JSON delta + unchanged receipts | 156,472 | 47,064 |
| Byte-cost adaptive selector | 152,668 | 44,508 |
| Best offered representation for measured unit | 152,668 | 43,989 |

The byte selector saves **2.43% bytes** against the stronger numeric-opcode byte baseline, and
**3.05% tokenizer tokens** against the stronger named-delta token baseline. Numeric opcodes are not
always the strongest token baseline. Byte selection remains 519 tokens above the token minimum.
The token file is identified by SHA256 in the results; no tokenizer or weights are redistributed.

These are narrow workload results, not a general compression or agent-success claim. Enumerating
representations and choosing the cheapest is deterministic by construction, not a learned result.
AXL3's underlying packed representation is JSON, so equivalent JSON must tie it. Claims that this
proves AXL3 universally outperforms JSON would be false.

## Reliability improvements included

- Consistent bounded shared-field iteration across core and readable profiles.
- Exact numeric-looking string preservation in native AXL3 and rejection of lossy v2 exports.
- Guarded adaptive selection retains usable alternatives when another candidate exceeds size or
  depth bounds. Tests cover near-limit states, nested state, huge integer costs, stale bases,
  target tampering, invalid revisions, no-op receipts, and detached decoded containers.
- Independent review found the candidate-bound coupling and huge-cost issues before publication;
  fixes and regression tests are included. Further review verified 4,894 additional candidate
  round-trips and malformed opcode rejection. These sampled probes are not a security proof.

Historical private-workflow metrics and source data are intentionally not part of this publication.
The tracked results here can be reproduced solely from the included synthetic benchmark.

## Cost-aware sharing with retained context

The follow-on `benchmark_sharing.py` covers 48 synthetic scenarios, each with three sequential
turns. It counts the complete constructed input: common profile instructions, schema once, every
previous wire for that mode, and the next wire. It does not count native provider chat-template
framing, generated output, repair messages or provider caching. No generation model is called.

| Strategy | Llama 3.1 full constructed-context tokens |
|---|---:|
| No shared fields | 127,194 |
| Share every eligible constant | 102,636 |
| Cost-aware schema-ordered subsets | 101,622 |
| Byte-cost subset planner | 101,658 |
| Equivalent packed JSON with same guards/planner | 101,622 |
| Compact JSON with schema/version pinned by trusted session | 90,390 |

The planner improves on indiscriminate sharing by **0.99%** and on no sharing by **20.10%**, but
**ties equivalent packed JSON exactly**. Most improvement over share-all comes from avoiding
sharing overhead in single-record batches (930 of the 1,014 saved tokens). The byte heuristic is
only 36 tokens behind exact token selection here; this does not prove general tokenizer agreement.

Planned AXL3 is 12.43% larger than the compact negotiated JSON control. It omits the repeated per-message version/fingerprint, relying
on trusted out-of-band schema negotiation. That is a different wire contract, not an equal
per-message identity control. This points to session-level metadata amortization as a useful next
experiment, while making the contract tradeoff explicit. It does not establish a language win.

The new planner preserves existing codec validation and wire format. It evaluates no-sharing and
all-sharing first, then schema-ordered subsets. Small search spaces are exhaustive; larger ones
try bounded singleton/all-but-one/pair alternatives. The budget counts attempted configurations,
including unrepresentable wires. There is no global optimality promise beyond the evaluated
schema-ordered subsets, and no guarantee of best end-to-end model latency. Inputs are snapshotted
before the trusted cost callback; invalid states/costs reject. A valid shared representation can
still be selected when an unshared wire exceeds bounds.

Eight new unit tests include 100 exhaustive-oracle cases and boundary/type/presence checks.
Independent review added 160 oracle cases and a near-limit probe. Reproduce with:

```sh
python experimental/axl3/benchmark_sharing.py --output build/sharing-context-bytes.json
python experimental/axl3/benchmark_sharing.py --tokenizer /path/to/tokenizer.json --output build/sharing-context-tokens.json
```

The tracked `sharing-context-bytes.json` and `sharing-llama31-context.json` contain all case-level
measurements. Tokenizer identity is recorded by file hash; no private data or tokenizer is shipped.

Configured constant-column counts refer only to c0-c3, not every eligible field. Single-row
batches make all six fields constant. Results record both configured and actual eligible counts.
Exhaustive search is per turn; it does not optimize the whole three-turn sequence jointly.
Independent review reproduced all 144 token observations exactly, including every equivalent-JSON tie.

## Trusted-session schema metadata amortization

The `session/` offshoot tests a different contract: bind an approved schema fingerprint to a
short alias within a host-owned transport/session epoch, acknowledge it, then carry epoch, alias,
sequence and data. The explicit JSON control instead carries version/full fingerprint on each
frame. Both profiles use the same schema, transport checks, exact-last-retry detection, sequence
guards and target decoding. Equivalent alias-based JSON is identical to the session profile.

`benchmark_session.py` covers 48 synthetic scenarios with one/eight rows, short/long bodies,
1/2/4/8/16/32 frames and either stable transport or reconnect every four frames. All constructed
context costs include common instructions, schema provisioning, bind/ACK messages, every previous
data frame, and common host delivery receipts. Reconnects redo binding without erasing conversation
history. Separate transmitted-wire totals include both binding messages and every delivery receipt.
Handshakes/receipts are host-generated, not model calls. Native chat templates, generated tokens,
provider caching/billing, model quality and network latency remain outside this measurement.

Aggregate Llama 3.1 full-input token counts across four row/body conditions:

| Frames | Reconnect interval | Explicit fingerprint JSON | Session aliases | Equivalent alias JSON |
|---|---:|---:|---:|---:|
| 1 | none | 980 | 1,236 | 1,236 |
| 4 | none | 7,352 | 7,464 | 7,464 |
| 8 | none | 23,856 | 21,648 | 21,648 |
| 32 | none | 315,072 | 247,872 | 247,872 |
| 32 | 4 | 317,312 | 295,808 | 295,808 |

Short exchanges lose because binding/acknowledgment costs dominate. Longer stable exchanges save
21.33% here; reconnecting every four frames reduces that to 6.78%. These are **metadata amortization
results**, not AXL superiority over JSON: the strongest equivalent alias JSON control ties exactly.
Retaining every prior frame makes this a full-history condition, not a universal context policy.
Do not compare these totals to provider usage or omit setup costs in a shorter session.

### Mandatory host assumptions and recovery limits

- Authenticate the actual peer/session outside message content; schema definitions and binding
  approval are host-owned. A fingerprint is not a signature or capability.
- Allocate a fresh epoch for every new binding lifetime, and never reinitialize an existing binding
  after effects. The helper does not maintain a global used-epoch registry and cannot enforce this
  across host restarts. Reusing an epoch and resetting sequence can permit replay.
- Gate sending on successful `verify_ack`; the pure helper does not persist sender-readiness state.
- Commit the proposed binding/sequence and external effects atomically under host CAS/locking.
  Returning a new binding is not durable acknowledgment or exactly-once execution.
- Only an exact retry of the most recent accepted frame is deduplicated. Older retries reject and
  require application-level reconciliation. Gaps, altered retries, wrong aliases/epochs, wrong
  peers/sessions and unpinned schemas reject without advancing the supplied immutable binding.
- Reconnect with a newly approved binding/epoch. Decide at application level whether to resend a
  current snapshot or reconcile prior committed work; do not blindly replay older effects.

Nine tests cover handshake/ACK checks, explicit-control parity, typed values, exact retries,
altered retries, gaps, reconnects, malformed envelopes, rollback and sequence exhaustion.
Independent review added 300 sequential delivery/retry probes. No production security claim.

```sh
python experimental/axl3/benchmark_session.py --output build/session-context-bytes.json
python experimental/axl3/benchmark_session.py --tokenizer /path/to/tokenizer.json --output build/session-context-tokens.json
```


## Schema-typed text language candidate

The optional [typed-row profile](typed_rows/README.md) removes JSON quotes only from declared
string columns, with strict escaping, pinned schema identity, exact types and native resource
guards. It rejects optional-field schemas. Explicit LF/CRLF framing normalization is supported;
no inferred repair is attempted. This changes the language surface, not just transport metadata.

Across 48 synthetic scenarios, the Llama 3.1 tokenizer measures 2.94% fewer wire tokens than
equally guarded packed JSON. Including format instructions and schema, however, retained context
costs 4.46% more at three turns and 0.65% more at eight. At sixteen retained turns it costs 0.91%
less. Negotiated positional JSON remains smaller throughout, under its different out-of-band
schema contract. The local Python decoder is about 1.56 times slower, not faster.

This is an optional experiment, not a default replacement or a general advantage over JSON.
Ten additional tests cover exact typed values, framing and malformed/resource-limit cases;
independent review reproduced all three token artifacts and checked mutation/roundtrip cases.
No model generation, task success, provider billing or retry costs have been measured.
See the profile README and per-observation results for reproduction and all loss strata.


### Cross-tokenizer and frozen-content counterexamples

The [Gemma tokenizer check](typed_rows/gemma-README.md) reverses even the small Llama wire win:
three-turn wire costs 2.58% more than guarded JSON, and retained context costs 8.51%, 5.36%, and
4.07% more at 3/8/16 turns. Every primary stratum loses on wire and retained tokens.

A [new frozen synthetic diagnostic](typed_rows/heldout-README.md), authored after the original
study but measured against the unchanged grammar, varies schema string fractions, code/logs,
URLs, multilingual controls, numeric-only/nested content, and empty/all-shared cases. Its Llama
retained totals are 3.40%, 1.00%, and 0.04% larger at 3/8/16 turns. The earlier sixteen-turn
aggregate win does not reproduce. All 1,824 exact checks passed, and an independent run reproduced
every observation. Two integrity tests pin corpus bytes and reaggregate all recorded summaries.

These counterexamples are retained, not tuned away. A smaller character representation does not
ensure lower token cost. Shared parser internals or host codec selection are possible future
experiments, not proven improvements. No task-success or model-generation evidence exists here.


### Guard-preserving decoder implementation improvement

The [shared-envelope refactor](typed_rows/envelope-README.md) removes typed rows' redundant JSON
reparse, not the serialization that enforces reconstructed bounds. Both JSON and typed use the
same validated expansion. Six differential tests plus independent mutation/boundary review retain
acceptance/value behavior; all frozen corpus encoder bytes remain identical.

Four-arm full-entrypoint CPU measurements show typed decoding about 15.65% faster than its prior
implementation on 36 primary workloads, and 17.70% faster on 38 frozen first-turn workloads. JSON
is effectively unchanged. Updated typed decoding still takes 32.50% and 47.65% more time than
updated JSON, respectively. This is local implementation efficiency, not token savings, model
latency, provider billing, or a JSON performance win. No grammar change or weaker guard is used.


## Semantic schema redundancy experiment

The optional [semantic mapping](semantic/README.md) tests finite string enum ordinals and exact
default omission with explicit absent/default/value states. Definitions are immutable and pinned;
numeric types, null/absence distinctions, strict masks/indices and expanded bounds are preserved.
This is an experimental JSON mapping, not a new AXL release or semantic inference.

Identically transformed JSON ties every observation. A stronger native JSON control provisions
only base schema plus enum constraints, omits unnecessary compression-only default metadata, and
exhaustively chooses constant-field sharing subsets against the current full retained context.
Against that control, the candidate costs 8.37%, 4.71%, and 2.85% more study tokens at 3/8/16 turns;
the frozen synthetic holdout costs 3.24%, 2.04%, and 1.55% more. Apparent small wins against an
overprovisioned full-definition baseline disappear with the stronger control. All cases remain.

Eight tests and 4,548 decode checks support exactness; no model generation/task-success evidence.
This remains opt-in research, not a recommended default. The existing codecs are unchanged.


## Immutable schema metadata caching

The [per-instance cache](schema_cache/README.md) avoids repeated native schema fingerprint and
field-set calculations. Only exact immutable `Schema` instances use the fast path; subclasses
retain dynamic behavior. Public definition views stay fresh, dataclass fields remain unchanged,
and legacy uncached pickle state works lazily. Caches are bounded and live only with their schema.
Wire bytes, fingerprints, grammar and token results are unchanged; all parser guards remain.

On 38 frozen first-turn workloads, hot median-case decode time is 7.73% lower for JSON and 9.45%
lower for typed rows. Summed case medians improve only 2.25% and 3.10%, respectively, because larger
payload work dominates. Typed remains 35.75% slower than equally cached JSON by median-case ratio.
Construction is roughly unchanged; constructor plus first fingerprint is 0.26–4.81% slower, while
constructor plus first JSON decode is 8.94–19.00% faster on 1/4/16/128-field synthetic schemas.

These are local CPU diagnostics, not universal throughput or model-latency claims. Seven new tests
cover ordinary API/legacy/subclass compatibility and old/new parity; old full modules are frozen
as independent controls. Extra per-instance metadata memory and first-access cost are explicit.
