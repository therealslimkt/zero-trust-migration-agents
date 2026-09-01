"""The Apache Beam pipeline that resolves Oracle EBS descriptive flexfields.

EBS lets a customer extend a table without changing its shape, by writing into
generic columns named ATTRIBUTE1..ATTRIBUTE15. What those columns *mean* is not
in the data: it is held in FND_DESCRIPTIVE_FLEXS, keyed by application, table,
context value, segment column and metadata version. ATTRIBUTE1 is
`customer_tier` for one context and `payment_profile` for another, in the same
column of the same table.

So the migration hazard here is semantic. Copying ATTRIBUTE1 into a warehouse
column called `attribute1` preserves the bytes and loses the meaning, and
guessing the meaning from the value is exactly the kind of coercion that
silently corrupts a migration. A row whose context has no mapping at the
declared metadata version is refused rather than carried across untyped.

Like the JDE pipeline this is the real transform: a ParDo over the flexfield
resolver, executed by the DirectRunner and written out through
beam.io.WriteToText. The module lives at the repository root because Beam
pickles the DoFn by reference.
"""
from __future__ import annotations

import json

import apache_beam as beam


GENERIC_COLUMNS = ("attribute1", "attribute2", "attribute3", "attribute4", "attribute5")


class ResolveDescriptiveFlexfield(beam.DoFn):
    """Rename generic attributes to their declared semantics, or reject the row.

    `flex_map` is keyed by (context_value, segment_column) and carries the
    semantic name and declared type for one metadata version. A context absent
    from that map means the warehouse has no name to land the value under, so
    the row is quarantined instead of being written with its meaning guessed.
    """

    REJECTED = "rejected"

    def __init__(self, flex_map: dict, metadata_version: str):
        self._flex_map = flex_map
        self._metadata_version = metadata_version

    def process(self, element):
        row = element
        party_id = row["party_id"]
        context = row["attribute_category"]

        mapped = {
            segment: semantics for (ctx, segment), semantics in self._flex_map.items()
            if ctx == context
        }
        if not mapped:
            # Quarantine locates the row and explains the refusal, never the
            # row's contents.
            yield beam.pvalue.TaggedOutput(self.REJECTED, json.dumps({
                "partyId": party_id,
                "attributeCategory": context,
                "reason": "unmapped_context_metadata",
                "detail": (
                    f"context {context!r} has no descriptive flexfield mapping at "
                    f"metadata version {self._metadata_version}; ATTRIBUTE1..5 cannot "
                    "be named without guessing"
                )[:160],
                "sourceTable": "hz_parties",
                "sourceKey": f"PARTY_ID={party_id}",
            }))
            return

        resolved = {
            "party_id": party_id,
            "party_name": row["party_name"],
            "attribute_category": context,
            "last_update_date": row["last_update_date"],
            "source_ordinal": party_id,
        }
        classes = {
            "party_id": "public",
            "party_name": "name",
            "attribute_category": "public",
            "last_update_date": "public",
        }
        for column in GENERIC_COLUMNS:
            semantics = mapped.get(column.upper())
            if semantics is None:
                continue
            semantic_name, _data_type = semantics
            resolved[semantic_name] = row.get(column)
            classes[semantic_name] = "public"

        resolved["_classes"] = classes
        yield json.dumps(resolved)


def build(pipeline, party_rows, flex_map, metadata_version, accepted_path: str,
          rejected_path: str):
    """Wire Create -> ParDo -> WriteToText for both outputs."""
    outputs = (
        pipeline
        | "ReadHzParties" >> beam.Create(party_rows)
        | "ResolveDescriptiveFlexfield" >> beam.ParDo(
            ResolveDescriptiveFlexfield(flex_map, metadata_version)).with_outputs(
                ResolveDescriptiveFlexfield.REJECTED, main="accepted")
    )
    outputs.accepted | "WriteAccepted" >> beam.io.WriteToText(accepted_path)
    outputs.rejected | "WriteRejected" >> beam.io.WriteToText(rejected_path)
    return outputs
