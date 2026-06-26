# AXL Agent eXchange Language

AXL is a compact, parser-ready wire format for agent communication. It gives
tasks, results, status updates, errors, evaluations, sync messages, notes, and
social/community posts a stable shape that both humans and software can read.

This repository contains the standalone Python package for AXL. It was extracted
from Unigint so other projects can parse, validate, build, normalize, and route
AXL messages without depending on the Unigint application stack.

## Why Use AXL

Use AXL when agents, workflow runtimes, tools, or user interfaces need to pass
messages that are more structured than prose but lighter than a full JSON API.

For example, this prose instruction:

```text
Ask QA and security to review the auth release urgently.
```

can be represented as:

```text
TX: id=t-qa; to=[@qa,@security]; pri=hi; >review auth-release
```

That message is still easy for a human to scan, but code can reliably identify
the prefix, task id, recipients, priority, and directive.

The package is useful because it provides:

- A parser that turns raw AXL text into structured `AxlMessage` objects.
- A safe builder that serializes Python data into canonical AXL text.
- A normalizer that produces stable wire output for logging, storage, tests, or
  comparisons.
- Strict validation for canonical prefixes, fields, enums, recipients, channel
  rules, required task fields, social post rules, stream continuations, and
  delta operations.
- A small in-process transport for tests, local runtimes, and simple agent
  routing.
- Shared protocol metadata and generated TypeScript constants for non-Python
  consumers.

AXL is a protocol layer, not a queue, database, network service, or complete
agent orchestrator. Your application still decides where messages are stored,
how they are delivered, and what each agent does after receiving one.

## Message Shape

An AXL message has one `PREFIX:` header line with semicolon-delimited fields,
plus an optional indented payload block.

```text
TX: id=t-1; to=@backend-dev; pri=hi; >impl api/teams
  summary="Add team create/list endpoints"
  art=[file:openapi/teams.yaml]
```

The canonical AXL v2.0 prefixes are:

- `TX`: task or request.
- `RX`: result or answer.
- `ST`: status or lifecycle update.
- `ER`: error report.
- `EV`: evaluation or workflow review verdict.
- `SY`: synchronization, plan, capabilities, registry, or delta message.
- `NT`: note.
- `PS`: social/community post.

See [AgenteXchangeLanguage.md](./AgenteXchangeLanguage.md) for the full grammar,
prefix semantics, validation rules, transport guidance, and examples.

## Install

```bash
pip install git+https://github.com/cdavisv/axl-agent-exchange-language.git
```

If the package is later published to PyPI, the package name is
`axl-agent-exchange-language`.

For local development:

```bash
python -m pip install -e ".[dev]"
pytest
```

## Python Usage

Import from the short package namespace:

```python
from axl import (
    AxlParseError,
    AxlTransport,
    build_axl_message,
    normalize_axl_message,
    parse_axl_message,
)
```

You can also import through the longer compatibility namespace:

```python
from agent_exchange_language import AxlTransport, parse_axl_message
```

## Build Outbound Messages

Use `build_axl_message` when your application is creating AXL. It serializes
values safely, validates the result by reparsing it, and returns canonical wire
text.

```python
from axl import build_axl_message

raw = build_axl_message(
    "TX",
    fields={"id": "t-1", "to": "@backend-dev", "pri": "hi"},
    directives=[">impl api/teams"],
    payload={"summary": "Add team create/list endpoints"},
    strict=True,
)

print(raw)
```

Output:

```text
TX: id=t-1; to=@backend-dev; pri=hi; >impl api/teams
  summary="Add team create/list endpoints"
```

`compose_axl_message` is available as a canonical alias of
`build_axl_message` for orchestration call sites.

## Parse Inbound Messages

Use `parse_axl_message` before acting on AXL received from an agent, user
interface, log, queue, or test fixture.

```python
from axl import AxlParseError, parse_axl_message

try:
    message = parse_axl_message(
        "RX: ref=t-1; st=done; {implemented teams API}",
        strict=True,
    )
except AxlParseError as exc:
    raise ValueError(f"Invalid agent message: {exc}") from exc

assert message.prefix == "RX"
assert message.fields["ref"] == "t-1"
assert message.fields["st"] == "done"
assert message.fields["content"] == "implemented teams API"
```

`parse_axl_message` returns an `AxlMessage`, a Pydantic model with:

- `prefix`: one of the canonical prefixes.
- `fields`: parsed header fields, directives, refs, content, sequences, and
  typed items.
- `payload`: parsed indented payload assignments or payload lines.
- `raw`: the original raw message.

## Normalize For Stable Output

Use `normalize_axl_message` when you need deterministic AXL text for storage,
comparison, logging, snapshot tests, or passing a message to another component.

```python
from axl import normalize_axl_message, parse_axl_message

message = parse_axl_message(
    "TX: pri=md; chan=dm; id=t-1; to=@backend-dev; >impl api/teams"
)

assert normalize_axl_message(message) == (
    "TX: id=t-1; to=@backend-dev; >impl api/teams"
)
```

Normalization orders fields, omits prefix defaults such as `TX pri=md` and
`TX chan=dm`, safely quotes complex values, and preserves parseable structure.

## Route Messages In Process

Use `AxlTransport` for simple local routing, unit tests, workflow prototypes, or
runtime components that already have their own persistence and delivery layer.

```python
from axl import AxlTransport, parse_axl_message

transport = AxlTransport()

task = parse_axl_message(
    "TX: id=t-qa; to=[@qa,@security]; >review auth-release",
    strict=True,
)

transport.route(channel="dm", message=task, strict=True)

messages = transport.list_messages_for("@qa", "dm")
assert messages[0].message.fields["id"] == "t-qa"
```

The transport supports three channels: `dm`, `state`, and `social`. It
normalizes a message's `chan` field to match the routed channel, keeps a capped
message history, can filter messages by recipient, records `SY mode=registry`
abbreviation entries by scope, and tracks task lifecycle state from `TX`, `ST`,
`ER`, and stream/result references.

```python
transport.route(
    channel="state",
    message=parse_axl_message("ST: ref=t-qa; st=run; pct=50", strict=True),
    strict=True,
)

assert transport.get_task_state("t-qa") == "run"
```

State tracking is helpful for local workflow coordination, but it is not a
durable state store.

## Strict Validation

Pass `strict=True` when messages cross a trust boundary or when invalid protocol
usage should fail fast.

```python
from axl import AxlParseError, parse_axl_message

try:
    parse_axl_message("TX: id=t-missing-recipient; >ship fix", strict=True)
except AxlParseError:
    # Direct task messages must include a canonical to=@recipient field.
    ...
```

Strict validation rejects malformed or incomplete protocol messages, including
unsupported prefixes, invalid enum values, non-canonical recipient fields,
duplicate recipients, social posts on direct channels, missing social answer
references, malformed delta operations, invalid stream continuations, and
fields used on prefixes where they are not canonical.

## TypeScript Metadata

The Python package is the runtime implementation. Non-Python consumers can use
the generated metadata in [typescript/axl.ts](./typescript/axl.ts), which
contains canonical prefixes, fields, enum constraints, defaults, and
abbreviation lists.

After editing [src/axl/axl_protocol.json](./src/axl/axl_protocol.json),
regenerate the TypeScript metadata:

```bash
python scripts/generate_axl_shared_types.py
```

## What Is Included

- [src/axl/models.py](./src/axl/models.py): Pydantic message models and shared
  protocol metadata.
- [src/axl/protocol.py](./src/axl/protocol.py): parser, normalizer, builder,
  strict validation, and in-process transport.
- [src/axl/axl_protocol.json](./src/axl/axl_protocol.json): canonical prefixes,
  fields, enums, defaults, and abbreviations.
- [typescript/axl.ts](./typescript/axl.ts): generated TypeScript constants and
  types for non-Python consumers.
- [AgenteXchangeLanguage.md](./AgenteXchangeLanguage.md): full AXL v2.0
  protocol document.
- [docs/axl-directive.md](./docs/axl-directive.md): concise authoring guidance
  for agent prompts.
