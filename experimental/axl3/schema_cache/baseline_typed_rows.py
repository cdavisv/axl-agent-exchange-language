"""Experimental typed text rows; exact declared strings, never inferred repair."""

from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from baseline_axl3 import Error, MAX_BYTES, MAX_ROWS, dump, load, pack, _unpack_validated_envelope


def _bound(wire):
    if type(wire) is not str:
        raise Error("Expected text")
    try:
        size = len(wire.encode("utf-8"))
    except UnicodeError as exc:
        raise Error("Invalid Unicode scalar") from exc
    if size > MAX_BYTES:
        raise Error("Wire byte limit")


def _schema(schema):
    if any(not required for _, _, required in schema.fields):
        raise Error("Typed rows require all fields required")


def _escape(value):
    out = []
    for char in value:
        if char == "\\":
            out.append("\\\\")
        elif char == "\t":
            out.append("\\t")
        elif char == "\n":
            out.append("\\n")
        elif char == "\r":
            out.append("\\r")
        elif ord(char) < 32:
            out.append("\\x" + format(ord(char), "02x"))
        else:
            out.append(char)
    return "".join(out)


def _unescape(value):
    out = []
    i = 0
    while i < len(value):
        char = value[i]
        if ord(char) < 32:
            raise Error("Raw control character")
        if char != "\\":
            out.append(char)
            i += 1
            continue
        if i + 1 == len(value):
            raise Error("Incomplete escape")
        escape = value[i + 1]
        if escape in {"\\", "t", "n", "r"}:
            out.append({"\\": "\\", "t": "\t", "n": "\n", "r": "\r"}[escape])
            i += 2
        elif (
            escape == "x"
            and i + 3 < len(value)
            and re.fullmatch("[0-9a-f]{2}", value[i + 2 : i + 4])
        ):
            number = int(value[i + 2 : i + 4], 16)
            if number >= 32:
                raise Error("Only control hex escapes permitted")
            out.append(chr(number))
            i += 4
        else:
            raise Error("Unknown or incomplete escape")
    return "".join(out)


def encode(records, schema, shared=()):
    _schema(schema)
    standard = load(pack(records, schema, shared))
    constants, rows = standard[2:]
    remaining = [field for i, field in enumerate(schema.fields) if str(i) not in constants]
    lines = ["@axl3t " + schema.fingerprint, "=" + dump(constants)]
    for row in rows:
        cells = [
            _escape(value) if field[1] == "string" else dump(value)
            for field, value in zip(remaining, row)
        ]
        lines.append(">" + "\t".join(cells))
    wire = "\n".join(lines)
    _bound(wire)
    return wire


def decode(wire, schemas):
    _bound(wire)
    # Deterministic framing only: normalize CRLF boundaries and one terminal
    # line ending. Do not trim cells/tabs or infer missing fields/escapes.
    wire = wire.replace("\r\n", "\n")
    if wire.endswith("\n"):
        wire = wire[:-1]
    lines = wire.split("\n")
    if (
        len(lines) < 2
        or len(lines) > MAX_ROWS + 2
        or not re.fullmatch(r"@axl3t [0-9a-f]{64}", lines[0])
    ):
        raise Error("Typed-row header or row bound")
    key = lines[0][7:]
    if key not in schemas or schemas[key].fingerprint != key:
        raise Error("Unpinned schema")
    schema = schemas[key]
    _schema(schema)
    if not lines[1].startswith("="):
        raise Error("Shared declaration")
    constants = load(lines[1][1:])
    if type(constants) is not dict or any(
        k not in {str(i) for i in range(len(schema.fields))} for k in constants
    ):
        raise Error("Shared index")
    remaining = [field for i, field in enumerate(schema.fields) if str(i) not in constants]
    rows = []
    for line in lines[2:]:
        if not line.startswith(">"):
            raise Error("Row marker")
        raw = line[1:]
        cells = raw.split("\t") if remaining else ([] if raw == "" else [raw])
        if len(cells) != len(remaining):
            raise Error("Row width")
        rows.append(
            [
                _unescape(cell) if field[1] == "string" else load(cell)
                for field, cell in zip(remaining, cells)
            ]
        )
    # Reuse all native type, expanded-byte, depth, node and alias-isolation checks.
    envelope = [3, key, constants, rows]
    dump(envelope)  # Preserve exact canonical-envelope byte/global bounds.
    return _unpack_validated_envelope(envelope, schemas)
