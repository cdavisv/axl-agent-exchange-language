"""Verify packaged files against the archive manifest; no inference or downloads."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parent
manifest = json.loads((root / 'archive-provenance.json').read_text())
for relative, expected in manifest['files'].items():
    actual = hashlib.sha256((root / relative).read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit('Archive hash mismatch: ' + relative)
print(str(len(manifest['files'])) + ' archived file hashes verified')
