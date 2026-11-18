"""Opt-in warm-base handoff selection. Pure data, not agent authority.
All modes require an authenticated host's actual matching base. No cold-base
hydration, remote fetching, permission changes, or persistence is performed.
"""

from dataclasses import dataclass
import math
from delta import Error, dump, load, frame, structure, sha, equal, apply
from controls import guarded_control


@dataclass(frozen=True)
class Selection:
    mode: str
    wire: str
    cost: float
    candidate_costs: tuple


def candidates(before, after, revision, next_revision):
    # Validate semantic inputs independently. A candidate-specific size/depth
    # failure must not discard a valid smaller representation.
    dump(before)
    dump(after)
    same = equal(before, after)
    meta = [3, revision, next_revision, sha(before), sha(after)]
    structure(meta + [[]])
    if not same and revision == next_revision:
        raise Error("Changed state requires revision increment")
    result = {}
    try:
        result["snapshot"] = dump(["snapshot", meta + [after]])
    except Error:
        pass  # This representation exceeds codec bounds.
    try:
        f = frame(before, after, revision, next_revision)
    except Error:
        f = None
    if f is not None:
        for mode, payload in [
            ("delta", f),
            (
                "opcodes",
                f[:5] + [[[{"set": 0, "unset": 1, "append": 2}[op[0]]] + op[1:] for op in f[5]]],
            ),
        ]:
            try:
                result[mode] = dump([mode, payload])
            except Error:
                pass
    if revision == next_revision and same:
        result["unchanged"] = dump(["unchanged", [3, revision, sha(before)]])
    if not result:
        raise Error("No bounded handoff representation")
    return result


def select(before, after, revision, next_revision, *, measure=None):
    """Minimize supplied complete-wire cost; default UTF8 bytes, not tokens.
    measure is trusted local configuration. Its cost excludes any caller-owned
    prompt/schema provisioning; callers must account for those separately.
    """
    measure = measure or (lambda text: len(text.encode("utf-8")))
    wires = candidates(before, after, revision, next_revision)
    costs = {}
    for mode, wire in wires.items():
        value = measure(wire)
        if (
            type(value) not in (int, float)
            or (type(value) is float and not math.isfinite(value))
            or value < 0
        ):
            raise Error("Invalid measured cost")
        costs[mode] = value
    mode = min(costs, key=costs.get)
    return Selection(mode, wires[mode], costs[mode], tuple(costs.items()))


def receive(before, revision, wire):
    """Guard before selection/application; return a detached value and revision."""
    obj = load(wire)
    if type(obj) is not list or len(obj) != 2 or type(obj[0]) is not str:
        raise Error("Adaptive envelope")
    mode, payload = obj
    if mode == "snapshot":
        value = guarded_control(before, revision, dump(payload), "snapshot")
        return value, payload[2]
    if mode == "opcodes":
        if (
            type(payload) is not list
            or len(payload) != 6
            or type(payload[5]) is not list
            or len(payload[5]) > 256
        ):
            raise Error("Opcode envelope")
        ops = []
        for op in payload[5]:
            if type(op) is not list or not op or type(op[0]) is not int or op[0] not in (0, 1, 2):
                raise Error("Opcode")
            ops.append([("set", "unset", "append")[op[0]]] + op[1:])
        payload = payload[:5] + [ops]
        return apply(before, revision, payload)
    if mode == "delta":
        return apply(before, revision, payload)
    if mode != "unchanged":
        raise Error("Adaptive mode")
    if type(payload) is not list or len(payload) != 3:
        raise Error("Receipt envelope")
    version, rev, digest = payload
    # Reuse exact version/revision/hash validation, never rely on bool==int.
    structure([version, rev, rev, digest, digest, []])
    if type(revision) is not int or revision != rev or sha(before) != digest:
        raise Error("STALE_BASE")
    return load(dump(before)), rev
