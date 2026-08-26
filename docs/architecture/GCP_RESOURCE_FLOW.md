# Google Cloud Resource Flow and Trust Boundaries

## 1. Target Environment

Target cloud resources belong to project `ztm-agent-9049c3` and use `us-central1`, subject to a verified Vertex AI model-availability check.

Canonical private source names are:

- `legacy-jde-db`
- `legacy-maxdb`
- `legacy-btrieve-db`
- `sparky-sid-411116` (edge gateway)

Application configuration resolves these through Tailscale MagicDNS and never depends on their `100.x` addresses.

## 2. Target Data Flow

```text
Private legacy sources
        |
        v
Sparky deterministic scrubber + local Gemma
        |
        | sanitized metadata and synthetic samples only
        v
Vertex AI Gemini agent control plane
        |
        | validated declarative TransformPlan + durable evidence
        v
Single portfolio approval gate
        |
        v
Pre-registered Dataflow Flex Template
        |
        +--> BigQuery: jde_f0101
        +--> BigQuery: sap_kna1
        +--> BigQuery: accpac_arcus
        +--> BigQuery: migration_audit
```

## 3. Trust Boundaries

1. **Edge perimeter:** raw legacy data exists only here. Sparky performs deterministic redaction, local Gemma review, and an outbound PII check. Any uncertainty fails closed.
2. **Cloud control plane:** receives sanitized inputs, invokes Gemini under a dedicated identity, validates structured outputs, and stores evidence. It cannot execute arbitrary code.
3. **Human approval boundary:** approval is portfolio-wide and bound to the exact validated plan digest.
4. **Execution plane:** Dataflow consumes typed parameters with a pre-built template. Workers cannot invoke Gemini or change the approved plan.
5. **Warehouse boundary:** BigQuery stores normalized output plus append-only reconciliation and lineage evidence.

## 4. Target Service Identities

These identities are proposed resources, not evidence of current deployment:

- **Orchestrator identity:** Vertex invocation, target schema read, plan-object create/read, and Dataflow launch permissions scoped to required resources.
- **Dataflow worker identity:** Dataflow worker, staging-object access, and data-editor access scoped to the migration dataset.
- **Edge bridge identity:** create-only access to the sanitized ingress location, with no warehouse access.

The default Compute Engine service account and project-wide Editor role are prohibited. Bucket- and dataset-level bindings are preferred over project-wide roles.

## 5. Durable Evidence

The target `migration_audit` table records run ID, plan digest, source checksum, sanitized record totals, rejection totals, Dataflow job IDs, BigQuery row counts, operator approval, timestamps, and verification result. Logs must carry trace IDs but no raw PII or secrets.

## 6. Failure and Containment

- PII detection stops egress before Vertex AI and records only a sanitized alert.
- Invalid Gemini output never reaches approval.
- Source failure blocks portfolio approval unless the operator creates a new explicitly reduced-scope run.
- Unparseable records go to a typed dead-letter output with sanitized error details.
- Dataflow or verification failure sets the run to `failed`; it cannot be shown as migrated.
- The old arbitrary-execution Cloud Run service remains contained and must be replaced, not re-enabled.

## 7. Baseline vs. Target

| Component | Milestone 0 baseline | Target |
| --- | --- | --- |
| IAM | Default Compute identity with Editor | Dedicated resource-scoped identities |
| Runner | Contained arbitrary-execution Cloud Run service | Trusted Dataflow Flex Template |
| Warehouse | No migration dataset | Four verified target/audit tables |
| Region | Mixed regions | One documented region after the model-availability gate passes |
| Network | MaxDB still has a public IP | All source access through MagicDNS |
