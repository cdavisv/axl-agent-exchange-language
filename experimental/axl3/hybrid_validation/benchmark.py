from itertools import islice
import importlib.util, sys, random, time, statistics, tracemalloc, json, math
from pathlib import Path

P = Path(__file__).parent
spec = importlib.util.spec_from_file_location("baseline", P / "baseline_axl3.py")
b = importlib.util.module_from_spec(spec)
sys.modules["baseline"] = b
spec.loader.exec_module(b)
sys.path.insert(0, str(P.parent))
import axl3

hybrid = axl3.validate_value
MAX_DEPTH = b.MAX_DEPTH
MAX_NODES = b.MAX_NODES


def outcome(fn, v):
    try:
        return ("ok", fn(v))
    except Exception as e:
        return (type(e).__name__, str(e))


rng = random.Random(54329)


def val(depth=0):
    if depth > 4 or rng.random() < 0.55:
        return rng.choice([None, True, 42, 1.25, "hello", float("inf"), "\ud800", object()])
    if rng.random() < 0.5:
        return [val(depth + 1) for _ in range(rng.randrange(8))]
    return {str(i): val(depth + 1) for i in range(rng.randrange(8))}


cases = [val() for _ in range(10000)]
for n in [0, 1, 127, 128, 129, 255, 256, 257, MAX_NODES - 1, MAX_NODES, MAX_NODES + 1, 100000]:
    cases.extend(
        [
            [0] * n,
            {"x": [0] * n},
            [object()] + [0] * n,
            [0] * n + [object()],
            {"first": object(), "wide": [0] * n},
            {"wide": [0] * n, "last": object()},
        ]
    )
for depth in range(35):
    x = 0
    for _ in range(depth):
        x = [x]
    cases.append(x)
for n in [127, 128, 129, 255, 256, 257, 4096]:
    for i in range(5):
        v = {str(k): 0 for k in range(n)}
        v[str(rng.randrange(n))] = rng.choice([float("inf"), "\ud800", object()])
        cases.append(v)
        v = [0] * n
        v[rng.randrange(n)] = [0] * 300
        cases.append(v)
cyclic = []
cyclic.append(cyclic)
cases.append(cyclic)
cyclic = {}
cyclic["x"] = cyclic
cases.append(cyclic)
cases.extend([{1: 0, "x": object()}, {"x": float("inf"), "y": "\ud800"}])
for i, v in enumerate(cases):
    a, c = (outcome(b.validate_value, v), outcome(hybrid, v))
    assert a == c, (i, a, c)
fixtures = {
    "scalar": 42,
    "tiny": {"x": 42, "y": ["a", True]},
    "list64": list(range(64)),
    "list256": list(range(256)),
    "list257": list(range(257)),
    "dict128": {str(i): i for i in range(128)},
    "dict129": {str(i): i for i in range(129)},
    "wide_valid": [0] * 10000,
    "records": [{"id": i, "text": "abc"} for i in range(1000)],
    "wide_rejected": [0] * 1000000,
    "dict_rejected": {str(i): 0 for i in range(100000)},
    "branching": [[[0] * 300] * 10] * 10,
}
results = {}
for name, v in fixtures.items():
    row = {}
    for label, fn in [("baseline", b.validate_value), ("hybrid", hybrid)]:
        tracemalloc.start()
        outcome(fn, v)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        row[label] = {"peak_aux_bytes": peak, "times": []}
    for i in range(21):
        order = [("baseline", b.validate_value), ("hybrid", hybrid)]
        rng.shuffle(order)
        for label, fn in order:
            count = (
                10000
                if name in ["scalar", "tiny"]
                else 100
                if name in ["list64", "list256", "list257", "dict128", "dict129"]
                else 3
            )
            t = time.perf_counter()
            for _ in range(count):
                outcome(fn, v)
            row[label]["times"].append((time.perf_counter() - t) / count)
    for label in row:
        row[label]["median_seconds"] = statistics.median(row[label]["times"])
    row["speedup"] = row["baseline"]["median_seconds"] / row["hybrid"]["median_seconds"]
    results[name] = row
output = {"differential_cases": len(cases), "results": results, "python": sys.version}
(P / "results.json").write_text(json.dumps(output, indent=2))
print(
    json.dumps(
        {
            k: (v["speedup"], v["baseline"]["peak_aux_bytes"], v["hybrid"]["peak_aux_bytes"])
            for k, v in results.items()
        },
        indent=2,
    )
)
