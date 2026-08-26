# Milestone 2 Gate

Status: **passed**

## Outcome

All three legacy migrations now use real binary exports and strict source
adapters over Tailscale MagicDNS. Sensitive decoded values are deterministically
HMAC-tokenized before the already-sanitized candidate is reviewed by
`gemma2:2b` running locally through Ollama on `sparky-sid-411116`.

No raw legacy byte, decoded PII value, or model response is printed, logged, or
persisted by the live verifier. The verifier emits only source identity,
byte/record/finding counts, and SHA-256 evidence digests.

## Provider lanes

| Lane | Provider | Integrated commit | Result |
| --- | --- | --- | --- |
| JDE/AS400 F0101 | Codex | `aea3bb0` | 8 strict-decoder tests passed |
| Accpac/Btrieve ARCUS | Claude Code | `b33165c` | 26 strict/adversarial tests passed; Codex integration review passed |
| SAP MaxDB KNA1 | Gemini/Antigravity | `4ba68b0`, `9afad49` | 10 strict-decoder/generator tests passed after integrator hardening |
| Edge transport and protection | Codex | `0af34cf`, `1f9e553`, `a8c6722` | MagicDNS-only transport, deterministic protection, and edge-local Gemma review |

External providers operated only in isolated worktrees under the approved
repository boundary. Shell access was removed from Claude, and Gemini ran in a
terminal-restricted sandbox. Codex ran tests and Git operations.

Independent review closure:

- Codex reviewed Claude's Btrieve implementation: **PASS**.
- Gemini reviewed Codex's transport, JDE, deterministic protection, and local
  Gemma boundary: **PASS**.
- Claude's first MaxDB review found Unicode-digit acceptance, raw-bearing
  exception causes, and adversarial coverage gaps: **FAIL**. Commit `9afad49`
  corrected those findings; Claude's fresh re-review returned **PASS** with no
  remaining blocker.

## Live evidence

The sanitized evidence record is
[`evidence/m2-live-edge-canary.json`](evidence/m2-live-edge-canary.json).

| Source | MagicDNS host | Bytes | Records | Deterministic findings protected | Gemma residual findings |
| --- | --- | ---: | ---: | ---: | ---: |
| JDE | `legacy-jde-db` | 260 | 4 | 8 | 0 |
| MaxDB | `legacy-maxdb` | 386 | 4 | 12 | 0 |
| Btrieve | `legacy-btrieve-db` | 8,192 | 1 | 2 | 0 |

The MaxDB fixture was uploaded only after the exact target was confirmed absent,
using shell noclobber. Local and remote SHA-256 digests both equal
`6698000415f25413fd88032ae4775ebbdcda7b9b5f4c010e0566fe0a2c49bc45`;
the remote mode is `0600`.

## Verification

Focused integrated gate:

```sh
PYTHONPYCACHEPREFIX=/private/tmp/ztm-m2-pycache python3 -m unittest \
  tests.edge_runtime.test_transport \
  tests.edge_runtime.test_types \
  tests.edge_runtime.test_jde_adapter \
  tests.edge_runtime.test_btrieve_adapter \
  tests.edge_runtime.test_maxdb_adapter \
  tests.security.test_pii_redactor \
  tests.security.test_local_gemma_agent
```

Result: **61 passed**.

Extended contracts, security, and edge gate:

```sh
venv/bin/python -m pytest -q tests/security tests/contracts tests/edge_runtime
```

Result: **121 passed** with one pre-existing third-party Pydantic warning.

Live gate (token key supplied at runtime, never committed):

```sh
python3 -m scripts.verify_live_edge \
  --tailscale-binary /Applications/Tailscale.app/Contents/MacOS/Tailscale
```

Result: **passed for 3/3 sources**.

## Fail-closed properties exercised

- Canonical source ID, MagicDNS hostname, remote path, and format are matched as
  one allowlisted tuple; IP addresses and substituted paths are rejected.
- Partial records, malformed COMP-3, invalid page structures, nonzero Btrieve
  slack space, compression bombs, duplicate/noncanonical JSON, bad CRCs, and
  trailing bytes are rejected without partial output.
- Raw bytes and decoded values are excluded from dataclass reprs and structural
  errors.
- Classified values are tokenized before Gemma; obvious PII mislabeled public
  blocks before model access.
- DERP-relayed Tailscale reachability is accepted without requiring a direct
  NAT path; unreachable hosts still fail closed.
- Gemma verdicts must be exact, internally consistent JSON with allowlisted
  fields/categories. Errors, timeouts, and malformed verdicts block the run.

## Next gate

Milestone 3 must turn these edge artifacts into validated `SourceManifest`,
`RecordBatch`, and `RedactionReport` contracts, feed only those artifacts into
the Gemini planner, persist a real portfolio state machine, and require a
digest-bound human approval before any trusted execution.
