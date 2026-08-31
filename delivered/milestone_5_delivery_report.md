# Enterprise Fleet Milestone 5 delivery report

Status: **complete for the bounded, locally verified M5 slice; merged to
`main`**

M5 makes Keraun testable as an authenticated local Mission Control surface
without presenting fixture activity as cloud execution. It adds an inert
offline plugin release, a fail-closed persisted-workflow inspector boundary,
a no-setup loopback login/demo path, and a release-bound outbound-mTLS
evidence adapter. No live cloud resource, customer source, private key,
certificate, CA, plugin activation, or production release was used.

## What changed

### 1. Inert offline plugin reference package and verification

`plugin_factory/` introduces a narrow Agent Plugins 1.0-compatible,
skills-only reference package: `inert-fixture-inspector`. It contains one
descriptive skill and an empty MCP map; it cannot execute a tool, start an MCP
server, download anything, unpack an archive, or activate itself.

The factory validates containment, symlinks, regular-file type, case-folding,
bounded file counts/sizes, strict JSON, a closed plugin profile, skill
frontmatter, and empty MCP configuration. It deterministically writes an
inventory, `SHA256SUMS`, CycloneDX 1.7 SBOM, in-toto Statement v1 / SLSA
provenance metadata, and a disabled bundle manifest. For example, an added
file or one changed byte in `SKILL.md` causes verification to fail with
`checksums_mismatch`.

`plugin_factory/verifiers/verify-plugin.sh` and
`plugin_factory/verifiers/Verify-Plugin.ps1` verify only bytes against a
required out-of-band release digest. The Bash verifier was executed locally;
PowerShell is supplied and statically checked, but `pwsh` was unavailable on
this host. The provenance is integrity metadata, **not** a publisher
signature, KMS signature, or SLSA-level claim.

### 2. Persisted workflow-evidence inspector

The protected source view now contains `WorkflowEvidencePanel`. It can display
only a closed, contiguous server projection of persisted model calls,
deterministic nodes, checkpoints, and approval interrupts. It shows
**Workflow evidence unavailable** if that projection is absent, malformed, or
unconfigured; it never reconstructs a claim from timestamps, narrated SSE
events, browser state, prompts, or raw data.

The optional authenticated BFF extension
`GET /api/web/v1/runs/{run_id}/workflow-evidence` verifies the existing run
owner first and then calls an injected read-only persisted-evidence reader.
Foreign/missing runs and absent reader wiring return not-found. A malformed
reader response is rejected server-side; a malformed/non-2xx/404 browser
response becomes `unavailable`. Example valid entries must contain a
contiguous sequence, event ID, SHA-256 evidence digest, and either exact
model/deterministic identity or an interrupt fixed to
`approval_endpoint`.

The endpoint is deliberately an optional web extension: neither frozen v1
control-plane API nor the frozen three-route v2 contract was changed. See
`docs/execution/M5_PERSISTED_WORKFLOW_EVIDENCE.md`.

### 3. Testable local authenticated Mission Control

`npm run dev:demo` now works with no manually-created state file. It allocates
a temporary durable control-plane path, keeps port 5173 when available, and
automatically selects a free loopback UI port when 5173 is already occupied.
It also allocates a free loopback backend port, passes both endpoints to the
Vite proxy/BFF allowlist, and prints their URLs. The local profile
creates exactly one owned canonical three-source portfolio only when state is
empty; a restart reuses it.

The initial record is intentionally honest: state `created`, one creation
event, zero read/written/rejected counts, no approval, no plan digest, no
artifacts, no cloud verification, and no workflow-evidence reader. The local
credential is public but accepted only by that loopback-only process. This is
an interaction/test path, not Google Identity Platform, a hosted backend, or
a cartridge execution.

### 4. Outbound-mTLS release binding boundary

`M5ValidateOutboundMTLSReleaseBinding` validates a non-secret enrollment
reference against the exact M3 release tuple: tenant, run, approval, release,
plan digest, artifact digest, client-certificate fingerprint, DNS server name,
and validity window. Any swap, expired window, malformed fingerprint, URL, or
localhost server name fails closed.

The adapter deliberately does not create a CA, mint/read a certificate or
private key, make a network connection, perform mTLS, persist enrollment, or
create a release. The M3 release authority remains the only release creator;
deployment composition must separately prove enrollment and handshake.

## Agentic execution and models

M5 used parallel feature slices over frozen boundaries, then a deterministic
integration join:

```text
inert plugin evidence | authenticated local demo | workflow projection UI
| release-binding policy -> independent tests -> integration gates
```

Claude Opus 5 was attempted for the plugin/security and API-review lanes. One
CLI status probe reported authentication, but usable review/coding invocations
either returned no output or reported capacity/authentication failure. No
Opus-authored output is claimed. Native local agents implemented and reviewed
the bounded changes; no customer data, credentials, proprietary binaries, or
production records were provided to any model.

## Verification evidence

The joined integration branch passed:

```text
studio-backend: go test ./... -count=1          PASS
studio-backend: go vet ./...                    PASS
Studio launcher tests: 4/4                      PASS
Studio unit tests: 14 files / 50 tests          PASS
Studio production build                          PASS
Studio lint                                      PASS with one pre-existing M4 Fast Refresh warning
Studio Playwright: 6/6                           PASS
Plugin factory: 7/7 unittest cases              PASS
Bash plugin verifier                             verified_inert
git diff --check                                 PASS
```

The exact live preflight command was also exercised:

```sh
cd studio
npm run dev:demo -- --port 5183
```

It selected a disposable backend port, served the UI, and returned one
authenticated owned run with all migration counters zero. The temporary Vite
and Go processes were stopped after the check.

The remediation gate additionally reserves the preferred frontend port before
launch. `npm run dev:demo` must select and print a different loopback UI URL
while that port is occupied, and the BFF must admit that exact selected Origin.
This prevents the M4 fixture lab and the authenticated M5 demo from blocking
one another.

## Branches and commits

Fresh M5 worktrees were created from origin-current `main` at `55923c2`.
The integration branch is `agent/v2-m5-integration`.

- `0fb3847` — fail-closed workflow evidence inspector
- `6cb400c` — inert offline plugin factory and verifier artifacts
- `7d85632` — honest empty-state local demo seed and state-free launcher
- `e8cefff` — automatic isolated local backend port
- `7f6623f` — outbound-mTLS release-binding validator
- `02a6ed6` / `e953d61` — browser adapter and authenticated persisted-evidence boundary

## Truth boundary and deferred work

Implemented: the inert package/evidence verifier, a closed UI/API evidence
boundary, local loopback sign-in and initial-state test run, and pure
release-binding validation.

Deferred: complete Agent Plugins 1.0 normative profile coverage, platform
native installation/activation, KMS/cosign signing, external publisher trust,
actual CA enrollment/mTLS handshake, production M3 Cloud SQL reader wiring,
hosted Identity Platform session, live model calls, live cartridge execution,
Dataflow, BigQuery, and every cloud/production claim. Those require separate
deployment authority and live evidence; this report does not treat the local
fixtures or adapters as proof of them.
