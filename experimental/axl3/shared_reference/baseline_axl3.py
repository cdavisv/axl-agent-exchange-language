"""AXL 3 candidate: bounded, schema-first JSON-compatible communication codec.
Not an authorization system, semantic compressor, or released protocol.
"""

from itertools import islice
import hashlib
import json
import math
import copy
from decimal import Decimal, DecimalException
from types import MappingProxyType
from dataclasses import dataclass
from functools import cached_property

MAX_BYTES = 262144
MAX_DEPTH = 32
MAX_NODES = 32768
MAX_ROWS = 1024
MAX_FIELDS = 128
TYPES = {"any", "string", "integer", "number", "boolean", "array", "object", "null"}


class Error(ValueError):
    pass


def _validation_list_children(value, depth):
    return ((child, depth + 1) for child in reversed(value))


def _validation_dict_children(value, depth):
    return ((child, depth + 1) for key in reversed(value) for child in (value[key], key))


def validate_value(value):
    # Preserve LIFO error precedence. Suspend wide containers and refill in
    # bounded reverse-order chunks instead of allocating a tuple per child.
    # Small containers retain the original eager path. Inputs must not mutate
    # concurrently during validation; limits assume a fixed host policy.
    stack = [(value, 0)]
    pending = []
    nodes = 0
    while True:
        while stack:
            v, d = stack.pop()
            nodes += 1
            if d > MAX_DEPTH or nodes > MAX_NODES:
                raise Error("JSON resource limit")
            if v is None or type(v) in (bool, int):
                continue
            if type(v) is float:
                if not math.isfinite(v):
                    raise Error("Nonfinite number")
            elif type(v) is str:
                try:
                    v.encode("utf-8")
                except UnicodeError as e:
                    raise Error("Invalid Unicode scalar") from e
            elif type(v) is list:
                if d >= MAX_DEPTH:
                    raise Error("JSON depth limit")
                if len(v) <= 4096:
                    stack.extend((x, d + 1) for x in v)
                else:
                    pending.append((stack, _validation_list_children(v, d)))
                    stack = []
                    break
            elif type(v) is dict:
                if d >= MAX_DEPTH:
                    raise Error("JSON depth limit")
                if any(type(k) is not str for k in v):
                    raise Error("Non-string object key")
                if len(v) <= 2048:
                    stack.extend((x, d + 1) for pair in v.items() for x in pair)
                else:
                    pending.append((stack, _validation_dict_children(v, d)))
                    stack = []
                    break
            else:
                raise Error("Not a JSON value")
        while pending and not stack:
            parent, iterator = pending[-1]
            chunk = list(islice(iterator, 1024))
            if chunk:
                # The iterator yields visitation order; reversing into a LIFO
                # stack retains that order across chunk and container boundaries.
                stack.extend(reversed(chunk))
            else:
                stack = parent
                pending.pop()
        if not stack:
            return


def dump(value):
    validate_value(value)
    try:
        s = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (ValueError, OverflowError) as e:
        raise Error(str(e)) from e
    if len(s.encode("utf-8")) > MAX_BYTES:
        raise Error("Wire byte limit")
    return s


def load(s, *, preserve_number_lexemes=False):
    if type(s) is not str:
        raise Error("Expected text")
    try:
        if len(s.encode("utf-8")) > MAX_BYTES:
            raise Error("Wire byte limit")
    except UnicodeError as e:
        raise Error("Invalid Unicode scalar") from e
    # Bound nesting before the standard decoder allocates recursive containers.
    depth = 0
    quoted = False
    escape = False
    for ch in s:
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
            if depth > MAX_DEPTH:
                raise Error("Wire nesting limit")
        elif ch in "]}":
            depth -= 1

    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise Error("Duplicate JSON key")
            out[k] = v
        return out

    def constant(s):
        raise Error("Nonfinite number")

    def integer(text):
        if preserve_number_lexemes:
            return text
        if text == "-0":
            raise Error("Negative integer zero unsupported")
        return int(text)

    def number(text):
        if preserve_number_lexemes:
            return text
        v = float(text)
        if not math.isfinite(v) or Decimal(json.dumps(v)) != Decimal(text):
            raise Error("Number cannot roundtrip exactly")
        return v

    try:
        v = json.loads(
            s,
            object_pairs_hook=pairs,
            parse_constant=constant,
            parse_int=integer,
            parse_float=number,
        )
    except (ValueError, RecursionError, DecimalException) as e:
        raise Error(str(e)) from e
    validate_value(v)
    return v


def matches(v, t):
    return (
        t == "any"
        or (t == "string" and type(v) is str)
        or (t == "integer" and type(v) is int)
        or (t == "number" and type(v) in (int, float))
        or (t == "boolean" and type(v) is bool)
        or (t == "array" and type(v) is list)
        or (t == "object" and type(v) is dict)
        or (t == "null" and v is None)
    )


@dataclass(frozen=True)
class Schema:
    name: str
    fields: tuple  # (name, JSON type, required)

    def __post_init__(self):
        if type(self.name) is not str or not self.name or len(self.name) > 128:
            raise Error("Bad schema name")
        if type(self.fields) is not tuple or not 1 <= len(self.fields) <= MAX_FIELDS:
            raise Error("Bad schema fields")
        seen = set()
        for f in self.fields:
            if type(f) is not tuple or len(f) != 3:
                raise Error("Bad field")
            n, t, r = f
            if (
                type(n) is not str
                or not n
                or len(n) > 128
                or n in seen
                or type(t) is not str
                or t not in TYPES
                or type(r) is not bool
            ):
                raise Error("Bad field definition")
            seen.add(n)
        dump(self.definition)

    @property
    def definition(self):
        return {"name": self.name, "fields": [list(f) for f in self.fields]}

    @cached_property
    def _field_name_set(self):
        return frozenset(f[0] for f in self.fields)

    @cached_property
    def _field_index_set(self):
        return frozenset(str(i) for i in range(len(self.fields)))

    @cached_property
    def _fingerprint_cache(self):
        return hashlib.sha256(dump(self.definition).encode()).hexdigest()

    @property
    def fingerprint(self):
        # Only exact immutable Schema instances use cached metadata. Subclasses
        # retain dynamic definition behavior; old pickles lazily fill caches.
        if type(self) is Schema:
            return self._fingerprint_cache
        return hashlib.sha256(dump(self.definition).encode()).hexdigest()

    def check(self, obj):
        if type(obj) is not dict:
            raise Error("Record must be object")
        validate_value(obj)
        if set(obj) - (
            self._field_name_set if type(self) is Schema else {f[0] for f in self.fields}
        ):
            raise Error("Unknown field")
        for n, t, r in self.fields:
            if n not in obj:
                if r:
                    raise Error("Required field missing")
            elif not matches(obj[n], t):
                raise Error("Wrong field type: " + n)


# Immutable registry snapshot: receivers provision and pin schemas out of band.
def registry(*schemas):
    return MappingProxyType({s.fingerprint: s for s in schemas})


def normalize_shared(shared, names, *, forbidden=()):
    """Consume a bounded field-name iterable once; reject malformed API input.

    This is encoder configuration, not wire data. Keep one-shot iterables
    consistent across the core and human-readable surface profiles.
    """
    if isinstance(shared, (str, bytes)):
        raise Error("Bad shared field iterable")
    try:
        iterator = iter(shared)
    except TypeError as exc:
        raise Error("Bad shared field iterable") from exc
    selected = []
    seen = set()
    allowed = set(names) - set(forbidden)
    for name in iterator:
        if (
            len(selected) >= MAX_FIELDS
            or type(name) is not str
            or name not in allowed
            or name in seen
        ):
            raise Error("Bad shared field")
        selected.append(name)
        seen.add(name)
    return tuple(selected)


def pack(records, schema, shared=()):
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


def unpack(wire, schemas):
    return _unpack_validated_envelope(load(wire), schemas)


def _unpack_validated_envelope(value, schemas):
    """Internal expansion of an already bounded/validated JSON envelope.

    Text entry points must use strict load first. Constructed envelopes must
    use dump first to retain canonical bytes, aggregate nodes/depth and scalar
    validation. This helper is not an untrusted Python-object entry point.
    """
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
    indices = (
        schema._field_index_set if type(schema) is Schema else {str(i) for i in range(len(fields))}
    )
    if any(k not in indices for k in constants):
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
        # Exact schemas validate without mutating rows. Defer detachment until
        # all original guards pass; preserve eager snapshots for subclasses.
        output.append(obj if type(schema) is Schema else copy.deepcopy(obj))
    validate_value(output)
    # Empty batches still validate constants, including their declared types.
    for i, v in constants.items():
        if not matches(v, fields[int(i)][1]):
            raise Error("Wrong shared type")
    return [copy.deepcopy(obj) for obj in output] if type(schema) is Schema else output


# Wrap every strict v2 field/payload, rather than silently remapping semantics.
V2 = Schema(
    "axl.v2.lossless-wrapper",
    (("prefix", "string", True), ("fields", "object", True), ("payload", "object", True)),
)


def _v2_delta_byte_guard(fields, payload):
    if fields.get("mode") != "delta":
        return
    operations = fields.get("operations", payload.get("operations"))
    if type(operations) is str:
        if len(operations.encode("utf-8")) > 65536:
            raise Error("V2 delta operations UTF8 byte limit")
        operations = load(operations)
    elif len(dump(operations).encode("utf-8")) > 65536:
        raise Error("V2 delta operations UTF8 byte limit")
    if type(operations) is list:
        for operation in operations:
            if type(operation) is dict:
                for key in ("path", "from"):
                    pointer = operation.get(key)
                    if type(pointer) is str and len(pointer.encode("utf-8")) > 1024:
                        raise Error("V2 delta pointer UTF8 byte limit")


def import_v2(wires):
    from axl import parse_axl_message

    out = []
    for w in wires:
        if len(w.encode("utf-8")) > MAX_BYTES or any(
            len(line.encode("utf-8")) > 8192 for line in w.splitlines()[1:]
        ):
            raise Error("V2 UTF8 byte limit")
        m = parse_axl_message(w, strict=True)
        _v2_delta_byte_guard(m.fields, m.payload)
        out.append({"prefix": m.prefix, "fields": m.fields, "payload": m.payload})
    return pack(out, V2)


def export_v2(wire):
    from axl import build_axl_message, parse_axl_message

    output = []
    for obj in unpack(wire, registry(V2)):
        _v2_delta_byte_guard(obj["fields"], obj["payload"])
        w = build_axl_message(
            obj["prefix"], fields=obj["fields"], payload=obj["payload"], strict=True
        )
        if len(w.encode("utf-8")) > MAX_BYTES or any(
            len(line.encode("utf-8")) > 8192 for line in w.splitlines()[1:]
        ):
            raise Error("V2 UTF8 byte limit")
        m = parse_axl_message(w, strict=True)
        back = {"prefix": m.prefix, "fields": m.fields, "payload": m.payload}
        if json.dumps(back, sort_keys=True, ensure_ascii=False) != json.dumps(
            obj, sort_keys=True, ensure_ascii=False
        ):
            raise Error("V2 translation would change data")
        output.append(w)
    return output


# Exact JSON-value translator. Preserves parsed values, not whitespace/key spelling.
JSON = Schema("json.value", (("value", "any", True),))


def json_to_axl(text):
    return pack([{"value": load(text)}], JSON)


def axl_to_json(wire):
    rows = unpack(wire, registry(JSON))
    if len(rows) != 1:
        raise Error("Expected one JSON value")
    return dump(rows[0]["value"])


MESSAGE = Schema(
    "axl.message.3-candidate",
    tuple(
        (n, t, r)
        for n, t, r in [
            ("id", "string", True),
            ("task", "string", True),
            ("sender", "string", True),
            ("to", "string", True),
            ("kind", "string", True),
            ("seq", "integer", True),
            ("body", "any", True),
            ("reply", "string", False),
            ("status", "string", False),
            ("evidence", "array", False),
        ]
    ),
)


def accept_messages(wire, *, authenticated_peer, local_recipient, task, seen):
    """Validate claims against trusted transport context; no tool execution.
    `seen` is caller-owned replay ledger; return new IDs but never mutate ledger.
    Caller must atomically record IDs with effects. Not exactly-once delivery.
    """
    import re

    rows = unpack(wire, registry(MESSAGE))
    ids = set()
    for m in rows:
        if m["sender"] != authenticated_peer or m["to"] != local_recipient or m["task"] != task:
            raise Error("Transport/task claim mismatch")
        for k in ("id", "task", "sender", "to"):
            if not re.fullmatch(r"[A-Za-z0-9_@.:-]{1,128}", m[k]):
                raise Error("Bad identity")
        if m["id"] in seen or m["id"] in ids:
            raise Error("Replay/duplicate ID")
        ids.add(m["id"])
        if m["kind"] not in {"request", "result", "status", "error", "evidence", "cancel"}:
            raise Error("Unknown kind")
        if m["seq"] < 0 or m["seq"] > 2**53 - 1:
            raise Error("Invalid sequence")
        if m["kind"] in {"result", "status", "error", "cancel"} and "reply" not in m:
            raise Error("Missing correlation")
        if "reply" in m and not re.fullmatch(r"[A-Za-z0-9_@.:-]{1,128}", m["reply"]):
            raise Error("Bad correlation")
        if "status" in m and m["status"] not in {
            "new",
            "running",
            "blocked",
            "done",
            "failed",
            "cancelled",
        }:
            raise Error("Unknown status")
        if "evidence" in m and any(
            type(x) is not dict
            or set(x) != {"source", "sha256"}
            or type(x["source"]) is not str
            or type(x["sha256"]) is not str
            or not re.fullmatch("[0-9a-f]{64}", x["sha256"])
            for x in m["evidence"]
        ):
            raise Error("Bad evidence references")
    return rows, ids


# Lexical capsule retains whitespace, member order and all numeric lexemes exactly.
# No token-saving claim: escaping the source string may increase size substantially.
JSON_TEXT = Schema("json.raw-text", (("text", "string", True),))


def json_text_to_axl(text):
    load(text, preserve_number_lexemes=True)
    return pack([{"text": text}], JSON_TEXT)


def axl_to_json_text(wire):
    records = unpack(wire, registry(JSON_TEXT))
    if len(records) != 1:
        raise Error("Expected one raw JSON record")
    text = records[0]["text"]
    load(text, preserve_number_lexemes=True)
    return text
