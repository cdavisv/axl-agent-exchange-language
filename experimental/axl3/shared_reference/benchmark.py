"""Synthetic shared-field encoder CPU diagnostic; no token or model claims."""

import importlib.util, sys, random, time, statistics, json, hashlib, platform
from pathlib import Path

P = Path(__file__).parent


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


b = module("old_shared", P / "baseline_axl3.py")
c = module("new_shared", P.parent / "axl3.py")


def schema(m):
    return m.Schema(
        "shared.reference.v1",
        (("id", "integer", True), ("shared", "any", False), ("other", "string", True)),
    )


def outcome(fn):
    try:
        return ("ok", fn())
    except Exception as e:
        return (type(e).__name__, str(e))


bs, cs = schema(b), schema(c)
rng = random.Random(674301)
fixtures = []
for kind, value in [
    ("scalar", True),
    ("short", "same value"),
    ("long", "αβγ" * 300),
    ("nested", {"text": ["x" * 30] * 8, "codes": list(range(20))}),
]:
    for count in [1, 8, 64]:
        records = [{"id": i, "shared": value, "other": str(i)} for i in range(count)]
        for shared in [(), ("shared",)]:
            fixtures.append((kind, count, shared, records))
checks = 0
for value in [
    None,
    True,
    False,
    0,
    1,
    1.0,
    -0.0,
    "1",
    "true",
    "\ud800",
    float("inf"),
    [],
    {},
    [1],
    {"a": 1, "b": 2},
    {"b": 2, "a": 1},
]:
    for other in [value, None, False, 0, 0.0, "1", {}, []]:
        records = [
            {"id": 0, "shared": value, "other": "a"},
            {"id": 1, "shared": other, "other": "b"},
        ]
        for shared in [(), ("shared",), ("other", "shared")]:
            a = outcome(lambda: b.pack(records, bs, shared))
            z = outcome(lambda: c.pack(records, cs, shared))
            assert a == z, (a, z)
            checks += 1
for n in [0, 1, 2, 1024, 1025]:
    for shared in [(), ("shared",), ("id", "id"), ("unknown",), "shared"]:
        records = [{"id": i, "shared": [], "other": "a"} for i in range(n)]
        assert outcome(lambda: b.pack(records, bs, shared)) == outcome(
            lambda: c.pack(records, cs, shared)
        )
        checks += 1
rows = []
for kind, count, shared, records in fixtures:
    wire = b.pack(records, bs, shared)
    assert c.pack(records, cs, shared) == wire
    assert b.unpack(wire, b.registry(bs)) == c.unpack(wire, c.registry(cs)) == records
    for _ in range(3):
        b.pack(records, bs, shared)
        c.pack(records, cs, shared)
    times = {"baseline": [], "candidate": []}
    for _ in range(31):
        order = [("baseline", b, bs), ("candidate", c, cs)]
        rng.shuffle(order)
        repeats = 100 if count == 1 else (10 if count == 8 else 3)
        for label, m, s in order:
            start = time.perf_counter_ns()
            for _ in range(repeats):
                actual = m.pack(records, s, shared)
            elapsed = (time.perf_counter_ns() - start) / repeats
            assert actual == wire
            times[label].append(elapsed)
    med = {k: statistics.median(v) for k, v in times.items()}
    rows.append(
        {
            "kind": kind,
            "rows": count,
            "sharing": bool(shared),
            "wire_bytes": len(wire.encode()),
            "times_ns": times,
            "median_ns": med,
            "speedup": med["baseline"] / med["candidate"],
        }
    )
result = {
    "baseline_commit": "2130df30837885af91cde693c6953cafc5cfc3f3",
    "baseline_sha256": hashlib.sha256((P / "baseline_axl3.py").read_bytes()).hexdigest(),
    "python": platform.python_version(),
    "differential_cases": checks,
    "repetitions": 31,
    "scope": "Complete pack, synthetic CPU only; exact wire and decoded equality. Same shared value choice and validation. No tokenizer, inference, I/O or billing. Warm reusable schemas. Retains all nonsharing and one-row controls.",
    "cases": rows,
}
(P / "results.json").write_text(json.dumps(result, indent=2) + "\n")
print(
    json.dumps(
        [{k: v for k, v in row.items() if k not in ["times_ns", "median_ns"]} for row in rows],
        indent=2,
    )
)
