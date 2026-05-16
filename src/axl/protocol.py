"""AXL v2.0 parsing, normalization, and in-process routing."""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict, deque
from datetime import date, datetime
from typing import Any, Literal, cast

from .models import (
    AXL_CANONICAL_PREFIXES,
    AXL_DELTA_OPERATION_OPS,
    AXL_ENUM_CONSTRAINTS,
    AXL_FIELD_PREFIX_GUIDANCE,
    AXL_ID_OPTIONAL_PREFIXES,
    AXL_PREFIX_DEFAULTS,
    AXL_PS_ID_OPTIONAL_KINDS,
    AXL_PS_REF_REQUIRED_KINDS,
    AXL_RX_ID_OPTIONAL_STATUSES,
    AXL_SOCIAL_RX_FIELD_COMPATIBILITY,
    AXL_STREAM_CONTINUATION_VALUES,
    AxlEnvelope,
    AxlMessage,
    AxlParseError,
    AxlPrefix,
)

logger = logging.getLogger(__name__)

CANONICAL_PREFIXES = set(AXL_CANONICAL_PREFIXES)
TRANSPORT_MESSAGE_HISTORY_LIMIT = 256
TRANSPORT_STATE_MAP_LIMIT = 2048
TRANSPORT_REGISTRY_SCOPE_LIMIT = 256
AxlChannel = Literal["state", "dm", "social"]
_VALID_CHANNELS = {"state", "dm", "social"}

# ── Parser bounds (DoS hardening) ─────────────────────────────────────
# All limits apply at parser entry; raw AXL messages that exceed them are
# rejected before further work. Values are intentionally generous for normal
# traffic (workflow handoffs, payload blocks, social posts) but small enough
# that adversarial input cannot exhaust memory or stack.
MAX_AXL_MESSAGE_BYTES = 256 * 1024
MAX_AXL_PAYLOAD_LINES = 256
MAX_AXL_PAYLOAD_LINE_BYTES = 8 * 1024
MAX_AXL_HEADER_ITEMS = 256
MAX_AXL_LIST_ITEMS = 1024
MAX_AXL_VALUE_NESTING_DEPTH = 32
MAX_AXL_DELTA_OPERATIONS_BYTES = 64 * 1024
MAX_AXL_DELTA_OPERATIONS = 256
MAX_AXL_DELTA_POINTER_BYTES = 1024

__all__ = [
    "AxlEnvelope",
    "AxlMessage",
    "AxlParseError",
    "AxlPrefix",
    "compose_axl_message",
    "AxlTransport",
    "build_axl_message",
    "extract_abbreviation_registry",
    "normalize_axl_message",
    "parse_axl_message",
]

# ── Enum constraints ──────────────────────────────────────────────────

ENUM_CONSTRAINTS: dict[str, set[str]] = {
    field_name: set(values) for field_name, values in AXL_ENUM_CONSTRAINTS.items()
}
_VALID_STATUS_VALUES = set(ENUM_CONSTRAINTS.get("st", set()))

# ── Canonical field ordering ──────────────────────────────────────────

CANONICAL_FIELD_ORDER = [
    "id",
    "ref",
    "to",
    "from",
    "chan",
    "kind",
    "sub",
    "tone",
    "tgt",
    "pri",
    "c",
    "st",
    "sev",
    "retry",
    "fmt",
    "src",
    "score",
    "art",
    "fix",
    "tok",
    "mode",
    "operations",
    "expected_revision_no",
    "base_revision",
    "out",
    "pct",
    "split",
    "opts",
    "stream",
    "seq",
    "cond",
    "counter",
    "esc",
    "stake",
    "ts",
    "ddl",
    "why",
    "ver",
    "tldr",
    "note",
    "content",
    "caps",
    "abbr",
    "meaning",
]
_CANONICAL_FIELD_ORDER_INDEX = {
    field_name: index for index, field_name in enumerate(CANONICAL_FIELD_ORDER)
}

# ── Per-prefix defaults (omitted from wire when equal) ────────────────

PREFIX_DEFAULTS: dict[str, dict[str, str]] = {
    prefix: dict(defaults) for prefix, defaults in AXL_PREFIX_DEFAULTS.items()
}

# Prefixes where ``id`` may be omitted (fire-and-forget)
_ID_OPTIONAL_PREFIXES = set(AXL_ID_OPTIONAL_PREFIXES)
_PS_ID_OPTIONAL_KINDS = set(AXL_PS_ID_OPTIONAL_KINDS)
_PS_REF_REQUIRED_KINDS = set(AXL_PS_REF_REQUIRED_KINDS)
_RX_ID_OPTIONAL_STATUSES = set(AXL_RX_ID_OPTIONAL_STATUSES)
_STREAM_CONTINUATION_VALUES = set(AXL_STREAM_CONTINUATION_VALUES)
_DELTA_OPERATION_OPS = set(AXL_DELTA_OPERATION_OPS)

# Fields that are only canonical on specific prefixes. Compatibility is warning-level
# except where dedicated validation below enforces stronger semantics.
_FIELD_PREFIX_GUIDANCE: dict[str, set[str]] = {
    field_name: set(prefixes) for field_name, prefixes in AXL_FIELD_PREFIX_GUIDANCE.items()
}
_SOCIAL_RX_FIELD_COMPATIBILITY = set(AXL_SOCIAL_RX_FIELD_COMPATIBILITY)

# ── State machine valid transitions ───────────────────────────────────

_VALID_TRANSITIONS: dict[str, set[str]] = {
    # Compact workflows commonly emit the first observable follow-up directly from
    # a freshly created task without an intermediate ack/run hop.
    "new": {"ack", "run", "wait", "blk", "done", "fail", "cxl", "rj", "partial"},
    "ack": {"run", "wait", "blk", "cxl", "rj"},
    "run": {"done", "fail", "wait", "blk", "partial", "cxl"},
    "wait": {"run", "blk", "cxl", "fail"},
    "blk": {"run", "wait", "cxl", "fail"},
    "partial": {"partial", "run", "done", "fail"},
    "done": set(),  # terminal
    "fail": {"run", "cxl"},  # retry re-entry
    "cxl": set(),  # terminal
    "rj": {"ack", "run"},  # counter-proposal accepted
}

# ── Regex helpers ─────────────────────────────────────────────────────

_SEQ_RE = re.compile(r"\s*->\s*")
_CAUSE_RE = re.compile(r"\s*<-\s*")
_REF_GLYPHS = {"@": "to", "#": "alias", "^": "prior", "&": "dep"}
_ABBR_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
_RECIPIENT_REF_RE = re.compile(r"^@[A-Za-z0-9_.:/+-]+$")
_PARSE_DELIMITER_CHARS = frozenset('"[](){}')
_PARSER_RESERVED_FIELD_NAMES = frozenset(
    {"atoms", "cause", "directives", "refs", "sequence", "typed"}
)
_PARSER_RESERVED_PAYLOAD_KEYS = frozenset({"lines"})


# ── Tokenizing helpers ────────────────────────────────────────────────


def _ensure_balanced_delimiters(value: str, *, context: str = "AXL value") -> None:
    """Validate quotes and structural delimiters on a single parsed value."""

    in_quotes = False
    depth_bracket = 0
    depth_paren = 0
    depth_brace = 0
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and in_quotes and i + 1 < len(value):
            i += 2
            continue
        if ch == '"':
            in_quotes = not in_quotes
        elif not in_quotes:
            if ch == "[":
                depth_bracket += 1
            elif ch == "]":
                depth_bracket -= 1
                if depth_bracket < 0:
                    raise AxlParseError(f"Unmatched brackets `[]` in {context}.")
            elif ch == "(":
                depth_paren += 1
            elif ch == ")":
                depth_paren -= 1
                if depth_paren < 0:
                    raise AxlParseError(f"Unmatched parentheses `()` in {context}.")
            elif ch == "{":
                depth_brace += 1
            elif ch == "}":
                depth_brace -= 1
                if depth_brace < 0:
                    raise AxlParseError(f"Unmatched braces `{{}}` in {context}.")
        i += 1

    if in_quotes:
        raise AxlParseError(f"Unclosed quote in {context}.")
    if depth_bracket != 0:
        raise AxlParseError(f"Unmatched brackets `[]` in {context}.")
    if depth_paren != 0:
        raise AxlParseError(f"Unmatched parentheses `()` in {context}.")
    if depth_brace != 0:
        raise AxlParseError(f"Unmatched braces `{{}}` in {context}.")


def _split_header_items(header_remainder: str) -> list[str]:
    """Split header items by ``;`` respecting quotes, brackets, braces, parens."""
    items: list[str] = []
    current: list[str] = []
    in_quotes = False
    depth_bracket = 0
    depth_paren = 0
    depth_brace = 0
    i = 0
    while i < len(header_remainder):
        ch = header_remainder[i]
        if ch == "\\" and in_quotes and i + 1 < len(header_remainder):
            current.append(ch)
            current.append(header_remainder[i + 1])
            i += 2
            continue
        if ch == '"':
            in_quotes = not in_quotes
        elif not in_quotes:
            if ch == "[":
                depth_bracket += 1
            elif ch == "]":
                depth_bracket -= 1
                if depth_bracket < 0:
                    raise AxlParseError("Unmatched brackets `[]` in AXL header.")
            elif ch == "(":
                depth_paren += 1
            elif ch == ")":
                depth_paren -= 1
                if depth_paren < 0:
                    raise AxlParseError("Unmatched parentheses `()` in AXL header.")
            elif ch == "{":
                depth_brace += 1
            elif ch == "}":
                depth_brace -= 1
                if depth_brace < 0:
                    raise AxlParseError("Unmatched braces `{}` in AXL header.")
            elif ch == ";" and depth_bracket == 0 and depth_paren == 0 and depth_brace == 0:
                items.append("".join(current))
                current = []
                i += 1
                continue
        current.append(ch)
        i += 1
    if current:
        items.append("".join(current))

    # v2.0: validate balanced delimiters
    if in_quotes:
        raise AxlParseError("Unclosed quote in AXL header.")
    if depth_bracket != 0:
        raise AxlParseError("Unmatched brackets `[]` in AXL header.")
    if depth_paren != 0:
        raise AxlParseError("Unmatched parentheses `()` in AXL header.")
    if depth_brace != 0:
        raise AxlParseError("Unmatched braces `{}` in AXL header.")

    return [item.strip() for item in items if item.strip()]


def _split_list_items(inner: str) -> list[str]:
    """Split comma-separated items respecting nested delimiters."""
    items: list[str] = []
    current: list[str] = []
    in_quotes = False
    depth_bracket = 0
    depth_paren = 0
    depth_brace = 0
    i = 0
    while i < len(inner):
        ch = inner[i]
        if ch == "\\" and in_quotes and i + 1 < len(inner):
            current.append(ch)
            current.append(inner[i + 1])
            i += 2
            continue
        if ch == '"':
            in_quotes = not in_quotes
            current.append(ch)
        elif not in_quotes:
            if ch == "[":
                depth_bracket += 1
            elif ch == "]":
                depth_bracket -= 1
                if depth_bracket < 0:
                    raise AxlParseError("Unmatched brackets `[]` in AXL list.")
            elif ch == "(":
                depth_paren += 1
            elif ch == ")":
                depth_paren -= 1
                if depth_paren < 0:
                    raise AxlParseError("Unmatched parentheses `()` in AXL list.")
            elif ch == "{":
                depth_brace += 1
            elif ch == "}":
                depth_brace -= 1
                if depth_brace < 0:
                    raise AxlParseError("Unmatched braces `{}` in AXL list.")
            elif ch == "," and depth_bracket == 0 and depth_paren == 0 and depth_brace == 0:
                items.append("".join(current))
                current = []
                if len(items) > MAX_AXL_LIST_ITEMS:
                    raise AxlParseError(f"AXL list exceeds maximum of {MAX_AXL_LIST_ITEMS} items.")
                i += 1
                continue
            current.append(ch)
        else:
            current.append(ch)
        i += 1
    if current:
        items.append("".join(current))

    if len(items) > MAX_AXL_LIST_ITEMS:
        raise AxlParseError(f"AXL list exceeds maximum of {MAX_AXL_LIST_ITEMS} items.")

    # v2.0: validate balanced delimiters (mirrors _split_header_items)
    if in_quotes:
        raise AxlParseError("Unclosed quote in AXL list.")
    if depth_bracket != 0:
        raise AxlParseError("Unmatched brackets `[]` in AXL list.")
    if depth_paren != 0:
        raise AxlParseError("Unmatched parentheses `()` in AXL list.")
    if depth_brace != 0:
        raise AxlParseError("Unmatched braces `{}` in AXL list.")

    return items


def _find_top_level_tokens(value: str) -> tuple[int, int, int]:
    """Return ``(eq_index, sequence_index, cause_index)`` in a single pass.

    Scans *value* once to locate the first top-level ``=``, ``->``, and
    ``<-`` tokens, skipping quoted and nested content.  Replaces three
    separate ``_find_top_level_token`` calls for a ~3x reduction in
    per-item scanning work.
    """

    in_quotes = False
    depth_bracket = 0
    depth_paren = 0
    depth_brace = 0
    eq_index = -1
    seq_index = -1
    cause_index = -1
    found = 0
    i = 0
    length = len(value)
    while i < length and found < 3:
        ch = value[i]
        if ch == "\\" and in_quotes and i + 1 < length:
            i += 2
            continue
        if ch == '"':
            in_quotes = not in_quotes
            i += 1
            continue
        if not in_quotes:
            if ch == "[":
                depth_bracket += 1
            elif ch == "]":
                depth_bracket = max(0, depth_bracket - 1)
            elif ch == "(":
                depth_paren += 1
            elif ch == ")":
                depth_paren = max(0, depth_paren - 1)
            elif ch == "{":
                depth_brace += 1
            elif ch == "}":
                depth_brace = max(0, depth_brace - 1)
            elif depth_bracket == 0 and depth_paren == 0 and depth_brace == 0:
                if ch == "=" and eq_index < 0:
                    eq_index = i
                    found += 1
                elif ch == "-" and i + 1 < length and value[i + 1] == ">":
                    if seq_index < 0:
                        seq_index = i
                        found += 1
                elif ch == "<" and i + 1 < length and value[i + 1] == "-":
                    if cause_index < 0:
                        cause_index = i
                        found += 1
        i += 1
    return eq_index, seq_index, cause_index


def _parse_value(raw_value: str, *, _depth: int = 0) -> Any:
    if _depth > MAX_AXL_VALUE_NESTING_DEPTH:
        raise AxlParseError(
            f"AXL value nesting exceeds maximum depth of {MAX_AXL_VALUE_NESTING_DEPTH}."
        )
    value = raw_value.strip()
    if not value:
        return ""
    if not _PARSE_DELIMITER_CHARS.isdisjoint(value):
        _ensure_balanced_delimiters(value)
    if value.startswith('"') and value.endswith('"'):
        return _unescape_quoted_value(value[1:-1])
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_value(item, _depth=_depth + 1) for item in _split_list_items(inner)]
    if value.startswith("(") and value.endswith(")"):
        inner = value[1:-1].strip()
        if not inner:
            return {"_group": []}
        return {
            "_group": [_parse_value(item, _depth=_depth + 1) for item in _split_list_items(inner)]
        }
    if value.startswith("{") and value.endswith("}"):
        # v2.0: content stored as plain string (no _nlesc wrapper)
        return value[1:-1]
    if value in {"yes", "no"}:
        return value
    if value.isdigit() or (len(value) > 1 and value.startswith("-") and value[1:].isdigit()):
        return int(value)
    if re.fullmatch(r"-?(?:\d+\.\d+|\d+\.)", value):
        return float(value)
    return value


def _value_to_strings(value: Any) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    rendered: list[str] = []
    for item in items:
        if isinstance(item, dict):
            if "_group" in item:
                text = ", ".join(str(part) for part in item.get("_group") or [])
            else:
                text = str(item)
        else:
            text = str(item)
        compact = " ".join(text.split()).strip()
        if compact:
            rendered.append(compact)
    return rendered


def _normalize_registry_pairs(
    abbr_value: Any,
    meaning_value: Any,
) -> list[tuple[str, str]]:
    abbreviations = _value_to_strings(abbr_value)
    meanings = _value_to_strings(meaning_value)
    if not abbreviations and not meanings:
        return []
    if not abbreviations or not meanings:
        raise AxlParseError("AXL registry messages must include both `abbr` and `meaning`.")
    if len(abbreviations) != len(meanings):
        raise AxlParseError(
            "AXL registry messages must provide the same number of `abbr` and `meaning` values."
        )

    seen: set[str] = set()
    pairs: list[tuple[str, str]] = []
    for abbreviation, meaning in zip(abbreviations, meanings, strict=True):
        if not _ABBR_RE.match(abbreviation):
            raise AxlParseError(
                "AXL registry entries must use compact identifiers "
                "matching `[A-Za-z][A-Za-z0-9_-]{0,31}`."
            )
        normalized_key = abbreviation.casefold()
        if normalized_key in seen:
            raise AxlParseError(f"AXL registry contains duplicate abbreviation `{abbreviation}`.")
        seen.add(normalized_key)
        if not meaning.strip():
            raise AxlParseError(
                f"AXL registry entry `{abbreviation}` must include a non-empty meaning."
            )
        pairs.append((abbreviation, meaning))
    return pairs


def extract_abbreviation_registry(message: AxlMessage) -> dict[str, str]:
    """Return abbreviation registry entries declared by a SY registry message."""

    if message.prefix != "SY":
        return {}
    if str(message.fields.get("mode", "")).lower() != "registry":
        return {}
    abbr_value = message.fields.get("abbr", message.payload.get("abbr"))
    meaning_value = message.fields.get("meaning", message.payload.get("meaning"))
    return {
        abbreviation: meaning
        for abbreviation, meaning in _normalize_registry_pairs(abbr_value, meaning_value)
    }


def _normalize_prefix(original_prefix: str) -> AxlPrefix:
    if original_prefix not in CANONICAL_PREFIXES:
        raise AxlParseError(f"Unsupported AXL prefix `{original_prefix}`.")
    return cast("AxlPrefix", original_prefix)


def _assign_single_field(
    fields: dict[str, Any],
    key: str,
    value: Any,
    *,
    allow_parser_reserved: bool = False,
) -> None:
    """Assign a scalar header field, rejecting ambiguous duplicate keys."""

    normalized_key = key.strip()
    if not normalized_key:
        raise AxlParseError("AXL header field names cannot be empty.")
    if not allow_parser_reserved and normalized_key in _PARSER_RESERVED_FIELD_NAMES:
        raise AxlParseError(
            f"AXL header field `{normalized_key}` is reserved for parser structure."
        )
    if normalized_key in fields:
        raise AxlParseError(f"AXL header field `{normalized_key}` must appear at most once.")
    fields[normalized_key] = value


# ── Main parser ───────────────────────────────────────────────────────


def parse_axl_message(
    raw_message: str,
    *,
    strict: bool = False,
) -> AxlMessage:
    """Parse a raw AXL message into a canonical v2.0 model."""

    if len(raw_message) > MAX_AXL_MESSAGE_BYTES:
        raise AxlParseError(f"AXL message exceeds maximum size of {MAX_AXL_MESSAGE_BYTES} bytes.")
    raw = raw_message.strip()
    if not raw:
        raise AxlParseError("AXL message cannot be empty.")

    lines = raw.splitlines()
    header = lines[0]
    if ":" not in header:
        raise AxlParseError("AXL header must include a `PREFIX:` segment.")

    if len(lines) - 1 > MAX_AXL_PAYLOAD_LINES:
        raise AxlParseError(f"AXL payload exceeds maximum of {MAX_AXL_PAYLOAD_LINES} lines.")

    original_prefix, remainder = header.split(":", 1)
    original_prefix = original_prefix.strip().upper()
    prefix = _normalize_prefix(original_prefix)

    fields: dict[str, Any] = {}
    typed_items: list[str] = []
    header_items = _split_header_items(remainder)
    if len(header_items) > MAX_AXL_HEADER_ITEMS:
        raise AxlParseError(f"AXL header exceeds maximum of {MAX_AXL_HEADER_ITEMS} items.")
    for item in header_items:
        eq_index, sequence_index, cause_index = _find_top_level_tokens(item)

        if item == "ok":
            _assign_single_field(fields, "st", "done")
            continue
        if item == "fail":
            _assign_single_field(fields, "st", "fail")
            continue
        if item.startswith("{") and item.endswith("}"):
            # v2.0: content stored as plain string
            _assign_single_field(fields, "content", item[1:-1])
            continue
        if sequence_index >= 0 and (eq_index < 0 or sequence_index < eq_index):
            steps = [s.strip() for s in _SEQ_RE.split(item)]
            if any(not step for step in steps):
                raise AxlParseError("AXL sequence entries cannot be empty.")
            fields.setdefault("sequence", []).extend(steps)
            continue
        if cause_index >= 0 and (eq_index < 0 or cause_index < eq_index):
            parts = [s.strip() for s in _CAUSE_RE.split(item, maxsplit=1)]
            if len(parts) != 2 or not parts[0] or not parts[1]:
                raise AxlParseError("AXL cause expressions must include effect and source.")
            _assign_single_field(
                fields,
                "cause",
                {"effect": parts[0], "source": parts[1]},
                allow_parser_reserved=True,
            )
            continue
        if item.startswith(">") or item.startswith("?"):
            fields.setdefault("directives", []).append(item)
            continue
        if eq_index >= 0:
            key, value = item[:eq_index], item[eq_index + 1 :]
            _assign_single_field(fields, key, _parse_value(value))
            continue
        if "::" in item:
            typed_items.append(item)
            continue
        # Ref glyphs: @, #, ^, &
        if item and item[0] in _REF_GLYPHS:
            ref_type = _REF_GLYPHS[item[0]]
            fields.setdefault("refs", []).append({"type": ref_type, "value": item[1:]})
            continue
        fields.setdefault("atoms", []).append(item)

    if typed_items:
        fields["typed"] = typed_items

    if _requires_id(prefix, fields) and "id" not in fields:
        raise AxlParseError(
            "AXL messages must include `id` unless the prefix allows fire-and-forget "
            "usage or the message is an RX stream continuation / compact result with `ref`."
        )

    payload: dict[str, Any] = {}
    for line in lines[1:]:
        if len(line) > MAX_AXL_PAYLOAD_LINE_BYTES:
            raise AxlParseError(
                f"AXL payload line exceeds maximum of {MAX_AXL_PAYLOAD_LINE_BYTES} bytes."
            )
        if not line.startswith("  "):
            raise AxlParseError("AXL payload lines must be indented by two spaces.")
        entry = line.strip()
        if "=" in entry:
            key, value = entry.split("=", 1)
            payload_key = key.strip()
            if not payload_key:
                raise AxlParseError("AXL payload field names cannot be empty.")
            if payload_key in _PARSER_RESERVED_PAYLOAD_KEYS:
                raise AxlParseError(
                    f"AXL payload field `{payload_key}` is reserved for parser structure."
                )
            if payload_key in payload:
                raise AxlParseError(f"AXL payload field `{payload_key}` must appear at most once.")
            payload[payload_key] = _parse_value(value)
        else:
            payload.setdefault("lines", []).append(entry)

    _validate_enum_fields(fields, strict=strict)
    _warn_channel_prefix_alignment(prefix, fields, strict=strict)
    _validate_prefix_requirements(prefix, fields, strict=strict)
    _validate_recipient_fields(prefix, fields, strict=strict)
    _validate_structured_fields(prefix, fields, payload, strict=strict)
    _validate_registry_fields(prefix, fields, payload)
    _warn_prefix_guidance(prefix, fields, strict=strict)
    _warn_field_compatibility(prefix, fields, strict=strict)
    _warn_ts_format(fields, strict=strict)
    _warn_ddl_format(fields, strict=strict)

    return AxlMessage(
        prefix=prefix,
        fields=fields,
        payload=payload,
        raw=raw,
    )


# ── Validation helpers ────────────────────────────────────────────────


def _validate_enum_fields(fields: dict[str, Any], *, strict: bool) -> None:
    """Warn on invalid enum field values. Logs warnings rather than raising."""
    for field_name, allowed in ENUM_CONSTRAINTS.items():
        if field_name in fields and str(fields[field_name]) not in allowed:
            message = (
                f"AXL field `{field_name}` should be one of {sorted(allowed)}, got "
                f"`{fields[field_name]}`."
            )
            if strict:
                raise AxlParseError(message)
            logger.warning(message)


def _warn_channel_prefix_alignment(
    prefix: str,
    fields: dict[str, Any],
    *,
    strict: bool,
) -> None:
    """Warn when a message prefix is routed through an incompatible channel."""

    channel = str(fields.get("chan") or "").strip().lower()
    if not channel:
        return

    message = ""
    if prefix == "PS" and channel != "social":
        message = "PS messages must use `chan=social`; use TX/RX/ST for direct workflow traffic."
    elif channel == "social" and prefix not in {"PS", "RX"}:
        message = "Only PS messages and RX social answers may use `chan=social`."

    if not message:
        return
    if strict:
        raise AxlParseError(message)
    logger.warning(message)


def _validate_prefix_requirements(
    prefix: str,
    fields: dict[str, Any],
    *,
    strict: bool,
) -> None:
    """Enforce documented required fields for specific prefixes."""
    directives = [str(item) for item in fields.get("directives", [])]

    if prefix == "TX" and not any(
        item.startswith(">") or item.startswith("?") for item in directives
    ):
        raise AxlParseError("TX messages must include at least one `>` or `?` directive.")

    ps_kind = str(fields.get("kind") or "reply").lower()
    if prefix == "PS" and ps_kind in _PS_REF_REQUIRED_KINDS and "ref" not in fields:
        raise AxlParseError(f"PS messages with `kind={ps_kind}` must include `ref`.")

    if prefix == "RX" and str(fields.get("chan") or "").lower() == "social" and "ref" not in fields:
        raise AxlParseError("Social RX messages must include `ref`.")

    typed_items = [str(item) for item in fields.get("typed", [])]
    if prefix == "ER" and not any(item.startswith("err::") for item in typed_items):
        raise AxlParseError("ER messages must include a typed error label like `err::timeout`.")

    if (
        prefix == "EV"
        and str(fields.get("out") or "").lower() == "conditional"
        and "cond" not in fields
    ):
        raise AxlParseError("EV messages with `out=conditional` must include `cond=...`.")
    if (
        prefix == "PS"
        and str(fields.get("kind") or "").lower() == "review"
        and str(fields.get("out") or "").lower() == "conditional"
        and "cond" not in fields
    ):
        raise AxlParseError("PS review messages with `out=conditional` must include `cond=...`.")

    if prefix == "PS" and str(fields.get("kind") or "").lower() == "poll":
        opts_value = fields.get("opts")
        if "opts" not in fields:
            raise AxlParseError("Poll messages (PS kind=poll) must include `opts=[...]`.")
        if isinstance(opts_value, list) and not opts_value:
            raise AxlParseError("Poll messages (PS kind=poll) must include at least one option.")


def _recipient_values(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(value)]


def _validate_recipient_fields(
    prefix: str,
    fields: dict[str, Any],
    *,
    strict: bool,
) -> None:
    """Validate canonical recipient references used for routing and escalation."""

    recipient_fields = ("to", "from", "esc")
    for field_name in recipient_fields:
        if field_name not in fields:
            continue

        values = _recipient_values(fields[field_name])
        if not values:
            message = f"AXL field `{field_name}` must include at least one recipient."
        elif field_name != "to" and len(values) > 1:
            message = f"AXL field `{field_name}` must contain exactly one recipient."
        else:
            invalid_values = [value for value in values if not _RECIPIENT_REF_RE.match(value)]
            message = (
                f"AXL field `{field_name}` must use canonical `@recipient` atoms."
                if invalid_values
                else ""
            )

        if not message:
            continue
        if strict:
            raise AxlParseError(message)
        logger.warning(message)

    if "to" in fields:
        values = _recipient_values(fields["to"])
        if len(values) != len(set(values)):
            message = "AXL field `to` must not contain duplicate recipients."
            if strict:
                raise AxlParseError(message)
            logger.warning(message)


def _validate_structured_fields(
    prefix: str,
    fields: dict[str, Any],
    payload: dict[str, Any],
    *,
    strict: bool,
) -> None:
    # v2.1: strict mode does not alter canonical parsing constraints; this function
    # already fails hard for malformed payload structures.
    _ = strict
    """Validate cross-field structure for v2 features that should fail loudly."""

    if "pct" in fields:
        pct = fields["pct"]
        if not isinstance(pct, int):
            raise AxlParseError("AXL field `pct` must be an integer percentage.")
        if pct < 0 or pct > 100:
            raise AxlParseError("AXL field `pct` must be between 0 and 100.")

    if "seq" in fields:
        seq = fields["seq"]
        if not isinstance(seq, int):
            raise AxlParseError("AXL field `seq` must be an integer.")
        if seq < 0:
            raise AxlParseError("AXL field `seq` must be >= 0.")

    if "score" in fields:
        score = fields["score"]
        if isinstance(score, bool) or not isinstance(score, int | float):
            raise AxlParseError("AXL field `score` must be numeric.")

    stream = str(fields.get("stream") or "").lower()
    if prefix != "RX" and ("stream" in fields or "seq" in fields):
        raise AxlParseError("Only RX messages may use `stream` / `seq`.")
    if prefix == "RX" and "seq" in fields and "stream" not in fields:
        raise AxlParseError("RX messages with `seq` must also include `stream=...`.")
    if prefix == "RX" and stream in _STREAM_CONTINUATION_VALUES:
        if "ref" not in fields:
            raise AxlParseError(
                "RX stream continuation messages (`data`/`end`/`error`) must include `ref`."
            )
        if "seq" not in fields:
            raise AxlParseError(
                "RX stream continuation messages (`data`/`end`/`error`) must include `seq`."
            )

    mode = str(fields.get("mode") or "").lower()
    if "part" in fields or "more" in fields:
        raise AxlParseError(
            "AXL fields `part` / `more` are no longer supported. Use `stream` / `seq`."
        )
    if ("caps" in fields or "caps" in payload) and not (prefix == "SY" and mode == "caps"):
        raise AxlParseError("AXL field `caps` is only valid on `SY: mode=caps`.")
    if any(name in fields or name in payload for name in ("abbr", "meaning")) and not (
        prefix == "SY" and mode == "registry"
    ):
        raise AxlParseError("AXL fields `abbr` / `meaning` are only valid on `SY: mode=registry`.")
    if prefix == "SY" and mode == "delta":
        _validate_delta_fields(fields, payload)
    elif any(
        name in fields or name in payload
        for name in ("operations", "expected_revision_no", "base_revision")
    ):
        raise AxlParseError(
            "AXL delta fields `operations` / `expected_revision_no` are only valid on "
            "`SY: mode=delta`."
        )


def _validate_delta_fields(fields: dict[str, Any], payload: dict[str, Any]) -> None:
    operations = fields.get("operations", payload.get("operations"))
    if operations is None:
        raise AxlParseError("SY mode=delta messages must include `operations`.")
    parsed_operations = _coerce_delta_operations(operations)
    for operation in parsed_operations:
        _validate_delta_operation(operation)
    revision_value = fields.get(
        "expected_revision_no",
        fields.get(
            "base_revision",
            payload.get("expected_revision_no", payload.get("base_revision")),
        ),
    )
    if revision_value is not None and not isinstance(revision_value, int):
        raise AxlParseError("AXL delta `expected_revision_no` must be an integer.")


def _coerce_delta_operations(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        if len(value) > MAX_AXL_DELTA_OPERATIONS_BYTES:
            raise AxlParseError(
                f"AXL delta `operations` exceeds maximum size of "
                f"{MAX_AXL_DELTA_OPERATIONS_BYTES} bytes."
            )
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise AxlParseError("AXL delta `operations` must be valid JSON.") from exc
    if not isinstance(value, list) or not value:
        raise AxlParseError("AXL delta `operations` must be a non-empty JSON list.")
    if len(value) > MAX_AXL_DELTA_OPERATIONS:
        raise AxlParseError(
            f"AXL delta `operations` exceeds maximum of {MAX_AXL_DELTA_OPERATIONS} entries."
        )
    operations: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise AxlParseError("AXL delta operation entries must be JSON objects.")
        operations.append(item)
    return operations


def _validate_delta_operation(operation: dict[str, Any]) -> None:
    op_raw = operation.get("op")
    if not isinstance(op_raw, str):
        raise AxlParseError("AXL delta operation `op` must be a string.")
    op = op_raw.strip()
    if op not in _DELTA_OPERATION_OPS:
        raise AxlParseError(
            "AXL delta operation `op` must be one of "
            f"{sorted(_DELTA_OPERATION_OPS)}, got `{op or '<empty>'}`."
        )
    path_raw = operation.get("path")
    if not isinstance(path_raw, str):
        raise AxlParseError("AXL delta operation `path` must be a string JSON pointer.")
    path = path_raw.strip()
    if not _is_json_pointer(path):
        raise AxlParseError("AXL delta operation `path` must be a JSON pointer.")
    if op in {"set", "append", "replace"} and "value" not in operation:
        raise AxlParseError(f"AXL delta operation `{op}` requires `value`.")
    if op == "move":
        from_raw = operation.get("from")
        if not isinstance(from_raw, str) or not _is_json_pointer(from_raw.strip()):
            raise AxlParseError("AXL delta operation `move` requires JSON-pointer `from`.")


def _is_json_pointer(path: str) -> bool:
    if not path.startswith("/"):
        return False
    if len(path) > MAX_AXL_DELTA_POINTER_BYTES:
        return False
    index = 0
    while index < len(path):
        if path[index] == "~":
            if index + 1 >= len(path) or path[index + 1] not in {"0", "1"}:
                return False
            index += 2
            continue
        index += 1
    return True


def _validate_registry_fields(
    prefix: str,
    fields: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    """Validate optional abbreviation registry declarations."""
    if prefix != "SY" or str(fields.get("mode", "")).lower() != "registry":
        return
    abbr_value = fields.get("abbr", payload.get("abbr"))
    meaning_value = fields.get("meaning", payload.get("meaning"))
    _normalize_registry_pairs(abbr_value, meaning_value)


def _warn_prefix_guidance(
    prefix: str,
    fields: dict[str, Any],
    *,
    strict: bool,
) -> None:
    """Log non-fatal guidance when a message is valid but non-canonical."""

    effective_channel = str(
        fields.get("chan") or PREFIX_DEFAULTS.get(prefix, {}).get("chan") or ""
    ).lower()
    if prefix == "TX" and effective_channel == "dm" and "to" not in fields:
        message = "Direct TX messages must include `to` so the recipient is unambiguous."
        if strict:
            raise AxlParseError(message)
        logger.warning(message)
    if (
        prefix == "ST"
        and fields.get("st") in {"wait", "blk", "cxl", "fail", "rj"}
        and "why" not in fields
    ):
        message = f"ST messages with `st={fields['st']}` should include `why`."
        if strict:
            raise AxlParseError(message)
        logger.warning(message)
    if prefix in {"EV"} and "ref" not in fields:
        message = "EV messages should include `ref` for canonical linking."
        if strict:
            raise AxlParseError(message)
        logger.warning(message)
    if prefix == "PS" and str(fields.get("kind") or "").lower() == "review" and "ref" not in fields:
        message = "PS review posts should include `ref` for canonical linking."
        if strict:
            raise AxlParseError(message)
        logger.warning(message)


def _warn_field_compatibility(
    prefix: str,
    fields: dict[str, Any],
    *,
    strict: bool,
) -> None:
    """Log guidance when fields appear on non-canonical prefixes."""

    for field_name, valid_prefixes in _FIELD_PREFIX_GUIDANCE.items():
        if field_name not in fields:
            continue
        if prefix == "RX" and str(fields.get("chan") or "").lower() == "social":
            if field_name in _SOCIAL_RX_FIELD_COMPATIBILITY:
                continue
        elif field_name == "sub" and prefix == "RX":
            continue
        if prefix not in valid_prefixes:
            message = (
                f"AXL field `{field_name}` is non-canonical on `{prefix}`; "
                f"expected one of {sorted(valid_prefixes)}."
            )
            if strict:
                raise AxlParseError(message)
            logger.warning(message)


def _is_valid_iso8601_deadline(value: str) -> bool:
    """Return whether *value* is a supported ISO 8601 date or timestamp."""

    candidate = value.strip()
    if not candidate:
        return False
    try:
        if "T" not in candidate and "t" not in candidate:
            date.fromisoformat(candidate)
            return True
        normalized = candidate[:-1] + "+00:00" if candidate.endswith("Z") else candidate
        datetime.fromisoformat(normalized)
        return True
    except ValueError:
        return False


def _is_valid_iso8601_timestamp(value: str) -> bool:
    """Return whether *value* is a supported ISO 8601 timestamp."""

    candidate = value.strip()
    if not candidate or ("T" not in candidate and "t" not in candidate):
        return False
    try:
        normalized = candidate[:-1] + "+00:00" if candidate.endswith("Z") else candidate
        datetime.fromisoformat(normalized)
        return True
    except ValueError:
        return False


def _warn_ddl_format(fields: dict[str, Any], *, strict: bool) -> None:
    """Warn if deadline format is invalid."""
    ddl = fields.get("ddl")
    if ddl is not None and isinstance(ddl, str) and not _is_valid_iso8601_deadline(ddl):
        message = f"AXL field `ddl` should be YYYY-MM-DD or ISO 8601 timestamp, got `{ddl}`."
        if strict:
            raise AxlParseError(message)
        logger.warning(message)


def _warn_ts_format(fields: dict[str, Any], *, strict: bool) -> None:
    """Warn if timestamp format is invalid."""

    ts = fields.get("ts")
    if ts is not None and isinstance(ts, str) and not _is_valid_iso8601_timestamp(ts):
        message = f"AXL field `ts` should be an ISO 8601 timestamp, got `{ts}`."
        if strict:
            raise AxlParseError(message)
        logger.warning(message)


# ── Normalization / serialization ─────────────────────────────────────


def _field_sort_key(field_name: str) -> tuple[int, str]:
    return (_CANONICAL_FIELD_ORDER_INDEX.get(field_name, len(CANONICAL_FIELD_ORDER)), field_name)


def _contains_structured_object(value: Any) -> bool:
    """Return whether an AXL value needs JSON string serialization."""

    if isinstance(value, dict):
        return "_group" not in value
    if isinstance(value, list):
        return any(_contains_structured_object(item) for item in value)
    return False


def _serialize_json_value(value: Any) -> str:
    """Serialize nested payload data as deterministic JSON inside a quoted value."""

    text = json.dumps(
        value,
        default=str,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    escaped = _escape_quoted_value(text)
    return f'"{escaped}"'


def _serialize_value(value: Any) -> str:
    if _contains_structured_object(value):
        return _serialize_json_value(value)
    if isinstance(value, dict) and "_group" in value:
        return "(" + ", ".join(_serialize_value(item) for item in value["_group"]) + ")"
    if isinstance(value, list):
        return "[" + ", ".join(_serialize_value(item) for item in value) + "]"
    if isinstance(value, str):
        if not value:
            return '""'
        if re.search(r"[\s;,\[\]\{\}\(\)\\]", value):
            escaped = _escape_quoted_value(value)
            return f'"{escaped}"'
        return value
    return str(value)


# Characters that would cause a positionally-emitted value (directive,
# sequence step, cause effect/source, ref value, atom, typed item) to be
# re-classified by the header parser, smuggling new fields onto the wire.
# These positions have no quoting form in the grammar, so we refuse to
# normalize values that would split on re-parse.
_REPARSE_INJECTION_SEPARATORS = (";", "\n", "\r", "->", "<-")


def _assert_no_reparse_injection(value: str, *, kind: str) -> str:
    """Raise if ``value`` contains separators that would inject new header items."""

    for token in _REPARSE_INJECTION_SEPARATORS:
        if token in value:
            raise AxlParseError(
                f"AXL {kind} value contains reserved separator `{token}` that would "
                "inject additional header items on re-parse."
            )
    return value


def _escape_quoted_value(value: str) -> str:
    """Escape text for a single-line quoted AXL assignment value."""

    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )


def _unescape_quoted_value(value: str) -> str:
    """Decode the quoted-value escapes emitted by ``_escape_quoted_value``."""

    decoded: list[str] = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch != "\\" or i + 1 >= len(value):
            decoded.append(ch)
            i += 1
            continue

        nxt = value[i + 1]
        if nxt == "n":
            decoded.append("\n")
        elif nxt == "r":
            decoded.append("\r")
        elif nxt == "t":
            decoded.append("\t")
        elif nxt in {'"', "\\"}:
            decoded.append(nxt)
        else:
            decoded.append("\\")
            decoded.append(nxt)
        i += 2
    return "".join(decoded)


def _requires_id(prefix: str, fields: dict[str, Any]) -> bool:
    """Return whether the current message shape requires an explicit wire id."""

    if prefix in _ID_OPTIONAL_PREFIXES:
        return False
    if prefix == "PS":
        return str(fields.get("kind") or "reply").lower() not in _PS_ID_OPTIONAL_KINDS
    if prefix == "RX":
        stream = str(fields.get("stream") or "").lower()
        if stream in _STREAM_CONTINUATION_VALUES and "ref" in fields:
            return False
        status = str(fields.get("st") or "").lower()
        if status in _RX_ID_OPTIONAL_STATUSES and "ref" in fields:
            return False
    return True


def _serialize_content(value: Any) -> str:
    """Serialize a content field value, wrapping in braces."""
    if isinstance(value, str):
        return "{" + value + "}"
    return "{" + str(value) + "}"


def _content_can_use_brace_block(value: Any) -> bool:
    """Return whether ``value`` can be encoded safely as a ``{...}`` block."""

    text = value if isinstance(value, str) else str(value)
    if "\n" in text or "\r" in text:
        return False
    try:
        _ensure_balanced_delimiters("{" + text + "}", context="AXL content block")
    except AxlParseError:
        return False
    return True


def normalize_axl_message(message: AxlMessage) -> str:
    """Return a canonical v2.0 wire representation for an AXL message."""

    prefix = message.prefix
    defaults = PREFIX_DEFAULTS.get(prefix, {})
    content_value = message.fields.get("content")
    content_as_field = content_value is not None and not _content_can_use_brace_block(content_value)

    skip = {"atoms", "typed", "sequence", "cause", "directives", "refs"}
    if not content_as_field:
        skip.add("content")
    parts: list[str] = []
    for key in sorted(
        (k for k in message.fields if k not in skip),
        key=_field_sort_key,
    ):
        value = message.fields[key]
        # Omit fields that match prefix defaults
        if key in defaults and str(value) == defaults[key]:
            continue
        parts.append(f"{key}={_serialize_value(value)}")
    for directive in message.fields.get("directives", []):
        parts.append(_assert_no_reparse_injection(str(directive), kind="directive"))
    if "sequence" in message.fields:
        steps = [
            _assert_no_reparse_injection(str(s), kind="sequence step")
            for s in message.fields["sequence"]
        ]
        parts.append(" -> ".join(steps))
    if "cause" in message.fields:
        cause = message.fields["cause"]
        effect = _assert_no_reparse_injection(str(cause["effect"]), kind="cause effect")
        source = _assert_no_reparse_injection(str(cause["source"]), kind="cause source")
        parts.append(f"{effect} <- {source}")
    for ref in message.fields.get("refs", []):
        glyph = next((g for g, t in _REF_GLYPHS.items() if t == ref["type"]), "")
        parts.append(_assert_no_reparse_injection(f"{glyph}{ref['value']}", kind="ref"))
    for atom in message.fields.get("atoms", []):
        parts.append(_assert_no_reparse_injection(str(atom), kind="atom"))
    for typed_item in message.fields.get("typed", []):
        parts.append(_assert_no_reparse_injection(str(typed_item), kind="typed item"))
    if content_value is not None and not content_as_field:
        parts.append(_serialize_content(content_value))

    header = f"{prefix}: {'; '.join(parts)}".rstrip()
    if not message.payload:
        return header

    payload_lines: list[str] = []
    for key, value in message.payload.items():
        if key == "lines":
            payload_lines.extend(f"  {line}" for line in value)
        else:
            payload_lines.append(f"  {key}={_serialize_value(value)}")
    return "\n".join([header, *payload_lines])


def build_axl_message(
    prefix: str,
    *,
    fields: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    directives: list[str] | None = None,
    strict: bool = False,
) -> str:
    """Build and validate a canonical AXL wire message safely."""

    canonical_prefix = _normalize_prefix(str(prefix or "").strip().upper())
    if directives and fields and "directives" in fields:
        raise AxlParseError(
            "Pass directives via the `directives=` argument or `fields['directives']`, not both; "
            "supplying both would silently drop the value in `fields`."
        )
    message = AxlMessage(
        prefix=canonical_prefix,
        fields={**(fields or {}), **({"directives": list(directives)} if directives else {})},
        payload=dict(payload or {}),
        raw="",
    )
    canonical_message = normalize_axl_message(message)
    reparsed = parse_axl_message(canonical_message, strict=strict)
    return normalize_axl_message(reparsed)


def compose_axl_message(
    prefix: str,
    *,
    fields: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    directives: list[str] | None = None,
    strict: bool = False,
) -> str:
    """Canonical alias kept for orchestration call sites and future extension."""

    return build_axl_message(
        prefix,
        fields=fields,
        payload=payload,
        directives=directives,
        strict=strict,
    )


def _capped_set(mapping: dict[str, Any], key: str, value: Any, *, limit: int) -> None:
    mapping[key] = value
    while len(mapping) > limit:
        mapping.pop(next(iter(mapping)))


def _normalize_channel(channel: str) -> AxlChannel:
    normalized = str(channel or "").strip().lower()
    if normalized not in _VALID_CHANNELS:
        raise AxlParseError(f"Unsupported AXL channel `{channel}`.")
    return cast("AxlChannel", normalized)


def _normalize_recipient_ref(value: Any) -> str:
    """Return a canonical single recipient ref for transport lookups."""

    raw = str(value or "").strip()
    if raw and not raw.startswith("@"):
        raw = f"@{raw}"
    if not _RECIPIENT_REF_RE.match(raw):
        raise AxlParseError("Recipient lookup must use a canonical `@recipient` atom.")
    return raw


# ── Transport ─────────────────────────────────────────────────────────


class AxlTransport:
    """In-process AXL router used by communication tools and workflow runtime."""

    def __init__(self) -> None:
        self._strict_default = False
        self._messages: dict[str, deque[AxlEnvelope]] = defaultdict(
            lambda: deque(maxlen=TRANSPORT_MESSAGE_HISTORY_LIMIT)
        )
        self._abbreviation_registries: dict[str, dict[str, str]] = defaultdict(dict)
        # v2.0: state machine tracking (warning-only)
        self._state_map: dict[str, str] = {}
        self._state_aliases: dict[str, str] = {}
        self._retry_allowed: dict[str, bool] = {}

    def _resolve_state_target(self, task_id: str) -> str:
        """Resolve stream/result aliases to the root task id when known."""

        resolved = task_id
        seen: set[str] = set()
        while resolved and resolved not in seen and resolved in self._state_aliases:
            seen.add(resolved)
            resolved = self._state_aliases[resolved]
        return resolved

    def _record_reference_alias(self, message: AxlMessage) -> None:
        """Link result/status/review ids back to the root task they reference."""

        result_id = str(message.fields.get("id") or "").strip()
        ref = str(message.fields.get("ref") or "").strip()
        if not result_id or not ref or message.prefix == "TX":
            return
        _capped_set(
            self._state_aliases,
            result_id,
            self._resolve_state_target(ref),
            limit=TRANSPORT_STATE_MAP_LIMIT,
        )

    def _task_id_for_message(self, message: AxlMessage) -> str:
        """Return the task id that should receive lifecycle updates."""

        if message.prefix == "TX":
            message_id = str(message.fields.get("id") or "").strip()
            if message_id:
                return self._resolve_state_target(message_id)

        ref = str(message.fields.get("ref") or "").strip()
        if ref:
            return self._resolve_state_target(ref)
        message_id = str(message.fields.get("id") or "").strip()
        if message_id:
            return self._resolve_state_target(message_id)
        return ""

    def _status_for_message(self, message: AxlMessage) -> str | None:
        """Return the effective lifecycle state represented by this message."""

        explicit = message.fields.get("st")
        if explicit is not None:
            return str(explicit).lower()
        if message.prefix == "TX":
            return "new"
        if message.prefix == "ER":
            return "fail"
        return None

    def _record_retry_policy(
        self,
        task_id: str,
        message: AxlMessage,
        *,
        status: str | None = None,
    ) -> None:
        """Track whether a failed task is allowed to re-enter `run`."""

        if not task_id:
            return
        retry_default = PREFIX_DEFAULTS.get(message.prefix, {}).get("retry", "")
        retry_value = str(
            message.fields.get("retry", message.payload.get("retry", retry_default)) or ""
        ).lower()
        status_value = str(status or self._status_for_message(message) or "").lower()
        if retry_value in {"yes", "cond"} and status_value in {"fail"}:
            _capped_set(self._retry_allowed, task_id, True, limit=TRANSPORT_STATE_MAP_LIMIT)
        elif retry_value == "no" or status_value in {"done", "cxl"}:
            _capped_set(self._retry_allowed, task_id, False, limit=TRANSPORT_STATE_MAP_LIMIT)

    def _sync_message_channel(self, channel: str, message: AxlMessage) -> None:
        """Align the message `chan` field with the actual routed transport channel."""

        routed_channel = str(channel or "").strip().lower()
        message_channel = str(message.fields.get("chan") or "").strip().lower()
        if message_channel and message_channel != routed_channel:
            logger.warning(
                "AXL message chan=`%s` routed on `%s`; normalizing to the transport channel.",
                message_channel,
                routed_channel,
            )

        default_channel = (
            str(PREFIX_DEFAULTS.get(message.prefix, {}).get("chan") or "").strip().lower()
        )
        if routed_channel and routed_channel != default_channel:
            message.fields["chan"] = routed_channel
        elif "chan" in message.fields:
            message.fields.pop("chan", None)

    def _registry_scopes(
        self,
        *,
        channel: str,
        message: AxlMessage,
        metadata: dict[str, Any],
    ) -> list[str]:
        scopes: list[str] = []

        explicit_scope = str(
            metadata.get("registry_scope")
            or message.payload.get("scope")
            or message.fields.get("tgt")
            or ""
        ).strip()
        if explicit_scope:
            scopes.append(explicit_scope)

        project_id = str(metadata.get("project_id") or "").strip()
        if project_id:
            scopes.append(f"project:{project_id}")

        sender = str(metadata.get("sender") or "").strip()
        target = str(metadata.get("target") or "").strip()
        if channel == "dm" and sender and target:
            scopes.append(f"dm:{sender}->{target}")

        scopes.append(f"channel:{channel}")

        deduped: list[str] = []
        seen: set[str] = set()
        for scope in scopes:
            lowered = scope.casefold()
            if lowered in seen:
                continue
            seen.add(lowered)
            deduped.append(scope)
        return deduped

    def _record_registry_entries(
        self,
        *,
        channel: str,
        message: AxlMessage,
        metadata: dict[str, Any],
    ) -> None:
        registry = extract_abbreviation_registry(message)
        if not registry:
            return
        for scope in self._registry_scopes(channel=channel, message=message, metadata=metadata):
            if (
                scope not in self._abbreviation_registries
                and len(self._abbreviation_registries) >= TRANSPORT_REGISTRY_SCOPE_LIMIT
            ):
                self._abbreviation_registries.pop(next(iter(self._abbreviation_registries)))
            self._abbreviation_registries[scope].update(registry)

    def _validate_state_transition(
        self,
        message: AxlMessage,
        *,
        strict: bool | None = None,
    ) -> None:
        """Warn on invalid state transitions (warning-only enforcement)."""
        strict_mode = self._strict_default if strict is None else strict
        task_id = self._task_id_for_message(message)
        st = self._status_for_message(message)
        if st is None:
            return

        st_str = str(st).lower()
        if task_id:
            self._record_retry_policy(task_id, message, status=st_str)

        if st_str not in _VALID_STATUS_VALUES:
            warning_text = (
                f"Unknown lifecycle state `{st_str}` for task `{task_id or '(unknown)'}`; "
                "preserving tracked state."
            )
            if strict_mode:
                raise AxlParseError(warning_text)
            logger.warning(warning_text)
            return
        if not task_id:
            return

        current = self._state_map.get(task_id)
        if current is None:
            # First status for this task
            _capped_set(self._state_map, task_id, st_str, limit=TRANSPORT_STATE_MAP_LIMIT)
            return
        if current not in _VALID_STATUS_VALUES:
            warning_text = (
                f"Tracked lifecycle state `{current}` for task `{task_id}` is unknown; "
                f"resetting to `{st_str}`."
            )
            if strict_mode:
                raise AxlParseError(warning_text)
            logger.warning(warning_text)
            _capped_set(self._state_map, task_id, st_str, limit=TRANSPORT_STATE_MAP_LIMIT)
            return

        valid_next = _VALID_TRANSITIONS.get(current, set())
        retry_allowed = self._retry_allowed.get(task_id, False)
        invalid_transition = False
        if current == "fail" and st_str == "run" and not retry_allowed:
            warning_text = (
                f"Invalid state transition for task `{task_id}`: `{current}` -> `{st_str}`. "
                "A retryable failure must set `retry=yes|cond` before re-entering `run`."
            )
            if strict_mode:
                raise AxlParseError(warning_text)
            logger.warning(warning_text)
            invalid_transition = True
        elif st_str not in valid_next and st_str != current:
            warning_text = (
                f"Invalid state transition for task `{task_id}`: `{current}` -> `{st_str}`. "
                f"Valid transitions from `{current}`: "
                f"{sorted(valid_next) if valid_next else '(terminal)'}"
            )
            if strict_mode:
                raise AxlParseError(warning_text)
            logger.warning(warning_text)
            invalid_transition = True

        if invalid_transition:
            return

        if current == "fail" and st_str == "run" and retry_allowed:
            _capped_set(self._retry_allowed, task_id, False, limit=TRANSPORT_STATE_MAP_LIMIT)
        _capped_set(self._state_map, task_id, st_str, limit=TRANSPORT_STATE_MAP_LIMIT)

    def route(
        self,
        *,
        channel: str,
        message: AxlMessage,
        metadata: dict[str, Any] | None = None,
        strict: bool | None = None,
    ) -> AxlEnvelope:
        resolved_channel = _normalize_channel(channel)
        self._sync_message_channel(resolved_channel, message)
        strict_mode = self._strict_default if strict is None else strict
        validated_message = parse_axl_message(normalize_axl_message(message), strict=strict_mode)
        message.fields = validated_message.fields
        message.payload = validated_message.payload
        message.raw = validated_message.raw
        self._validate_state_transition(message, strict=strict_mode)
        self._record_registry_entries(
            channel=resolved_channel,
            message=message,
            metadata=metadata or {},
        )
        self._record_reference_alias(message)
        message.raw = normalize_axl_message(message)
        envelope = AxlEnvelope(channel=resolved_channel, message=message)
        self._messages[resolved_channel].append(envelope)
        return envelope

    def list_messages(self, channel: str | None = None) -> list[AxlEnvelope]:
        if channel is None:
            return [message for messages in self._messages.values() for message in messages]
        return list(self._messages[_normalize_channel(channel)])

    def list_messages_for(
        self,
        recipient: str,
        channel: str | None = None,
        *,
        include_unaddressed: bool = False,
    ) -> list[AxlEnvelope]:
        """Return routed messages addressed to a recipient."""

        recipient_ref = _normalize_recipient_ref(recipient)
        addressed: list[AxlEnvelope] = []
        for envelope in self.list_messages(channel):
            recipients = _recipient_values(envelope.message.fields.get("to"))
            if recipient_ref in recipients or (include_unaddressed and not recipients):
                addressed.append(envelope)
        return addressed

    def get_abbreviation_registry(self, scope: str | None = None) -> Any:
        """Return a registry snapshot for one scope or all scopes."""

        if scope is not None:
            return dict(self._abbreviation_registries.get(scope, {}))
        return {
            registry_scope: dict(entries)
            for registry_scope, entries in self._abbreviation_registries.items()
        }

    def get_task_state(self, task_id: str) -> str | None:
        """Return the current state for a tracked task, or None."""
        resolved = self._resolve_state_target(task_id)
        return self._state_map.get(resolved) or self._state_map.get(task_id)
