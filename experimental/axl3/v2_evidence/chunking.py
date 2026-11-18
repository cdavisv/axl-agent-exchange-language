"""Lossless bounded AXL chunks: integrity/provenance framing, no truncation."""
import hashlib, json
from benchmark import encode, decode, SCHEMAS, render, ROOT, TOKENIZERS_ROOT
from axl import AxlParseError

def split_record(record, max_chars=2048):
    if record['prefix'] != 'NT' or set(record['fields']) != {'id', 'to'} or set(record['payload']) != {'summary'}:
        raise ValueError('Only benchmark NT schema supported')
    if max_chars < 1:
        raise ValueError('Positive chunk limit required')
    text = record['payload']['summary']
    digest = hashlib.sha256(text.encode()).hexdigest()
    out = []
    start = 0
    while start < len(text) or not out:
        end = min(start + max_chars, len(text))
        while True:
            meta = {'source_id': record['fields']['id'], 'sha256': digest, 'start': start, 'end': end, 'total_chars': len(text), 'text': text[start:end]}
            chunk = {'prefix': 'NT', 'fields': {'id': f"{record['fields']['id']}-c{len(out)}", 'to': record['fields']['to']}, 'payload': {'summary': json.dumps(meta, ensure_ascii=False, separators=(',', ':'))}}
            try:
                wire = encode(chunk, 'axl')
                if any((len(line.encode('utf-8')) > 8192 for line in wire.splitlines())):
                    raise AxlParseError('Explicit UTF-8 byte line cap exceeded')
                assert decode(wire, 'axl') == chunk
                break
            except AxlParseError:
                if end - start <= 1:
                    raise
                end = start + (end - start) // 2
        out.append(chunk)
        start = end
        if start == len(text):
            return out

def reassemble(chunks, *, expected_source_id=None, expected_sha256=None, expected_to=None):
    if not chunks:
        raise ValueError('Missing chunks')
    metas = [json.loads(c['payload']['summary']) for c in chunks]
    first = metas[0]
    pos = 0
    pieces = []
    to = chunks[0]['fields']['to']
    if expected_source_id is not None and first['source_id'] != expected_source_id:
        raise ValueError('Untrusted source identity')
    if expected_sha256 is not None and first['sha256'] != expected_sha256:
        raise ValueError('Untrusted content digest')
    if expected_to is not None and to != expected_to:
        raise ValueError('Unexpected recipient')
    for i, (c, m) in enumerate(zip(chunks, metas)):
        if c['prefix'] != 'NT' or c['fields'] != {'id': f"{first['source_id']}-c{i}", 'to': to}:
            raise ValueError('Envelope mismatch')
        if any((m[k] != first[k] for k in ('source_id', 'sha256', 'total_chars'))):
            raise ValueError('Provenance mismatch')
        if m['start'] != pos or m['end'] != pos + len(m['text']):
            raise ValueError('Missing or reordered segment')
        pieces.append(m['text'])
        pos = m['end']
    text = ''.join(pieces)
    if pos != first['total_chars'] or hashlib.sha256(text.encode()).hexdigest() != first['sha256']:
        raise ValueError('Integrity failure')
    return {'prefix': 'NT', 'fields': {'id': first['source_id'], 'to': to}, 'payload': {'summary': text}}

def experiment():
    from tokenizers import Tokenizer
    from jinja2 import Environment
    p = TOKENIZERS_ROOT / 'google--gemma-4-e2b-it'
    tok = Tokenizer.from_file(str(p / 'tokenizer.json'))
    template = Environment().from_string((p / 'chat_template.jinja').read_text())

    def count(s):
        return len(tok.encode(template.render(messages=[{'role': 'user', 'content': s}], bos_token='<bos>', add_generation_prompt=True, tools=None, enable_thinking=False), add_special_tokens=False).ids)
    cases = {'ascii_source': 'def example(x):\n    return x + 1\n' * 500, 'unicode_escaped': '你好🦊 "\\\n' * 1500}
    rows = []
    for name, text in cases.items():
        r = {'prefix': 'NT', 'fields': {'id': 'source-e1', 'to': '@fixer'}, 'payload': {'summary': text}}
        chunks = split_record(r)
        assert reassemble(chunks) == r
        for mode in SCHEMAS:
            wires = [encode(c, mode) for c in chunks]
            schema = 'Each summary encodes a JSON chunk with source_id, sha256 of full UTF-8 text, start/end character offsets, total_chars, text. Reassemble contiguous ordered chunks; reject checksum or provenance mismatch.\n'
            tokens = count(schema + render(mode, wires))
            unchunked = None if mode == 'axl' else count(render(mode, [encode(r, mode)]))
            rows.append({'case': name, 'format': mode, 'utf8_bytes': len(text.encode()), 'chunks': len(chunks), 'chunked_input_tokens': tokens, 'unchunked_input_tokens': unchunked, 'metadata_and_chunking_cost': tokens - unchunked if unchunked is not None else None})
    (ROOT / 'chunking-results.json').write_text(json.dumps(rows, indent=2))
if __name__ == '__main__':
    experiment()
