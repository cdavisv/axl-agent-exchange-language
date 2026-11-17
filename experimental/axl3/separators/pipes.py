"""Explicit pipe-separated AXL profile and opt-in deterministic syntax repair.
No baseline grammar change. Never infers missing values or user intent.
"""

import hashlib, sys
from pathlib import Path
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "surface"))
from surface import bound, values, MISSING, encode as old_encode, decode as old_decode, ACTS
from axl3 import Error, dump, load, registry


def split_top_level_pipes(text):
    bound(text)
    parts = []
    start = 0
    depth = 0
    quoted = False
    escape = False
    for i, ch in enumerate(text):
        if quoted:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                quoted = False
        elif ch == '"':
            quoted = True
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        elif ch == "|" and depth == 0:
            # Require exact visible separator spaces, never reinterpret adjacent tokens.
            if i == 0 or i + 1 == len(text) or text[i - 1] != " " or text[i + 1] != " ":
                raise Error("Separator spacing")
            part = text[start : i - 1]
            if not part or part.endswith(" "):
                raise Error("Empty/ambiguous field")
            parts.append(part)
            if len(parts) >= 128:
                raise Error("Too many columns")
            start = i + 2
    if start:
        final = text[start:]
        if not final or final.startswith(" "):
            raise Error("Empty/trailing field")
        parts.append(final)
    else:
        parts = [text]
    return parts


def _render(value):
    return "~" if value is MISSING else dump(value)


def encode(records, schema, shared=()):
    original = old_encode(records, schema, shared)
    lines = original.split("\n")
    out = [lines[0].replace("@axl3 ", "@axl3p ", 1)]
    for line in lines[1:]:
        if line.startswith("="):
            out.append(line)
            continue
        act, sep, raw = line.partition(" | ")
        out.append(act + " | " + " | ".join(_render(v) for v in values(raw)))
    result = "\n".join(out)
    bound(result)
    return result


def _convert(wire, *, header, allow_mixed):
    bound(wire)
    lines = wire.split("\n")
    if not lines or not lines[0].startswith(header + " "):
        raise Error("Profile header")
    out = [lines[0].replace(header + " ", "@axl3 ", 1)]
    extra = 0
    for line in lines[1:]:
        if line.startswith("="):
            out.append(line)
            continue
        act, sep, raw = line.partition(" | ")
        if not sep or act not in ACTS:
            raise Error("Act boundary")
        pieces = split_top_level_pipes(raw)
        typed = []
        extra += len(pieces) - 1
        for piece in pieces:
            parsed = values(piece)
            if not allow_mixed and len(pieces) > 1 and len(parsed) != 1:
                raise Error("One typed value per pipe field")
            if not allow_mixed and len(pieces) == 1 and len(parsed) > 1:
                raise Error("Missing field separator")
            typed.extend(parsed)
            if len(typed) > 128:
                raise Error("Too many columns")
        out.append(act + " | " + " ".join(_render(v) for v in typed))
    result = "\n".join(out)
    bound(result)
    return result, extra


def decode(wire, schemas):
    normalized, _ = _convert(wire, header="@axl3p", allow_mixed=False)
    return old_decode(normalized, schemas)


@dataclass(frozen=True)
class Normalization:
    original_sha256: str
    normalized_sha256: str
    records_sha256: str
    removed_separators: int
    wire: str


def normalize_extra_separators(wire, schemas, *, allow=False):
    if allow is not True:
        raise Error("Explicit normalization opt-in required")
    h = lambda text: hashlib.sha256(text.encode()).hexdigest()
    try:
        records = old_decode(wire, schemas)
    except Error:
        pass
    else:
        return Normalization(h(wire), h(wire), h(dump(records)), 0, wire)
    normalized, extra = _convert(wire, header="@axl3", allow_mixed=True)
    records = old_decode(normalized, schemas)
    # Registered schema validates the unique interpretation selected by this rule.
    # This does not establish author intent for malformed baseline input.
    h = lambda text: hashlib.sha256(text.encode()).hexdigest()
    return Normalization(h(wire), h(normalized), h(dump(records)), extra, normalized)
