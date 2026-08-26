# Milestone 1 Threat Model: Execution, Deployment, and Identity

Scope: the execution sandbox (`sandbox_mcp.py`, `tools/mcp_sandbox.py`), its
Cloud Run deployment (`deploy_sandbox.sh`, `cloudbuild.sandbox.yaml`), the
legacy VM fleet bootstrap (`setup_vms.sh`, `configure_zero_trust.sh`), the
Mission Control WebSocket/HTTP backend (`studio-backend/`), and the approval
policy layer (`ztm_security/approval.py`).

## Prior state (Milestone 0 finding)

The `execution-sandbox` Cloud Run service accepted a `code` string over MCP
and ran it in-process with `exec()`. The service was deployed with
`--allow-unauthenticated`, no Invoker IAM binding, and public ingress, on the
default Compute Engine service account. This combination allowed any
unauthenticated caller on the internet to run arbitrary Python with the
privileges of the default service account. Milestone 0 performed emergency
containment (removed the `allUsers` binding, set ingress to `internal`) but
did not remove the `exec()` code path itself.

## Identity boundaries

| Identity | Scope | Boundary enforced by |
| --- | --- | --- |
| Cloud Run runtime service account (`SANDBOX_SERVICE_ACCOUNT`) | Executes the sandbox container | Must be set explicitly; `deploy_sandbox.sh` fails closed if unset, so the service can never fall back to the default Compute Engine SA. |
| Cloud Run invoker principal (`SANDBOX_INVOKER_MEMBER`) | Allowed to call the sandbox HTTP/MCP endpoint | `deploy_sandbox.sh` fails closed if unset, then replaces the service's IAM policy with a single-member `roles/run.invoker` binding. No `allUsers`/`allAuthenticatedUsers` path exists. |
| Legacy VM service account (`VM_SERVICE_ACCOUNT`) | Runs on each `legacy-*` Compute Engine instance | `setup_vms.sh` fails closed if unset; `configure_zero_trust.sh` additionally verifies the `legacy-db-sa` identity exists before rewiring any VM. |
| VM instance identity (metadata token) | Retrieves the Tailscale auth key at boot | The startup script exchanges the VM's own instance identity token for the secret via the Secret Manager API. The auth key value never appears in Compute Engine metadata, gcloud command history, or the deployment script's environment beyond the VM's own boot-time process. |
| Mission Control browser client | Talks to `studio-backend` over HTTP and WebSocket | Origin is checked against `MISSION_CONTROL_ALLOWED_ORIGINS` (default: localhost dev origins only) for both the `/api/status` CORS path and the `/ws` upgrade. Unlisted or missing origins are denied, not defaulted to allow. |
| Plan approver (`ApprovalRecord.approver`) | Authorizes a specific migration plan to proceed past this milestone's validation gate | Binds approver, plan digest, timestamp, and portfolio run ID together; `authorize_run` denies on any mismatch and denies non-overridable categories unconditionally. |

## Failure modes and how they now fail closed

1. **Sandbox receives executable content.** `validate_pipeline_plan` recurses
   through the submitted JSON and rejects any `code`, `script`, `command`,
   or `expression` key at any depth before computing a digest. There is no
   code path in either MCP module that calls `exec()` or `eval()`; the tools
   that did so have been removed, not merely gated. A regression that
   reintroduces such a call is caught by
   `tests/security/test_no_arbitrary_execution.py`.
2. **Deployment omits an explicit identity or invoker.** `deploy_sandbox.sh`
   checks `SANDBOX_SERVICE_ACCOUNT` and `SANDBOX_INVOKER_MEMBER` before the
   first mutating command (`gcloud builds submit`) runs, and exits non-zero
   if either is missing. No default value silently permits public or
   default-identity deployment.
3. **Secret material leaks through instance metadata.** `setup_vms.sh` only
   ever writes a Secret Manager resource name (`tailscale-secret-name`) to
   instance metadata. If `TAILSCALE_SECRET_NAME` is unset, the script exits
   before creating any VM. If the startup script cannot resolve the secret
   at boot (missing metadata attribute, token exchange failure, or empty
   secret payload), it exits before calling `tailscale up`, so a VM never
   joins the tailnet half-configured.
4. **Zero-trust VM reconfiguration runs against a missing identity.**
   `configure_zero_trust.sh` now verifies `legacy-db-sa` exists via
   `gcloud iam service-accounts describe` before deleting any external IP
   access config or reassigning any VM's service account.
5. **Browser origin spoofing.** `studio-backend` denies any WebSocket
   upgrade or `/api/status` POST whose `Origin` header is absent or not in
   the configured allowlist, rather than reflecting the caller's origin or
   allowing all origins as the prior implementation did.
6. **Approval reuse or scope creep.** `authorize_run` requires the
   `ApprovalRecord.plan_digest` and `portfolio_run_id` to exactly match the
   plan and run being authorized. An approval signed for one plan cannot be
   replayed against a different plan or run. `raw_pii`,
   `arbitrary_execution`, `public_source_database`, and `unapproved_run` are
   checked independently of any approval and can never be authorized around.

## Rollback

- **Sandbox modules:** reverting `sandbox_mcp.py` and `tools/mcp_sandbox.py`
  to a version with an `exec()`-based tool is a regression to the
  Milestone 0 finding and must not happen; `tests/security/test_no_arbitrary_execution.py`
  is designed to fail any such revert.
- **Cloud Run deployment:** if `deploy_sandbox.sh` needs to be rolled back to
  a previous container revision, use `gcloud run services update-traffic`
  to shift traffic to the prior revision rather than redeploying with
  `--allow-unauthenticated`. The IAM policy set by this script should be
  re-applied (or left in place, since it is revision-independent) after any
  rollback so the service never becomes publicly invokable again.
- **VM identity/network changes:** `configure_zero_trust.sh`'s VM mutations
  (stop, set-service-account, start, delete external access config) are
  reversible by re-adding an access config and reassigning the previous
  service account, but the previous state (default Compute Engine SA with a
  public IP) is the Milestone 0 finding and should only be restored as a
  deliberate, reviewed exception, not an automatic rollback path.
- **Origin allowlist:** `MISSION_CONTROL_ALLOWED_ORIGINS` is read at runtime
  from the environment, so widening or narrowing the allowlist is a
  configuration change, not a code rollback.

## Non-overridable denials

`raw_pii`, `arbitrary_execution`, `public_source_database`, and
`unapproved_run` are denied by `ztm_security.approval.check_non_overridable`
independently of any `ApprovalRecord`. No approver, digest, or run binding
can cause `authorize_run` to permit an action tagged with one of these
categories.
