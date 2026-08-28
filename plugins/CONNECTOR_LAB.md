# Optional local source connector lab

This lab is a local, fixture-based verification of the source adapter code. It
is intended for an optional judge walkthrough after the hosted replay. It does
not connect to the deployed private VMs, does not use Tailscale, and does not
create Google Cloud resources.

## Install the test environment

From the repository root:

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt -r requirements-dev.txt
```

Do not place database passwords, cloud credentials, or a private fixture dump
in the virtual environment or repository.

## Run the three connector checks

```bash
venv/bin/python -m pytest \
  tests/edge_runtime/test_jde_adapter.py \
  tests/edge_runtime/test_maxdb_adapter.py \
  tests/edge_runtime/test_btrieve_adapter.py
```

Expected outcome: the tests exercise deterministic repository fixtures and
their rejection paths. A passing test is evidence for the local adapter’s
checked fixture format only; it is not evidence of a live database connection,
a production migration, a Dataflow job, or a BigQuery write.

## Optional inspection

Read the adapter implementations without executing a connector:

```bash
sed -n '1,220p' edge_runtime/adapters/jde.py
sed -n '1,220p' edge_runtime/adapters/maxdb.py
sed -n '1,260p' edge_runtime/adapters/btrieve.py
```

The YAML files under this directory are metadata. Do not run them with a
plugin CLI and do not infer that they provide installation, authentication, or
network configuration.
