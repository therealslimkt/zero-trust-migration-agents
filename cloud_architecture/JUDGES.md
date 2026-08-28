# Judge setup: hosted replay first, connector lab optional

## Primary path: exact hosted replay

The primary judge experience is an owner-published hosted route for an **exact
synthetic recorded replay**. The submission owner supplies the URL and replay
descriptor at release time; this repository deliberately does not embed a URL,
default demo ID, or claim that a replay is currently hosted.

Judge steps when that URL is supplied:

1. Open the supplied URL in a clean browser profile.
2. Confirm the page identifies the replay as exact, synthetic, and recorded.
3. Verify the displayed run, approval, plan, and evidence values are sourced
   from the published descriptor/bundle, not generated after page load.
4. Use the architecture links to distinguish the replay from planned cloud
   services. A replay is not proof of an enabled Dataflow job or migration
   BigQuery dataset.

The public path must not require a Tailscale connection, a private VM address,
a credential, a Firebase account, a cloud project, or an artifact upload.

## Optional path: local source connector lab

For a code-level walkthrough, judges may run the fixture-based connector lab in
[plugins/CONNECTOR_LAB.md](../plugins/CONNECTOR_LAB.md). It is optional and
does not contact the private VMs or Google Cloud. It validates deterministic
local adapters against repository test fixtures.

## What judges should not do

- Do not enable APIs, create datasets, deploy Cloud Run, or launch Dataflow.
- Do not authenticate to the project or request access to the private VM
  network.
- Do not upload a vendor driver or interpret `plugins/*/plugin.yaml` as an
  executable plugin installer.
- Do not treat a planned label as a failed hosted-demo setup; it is deliberate
  disclosure of current scope.
