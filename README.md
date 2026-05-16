# AXL Agent eXchange Language

AXL is a compact, parser-ready wire format for agent communication: tasks, results, status, errors, evaluations, sync messages, notes, and social/community posts.

This repository is the standalone package extracted from Unigint so other projects can install it without pulling in the Unigint application stack.

## Install

```bash
pip install git+https://github.com/cdavisv/axl-agent-exchange-language.git
```

If the package is later published to PyPI, the package name is `axl-agent-exchange-language`.

For local development:

```bash
python -m pip install -e ".[dev]"
pytest
```

## Python Usage

```python
from axl import build_axl_message, normalize_axl_message, parse_axl_message

raw = build_axl_message(
    "TX",
    fields={"id": "t-1", "to": "@backend-dev", "pri": "hi"},
    directives=[">impl api/teams"],
    strict=True,
)

message = parse_axl_message(raw, strict=True)
assert normalize_axl_message(message) == "TX: id=t-1; to=@backend-dev; pri=hi; >impl api/teams"
```

You can also import through the longer compatibility namespace:

```python
from agent_exchange_language import AxlTransport, parse_axl_message
```

## What Is Included

- `src/axl/models.py`: Pydantic message models and shared protocol metadata.
- `src/axl/protocol.py`: parser, normalizer, builder, strict validation, and in-process transport.
- `src/axl/axl_protocol.json`: canonical prefixes, fields, enums, defaults, and abbreviations.
- `typescript/axl.ts`: generated TypeScript constants/types for non-Python consumers.
- `AgenteXchangeLanguage.md`: full AXL v2.0 protocol document.
- `docs/axl-directive.md`: concise authoring guidance for agent prompts.

Regenerate the TypeScript metadata after editing `src/axl/axl_protocol.json`:

```bash
python scripts/generate_axl_shared_types.py
```

## Quick Example

```python
from axl import AxlTransport, parse_axl_message

transport = AxlTransport()
task = parse_axl_message("TX: id=t-qa; to=[@qa,@security]; >review auth-release", strict=True)
transport.route(channel="dm", message=task, strict=True)

messages = transport.list_messages_for("@qa", "dm")
assert messages[0].message.fields["id"] == "t-qa"
```

## Protocol

See [AgenteXchangeLanguage.md](./AgenteXchangeLanguage.md) for the grammar, prefix semantics, validation rules, transport guidance, and examples.
