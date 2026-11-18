"""Local public synthetic fixtures only; not a JTON implementation/benchmark."""
import json
from pathlib import Path
cases = {'dense': [{'id': 1, 'value': '001'}, {'id': 2, 'value': '002'}], 'absent_vs_null': [{'id': 1, 'value': None}, {'id': 2}], 'seventy_percent': [{'id': i, 'value': None} for i in range(7)] + [{'id': i} for i in range(7, 10)], 'key_order': [{'id': 1, 'value': 'x'}, {'value': 'y', 'id': 2}], 'reserved_strings': [{'value': v} for v in ['true', 'false', 'null', 'NaN', 'Infinity', '001', '1e2', '']], 'delimiters': [{'value': v} for v in ['a;b', 'a,b', 'a\tb', 'a|b', 'a\nb', '"quoted"', '\\', '日本語']], 'nested': [{'id': 1, 'value': {'a': [None, True, 'true']}}, {'id': 2, 'value': {'a': []}}], 'numbers': [{'value': v} for v in [0, -0.0, 9007199254740993, 1e-20]], 'empty': [], 'single': [{'id': 1}]}

def same(a, b):
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all((same(a[k], b[k]) for k in a))
    if isinstance(a, list):
        return len(a) == len(b) and all((same(x, y) for x, y in zip(a, b)))
    if isinstance(a, float) and a == 0:
        return str(a) == str(b)
    return a == b
report = []
for name, data in cases.items():
    wire = json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    assert same(data, json.loads(wire))
    eligible = len(data) >= 2 and all((isinstance(x, dict) and list(x) == list(data[0]) for x in data))
    report.append({'case': name, 'compact_json_bytes': len(wire.encode()), 'spec_grid_eligible': eligible, 'strict_json_roundtrip': True})
root = Path(__file__).resolve().parent
(root / 'fixtures.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
(root / 'preflight-results.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps(report, indent=2))
