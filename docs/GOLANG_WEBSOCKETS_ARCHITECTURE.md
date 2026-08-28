# Superseded decision: WebSocket browser transport

> **Status: superseded.** This filename remains so existing links continue to
> resolve. It does not describe the active Mission Control browser transport.

The previous proposal used Gorilla WebSocket with a `/ws` endpoint and a
legacy `/api/status` broadcaster. Those routes are explicitly **not mounted**
by the current server mux and return `404`; they are not part of the supported
browser API.

The active architecture is documented in
[GOLANG_MISSION_CONTROL_ARCHITECTURE.md](GOLANG_MISSION_CONTROL_ARCHITECTURE.md):

- REST resources are served from `/api/v1/` and the authenticated browser BFF
  at `/api/web/v1/`.
- Browser run events use bounded Server-Sent Events at
  `/api/web/v1/runs/{run_id}/events` with validated `Last-Event-ID` resume.
- Durable snapshots and persisted events are the source of dashboard state;
  the browser does not infer missing events or maintain a broadcast socket.

Legacy Gorilla WebSocket helper code/dependency may still be present in source,
but it has no mounted route and is not an active delivery contract. Its removal
is a separate cleanup task, not a reason to revive `/ws` or `/api/status`.
