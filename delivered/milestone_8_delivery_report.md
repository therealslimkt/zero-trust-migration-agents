# Milestone 8 Delivery Report — Plugin Factory Checkpoint

Status: **complete for the local, sealed candidate-verification slice**  
Date: 2026-08-31  
Branch: `agent/m8/hosted-runner-platform`

## What changed

### 1. A real local verification action is available from the factory UI

`./scripts/start_local_cartridge_ui.sh` starts two loopback-only processes:

- the Vite UI, and
- `scripts/local_cartridge_agent.py` on `127.0.0.1:4344`.

The browser can only request one fixed operation: the three-cartridge synthetic
evidence run. It cannot submit a shell command, image reference, source path,
credential, or cloud endpoint. Vite injects a generated per-launch token into
the loopback proxy; the token is never exposed to browser JavaScript.

Example successful result:

```json
{
  "schemaVersion": "keraun.cartridge-evidence/v1",
  "synthetic": true,
  "checks": {
    "jdeInvalidCyyddd": 1,
    "axOrphanDerived": 2,
    "ebsUnmappedFlexfield": 1
  }
}
```

This proves only the deterministic synthetic guardrails. It does **not** claim
that an Apache Beam job, Dataflow, BigQuery, customer source, or production
plugin ran.

### 2. The front end now presents a Plugin Factory, not a “lab”

The public route is now `/factory`; the prior `/lab/m4` address redirects to
it. The view calls JDE, Dynamics AX, and Oracle EBS **preloaded demonstration
cartridges** and labels the local action as a sealed sandbox preflight.

The page makes the lifecycle visible:

1. discover an existing cartridge or research a new one;
2. verify its source contract;
3. review the sealed run in Mission Control; and
4. download a portable plugin only after its formal package is verified.

It also states the boundary directly: a preflight pass creates a candidate for
Mission Control; it is not migration execution evidence.

### 3. The product and architecture have a durable north-star handoff

[`docs/hackathon/PLUGIN_FACTORY_NORTH_STAR_HANDOFF.md`](../docs/hackathon/PLUGIN_FACTORY_NORTH_STAR_HANDOFF.md)
now records the canonical product flow, ADK 2 patterns, four memory categories,
terminal-lane contract, A2A/Agent Plugins packaging requirements, current
proof, non-claims, and next execution sequence.

Examples of the explicit design choices:

- a `single_turn` collaborative ADK 2 team discovers a vetted Agent Plugin or
  returns `research_required`;
- bounded dynamic research uses a fixed width/depth and approved source
  boundary;
- a graph workflow performs deterministic metadata/policy/template checks in
  parallel, joins them, then permits one compiler agent to emit only a typed
  declarative contract;
- Mission Control must show source VM, compiler/Beam, and BigQuery lanes from
  persisted backend events only, with no generated terminal progress.

### 4. Local operator instructions are pre-vetted and aligned with the UI

`studio/README.md` now describes `/factory`, its non-claims, and the redirect
from the legacy URL. The Vite configuration comments match the same boundary.
This removes the earlier mismatch between the application wording and the
actual safe local run behavior.

## Verification performed

```text
cd studio
npm run test -- --run src/web/pages/lab/M4FixtureLabPage.test.tsx  # 3 passed
npm run build                                                       # passed
npm run lint                                                        # passed
```

The sealed local runner was also exercised through its Vite loopback proxy and
returned only the count-only evidence structure above.

## Cloud status and deliberate non-claims

No new cloud resource was created in this checkpoint; therefore
`cloud_architecture/CLOUD_RESOURCE_MANIFEST.md` has no M8 mutation to record.
Firebase is active for the project, but a hosted Cloud Run deployment, live
runner-agent event stream, Dataflow job, BigQuery migration write, and
downloadable migration Agent Plugin are still outstanding submission gates.

## Next required proof

1. Persist a selected preloaded cartridge in the authenticated Mission Control
   flow and stream the three sanitized backend lanes.
2. Run one real JDE Beam Flex Template path into BigQuery after digest-bound
   approval, then capture the Dataflow job ID, BigQuery job/table and
   reconciliation evidence.
3. Build and verify a portable Agent Plugins 1.0 package with the appropriate
   A2A Agent Card, instead of the present inert reference profile.
