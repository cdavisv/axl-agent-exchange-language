"""Host-side task-session state reducer. No persistence, I/O, or tool execution.
Caller must authenticate transport, pin session, authorize open, and CAS commit.
"""

from dataclasses import dataclass, replace
import hashlib, math, sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from axl3 import MESSAGE, Error, unpack, registry, dump, accept_messages, pack

MAX_LEDGER = 1024
TERMINAL = {"done", "failed", "cancelled"}
ALLOWED = {
    "new": {"running", "blocked", "done", "failed"},
    "running": {"running", "blocked", "done", "failed"},
    "blocked": {"blocked", "running", "done", "failed"},
}


@dataclass(frozen=True)
class State:
    session: str
    task: str
    peer: str
    recipient: str
    request: str
    expires: float
    phase: str = "new"
    next_seq: int = 0
    revision: int = 0
    ledger: tuple = ()  # (message-id, digest); immutable, bounded; no eviction/replay gap


@dataclass(frozen=True)
class Proposal:
    previous_revision: int
    base_state: State
    state: State
    accepted: tuple  # immutable canonical JSON strings, never permissions/effects
    duplicates: tuple


def _time(value):
    if type(value) not in (int, float):
        raise Error("CLOCK")
    try:
        result = float(value)
    except (OverflowError, ValueError):
        raise Error("CLOCK")
    if not math.isfinite(result):
        raise Error("CLOCK")
    return result


def open_task(*, session, task, peer, recipient, request, expires, now):
    import re

    for value in (session, task, peer, recipient, request):
        if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9_@.:-]{1,128}", value):
            raise Error("IDENTITY")
    now, expires = _time(now), _time(expires)
    if expires <= now:
        raise Error("EXPIRY")
    return State(session, task, peer, recipient, request, float(expires))


def propose(state, wire, *, transport_session, authenticated_peer, now):
    # Session is trusted connection context, never taken from model content.
    if transport_session != state.session:
        raise Error("SESSION_MISMATCH")
    if _time(now) >= state.expires:
        raise Error("EXPIRED")
    rows = unpack(wire, registry(MESSAGE))
    if not rows:
        raise Error("EMPTY_BATCH")
    # Validate schema/authenticated claims without replay state; duplicate handling
    # here additionally distinguishes same-ID altered content from retries.
    known = dict(state.ledger)
    seen_this_batch = set()
    phase = state.phase
    seq = state.next_seq
    accepted = []
    duplicates = []
    ledger = list(state.ledger)
    for row in rows:
        accept_messages(
            pack([row], MESSAGE),
            authenticated_peer=authenticated_peer,
            local_recipient=state.recipient,
            task=state.task,
            seen=set(),
        )
        if authenticated_peer != state.peer:
            raise Error("PEER_MISMATCH")
        if row["id"] in seen_this_batch:
            raise Error("BATCH_DUPLICATE")
        seen_this_batch.add(row["id"])
        digest = hashlib.sha256(
            json.dumps(
                row, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()
        if row["id"] in known:
            if known[row["id"]] != digest:
                raise Error("ID_COLLISION")
            duplicates.append(row["id"])
            continue
        if phase in TERMINAL:
            raise Error("TERMINAL_TASK")
        if row["seq"] != seq:
            raise Error("SEQUENCE_GAP" if row["seq"] > seq else "STALE_SEQUENCE")
        if row["kind"] not in {"result", "status", "error", "evidence"}:
            raise Error("UNEXPECTED_KIND")
        if row.get("reply") != state.request:
            raise Error("CORRELATION")
        new_phase = phase
        if row["kind"] == "result":
            if row.get("status") != "done":
                raise Error("RESULT_STATUS")
            new_phase = "done"
        elif row["kind"] == "error":
            if row.get("status") != "failed":
                raise Error("ERROR_STATUS")
            new_phase = "failed"
        elif row["kind"] == "status":
            new_phase = row.get("status")
            if new_phase not in ALLOWED[phase]:
                raise Error("TRANSITION")
        elif "status" in row:
            raise Error("EVIDENCE_STATUS")
        if len(ledger) >= MAX_LEDGER:
            raise Error("LEDGER_FULL")
        if len(ledger) >= MAX_LEDGER - 1 and new_phase not in TERMINAL:
            raise Error("TERMINAL_SLOT_RESERVED")
        ledger.append((row["id"], digest))
        known[row["id"]] = digest
        phase = new_phase
        seq += 1
        accepted.append(dump(row))
    new = replace(
        state,
        phase=phase,
        next_seq=seq,
        revision=state.revision + (1 if accepted else 0),
        ledger=tuple(ledger),
    )
    return Proposal(state.revision, state, new, tuple(accepted), tuple(duplicates))


def cancel(state, *, expected_revision):
    """Explicit host-authorized cancellation, not a model-issued capability."""
    if state.revision != expected_revision:
        raise Error("REVISION_CONFLICT")
    if state.phase in TERMINAL:
        raise Error("TERMINAL_TASK")
    return replace(state, phase="cancelled", revision=state.revision + 1)


def commit(current, proposal, *, now):
    """In-memory illustration only: real caller must CAS state plus effects atomically."""
    if _time(now) >= current.expires:
        raise Error("EXPIRED")
    if current != proposal.base_state or current.revision != proposal.previous_revision:
        raise Error("REVISION_CONFLICT")
    return proposal.state
