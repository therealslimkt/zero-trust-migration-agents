from __future__ import annotations

import copy
import dataclasses
import datetime as dt
import decimal

import pytest

from control_plane.canonical import document_digest
from trusted_runtime.interpreter import ExecutionRejected, execute_plan
from ztm_security.approval import ApprovalRecord, PolicyDenied


RUN_ID = "mig_INTERPRETER01"
MANIFEST_DIGEST = "sha256:" + "1" * 64
PORTFOLIO_DIGEST = "sha256:" + "9" * 64


def _plan(*, operations=None, output_fields=None, source_id="jde"):
    plan = {
        "schemaVersion": "1.0.0",
        "planId": "plan_INTERPRETER01",
        "runId": RUN_ID,
        "sourceId": source_id,
        "sourceManifestDigest": MANIFEST_DIGEST,
        "target": {
            "dataset": "legacy_migration",
            "table": {
                "jde": "jde_f0101",
                "maxdb": "sap_kna1",
                "btrieve": "accpac_arcus",
            }[source_id],
        },
        "operations": operations
        or [{"operation": "rename", "from": "old", "to": "renamed"}],
        "outputFields": output_fields
        or [{"name": "renamed", "type": "string", "nullable": False}],
    }
    plan["planDigest"] = document_digest(plan)
    return plan


def _batch(values=None):
    values = values or [
        {"field": "old", "protection": "sanitized", "value": "safe"}
    ]
    return {
        "schemaVersion": "1.0.0",
        "batchId": "batch_INTERPRETER01",
        "runId": RUN_ID,
        "sourceId": "jde",
        "sourceManifestDigest": MANIFEST_DIGEST,
        "recordSet": "F0101",
        "schemaDigest": "sha256:" + "2" * 64,
        "recordCount": 1,
        "records": [
            {"recordId": "rec_INTERP01", "ordinal": 0, "values": values}
        ],
    }


def _approval(*, digest=PORTFOLIO_DIGEST, run_id=RUN_ID):
    return ApprovalRecord(
        approver="security-reviewer",
        plan_digest=digest,
        timestamp="2026-08-26T12:00:00Z",
        portfolio_run_id=run_id,
    )


def _execute(plan=None, batch=None, approval=None):
    return execute_plan(
        plan=plan or _plan(),
        record_batch=batch or _batch(),
        approval=approval or _approval(),
        portfolio_digest=PORTFOLIO_DIGEST,
    )


def _resign(plan):
    plan["planDigest"] = document_digest(plan, omit=("planDigest",))
    return plan


def test_valid_closed_operations_and_every_declared_type():
    values = [
        {"field": "old", "protection": "sanitized", "value": "kept"},
        {"field": "integer_value", "protection": "sanitized", "value": "42"},
        {"field": "decimal_value", "protection": "sanitized", "value": "12.50"},
        {"field": "date_value", "protection": "sanitized", "value": "2026-08-26"},
        {
            "field": "timestamp_value",
            "protection": "sanitized",
            "value": "2026-08-26T12:30:00Z",
        },
        {"field": "boolean_value", "protection": "sanitized", "value": "true"},
        {"field": "bytes_value", "protection": "sanitized", "value": "abc"},
        {
            "field": "token_value",
            "protection": "tokenized",
            "value": "tok_abcdefgh",
        },
        {"field": "discard", "protection": "sanitized", "value": "gone"},
    ]
    operations = [
        {"operation": "rename", "from": "old", "to": "string_value"},
        *[
            {
                "operation": "cast",
                "field": field,
                "targetType": target,
                "invalidPolicy": "reject",
            }
            for field, target in (
                ("string_value", "string"),
                ("integer_value", "integer"),
                ("decimal_value", "decimal"),
                ("date_value", "date"),
                ("timestamp_value", "timestamp"),
                ("boolean_value", "boolean"),
                ("bytes_value", "bytes"),
                ("token_value", "string"),
            )
        ],
        {"operation": "drop", "field": "discard"},
    ]
    output_fields = [
        {"name": "string_value", "type": "string", "nullable": False},
        {"name": "integer_value", "type": "integer", "nullable": False},
        {"name": "decimal_value", "type": "decimal", "nullable": False},
        {"name": "date_value", "type": "date", "nullable": False},
        {"name": "timestamp_value", "type": "timestamp", "nullable": False},
        {"name": "boolean_value", "type": "boolean", "nullable": False},
        {"name": "bytes_value", "type": "bytes", "nullable": False},
        {"name": "token_value", "type": "string", "nullable": False},
    ]

    result = _execute(_plan(operations=operations, output_fields=output_fields), _batch(values))

    row = result.rows[0]
    assert result.source_id == "jde"
    assert result.target == {"dataset": "legacy_migration", "table": "jde_f0101"}
    assert result.record_count == 1
    assert row["string_value"]["value"] == "kept"
    assert row["integer_value"]["value"] == 42
    assert row["decimal_value"]["value"] == decimal.Decimal("12.50")
    assert row["date_value"]["value"] == dt.date(2026, 8, 26)
    assert row["timestamp_value"]["value"] == dt.datetime(
        2026, 8, 26, 12, 30, tzinfo=dt.timezone.utc
    )
    assert row["boolean_value"]["value"] is True
    assert row["bytes_value"]["value"] == b"abc"
    assert row["token_value"] == {
        "protection": "tokenized",
        "value": "tok_abcdefgh",
    }
    assert result.output_digest.startswith("sha256:")
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.record_count = 2
    with pytest.raises(TypeError):
        result.rows[0]["string_value"]["value"] = "changed"
    detached = result.as_rows()
    detached[0]["string_value"]["value"] = "changed"
    assert result.rows[0]["string_value"]["value"] == "kept"


def test_output_is_deterministic_and_hashes_rows_only():
    plan = _plan()
    batch = _batch()
    first = _execute(plan, batch)
    batch["records"][0]["values"].reverse()
    second = _execute(plan, batch)
    assert first.rows == second.rows
    assert first.output_digest == second.output_digest

    other_target = copy.deepcopy(plan)
    other_target["target"]["dataset"] = "another_dataset"
    _resign(other_target)
    third = _execute(other_target, batch)
    assert first.output_digest == third.output_digest


def test_tampered_plan_is_rejected():
    plan = _plan()
    plan["target"]["dataset"] = "tampered"
    with pytest.raises(ExecutionRejected, match="^plan_digest$"):
        _execute(plan)


@pytest.mark.parametrize(
    "approval",
    [
        _approval(digest="sha256:" + "8" * 64),
        _approval(run_id="mig_ANOTHERRUN001"),
    ],
)
def test_stale_or_wrong_run_approval_is_rejected_before_bad_batch(approval):
    malformed_batch = {"a_secret_value": "must not be inspected"}
    with pytest.raises(PolicyDenied):
        _execute(batch=malformed_batch, approval=approval)


@pytest.mark.parametrize("key", ["runId", "sourceId", "sourceManifestDigest"])
def test_plan_batch_identity_must_agree(key):
    batch = _batch()
    if key == "runId":
        batch[key] = "mig_DIFFERENTRUN01"
    elif key == "sourceId":
        batch[key] = "maxdb"
    else:
        batch[key] = "sha256:" + "3" * 64
    with pytest.raises(ExecutionRejected, match="^plan_batch_mismatch$"):
        _execute(batch=batch)


@pytest.mark.parametrize(
    "operation",
    [
        {
            "operation": "decode_text",
            "inputField": "old",
            "outputField": "decoded",
            "encoding": "utf-8",
        },
        {
            "operation": "packed_decimal",
            "inputField": "old",
            "outputField": "number",
            "precision": 8,
            "scale": 0,
            "signed": True,
        },
        {
            "operation": "map_date",
            "inputField": "old",
            "outputField": "date",
            "inputFormat": "iso-8601",
            "outputFormat": "iso-8601-date",
            "invalidPolicy": "reject",
        },
        {
            "operation": "tokenize",
            "field": "old",
            "outputField": "token",
            "algorithm": "hmac-sha256",
            "keyReference": "secret://edge/token-key",
            "tokenFormat": "hex",
        },
    ],
)
def test_edge_only_operations_are_rejected(operation):
    with pytest.raises(ExecutionRejected, match="^edge_operation_in_cloud$"):
        _execute(_plan(operations=[operation]))


@pytest.mark.parametrize("bad_key", ["code", "command", "script", "expression", "callback", "sql", "imports"])
def test_executable_or_unknown_operation_fields_are_rejected(bad_key):
    plan = _plan()
    plan["operations"][0][bad_key] = "sensitive payload"
    _resign(plan)
    with pytest.raises(ExecutionRejected) as caught:
        _execute(plan)
    assert str(caught.value) == "plan_contract"
    assert "sensitive" not in repr(caught.value)


def test_duplicate_record_fields_are_rejected():
    batch = _batch(
        [
            {"field": "old", "protection": "sanitized", "value": "first"},
            {"field": "old", "protection": "sanitized", "value": "second"},
        ]
    )
    with pytest.raises(ExecutionRejected, match="^batch_fields$"):
        _execute(batch=batch)


@pytest.mark.parametrize("ordinals", [[0, 0], [0, 2], [1, 0]])
def test_duplicate_or_missing_ordinals_are_rejected(ordinals):
    batch = _batch()
    batch["recordCount"] = 2
    batch["records"].append(copy.deepcopy(batch["records"][0]))
    batch["records"][1]["recordId"] = "rec_INTERP02"
    for record, ordinal in zip(batch["records"], ordinals):
        record["ordinal"] = ordinal
    with pytest.raises(ExecutionRejected, match="^batch_ordinals$"):
        _execute(batch=batch)


def test_naive_timestamp_is_rejected():
    plan = _plan(
        operations=[
            {
                "operation": "cast",
                "field": "old",
                "targetType": "timestamp",
                "invalidPolicy": "reject",
            }
        ],
        output_fields=[
            {"name": "old", "type": "timestamp", "nullable": False}
        ],
    )
    batch = _batch(
        [{"field": "old", "protection": "sanitized", "value": "2026-08-26T12:00:00"}]
    )
    with pytest.raises(ExecutionRejected, match="^invalid_cast$"):
        _execute(plan, batch)


def test_record_count_and_record_ids_are_exact_and_unique():
    count_batch = _batch()
    count_batch["recordCount"] = 2
    with pytest.raises(ExecutionRejected, match="^batch_record_count$"):
        _execute(batch=count_batch)

    id_batch = _batch()
    id_batch["recordCount"] = 2
    id_batch["records"].append(copy.deepcopy(id_batch["records"][0]))
    id_batch["records"][1]["ordinal"] = 1
    with pytest.raises(ExecutionRejected, match="^batch_record_ids$"):
        _execute(batch=id_batch)


def test_records_must_have_the_same_complete_field_set():
    batch = _batch()
    batch["recordCount"] = 2
    batch["records"].append(
        {
            "recordId": "rec_INTERP02",
            "ordinal": 1,
            "values": [
                {"field": "different", "protection": "sanitized", "value": "safe"}
            ],
        }
    )
    with pytest.raises(ExecutionRejected, match="^batch_fields$"):
        _execute(batch=batch)


@pytest.mark.parametrize(
    "operation",
    [
        {"operation": "rename", "from": "missing", "to": "renamed"},
        {"operation": "drop", "field": "missing"},
        {
            "operation": "cast",
            "field": "missing",
            "targetType": "string",
            "invalidPolicy": "reject",
        },
    ],
)
def test_operations_must_reference_existing_fields(operation):
    with pytest.raises(ExecutionRejected, match="^operation_missing_field$"):
        _execute(_plan(operations=[operation]))


def test_rename_cannot_overwrite_a_field():
    plan = _plan(
        operations=[{"operation": "rename", "from": "old", "to": "existing"}],
        output_fields=[{"name": "existing", "type": "string", "nullable": False}],
    )
    batch = _batch(
        [
            {"field": "old", "protection": "sanitized", "value": "safe"},
            {"field": "existing", "protection": "sanitized", "value": "safe"},
        ]
    )
    with pytest.raises(ExecutionRejected, match="^rename_overwrite$"):
        _execute(plan, batch)


def test_invalid_cast_reject_and_null_policy():
    reject_plan = _plan(
        operations=[
            {
                "operation": "cast",
                "field": "old",
                "targetType": "integer",
                "invalidPolicy": "reject",
            }
        ],
        output_fields=[{"name": "old", "type": "integer", "nullable": False}],
    )
    with pytest.raises(ExecutionRejected, match="^invalid_cast$"):
        _execute(reject_plan)

    null_plan = copy.deepcopy(reject_plan)
    null_plan["operations"][0]["invalidPolicy"] = "null"
    null_plan["outputFields"][0]["nullable"] = True
    _resign(null_plan)
    result = _execute(null_plan)
    assert result.rows[0]["old"] == {"protection": "sanitized", "value": None}


@pytest.mark.parametrize("nonfinite", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_input_is_always_rejected_without_echo(nonfinite):
    batch = _batch(
        [{"field": "old", "protection": "sanitized", "value": nonfinite}]
    )
    with pytest.raises(ExecutionRejected) as caught:
        _execute(batch=batch)
    assert str(caught.value) == "nonfinite_numeric"


def test_tokenized_values_can_only_remain_strings():
    plan = _plan(
        operations=[
            {
                "operation": "cast",
                "field": "old",
                "targetType": "integer",
                "invalidPolicy": "null",
            }
        ],
        output_fields=[{"name": "old", "type": "integer", "nullable": True}],
    )
    batch = _batch(
        [{"field": "old", "protection": "tokenized", "value": "tok_abcdefgh"}]
    )
    with pytest.raises(ExecutionRejected, match="^tokenized_type_change$"):
        _execute(plan, batch)


def test_nullability_and_output_field_and_type_mismatches():
    null_batch = _batch(
        [{"field": "old", "protection": "sanitized", "value": None}]
    )
    with pytest.raises(ExecutionRejected, match="^output_nullability$"):
        _execute(batch=null_batch)

    mismatch_plan = _plan(
        operations=[{"operation": "drop", "field": "old"}],
        output_fields=[{"name": "expected", "type": "string", "nullable": False}],
    )
    with pytest.raises(ExecutionRejected, match="^output_field_mismatch$"):
        _execute(mismatch_plan)

    type_plan = _plan(
        operations=[{"operation": "cast", "field": "old", "targetType": "string", "invalidPolicy": "reject"}],
        output_fields=[{"name": "old", "type": "integer", "nullable": False}],
    )
    with pytest.raises(ExecutionRejected, match="^output_type$"):
        _execute(type_plan)


def test_output_field_declarations_must_be_unique():
    plan = _plan(
        output_fields=[
            {"name": "renamed", "type": "string", "nullable": False},
            {"name": "renamed", "type": "string", "nullable": False},
        ]
    )
    with pytest.raises(ExecutionRejected, match="^output_duplicate_field$"):
        _execute(plan)


def test_target_must_be_pre_registered_for_source():
    plan = _plan()
    plan["target"]["table"] = "sap_kna1"
    _resign(plan)
    with pytest.raises(ExecutionRejected, match="^target_not_registered$"):
        _execute(plan)


def test_result_repr_and_errors_do_not_expose_values():
    secret = "should-never-appear"
    result = _execute(batch=_batch([{"field": "old", "protection": "sanitized", "value": secret}]))
    assert secret not in repr(result)
    assert "rows=" not in repr(result)

    batch = _batch(
        [
            {"field": "old", "protection": "sanitized", "value": secret},
            {"field": "old", "protection": "sanitized", "value": secret},
        ]
    )
    with pytest.raises(ExecutionRejected) as caught:
        _execute(batch=batch)
    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)
