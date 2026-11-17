"""Experimental exact-value dictionaries. No remote retrieval or authorization."""

import json, re, hashlib, sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "surface"))
from surface import encode as lines_encode, decode as lines_decode, bound, check_schema
from axl3 import load, dump, Error, MAX_BYTES

NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,31}\Z")
SCOPE = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
MAX_ENTRIES = 128


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


@dataclass(frozen=True)
class Cache:
    scope: str
    entries: tuple  # immutable(alias, sha256, canonical JSON text)


def validate_cache(cache):
    if (
        not isinstance(cache, Cache)
        or type(cache.scope) is not str
        or not SCOPE.fullmatch(cache.scope)
        or type(cache.entries) is not tuple
    ):
        raise Error("Cache structure")
    if len(cache.entries) > MAX_ENTRIES:
        raise Error("Dictionary count")
    out = {}
    total = 0
    for entry in cache.entries:
        if type(entry) is not tuple or len(entry) != 3:
            raise Error("Cache entry")
        name, sha, text = entry
        if type(name) is not str or not NAME.fullmatch(name) or name in out:
            raise Error("Dictionary alias")
        value = load(text)
        canonical = dump(value)
        if canonical != text or digest(text) != sha:
            raise Error("Stale dictionary hash")
        total += len(text.encode())
        if total > MAX_BYTES:
            raise Error("Dictionary value budget")
        out[name] = (sha, text)
    return out


def cache_fingerprint(cache):
    entries = validate_cache(cache)
    return digest(dump([cache.scope, [[name, sha] for name, (sha, _) in sorted(entries.items())]]))


def tokens(text):
    bound(text)
    decoder = json.JSONDecoder()
    position = 0
    out = []
    while position < len(text):
        start = position
        if text[position] == "^":
            end = text.find(" ", position)
            if end == -1:
                end = len(text)
            if not NAME.fullmatch(text[position + 1 : end]):
                raise Error("Reference syntax")
        elif text[position] == "~":
            end = position + 1
        else:
            try:
                _, end = decoder.raw_decode(text, position)
            except (ValueError, RecursionError) as e:
                raise Error("Literal syntax") from e
        out.append(text[start:end])
        if len(out) > 128:
            raise Error("Too many columns")
        if end == len(text):
            break
        if text[end] != " " or end + 1 == len(text) or text[end + 1] == " ":
            raise Error("Value boundary")
        position = end + 1
    return out


def encode(records, schema, shared=(), *, scope="batch", cache=None, min_bytes=64):
    if type(min_bytes) is not int or min_bytes < 0:
        raise Error("Dictionary threshold")
    if cache is None:
        cache = Cache(scope, ())
    if cache.scope != scope:
        raise Error("Scope mismatch")
    known = validate_cache(cache)
    original = lines_encode(records, schema, shared)
    if "body" not in [f[0] for f in schema.fields] or "body" in shared:
        raise Error("Dictionary requires unshared body column")
    by_text = {text: name for name, (_, text) in known.items()}
    counts = {}
    for row in records:
        if "body" in row:
            text = dump(row["body"])
            counts[text] = counts.get(text, 0) + 1
    selected = {
        text
        for text, n in counts.items()
        if (n >= 2 and len(text.encode()) >= min_bytes) or text in by_text
    }
    declarations = []
    bindings = dict(known)
    for text in sorted(selected, key=digest):
        if text in by_text:
            continue
        i = 0
        while "e" + str(i) in bindings:
            i += 1
        name = "e" + str(i)
        sha = digest(text)
        bindings[name] = (sha, text)
        by_text[text] = name
        declarations.append("&" + name + " " + sha + " " + text)
    new_cache = Cache(scope, tuple((n, h, t) for n, (h, t) in sorted(bindings.items())))
    validate_cache(new_cache)
    fields = [f[0] for f in schema.fields if f[0] != "kind" and f[0] not in shared]
    body_index = fields.index("body")
    lines = original.split("\n")
    out = [lines[0].replace("@axl3 ", "@axl3d ", 1) + " " + scope + " " + cache_fingerprint(cache)]
    inserted = False
    for line in lines[1:]:
        if line.startswith("="):
            out.append(line)
            continue
        if not inserted:
            out.extend(declarations)
            inserted = True
        act, _, raw = line.partition(" | ")
        parts = tokens(raw)
        if parts[body_index] in selected:
            parts[body_index] = "^" + by_text[parts[body_index]]
        out.append(act + " | " + " ".join(parts))
    if not inserted:
        out.extend(declarations)
    wire = "\n".join(out)
    bound(wire)
    return wire, new_cache


def decode(wire, schemas, *, expected_scope, cache=None):
    bound(wire)
    lines = wire.split("\n")
    parts = lines[0].split(" ")
    if (
        len(parts) != 4
        or parts[0] != "@axl3d"
        or parts[2] != expected_scope
        or not SCOPE.fullmatch(expected_scope)
    ):
        raise Error("Dictionary frame/scope")
    if cache is None:
        cache = Cache(expected_scope, ())
    if cache.scope != expected_scope:
        raise Error("Cache scope mismatch")
    bindings = validate_cache(cache)
    if parts[3] != cache_fingerprint(cache):
        raise Error("Stale cache manifest")
    out = []
    expanded_bytes = 0

    def append_line(line):
        nonlocal expanded_bytes
        expanded_bytes += len(line.encode()) + (1 if out else 0)
        if expanded_bytes > MAX_BYTES:
            raise Error("Expanded frame budget")
        out.append(line)

    append_line("@axl3 " + parts[1])
    began = False
    references = 0
    retrieved_bytes = 0
    if parts[1] not in schemas:
        raise Error("Unpinned schema")
    for line in lines[1:]:
        if line.startswith("&"):
            if began:
                raise Error("Late dictionary declaration")
            fields = line[1:].split(" ", 2)
            if len(fields) != 3:
                raise Error("Dictionary declaration")
            name, sha, text = fields
            if name in bindings:
                raise Error("Duplicate dictionary alias")
            # Canonical text, hash, identifier and aggregate bounds checked together.
            bindings[name] = (sha, text)
            validate_cache(
                Cache(expected_scope, tuple((n, h, t) for n, (h, t) in bindings.items()))
            )
            continue
        if line.startswith("="):
            if began:
                raise Error("Late shared declaration")
            if any(t.startswith("^") for t in tokens(line.partition(" ")[2])):
                raise Error("Reference in shared declaration")
            append_line(line)
            continue
        began = True
        act, sep, raw = line.partition(" | ")
        if not sep:
            raise Error("Act boundary")
        ts = tokens(raw)
        for i, t in enumerate(ts):
            if not t.startswith("^"):
                continue
            name = t[1:]
            if name not in bindings:
                raise Error("Unknown evidence reference")
            value = bindings[name][1]
            ts[i] = value
            references += 1
            retrieved_bytes += len(value.encode())
            if retrieved_bytes > MAX_BYTES:
                raise Error("Reference expansion budget")
        append_line(act + " | " + " ".join(ts))
    rows = lines_decode("\n".join(out), schemas)
    final = Cache(expected_scope, tuple((n, h, t) for n, (h, t) in sorted(bindings.items())))
    return (
        rows,
        final,
        {"references": references, "retrieved_value_bytes": retrieved_bytes, "network_requests": 0},
    )
