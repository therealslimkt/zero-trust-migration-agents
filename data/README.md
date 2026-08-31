# Keraun source-emulator cartridges

Each source family has a self-contained folder with a semantic `seed.yaml`, a
source-shaped SQL initialization file, a container recipe, and a one-command
local start script:

| Folder | Command | Demonstrates |
| --- | --- | --- |
| `jde_e1_ibmi/` | `./data/jde_e1_ibmi/start.sh` | `UPMJ` CYYDDD dates and ordered `UPMT` CDC. |
| `dynamics_ax_2012_r3/` | `./data/dynamics_ax_2012_r3/start.sh` | `RecId` base/derived inheritance in a company/partition scope. |
| `oracle_ebs_19c/` | `./data/oracle_ebs_19c/start.sh` | Context-sensitive DFF mapping for `ATTRIBUTE1…ATTRIBUTE15`. |

These are project-owned, synthetic PostgreSQL emulators. They deliberately
resemble the relevant metadata and data boundaries but are **not** licensed
JDE, IBM i/Db2, Microsoft Dynamics/SQL Server, Oracle EBS, or Oracle Database
products. The required enterprise JDBC JAR name is recorded in each seed file;
no proprietary driver is bundled, downloaded, or redistributed.

The private live host is built from these images by the bounded cartridge
provisioner. Its source databases have no host-published ports; the only
cross-container reader is the gVisor `runsc` evidence runner. Never mount
`/var/run/docker.sock` in a cartridge or runner container.

## Full local evidence pass

With Docker Desktop running, execute this one command from the repository root:

```bash
./scripts/run_local_cartridge_evidence.sh
```

It builds only the project-owned synthetic images, starts an isolated temporary
Compose project, prints the sanitized three-cartridge evidence JSON, and then
removes that temporary project's containers, network, and volumes. It uses the
explicit `compose.local.yaml` `runc` override because Docker Desktop does not
provide the production VM's `runsc` gVisor runtime.
