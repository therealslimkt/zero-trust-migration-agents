#!/usr/bin/env python3
"""Run the sealed, post-approval Keraun cartridge-host provisioning action.

This command accepts digest-pinned images only. ``--apply`` additionally
requires the exact plan digest emitted by the dry-run, preventing a review of
one image set from provisioning another.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_runtime.workflows.cartridge_provisioning import (
    CartridgeHostPlan,
    apply_provisioning,
    bootstrap_digest,
)


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "cartridge_runtime" / "host" / "bootstrap-cartridge-host.sh"


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--run-id", required=True)
    value.add_argument("--jde-image", required=True)
    value.add_argument("--ax-image", required=True)
    value.add_argument("--ebs-image", required=True)
    value.add_argument("--runner-image", required=True)
    value.add_argument("--apply", action="store_true")
    value.add_argument("--approved-plan-digest")
    return value


def main() -> int:
    args = parser().parse_args()
    plan = CartridgeHostPlan(
        run_id=args.run_id,
        jde_image=args.jde_image,
        ax_image=args.ax_image,
        ebs_image=args.ebs_image,
        runner_image=args.runner_image,
        bootstrap_digest=bootstrap_digest(BOOTSTRAP),
    )
    if args.apply:
        if args.approved_plan_digest != plan.plan_digest:
            raise SystemExit("approved plan digest does not bind this image set")
        command_digests = apply_provisioning(plan, bootstrap_script=BOOTSTRAP)
        print(json.dumps({"status": "submitted", "planDigest": plan.plan_digest, "commandDigests": command_digests}, sort_keys=True))
    else:
        print(json.dumps({"status": "dry_run", "planDigest": plan.plan_digest, "bootstrapDigest": plan.bootstrap_digest}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
