# Evidence: three legacy cartridges detect their signature defect

Captured (UTC): `2026-08-31T21:43:35Z` · project `ztm-agent-9049c3` · synthetic/deidentified fixtures

Three sealed synthetic source emulators run on an **internal-only Docker network** with no
egress. A separate evidence runner is the only container permitted to query them, and it
emits **count-only sanitized results** — never raw records, credentials, or connection
strings.

| Cartridge | Source emulated | Signature defect detected | Count |
| --- | --- | --- | --- |
| JDE | Oracle JD Edwards EnterpriseOne 9.2 / IBM i | invalid `CYYDDD` Julian date | 1 |
| AX | Microsoft Dynamics AX 2012 R3 / SQL Server | orphan-derived `RecId` (broken table inheritance) | 2 |
| EBS | Oracle E-Business Suite / Oracle 19c | unmapped descriptive flexfield | 1 |

## Verbatim runner output

```json
{"schemaVersion":"keraun.cartridge-evidence/v1","synthetic":true,"checks":{"jdeInvalidCyyddd":1,"axOrphanDerived":2,"ebsUnmappedFlexfield":1}}
```

## Reproduce

```bash
./scripts/run_local_cartridge_evidence.sh
```

Production runs the same contract under **gVisor (runsc)** on the private Compute Engine host
`keraun-cartridge-lab` (no external IP). The local pass uses Docker Desktop's runc override
purely so the evidence is reproducible on a laptop.

`synthetic: true` is asserted in the payload itself — these are deidentified emulators, not
licensed production JDE, Dynamics, or Oracle EBS databases.
