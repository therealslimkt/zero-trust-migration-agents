"""The Apache Beam pipeline that converts JDE physical records.

This is the real transform, not a description of one: `beam.Pipeline` with a
`ParDo` over a `DecodeJDERecord` DoFn, executed by the DirectRunner and written
out through `beam.io.WriteToText`. The DoFn calls the same code-owned adapter
the rest of the fleet uses, so what runs here is what was reviewed.

The module lives at the repository root because Beam pickles the DoFn by
reference and the worker must be able to import it by module path.
"""
from __future__ import annotations

import json

import apache_beam as beam


class DecodeJDERecord(beam.DoFn):
    """Turn one 65-byte IBM i record into typed columns, or reject it.

    A structurally invalid record is tagged to the 'rejected' output rather
    than raising, so one bad row cannot take down the bundle, and rejects stay
    countable instead of silently disappearing.
    """

    REJECTED = "rejected"

    def process(self, element):
        from edge_runtime.adapters import jde
        from edge_runtime.types import SOURCE_SPECS, SourcePayload

        number, payload = element
        # Accept the record either as raw bytes or as the hex a SQL client
        # returns, so the same DoFn serves the pipeline and ad-hoc replay.
        raw = bytes.fromhex(payload) if isinstance(payload, str) else bytes(payload)
        try:
            decoded = jde.decode(SourcePayload(spec=SOURCE_SPECS["jde"], data=raw))
        except Exception as error:  # structural fault: refuse the row, keep the count
            # Quarantine carries enough to find the row again in the source and
            # enough to explain the refusal, but never the row's contents.
            yield beam.pvalue.TaggedOutput(
                self.REJECTED,
                json.dumps({
                    "aban8": number,
                    "reason": type(error).__name__,
                    "detail": str(error)[:160],
                    "recordLength": len(raw),
                    "comp3FieldHex": raw[:5].hex(),
                    "sourceTable": "f0101",
                    "sourceKey": f"ABAN8={number}",
                }))
            return
        record = decoded.records[0]
        row = {field.name: field.value for field in record.fields}
        row["source_ordinal"] = number
        row["_classes"] = {field.name: field.category for field in record.fields}
        yield json.dumps(row)


def build(pipeline, rows, accepted_path: str, rejected_path: str):
    """Wire Create -> ParDo -> WriteToText for both outputs."""
    outputs = (
        pipeline
        | "ReadPhysicalRecords" >> beam.Create(rows)
        | "DecodeJDERecord" >> beam.ParDo(DecodeJDERecord()).with_outputs(
            DecodeJDERecord.REJECTED, main="accepted")
    )
    outputs.accepted | "WriteAccepted" >> beam.io.WriteToText(accepted_path)
    outputs.rejected | "WriteRejected" >> beam.io.WriteToText(rejected_path)
    return outputs
