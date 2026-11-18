"""Paired wire-format experiment, NOT an agent/coding benchmark."""
import json, sys, hashlib, random, statistics, os
from pathlib import Path
ROOT = Path(__file__).resolve().parent
AXL_REPO = Path(os.environ.get('AXL_REPO', str(ROOT.parents[2])))
TOKENIZERS_ROOT = Path(os.environ.get('AXL_TOKENIZER_DIR', str(ROOT / 'tokenizers')))
sys.path.insert(0, str(AXL_REPO / 'src'))
from axl import build_axl_message, parse_axl_message
from tokenizers import Tokenizer
from jinja2 import Environment
SCHEMAS = {'shared_json': 'Evidence is a JSON object with prefix and to applying to every row; rows are [id,summary] arrays. NT is a note; id identifies it; to is recipient; summary contains exact source evidence. Preserve source content exactly.', 'array_json': 'Evidence messages are JSON arrays [prefix,id,to,summary]. NT is a note; id identifies it; to is recipient; summary contains exact source evidence. Preserve source content exactly.', 'flat_json': 'Evidence messages are flat JSON objects with prefix, id, to, and summary. NT is a note; id identifies it; to is recipient; summary contains exact source evidence. Preserve source content exactly.', 'json': 'Evidence messages are JSON objects with prefix, fields, and payload. NT is a note; id identifies it; to is recipient; summary contains exact source evidence. Preserve source content exactly.', 'axl': 'Evidence messages use AXL: NT: id=<id>; to=<recipient> followed by an indented summary=<JSON string>. NT is a note; id identifies it; to is recipient; summary contains exact source evidence. Preserve source content exactly.'}

def encode(obj, mode):
    if mode in ('array_json', 'shared_json'):
        return json.dumps([obj['prefix'], obj['fields']['id'], obj['fields']['to'], obj['payload']['summary']], ensure_ascii=False, separators=(',', ':'))
    if mode == 'flat_json':
        return json.dumps({'prefix': obj['prefix'], **obj['fields'], **obj['payload']}, ensure_ascii=False, separators=(',', ':'))
    if mode == 'json':
        return json.dumps(obj, ensure_ascii=False, separators=(',', ':'))
    return build_axl_message(obj['prefix'], fields=obj['fields'], payload=obj['payload'], strict=True)

def decode(s, mode):
    if mode in ('array_json', 'shared_json'):
        p, i, t, v = json.loads(s)
        return {'prefix': p, 'fields': {'id': i, 'to': t}, 'payload': {'summary': v}}
    if mode == 'flat_json':
        o = json.loads(s)
        return {'prefix': o['prefix'], 'fields': {'id': o['id'], 'to': o['to']}, 'payload': {'summary': o['summary']}}
    if mode == 'json':
        return json.loads(s)
    m = parse_axl_message(s, strict=True)
    return {'prefix': m.prefix, 'fields': m.fields, 'payload': m.payload}

def render(mode, wires):
    if mode == 'shared_json':
        rows = [json.loads(w) for w in wires]
        if rows:
            prefix, to = (rows[0][0], rows[0][2])
            assert all((r[0] == prefix and r[2] == to for r in rows))
        else:
            prefix, to = ('NT', '@fixer')
        text = json.dumps({'prefix': prefix, 'to': to, 'rows': [[r[1], r[3]] for r in rows]}, ensure_ascii=False, separators=(',', ':'))
    else:
        text = '\n'.join(wires)
    return SCHEMAS[mode] + '\n' + text

def corpus():
    raw = (ROOT / 'corpus.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != '1284a65dab14639f432f632c36be97bc6daa1b304f38c5ee943ac3587c87f19f':
        raise ValueError('Frozen public corpus hash mismatch')
    return json.loads(raw)

def run():
    records = corpus()
    results = []
    for folder in sorted(TOKENIZERS_ROOT.iterdir()):
        tok = Tokenizer.from_file(str(folder / 'tokenizer.json'))
        source = json.loads((folder / 'source.json').read_text())
        template_path = folder / 'chat_template.jinja'
        template = Environment().from_string(template_path.read_text()) if template_path.exists() else None

        def frame(s):
            if template is None:
                return s
            return template.render(messages=[{'role': 'user', 'content': s}], bos_token='<bos>', add_generation_prompt=True, tools=None, enable_thinking=False)
        n = lambda s: len(tok.encode(frame(s), add_special_tokens=False).ids)
        for seed in range(30):
            ranked = random.Random(seed).sample(records, len(records))
            wires = {mode: [encode(r, mode) for r in ranked] for mode in SCHEMAS}
            for mode in SCHEMAS:
                for obj, wire in zip(ranked, wires[mode]):
                    assert decode(wire, mode) == obj
            for mode in SCHEMAS:
                fixed = render(mode, wires[mode][:20])
                results.append(dict(model=source['model'], seed=seed, arm={'axl': 'B', 'json': 'A', 'flat_json': 'E', 'array_json': 'G', 'shared_json': 'I'}[mode], mode=mode, budget=None, records=20, tokens=n(fixed), schema_tokens=n(SCHEMAS[mode]), retries=0, agent_success=None))
                for cap in [512, 1024, 2048, 4096, 8192]:
                    prompt = render(mode, [])
                    k = 0
                    for wire in wires[mode]:
                        candidate = render(mode, wires[mode][:k + 1])
                        if n(candidate) > cap:
                            break
                        prompt = candidate
                        k += 1
                    results.append(dict(model=source['model'], seed=seed, arm={'axl': 'D', 'json': 'C', 'flat_json': 'F', 'array_json': 'H', 'shared_json': 'J'}[mode], mode=mode, budget=cap, records=k, tokens=n(prompt), schema_tokens=n(SCHEMAS[mode]), retries=0, agent_success=None))
    (ROOT / 'results.json').write_text(json.dumps(results, indent=2))
    summary = []
    for model in sorted({r['model'] for r in results}):
        rows = [r for r in results if r['model'] == model]
        a = [r['tokens'] for r in rows if r['arm'] == 'A']
        b = [r['tokens'] for r in rows if r['arm'] == 'B']
        item = {'model': model, 'fixed_json_mean_tokens': statistics.mean(a), 'fixed_axl_mean_tokens': statistics.mean(b), 'paired_mean_saving_pct': statistics.mean([(x - y) / x * 100 for x, y in zip(a, b)]), 'capacity': []}
        for cap in [512, 1024, 2048, 4096, 8192]:
            c = [r['records'] for r in rows if r['arm'] == 'C' and r['budget'] == cap]
            d = [r['records'] for r in rows if r['arm'] == 'D' and r['budget'] == cap]
            item['capacity'].append({'cap': cap, 'json_mean_records': statistics.mean(c), 'axl_mean_records': statistics.mean(d), 'axl_more': sum((y > x for x, y in zip(c, d))), 'tie': sum((y == x for x, y in zip(c, d))), 'axl_fewer': sum((y < x for x, y in zip(c, d)))})
        e = [r['tokens'] for r in rows if r['arm'] == 'E']
        item['flat_json_mean_tokens'] = statistics.mean(e)
        item['axl_saving_vs_flat_json_pct'] = statistics.mean([(x - y) / x * 100 for x, y in zip(e, b)])
        for capitem in item['capacity']:
            capitem['flat_json_mean_records'] = statistics.mean([r['records'] for r in rows if r['arm'] == 'F' and r['budget'] == capitem['cap']])
        g = [r['tokens'] for r in rows if r['arm'] == 'G']
        item['array_json_mean_tokens'] = statistics.mean(g)
        item['axl_saving_vs_array_json_pct'] = statistics.mean([(x - y) / x * 100 for x, y in zip(g, b)])
        for capitem in item['capacity']:
            capitem['array_json_mean_records'] = statistics.mean([r['records'] for r in rows if r['arm'] == 'H' and r['budget'] == capitem['cap']])
        shared = [r['tokens'] for r in rows if r['arm'] == 'I']
        item['shared_json_mean_tokens'] = statistics.mean(shared)
        item['axl_saving_vs_shared_json_pct'] = statistics.mean([(x - y) / x * 100 for x, y in zip(shared, b)])
        for capitem in item['capacity']:
            capitem['shared_json_mean_records'] = statistics.mean([r['records'] for r in rows if r['arm'] == 'J' and r['budget'] == capitem['cap']])
        summary.append(item)
    (ROOT / 'summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
if __name__ == '__main__':
    run()
