# Frozen held-out synthetic diagnostic

This corpus was newly authored after the original study and frozen before its first token measurement. It is held out relative to the unchanged grammar, not independent naturalistic data, user data, or model task-success evidence. No grammar or instruction tuning followed these outcomes. All scenarios and losses are retained.

## Design

Six new strata use code/logs, URLs, multiline documents, multilingual/control/empty strings, numeric-only values, and nested-heavy records. Schema-declared string fractions span 0%, 25%, 67%, 75%, 80%, and 100%. Each crosses rows 1/7/31 and first-field sharing on/off; additional empty-batch and all-shared cases give 38 scenarios. Sixteen turns are generated per scenario; prefix analyses at 3/8/16 turns are correlated ablations, not independent replications. Nested-heavy records intentionally have most strings inside JSON objects rather than declared string cells.

The original grammar and per-format instructions are reused unchanged. Primary guarded packed JSON has the same pinned schema, fingerprint, exact typing, and resource checks. Secondary negotiated positional JSON trusts schema/version out of band and therefore has a different metadata contract. Setup includes the schema and format-specific instructions. Retained cost sums each constructed input including setup and every previous message. Provider chat framing, output tokens, model generation, retry costs and downstream task success are not measured.

Corpus SHA256: `0002d0da5cdf9326b557c612d09e28dd4fefeb93f7f1ba75b520df175189ce0a`. The SHA256 file is checked on every benchmark run. The generator refuses to overwrite an existing frozen corpus. Tokenizer SHA256: `79e3e522635f3171300913bb421464a87de6222182a0570b9b2ccba2a964b2b4` (cached Llama 3.1). The final corpus superseded a pre-measurement draft to incorporate rows 1 and explicit edge cases; no token results existed at that revision.

## Results

All 1,824 exact typed decode checks passed (38 scenarios x 16 turns x 3 formats). Counts below are tokenizer tokens, not measured billing.

| Turns | Typed wire | Guarded wire | Typed retained | Guarded retained | Negotiated retained | Retained change vs guarded |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 3 | 82,145 | 83,029 | 184,837 | 178,766 | 170,288 | +3.40% |
| 8 | 218,858 | 221,355 | 1,041,963 | 1,031,629 | 978,481 | +1.00% |
| 16 | 437,460 | 442,559 | 3,839,669 | 3,838,073 | 3,634,049 | +0.04% |

The original sixteen-turn aggregate win did not reproduce on this newly authored diagnostic: typed rows still cost 0.04% more retained tokens at sixteen turns. Three-turn wire savings are only 1.06%, with cold setup-inclusive totals 102,413 versus 95,545 (7.19% worse). Negotiated JSON remains smaller in aggregate. A smaller wire alone is not an overall improvement.

### Per-stratum changes versus guarded JSON

| Stratum | Three-turn wire | Three-turn retained | Sixteen-turn retained |
| --- | ---: | ---: | ---: |
| code_logs | -3.46% | +2.42% | -1.84% |
| urls | -6.31% | -0.87% | -4.93% |
| multiline_docs | -2.33% | +3.52% | -0.72% |
| multilingual_controls | -3.06% | +8.44% | +0.29% |
| numeric_only | +7.65% | +17.76% | +9.64% |
| nested_heavy | +0.55% | +1.96% | +0.89% |
| empty_batches | +0.00% | +37.36% | +13.77% |
| all_shared | +0.00% | +35.42% | +12.67% |

Positive changes mean more tokens. Empty and all-shared edge cases are included, not silently discarded. Detailed setup costs and every observation are in `heldout-results.json`. No automatic fallback selection or post-hoc string tuning was used. This bounds the evidence: gains depend on schema, content, tokenizer, setup wording, and history length. It does not validate broad generalization or model reliability.

## Reproduce

From repository root:

```sh
python experimental/axl3/typed_rows/heldout_benchmark.py --tokenizer /path/to/tokenizer.json --output heldout-results-reproduced.json
```

The committed corpus is the frozen input. `heldout_corpus.py` documents deterministic generation and can regenerate in a separate clean directory; it will not replace an existing corpus. No model calls, credits resets, private data, network downloads, or codec changes are involved.


## Gemma cross-check of the same frozen corpus

An independent Linux execution of the published corpus also passed all 1,824 exact checks.
The Gemma tokenizer identity is recorded in [gemma-summary.json](gemma-summary.json), and
[heldout-gemma-summary.json](heldout-gemma-summary.json) records the aggregate results.

| Turns | Typed wire | Guarded wire | Typed retained | Guarded retained | Negotiated retained | Typed retained change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 3 | 104,141 | 104,002 | 229,649 | 221,243 | 208,475 | +3.80% |
| 8 | 284,840 | 284,526 | 1,330,653 | 1,307,503 | 1,228,995 | +1.77% |
| 16 | 575,070 | 574,442 | 4,982,169 | 4,933,357 | 4,634,069 | +0.99% |

Unlike the primary Gemma corpus, this diagnostic has some winning strata: sixteen-turn
code/log retained tokens are 552,092 versus 553,436 (-0.24%), and multilingual/control tokens
are 270,442 versus 294,022 (-8.02%). Other strata lose, and the aggregate remains larger.
Content, schema and tokenizer jointly matter; neither the positive subsets nor negative
aggregate establish model reliability. Run the same heldout command with the Gemma tokenizer
to reproduce full per-observation results. No grammar changes followed these measurements.
