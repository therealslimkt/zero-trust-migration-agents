"""Closed ADK 2 workflow shape for provisioning the synthetic cartridge host.

The model-facing preparation phase may inspect only sanitized cartridge
metadata.  The actual host setup is a deterministic post-approval action: the
executor receives exact image digests and a fixed repository bootstrap script,
never a model-generated command, SQL string, image, or endpoint.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from agent_runtime.adk_compat import load_adk_patterns


class CartridgeProvisioningError(ValueError):
    """A fixed-vocabulary provisioning boundary rejection."""


PROJECT = "ztm-agent-9049c3"
REGION = "us-central1"
ZONE = "us-central1-a"
HOST = "keraun-cartridge-lab"
HOST_SERVICE_ACCOUNT = "keraun-cartridge-host"
NETWORK = "keraun-cartridge-vpc"
SUBNET = "keraun-cartridge-subnet"
ROUTER = "keraun-cartridge-router"
BOOTSTRAP_NAT = "keraun-cartridge-bootstrap-nat"
IAP_FIREWALL = "keraun-cartridge-iap-ssh"
REPOSITORY = "sparky-services"
_DIGEST_IMAGE = re.compile(
    rf"^us-central1-docker\.pkg\.dev/{PROJECT}/{REPOSITORY}/[a-z0-9][a-z0-9._-]{{0,127}}@sha256:[a-f0-9]{{64}}$"
)
_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
_RUN_ID = re.compile(r"^mig_[a-z0-9][a-z0-9_-]{2,80}$")


def _require(condition: bool, code: str) -> None:
    if condition is not True:
        raise CartridgeProvisioningError(code)


@dataclasses.dataclass(frozen=True, slots=True)
class CartridgeHostPlan:
    """Exact approved input to the side-effecting host bootstrap node."""

    run_id: str
    jde_image: str
    ax_image: str
    ebs_image: str
    runner_image: str
    bootstrap_digest: str

    def __post_init__(self) -> None:
        _require(_RUN_ID.fullmatch(self.run_id) is not None, "cartridge_run")
        for image in (self.jde_image, self.ax_image, self.ebs_image, self.runner_image):
            _require(_DIGEST_IMAGE.fullmatch(image) is not None, "cartridge_image")
        _require(_DIGEST.fullmatch(self.bootstrap_digest) is not None, "bootstrap_digest")

    @property
    def plan_digest(self) -> str:
        material = "\n".join(
            (
                "keraun.cartridge-host-plan/v1",
                self.run_id,
                self.jde_image,
                self.ax_image,
                self.ebs_image,
                self.runner_image,
                self.bootstrap_digest,
            )
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(material).hexdigest()


def bootstrap_digest(path: Path) -> str:
    """Read the only script that the executor will ever place on a new host."""

    try:
        resolved = path.resolve(strict=True)
        payload = resolved.read_bytes()
    except OSError as exc:
        raise CartridgeProvisioningError("bootstrap_unavailable") from exc
    _require(resolved.name == "bootstrap-cartridge-host.sh", "bootstrap_path")
    _require(0 < len(payload) <= 64 << 10, "bootstrap_size")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


@dataclasses.dataclass(frozen=True, slots=True)
class AdkCartridgeProvisioningNodes:
    """Caller-owned nodes; this factory grants no cloud authority itself."""

    validate_plan: object
    inspect_seed_manifests: object
    inspect_image_digests: object
    inspect_host_policy: object
    request_approval: object
    provision_host: object
    verify_host: object
    fail_closed: object


def build_cartridge_provisioning_workflow(nodes: AdkCartridgeProvisioningNodes) -> object:
    """Build the bounded ADK 2.7.1 map/join/approval/action workflow.

    The three read-only preparation branches fan in before the approval node.
    ``provision_host`` is intentionally after approval and must be a sealed
    executor adapter, not a model tool.
    """

    adk = load_adk_patterns()
    validate = adk.node(nodes.validate_plan, name="validate_cartridge_host_plan")
    seeds = adk.node(nodes.inspect_seed_manifests, name="inspect_seed_manifests")
    images = adk.node(nodes.inspect_image_digests, name="inspect_image_digests")
    policy = adk.node(nodes.inspect_host_policy, name="inspect_host_policy")
    joined = adk.JoinNode(name="cartridge_host_preflight_join")
    approval = adk.node(nodes.request_approval, name="cartridge_host_approval", rerun_on_resume=True)
    provision = adk.node(nodes.provision_host, name="provision_cartridge_host")
    verify = adk.node(nodes.verify_host, name="verify_cartridge_host")
    failed = adk.node(nodes.fail_closed, name="cartridge_host_fail_closed")
    return adk.Workflow(
        name="cartridge_host_provisioning",
        max_concurrency=3,
        edges=[
            (adk.START, validate, (seeds, images, policy), joined, approval),
            (approval, {"approved": provision, adk.DEFAULT_ROUTE: failed}),
            (provision, {"verified": verify, adk.DEFAULT_ROUTE: failed}),
        ],
    )


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def provision_commands(plan: CartridgeHostPlan, *, bootstrap_script: Path) -> tuple[tuple[str, ...], ...]:
    """Return the sole allowlisted Cloud CLI commands for an approved plan."""

    _require(bootstrap_digest(bootstrap_script) == plan.bootstrap_digest, "bootstrap_changed")
    service_account = f"{HOST_SERVICE_ACCOUNT}@{PROJECT}.iam.gserviceaccount.com"
    metadata = (
        f"keraun-jde-image={plan.jde_image},"
        f"keraun-ax-image={plan.ax_image},"
        f"keraun-ebs-image={plan.ebs_image},"
        f"keraun-runner-image={plan.runner_image},"
        f"keraun-plan-digest={plan.plan_digest}"
    )
    return (
        ("gcloud", "iam", "service-accounts", "create", HOST_SERVICE_ACCOUNT, "--project", PROJECT, "--display-name", "Keraun private cartridge host"),
        ("gcloud", "artifacts", "repositories", "add-iam-policy-binding", REPOSITORY, "--project", PROJECT, "--location", REGION, "--member", f"serviceAccount:{service_account}", "--role", "roles/artifactregistry.reader"),
        ("gcloud", "compute", "networks", "create", NETWORK, "--project", PROJECT, "--subnet-mode", "custom"),
        ("gcloud", "compute", "networks", "subnets", "create", SUBNET, "--project", PROJECT, "--region", REGION, "--network", NETWORK, "--range", "10.119.104.0/28", "--enable-private-ip-google-access"),
        ("gcloud", "compute", "routers", "create", ROUTER, "--project", PROJECT, "--region", REGION, "--network", NETWORK),
        ("gcloud", "compute", "routers", "nats", "create", BOOTSTRAP_NAT, "--project", PROJECT, "--region", REGION, "--router", ROUTER, "--nat-all-subnet-ip-ranges"),
        ("gcloud", "compute", "firewall-rules", "create", IAP_FIREWALL, "--project", PROJECT, "--network", NETWORK, "--direction", "INGRESS", "--priority", "1000", "--action", "ALLOW", "--rules", "tcp:22", "--source-ranges", "35.235.240.0/20", "--target-service-accounts", service_account),
        ("gcloud", "compute", "instances", "create", HOST, "--project", PROJECT, "--zone", ZONE, "--machine-type", "e2-small", "--boot-disk-size", "20GB", "--boot-disk-type", "pd-balanced", "--image-family", "ubuntu-2404-lts-amd64", "--image-project", "ubuntu-os-cloud", "--subnet", SUBNET, "--no-address", "--service-account", service_account, "--scopes", "cloud-platform", "--metadata", metadata, "--metadata-from-file", f"startup-script={bootstrap_script}", "--labels", "app=keraun-cartridge-lab,environment=hackathon,synthetic=true"),
    )


def apply_provisioning(
    plan: CartridgeHostPlan,
    *,
    bootstrap_script: Path,
    runner: CommandRunner = subprocess.run,
) -> tuple[str, ...]:
    """Execute only the sealed command set after a caller validates approval."""

    command_digests: list[str] = []
    for command in provision_commands(plan, bootstrap_script=bootstrap_script):
        result = runner(command, check=False, text=True, capture_output=True)
        if result.returncode != 0:
            raise CartridgeProvisioningError("provisioning_command_failed")
        command_digests.append("sha256:" + hashlib.sha256("\0".join(command).encode()).hexdigest())
    return tuple(command_digests)
