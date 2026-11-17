from pathlib import Path
import importlib.util, sys, json, random, time, statistics, hashlib

ROOT = Path(__file__).parent
source = (ROOT / "baseline_axl3.py").read_text()


def module(name):
    s = importlib.util.spec_from_file_location(
        name, (ROOT / "baseline_axl3.py") if name == "baseline" else ROOT.parent / "axl3.py"
    )
    m = importlib.util.module_from_spec(s)
    sys.modules[name] = m
    s.loader.exec_module(m)
    return m


b, c = module("baseline"), module("deferred")
schema = b.Schema("budget", (("x", "any", True),))
cs = c.Schema("budget", (("x", "any", True),))
regs = {b: b.registry(schema), c: c.registry(cs)}
cases = {}
for n, rows in [(100, 10), (1000, 20), (1000, 33), (2000, 100), (8000, 100), (16000, 100)]:
    cases[f"list-{n}-rows-{rows}"] = b.dump([3, schema.fingerprint, {"0": [0] * n}, [[]] * rows])
for n in (32763, 32764, 32765, 32766):
    # Single shared list values at node boundary also test load-envelope constraints.
    try:
        cases[f"near-bound-{n}"] = b.dump([3, schema.fingerprint, {"0": [0] * n}, [[]]])
    except b.Error:
        pass
rng = random.Random(17013)
for i in range(200):
    n = rng.randrange(1, 100)
    rows = rng.randrange(0, 50)
    v = rng.choice([None, False, 0, 1.0, "é", {"a": [None, True, "0"]}, list(range(n))])
    cases[f"random-{i}"] = b.dump([3, schema.fingerprint, {"0": v}, [[]] * rows])


def run(m, w):
    try:
        return ("ok", json.dumps(m.unpack(w, regs[m]), ensure_ascii=False, separators=(",", ":")))
    except m.Error as e:
        return ("reject", str(e))


results = []
for name, w in cases.items():
    old, new = run(b, w), run(c, w)
    assert old == new, name
    if name.startswith("random"):
        continue
    timings = {b: [], c: []}
    copies = {}
    for m in (b, c):
        orig = m.copy.deepcopy
        counter = [0]

        def counted(v):
            counter[0] += 1
            return orig(v)

        m.copy.deepcopy = counted
        run(m, w)
        m.copy.deepcopy = orig
        copies[m.__name__] = counter[0]
    for repeat in range(11):
        order = [b, c]
        rng.shuffle(order)
        for m in order:
            t = time.perf_counter()
            run(m, w)
            timings[m].append(time.perf_counter() - t)
    results.append(
        {
            "case": name,
            "outcome": old[0],
            "wire_bytes": len(w.encode()),
            "deepcopies": copies,
            "baseline_median_s": statistics.median(timings[b]),
            "candidate_median_s": statistics.median(timings[c]),
            "ratio": statistics.median(timings[b]) / statistics.median(timings[c]),
        }
    )
out = {
    "source_commit": "8743a6839fe5dcb96731564ed29d8fe8f2312773",
    "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
    "agreement_cases": len(cases),
    "results": results,
}
(ROOT / "results.json").write_text(json.dumps(out, indent=2))
print(json.dumps(out, indent=2))
