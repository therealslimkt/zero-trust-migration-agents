"""Deterministic, fail-closed protection before any model sees a record."""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import hmac
import json
import re

from edge_runtime.types import DecodedSource, LegacyScalar


PII_CATEGORIES = (
    "name",
    "email",
    "phone",
    "address",
    "governmentId",
    "financialAccount",
    "other",
)

_RESIDUAL_PATTERNS = (
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)"),
)


class RedactionBlocked(RuntimeError):
    """Raised without field values when deterministic protection is incomplete."""


@dataclasses.dataclass(frozen=True)
class ProtectedField:
    name: str
    protection: str
    value: LegacyScalar = dataclasses.field(repr=False)

    def as_contract_value(self) -> dict[str, LegacyScalar]:
        return {
            "field": self.name,
            "protection": self.protection,
            "value": self.value,
        }


@dataclasses.dataclass(frozen=True)
class ProtectedRecord:
    ordinal: int
    record_id: str
    fields: tuple[ProtectedField, ...] = dataclasses.field(repr=False)

    def as_contract_record(self) -> dict[str, object]:
        return {
            "recordId": self.record_id,
            "ordinal": self.ordinal,
            "values": [field.as_contract_value() for field in self.fields],
        }


@dataclasses.dataclass(frozen=True)
class SanitizedSource:
    source_id: str
    record_set: str
    records: tuple[ProtectedRecord, ...] = dataclasses.field(repr=False)

    def as_candidate(self) -> dict[str, object]:
        return {
            "sourceId": self.source_id,
            "recordSet": self.record_set,
            "records": [record.as_contract_record() for record in self.records],
        }


@dataclasses.dataclass(frozen=True)
class DeterministicRedaction:
    sanitized: SanitizedSource = dataclasses.field(repr=False)
    finding_count: int
    category_counts: dict[str, int]
    evidence_digest: str


class DeterministicRedactor:
    """Tokenize classified fields and block residual PII in public fields."""

    ruleset_version = "1.0.0"

    def __init__(self, token_key: bytes) -> None:
        if len(token_key) < 32:
            raise ValueError("token key must contain at least 32 bytes")
        self._token_key = token_key

    def _tokenize(
        self,
        *,
        source_id: str,
        ordinal: int,
        field_name: str,
        value: LegacyScalar,
    ) -> str:
        message = json.dumps(
            [source_id, ordinal, field_name, value],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hmac.new(self._token_key, message, hashlib.sha256).digest()[:18]
        return "tok_" + base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    @staticmethod
    def _has_residual_pii(value: LegacyScalar) -> bool:
        return isinstance(value, str) and any(
            pattern.search(value) for pattern in _RESIDUAL_PATTERNS
        )

    def sanitize(self, source: DecodedSource) -> DeterministicRedaction:
        category_counts = {category: 0 for category in PII_CATEGORIES}
        protected_records = []

        for record in source.records:
            protected_fields = []
            for field in record.fields:
                if field.category == "public":
                    if self._has_residual_pii(field.value):
                        raise RedactionBlocked(
                            "deterministic protection blocked a public field"
                        )
                    protected = ProtectedField(field.name, "sanitized", field.value)
                else:
                    category_counts[field.category] += 1
                    protected = ProtectedField(
                        field.name,
                        "tokenized",
                        self._tokenize(
                            source_id=source.source_id,
                            ordinal=record.ordinal,
                            field_name=field.name,
                            value=field.value,
                        ),
                    )
                protected_fields.append(protected)

            record_seed = json.dumps(
                [
                    source.source_id,
                    record.ordinal,
                    [field.as_contract_value() for field in protected_fields],
                ],
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            record_id = "rec_" + hashlib.sha256(record_seed).hexdigest()[:16]
            protected_records.append(
                ProtectedRecord(record.ordinal, record_id, tuple(protected_fields))
            )

        sanitized = SanitizedSource(
            source.source_id,
            source.record_set,
            tuple(protected_records),
        )
        evidence = json.dumps(
            sanitized.as_candidate(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return DeterministicRedaction(
            sanitized=sanitized,
            finding_count=sum(category_counts.values()),
            category_counts=category_counts,
            evidence_digest="sha256:" + hashlib.sha256(evidence).hexdigest(),
        )
