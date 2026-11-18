# Experimental native JSON-tool boundary

Opt-in interoperability prototype, not a provider integration, authorization system, released API or default prompt. The host supplies a pinned `Schema`; models supply only ordinary JSON `{ "records": [...] }`. `arguments_to_axl` validates exact arguments and packs the existing native wire; `axl_to_arguments` decodes only that pinned schema. Neither executes a tool or accepts permissions from record contents. Optional absence is not replaced by null/defaults.

`tool_definition` returns fresh generic JSON Schema metadata. A provider may reject unsupported schema features; this does not claim support for any provider's strict structured-output subset. Provider/tool-schema validation cannot replace native codec checks: for example JSON Schema may consider floating `1.0` an integer, but AXL exact integer rejects it. Model schema identifiers are never trusted.

The wrapper consumes additional byte/node/depth budget. A valid native AXL wire can fail conversion to tool arguments near limits; failure is explicit, with no truncation or silent dropping. Inputs and expanded outputs still pass native bounds. The helper does not guarantee every native wire can be represented within the tool envelope.

## Example

```python
# Add experimental/axl3/native_tools to sys.path for this isolated prototype.
from native_tools import arguments_to_axl, axl_to_arguments
from axl3 import Schema

schema = Schema("example", (("id", "string", True), ("value", "any", False)))
wire = arguments_to_axl('{"records":[{"id":"001","value":null},{"id":"002"}]}', schema)
assert axl_to_arguments(wire, schema) == '{"records":[{"id":"001","value":null},{"id":"002"}]}'
```

## Abbreviated instructions: experimental only

`brief_instruction` returns a shorter prompt for native all-required schemas. The unchanged runtime still validates; fewer detailed rejection instructions could increase model errors/retries. No model has been tested with this prompt, so it is not enabled automatically or recommended as a default. Optional schemas are rejected by this prompt helper, though the tool bridge supports them.

## Measured startup diagnostic

`diagnostic.py` compares four alternatives with existing guarded JSON instructions on 38 previously examined synthetic scenarios, three turns each. It counts full constructed text using local Gemma and Qwen tokenizers, including full generic tool schema. No model weights/inference, output generation, provider chat-template/billing, retries or task success is measured. This is exploratory and not fresh heldout evidence. The shorter runtime prompt was added after the first three candidates were measured; all rejected alternatives remain.

On the final exported implementation (`summary.json`):

- Brief prompt reduces setup tokens by 22.82% Gemma / 20.76% Qwen, but total first-input tokens only by 2.65% / 2.37%. Model reliability is unknown.
- Concise general rewrite ties Gemma setup and increases Qwen setup 1.81%; rejected as optimization.
- Schema-specialized instructions increase setup 21.55% / 23.47%; rejected.
- Native-tool adapter increases total first-input tokens by about 8.48% / 8.87%. Keep for compatibility experiments, not compression. Full native-tool metadata and named-record payloads are counted.

The same transformations and host validation are available to JSON: no language-superiority claim. Later core changes preserve the existing wire; this run used core at `a12d43c18d1af1298c757099c40854a85ef99758`. Independent review exercised 1,000 additional exact optional-field roundtrips and malformed/depth probes. This is sampled testing, not a security proof.

## Reproduce

From repository root:

```sh
python -m unittest discover -s experimental/axl3/native_tools -p 'test_*.py' -v
python experimental/axl3/native_tools/diagnostic.py --tokenizer /path/to/local/tokenizer.json --output build/native-tools-results.json
```

The 13 focused tests require only the standard library. Optional diagnostic token counting requires `tokenizers` and a locally supplied tokenizer, never downloaded by the script. The diagnostic verifies 228 exact adapter/native checks per tokenizer, and outputs every observation so totals can be independently recomputed. Existing v2 and core/default behavior are unchanged.
