# M7 live cartridge runtime

M7 turns the first three M4 fixture families into a live, private
demonstration environment. The output is intentionally a **synthetic source
emulator**, not an assertion that Keraun runs a licensed vendor application or
has connected to customer data.

## Runtime chain

```text
ADK 2 preflight map/join → approval interrupt → sealed host provisioner
    → private VM source-emulator images → gVisor evidence runner
    → sanitized check result → Mission Control evidence / later Flex launch
```

The ADK graph has three read-only preflight branches—seed manifest, image
digest, and host-policy inspection—which join before the approval node. After
approval, the provisioner accepts only the four digest-pinned Artifact Registry
image references and the SHA-256 of `bootstrap-cartridge-host.sh`. It has no
tool for arbitrary commands, images, SQL, paths, endpoints, Docker sockets, or
customer credentials.

## Source emulators

| Family | Metadata and source shape | Failure made observable |
| --- | --- | --- |
| `jde_e1_ibmi` | `F9860`, `F98711`, `F0911`, `UPMJ`/`UPMT`, ordered delta | Invalid CYYDDD ordinal must be rejected before a calendar conversion. |
| `dynamics_ax_2012_r3` | `SQLDICTIONARY`, `MODELELEMENT`, `DirPartyTable`, `CustTable`, scoped `RecId` | Orphan and cross-partition derived rows must not flatten. |
| `oracle_ebs_19c` | `FND_TABLES`, `FND_COLUMNS`, `FND_DESCRIPTIVE_FLEXS`, `HZ_PARTIES` | A generic `ATTRIBUTE1` value must not be named until context metadata resolves it. |

Each folder in `data/` carries the semantic source seed, source-like DDL,
container recipe, and one-line launcher. Driver requirements are recorded as
deployment metadata only: `jt400.jar`/`db2jcc4.jar`, `mssql-jdbc.jar`, and
`ojdbc8.jar`. Keraun does not ship or download proprietary drivers.

## Isolation and network boundary

- The source host is an `e2-small` private-only Compute Engine VM in a dedicated
  VPC and `/28` subnet; it has no external IP and only IAP TCP/22 ingress.
- A short-lived Cloud NAT bootstrap path lets the host install Docker and the
  signed `runsc` package; it is retired after startup verification.
- Source database containers have no host-published ports and communicate only
  on an internal Docker network.
- The `evidence-runner` is the only parser/certifier process. It uses
  `runtime: runsc` (gVisor), an unprivileged UID, read-only root, no Linux
  capabilities, `no-new-privileges`, an explicit small tmpfs, 256 MiB memory,
  half a CPU, and a 64-process ceiling. It has no Docker socket or bind mounts.
- The runner reads only through the `cartridge_reader` role, emits counts of
  seeded failure cases, and never emits raw fixture rows.

The first source emulators are PostgreSQL compatibility representations because
redistributing vendor database engines is out of scope. The later approved
customer connector supplies a version- and checksum-verified JDBC dependency,
and the Flex Template contains the fixed Beam transform. The template and its
Artifact Registry image must be separately digest-bound before Dataflow launch.

## Operations

1. Cloud Build creates the four project-owned images from
   `cloudbuild.cartridges.yaml`.
2. The resulting image digests form `CartridgeHostPlan`.
3. `scripts/provision_cartridge_lab.py` produces a dry-run digest. An approval
   must bind that exact digest before `--apply` can submit the sealed commands.
4. The VM startup script verifies image-reference format, installs gVisor,
   launches source emulators, then runs the gVisor evidence check once.
5. Operators retrieve only `/var/log/keraun-cartridge-evidence.json` via IAP;
   no database endpoint is published.

Every cloud mutation is reflected in `cloud_architecture/CLOUD_RESOURCE_MANIFEST.md`
before the M7 delivery report is written.
