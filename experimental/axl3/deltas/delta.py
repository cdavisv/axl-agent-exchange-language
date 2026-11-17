"""Revision-bound typed state deltas. Established technique, experimental AXL UI.
Pure functions only; never grants permissions or modifies external state.
"""

import sys, json, hashlib, re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from axl3 import Error, load, dump, validate_value

_SURFACE = str(Path(__file__).resolve().parents[1] / "surface")
if _SURFACE not in sys.path:
    sys.path.insert(0, _SURFACE)
from surface import values

MAX_OPS = 256


def canonical(value):
    dump(value)
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def sha(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def equal(a, b):
    return canonical(a) == canonical(b)


def diff(before, after, path=()):
    if equal(before, after):
        return []
    if type(before) is dict and type(after) is dict:
        ops = []
        for key in sorted(set(before) - set(after)):
            ops.append(["unset", list(path + (key,))])
        for key in sorted(after):
            if key not in before:
                ops.append(["set", list(path + (key,)), after[key]])
            else:
                ops.extend(diff(before[key], after[key], path + (key,)))
        return ops
    if (
        type(before) is list
        and type(after) is list
        and len(after) > len(before)
        and all(equal(a, b) for a, b in zip(before, after))
    ):
        return [["append", list(path), after[len(before) :]]]
    return [["set", list(path), after]]


def frame(before, after, base_revision, next_revision):
    dump(before)
    dump(after)
    if (
        type(base_revision) is not int
        or type(next_revision) is not int
        or not 0 <= base_revision < 2**53
        or not 0 <= next_revision < 2**53
        or next_revision not in (base_revision, base_revision + 1)
    ):
        raise Error("Revision")
    ops = diff(before, after)
    if len(ops) > MAX_OPS:
        ops = [["set", [], after]]  # Deterministic bounded full-root fallback.
    if ops and next_revision == base_revision:
        raise Error("Changed state requires revision increment")
    result = [3, base_revision, next_revision, sha(before), sha(after), ops]
    structure(result)
    return result


def emit_axl(f):
    # Validate structural envelope before rendering; no need for base content here.
    structure(f)
    header = "@axld " + str(f[1]) + " " + str(f[2]) + " " + f[3] + " " + f[4]
    return header + "".join(
        "\n" + op[0] + " " + dump(op[1]) + (" " + dump(op[2]) if len(op) == 3 else "")
        for op in f[5]
    )


def parse_axl(wire):
    if type(wire) is not str:
        raise Error("Wire type")
    try:
        size = len(wire.encode())
    except UnicodeError as e:
        raise Error("Wire Unicode") from e
    if size > 262144:
        raise Error("Wire bound")
    lines = wire.split("\n")
    head = lines[0].split(" ")
    if (
        len(head) != 5
        or head[0] != "@axld"
        or not all(re.fullmatch(r"0|[1-9][0-9]{0,15}", x) for x in head[1:3])
    ):
        raise Error("Delta header")
    ops = []
    for line in lines[1:]:
        op, space, raw = line.partition(" ")
        if not space:
            raise Error("Delta operation")
        parts = values(raw)
        ops.append([op] + parts)
        if len(ops) > MAX_OPS:
            raise Error("Operation count")
    f = [3, int(head[1]), int(head[2]), head[3], head[4], ops]
    structure(f)
    return f


def structure(f):
    dump(f)
    if type(f) is not list or len(f) != 6:
        raise Error("Delta envelope")
    version, old, new, base, target, ops = f
    if (
        type(version) is not int
        or version != 3
        or type(old) is not int
        or type(new) is not int
        or not 0 <= old < 2**53
        or not 0 <= new < 2**53
        or new not in (old, old + 1)
    ):
        raise Error("Revision")
    if any(type(h) is not str or not re.fullmatch("[0-9a-f]{64}", h) for h in (base, target)):
        raise Error("State hash")
    if type(ops) is not list or len(ops) > MAX_OPS:
        raise Error("Operation count")
    if ops and old == new:
        raise Error("Changed revision required")
    for op in ops:
        if (
            type(op) is not list
            or len(op) not in (2, 3)
            or type(op[0]) is not str
            or op[0] not in ("set", "unset", "append")
        ):
            raise Error("Operation")
        if (op[0] == "unset") != (len(op) == 2):
            raise Error("Operation arity")
        if type(op[1]) is not list or len(op[1]) > 32 or any(type(k) is not str for k in op[1]):
            raise Error("Object-key path only")
        if op[0] == "unset" and not op[1]:
            raise Error("Cannot unset root")
        if op[0] == "append" and (type(op[2]) is not list or not op[2]):
            raise Error("Append array suffix required")


def apply(before, revision, f):
    structure(f)
    if type(revision) is not int or revision != f[1] or sha(before) != f[3]:
        raise Error("STALE_BASE")
    result = load(dump(before))
    for op in f[5]:
        kind, path = op[:2]
        parent = result
        for key in path[:-1]:
            if type(parent) is not dict or key not in parent:
                raise Error("Missing parent")
            parent = parent[key]
        if path and type(parent) is not dict:
            raise Error("Object parent required")
        if kind == "set":
            value = load(dump(op[2]))
            if path:
                parent[path[-1]] = value
            else:
                result = value
        elif kind == "unset":
            if path[-1] not in parent:
                raise Error("Missing unset target")
            del parent[path[-1]]
        else:
            current = result if not path else parent.get(path[-1])
            if type(current) is not list:
                raise Error("Append target must exist as array")
            current.extend(load(dump(op[2])))
        dump(result)  # Bound every intermediate state, not just final output.
    if sha(result) != f[4]:
        raise Error("TARGET_MISMATCH")
    return result, f[2]


def json_patch_ops(f):
    """Equivalent RFC6902 subset, guarded by same external base/target metadata."""
    out = []
    for op in f[5]:
        path = "".join("/" + k.replace("~", "~0").replace("/", "~1") for k in op[1])
        if op[0] == "unset":
            out.append({"op": "remove", "path": path})
        elif op[0] == "set":
            out.append({"op": "add", "path": path, "value": op[2]})
        else:
            for value in op[2]:
                out.append({"op": "add", "path": path + "/-", "value": value})
    return out
