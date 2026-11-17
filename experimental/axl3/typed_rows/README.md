# Experimental schema-typed text rows

This is a language-level candidate, not a replacement for AXL3 or a claim of better model task success. Removing JSON quotes around schema-declared strings produces small wire-token savings, but its longer instructions and slower Python decoder make it unattractive for short contexts in this study. Keep it experimental.

## Profile and safety contract

A message consists of `@axl3t ` plus the pinned 64-character lowercase schema fingerprint, then a line beginning `=` containing the JSON shared-index map, then zero or more `>`-prefixed tab-separated rows. Remaining columns follow schema order after shared columns are removed. All schema fields must be required; optional-field schemas are rejected. Empty batches have no row lines. An all-shared row is `>`; schema width distinguishes this from an empty string cell.

Declared string fields are exact strings, not inferred JSON: `001`, `true`, and `null` stay strings. Escape backslash as `\\`, tab as `\t`, LF as `\n`, CR as `\r`, and other C0 controls as `\xhh` with exactly two lowercase hex digits. Unknown/incomplete escapes, raw C0 string characters, and hex escapes for printable characters are rejected. Other field types, including `any`, use JSON literals. Strings inside `any` therefore remain JSON-quoted.

LF and CRLF framing are accepted, with at most one optional terminal line ending. This is explicit lossless framing normalization, not guessed repair. Tabs, spaces, empty cells, and trailing tabs are never trimmed. Extra blank rows fail. Encoders emit LF without a terminal newline.

Native AXL3 pack/unpack validation remains authoritative for schema identity, exact shared indices, row width, types, Unicode, nesting, expanded resources, and isolated shared containers. The original input is bounded before normalization; the reconstructed JSON envelope also has to satisfy native bounds. Consequently a text message fitting the text byte bound can still be rejected when its reconstructed envelope exceeds a native bound. This is a deliberate limitation, not a successful roundtrip. No optional-field coercion or inferred repair is attempted. A schema fingerprint is not authentication, authorization, or corruption protection.

## Reproducible synthetic study

Forty-eight scenarios cross six strata, 1/4/16/64 rows, and kind-field sharing on/off. Three-turn primary results are retained unchanged; eight- and sixteen-turn runs are separately labeled longer-session ablations of the same corpus. Each arm is decoded and compared with type-preserving canonical JSON for every observation. No private transcripts are used.

The primary control is native guarded packed JSON with identical schema, fingerprint, shared map, type and resource checks, not verbose JSON objects. The secondary positional JSON control omits version/fingerprint per message using a trusted out-of-band pinned schema: a different contract, not an equally self-identifying format.

Actual locally cached Llama 3.1 tokenizer tokens are counted without special tokens. Tokenizer SHA256: `79e3e522635f3171300913bb421464a87de6222182a0570b9b2ccba2a964b2b4`.

Setup includes common safety text, the full pinned schema, and format-specific instructions: typed rows 175 tokens, guarded JSON 107, negotiated JSON 113. Cold counts include setup plus the current message. Retained-context counts sum every constructed input containing setup and all prior messages at each turn. These are tokenizer measurements, not provider billing: native chat framing, output generation, retry/repair costs, and task success are unmeasured. Instruction wording influences the crossover.

### Three-turn primary totals

| Format | Wire | Cold | Retained context |
| --- | ---: | ---: | ---: |
| Typed rows | 60,061 | 85,405 | 145,576 |
| Guarded packed JSON | 61,881 | 77,433 | 139,364 |
| Negotiated positional JSON | 55,833 | 72,249 | 128,132 |

Typed rows save 2.94% wire tokens against guarded JSON, but cost 10.30% more cold tokens and 4.46% more retained-context tokens. They lose to negotiated positional JSON on all three aggregate measures.

| Stratum | Wire change vs guarded JSON | Retained-context change |
| --- | ---: | ---: |
| Metadata | -3.96% | +6.81% |
| Natural prose | -2.07% | +4.15% |
| Numeric-looking strings | -1.52% | +8.06% |
| Escapes/control-heavy strings | -5.52% | +2.78% |
| Unicode | -1.96% | +6.44% |
| Nested/mixed values | -2.87% | +1.81% |

Negative changes mean fewer tokens. No loss stratum was removed.

### Longer-session ablation: aggregate retained-context tokens

| Turns | Typed rows | Guarded JSON | Negotiated JSON | Typed vs guarded |
| --- | ---: | ---: | ---: | ---: |
| 3 | 145,576 | 139,364 | 128,132 | +4.46% |
| 8 | 791,732 | 786,600 | 716,328 | +0.65% |
| 16 | 2,874,956 | 2,901,290 | 2,631,722 | -0.91% |

There is a small conditional aggregate win over guarded JSON after 16 retained turns, not an overall win or a universal break-even guarantee. Negotiated positional JSON remains smaller throughout. This does not establish model reliability or generation speed.

## Correctness and decoder cost

Ten test methods pass, including 1,000 generated exact typed batches, numeric-looking strings, actual Unicode and escaped controls, empty/all-shared rows, container isolation, LF/CRLF framing, malformed/unknown escapes, optional-schema rejection, mismatched widths/fingerprints/types, and byte/row/depth/expanded-resource failures. Independent review additionally reproduced all three token-result files exactly and exercised generated roundtrips and mutations. Some mutations are valid changed messages, not required rejections.

A separate 36-case CPU diagnostic uses three warmups and 30 repetitions, seeded shuffled arm order, and checks each decoded result outside the timed interval. On Python 3.14.2/Windows, typed decoding was **1.556x slower** by median per-case ratio; summed per-case medians were 28.6421 ms versus 18.8176 ms. These sums are descriptive, not one batch timing. Per-case p95 is the sorted sample at zero-based floor(0.95*(n-1)), not nearest-rank or interpolated. Background load and implementation matter. These are local decoder costs, not model latency. More compact syntax did not yield faster parsing here.

## Run

From repository root, with Python and (for token measurements) the `tokenizers` package:

```sh
python -m unittest discover -s experimental/axl3/typed_rows -p 'test_*.py' -v
python experimental/axl3/typed_rows/benchmark.py --output results-bytes.json
python experimental/axl3/typed_rows/benchmark.py --tokenizer /path/to/tokenizer.json --turns 3 --output results-llama31.json
python experimental/axl3/typed_rows/benchmark.py --tokenizer /path/to/tokenizer.json --turns 8 --output results-llama31-8turns.json
python experimental/axl3/typed_rows/benchmark.py --tokenizer /path/to/tokenizer.json --turns 16 --output results-llama31-16turns.json
python experimental/axl3/typed_rows/decoder_benchmark.py --output decoder-results.json
```

Result files in this directory preserve per-observation counts and per-case timing. Byte-only output is not evidence about tokenizer behavior. Next useful evidence would be a controlled model-generation/task-success comparison with retry costs, rather than further tuning synthetic strings to enlarge a small token win.
