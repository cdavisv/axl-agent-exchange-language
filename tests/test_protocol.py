from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import get_args

import pytest

from axl import (
    AXL_CANONICAL_PREFIXES,
    AxlMessage,
    AxlParseError,
    AxlPrefix,
    AxlTransport,
    build_axl_message,
    compose_axl_message,
    normalize_axl_message,
    parse_axl_message,
)
from axl.protocol import TRANSPORT_MESSAGE_HISTORY_LIMIT, _split_list_items

INVALID_FIXTURE_CORPUS = Path(__file__).parent / "fixtures" / "axl_invalid_messages.json"


@pytest.mark.parametrize(
    ("raw", "expected_prefix"),
    [
        ("TX: id=t-1; to=@backend-dev; >impl api/teams; pri=hi", "TX"),
        ("RX: id=r-1; ref=t-1; st=done; fmt=axl", "RX"),
        ("ST: ref=t-1; st=run; pct=60", "ST"),
        ("ER: id=e-1; ref=t-1; err::timeout; sev=hi; retry=no", "ER"),
        ("EV: id=v-1; ref=pr-1; out=changes; sev=md", "EV"),
        ("SY: id=sy-1; mode=plan; >design -> >impl -> >tst", "SY"),
        ('NT: ref=t-1; note="context only"', "NT"),
        ("PS: id=p-1; kind=showcase; sub=frontend; {finished PKCE}", "PS"),
    ],
)
def test_parse_canonical_prefixes(raw: str, expected_prefix: str) -> None:
    message = parse_axl_message(raw)
    assert message.prefix == expected_prefix


@pytest.mark.parametrize(
    "raw",
    [
        "QR: id=q-1; to=@agent; ?schema user_create",
        "AN: id=a-1; ref=q-1; fmt=json; c=hi",
        "CF: id=c-1; ref=t-1",
        "RJ: id=j-1; ref=t-1; why=scope",
        "MT: id=m-1; caps=[tx,rx]",
        "PL: id=p-1; >design -> >impl -> >tst",
        "OP: id=p-1; sub=architecture; {event sourcing > CRUD}",
        "DQ: id=q-1; sub=contextwindow; {when do you prune context?}",
        "AW: id=a-1; ref=q-1; {summarize first}",
        "SC: id=s-1; sub=frontend; {finished PKCE}",
        "VT: id=vt-1; sub=axl; opts=[tabs,spaces]; {indent pref?}",
    ],
)
def test_legacy_prefixes_are_rejected(raw: str) -> None:
    with pytest.raises(AxlParseError, match="Unsupported AXL prefix"):
        parse_axl_message(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "RX: id=r-1; ref=t-1; st=run; part=1; more=yes",
        "RX: id=r-1; ref=t-1; st=done; part=2",
        "RX: id=r-1; ref=t-1; st=done; more=no",
    ],
)
def test_part_and_more_are_rejected(raw: str) -> None:
    with pytest.raises(AxlParseError, match="no longer supported"):
        parse_axl_message(raw)


def test_parse_and_normalize_axl_message() -> None:
    raw = "TX: id=t-1; to=@backend-dev; >impl api/teams; pri=hi\n  art=[file:openapi/teams.yaml]"
    message = parse_axl_message(raw)

    assert message.prefix == "TX"
    assert message.fields["id"] == "t-1"
    assert message.payload["art"] == ["file:openapi/teams.yaml"]
    assert normalize_axl_message(message).startswith("TX: id=t-1")


def test_roundtrip_with_payload_and_sequence() -> None:
    raw = "SY: id=sy-1; mode=plan; ref=feat-auth; >design -> >impl -> >tst\n  owner=@backend-dev"
    message = parse_axl_message(raw)
    normalized = normalize_axl_message(message)
    reparsed = parse_axl_message(normalized)

    assert reparsed.fields["sequence"] == [">design", ">impl", ">tst"]
    assert reparsed.payload["owner"] == "@backend-dev"


def test_parse_sequence_and_cause_operators() -> None:
    plan = parse_axl_message("SY: id=sy-1; mode=plan; >design -> >impl -> >tst")
    status = parse_axl_message("ST: ref=t-1; st=blk; blk <- rate_limit")

    assert plan.fields["sequence"] == [">design", ">impl", ">tst"]
    assert status.fields["cause"] == {"effect": "blk", "source": "rate_limit"}


def test_parse_quoted_list_group_and_content_values() -> None:
    message = parse_axl_message(
        'PS: id=p-1; kind=showcase; sub=frontend; tldr="alpha; beta"; '
        'art=["file:src/a.tsx","file:src/b.tsx"]; ctx=(a, b); {ctx=mem}'
    )

    assert message.fields["tldr"] == "alpha; beta"
    assert message.fields["art"] == ["file:src/a.tsx", "file:src/b.tsx"]
    assert message.fields["ctx"] == {"_group": ["a", "b"]}
    assert message.fields["content"] == "ctx=mem"


def test_semicolon_inside_brackets_is_preserved() -> None:
    message = parse_axl_message("SY: id=m-1; mode=caps; caps=[tx;rx;st]")
    assert message.fields["caps"] == ["tx;rx;st"]


def test_registry_meaning_with_sequence_glyph_roundtrips() -> None:
    raw = 'SY: id=sy-1; mode=registry; abbr=api; meaning="payments-api -> gateway"'
    normalized = normalize_axl_message(parse_axl_message(raw))
    reparsed = parse_axl_message(normalized)

    assert reparsed.fields["meaning"] == "payments-api -> gateway"


def test_payload_indentation_is_enforced() -> None:
    with pytest.raises(AxlParseError, match="indented"):
        parse_axl_message("ST: ref=t-1; st=run\nbad_line")


def test_invalid_delimiters_raise() -> None:
    with pytest.raises(AxlParseError, match="Unclosed quote"):
        parse_axl_message('TX: id=t-1; >noop; note="unterminated')
    with pytest.raises(AxlParseError, match="Unmatched brackets"):
        parse_axl_message("TX: id=t-1; >noop; items=[a,b")
    with pytest.raises(AxlParseError, match="Unmatched braces"):
        parse_axl_message("TX: id=t-1; >noop; {unclosed content")


def test_duplicate_header_fields_raise() -> None:
    with pytest.raises(AxlParseError, match="field `to` must appear at most once"):
        parse_axl_message("TX: id=t-1; to=@qa; to=@security; >review auth-release")

    with pytest.raises(AxlParseError, match="field `content` must appear at most once"):
        parse_axl_message("PS: id=p-1; kind=notice; {first}; {second}")

    with pytest.raises(AxlParseError, match="field `st` must appear at most once"):
        parse_axl_message("ST: ref=t-1; ok; st=run")


def test_duplicate_payload_fields_raise() -> None:
    with pytest.raises(AxlParseError, match="payload field `summary` must appear at most once"):
        parse_axl_message(
            "TX: id=t-1; to=@reviewer; >handoff reviewer\n"
            "  summary=first\n"
            "  summary=second"
        )


@pytest.mark.parametrize(
    "fixture",
    json.loads(INVALID_FIXTURE_CORPUS.read_text(encoding="utf-8"))["cases"],
    ids=lambda fixture: fixture["id"],
)
def test_shared_invalid_fixture_corpus_rejected_under_strict_validation(
    fixture: dict[str, str],
) -> None:
    with pytest.raises(AxlParseError):
        parse_axl_message(fixture["raw"], strict=True)


def test_empty_sequence_and_cause_parts_raise() -> None:
    with pytest.raises(AxlParseError, match="sequence entries cannot be empty"):
        parse_axl_message("SY: id=sy-1; mode=plan; >design ->")

    with pytest.raises(AxlParseError, match="cause expressions must include effect and source"):
        parse_axl_message("ST: ref=t-1; st=blk; blk <-")


def test_parser_reserved_assignment_fields_raise() -> None:
    with pytest.raises(AxlParseError, match="field `sequence` is reserved"):
        parse_axl_message("SY: id=sy-1; mode=plan; sequence=[>design,>impl]")

    with pytest.raises(AxlParseError, match="field `directives` is reserved"):
        parse_axl_message("TX: id=t-1; to=@qa; directives=[>review]")

    with pytest.raises(AxlParseError, match="payload field `lines` is reserved"):
        parse_axl_message("NT: ref=t-1\n  lines=looks-like-body")


def test_split_list_items_rejects_unbalanced_values() -> None:
    with pytest.raises(AxlParseError, match="Unclosed quote"):
        _split_list_items('a, "b')
    with pytest.raises(AxlParseError, match="Unmatched"):
        _split_list_items("[a, b")


def test_tx_requires_directive() -> None:
    with pytest.raises(AxlParseError, match="directive"):
        parse_axl_message("TX: id=t-1; to=@backend-dev; pri=hi")


def test_er_requires_typed_error() -> None:
    with pytest.raises(AxlParseError, match="typed error"):
        parse_axl_message("ER: id=e-1; ref=t-1; sev=hi")


def test_ps_reply_requires_ref() -> None:
    with pytest.raises(AxlParseError, match="kind=reply"):
        parse_axl_message("PS: id=rp-1; {reply with no thread target}")


def test_ps_reply_can_omit_id_when_ref_present() -> None:
    message = parse_axl_message("PS: ref=p-1; {+1; event streams help}")
    assert message.fields["ref"] == "p-1"
    assert "id" not in message.fields


def test_ps_poll_requires_opts() -> None:
    with pytest.raises(AxlParseError, match="opts"):
        parse_axl_message("PS: id=vt-1; kind=poll; sub=axl; {indent pref?}")


def test_ps_poll_rejects_empty_opts() -> None:
    with pytest.raises(AxlParseError, match="at least one option"):
        parse_axl_message("PS: id=vt-empty; kind=poll; sub=axl; opts=[]; {indent pref?}")


def test_social_rx_requires_ref() -> None:
    with pytest.raises(AxlParseError, match="ref"):
        parse_axl_message("RX: id=a-1; chan=social; {summarize first}")


def test_strict_validation_rejects_ps_on_direct_channel() -> None:
    with pytest.raises(AxlParseError, match="PS messages must use `chan=social`"):
        parse_axl_message("PS: id=p-1; chan=dm; kind=notice; {private note}", strict=True)


def test_strict_validation_rejects_non_social_prefix_on_social_channel() -> None:
    with pytest.raises(AxlParseError, match="Only PS messages and RX social answers"):
        parse_axl_message("ST: id=s-1; ref=t-1; chan=social; st=run", strict=True)


def test_social_rx_allows_answer_context_fields_under_strict_validation() -> None:
    message = parse_axl_message(
        "RX: id=a-1; chan=social; ref=p-1; sub=contextwindow; tone=agree; "
        "tgt=thread; tldr=agree; {summarize first}",
        strict=True,
    )

    assert message.fields["sub"] == "contextwindow"
    assert message.fields["tone"] == "agree"
    assert message.fields["tgt"] == "thread"
    assert message.fields["tldr"] == "agree"


def test_ev_conditional_requires_cond() -> None:
    with pytest.raises(AxlParseError, match="cond"):
        parse_axl_message("EV: id=v-1; ref=pr-1; out=conditional")


def test_caps_and_registry_fields_require_correct_sy_modes() -> None:
    with pytest.raises(AxlParseError, match="`caps` is only valid"):
        parse_axl_message("TX: id=t-1; >work; caps=[tx]")
    with pytest.raises(AxlParseError, match="`abbr` / `meaning` are only valid"):
        parse_axl_message("SY: id=sy-1; mode=caps; abbr=ux; meaning=ux-architect")


def test_delta_mode_accepts_promoted_operation_vocabulary() -> None:
    operations = json.dumps(
        [{"op": "replace", "path": "/objectives/0/status", "value": "done"}],
        separators=(",", ":"),
    )
    message = parse_axl_message(
        "SY: id=sy-delta-1; mode=delta; ref=upp:project-alpha; "
        f"expected_revision_no=3; operations={json.dumps(operations)}",
        strict=True,
    )

    assert message.fields["mode"] == "delta"
    assert message.fields["expected_revision_no"] == 3
    assert json.loads(message.fields["operations"]) == [
        {"op": "replace", "path": "/objectives/0/status", "value": "done"}
    ]


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        ("SY: id=sy-delta-missing; mode=delta; ref=upp:p", "operations"),
        (
            'SY: id=sy-delta-bad-op; mode=delta; ref=upp:p; operations="'
            '[{\\"op\\":\\"merge\\",\\"path\\":\\"/x\\",\\"value\\":1}]"',
            "operation `op`",
        ),
        (
            'SY: id=sy-delta-bad-path; mode=delta; ref=upp:p; operations="'
            '[{\\"op\\":\\"set\\",\\"path\\":\\"x\\",\\"value\\":1}]"',
            "JSON pointer",
        ),
        (
            'SY: id=sy-delta-missing-value; mode=delta; ref=upp:p; operations="'
            '[{\\"op\\":\\"replace\\",\\"path\\":\\"/x\\"}]"',
            "requires `value`",
        ),
        (
            'SY: id=sy-delta-move-missing-from; mode=delta; ref=upp:p; operations="'
            '[{\\"op\\":\\"move\\",\\"path\\":\\"/x\\"}]"',
            "requires JSON-pointer `from`",
        ),
    ],
)
def test_delta_mode_rejects_malformed_operations(raw: str, match: str) -> None:
    with pytest.raises(AxlParseError, match=match):
        parse_axl_message(raw, strict=True)


def test_stream_continuations_require_ref_and_seq() -> None:
    with pytest.raises(AxlParseError, match="must include `ref`"):
        parse_axl_message("RX: id=r-stream-1; stream=data; seq=1; {first batch}")
    with pytest.raises(AxlParseError, match="must include `seq`"):
        parse_axl_message("RX: ref=r-stream-1; stream=data; {first batch}")


def test_rx_stream_continuation_can_omit_id() -> None:
    message = parse_axl_message("RX: ref=r-stream-1; stream=data; seq=1; {first batch}")

    assert message.prefix == "RX"
    assert message.fields["ref"] == "r-stream-1"
    assert "id" not in message.fields


def test_compact_rx_result_can_omit_id_when_ref_and_status() -> None:
    message = parse_axl_message("RX: ref=t-1; st=done; {complete}", strict=True)

    assert message.prefix == "RX"
    assert message.fields["ref"] == "t-1"
    assert message.fields["st"] == "done"
    assert "id" not in message.fields


def test_pct_must_be_between_zero_and_one_hundred() -> None:
    with pytest.raises(AxlParseError, match="between 0 and 100"):
        parse_axl_message("ST: ref=t-1; st=partial; pct=101")


def test_score_must_be_numeric() -> None:
    message = parse_axl_message("PS: id=p-review; kind=review; ref=tool-x; score=4.5; {solid}")

    assert message.fields["score"] == 4.5

    with pytest.raises(AxlParseError, match="`score` must be numeric"):
        parse_axl_message("PS: id=p-review; kind=review; ref=tool-x; score=great; {solid}")


def test_noncanonical_field_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="axl.protocol")
    parse_axl_message("TX: id=t-1; >work; kind=proposal")
    assert "field `kind` is non-canonical on `TX`" in caplog.text


@pytest.mark.parametrize(
    "raw",
    [
        "TX: id=t-1; to=@a; >work; counter=split",
        "ER: id=e-1; ref=t-1; err::timeout; counter=split",
        "EV: id=v-1; ref=pr-1; out=changes; counter=split",
        "RX: id=r-1; ref=t-1; st=done; counter=split",
    ],
)
def test_strict_rejects_counter_off_st_prefix(raw: str) -> None:
    with pytest.raises(AxlParseError, match="`counter` is non-canonical"):
        parse_axl_message(raw, strict=True)


@pytest.mark.parametrize(
    "raw",
    [
        "TX: id=t-1; to=@a; >work; esc=@boss",
        "EV: id=v-1; ref=pr-1; out=changes; esc=@boss",
        "RX: id=r-1; ref=t-1; st=done; esc=@boss",
        "SY: id=sy-1; mode=plan; ref=feat; esc=@boss",
    ],
)
def test_strict_rejects_esc_off_er_st_prefixes(raw: str) -> None:
    with pytest.raises(AxlParseError, match="`esc` is non-canonical"):
        parse_axl_message(raw, strict=True)


@pytest.mark.parametrize(
    "raw",
    [
        "TX: id=t-1; to=@a; >work; cond=ready",
        "RX: id=r-1; ref=t-1; st=done; cond=ready",
        "ER: id=e-1; ref=t-1; err::timeout; cond=retry",
        "NT: ref=t-1; cond=ready",
        "SY: id=sy-1; mode=plan; ref=feat; cond=ready",
    ],
)
def test_strict_rejects_cond_off_ev_ps_st_prefixes(raw: str) -> None:
    with pytest.raises(AxlParseError, match="`cond` is non-canonical"):
        parse_axl_message(raw, strict=True)


def test_ps_review_conditional_requires_cond() -> None:
    with pytest.raises(AxlParseError, match="PS review messages with `out=conditional`"):
        parse_axl_message(
            "PS: id=p-rev-1; kind=review; ref=tool-x; sub=reviews; out=conditional; "
            "{ship after tests}"
        )


def test_ps_review_conditional_accepts_cond() -> None:
    message = parse_axl_message(
        "PS: id=p-rev-1; kind=review; ref=tool-x; sub=reviews; out=conditional; "
        'cond="add tests for edge cases"; {ship after tests}',
        strict=True,
    )
    assert message.fields["kind"] == "review"
    assert message.fields["out"] == "conditional"
    assert message.fields["cond"] == "add tests for edge cases"


def test_state_machine_allows_rj_to_ack_directly() -> None:
    transport = AxlTransport()
    new_task = parse_axl_message("TX: id=task-rj; to=@a; >work")
    rejected = parse_axl_message("ST: ref=task-rj; st=rj; why=scope; counter={split}")
    accepted = parse_axl_message("ST: ref=task-rj; st=ack; {accepting counter}")

    transport.route(channel="dm", message=new_task)
    transport.route(channel="state", message=rejected)
    transport.route(channel="state", message=accepted)

    assert transport.get_task_state("task-rj") == "ack"


def test_missing_id_raises_for_required_prefixes() -> None:
    with pytest.raises(AxlParseError, match="id"):
        parse_axl_message("TX: to=@agent; >impl api/teams")


def test_strict_direct_tx_requires_to() -> None:
    with pytest.raises(AxlParseError, match="must include `to`"):
        parse_axl_message("TX: id=t-implicit-to; >ship fix", strict=True)


def test_strict_recipient_fields_must_be_canonical_refs() -> None:
    with pytest.raises(AxlParseError, match="canonical `@recipient` atoms"):
        parse_axl_message("TX: id=t-bad-to; to=backend dev; >ship fix", strict=True)

    with pytest.raises(AxlParseError, match="canonical `@recipient` atoms"):
        parse_axl_message("ST: id=s-escalate; ref=t-1; st=blk; esc=team-lead", strict=True)

    message = parse_axl_message(
        "TX: id=t-multi; to=[@qa,@security]; from=@lead; >review auth-release",
        strict=True,
    )

    assert message.fields["to"] == ["@qa", "@security"]


def test_strict_tx_rejects_duplicate_recipients() -> None:
    with pytest.raises(AxlParseError, match="duplicate recipients"):
        parse_axl_message("TX: id=t-dupe; to=[@qa,@qa]; >review auth-release", strict=True)


def test_strict_rejects_duplicate_to_recipients_on_responses() -> None:
    with pytest.raises(AxlParseError, match="duplicate recipients"):
        parse_axl_message(
            "RX: id=r-dupe; ref=t-1; to=[@qa,@qa]; st=done",
            strict=True,
        )


def test_nt_and_st_can_omit_id() -> None:
    assert "id" not in parse_axl_message('NT: ref=t-1; note="beta freeze"').fields
    assert "id" not in parse_axl_message("ST: ref=t-1; st=run; pct=50").fields


def test_route_normalizes_channel_field() -> None:
    transport = AxlTransport()
    message = parse_axl_message("RX: id=r-1; ref=t-1; chan=dm; st=done")

    transport.route(channel="Social", message=message)

    assert message.fields["chan"] == "social"
    assert "chan=social" in normalize_axl_message(message)
    assert transport.list_messages("SOCIAL")


def test_route_strictly_validates_after_channel_normalization() -> None:
    transport = AxlTransport()
    message = parse_axl_message("RX: id=a-1; {summarize first}")

    with pytest.raises(AxlParseError, match="Social RX messages must include `ref`"):
        transport.route(channel="social", message=message, strict=True)

    assert not transport.list_messages("social")


def test_route_rejects_ps_on_dm_after_channel_normalization() -> None:
    transport = AxlTransport()
    message = parse_axl_message("PS: id=p-1; kind=notice; {private note}")

    with pytest.raises(AxlParseError, match="PS messages must use `chan=social`"):
        transport.route(channel="dm", message=message, strict=True)

    assert not transport.list_messages("dm")


def test_transport_message_history_is_capped() -> None:
    transport = AxlTransport()
    for index in range(TRANSPORT_MESSAGE_HISTORY_LIMIT + 5):
        message = parse_axl_message(f"ST: id=s-{index}; ref=t-1; st=run")
        transport.route(channel="state", message=message)

    messages = transport.list_messages("state")
    assert len(messages) == TRANSPORT_MESSAGE_HISTORY_LIMIT
    assert messages[0].message.fields["id"] == "s-5"


def test_transport_lists_messages_for_recipient() -> None:
    transport = AxlTransport()
    transport.route(
        channel="dm",
        message=parse_axl_message("TX: id=t-qa; to=[@qa,@security]; >review auth-release"),
        strict=True,
    )
    transport.route(
        channel="dm",
        message=parse_axl_message("TX: id=t-backend; to=@backend-dev; >impl api"),
        strict=True,
    )
    transport.route(
        channel="state",
        message=parse_axl_message("ST: ref=t-qa; st=run; pct=50"),
        strict=True,
    )

    assert [env.message.fields["id"] for env in transport.list_messages_for("qa", "dm")] == [
        "t-qa"
    ]
    assert [env.message.fields["id"] for env in transport.list_messages_for("@security")] == [
        "t-qa"
    ]


def test_transport_tracks_registry_entries_by_scope() -> None:
    transport = AxlTransport()
    message = parse_axl_message(
        "SY: id=m-1; mode=registry; abbr=[ux,api]; meaning=[ux-architect,payments-api]"
    )

    transport.route(
        channel="dm",
        message=message,
        metadata={
            "sender": "planner",
            "target": "frontend-dev",
            "project_id": "proj-123",
        },
    )

    expected = {"ux": "ux-architect", "api": "payments-api"}
    assert transport.get_abbreviation_registry("project:proj-123") == expected
    assert transport.get_abbreviation_registry("dm:planner->frontend-dev") == expected
    assert transport.get_abbreviation_registry("channel:dm") == expected


def test_transport_does_not_register_caps_sync() -> None:
    transport = AxlTransport()
    message = parse_axl_message("SY: id=m-1; mode=caps; caps=[tx,rx,st]")

    transport.route(
        channel="dm", message=message, metadata={"sender": "planner", "target": "frontend-dev"}
    )

    assert transport.get_abbreviation_registry("dm:planner->frontend-dev") == {}


def test_state_machine_invalid_transition_warns(caplog: pytest.LogCaptureFixture) -> None:
    transport = AxlTransport()
    done = parse_axl_message("ST: id=s-1; ref=task-1; st=done")
    rerun = parse_axl_message("ST: id=s-2; ref=task-1; st=run")

    with caplog.at_level(logging.WARNING, logger="axl.protocol"):
        transport.route(channel="state", message=done)
        transport.route(channel="state", message=rerun)

    assert "Invalid state transition" in caplog.text
    assert transport.get_task_state("task-1") == "done"


def test_state_machine_fail_to_run_requires_retry(caplog: pytest.LogCaptureFixture) -> None:
    transport = AxlTransport()
    fail = parse_axl_message("ST: id=s-1; ref=task-1; st=fail; why=timeout")
    rerun = parse_axl_message("ST: id=s-2; ref=task-1; st=run")

    with caplog.at_level(logging.WARNING, logger="axl.protocol"):
        transport.route(channel="state", message=fail)
        transport.route(channel="state", message=rerun)

    assert "retryable failure must set `retry=yes|cond`" in caplog.text
    assert transport.get_task_state("task-1") == "fail"


def test_state_machine_fail_to_run_with_retry_allowed() -> None:
    transport = AxlTransport()
    retryable = parse_axl_message("ER: id=e-1; ref=task-1; err::timeout; retry=yes")
    fail = parse_axl_message("ST: id=s-1; ref=task-1; st=fail; why=timeout")
    rerun = parse_axl_message("ST: id=s-2; ref=task-1; st=run")

    transport.route(channel="state", message=retryable)
    transport.route(channel="state", message=fail)
    transport.route(channel="state", message=rerun)

    assert transport.get_task_state("task-1") == "run"


def test_retry_flag_on_rerun_does_not_self_authorize_failed_task() -> None:
    transport = AxlTransport()

    transport.route(
        channel="dm",
        message=parse_axl_message("TX: id=t-1; to=@backend-dev; >work", strict=True),
        strict=True,
    )
    transport.route(
        channel="state",
        message=parse_axl_message("ST: id=s-1; ref=t-1; st=fail; why=timeout", strict=True),
        strict=True,
    )

    with pytest.raises(AxlParseError, match="retryable failure must set `retry=yes\\|cond`"):
        transport.route(
            channel="state",
            message=parse_axl_message("ST: id=s-2; ref=t-1; st=run; retry=yes", strict=True),
            strict=True,
        )

    assert transport.get_task_state("t-1") == "fail"


def test_stream_completion_updates_root_task_state() -> None:
    transport = AxlTransport()
    start = parse_axl_message("RX: id=r-1; ref=task-1; stream=start; fmt=json")
    end = parse_axl_message("RX: ref=r-1; stream=end; seq=2; st=done")

    transport.route(channel="dm", message=start)
    transport.route(channel="dm", message=end)

    assert transport.get_task_state("task-1") == "done"


def test_rejection_follow_up_ref_chain_resolves_back_to_root_task() -> None:
    transport = AxlTransport()
    rejection = parse_axl_message(
        "ST: id=s-rj-1; ref=t-auth-api; st=rj; why=complexity; counter={split into 2 tasks}"
    )
    accepted_counter = parse_axl_message("ST: ref=s-rj-1; st=ack; {accepted counter-proposal}")

    transport.route(channel="state", message=rejection)
    transport.route(channel="state", message=accepted_counter)

    assert transport.get_task_state("t-auth-api") == "ack"
    assert transport.get_task_state("s-rj-1") == "ack"


def test_build_axl_message_uses_safe_content_serialization() -> None:
    message = build_axl_message(
        "PS",
        fields={
            "id": "p-safe-1",
            "kind": "notice",
            "sub": "status",
            "content": 'deploy {staging done and say "ship it"',
        },
    )

    assert 'content="deploy {staging done and say \\"ship it\\""' in message


def test_normalize_content_with_unbalanced_brace_falls_back_to_assignment() -> None:
    message = AxlMessage(
        prefix="PS",
        fields={"id": "p-1", "content": "deploy {staging", "kind": "notice"},
        payload={},
        raw="",
    )

    normalized = normalize_axl_message(message)
    reparsed = parse_axl_message(normalized)

    assert 'content="deploy {staging"' in normalized
    assert reparsed.fields["content"] == "deploy {staging"


def test_normalize_escapes_multiline_values_for_payload_roundtrip() -> None:
    raw_note = "first line\nsecond line\twith tab"
    message = build_axl_message(
        "TX",
        fields={"id": "t-multiline-1", "to": "@reviewer"},
        directives=[">handoff reviewer"],
        payload={"summary": raw_note},
        strict=True,
    )

    assert "\\n" in message
    assert "\nsecond line" not in message
    assert parse_axl_message(message).payload["summary"] == raw_note


def test_normalize_escapes_multiline_content_assignment_roundtrip() -> None:
    raw_content = "deploy {staging\nthen verify"
    message = AxlMessage(
        prefix="PS",
        fields={"id": "p-1", "kind": "notice", "content": raw_content},
        payload={},
        raw="",
    )

    normalized = normalize_axl_message(message)

    assert 'content="deploy {staging\\nthen verify"' in normalized
    assert parse_axl_message(normalized).fields["content"] == raw_content


def test_normalize_quotes_backslash_values_for_payload_roundtrip() -> None:
    raw_path = r"C:\Users\agent\handoff.txt"
    message = build_axl_message(
        "NT",
        fields={"ref": "t-path"},
        payload={"path": raw_path},
        strict=True,
    )

    assert 'path="C:\\\\Users\\\\agent\\\\handoff.txt"' in message
    assert parse_axl_message(message).payload["path"] == raw_path


def test_complex_payload_values_serialize_as_deterministic_json_strings() -> None:
    questions = [
        {
            "id": "workflow_context",
            "missing_context": ["target_audience", "visual_style"],
            "question": "Provide missing workflow context.",
        }
    ]
    message = build_axl_message(
        "TX",
        fields={"id": "q-context", "to": "@human"},
        directives=["?clarify context"],
        payload={
            "questions": questions,
            "metadata": {"step": "Frontend Dev", "workflow": "Website Delivery"},
        },
        strict=True,
    )

    parsed = parse_axl_message(message, strict=True)

    assert "{'id':" not in message
    assert json.loads(parsed.payload["questions"]) == questions
    assert json.loads(parsed.payload["metadata"]) == {
        "step": "Frontend Dev",
        "workflow": "Website Delivery",
    }


def test_normalize_omits_defaults() -> None:
    tx = normalize_axl_message(parse_axl_message("TX: id=t-1; >impl api; pri=md; chan=dm"))
    ps = normalize_axl_message(
        parse_axl_message(
            "PS: id=p-1; ref=p-root; kind=reply; tone=neutral; chan=social; {content}"
        )
    )

    assert "pri=" not in tx
    assert "chan=" not in tx
    assert "kind=reply" not in ps
    assert "tone=" not in ps
    assert "chan=" not in ps


def test_new_ps_kinds_parse() -> None:
    message = parse_axl_message(
        "PS: id=p-rfc-1; kind=proposal; sub=architecture; stake=hi; {gRPC internal + REST gateway}"
    )
    assert message.fields["kind"] == "proposal"
    assert message.fields["stake"] == "hi"


def test_axl_prefix_literal_matches_canonical_prefixes() -> None:
    literal_values = set(get_args(AxlPrefix))
    canonical_set = set(AXL_CANONICAL_PREFIXES)
    assert literal_values == canonical_set


def test_long_namespace_reexports_package_api() -> None:
    from agent_exchange_language import parse_axl_message as compat_parse

    assert compat_parse("ST: ref=t-1; st=run").prefix == "ST"


@pytest.mark.parametrize(
    ("prefix", "fields", "directives", "payload"),
    [
        (
            "TX",
            {"id": "t-parity", "to": "@backend-dev", "pri": "hi"},
            [">impl api/teams"],
            {},
        ),
        (
            "ST",
            {"ref": "t-parity", "st": "run", "pct": 60},
            None,
            {},
        ),
        (
            "PS",
            {
                "id": "p-parity",
                "kind": "showcase",
                "sub": "frontend",
                "content": "PKCE shipped",
            },
            None,
            {},
        ),
        (
            "ER",
            {"id": "e-parity", "ref": "t-parity", "sev": "hi", "typed": ["err::timeout"]},
            None,
            {},
        ),
    ],
)
def test_compose_and_build_axl_message_are_equivalent(
    prefix: str,
    fields: dict[str, object],
    directives: list[str] | None,
    payload: dict[str, object],
) -> None:
    """`compose_axl_message` is documented as a canonical alias of `build_axl_message`."""

    composed = compose_axl_message(
        prefix,
        fields=fields,
        payload=payload,
        directives=directives,
        strict=True,
    )
    built = build_axl_message(
        prefix,
        fields=fields,
        payload=payload,
        directives=directives,
        strict=True,
    )

    assert composed == built


def test_build_axl_message_rejects_directives_collision() -> None:
    with pytest.raises(AxlParseError, match="not both"):
        build_axl_message(
            "TX",
            fields={"id": "t-collide", "to": "@reviewer", "directives": [">old-action"]},
            directives=[">new-action"],
            strict=True,
        )
