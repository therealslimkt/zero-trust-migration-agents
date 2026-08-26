# Trusted Google Cloud Evidence Bindings (Milestone 4)

This document describes the security and verification boundary implemented in Go to convert verified Google Cloud execution facts into the frozen `ControlPlaneEvidence` references.

> [!IMPORTANT]
> **Code Presence Alone is Not Cloud Proof.**
> The mere presence of this boundary code within the studio backend does not prove that a migration has actually executed in Google Cloud. Before invoking this boundary, the calling system must query the real Google Cloud APIs to retrieve and verify these facts. This boundary acts as a fail-closed converter that encodes verified cloud statements into canonical evidence records.

---

## 1. Required Facts to Retrieve from Google Cloud APIs

Before invoking the converter boundary (`VerifyAndConvert`), the caller must query the official Google Cloud APIs to obtain the following authentic execution facts:

### A. Dataflow Job Facts
*Query the Google Cloud Dataflow API (`dataflow.projects.locations.jobs.get`):*
1. **Project ID**: The GCP project where the job was run (e.g., `my-gcp-project`).
2. **Region**: The GCP region where the job was run (e.g., `us-central1`).
3. **Job ID**: The unique identifier of the Dataflow job.
4. **Terminal State**: The job state must be resolved and confirmed as successful terminal state (`JOB_STATE_DONE` or equivalent).
5. **Source ID**: The canonical legacy source migration target identifier (`jde`, `maxdb`, or `btrieve`).
6. **Input Artifact Digest**: The lowercase `sha256:` digest of the source manifest files read from GCS.
7. **Plan Digest**: The lowercase `sha256:` digest of the migration execution plan.

### B. BigQuery Table Write Facts
*Query the Google Cloud BigQuery API (`bigquery.jobs.get` / `bigquery.tables.get`):*
1. **Project ID**: The GCP project where the target BigQuery table is stored.
2. **Dataset ID**: The BigQuery dataset identifier.
3. **Table ID**: The BigQuery table name.
4. **Committed Row Count**: The number of records successfully written/inserted (non-negative).
5. **Rejected Row Count**: The number of records rejected or failed to load (non-negative).
6. **Output Digest**: The lowercase `sha256:` digest of the exact protected output rows, recomputed from the lineage-scoped BigQuery result.

### C. Reconciliation Facts
*Perform end-to-end audit reconciliation over the execution:*
1. **Records Read**: Total records loaded from source.
2. **Records Written**: Total records committed to destination.
3. **Records Rejected**: Total records rejected.
4. **Invariants**: Validate that `recordsRead == recordsWritten + recordsRejected`.
5. **Digest Bindings**: Ensure input digest, plan digest, and output digest match the values verified from Dataflow and BigQuery APIs.

---

## 2. Invariants Enforced by the Verification Boundary

The boundary enforces a strict zero-trust, fail-closed policy. Any validation or integrity check failure results in an immediate rejection of the facts.

| Rule / Invariant | Validation Logic |
| :--- | :--- |
| **Canonical Sources** | Only `jde`, `maxdb`, and `btrieve` are permitted. All three facts must refer to the exact same source ID. |
| **Successful Terminal State** | Dataflow job terminal state must exactly match the canonical API value `"JOB_STATE_DONE"`. Friendly aliases are rejected. |
| **Bounded Identifiers** | Project IDs, regions, datasets, and tables are validated against strict character sets and length boundaries to prevent parameter injection or buffer issues. |
| **Digests** | Every digest must be a canonical lowercase SHA-256 digest format matching `^sha256:[a-f0-9]{64}$`. |
| **Nonnegative Counts** | All row and record counters must be `>= 0` to prevent underflow. |
| **No Integer Overflow** | Count additions are checked using strict bounds checking (`written <= MaxInt64 - rejected`) to prevent overflow exploits. |
| **Equality Invariant** | Must satisfy the invariant: `RecordsRead == RecordsWritten + RecordsRejected`. |
| **Chain Binding** | Dataflow and BigQuery counts, digests, and sources are bound to the Reconciliation records to ensure they represent the same pipeline run. |
| **Registered Destination** | The Google Cloud project must match across Dataflow and BigQuery, and the target table must be the canonical table registered for the source. |

---

## 3. Evidence Generation Specs

Once verified, the converter outputs exactly three deterministic evidence structures matching the control plane schema:

1. **`dataflow_job` Evidence**:
   - **Artifact ID**: `art_dataflow_<sourceID>_<project_region_jobid_hash>`
   - **Digest**: SHA-256 hash of the Dataflow fact model.
2. **`bigquery_table` Evidence**:
   - **Artifact ID**: `art_bigquery_<sourceID>_<project_dataset_table_hash>`
   - **Digest**: SHA-256 hash of the BigQuery table write fact model.
3. **`reconciliation` Evidence**:
   - **Artifact ID**: `art_reconciliation_<sourceID>_<chain_hash>`
   - **Digest**: SHA-256 hash of the Reconciliation fact model.

No user-supplied text or identifying project names are leaked into the artifact IDs or API event summaries.
