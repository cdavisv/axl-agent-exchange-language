import importlib.util, sys, json, random, statistics, time, tracemalloc
from pathlib import Path

P = Path(__file__).parent


def mod(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    sys.modules[name] = m
    s.loader.exec_module(m)
    return m


b = mod("old", P / "baseline_axl3.py")
c = mod("new", P.parent / "axl3.py")


def result(f, x):
    try:
        return ("ok", f(x))
    except Exception as e:
        return (type(e).__name__, str(e))


rng = random.Random(74963)
checks = 0
for size in [
    2047,
    2048,
    2049,
    4095,
    4096,
    4097,
    8191,
    8192,
    16383,
    16384,
    32765,
    32766,
    32767,
    32768,
    32769,
]:
    for mode in ["list", "dict"]:
        for bad in [None, "front", "middle", "end", "nonstringkey"]:
            x = [0] * size if mode == "list" else {str(i): 0 for i in range(size)}
            if bad in ["front", "middle", "end"]:
                pos = {"front": 0, "middle": size // 2, "end": size - 1}[bad]
                x[pos if mode == "list" else str(pos)] = rng.choice(
                    [float("nan"), "\ud800", object()]
                )
            elif bad == "nonstringkey" and mode == "dict":
                x[42] = 0
            for outer in [
                lambda x: x,
                lambda x: {"x": x, "z": [1, 2]},
                lambda x: [object(), x],
                lambda x: [x, object()],
                lambda x: [x, x],
            ]:
                v = outer(x)
                assert result(b.validate_value, v) == result(c.validate_value, v)
                checks += 1
results = {}
for name, value in [
    ("scalar", 42),
    ("small", {"id": 1, "message": "hello", "ok": True}),
    ("nested", {"a": [{"x": i, "y": [None, False]} for i in range(100)]}),
    ("wide", [0] * 8192),
    ("boundary", [0] * 4097),
]:
    for operation in ["dump", "load", "roundtrip"]:
        text = b.dump(value)
        funcs = {
            "dump": lambda m: m.dump(value),
            "load": lambda m: m.load(text),
            "roundtrip": lambda m: m.axl_to_json(m.json_to_axl(text)),
        }
        fn = funcs[operation]
        assert fn(b) == fn(c)
        count = 500 if name in ["scalar", "small"] else 5
        times = {"baseline": [], "candidate": []}
        for i in range(21):
            order = [("baseline", b), ("candidate", c)]
            rng.shuffle(order)
            for label, m in order:
                t = time.perf_counter()
                for _ in range(count):
                    fn(m)
                times[label].append((time.perf_counter() - t) / count)
        results[name + "/" + operation] = {
            "speedup": statistics.median(times["baseline"]) / statistics.median(times["candidate"]),
            "times": times,
        }
out = {"holdout_checks": checks, "results": results}
(P / "holdout-results.json").write_text(json.dumps(out, indent=2))
print(checks)
print(json.dumps({k: round(v["speedup"], 3) for k, v in results.items()}, indent=2))
