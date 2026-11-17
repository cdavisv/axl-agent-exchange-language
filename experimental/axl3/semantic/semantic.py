"""Opt-in lossless host-pinned enum/default profile; no semantic inference."""

import copy
import hashlib
from dataclasses import dataclass
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from axl3 import Error, Schema, MAX_FIELDS, MAX_ROWS, MAX_BYTES, dump, load, matches


@dataclass(frozen=True)
class SemanticSchema:
    base: Schema
    enums: tuple = ()  # (field name, tuple of unique strings), bounded ordinal table
    defaults: tuple = ()  # (field name, strict JSON text); canonicalized on construction

    def __post_init__(self):
        if (
            type(self.base) is not Schema
            or type(self.enums) is not tuple
            or type(self.defaults) is not tuple
        ):
            raise Error("Immutable definition required")
        fields = {name: kind for name, kind, _ in self.base.fields}
        for entries in (self.enums, self.defaults):
            if len(entries) > MAX_FIELDS or any(
                type(x) is not tuple or len(x) != 2 or type(x[0]) is not str for x in entries
            ):
                raise Error("Bad semantic definition")
            names = [x[0] for x in entries]
            if len(set(names)) != len(names) or any(name not in fields for name in names):
                raise Error("Duplicate/unknown semantic field")
        for name, values in self.enums:
            if (
                fields[name] != "string"
                or type(values) is not tuple
                or not 1 <= len(values) <= 256
                or any(type(v) is not str for v in values)
                or len(set(values)) != len(values)
            ):
                raise Error("Bad finite string enum")
            dump(list(values))
        canonical = []
        for name, text in self.defaults:
            value = load(text)
            if not matches(value, fields[name]):
                raise Error("Default type mismatch")
            table = dict(self.enums).get(name)
            if table is not None and value not in table:
                raise Error("Default outside enum")
            canonical.append((name, dump(value)))
        object.__setattr__(self, "defaults", tuple(canonical))
        dump(self.definition)

    @property
    def definition(self):
        return {
            "profile": "axl3-sem1",
            "base": self.base.definition,
            "enums": [[n, list(v)] for n, v in self.enums],
            "defaults": [[n, load(v)] for n, v in self.defaults],
        }

    @property
    def fingerprint(self):
        return hashlib.sha256(dump(self.definition).encode("utf8")).hexdigest()


def validate_records(records, schema):
    if type(records) is not list or len(records) > MAX_ROWS:
        raise Error("Rows limit/type")
    dump(records)
    enums = dict(schema.enums)
    for row in records:
        schema.base.check(row)
        for name, table in enums.items():
            if name in row and row[name] not in table:
                raise Error("Value outside enum")


def encode(records, schema):
    validate_records(records, schema)
    enums = dict(schema.enums)
    defaults = dict(schema.defaults)
    rows = []
    for record in records:
        states = []
        values = []
        for name, kind, required in schema.base.fields:
            if name not in record:
                states.append("0")
            elif name in defaults and dump(record[name]) == defaults[name]:
                states.append("1")
            else:
                states.append("2")
                values.append(enums[name].index(record[name]) if name in enums else record[name])
        rows.append(["".join(states), values])
    return dump(["axl3-sem1", schema.fingerprint, rows])


def decode(wire, schemas):
    value = load(wire)
    if type(value) is not list or len(value) != 3:
        raise Error("Envelope")
    version, key, rows = value
    if (
        type(version) is not str
        or version != "axl3-sem1"
        or type(key) is not str
        or key not in schemas
    ):
        raise Error("Version/unpinned schema")
    schema = schemas[key]
    if type(schema) is not SemanticSchema or schema.fingerprint != key:
        raise Error("Registry mismatch")
    if type(rows) is not list or len(rows) > MAX_ROWS:
        raise Error("Rows limit/type")
    enums = dict(schema.enums)
    defaults = dict(schema.defaults)
    output = []
    expanded_bytes = 2
    for row in rows:
        if type(row) is not list or len(row) != 2:
            raise Error("Row")
        states, values = row
        if (
            type(states) is not str
            or len(states) != len(schema.base.fields)
            or set(states) - {"0", "1", "2"}
            or type(values) is not list
            or len(values) != states.count("2")
        ):
            raise Error("Presence/width")
        record = {}
        index = 0
        for state, (name, kind, required) in zip(states, schema.base.fields):
            if state == "0":
                if required:
                    raise Error("Required absent")
            elif state == "1":
                if name not in defaults:
                    raise Error("Undeclared default")
                record[name] = load(defaults[name])
            else:
                cell = values[index]
                index += 1
                if name in enums:
                    if type(cell) is not int or not 0 <= cell < len(enums[name]):
                        raise Error("Enum ordinal")
                    cell = enums[name][cell]
                record[name] = copy.deepcopy(cell)
        schema.base.check(record)
        expanded_bytes += len(dump(record).encode("utf8")) + (1 if output else 0)
        if expanded_bytes > MAX_BYTES:
            raise Error("Expanded output limit")
        output.append(record)
    validate_records(output, schema)
    return output
