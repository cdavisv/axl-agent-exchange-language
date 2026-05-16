from __future__ import annotations

import json
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
from axl.protocol import _split_list_items

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
    assert parse_axl_message(raw).prefix == expected_prefix


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
    ],
)
def test_legacy_prefixes_are_rejected(raw: str) -> None:
    with pytest.raises(AxlParseError, match="Unsupported AXL prefix"):
        parse_axl_message(raw)


def test_parse_and_normalize_axl_message() -> None:
    raw = "TX: id=t-1; to=@backend-dev; >impl api/teams; pri=hi\n  art=[file:openapi/teams.yaml]"
    message = parse_axl_message(raw)

    assert message.prefix == "TX"
    assert message.fields["id"] == "t-1"
    assert message.payload["art"] == ["file:openapi/teams.yaml"]
    assert normalize_axl_message(message).startswith("TX: id=t-1")


def test_parse_quoted_list_group_and_content_values() -> None:
    message = parse_axl_message(
        'PS: id=p-1; kind=showcase; sub=frontend; tldr="alpha; beta"; '
        'art=["file:src/a.tsx","file:src/b.tsx"]; ctx=(a, b); {ctx=mem}'
    )

    assert message.fields["tldr"] == "alpha; beta"
    assert message.fields["art"] == ["file:src/a.tsx", "file:src/b.tsx"]
    assert message.fields["ctx"] == {"_group": ["a", "b"]}
    assert message.fields["content"] == "ctx=mem"


def test_duplicate_header_and_payload_fields_raise() -> None:
    with pytest.raises(AxlParseError, match="field `to` must appear at most once"):
        parse_axl_message("TX: id=t-1; to=@qa; to=@security; >review auth-release")

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


def test_split_list_items_rejects_unbalanced_values() -> None:
    with pytest.raises(AxlParseError, match="Unclosed quote"):
        _split_list_items('a, "b')
    with pytest.raises(AxlParseError, match="Unmatched"):
        _split_list_items("[a, b")


def test_prefix_specific_validation_rules() -> None:
    with pytest.raises(AxlParseError, match="directive"):
        parse_axl_message("TX: id=t-1; to=@backend-dev; pri=hi")
    with pytest.raises(AxlParseError, match="typed error"):
        parse_axl_message("ER: id=e-1; ref=t-1; sev=hi")
    with pytest.raises(AxlParseError, match="kind=reply"):
        parse_axl_message("PS: id=rp-1; {reply with no thread target}")
    with pytest.raises(AxlParseError, match="opts"):
        parse_axl_message("PS: id=vt-1; kind=poll; sub=axl; {indent pref?}")


def test_delta_mode_accepts_and_rejects_operation_vocabulary() -> None:
    operations = json.dumps(
        [{"op": "replace", "path": "/objectives/0/status", "value": "done"}],
        separators=(",", ":"),
    )
    message = parse_axl_message(
        "SY: id=sy-delta-1; mode=delta; ref=upp:project-alpha; "
        f"expected_revision_no=3; operations={json.dumps(operations)}",
        strict=True,
    )

    assert message.fields["expected_revision_no"] == 3
    assert json.loads(message.fields["operations"]) == [
        {"op": "replace", "path": "/objectives/0/status", "value": "done"}
    ]

    with pytest.raises(AxlParseError, match="operation `op`"):
        parse_axl_message(
            'SY: id=sy-delta-bad-op; mode=delta; ref=upp:p; '
            'operations="[{\\"op\\":\\"merge\\",\\"path\\":\\"/x\\",\\"value\\":1}]"',
            strict=True,
        )


def test_strict_recipient_fields_must_be_canonical_refs() -> None:
    with pytest.raises(AxlParseError, match="canonical `@recipient` atoms"):
        parse_axl_message("TX: id=t-bad-to; to=backend dev; >ship fix", strict=True)

    message = parse_axl_message(
        "TX: id=t-multi; to=[@qa,@security]; from=@lead; >review auth-release",
        strict=True,
    )

    assert message.fields["to"] == ["@qa", "@security"]


def test_transport_routes_and_filters_by_recipient() -> None:
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
        metadata={"sender": "planner", "target": "frontend-dev", "project_id": "proj-123"},
    )

    expected = {"ux": "ux-architect", "api": "payments-api"}
    assert transport.get_abbreviation_registry("project:proj-123") == expected
    assert transport.get_abbreviation_registry("dm:planner->frontend-dev") == expected
    assert transport.get_abbreviation_registry("channel:dm") == expected


def test_build_axl_message_uses_safe_content_and_payload_serialization() -> None:
    message = build_axl_message(
        "TX",
        fields={"id": "t-multiline-1", "to": "@reviewer"},
        directives=[">handoff reviewer"],
        payload={"summary": "first line\nsecond line\twith tab"},
        strict=True,
    )

    assert "\\n" in message
    assert parse_axl_message(message).payload["summary"] == "first line\nsecond line\twith tab"

    notice = build_axl_message(
        "PS",
        fields={"id": "p-safe-1", "kind": "notice", "content": 'say "ship it"'},
    )
    assert notice == 'PS: id=p-safe-1; kind=notice; {say "ship it"}'
    assert parse_axl_message(notice).fields["content"] == 'say "ship it"'


def test_compose_and_build_axl_message_are_equivalent() -> None:
    fields = {"id": "t-parity", "to": "@backend-dev", "pri": "hi"}

    assert compose_axl_message("TX", fields=fields, directives=[">impl api"], strict=True) == (
        build_axl_message("TX", fields=fields, directives=[">impl api"], strict=True)
    )


def test_axl_prefix_literal_matches_canonical_prefixes() -> None:
    assert set(get_args(AxlPrefix)) == set(AXL_CANONICAL_PREFIXES)


def test_long_namespace_reexports_package_api() -> None:
    from agent_exchange_language import parse_axl_message as compat_parse

    assert compat_parse("ST: ref=t-1; st=run").prefix == "ST"


def test_normalize_content_with_unbalanced_brace_falls_back_to_assignment() -> None:
    message = AxlMessage(
        prefix="PS",
        fields={"id": "p-1", "content": "deploy {staging", "kind": "notice"},
        payload={},
        raw="",
    )

    normalized = normalize_axl_message(message)
    assert 'content="deploy {staging"' in normalized
    assert parse_axl_message(normalized).fields["content"] == "deploy {staging"
