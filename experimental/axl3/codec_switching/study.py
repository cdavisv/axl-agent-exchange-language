"""Synthetic per-message codec selection; full mixed-grammar context cost."""
import argparse, hashlib, json, sys
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[3])
p.add_argument('--tokenizer', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
here = a.repo / 'experimental/axl3/typed_rows'
sys.path[:0] = [str(here), str(here.parent)]
from benchmark import COMMON, PROFILE
from typed_rows import encode, decode
from axl3 import Schema, dump, load, pack, registry, unpack
from tokenizers import Tokenizer
raw = (here / 'heldout-corpus.json').read_bytes()
assert hashlib.sha256(raw).hexdigest() == (here / 'heldout-corpus.sha256').read_text().strip()
tok = Tokenizer.from_file(str(a.tokenizer))
cost = lambda s: len(tok.encode(s, add_special_tokens=False).ids)
canon = lambda x: json.dumps(x, sort_keys=True, ensure_ascii=True)
obs = []
checks = 0
for case_id, c in enumerate(json.loads(raw)['cases']):
    s = Schema('heldout.' + c['family'] + '.v1', tuple(((n, t, True) for n, t in c['fields'])))
    reg = registry(s)
    setup = {m: COMMON + v + 'SCHEMA=' + dump(s.definition) + '\n' for m, v in PROFILE.items()}
    mixed = COMMON + PROFILE['typed_rows'] + PROFILE['guarded_packed_json'] + 'Dispatch @axl3t to typed rows; dispatch [ to guarded JSON.\nSCHEMA=' + dump(s.definition) + '\n'
    setup.update(hybrid_wire=mixed, hybrid_context=mixed)
    hist = dict(setup)
    for turn, records in enumerate(c['turns']):
        wires = {'typed_rows': encode(records, s, tuple(c['shared'])), 'guarded_packed_json': pack(records, s, tuple(c['shared']))}
        wires['negotiated_positional_json'] = dump(load(wires['guarded_packed_json'])[2:])
        for mode, wire in wires.items():
            got = decode(wire, reg) if mode == 'typed_rows' else unpack(wire if mode == 'guarded_packed_json' else dump([3, s.fingerprint, *load(wire)]), reg)
            assert canon(got) == canon(records)
            checks += 1
        candidates = ('guarded_packed_json', 'typed_rows')
        choices = {'hybrid_wire': min(candidates, key=lambda m: cost(wires[m])), 'hybrid_context': min(candidates, key=lambda m: cost(hist['hybrid_context'] + 'NEXT=' + wires[m]))}
        for m, choice in choices.items():
            wires[m] = wires[choice]
        measurements = {m: {'wire': cost(w), 'cold': cost(setup[m] + 'NEXT=' + w), 'retained_context': cost(hist[m] + 'NEXT=' + w)} for m, w in wires.items()}
        obs.append(dict(case_id=case_id, family=c['family'], turn=turn, choices=choices, costs=measurements))
        for m, w in wires.items():
            hist[m] += 'PREVIOUS=' + w + '\n'
summary = {str(n): {m: {metric: sum((o['costs'][m][metric] for o in obs if o['turn'] < n)) for metric in ('wire', 'cold', 'retained_context')} for m in setup} for n in (3, 8, 16)}
result = dict(scope='Synthetic tokenizer-only host-side selection. Both mixed grammars and schema counted once in each retained input. No model generation, inference, retry, output billing or selection CPU cost. Online context selector is greedy, not globally optimal. Negotiated positional JSON has different out-of-band identity contract. Corpus already observed: diagnostic not new heldout evidence.', tokenizer_sha256=hashlib.sha256(a.tokenizer.read_bytes()).hexdigest(), corpus_sha256=hashlib.sha256(raw).hexdigest(), checks=checks, summary=summary, observations=obs)
a.output.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({k: v for k, v in result.items() if k != 'observations'}, indent=2))
