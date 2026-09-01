"""The Apache Beam pipeline that resolves Dynamics AX table inheritance.

AX 2012 splits one logical entity across two physical tables: a derived table
(CustTable) carries only its own columns and inherits the rest from a base
table (DirPartyTable) through a shared RecId. The join is not a foreign key —
it is only valid inside the same company (DataAreaId) *and* the same partition,
so RecId alone is not an identity.

That makes the migration hazard structural rather than binary. There are no
packed fields to unpack here; the way this source lies is by presenting a
derived row whose base row does not exist in its own company and partition.

Like the JDE pipeline this is the real transform: a CoGroupByKey performs the
inheritance join and a ParDo classifies the result, executed by the DirectRunner
and written out through beam.io.WriteToText. The module lives at the repository
root because Beam pickles the DoFn by reference.
"""
from __future__ import annotations

import json

import apache_beam as beam


def identity(row: dict) -> tuple:
    """AX identity is company + partition + RecId, never RecId on its own."""
    return (row["data_area_id"], row["partition_id"], row["rec_id"])


class ResolveAXInheritance(beam.DoFn):
    """Join one derived row to its base row, or reject it with a reason.

    `rec_id_index` maps a RecId to every (company, partition) that actually
    holds a base row for it. That is what lets the refusal be specific: a RecId
    absent everywhere is an orphan, whereas a RecId present only under another
    partition is an identity that has been bound across a partition boundary.
    Both are refused, but they are not the same defect and are not counted as
    one.
    """

    REJECTED = "rejected"

    def __init__(self, rec_id_index: dict):
        self._rec_id_index = rec_id_index

    def _reject(self, key, derived, reason, detail):
        # Quarantine locates the row and explains the refusal. It never carries
        # the row's contents.
        data_area_id, partition_id, rec_id = key
        return beam.pvalue.TaggedOutput(self.REJECTED, json.dumps({
            "recId": rec_id,
            "dataAreaId": data_area_id,
            "partitionId": partition_id,
            "reason": reason,
            "detail": detail[:160],
            "sourceTable": "custtable",
            "sourceKey": f"DATAAREAID={data_area_id} PARTITION={partition_id} RECID={rec_id}",
        }))

    def process(self, element):
        key, grouped = element
        derived = list(grouped["derived"])
        base = list(grouped["base"])
        if not derived:
            # A base row with no derived row is simply not a customer; it is
            # not an error and nothing is emitted for it.
            return
        row = derived[0]
        data_area_id, partition_id, rec_id = key

        if not base:
            elsewhere = [
                where for where in self._rec_id_index.get(rec_id, ())
                if where != (data_area_id, partition_id)
            ]
            if elsewhere:
                yield self._reject(
                    key, row, "cross_partition_identity_binding",
                    f"RecId {rec_id} has no base row in partition {partition_id}; "
                    f"it resolves only under {elsewhere[0][1]}, so the identity is "
                    "bound across a partition boundary")
            else:
                yield self._reject(
                    key, row, "orphan_derived_record",
                    f"CustTable RecId {rec_id} extends DirPartyTable, which holds no "
                    "row for that RecId in any company or partition")
            return

        parent = base[0]
        resolved = {
            "rec_id": rec_id,
            "data_area_id": data_area_id,
            "partition_id": partition_id,
            "party_name": parent["party_name"],
            "customer_group": row["customer_group"],
            "modified_datetime": row["modified_datetime"],
            "source_ordinal": rec_id,
            "_classes": {
                "rec_id": "public",
                "data_area_id": "public",
                "partition_id": "public",
                "party_name": "name",
                "customer_group": "public",
                "modified_datetime": "public",
            },
        }
        yield json.dumps(resolved)


def build(pipeline, derived_rows, base_rows, accepted_path: str, rejected_path: str):
    """Wire the inheritance join, then classify and write both outputs."""
    rec_id_index: dict = {}
    for row in base_rows:
        rec_id_index.setdefault(row["rec_id"], []).append(
            (row["data_area_id"], row["partition_id"]))

    derived = (
        pipeline
        | "ReadCustTable" >> beam.Create(derived_rows)
        | "KeyDerivedByIdentity" >> beam.Map(lambda row: (identity(row), row))
    )
    base = (
        pipeline
        | "ReadDirPartyTable" >> beam.Create(base_rows)
        | "KeyBaseByIdentity" >> beam.Map(lambda row: (identity(row), row))
    )
    outputs = (
        {"derived": derived, "base": base}
        | "JoinInheritance" >> beam.CoGroupByKey()
        | "ResolveAXInheritance" >> beam.ParDo(
            ResolveAXInheritance(rec_id_index)).with_outputs(
                ResolveAXInheritance.REJECTED, main="accepted")
    )
    outputs.accepted | "WriteAccepted" >> beam.io.WriteToText(accepted_path)
    outputs.rejected | "WriteRejected" >> beam.io.WriteToText(rejected_path)
    return outputs
