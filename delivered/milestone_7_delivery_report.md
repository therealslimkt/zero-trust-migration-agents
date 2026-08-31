# Enterprise Fleet Milestone 7 delivery report

Status: **complete for the first live, private synthetic-cartridge runtime;
ready for review.**

M7 turns the first three fixture families into a real, digest-pinned Google
Cloud demonstration slice. It solves the gap between a browser-only fixture
preview and an agentically governed, contained source-examination path. The
result is intentionally a synthetic source emulator: it does not run licensed
JDE, Microsoft Dynamics, Oracle EBS, DB2, SQL Server, or Oracle Database
software, and it has no customer data connection.

## Delivered

### 1. Source-shaped cartridge folders and local one-line launches

`data/jde_e1_ibmi`, `data/dynamics_ax_2012_r3`, and
`data/oracle_ebs_19c` each contain a semantic `seed.yaml`, source-like
`init.sql`, Dockerfile, Compose file, and executable `start.sh`. These are
project-owned PostgreSQL compatibility representations, not vendor images.

For example, the JDE seed contains `F9860`, `F98711`, and `F0911` metadata and
an intentionally invalid CYYDDD `UPMJ` ordinal; AX contains `SQLDICTIONARY`,
`MODELELEMENT`, company/partition-scoped `RecId` values, `DirPartyTable`, and
`CustTable`; EBS contains `FND_TABLES`, `FND_COLUMNS`,
`FND_DESCRIPTIVE_FLEXS`, and `HZ_PARTIES`. Their respective invalid cases make
the required migration protections observable: reject impossible JDE dates,
preserve AX partition semantics, and resolve an EBS flexfield context before
naming `ATTRIBUTE1`.

The seeds identify a real deployment's required JDBC driver artifacts
(`jt400.jar`/`db2jcc4.jar`, `mssql-jdbc.jar`, and `ojdbc8.jar`) but do not ship
or download any proprietary binary.

### 2. Sealed gVisor cartridge runtime and repeatable evidence check

`cartridge_runtime/host/compose.yaml` starts three internal-only source
containers. It exposes no database port on the VM. The sole evidence runner is
non-root, read-only, has no capabilities or Docker socket, uses a 256 MiB / 0.5
CPU / 64-PID boundary, and requests Docker's `runsc` gVisor runtime.

The repair added explicit private `172.28.0.0/24` addresses for the three
sources. This avoids Docker DNS in gVisor while preserving an internal network.
It also recreates only that network on a metadata rollout, retaining the named
synthetic data volumes. The runner returns counts only, never seeded rows:

```json
{"schemaVersion":"keraun.cartridge-evidence/v1","synthetic":true,"checks":{"jdeInvalidCyyddd":1,"axOrphanDerived":2,"ebsUnmappedFlexfield":1}}
```

This means one deliberately invalid JDE date, two AX orphan-derived rows, and
one unmapped EBS flexfield were observed. It is fixture evidence, not a
migration result or customer-data proof.

### 3. ADK 2 approval pattern with a closed cloud executor

`agent_runtime/workflows/cartridge_provisioning.py` implements the agentic
pattern **parallel read-only preflight → join → human approval interrupt →
sealed idempotent action → verification**. The three preflight branches inspect
only seed metadata, image digests, and host policy. The side-effecting node
accepts only four Artifact Registry digest references and the SHA-256 of the
reviewed startup script. It cannot accept model-produced shell commands, SQL,
images, endpoints, credentials, or Docker-socket access.

`scripts/provision_cartridge_lab.py` binds `--apply` or `--repair` to the
exact dry-run plan digest. The M7 repair plan
`sha256:97b2769becbe5377fc239e9534268d45b324ae3b9609d03af2889450a307fa09`
therefore could only replace the sealed startup metadata and reset the known
host; it could not change VM size, service identity, VPC, ingress, or image
identity. The runtime factory was smoke-tested against `google-adk==2.7.1`.

No generative model was given cloud-mutation authority. This milestone's
implementation and verification were performed in the repository with the
closed executor; no external-subscription model conclusion is claimed. The
design remains compatible with using Claude Opus as a read-only coding/review
assistant in future work, while keeping final mutation authority deterministic.

### 4. Live Google Cloud private host and immutable supply chain

Cloud Build produced four Artifact Registry images. The live host uses these
immutable digests: JDE `d66986970e1f8b6763a12cd238a1de2f8c6a11f4f8a54802bf654e6685055e99`,
AX `db4a3db4fc5ef6916d40d89b931754c7504c43f09f0ef0afe9c582849c0b54a2`,
EBS `f2549720c0eca29601fd38e7ea387010b7b9769ffde1a8e65efd85c3310db1a8`,
and the repaired runner
`7147fc1904e8576a7738e071146ff4c8061e273c143eed6b3274fde6a78b9d73`.

The live `keraun-cartridge-lab` is a low-cost `e2-small` Compute Engine VM in
`us-central1-a`, private-only in `keraun-cartridge-vpc` / its
`10.119.104.0/28` subnet. It has no external IP. Its only ingress is TCP/22
from the Google IAP range, scoped to the dedicated service account, which has
Artifact Registry Reader rather than a key. Docker confirms `runsc` is
registered; the internal network is set to `172.28.0.0/24`; and the live VM
produced the sanitized evidence above on 2026-08-31.

`cloud_architecture/CLOUD_RESOURCE_MANIFEST.md` now records all live M7
resources, their operator Console links, immutable digests, trust boundaries,
and the temporary Cloud NAT retirement status.

## Verification

```text
ruby YAML parse for production/local Compose and focused Cloud Build config       PASS
Docker Desktop production Compose + explicit local runc override                  PASS
Docker Desktop evidence runner (then stack/volumes removed)                       PASS
venv/bin/python -m pytest tests/agent_runtime/test_cartridge_provisioning.py     PASS (7)
ADK 2.7.1 workflow construction smoke test                                         PASS
Cloud Build aa127d3c-b085-4242-859d-d3be9bad5418                                  SUCCESS
Sealed metadata repair + private VM reset                                          PASS
IAP runtime inspection: runsc registered, internal network, healthy sources       PASS
IAP sanitized evidence retrieval                                                    PASS
git diff --check                                                                    PASS
```

## Cost, security, and deliberate deferrals

The `e2-small` VM, 20 GB persistent disk, and temporary Cloud NAT are
continuously billable. The NAT/router remain **retirement-pending** because the
current bootstrap installs Docker and gVisor on startup; removing them without
first changing that dependency would make a fresh start unreliable. No public
demo service, hosted login flow, Dataflow Flex Template launch, real JDBC
connector, customer credential, customer record, production migration, Kata
Containers runtime, or full remaining four source families is delivered here.
The `keraun-demo` Cloud Run manifest row remains planned, not live.

Relevant commits: `8faa4a6` through `6a1a19e` on
`agent/m7/live-demo-and-manifest`. Merge and push identifiers are appended only
after the final milestone merge.
