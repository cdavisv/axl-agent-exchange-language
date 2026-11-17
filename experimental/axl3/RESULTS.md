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
