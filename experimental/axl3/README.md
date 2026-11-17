# AXL 3 experimental candidate

This directory publishes an **opt-in research prototype**, not a released AXL 3.0 specification.
The existing AXL v2 package, its 0.1.0 package version, public API, and default behavior are unchanged.
The prototype is deliberately JSON-compatible: equivalent schema-packed JSON has identical bytes.
It does not establish a novel syntax-compression advantage or improved model reasoning.

## What is included

- `axl3.py`: bounded typed schema/row codec, optional-field presence, shared fields, pinned schema
  identity, lossless parsed-JSON translation, exact raw-JSON capsule, guarded v2 compatibility, and
  message checks against caller-supplied transport context.
- `surface/`, `separators/`, `offshoots/`: optional readable act-line, explicit pipe and grouped-block
  experiments. Parsing an act never authorizes its execution.
- `dictionaries/`: scoped, exact reference hydration with cache-manifest checks.
- `lifecycle/`, `integration/`: pure lifecycle/receipt/cache reducers plus a POSIX-only local-process
  fixture. No network service, external tool execution, or production persistence guarantee.
- `deltas/`: revision/base/target guarded state changes, equivalent JSON controls, and an opt-in
  selector among snapshots, named deltas, numeric-opcode deltas, and unchanged receipts.
- `session/`: experimental schema-alias binding and explicit-metadata JSON control with
  equal sequence/replay checks; host authentication, fresh epochs and persistence remain required.
- `typed_rows/`: optional strict schema-typed text grammar, with guarded JSON comparisons;
  short-context losses and slower decoding are retained alongside conditional longer-context gains.
- `planning/`: opt-in bounded, cost-aware shared-field selection; a trusted callback can price
  full constructed context, with byte cost as the default.
- `refinement/`: bounded coding-handoff prompt builder/scorer. No model calls, arbitrary `eval`, or
  generated-code execution.
- `results/`: fully synthetic, reproducible measurements. No private transcripts, model weights,
  credentials, personal paths, or archived business content are included.

## Run locally

From the repository root, using Python 3.10+ and the existing package dependencies:

```sh
python -m pip install -e .
python experimental/axl3/run_tests.py
python experimental/axl3/benchmark_synthetic.py --output build/axl3-synthetic-bytes.json
```

Optional exact tokenizer counts require the `tokenizers` package and an independently obtained local
`tokenizer.json`. The benchmark never downloads one or calls a model:

```sh
python experimental/axl3/benchmark_synthetic.py --tokenizer /path/to/tokenizer.json --output build/axl3-tokens.json
```

The runner isolates each profile in a separate process to avoid same-name module collisions. The
153-test suite passes on the publication Windows environment with **152 passed, 1 skipped**. The
skipped integration test requires POSIX `flock`; the process fixture was previously verified on
Linux. Windows production file locking is not implemented. The existing v2 suite must also pass.

## Example

```python
# Run with experimental/axl3 on Python's module search path.
from axl3 import Schema, pack, registry, unpack

schema = Schema("notes.example", (("kind", "string", True), ("text", "string", True)))
records = [{"kind": "note", "text": "001"}, {"kind": "note", "text": "1.0"}]
wire = pack(records, schema, shared=("kind",))
assert unpack(wire, registry(schema)) == records
```

Native strings retain their types and leading zeros. Shared-field configuration accepts bounded
iterables of complete field names, not bare strings/bytes. Legacy v2 export checks semantic fidelity
and rejects unsupported or lossy conversions rather than silently changing data.

## Bounds and trust

Core limits: 256 KiB UTF-8 wire and expanded data, nesting 32, nodes 32,768, rows 1,024 and fields 128.
Duplicate JSON keys, invalid Unicode, nonfinite numbers, unpinned schemas and malformed optional
presence maps fail closed. Shared decoded containers are detached to avoid cross-row mutations.

Schema fingerprints identify definitions; they are **not signatures or source authentication**.
Transport identity and permission checks remain the host's responsibility. `accept_messages` returns
replay IDs without mutating the caller ledger. Atomic effects, persistence, host-control changes,
capabilities and approvals must stay outside model-provided content. Local duplicate suppression
is not exactly-once external execution.

The lifecycle adapter expects trusted transport/session and clock inputs. Model text cannot grant
itself those claims. The POSIX worker is a local test harness, not a hardened server or crash-recovery
system. Do not expose generic delta patching of permissions, sessions or receipts to agents.

Python numeric round-trip does not imply JavaScript precision: agree on numeric limits for other
languages. The raw-JSON capsule preserves lexical text but can expand it. This is not full JSON
Schema, a cryptographic protocol, or a production-ready cross-language standard.

## Findings and next gates

See [RESULTS.md](RESULTS.md). Adaptive selection can avoid wasting tokens on a delta when a snapshot
or no-change receipt is cheaper. This is a host strategy also available to JSON, not language
superiority. Cold receivers cannot apply deltas without a verified base. Future inference tests
must compare equal contracts, evidence, tool permissions, retries and full context costs, using
held-out tasks and the same models. Do not infer task success from tokenizer counts.
