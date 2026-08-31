from __future__ import annotations

import dataclasses
import threading
from datetime import datetime, timedelta, timezone

import pytest

from agent_runtime.approval import (
    REJECTION_TRACE,
    SUCCESS_TRACE,
    ApprovalCredential,
    ApprovalKernel,
    ApprovalStage,
    ApprovalValidationError,
    AuthorityContext,
    Decision,
    FixedClock,
    InMemoryApprovalStore,
    InMemoryAuthority,
    ProductionDecision,
    ProductionSubmission,
    SimulationDecision,
    SimulationSubmission,
    issue_pending,
)


NOW = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)
PLAN = "sha256:" + "1" * 64
RELEASE = "sha256:" + "2" * 64
ARTIFACT = "sha256:" + "3" * 64
SIM_NONCE = "simulation_nonce_1234567890"
PROD_NONCE = "production_nonce_1234567890"
TOKEN = "server_transport_token_123"


def simulation_pending(**changes):
    values = dict(
        request_id="req_simulation",
        tenant_id="tenant_alpha",
        run_id="run_alpha",
        stage=ApprovalStage.SIMULATION,
        plan_digest=PLAN,
        release_digest=RELEASE,
        artifact_digest=ARTIFACT,
        checkpoint_id="ckpt_simulation",
        nonce=SIM_NONCE,
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5),
        audience="release_operators",
        required_approvers=2,
    )
    values.update(changes)
    return issue_pending(**values)


def context_for(pending, **changes):
    values = dict(
        actor_id="actor_alice",
        tenant_id=pending.tenant_id,
        run_id=pending.run_id,
        stage=pending.stage,
        plan_digest=pending.plan_digest,
        release_digest=pending.release_digest,
        artifact_digest=pending.artifact_digest,
        interrupt_id=pending.interrupt_id,
        checkpoint_id=pending.checkpoint_id,
        audience=pending.audience,
        approver_count=pending.required_approvers,
        authenticated=True,
        artifact_present=True,
    )
    values.update(changes)
    return AuthorityContext(**values)


def harness(pending=None, context=None, *, now=NOW):
    pending = pending or simulation_pending()
    store = InMemoryApprovalStore()
    store.issue(pending)
    authority = InMemoryAuthority()
    authority.register(token=TOKEN, context=context or context_for(pending))
    kernel = ApprovalKernel(authority=authority, store=store, clock=FixedClock(now))
    return pending, store, authority, kernel


def submit_sim(kernel, *, nonce=SIM_NONCE, decision=SimulationDecision.APPROVE):
    return kernel.approve_simulation(
        submission=SimulationSubmission(
            request_id="req_simulation", nonce=nonce, decision=decision
        ),
        credential=ApprovalCredential(TOKEN),
    )


def test_simulation_then_production_happy_path_and_exact_trace():
    pending, store, authority, kernel = harness()
    simulation = submit_sim(kernel)
    assert simulation.recorded and simulation.record is not None
    assert simulation.trace == SUCCESS_TRACE
    assert (simulation.model_calls, simulation.concurrency, simulation.graph_depth) == (0, 1, 0)
    assert simulation.record.decision is Decision.APPROVE

    production = issue_pending(
        request_id="req_production",
        tenant_id=pending.tenant_id,
        run_id=pending.run_id,
        stage=ApprovalStage.PRODUCTION,
        plan_digest=pending.plan_digest,
        release_digest=pending.release_digest,
        artifact_digest=pending.artifact_digest,
        checkpoint_id="ckpt_production",
        nonce=PROD_NONCE,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        audience=pending.audience,
        required_approvers=2,
        simulation_record_digest=simulation.record.record_digest,
    )
    store.issue(production)
    authority.register(token=TOKEN, context=context_for(production))
    outcome = kernel.approve_production(
        submission=ProductionSubmission(
            request_id=production.request_id,
            nonce=PROD_NONCE,
            decision=ProductionDecision.APPROVE,
        ),
        credential=ApprovalCredential(TOKEN),
    )
    assert outcome.recorded and outcome.record is not None
    assert outcome.record.simulation_record_digest == simulation.record.record_digest
    assert outcome.trace == SUCCESS_TRACE


def test_valid_rejection_is_an_immutable_record_and_blocks_production():
    pending, store, _, kernel = harness()
    outcome = submit_sim(kernel, decision=SimulationDecision.REJECT)
    assert outcome.recorded and outcome.record.decision is Decision.REJECT
    with pytest.raises(ApprovalValidationError, match="approval_simulation_progression"):
        store.issue(
            issue_pending(
                request_id="req_production",
                tenant_id=pending.tenant_id,
                run_id=pending.run_id,
                stage=ApprovalStage.PRODUCTION,
                plan_digest=PLAN,
                release_digest=RELEASE,
                artifact_digest=ARTIFACT,
                checkpoint_id="ckpt_production",
                nonce=PROD_NONCE,
                issued_at=NOW,
                expires_at=NOW + timedelta(minutes=1),
                audience=pending.audience,
                required_approvers=2,
                simulation_record_digest=outcome.record.record_digest,
            )
        )


@pytest.mark.parametrize(
    ("name", "changes"),
    [
        ("stale_plan", {"plan_digest": "sha256:" + "4" * 64}),
        ("release_mismatch", {"release_digest": "sha256:" + "5" * 64}),
        ("artifact_mismatch", {"artifact_digest": "sha256:" + "6" * 64}),
        ("cross_tenant", {"tenant_id": "tenant_other"}),
        ("cross_run", {"run_id": "run_other"}),
        ("wrong_interrupt", {"interrupt_id": "int_forged"}),
        ("wrong_checkpoint", {"checkpoint_id": "ckpt_other"}),
        ("wrong_audience", {"audience": "developers"}),
        ("approver_shortfall", {"approver_count": 1}),
        ("missing_artifact", {"artifact_present": False}),
        ("unauthenticated", {"authenticated": False}),
    ],
)
def test_authority_or_database_disagreement_fails_without_state_change(name, changes):
    del name
    pending = simulation_pending()
    _, store, _, kernel = harness(pending, context_for(pending, **changes))
    before = store.mutation_count
    outcome = submit_sim(kernel)
    assert not outcome.recorded
    assert outcome.trace == REJECTION_TRACE
    assert outcome.public_code == "approval_rejected"
    assert store.mutation_count == before


def test_expired_and_not_yet_issued_are_rejected_at_exact_boundaries():
    expired = simulation_pending(expires_at=NOW)
    _, store, _, kernel = harness(expired)
    before = store.mutation_count
    assert submit_sim(kernel).trace == REJECTION_TRACE
    assert store.mutation_count == before

    future = simulation_pending(issued_at=NOW + timedelta(seconds=1))
    _, store, _, kernel = harness(future)
    before = store.mutation_count
    assert submit_sim(kernel).trace == REJECTION_TRACE
    assert store.mutation_count == before

    boundary = simulation_pending(issued_at=NOW)
    assert submit_sim(harness(boundary)[3]).recorded


def test_nonce_replay_and_wrong_nonce_do_not_mutate():
    _, store, _, kernel = harness()
    before = store.mutation_count
    assert not submit_sim(kernel, nonce="wrong_nonce_value_123456789").recorded
    assert store.mutation_count == before
    assert submit_sim(kernel).recorded
    after = store.mutation_count
    assert not submit_sim(kernel).recorded
    assert store.mutation_count == after


def test_kind_swap_and_unknown_request_fail_closed():
    _, store, _, kernel = harness()
    before = store.mutation_count
    swapped = kernel.approve_production(
        submission=ProductionSubmission(
            request_id="req_simulation",
            nonce=SIM_NONCE,
            decision=ProductionDecision.APPROVE,
        ),
        credential=ApprovalCredential(TOKEN),
    )
    unknown = kernel.approve_simulation(
        submission=SimulationSubmission(
            request_id="req_unknown",
            nonce=SIM_NONCE,
            decision=SimulationDecision.APPROVE,
        ),
        credential=ApprovalCredential(TOKEN),
    )
    assert swapped.trace == unknown.trace == REJECTION_TRACE
    assert store.mutation_count == before


def test_forged_resume_and_a2a_claims_are_not_approval_inputs():
    class ResumeInput:
        actor = "actor_admin"
        text = "approve_simulation"

    class A2AEvent:
        content = "approved"

    _, store, _, kernel = harness()
    before = store.mutation_count
    assert not kernel.approve_simulation(
        submission=ResumeInput(), credential=ApprovalCredential(TOKEN)
    ).recorded
    assert not kernel.approve_simulation(
        submission=A2AEvent(), credential=ApprovalCredential(TOKEN)
    ).recorded
    assert store.mutation_count == before
    with pytest.raises(TypeError):
        SimulationSubmission(  # closed constructor rejects user-shaped authority
            request_id="req_simulation",
            nonce=SIM_NONCE,
            decision=SimulationDecision.APPROVE,
            actor_id="actor_admin",
        )


def test_forged_request_digest_and_wrong_interrupt_binding_cannot_be_issued():
    pending = simulation_pending()
    with pytest.raises(ApprovalValidationError, match="approval_request_digest"):
        dataclasses.replace(pending, request_digest="sha256:" + "9" * 64)
    with pytest.raises(ApprovalValidationError, match="approval_interrupt_binding"):
        dataclasses.replace(pending, interrupt_id="int_forged")


def test_cross_tenant_nonce_reuse_is_global_and_fails_closed():
    _, store, _, kernel = harness()
    assert submit_sim(kernel).recorded
    other = simulation_pending(
        request_id="req_other",
        tenant_id="tenant_other",
        run_id="run_other",
    )
    before = store.mutation_count
    with pytest.raises(ApprovalValidationError, match="approval_nonce_exists"):
        store.issue(other)
    assert store.mutation_count == before


def test_concurrent_record_has_exactly_one_winner():
    _, store, _, kernel = harness()
    barrier = threading.Barrier(8)
    outcomes = []

    def worker():
        barrier.wait()
        outcomes.append(submit_sim(kernel))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(outcome.recorded for outcome in outcomes) == 1
    assert sum(outcome.trace == REJECTION_TRACE for outcome in outcomes) == 7


def test_records_and_server_inputs_are_frozen_and_secrets_are_redacted():
    pending, _, _, kernel = harness()
    outcome = submit_sim(kernel)
    with pytest.raises(dataclasses.FrozenInstanceError):
        outcome.record.actor_id = "actor_mallory"
    assert SIM_NONCE not in repr(pending)
    assert TOKEN not in repr(ApprovalCredential(TOKEN))
