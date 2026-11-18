"""Equivalent guarded benchmark controls; RFC add/remove subset only."""

from delta import *


def rfc_apply(before, ops):
    out = load(dump(before))
    if type(ops) is not list or len(ops) > 1024:
        raise Error("Patch count")
    for op in ops:
        if (
            type(op) is not dict
            or op.get("op") not in ("add", "remove")
            or type(op.get("path")) is not str
        ):
            raise Error("Patch shape")
        if set(op) != ({"op", "path", "value"} if op["op"] == "add" else {"op", "path"}):
            raise Error("Patch fields")
        if op["path"] == "":
            if op["op"] != "add":
                raise Error("Root removal unsupported")
            out = load(dump(op["value"]))
            continue
        if not op["path"].startswith("/") or re.search(r"~(?![01])", op["path"]):
            raise Error("Pointer")
        keys = [s.replace("~1", "/").replace("~0", "~") for s in op["path"][1:].split("/")]
        if len(keys) > 33:
            raise Error("Pointer depth")
        parent = out
        for key in keys[:-1]:
            if type(parent) is not dict or key not in parent:
                raise Error("Patch parent")
            parent = parent[key]
        if op["op"] == "remove":
            if type(parent) is not dict or keys[-1] not in parent:
                raise Error("Remove target")
            del parent[keys[-1]]
        elif type(parent) is list and keys[-1] == "-":
            parent.append(load(dump(op["value"])))
        elif type(parent) is dict:
            parent[keys[-1]] = load(dump(op["value"]))
        else:
            raise Error("Add target")
        dump(out)
    return out


def guarded_control(before, revision, wire, mode):
    if mode not in ("json_patch", "snapshot"):
        raise Error("Control mode")
    parsed = load(wire)
    if type(parsed) is not list or len(parsed) != 6:
        raise Error("Delta envelope")
    structure(parsed[:5] + [[]])
    if type(revision) is not int or revision != parsed[1] or sha(before) != parsed[3]:
        raise Error("STALE_BASE")
    if parsed[1] == parsed[2] and (parsed[3] != parsed[4] or (mode == "json_patch" and parsed[5])):
        raise Error("Changed revision required")
    # No patch traversal or snapshot selection happens before the base guard.
    result = rfc_apply(before, parsed[5]) if mode == "json_patch" else parsed[5]
    dump(result)
    if sha(result) != parsed[4]:
        raise Error("TARGET_MISMATCH")
    return result
