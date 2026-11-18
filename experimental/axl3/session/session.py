"""Opt-in trusted-session schema aliases; pure proposals, not authentication.
Host must authorize bindings, supply authenticated transport context, allocate a
fresh epoch for each binding lifetime, and atomically persist state with effects.
"""

from dataclasses import dataclass, replace
import hashlib
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from axl3 import Error, Schema, dump, load, pack, registry, unpack

MAX_SEQ = 2**53 - 1


@dataclass(frozen=True)
class Binding:
    schema: Schema
    epoch: str
    alias: str
    session: str
    peer: str
    next_seq: int = 0
    last_digest: str | None = None


def _label(value):
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9_.-]{1,32}", value):
        raise Error("Binding label")


def _context(binding, session, peer):
    if session != binding.session or peer != binding.peer:
        raise Error("Transport context mismatch")


def offer(schema, *, epoch, alias):
    _label(epoch)
    _label(alias)
    return dump(["bind", 3, epoch, alias, schema.fingerprint])


def accept_offer(
    wire,
    schemas,
    *,
    approved_schema,
    approved_epoch,
    approved_alias,
    transport_session,
    authenticated_peer,
):
    """Only call after host approval. All approved_* values are host-owned.
    Schema definition must already be provisioned/pinned; never learn it from
    model text. A new binding requires a fresh host-allocated epoch.
    """
    _label(approved_epoch)
    _label(approved_alias)
    if (
        type(transport_session) is not str
        or not transport_session
        or type(authenticated_peer) is not str
        or not authenticated_peer
    ):
        raise Error("Trusted context required")
    obj = load(wire)
    if type(obj) is not list or len(obj) != 5 or type(obj[1]) is not int or obj[1] != 3:
        raise Error("Binding envelope")
    if obj != ["bind", 3, approved_epoch, approved_alias, approved_schema]:
        raise Error("Unapproved binding")
    if approved_schema not in schemas or schemas[approved_schema].fingerprint != approved_schema:
        raise Error("Unpinned schema")
    binding = Binding(
        schemas[approved_schema],
        approved_epoch,
        approved_alias,
        transport_session,
        authenticated_peer,
    )
    return binding, dump(["ack", 3, approved_epoch, approved_alias, approved_schema])


def verify_ack(wire, binding, *, transport_session, authenticated_peer):
    _context(binding, transport_session, authenticated_peer)
    obj = load(wire)
    if type(obj) is not list or len(obj) != 5 or type(obj[1]) is not int or obj[1] != 3:
        raise Error("Acknowledgment envelope")
    if obj != ["ack", 3, binding.epoch, binding.alias, binding.schema.fingerprint]:
        raise Error("Acknowledgment mismatch")


def encode(records, binding, *, seq, shared=()):
    if type(seq) is not int or not 0 <= seq <= MAX_SEQ:
        raise Error("Sequence")
    full = load(pack(records, binding.schema, shared))
    return dump([binding.epoch, binding.alias, seq, full[2], full[3]])


def receive(wire, binding, *, transport_session, authenticated_peer):
    """Return (new binding, records, duplicate). Does not execute/persist data.
    Only exact retry of the last accepted frame is deduplicated; older frames
    reject. The caller must CAS the original binding and commit with effects.
    """
    _context(binding, transport_session, authenticated_peer)
    obj = load(wire)
    if type(obj) is not list or len(obj) != 5:
        raise Error("Session data envelope")
    epoch, alias, seq, constants, rows = obj
    return _accept_data(wire, binding, epoch, alias, seq, constants, rows)


def _accept_data(wire, binding, epoch, alias, seq, constants, rows):
    if epoch != binding.epoch or alias != binding.alias:
        raise Error("Binding mismatch")
    if type(seq) is not int or not 0 <= seq <= MAX_SEQ:
        raise Error("Sequence")
    digest = hashlib.sha256(wire.encode("utf-8")).hexdigest()
    if seq == binding.next_seq - 1 and digest == binding.last_digest:
        return binding, [], True
    if seq != binding.next_seq:
        raise Error("Sequence gap or replay")
    records = unpack(
        dump([3, binding.schema.fingerprint, constants, rows]), registry(binding.schema)
    )
    return replace(binding, next_seq=seq + 1, last_digest=digest), records, False


def encode_explicit(records, binding, *, seq, shared=()):
    """Same data/replay contract, carrying version/full fingerprint each time."""
    short = load(encode(records, binding, seq=seq, shared=shared))
    return dump([3, binding.schema.fingerprint, short[0], short[2], short[3], short[4]])


def receive_explicit(wire, binding, *, transport_session, authenticated_peer):
    _context(binding, transport_session, authenticated_peer)
    obj = load(wire)
    if type(obj) is not list or len(obj) != 6 or type(obj[0]) is not int or obj[0] != 3:
        raise Error("Explicit data envelope")
    if obj[1] != binding.schema.fingerprint:
        raise Error("Schema mismatch")
    return _accept_data(wire, binding, obj[2], binding.alias, obj[3], obj[4], obj[5])
