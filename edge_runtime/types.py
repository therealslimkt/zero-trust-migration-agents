"""Internal edge types.

`SourcePayload.data` may contain raw legacy records and must never be serialized,
logged, or sent to a cloud service. Adapters and redaction run in the same edge
trust boundary before producing the public RecordBatch contract.
"""

from __future__ import annotations

import dataclasses
import hashlib
from typing import Union


LegacyScalar = Union[str, int, float, bool, None]

FIELD_CATEGORIES = frozenset(
    {
        "public",
        "name",
        "email",
        "phone",
        "address",
        "governmentId",
        "financialAccount",
        "other",
    }
)


@dataclasses.dataclass(frozen=True)
class SourceSpec:
    source_id: str
    hostname: str
    remote_path: str
    source_format: str


SOURCE_SPECS = {
    "jde": SourceSpec(
        source_id="jde",
        hostname="legacy-jde-db",
        remote_path="/home/kohalloran/F0101_address_book.bin",
        source_format="jde-as400-f0101",
    ),
    "maxdb": SourceSpec(
        source_id="maxdb",
        hostname="legacy-maxdb",
        remote_path="/home/kohalloran/KNA1_clustered_export.bin",
        source_format="sap-maxdb-kna1-cluster",
    ),
    "btrieve": SourceSpec(
        source_id="btrieve",
        hostname="legacy-btrieve-db",
        remote_path="/home/kohalloran/dummy_accpac.mkd",
        source_format="accpac-btrieve-arcus",
    ),
}


def get_source_spec(source_id: str) -> SourceSpec:
    try:
        return SOURCE_SPECS[source_id]
    except KeyError as exc:
        raise ValueError(f"unsupported source_id: {source_id}") from exc


@dataclasses.dataclass(frozen=True)
class SourcePayload:
    spec: SourceSpec
    data: bytes = dataclasses.field(repr=False)

    @property
    def size_bytes(self) -> int:
        return len(self.data)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclasses.dataclass(frozen=True)
class DecodedField:
    """One edge-only legacy value with an explicit deterministic policy hint."""

    name: str
    value: LegacyScalar = dataclasses.field(repr=False)
    category: str = "public"

    def __post_init__(self) -> None:
        if not self.name or not self.name.replace("_", "").isalnum():
            raise ValueError("decoded field name must be alphanumeric or underscore")
        if self.category not in FIELD_CATEGORIES:
            raise ValueError(f"unsupported field category: {self.category}")


@dataclasses.dataclass(frozen=True)
class DecodedRecord:
    """A decoded record that never includes legacy values in its repr."""

    ordinal: int
    fields: tuple[DecodedField, ...] = dataclasses.field(repr=False)

    def __post_init__(self) -> None:
        if self.ordinal < 0:
            raise ValueError("record ordinal must be non-negative")
        if not self.fields:
            raise ValueError("decoded record must contain fields")
        names = [field.name for field in self.fields]
        if len(names) != len(set(names)):
            raise ValueError("decoded field names must be unique")


@dataclasses.dataclass(frozen=True)
class DecodedSource:
    """Edge-only adapter output, prior to deterministic redaction."""

    source_id: str
    record_set: str
    records: tuple[DecodedRecord, ...] = dataclasses.field(repr=False)

    def __post_init__(self) -> None:
        if self.source_id not in SOURCE_SPECS:
            raise ValueError(f"unsupported source_id: {self.source_id}")
        if not self.record_set:
            raise ValueError("record_set is required")
        if not self.records:
            raise ValueError("decoded source must contain records")
