# Historical AXL v2 evidence-capacity studies

This archive makes the November 14–15, 2026 experiments reproducible. It is an **encoding/tokenizer study, not agent inference, coding success or a competition submission**. All reports retain the stronger JSON controls and negative findings.

## Included evidence

- `benchmark.py`: same ordered public evidence across nested/flat/array/shared JSON and strict AXL, including format instructions.
- `batched.py`: symmetric batching in AXL and JSON so one-sided batching is not mistaken for syntax improvement.
- `chunking.py`: lossless oversized-source transport, explicit UTF-8 line checks and trusted manifest options. This is a narrow benchmark helper, not a hardened network receiver.
- Eleven tests; frozen public corpus; historical results, summaries and source/dependency hashes.
- `HISTORICAL_REPORT.md` records the original interpretation. Its statements that no publication had happened refer to that historical run, not this archive.

The mixed corpus contains 156 snippets from the user's public AXL repository and 1,076 from Pallets Click, deterministically sliced into twelve-line pieces. The Click BSD-3-Clause copyright/conditions/disclaimer are retained in `licenses/Click-LICENSE.txt`. Source attribution is preserved in each snippet. No private transcripts or work records are included.

## Findings to retain

AXL's apparent advantage over nested JSON reverses against schema-defined arrays. After symmetric batching, AXL uses approximately 1.10% more Gemma tokens than JSON rows on the mixed corpus. Thirty permutations of one convenience corpus are not thirty independent tasks. Chunking increases tokens; it enables transport, not compression. `agent_success` remains null.

## Reproduce without downloading anything automatically

Use Python 3.12 and dependencies matching `requirements.lock.txt` in an isolated environment. Supply an existing AXL checkout at commit `1f9dfba14a9fdf79c84db05f8023c12060c40f1c` through `AXL_REPO`; the scripts use its `src/` directory. In a repository-native placement at `experimental/axl3/v2_evidence`, the default is the containing repository, but pinning the historical checkout is preferable for exact reproduction.

```sh
export AXL_REPO=/path/to/pinned/axl-checkout
python -m unittest test_benchmark.py test_chunking.py test_batched.py -v
python verify_artifacts.py
```

To regenerate tokenizer results, supply a local directory through `AXL_TOKENIZER_DIR` with these child folders:

- `google--gemma-4-e2b-it`: `tokenizer.json`, `chat_template.jinja`, and `source.json` containing `{"model":"google/gemma-4-e2b-it","sha":"4adf15748de9e1a0097b6274cee9c15836c41c37"}`.
- `Qwen--Qwen2.5-Coder-0.5B-Instruct`: `tokenizer.json` and `source.json` containing `{"model":"Qwen/Qwen2.5-Coder-0.5B-Instruct","sha":"ea3f2471cf1b1f0db85067f1ef93848e38e88c25"}`. Do not add a Qwen chat template when reproducing these content-only results.

Original tokenizer/template hashes appear in `original-provenance.json`. No tokenizers, templates, weights, source checkout trees or virtual environments are redistributed here. Obtain permitted artifacts independently. Scripts do not fetch them.

```sh
export AXL_TOKENIZER_DIR=/path/to/local/tokenizer-directory
python benchmark.py
python batched.py
python chunking.py
```

Run in a copy if preserving recorded results: these commands replace their result/summary files. Corpus bytes are fixed and hash-checked, not regenerated. It is the same public corpus as the original study, verified against its original SHA256. Because tokenizer files are external, full token regeneration is conditional on those exact inputs. The scripts do not verify every external file automatically; compare against recorded hashes before interpreting differences.

## Archive verification and limits

Portability changes replace private workspace layout assumptions with environment paths and use the frozen, attributed corpus instead of scanning an external source tree. AST-formatting changes preserve executable semantics. All eleven tests passed again against the pinned AXL checkout on November 18. The complete historical token benchmark was not rerun during packaging; its result hashes match the original provenance exactly. Prior upstream test counts in the historical report describe the original run, not a fresh full-platform suite.

The chunk helper checks its own benchmark schema, ordered offsets and digest. Self-declared hashes provide integrity, not authenticity; trusted expected source/digest/recipient must come from the host. It is not an authorization mechanism or a generic untrusted-input parser. Neither Python object order nor this benchmark establishes cross-language JSON map ordering; use row arrays as the portable-order control.
