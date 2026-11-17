"""Bounded opt-in shared-field planner. Equivalent packed JSON uses the same wire."""

from dataclasses import dataclass
from itertools import combinations
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from axl3 import Error, MAX_ROWS, dump, load, pack


@dataclass(frozen=True)
class Plan:
    shared: tuple
    wire: str
    cost: int | float
    evaluations: int
    exhaustive: bool


def plan_shared(records, schema, *, measure=None, max_evaluations=256):
    """Choose the cheapest offered legal sharing configuration.

    measure is trusted local code and can price the full prompt/context. Default
    cost is UTF-8 wire bytes, not tokens. Enumeration is exhaustive only when
    2**constant_columns fits the budget. Otherwise try none/all, singletons,
    all-but-one, then pairs, bounded by max_evaluations. No optimality claim for
    budget-limited search. Budget counts attempted configurations, including invalid
    wires. Exhaustive means schema-ordered subsets, not alternative key orders or
    encodings. Snapshot inputs before invoking the cost callback.
    """
    if type(max_evaluations) is not int or not 2 <= max_evaluations <= 1024:
        raise Error("Planning budget must be an integer from 2 to 1024")
    if type(records) is not list or len(records) > MAX_ROWS:
        raise Error("Row limit/type")
    rows = load(dump(records))
    for row in rows:
        schema.check(row)
    constants = tuple(
        name
        for name, _, _ in schema.fields
        if rows
        and all(name in row for row in rows)
        and all(dump(row[name]) == dump(rows[0][name]) for row in rows)
    )
    measure = measure or (lambda wire: len(wire.encode("utf-8")))
    exhaustive = (1 << len(constants)) <= max_evaluations

    def configurations():
        yield ()
        yield constants
        if exhaustive:
            for width in range(1, len(constants)):
                yield from combinations(constants, width)
        else:
            for name in constants:
                yield (name,)
            for name in constants:
                yield tuple(other for other in constants if other != name)
            yield from combinations(constants, 2)

    seen = set()
    best = None
    attempts = 0
    for shared in configurations():
        if shared in seen:
            continue
        if attempts >= max_evaluations:
            break
        seen.add(shared)
        attempts += 1
        try:
            wire = pack(rows, schema, shared)
        except Error:
            continue  # Common input already validated; this wire may exceed bounds.
        cost = measure(wire)
        if (
            type(cost) not in (int, float)
            or cost < 0
            or (type(cost) is float and not math.isfinite(cost))
        ):
            raise Error("Invalid measured cost")
        if best is None or cost < best[2]:
            best = (shared, wire, cost)
    if best is None:
        raise Error("No bounded sharing configuration")
    return Plan(*best, attempts, exhaustive)
