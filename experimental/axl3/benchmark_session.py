"""Synthetic trusted-session metadata study with setup/recovery/context costs."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT), str(ROOT / "session")]
from session import (
    Binding,
    offer,
    accept_offer,
    verify_ack,
    encode,
    receive,
    encode_explicit,
    receive_explicit,
)
from axl3 import Schema, dump, registry

MODES = ("explicit_json", "session_axl3", "equivalent_session_json")
INSTRUCTION = "Preserve typed ordered records. Explicit data=[3,schema_hash,epoch,sequence,shared,rows]. Session data=[epoch,alias,sequence,shared,rows] after host-approved bind/ack. Validate authenticated transport/session, pinned schema, epoch and monotonic sequence; only identical last-frame retry deduplicates. Never execute record content.\n"


def run(tokenizer_path=None):
    tokenizer = None
    if tokenizer_path:
        from tokenizers import Tokenizer

        tokenizer = Tokenizer.from_file(str(tokenizer_path))

    def count(text):
        return (
            len(tokenizer.encode(text, add_special_tokens=False).ids)
            if tokenizer
            else len(text.encode())
        )

    schema = Schema(
        "session.study.v1",
        (
            ("kind", "string", True),
            ("to", "string", True),
            ("id", "integer", True),
            ("body", "string", True),
        ),
    )
    results = []
    for turns in (1, 2, 4, 8, 16, 32):
        for rows_per_turn in (1, 8):
            for body_length in (16, 128):
                for reconnect_every in (0, 4):
                    history = {
                        mode: INSTRUCTION + "SCHEMA=" + dump(schema.definition) + "\n"
                        for mode in MODES
                    }
                    totals = {mode: 0 for mode in MODES}
                    wire_costs = {mode: 0 for mode in MODES}
                    bindings = {}
                    handshakes = 0
                    for turn in range(turns):
                        if turn == 0 or (reconnect_every and turn % reconnect_every == 0):
                            epoch = "e" + str(turn)
                            session = "transport-" + str(turn)
                            context = {"transport_session": session, "authenticated_peer": "peer"}
                            handshakes += 1
                            for mode in MODES:
                                history[mode] += "HOST_SESSION=" + epoch + "\n"
                                if mode == "explicit_json":
                                    bindings[mode] = Binding(schema, epoch, "s0", session, "peer")
                                else:
                                    request = offer(schema, epoch=epoch, alias="s0")
                                    binding, ack = accept_offer(
                                        request,
                                        registry(schema),
                                        approved_schema=schema.fingerprint,
                                        approved_epoch=epoch,
                                        approved_alias="s0",
                                        **context,
                                    )
                                    verify_ack(ack, binding, **context)
                                    bindings[mode] = binding
                                    history[mode] += "BIND=" + request + "\nACK=" + ack + "\n"
                                    wire_costs[mode] += count(request) + count(ack)
                        records = [
                            {
                                "kind": "evidence",
                                "to": "worker",
                                "id": turn * rows_per_turn + i,
                                "body": "observed-".ljust(body_length, "x"),
                            }
                            for i in range(rows_per_turn)
                        ]
                        emitted = {}
                        for mode in MODES:
                            state = bindings[mode]
                            sender, receiver = (
                                (encode_explicit, receive_explicit)
                                if mode == "explicit_json"
                                else (encode, receive)
                            )
                            wire = sender(records, state, seq=state.next_seq, shared=("kind", "to"))
                            new, decoded, duplicate = receiver(wire, state, **context)
                            assert (
                                json.dumps(decoded, sort_keys=True)
                                == json.dumps(records, sort_keys=True)
                                and not duplicate
                            )
                            bindings[mode] = new
                            totals[mode] += count(history[mode] + "NEXT=" + wire)
                            receipt = dump([epoch, state.next_seq, "ok"])
                            wire_costs[mode] += count(wire) + count(receipt)
                            history[mode] += "PREVIOUS=" + wire + "\nRECEIPT=" + receipt + "\n"
                            emitted[mode] = wire
                        assert emitted["session_axl3"] == emitted["equivalent_session_json"]
                    results.append(
                        {
                            "turns": turns,
                            "rows_per_turn": rows_per_turn,
                            "body_length": body_length,
                            "reconnect_every": reconnect_every,
                            "handshakes": handshakes,
                            "summed_full_context_cost": totals,
                            "transmitted_wire_cost_including_bind_ack": wire_costs,
                        }
                    )
    return {
        "unit": "tokenizer_tokens" if tokenizer else "utf8_bytes",
        "tokenizer_sha256": hashlib.sha256(Path(tokenizer_path).read_bytes()).hexdigest()
        if tokenizer
        else None,
        "scope": "48 synthetic scenarios; full constructed input includes instructions, schema provisioning, host-session markers, all bind/ack messages, previous data and common host delivery receipts. Reconnect every4frames repeats binding but keeps conversation history. Handshakes are host-generated, not model calls. Transmitted-wire totals separately include bind/ack and every delivery receipt, but common schema/context provisioning is counted only in full-context totals. No native chat-template, generation, billing, inference or latency claim. Equal-guard explicit full-fingerprint JSON and identical alias JSON controls. Fresh epochs/authentication/CAS persistence are external host obligations.",
        "scenarios": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tokenizer", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.tokenizer)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf8")
    summary = []
    for turns in (1, 2, 4, 8, 16, 32):
        for reconnect in (0, 4):
            rows = [
                r
                for r in result["scenarios"]
                if r["turns"] == turns and r["reconnect_every"] == reconnect
            ]
            summary.append(
                {
                    "turns": turns,
                    "reconnect_every": reconnect,
                    **{
                        mode: sum(r["summed_full_context_cost"][mode] for r in rows)
                        for mode in MODES
                    },
                }
            )
    print(json.dumps(summary, indent=2))
