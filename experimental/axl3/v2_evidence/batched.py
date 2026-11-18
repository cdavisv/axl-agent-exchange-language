"""Symmetric batching ablation. No inference."""
import json, random, statistics
from benchmark import ROOT, TOKENIZERS_ROOT, corpus, build_axl_message, parse_axl_message
from tokenizers import Tokenizer
from jinja2 import Environment
SCHEMAS = {'json_rows': 'Evidence is JSON {prefix,to,rows}; prefix and recipient apply to every [id,summary] row. NT means note. Summary contains exact source evidence. Preserve source content and row order exactly.', 'json_map': 'Evidence is JSON {prefix,to,rows}; prefix and recipient apply to every entry in rows, an ordered map from id to summary. NT means note. Summary contains exact source evidence. Preserve source content and entry order exactly.', 'axl_batch': 'Evidence is AXL NT: id=batch; to=<recipient>, then indented payload entries <id>=<JSON summary string>. Prefix and recipient apply to every entry; batch is a transport ID. NT means note. Summary contains exact source evidence. Preserve source content and entry order exactly.'}

def encode(records, mode):
    if records:
        p, t = (records[0]['prefix'], records[0]['fields']['to'])
        if not all((r['prefix'] == p and r['fields']['to'] == t for r in records)):
            raise ValueError('Mixed envelope')
    else:
        p, t = ('NT', '@fixer')
    ids = [r['fields']['id'] for r in records]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate source ID')
    rows = {r['fields']['id']: r['payload']['summary'] for r in records}
    if mode == 'axl_batch':
        return build_axl_message(p, fields={'id': 'batch', 'to': t}, payload=rows, strict=True)
    if mode == 'json_rows':
        rows = list(map(list, rows.items()))
    return json.dumps({'prefix': p, 'to': t, 'rows': rows}, ensure_ascii=False, separators=(',', ':'))

def decode(s, mode):
    if mode == 'axl_batch':
        m = parse_axl_message(s, strict=True)
        p, t, rows = (m.prefix, m.fields['to'], list(m.payload.items()))
    else:
        m = json.loads(s)
        p, t = (m['prefix'], m['to'])
        rows = m['rows'] if mode == 'json_rows' else list(m['rows'].items())
    return [{'prefix': p, 'fields': {'id': i, 'to': t}, 'payload': {'summary': v}} for i, v in rows]

def run():
    p = TOKENIZERS_ROOT / 'google--gemma-4-e2b-it'
    tok = Tokenizer.from_file(str(p / 'tokenizer.json'))
    template = Environment().from_string((p / 'chat_template.jinja').read_text())

    def count(s):
        return len(tok.encode(template.render(messages=[{'role': 'user', 'content': s}], bos_token='<bos>', add_generation_prompt=True, tools=None, enable_thinking=False), add_special_tokens=False).ids)

    def prompt(r, mode):
        return SCHEMAS[mode] + '\n' + encode(r, mode)
    records = corpus()
    datasets = {'mixed': records, 'axl': [r for r in records if r['payload']['summary'].startswith('axl/')], 'click': [r for r in records if r['payload']['summary'].startswith('click/')]}
    results = []
    for source, records in datasets.items():
        for seed in range(30):
            ranked = random.Random(seed).sample(records, len(records))
            for mode in SCHEMAS:
                selected = ranked[:20]
                wire = encode(selected, mode)
                assert decode(wire, mode) == selected
                results.append({'corpus': source, 'seed': seed, 'format': mode, 'cap': None, 'records': 20, 'tokens': count(prompt(selected, mode)), 'agent_success': None})
                for cap in [512, 1024, 2048, 4096, 8192]:
                    selected = []
                    for r in ranked:
                        trial = selected + [r]
                        if count(prompt(trial, mode)) > cap:
                            break
                        selected = trial
                    assert decode(encode(selected, mode), mode) == selected
                    results.append({'corpus': source, 'seed': seed, 'format': mode, 'cap': cap, 'records': len(selected), 'tokens': count(prompt(selected, mode)), 'agent_success': None})
    (ROOT / 'batched-results.json').write_text(json.dumps(results, indent=2))
    summary = []
    for source in datasets:
        rows = [r for r in results if r['corpus'] == source]
        item = {'corpus': source, 'corpus_records': len(datasets[source]), 'formats': {}}
        axl = [r['tokens'] for r in rows if r['format'] == 'axl_batch' and r['cap'] is None]
        for mode in SCHEMAS:
            fixed = [r['tokens'] for r in rows if r['format'] == mode and r['cap'] is None]
            item['formats'][mode] = {'fixed_mean_tokens': statistics.mean(fixed), 'axl_more_tokens_pct': statistics.mean([(a - j) / j * 100 for a, j in zip(axl, fixed)]), 'capacity': {cap: statistics.mean((r['records'] for r in rows if r['format'] == mode and r['cap'] == cap)) for cap in [512, 1024, 2048, 4096, 8192]}}
        summary.append(item)
    (ROOT / 'batched-summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
if __name__ == '__main__':
    run()
