from __future__ import annotations

import hashlib
import subprocess

import pytest

from agent_runtime.workflows.cartridge_provisioning import (
    BOOTSTRAP_NAT,
    HOST,
    IAP_FIREWALL,
    NETWORK,
    PROJECT,
    SUBNET,
    CartridgeHostPlan,
    CartridgeProvisioningError,
    apply_provisioning,
    bootstrap_digest,
    provision_commands,
)


def _image(name: str, character: str) -> str:
    return f"us-central1-docker.pkg.dev/{PROJECT}/sparky-services/{name}@sha256:" + character * 64


def _bootstrap(tmp_path):
    path = tmp_path / "bootstrap-cartridge-host.sh"
    path.write_text("#!/bin/sh\necho sealed\n", encoding="utf-8")
    return path


def _plan(tmp_path):
    bootstrap = _bootstrap(tmp_path)
    return (
        CartridgeHostPlan(
            run_id="mig_cartridge_lab_001",
            jde_image=_image("jde-e1-ibmi", "a"),
            ax_image=_image("dynamics-ax", "b"),
            ebs_image=_image("oracle-ebs-19c", "c"),
            runner_image=_image("cartridge-evidence-runner", "d"),
            bootstrap_digest=bootstrap_digest(bootstrap),
        ),
        bootstrap,
    )


def test_plan_requires_digest_pinned_project_images(tmp_path):
    bootstrap = _bootstrap(tmp_path)
    with pytest.raises(CartridgeProvisioningError, match="^cartridge_image$"):
        CartridgeHostPlan(
            run_id="mig_cartridge_lab_001",
            jde_image="postgres:16",
            ax_image=_image("dynamics-ax", "b"),
            ebs_image=_image("oracle-ebs-19c", "c"),
            runner_image=_image("cartridge-evidence-runner", "d"),
            bootstrap_digest=bootstrap_digest(bootstrap),
        )


def test_commands_are_closed_to_one_private_host_topology(tmp_path):
    plan, bootstrap = _plan(tmp_path)
    commands = provision_commands(plan, bootstrap_script=bootstrap)
    flattened = "\n".join(" ".join(command) for command in commands)

    assert len(commands) == 8
    assert f"networks create {NETWORK}" in flattened
    assert f"subnets create {SUBNET}" in flattened
    assert f"nats create {BOOTSTRAP_NAT}" in flattened
    assert f"firewall-rules create {IAP_FIREWALL}" in flattened
    assert f"instances create {HOST}" in flattened
    assert "--no-address" in flattened
    assert "--source-ranges 35.235.240.0/20" in flattened
    assert "--metadata-from-file" in flattened
    assert "--network-interface" not in flattened
    assert "docker.sock" not in flattened
    assert "http://" not in flattened


def test_changed_bootstrap_cannot_reuse_an_approved_plan(tmp_path):
    plan, bootstrap = _plan(tmp_path)
    bootstrap.write_text("#!/bin/sh\necho changed\n", encoding="utf-8")
    with pytest.raises(CartridgeProvisioningError, match="^bootstrap_changed$"):
        provision_commands(plan, bootstrap_script=bootstrap)


def test_apply_stops_at_first_provider_failure(tmp_path):
    plan, bootstrap = _plan(tmp_path)
    calls = []

    def runner(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, "", "provider details")

    with pytest.raises(CartridgeProvisioningError, match="^provisioning_command_failed$"):
        apply_provisioning(plan, bootstrap_script=bootstrap, runner=runner)
    assert len(calls) == 1


def test_apply_returns_only_command_digests(tmp_path):
    plan, bootstrap = _plan(tmp_path)

    def runner(command, **_kwargs):
        return subprocess.CompletedProcess(command, 0, "provider details", "")

    output = apply_provisioning(plan, bootstrap_script=bootstrap, runner=runner)
    assert len(output) == 8
    assert all(value.startswith("sha256:") and len(value) == 71 for value in output)
    expected = "sha256:" + hashlib.sha256("\0".join(provision_commands(plan, bootstrap_script=bootstrap)[0]).encode()).hexdigest()
    assert output[0] == expected
