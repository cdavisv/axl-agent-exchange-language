"""Readable grouped-act offshoot; no change to baseline candidate/surface."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "surface"))
from surface import encode as encode_lines, decode as decode_lines, bound, ACTS
from axl3 import Error, MAX_ROWS


def encode(records, schema, shared=()):
    lines = encode_lines(records, schema, shared).split("\n")
    out = [lines[0].replace("@axl3 ", "@axl3b ", 1)]
    current = None
    for line in lines[1:]:
        if line.startswith("="):
            out.append(line)
            continue
        act, sep, values = line.partition(" | ")
        if not sep:
            raise Error("Internal act frame")
        if act != current:
            out.append(act + ":")
            current = act
        out.append("  " + values)
    text = "\n".join(out)
    bound(text)
    return text


def decode(text, schemas):
    bound(text)
    lines = text.split("\n")
    if not lines or not lines[0].startswith("@axl3b "):
        raise Error("Block frame")
    out = [lines[0].replace("@axl3b ", "@axl3 ", 1)]
    current = None
    pending = False
    count = 0
    for line in lines[1:]:
        if line.startswith("="):
            if current is not None:
                raise Error("Late declaration")
            out.append(line)
            continue
        if line.endswith(":") and line[:-1] in ACTS:
            if pending:
                raise Error("Empty act block")
            current = line[:-1]
            pending = True
            continue
        if not line.startswith("  ") or current is None:
            raise Error("Expected indented typed row")
        # Exactly two leading spaces; whitespace cannot create another control line.
        if line.startswith("   "):
            raise Error("Noncanonical indentation")
        count += 1
        if count > MAX_ROWS:
            raise Error("Row limit")
        out.append(current + " | " + line[2:])
        pending = False
    if pending:
        raise Error("Empty act block")
    # Bound expanded framing before decoding. This profile does not weaken bounds.
    return decode_lines("\n".join(out), schemas)
