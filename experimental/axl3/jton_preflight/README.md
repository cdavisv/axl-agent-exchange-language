# JTON preflight, 2026-11-17

## Verified primary sources
- Preprint v1, submitted 7 April 2026: https://arxiv.org/abs/2604.05865
- Full paper: https://arxiv.org/html/2604.05865v1
- Author repository: https://github.com/gowthamkumar-nandakishore/JTON
- License: https://github.com/gowthamkumar-nandakishore/JTON/blob/master/LICENSE
- Specification: https://github.com/gowthamkumar-nandakishore/JTON/blob/master/SPEC.md

Repository license is MIT, copyright Gowthamkumar Nandakishore, 2025–2026; preserve the copyright and permission notice when reusing substantial source. No source copied or executed here.

## Applicability and caution
The paper evaluates header-sharing against compact JSON, not schema-packed JSON or AXL. Its o200k_base token measurements do not establish Gemma/Llama savings. Its own limitations say orjson is faster than JTON. Thus it is useful related work and an external comparator, not evidence to replace AXL or claim novelty for shared column headers.

There is a material version discrepancy: paper section 3.2 permits a table when at least 70% of rows share the first row's key set; specification inspected on 2026-11-17 section 6.2 requires all rows to have identical keys in identical order and otherwise falls back to JSON. The paper maps missing cells to null. A sparse absent-property case must not silently acquire nulls. This discrepancy is NOT a confirmed current implementation bug.

The specification inspected on 2026-11-17 also says multiline output is serializer-only and not parsed by loads. Exclude it from a lossless benchmark unless a verified separate decoder is included. Zen Grid output is not strict JSON, even though the parser accepts JSON input.

## Work performed
Created ten public synthetic fixture groups and a standard-library-only preflight. All ten preserve exact Python scalar/container types and signed zero through compact JSON; five qualify under the documented strict grid rule. Fixtures cover absent versus null, 70% overlap, reordered keys, reserved literal strings, punctuation/control/Unicode strings, nesting, large integer, signed zero, empty/single rows.

Run: `python preflight.py` regenerates fixtures.json and preflight-results.json.

No JTON reference runtime, tokenizer comparison, model generation, recovery or throughput experiment ran. This is a historical preflight note, not a claim about current runtime or package availability. Byte counts are fixture inventory ONLY, not token savings. These synthetic fixtures are now archived in the experimental repository. No JTON implementation source is redistributed.

## Next bounded experiment
Pin the implementation revision; inspect/build only through an authorized supported route. Run fixtures against actual dumps/loads before timing. Compare identical reconstructed records across compact JSON, headers-plus-rows JSON, existing AXL JSON/typed layouts, and JTON comma/tab/bare variants. Count complete cold setup and warm schema-amortized cost separately with each available Gemma and Llama tokenizer. Include missing-property distinction, strict type preservation, malformed row counts/widths, reserved strings and recovery attempts. Time encode+decode+validation with stdlib and orjson controls, then model generation on held-out tasks. Do not infer task success or novel contribution from byte/token compression alone.
