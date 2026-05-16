"""AXL message models and shared prefix metadata.

AXL v2.0 defines 8 canonical authoring prefixes. The protocol vocabulary
is sourced from ``axl_protocol.json`` so the Python runtime and
TypeScript UI can share the same canonical tables.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, Field


class AxlParseError(ValueError):
    """Raised when AXL input is malformed or incomplete."""


def _load_protocol_metadata() -> dict[str, Any]:
    metadata_path = Path(__file__).with_name("axl_protocol.json")
    with metadata_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("AXL protocol metadata must be a JSON object")
    return cast("dict[str, Any]", data)


_AXL_PROTOCOL = _load_protocol_metadata()

# ── v2.0 canonical authoring prefixes ────────────────────────────────

AXL_V2_PREFIXES = tuple(str(item) for item in _AXL_PROTOCOL["v2_prefixes"])
AXL_CANONICAL_PREFIXES = AXL_V2_PREFIXES

AXL_KIND_LABELS: dict[str, str] = {
    str(kind): str(label) for kind, label in _AXL_PROTOCOL["kind_labels"].items()
}
AXL_ENUM_CONSTRAINTS: dict[str, frozenset[str]] = {
    str(field_name): frozenset(str(value) for value in values)
    for field_name, values in _AXL_PROTOCOL["enum_constraints"].items()
}
AXL_PREFIX_DEFAULTS: dict[str, dict[str, str]] = {
    str(prefix): {str(field): str(value) for field, value in defaults.items()}
    for prefix, defaults in _AXL_PROTOCOL["prefix_defaults"].items()
}
AXL_CANONICAL_FIELDS = frozenset(str(value) for value in _AXL_PROTOCOL["canonical_fields"])
AXL_FIELD_PREFIX_GUIDANCE: dict[str, frozenset[str]] = {
    str(field_name): frozenset(str(prefix) for prefix in prefixes)
    for field_name, prefixes in _AXL_PROTOCOL["field_prefix_guidance"].items()
}
AXL_SOCIAL_RX_FIELD_COMPATIBILITY = frozenset(
    str(value) for value in _AXL_PROTOCOL["social_rx_field_compatibility"]
)
AXL_ID_OPTIONAL_PREFIXES = frozenset(
    str(prefix) for prefix in _AXL_PROTOCOL["id_optional_prefixes"]
)
AXL_PS_ID_OPTIONAL_KINDS = frozenset(str(kind) for kind in _AXL_PROTOCOL["ps_id_optional_kinds"])
AXL_PS_REF_REQUIRED_KINDS = frozenset(str(kind) for kind in _AXL_PROTOCOL["ps_ref_required_kinds"])
AXL_RX_ID_OPTIONAL_STATUSES = frozenset(
    str(value) for value in _AXL_PROTOCOL["rx_id_optional_statuses"]
)
AXL_STREAM_CONTINUATION_VALUES = frozenset(
    str(value) for value in _AXL_PROTOCOL["stream_continuation_values"]
)
AXL_DELTA_OPERATION_OPS = frozenset(str(value) for value in _AXL_PROTOCOL["delta_operation_ops"])
AXL_CORE_ABBREVIATIONS = frozenset(str(value) for value in _AXL_PROTOCOL["core_abbreviations"])
AXL_SOCIAL_ABBREVIATIONS = frozenset(str(value) for value in _AXL_PROTOCOL["social_abbreviations"])

# Union type for canonical AXL 2.0 prefixes.
AxlPrefix = Literal[
    "TX",
    "RX",
    "ST",
    "ER",
    "EV",
    "SY",
    "NT",
    "PS",
]


class AxlMessage(BaseModel):
    """Canonical AXL v2.0 message."""

    prefix: AxlPrefix
    fields: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    raw: str


class AxlEnvelope(BaseModel):
    """AXL message and its resolved transport channel."""

    channel: Literal["state", "dm", "social"]
    message: AxlMessage
