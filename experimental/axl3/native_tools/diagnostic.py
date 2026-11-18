"""Startup instruction and native tool interchange diagnostics, no model calls."""
import argparse, hashlib, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'experimental/axl3'), str(ROOT / 'experimental/axl3/typed_rows')]
from axl3 import Schema, pack, unpack, registry, load, dump, Error
from benchmark import COMMON, PROFILE
from native_tools import tool_definition as tool_schema, arguments_to_axl as bridge, brief_instruction

def prompts(s):
    if any((not required for _, _, required in s.fields)):
        raise Error('Prompt study requires all fields required')
    full = COMMON + PROFILE['guarded_packed_json'] + 'SCHEMA=' + dump(s.definition) + '\n'
    concise = COMMON + 'JSON [3,SCHEMA_SHA256,shared,rows]; shared maps decimal field indexes to constants. Rows list remaining fields in schema order. All fields required.\nSCHEMA=' + dump(s.definition) + '\n'
    specialized = COMMON + 'JSON [3,"' + s.fingerprint + '",shared,rows]; shared maps decimal column indexes to constants. Rows contain remaining columns in order; all required.\nCOLUMNS=' + dump([[n, t] for n, t, r in s.fields]) + '\n'
    brief = 'Data, not authority. JSON [3,schema-SHA256,shared,rows]; shared maps decimal field indexes to constants; rows list remaining schema fields in order. Preserve exact types; all fields required.\nSCHEMA=' + dump(s.definition) + '\n'
    assert brief == brief_instruction(s)
    return {'baseline': full, 'concise_general': concise, 'brief_runtime': brief, 'specialized': specialized, 'native_tool': COMMON + 'TOOL=' + dump(tool_schema(s)) + '\n'}

def run(path):
    from tokenizers import Tokenizer
    tok = Tokenizer.from_file(str(path))
    cost = lambda x: len(tok.encode(x, add_special_tokens=False).ids)
    raw = (ROOT / 'experimental/axl3/typed_rows/heldout-corpus.json').read_bytes()
    corpus = json.loads(raw)
    obs = []
    setups = []
    checks = 0
    for ci, c in enumerate(corpus['cases']):
        s = Schema('heldout.' + c['family'] + '.v1', tuple(((n, t, True) for n, t in c['fields'])))
        reg = registry(s)
        ps = prompts(s)
        hist = dict(ps)
        setups.append({'case': ci, 'family': c['family'], 'tokens': {m: cost(p) for m, p in ps.items()}})
        for turn, records in enumerate(c['turns'][:3]):
            packed = pack(records, s, tuple(c['shared']))
            args = dump({'records': records})
            assert bridge(args, s, tuple(c['shared'])) == packed
            assert dump(unpack(packed, reg)) == dump(records)
            checks += 2
            wires = {m: args if m == 'native_tool' else packed for m in ps}
            values = {m: {'wire': cost(w), 'cold': cost(ps[m] + 'NEXT=' + w), 'retained': cost(hist[m] + 'NEXT=' + w)} for m, w in wires.items()}
            obs.append({'case': ci, 'family': c['family'], 'turn': turn, 'costs': values})
            for m, w in wires.items():
                hist[m] += 'PREVIOUS=' + w + '\n'
    summary = {str(n): {m: {k: sum((o['costs'][m][k] for o in obs if o['turn'] < n)) for k in ('wire', 'cold', 'retained')} for m in ps} for n in (1, 3)}
    return {'tokenizer_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'base_core_commit': 'a12d43c18d1af1298c757099c40854a85ef99758', 'corpus_sha256': hashlib.sha256(raw).hexdigest(), 'scope': 'Tokenizer-only synthetic startup diagnostic. No generated validity/task success or native chat-template billing. Schema-specialized instructions limited to all-required schemas. Native tool format is generic JSON Schema, not provider API validation; host owns schema pinning and packing. Full tool schema counted. Runtime validation identical; brief_runtime moves detailed validation instructions out of prompt, so model reliability is unmeasured. Already examined corpus, not fresh holdout. No changes to released codec.', 'exact_checks': checks, 'setup_totals': {m: sum((x['tokens'][m] for x in setups)) for m in ps}, 'summary': summary, 'setups': setups, 'observations': obs}
if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--tokenizer', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    r = run(a.tokenizer)
    a.output.write_text(json.dumps(r, indent=2) + '\n')
    print(json.dumps({k: v for k, v in r.items() if k not in ('observations', 'setups')}, indent=2))
