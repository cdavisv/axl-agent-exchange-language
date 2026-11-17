"""Test/benchmark-only pre-refactor decoder snapshot; never production fallback.
Frozen before shared-envelope optimization. Common unchanged load/dump/schema
primitives are imported, while both old decoder bodies are retained verbatim.
"""

import copy
import re
from axl3 import *
from typed_rows import _bound, _schema, _unescape, _escape


def old_json(wire, schemas):
    value = load(wire)
    if type(value) is not list or len(value) != 4:
        raise Error("Bad envelope")
    version, key, constants, rows = value
    if type(version) is not int or version != 3:
        raise Error("Unsupported version")
    if type(key) is not str or key not in schemas:
        raise Error("Unpinned schema")
    schema = schemas[key]
    if schema.fingerprint != key:
        raise Error("Registry mismatch")
    if type(constants) is not dict or type(rows) is not list or len(rows) > MAX_ROWS:
        raise Error("Bad envelope containers")
    fields = schema.fields
    if any(k not in {str(i) for i in range(len(fields))} for k in constants):
        raise Error("Unknown shared index")
    remaining = [f for i, f in enumerate(fields) if str(i) not in constants]
    optional = [f for f in remaining if not f[2]]
    output = []
    expanded_bytes = 2
    for row in rows:
        if type(row) is not list:
            raise Error("Bad row")
        if optional:
            if (
                not row
                or type(row[0]) is not str
                or len(row[0]) != len(optional)
                or set(row[0]) - {"0", "1"}
            ):
                raise Error("Bad presence map")
            bits = iter(row[0])
            vals = row[1:]
            present = [f for f in remaining if f[2] or next(bits) == "1"]
        else:
            present = remaining
            vals = row
        if len(vals) != len(present):
            raise Error("Row width mismatch")
        obj = {fields[int(i)][0]: v for i, v in constants.items()}
        obj.update({f[0]: v for f, v in zip(present, vals)})
        schema.check(obj)
        expanded_bytes += len(dump(obj).encode("utf-8")) + (1 if output else 0)
        if expanded_bytes > MAX_BYTES:
            raise Error("Expanded output limit")
        output.append(copy.deepcopy(obj))
    validate_value(output)
    # Empty batches still validate constants, including their declared types.
    for i, v in constants.items():
        if not matches(v, fields[int(i)][1]):
            raise Error("Wrong shared type")
    return output


def old_typed(wire, schemas):
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
    return old_json(dump([3, key, constants, rows]), schemas)


def old_pack(records, schema, shared=()):
    if type(records) is not list or len(records) > MAX_ROWS:
        raise Error("Row limit/type")
    names = [f[0] for f in schema.fields]
    shared = normalize_shared(shared, names)
    dump(records)  # Bound expanded data as well as compact wire.
    for obj in records:
        schema.check(obj)
    constants = {}
    for n in shared:
        if not records or any(n not in x for x in records):
            raise Error("Shared field absent")
        # JSON spelling comparison prevents bool/int or int/float coercion.
        v = records[0][n]
        if any(dump(x[n]) != dump(v) for x in records):
            raise Error("Mixed shared values")
        constants[str(names.index(n))] = v
    remaining = [f for i, f in enumerate(schema.fields) if str(i) not in constants]
    optional = [f for f in remaining if not f[2]]
    rows = []
    for obj in records:
        values = [obj[n] for n, t, r in remaining if n in obj]
        if optional:
            values.insert(0, "".join("1" if f[0] in obj else "0" for f in optional))
        rows.append(values)
    return dump([3, schema.fingerprint, constants, rows])


def old_encode(records, schema, shared=()):
    _schema(schema)
    standard = load(old_pack(records, schema, shared))
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
