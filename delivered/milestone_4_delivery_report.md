# Enterprise Fleet Milestone 4 delivery report

Status: **complete locally; merged and pushed to `main` after this report commit**

Milestone 4 delivers the deadline-fast-track cartridge lab: JDE, Microsoft
Dynamics AX, and Oracle E-Business Suite on Oracle 19c. Every result is from
invented, checked-in, deterministic local fixture data. The slice is ready to
exercise in the Studio at `/lab/m4`; it does not claim a deployed plugin,
Dataflow job, BigQuery table, hosted backend, customer-data extraction, or
production migration.

## What was delivered

### 1. Closed shared fixture packet and portable evidence boundary

`cartridge_lab/core.py` defines the exact eight-artifact packet contract:
`manifest`, `metadata`, `snapshot`, `delta`, `invalid`, `bronze`, `silver`,
and `reconciliation`. The only permitted readiness label is
`synthetic_fixture`. Artifact, transform, reconciliation, and packet digests
are deterministic SHA-256 values over a narrow portable JSON domain; NaN,
floats, non-string map keys, unsupported values, and integers outside signed
64-bit range fail closed.

The packet keeps its validated evidence as private canonical JSON and returns
a fresh detached artifact copy to callers. For example, appending a fabricated
silver row to `packet.artifacts` cannot alter the packet's stored digest or its
next artifact read. This prevents a post-validation caller mutation from
reusing stale reconciliation evidence.

### 2. JD Edwards EnterpriseOne hero cartridge

`cartridge_lab/jde.py` and `edge_runtime/adapters/jde.py` deliver the deep
reference lane for a synthetic F0911 journal. JDE UPMJ numeric `CYYDDD` dates
strictly handle blank zero, leap-year dates, and invalid values. The fixture
applies a contiguous, ordered insert/update/delete journal keyed by company,
document type, document number, line, and ledger; it produces deterministic
bronze and current-state silver rows.

Example: UPMJ `100366` is accepted as leap-day year 2000, while day 366 in a
non-leap year, day zero, strings, booleans, negative values, and out-of-range
centuries fail closed. A delete requires an existing exact source identity;
the reconciliation binds the original snapshot, journal, bronze, and silver
outputs. The complete local-only explanation is in
`docs/cartridges/M4_JDE_HERO.md`.

### 3. Microsoft Dynamics AX metadata and identity cartridge

`cartridge_lab/ax.py` delivers a synthetic Dynamics AX fixture with its
identity boundary explicitly modeled as `(company, partition, table, RecId)`.
It validates base/derived metadata, verifies the snapshot high watermark,
applies an ordered delta, writes bronze/silver expected artifacts, and
reconciles two tombstones.

Example: an orphan derived row, duplicate identity, or cross-company identity
binding is rejected rather than coerced. The canonical packet reports six
snapshot rows, six expected silver rows, and three invalid vectors. See
`docs/cartridges/M4_DYNAMICS_AX.md` for fixture limits and source semantics.

### 4. Oracle EBS / Oracle 19c flexfield cartridge

`cartridge_lab/oracle_ebs.py` delivers a synthetic `HZ_PARTIES` EBS fixture
that resolves descriptive flexfields through the full five-part key:

```text
(application, table, context, segment, metadataVersion)
```

For example, `ATTRIBUTE1` resolves to `customerTier` under `CUSTOMER_EXT` but
to `paymentProfile` under `SUPPLIER_EXT`; it is never inferred from a column
name alone. The fixture applies strict `LAST_UPDATE_DATE` deltas and explicit
delete tombstones. The packet rejects missing/ambiguous context, stale
metadata versions, timestamp-at-watermark changes, per-key reverse/stale
events, unknown deletes, and delete-context mismatches.

The final lineage now binds the canonical **contents** of FND metadata—not
only its version label—alongside the input, bronze, silver, and transform
digests. For example, adding `DIAMOND` to an allowed-value list makes the
checked-in reconciliation fail rather than leaving its lineage digest stable.
The final fixture contains three snapshot rows, two upserts, one delete, three
silver rows, and three invalid vectors. See
`docs/cartridges/M4_ORACLE_EBS_19C.md`.

### 5. Testable additive Studio evidence surface

The public Studio route `/lab/m4` is an additive `Three-cartridge local lab`.
It has a visible `LOCAL SYNTHETIC FIXTURE` status and an explicit truth
boundary that says no Dataflow job, BigQuery table, hosted backend, customer
data, or production plugin is represented. The landing page links to it; the
frozen v1 replay/API behavior was not changed.

`studio/src/web/pages/lab/m4FixtureData.json` contains only the bounded UI
summary fields: display/source identity, readiness, three digests, and record
counts. `cartridge_lab/m4.py` freshly rebuilds all three packets and
`tests/cartridges/test_m4_ui_projection.py` proves the checked-in UI file is
byte-for-value equal to that verified projection. The tabs therefore display
actual local packet evidence rather than invented UI success values.

To inspect it locally:

```sh
cd studio
npm run dev:m4
# open http://localhost:5173/lab/m4
```

## Agentic execution pattern and model use

The milestone used the planned bounded dynamic map/reduce pattern:

```text
shared closed harness -> three independent deterministic cartridge compilers
-> digest/fidelity join -> UI projection -> adversarial evaluator -> repair
```

JDE, AX, and Oracle each had a narrow independent lane. The integration owner
joined only the shared packet API and then ran the deterministic UI projection.
An independent read-only adversarial reviewer found three real blockers in the
first join (Oracle metadata lineage, reverse per-key deltas, and shallow packet
immutability). Merge was held; the remediation added the failing tests, and
the reviewer confirmed all three were resolved with no remaining scoped
blocker.

Claude Opus 5 was requested for the cartridge coding lanes as the preferred
assistant, but the available CLI was not authenticated and managed review
denied private-repository transfer. No Opus authorship or external review is
claimed. The bounded native implementation fallback and integration/review
used the available local agents; no customer data, credentials, proprietary
binaries, or production records were sent to a model.

## Verification evidence

Final joined-tree gates:

```text
venv/bin/python -m scripts.verify_v1_baseline
  PASS
  Python: 537 passed, 3 expected skips, 1 existing Pydantic warning
  M4 historical focused suite: 36 passed
  Go tests, race tests, and vet: passed
  Studio build and lint: passed (one Fast Refresh export warning)
  Studio: 12 files / 46 tests passed
  whitespace: passed

M4 joined cartridge and JDE adapter regression
  44 passed

Independent remediation review
  25 scoped core + Oracle + JDE tests passed
  metadata tamper, stale reverse delta, and mismatched delete all rejected
```

## Branches and commits

All M4 lanes began from an origin-current `main` at `da6a537` in fresh,
separate worktrees. The integration branch was `agent/v2-m4-integration`.

- `a5f23d0` — shared local fixture packet contract
- `d2ab230` — additive local Studio cartridge lab
- `b1e4095` — Oracle EBS/Oracle 19c cartridge
- `0e47705` — JDE hero cartridge
- `5d15e25` — Dynamics AX cartridge
- `42c208e`, `65201bc` — verified UI projection
- `f3fc1c5` — integrity remediation after adversarial review

## Truth boundary and deferred work

Implemented and proven locally: the three named synthetic fixture compilers,
artifact validation, fail-closed invalid cases, deterministic reconciliation,
portable evidence digests, an evidence-bound UI view, and regression gates.

Deliberately deferred: SAP, Sage, additional IBM i-native, and standalone
COBOL cartridges; live source connectors; private connectivity and IAM;
Dataflow Flex Template images/jobs; GCS; BigQuery; Cloud SQL changes; hosted
Mission Control runtime; customer data; plugin packaging/signing; and any
production or cloud-readiness claim. Those need later M5/M6 implementation
and separate live evidence.
