"""Local host adapter prototype. Authentication/permissions stay host-owned."""

import hashlib, json, sys, re
from pathlib import Path
from dataclasses import dataclass, replace

BASE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BASE), str(BASE / "dictionaries"), str(BASE / "lifecycle")]
from axl3 import MESSAGE, Error, pack, unpack, registry, dump, load, matches
from dictionary import (
    Cache,
    validate_cache,
    cache_fingerprint,
    encode as axl_encode,
    decode as axl_decode,
)
from lifecycle import State, open_task, propose, commit


@dataclass(frozen=True)
class Host:
    task: State
    cache: Cache
    receipts: tuple = ()  # delivery-id, request-digest, committed-revision


MAX_RECEIPTS = 128


def encode_json(records, scope, cache):
    # Common dictionary selection policy; encoding speed not benchmarked.
    _, after = axl_encode(records, MESSAGE, ("task", "sender", "to"), scope=scope, cache=cache)
    shared = ("task", "sender", "to") + (
        ("kind",) if len({r["kind"] for r in records}) == 1 else ()
    )
    p = load(pack(records, MESSAGE, shared))
    known = validate_cache(cache)
    bindings = validate_cache(after)
    reverse = {t: n for n, (_, t) in bindings.items()}
    remaining = [f for i, f in enumerate(MESSAGE.fields) if str(i) not in p[2]]
    opts = [f for f in remaining if not f[2]]
    for row in p[3]:
        bits = iter(row[0])
        present = [f for f in remaining if f[2] or next(bits) == "1"]
        body_index = 1 + [f[0] for f in present].index("body")
        text = dump(row[body_index])
        ref = text in reverse
        row[0] = int(row[0], 2) * 2 + int(ref)
        if ref:
            row[body_index] = reverse[text]
    definitions = {n: [h, load(t)] for n, (h, t) in bindings.items() if n not in known}
    return dump([3, MESSAGE.fingerprint, scope, cache_fingerprint(cache), p[2], definitions, p[3]])


def decode_json(wire, cache):
    envelope = load(wire)
    if type(envelope) is not list or len(envelope) != 7:
        raise Error("JSON frame")
    version, key, scope, manifest, shared, definitions, rows = envelope
    if (
        type(version) is not int
        or version != 3
        or key != MESSAGE.fingerprint
        or scope != cache.scope
        or manifest != cache_fingerprint(cache)
    ):
        raise Error("JSON binding")
    if (
        type(shared) is not dict
        or type(definitions) is not dict
        or type(rows) is not list
        or len(rows) > 1024
    ):
        raise Error("JSON containers")
    if any(k not in {str(i) for i in range(len(MESSAGE.fields))} for k in shared):
        raise Error("JSON shared index")
    if any(MESSAGE.fields[int(k)][0] == "body" or not MESSAGE.fields[int(k)][2] for k in shared):
        raise Error("Body/optional columns must be per-record")
    entries = validate_cache(cache)
    for n, item in definitions.items():
        if n in entries or type(item) is not list or len(item) != 2:
            raise Error("JSON declaration")
        entries[n] = (item[0], dump(item[1]))
    final = Cache(scope, tuple((n, h, t) for n, (h, t) in sorted(entries.items())))
    validate_cache(final)
    remaining = [f for i, f in enumerate(MESSAGE.fields) if str(i) not in shared]
    optional = [f for f in remaining if not f[2]]
    total = 0
    for row in rows:
        if (
            type(row) is not list
            or not row
            or type(row[0]) is not int
            or not 0 <= row[0] < 2 ** (len(optional) + 1)
        ):
            raise Error("JSON row mask")
        ref = row[0] & 1
        bits = format(row[0] >> 1, "0" + str(len(optional)) + "b")
        row[0] = bits
        bititer = iter(bits)
        present = [f for f in remaining if f[2] or next(bititer) == "1"]
        if len(row) != len(present) + 1:
            raise Error("JSON row width")
        index = 1 + [f[0] for f in present].index("body")
        if ref:
            alias = row[index]
            if type(alias) is not str or alias not in entries:
                raise Error("Unknown reference")
            text = entries[alias][1]
            total += len(text.encode())
            if total > 262144:
                raise Error("Expanded budget")
            row[index] = load(text)
    restored = dump([3, key, shared, rows])
    records = unpack(restored, registry(MESSAGE))
    return records, final


def request_digest(request):
    return hashlib.sha256(
        json.dumps(
            request, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def receive(host, request, *, transport_session, authenticated_peer, now):
    """Prepare+commit in caller's exclusive transaction. No external effects."""
    if transport_session != host.task.session or authenticated_peer != host.task.peer:
        raise Error("TRANSPORT")
    # Verify clock/expiry even on retries; no stale-session bypass via receipts.
    from lifecycle import _time

    def clock():
        return _time(now() if callable(now) else now)

    if clock() >= host.task.expires:
        raise Error("EXPIRED")
    if type(request) is not dict or set(request) != {
        "delivery",
        "expected_revision",
        "format",
        "payload",
    }:
        raise Error("Request shape")
    request = load(
        dump(request)
    )  # Private bounded snapshot; callers cannot mutate it after hashing.
    delivery = request["delivery"]
    if type(delivery) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", delivery):
        raise Error("Delivery ID")
    if type(request["expected_revision"]) is not int:
        raise Error("Revision type")
    if request["format"] not in ("axl", "json"):
        raise Error("Format")
    if request["format"] == "axl" and type(request["payload"]) is not str:
        raise Error("AXL payload")
    if request["format"] == "json" and type(request["payload"]) not in (str, list):
        raise Error("JSON payload")
    dump(request)  # Bound transport envelope before digest/cache lookup.
    h = request_digest(request)
    for old_id, old_hash, revision in host.receipts:
        if delivery == old_id:
            if h != old_hash:
                raise Error("DELIVERY_COLLISION")
            return host, {
                "delivery": delivery,
                "revision": revision,
                "duplicate": True,
                "accepted": 0,
            }
    if request["expected_revision"] != host.task.revision:
        raise Error("STALE_REVISION")
    if len(host.receipts) >= MAX_RECEIPTS:
        raise Error("RECEIPT_CAPACITY")
    if request["format"] == "axl":
        records, cache, _ = axl_decode(
            request["payload"],
            registry(MESSAGE),
            expected_scope=transport_session,
            cache=host.cache,
        )
    else:
        records, cache = decode_json(
            request["payload"] if type(request["payload"]) is str else dump(request["payload"]),
            host.cache,
        )
    p = propose(
        host.task,
        pack(records, MESSAGE),
        transport_session=transport_session,
        authenticated_peer=authenticated_peer,
        now=clock(),
    )
    if not p.accepted and cache != host.cache:
        raise Error("CACHE_CHANGE_WITHOUT_NEW_MESSAGE")
    state = commit(host.task, p, now=clock())
    if len(host.receipts) >= MAX_RECEIPTS - 1 and state.phase not in {
        "done",
        "failed",
        "cancelled",
    }:
        raise Error("TERMINAL_RECEIPT_RESERVED")
    new = Host(state, cache, host.receipts + ((delivery, h, state.revision),))
    return new, {
        "delivery": delivery,
        "revision": state.revision,
        "duplicate": False,
        "accepted": len(p.accepted),
        "message_duplicates": list(p.duplicates),
    }


def serialize(host):
    from dataclasses import asdict

    return asdict(host)


def restore(data):
    # Trusted host-owned storage only; never accept arbitrary remote snapshots.
    task = dict(data["task"])
    task["ledger"] = tuple(tuple(x) for x in task["ledger"])
    cache = data["cache"]
    return Host(
        State(**task),
        Cache(cache["scope"], tuple(tuple(x) for x in cache["entries"])),
        tuple(tuple(x) for x in data["receipts"]),
    )
