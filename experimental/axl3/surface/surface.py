"""Experimental AXL act-line surface. Candidate v3 codec remains unchanged."""

import json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from axl3 import (
    Schema,
    Error,
    MAX_BYTES,
    MAX_DEPTH,
    MAX_ROWS,
    load,
    dump,
    validate_value,
    normalize_shared,
)

ACTS = {"request", "accept", "need", "evidence", "result", "status", "error", "cancel", "supersede"}
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")


def check_schema(schema):
    if any(not NAME.fullmatch(f[0]) for f in schema.fields):
        raise Error("Surface field name")
    if ("kind", "string", True) not in schema.fields:
        raise Error("Surface requires kind:string:required")


def bound(text):
    if type(text) is not str:
        raise Error("Expected text")
    try:
        size = len(text.encode("utf-8"))
    except UnicodeError as e:
        raise Error("Invalid Unicode") from e
    if size > MAX_BYTES:
        raise Error("Wire byte limit")
    depth = 0
    quoted = False
    escape = False
    for char in text:
        if quoted:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > MAX_DEPTH:
                raise Error("Depth limit")
        elif char in "]}":
            depth -= 1
        if depth < 0:
            raise Error("Unbalanced value")
    if quoted or depth:
        raise Error("Incomplete value")


MISSING = object()


def values(text):
    """Parse bounded, space-separated JSON literals or explicit absent marker.~"""
    bound(text)
    decoder = json.JSONDecoder()
    offset = 0
    output = []
    while offset < len(text):
        if text[offset] == "~":
            value = MISSING
            end = offset + 1
        else:
            try:
                _, end = decoder.raw_decode(text, offset)
            except (ValueError, RecursionError) as e:
                raise Error("Invalid literal") from e
            value = load(text[offset:end])  # duplicate/numeric/type/bounds checks from v3
        output.append(value)
        if len(output) > 128:
            raise Error("Field count")
        if end == len(text):
            break
        if text[end] != " " or end + 1 == len(text) or text[end + 1] == " ":
            raise Error("Expected single-space boundary")
        offset = end + 1
    return output


def encode(records, schema, shared=(), *, compact_optional=False):
    check_schema(schema)
    if type(records) is not list or len(records) > MAX_ROWS:
        raise Error("Record limit")
    dump(records)  # Bound expanded data before sharing.
    for row in records:
        schema.check(row)
        if row["kind"] not in ACTS:
            raise Error("Unknown act")
    names = [f[0] for f in schema.fields]
    shared = normalize_shared(shared, names, forbidden=("kind",))
    declarations = []
    for name in sorted(shared, key=names.index):
        if not records or any(name not in r for r in records):
            raise Error("Missing shared value")
        v = dump(records[0][name])
        if any(dump(r[name]) != v for r in records):
            raise Error("Mixed shared values")
        declarations.append("=" + name + " " + v)
    fields = [f for f in schema.fields if f[0] != "kind" and f[0] not in shared]
    lines = ["@axl3 " + schema.fingerprint] + declarations
    for row in records:
        chosen = fields
        act = row["kind"]
        if compact_optional:
            optional = [f for f in fields if not f[2]]
            bits = "".join("1" if f[0] in row else "0" for f in optional)
            act += " " + str(int(bits or "0", 2))
            chosen = [f for f in fields if f[2] or f[0] in row]
        lines.append(
            act + " | " + " ".join(dump(row[n]) if n in row else "~" for n, _, _ in chosen)
        )
    result = "\n".join(lines)
    bound(result)
    return result


def decode(text, schemas):
    bound(text)
    lines = text.split("\n")
    if not lines or not re.fullmatch(r"@axl3 [0-9a-f]{64}", lines[0]):
        raise Error("Frame header")
    key = lines[0][6:]
    if key not in schemas or schemas[key].fingerprint != key:
        raise Error("Unpinned schema")
    schema = schemas[key]
    check_schema(schema)
    definitions = {f[0]: f for f in schema.fields}
    shared = {}
    rows = []
    began = False
    size = 2
    for line in lines[1:]:
        if line.startswith("="):
            if began:
                raise Error("Late shared declaration")
            name, sep, raw = line[1:].partition(" ")
            if not sep or name not in definitions or name == "kind" or name in shared:
                raise Error("Invalid shared declaration")
            vals = values(raw)
            if len(vals) != 1 or vals[0] is MISSING:
                raise Error("Shared literal")
            shared[name] = vals[0]
            continue
        began = True
        act, sep, raw = line.partition(" | ")
        act_parts = act.split(" ")
        if not sep or len(act_parts) not in (1, 2) or act_parts[0] not in ACTS:
            raise Error("Act boundary")
        act = act_parts[0]
        mask = act_parts[1] if len(act_parts) == 2 else None
        vals = values(raw)
        fields = [f for f in schema.fields if f[0] != "kind" and f[0] not in shared]
        if mask is not None:
            optional = [f for f in fields if not f[2]]
            if not re.fullmatch(r"0|[1-9][0-9]{0,38}", mask) or int(mask) >= 2 ** len(optional):
                raise Error("Optional mask")
            bits = iter(format(int(mask), "0" + str(len(optional)) + "b") if optional else "")
            fields = [f for f in fields if f[2] or next(bits) == "1"]
            if any(v is MISSING for v in vals):
                raise Error("Absent marker in compact row")
        if len(vals) != len(fields):
            raise Error("Row width")
        # Shared containers are copied through roundtrip to avoid cross-row aliases.
        row = load(dump(shared))
        row["kind"] = act
        for (name, _, required), value in zip(fields, vals):
            if value is MISSING:
                if required:
                    raise Error("Missing required value")
            else:
                row[name] = value
        schema.check(row)
        size += len(dump(row).encode()) + (1 if rows else 0)
        if size > MAX_BYTES or len(rows) >= MAX_ROWS:
            raise Error("Expanded bound")
        rows.append(row)
    # Validate shared types even for empty frames.
    from axl3 import matches

    if any(not matches(value, definitions[name][1]) for name, value in shared.items()):
        raise Error("Shared type")
    validate_value(rows)
    return rows
