# Security and disclosure boundaries

## Deployment truth boundary

The following are current inventory facts: the named private VMs, the
`execution-sandbox` Cloud Run service, `cloud-run-source-deploy` Artifact
Registry repository, and the enabled Vertex AI, BigQuery, Cloud Run, and
Artifact Registry APIs. They do **not** prove a migration executed.

Identity Platform/Firebase, Dataflow, migration BigQuery datasets, and
Dataflow jobs are currently **planned**. The UI, a judge guide, and a replay
must not label any planned component as live or completed.

## Private-source boundary

The three inventory VMs have private addresses:

| VM | Address |
| --- | --- |
| `legacy-btrieve-db` | `10.128.0.2` |
| `legacy-jde-db` | `10.128.0.3` |
| `legacy-maxdb` | `10.128.0.4` |

The public hosted experience must not expose those addresses as connection
instructions, open them to the internet, or provide a proxy path to their raw
records. A connector lab is local and fixture-based; it is not permission to
reach the private VMs.

## Credential suppression

Never put these values in source, screenshots, demo manifests, frontend
environment variables, or terminal output shared with judges:

- active account email or identity subject;
- OAuth access/refresh tokens, Firebase ID tokens, ADC files, and service
  account keys;
- database passwords, private hostnames beyond the inventory names, or raw
  legacy rows;
- Artifact Registry bearer tokens, signed URLs, Cloud Run invoker tokens, or
  secret-manager payloads.

Use placeholders in written instructions. In a local terminal, prefer a
prompted sign-in or an approved workload identity. Before sharing output, scan
it for `Authorization`, `token`, `secret`, `credential`, and `key` values.

## Browser identity and BFF boundary — planned integration

When Identity Platform/Firebase is configured, the intended browser flow is:

1. Firebase obtains an ID token after a user-initiated sign-in.
2. The browser sends that token only to a same-origin endpoint.
3. The backend-for-frontend verifies the token before creating application
   session state and derives the caller identity server-side.

Until configuration is supplied, sign-in must be disabled rather than
simulated. Browser bundles must not contain cloud credentials or a server-side
service token.

## Public replay boundary

A public route may say **exact synthetic recorded replay** only when the owner
has published the corresponding descriptor and immutable replay bundle. It
must not fall back to a default run ID, random animation, invented timestamp,
or a live-cloud claim. Private source runs and browser-authenticated control
surfaces remain non-public.
