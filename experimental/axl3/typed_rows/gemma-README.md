# Cross-tokenizer check: Gemma

An independent Linux run used the unchanged published typed-row codec and benchmark at commit
`ba70c51c9249b65d674487bb0a421f97e7c4ac9e`, with the cached `google/gemma-4-e2b-it` tokenizer.
Revision and SHA256 are recorded in [gemma-summary.json](gemma-summary.json). No model was loaded
or called. All 153 experimental tests passed on Linux, including its POSIX process fixture.

The same 48 scenarios, format instructions, schema setup and retained history are counted.
The primary guarded JSON control has the same schema identity/type/resource contract; negotiated
JSON pins schema/version out of band. These are tokenizer counts, not provider usage or task success.

| Turns | Typed wire | Guarded wire | Typed retained | Guarded retained | Negotiated retained | Typed retained change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 3 | 75,590 | 73,686 | 178,410 | 164,414 | 147,278 | +8.51% |
| 8 | 202,242 | 197,146 | 985,114 | 935,042 | 829,826 | +5.36% |
| 16 | 405,148 | 394,996 | 3,602,096 | 3,461,186 | 3,060,290 | +4.07% |

Typed rows lose even on wire tokens (+2.58% at three turns), reversing the Llama result. Each of
the six three-turn strata loses on both wire and retained tokens. Setup costs 188 typed tokens
versus 117 guarded JSON and 122 negotiated JSON. The longer instruction cost is not the only
problem: token boundaries in the new grammar also cost more for this tokenizer.

There is no evidence here for a tokenizer-independent language advantage. Do not select this
profile by assuming fewer quotes or bytes means fewer tokens. Keep it optional; no grammar
changes were made in response to these results. The new [frozen diagnostic](heldout-README.md)
also tests content/schema sensitivity separately.

Reproduce full per-observation results from the repository root, substituting a locally obtained
tokenizer with the recorded hash and repeating for turns 3, 8 and 16:

```sh
python experimental/axl3/typed_rows/benchmark.py --tokenizer /path/to/gemma/tokenizer.json --turns 3 --output gemma-3turns.json
```

Potential next improvements require new evidence, not tuning away these losses: a shared validated
envelope implementation may remove typed decoding's serialize/reparse overhead, but must preserve
all bounds, numeric fidelity and isolation. A host-selected codec would need to count negotiation,
selection and recovery costs and compare with an equally adaptive JSON control. Neither is
implemented or claimed as an improvement by this study. Optional fields and model-generated
validity/task-success tests remain unresolved.
