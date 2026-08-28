# Source connector lab metadata

The `plugin.yaml` files in this directory are **descriptive presets only**.
They are not Codex plugins, OpenAI plugin manifests, package-manager recipes,
or executable connector installers. Nothing in this directory grants network
access, connects to a database, downloads a JDBC driver, or bypasses a vendor
application layer.

For the runnable, fixture-based lab, read
[CONNECTOR_LAB.md](CONNECTOR_LAB.md). It exercises the repository’s strict
local Python adapters and tests; it does not require Google Cloud, Tailscale,
or access to the private source VMs.

| Metadata preset | Runnable lab coverage | Truthful scope |
| --- | --- | --- |
| `jde-as400-migration` | `tests/edge_runtime/test_jde_adapter.py` | Deterministic fixture decoder for the repository’s JDE payload format. |
| `sap-maxdb-migration` | `tests/edge_runtime/test_maxdb_adapter.py` | Deterministic fixture decoder for the repository’s MaxDB payload format. |
| `accpac-btrieve-migration` | `tests/edge_runtime/test_btrieve_adapter.py` | Deterministic fixture decoder for the repository’s Btrieve payload format. |
| `live-system-researcher` | None | Product concept metadata only; no runnable agent or research connector is supplied here. |

The manifests are retained as design metadata. A future executable connector
must declare its runtime, permissions, input contract, secret handling,
network boundary, tests, and installation path before it can be called a
plugin.
