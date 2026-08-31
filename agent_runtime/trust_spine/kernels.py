"""Node kernels for the post-plan trust spine.

Each kernel owns exactly one node of the fixed trace and nothing else. Kernels
are small, injectable objects: the pre-approval kernels are pure functions of
their typed inputs (plus, for Prisma repair, the one model boundary), and the
post-approval kernels wrap exactly one narrow port each.

The separation matters structurally, not just stylistically:

* :class:`PrismaKernel` is the only object in the package that holds a model
  adapter. It is a *pre-approval* object and is never reachable from
  :class:`SealedExecution`.
* :class:`SealedExecution` is the only object that exists on the post-approval
  path. It is validated at construction by :func:`assert_no_model_surface`,
  which refuses to build it if any member is model-capable, is named like a
  model provider, or is a bare callable.
* Flow, Ledger and Forge hold *distinct* ports with distinct principals;
  signing authority never coincides with dispatch or reconciliation authority.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, fields, is_dataclass
from typing import Final

from .protocols import (
    CertificationPort,
    ModelCapable,
    ModelRepairAdapter,
    ReconciliationReader,
    TemplateDispatcher,
)
from .types import (
    ApprovalError,
    ApprovalQuery,
    ApprovalRecord,
    BudgetError,
    CanonicalMap,
    CanonicalValue,
    CertificationError,
    Certificate,
    CertificationRequest,
    Decision,
    DispatchError,
    DispatchReceipt,
    DispatchRequest,
    DurabilityError,
    ExecutionBundle,
    FailureCode,
    FrozenPlan,
    NodeName,
    NodeRecord,
    NodeStatus,
    ParameterBinding,
    PolicyConfig,
    PolicyDecision,
    PolicyError,
    ReconciliationError,
    ReconciliationQuery,
    ReconciliationReport,
    RecordError,
    RegistryError,
    RegistryTemplate,
    RepairRequest,
    SealedBundle,
    Stage,
    TypedValue,
    ValeVerdict,
    ValidatedProposal,
    ValidationError,
    ValueKind,
    chain_step,
    digest_of,
    require_digest,
    require_safe_text,
)

__all__ = [
    "EXECUTABLE_KEY_TOKENS",
    "ForgeKernel",
    "FlowKernel",
    "LedgerKernel",
    "MODEL_SURFACE_TOKENS",
    "PolicyKernel",
    "PrismaKernel",
    "SealedExecution",
    "ValeKernel",
    "assert_no_model_surface",
    "build_execution_bundle",
    "chain_values",
    "expected_effect_digest",
    "has_model_surface_name",
    "node_input_digest",
    "replay_chain",
    "simulation_subject_digest",
    "validate_payload",
    "verify_approval",
]


# ---------------------------------------------------------------------------
# Structural model-surface proof
# ---------------------------------------------------------------------------

#: Name fragments that indicate a model capability rather than model *data*.
MODEL_SURFACE_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "adapter",
        "adapters",
        "agent",
        "assistant",
        "chat",
        "completion",
        "completions",
        "embedding",
        "embeddings",
        "generate",
        "generation",
        "infer",
        "inference",
        "llm",
        "model",
        "models",
        "predict",
        "prompt",
        "prompts",
        "provider",
        "providers",
        "repair",
        "repairs",
        "sample",
    }
)

#: Name fragments a proposal key may never contain. These are the shapes an
#: attacker would need to smuggle an executable target through data.
EXECUTABLE_KEY_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "argv",
        "cmd",
        "code",
        "command",
        "endpoint",
        "eval",
        "exec",
        "expr",
        "expression",
        "file",
        "handle",
        "host",
        "image",
        "module",
        "path",
        "query",
        "script",
        "shell",
        "sql",
        "statement",
        "target",
        "uri",
        "url",
    }
)


def _tokens(name: str) -> tuple[str, ...]:
    cleaned = name.strip("_").lower()
    parts: list[str] = []
    for chunk in cleaned.replace(".", "_").replace("-", "_").split("_"):
        if chunk:
            parts.append(chunk)
    return tuple(parts)


def has_model_surface_name(name: str) -> bool:
    """True if ``name`` reads like a model capability."""
    return any(token in MODEL_SURFACE_TOKENS for token in _tokens(name))


def has_executable_key_name(name: str) -> bool:
    """True if ``name`` reads like an executable target."""
    return any(token in EXECUTABLE_KEY_TOKENS for token in _tokens(name))


def _member_names(obj: object) -> tuple[str, ...]:
    names: list[str] = []
    for klass in type(obj).__mro__:
        for name in getattr(klass, "__slots__", ()):
            if isinstance(name, str) and name not in names:
                names.append(name)
    if is_dataclass(obj):
        for field in fields(obj):
            if field.name not in names:
                names.append(field.name)
    if not names:
        for name in getattr(obj, "__dict__", {}):
            if name not in names:
                names.append(name)
    return tuple(names)


def assert_no_model_surface(obj: object, *, context: str, depth: int = 2) -> None:
    """Refuse ``obj`` if any model capability is reachable from it.

    This is a *structural* rejection, not a counter: it looks for a member that
    satisfies :class:`~agent_runtime.trust_spine.protocols.ModelCapable`, a
    member named like a model adapter/provider, or a stored callable of any
    kind. It never inspects how many calls were made, because on the
    post-approval path the correct number of model calls is not "zero so far",
    it is "not expressible".
    """
    cls = type(obj)
    if isinstance(obj, ModelCapable):
        raise BudgetError(
            FailureCode.POST_APPROVAL_MODEL_CALL,
            f"{context} satisfies the model-capable shape",
        )
    for name in dir(cls):
        if name.startswith("_") or not has_model_surface_name(name):
            continue
        try:
            member = inspect.getattr_static(cls, name)
        except AttributeError:  # pragma: no cover - defensive
            continue
        if callable(member):
            raise BudgetError(
                FailureCode.POST_APPROVAL_MODEL_CALL,
                f"{context} exposes a model-capable method {name!r}",
            )
    for name in _member_names(obj):
        try:
            value = getattr(obj, name)
        except AttributeError:  # pragma: no cover - unset slot
            continue
        if value is None or isinstance(value, (bool, int, float, str, bytes)):
            continue  # model *accounting* is data; data is never a capability
        if has_model_surface_name(name):
            raise BudgetError(
                FailureCode.POST_APPROVAL_MODEL_CALL,
                f"{context} holds a model-capable field {name!r}",
            )
        if callable(value):
            raise BudgetError(
                FailureCode.POST_APPROVAL_MODEL_CALL,
                f"{context}.{name} holds a callable",
            )
        if depth > 0:
            assert_no_model_surface(value, context=f"{context}.{name}", depth=depth - 1)


# ---------------------------------------------------------------------------
# Digest helpers
# ---------------------------------------------------------------------------


def node_input_digest(node: NodeName, *parts: CanonicalValue) -> str:
    """Digest of the closed input a node is about to be run on."""
    if not isinstance(node, NodeName):
        raise RecordError(FailureCode.INVALID_TYPE, "node must be a NodeName")
    return digest_of(("trust_spine.node_input.v1", str(node)) + tuple(parts))


def expected_effect_digest(sealed: SealedBundle) -> str:
    """The one effect the sealed bundle authorises.

    Flow must return exactly this digest on its receipt. Anything else means
    Flow executed something the approvals never sealed.
    """
    if not isinstance(sealed, SealedBundle):
        raise RecordError(FailureCode.INVALID_TYPE, "sealed must be a SealedBundle")
    bundle = sealed.bundle
    return digest_of(
        (
            "trust_spine.effect.v1",
            sealed.seal_digest,
            bundle.bundle_digest,
            bundle.template_digest,
            bundle.template_id,
            bundle.template_version,
            tuple(binding.canonical for binding in bundle.parameters),
        )
    )


def _fold(
    genesis: str,
    records: tuple[NodeRecord, ...],
    approvals: tuple[ApprovalRecord, ...],
) -> tuple[tuple[tuple[NodeName, NodeStatus] | None, str], ...]:
    """Walk the durable trace, verifying every link, yielding running values.

    The fold order is fixed and reconstructible: node records in append order,
    with both approvals folded immediately after the successful ``vale_verify``
    record. Each record must declare, as its ``predecessor_digest``, the chain
    value that preceded it -- so a re-ordered, dropped or edited record cannot
    produce a chain that still links up.
    """
    require_digest(genesis, "genesis")
    chain = genesis
    steps: list[tuple[tuple[NodeName, NodeStatus] | None, str]] = []
    folded = False
    for record in records:
        if record.predecessor_digest != chain:
            raise DurabilityError(
                FailureCode.CHAIN_CORRUPTION,
                f"{record.node}/{record.status} does not link to the chain",
            )
        chain = chain_step(chain, record.digest)
        steps.append(((record.node, record.status), chain))
        if not folded and record.node is NodeName.VALE_VERIFY and record.status is NodeStatus.SUCCEEDED:
            folded = True
            for approval in approvals:
                if approval.predecessor_digest != chain:
                    raise DurabilityError(
                        FailureCode.CHAIN_CORRUPTION,
                        f"{approval.stage} approval does not link to the chain",
                    )
                chain = chain_step(chain, approval.digest)
                steps.append((None, chain))
    if approvals and not folded:
        raise DurabilityError(
            FailureCode.CHAIN_CORRUPTION, "approvals recorded without a verified proposal"
        )
    return tuple(steps)


def chain_values(
    genesis: str,
    records: tuple[NodeRecord, ...],
    approvals: tuple[ApprovalRecord, ...],
) -> tuple[str, ...]:
    """Every running chain value, genesis first, with all links verified.

    Used on resume: a checkpoint written before a crash must equal one of these
    values, i.e. it must be a genuine prefix of the durable trace.
    """
    return (genesis,) + tuple(value for _, value in _fold(genesis, records, approvals))


def replay_chain(
    genesis: str,
    records: tuple[NodeRecord, ...],
    approvals: tuple[ApprovalRecord, ...],
    *,
    stop_after: tuple[NodeName, NodeStatus] | None = None,
) -> str:
    """Recompute the hash chain over the durable trace, verifying every link."""
    steps = _fold(genesis, records, approvals)
    if stop_after is None:
        return steps[-1][1] if steps else genesis
    for label, value in steps:
        if label == stop_after:
            return value
    raise DurabilityError(
        FailureCode.STATE_CORRUPTION, f"chain checkpoint {stop_after[0]} was never reached"
    )


# ---------------------------------------------------------------------------
# prisma_validate / prisma_repair
# ---------------------------------------------------------------------------

#: The complete, closed field set of a proposal payload.
PROPOSAL_FIELDS: Final[tuple[str, ...]] = (
    "parameters",
    "summary",
    "template_id",
    "template_version",
)
PARAMETER_FIELDS: Final[tuple[str, ...]] = ("kind", "name", "value")


def _reject_unknown(keys: tuple[str, ...], allowed: tuple[str, ...], where: str) -> None:
    for key in keys:
        if key in allowed:
            continue
        if has_executable_key_name(key):
            raise ValidationError(
                FailureCode.DANGEROUS_KEY, f"{where} carries an executable-looking key {key!r}"
            )
        raise ValidationError(FailureCode.UNKNOWN_FIELD, f"{where} has unknown field {key!r}")
    missing = tuple(name for name in allowed if name not in keys)
    if missing:
        raise ValidationError(
            FailureCode.PROPOSAL_INVALID, f"{where} is missing fields {missing!r}"
        )


def _parameter_from(entry: CanonicalValue, index: int) -> ParameterBinding:
    where = f"proposal.parameters[{index}]"
    if not isinstance(entry, CanonicalMap):
        raise ValidationError(FailureCode.INVALID_TYPE, f"{where} must be a map")
    _reject_unknown(entry.keys(), PARAMETER_FIELDS, where)
    raw_kind = entry["kind"]
    if not isinstance(raw_kind, str):
        raise ValidationError(FailureCode.INVALID_TYPE, f"{where}.kind must be a str")
    try:
        kind = ValueKind(raw_kind)
    except ValueError as exc:
        raise ValidationError(
            FailureCode.PARAMETER_INVALID, f"{where}.kind is not a known value kind"
        ) from exc
    name = entry["name"]
    value = entry["value"]
    if kind is ValueKind.BOOLEAN and not isinstance(value, bool):
        raise ValidationError(FailureCode.PARAMETER_INVALID, f"{where}.value must be a bool")
    if kind is ValueKind.INTEGER and (isinstance(value, bool) or not isinstance(value, int)):
        raise ValidationError(FailureCode.PARAMETER_INVALID, f"{where}.value must be an int")
    if kind is ValueKind.STRING and not isinstance(value, str):
        raise ValidationError(FailureCode.PARAMETER_INVALID, f"{where}.value must be a str")
    try:
        return ParameterBinding(name=name, value=TypedValue(kind=kind, value=value))
    except (RecordError, ValidationError) as exc:
        raise ValidationError(
            FailureCode.PARAMETER_INVALID, f"{where} was refused", detail=str(exc)
        ) from exc


def validate_payload(plan: FrozenPlan, payload: CanonicalMap) -> ValidatedProposal:
    """Prisma structured-output validation.

    Turns an untrusted candidate payload into a :class:`ValidatedProposal` or
    refuses it. The result is *data*: a registry template identity plus closed
    typed parameter values. There is no field in which a command, module, SQL
    statement, path, image reference or expression could survive validation.
    """
    if not isinstance(plan, FrozenPlan):
        raise RecordError(FailureCode.INVALID_TYPE, "plan must be a FrozenPlan")
    if not isinstance(payload, CanonicalMap):
        raise ValidationError(FailureCode.INVALID_TYPE, "proposal payload must be a canonical map")
    _reject_unknown(payload.keys(), PROPOSAL_FIELDS, "proposal")
    raw_parameters = payload["parameters"]
    if not isinstance(raw_parameters, tuple):
        raise ValidationError(FailureCode.INVALID_TYPE, "proposal.parameters must be a sequence")
    bindings = tuple(
        _parameter_from(entry, index) for index, entry in enumerate(raw_parameters)
    )
    names = [binding.name for binding in bindings]
    if len(set(names)) != len(names):
        raise ValidationError(FailureCode.PARAMETER_INVALID, "duplicate parameter name")
    summary = payload["summary"]
    require_safe_text(summary, "proposal.summary", max_length=200)
    try:
        return ValidatedProposal(
            tenant_id=plan.tenant_id,
            run_id=plan.run_id,
            source_digest=plan.source_digest,
            template_id=payload["template_id"],
            template_version=payload["template_version"],
            parameters=bindings,
            summary=summary,
            payload_digest=digest_of(payload),
        )
    except RecordError as exc:
        raise ValidationError(
            FailureCode.PROPOSAL_INVALID, "proposal failed record validation", detail=str(exc)
        ) from exc


@dataclass(frozen=True, slots=True)
class PrismaKernel:
    """Validation plus the single, bounded, pre-approval model boundary.

    This object deliberately *does* satisfy the model-capable shape: it is the
    contrast case for :func:`assert_no_model_surface`, and it must never appear
    on the sealed execution path.
    """

    adapter: ModelRepairAdapter

    def __post_init__(self) -> None:
        if not hasattr(self.adapter, "repair") or not hasattr(self.adapter, "adapter_id"):
            raise RecordError(FailureCode.INVALID_TYPE, "adapter must be a ModelRepairAdapter")

    @property
    def adapter_id(self) -> str:
        return self.adapter.adapter_id

    def validate(self, plan: FrozenPlan, payload: CanonicalMap) -> ValidatedProposal:
        return validate_payload(plan, payload)

    def repair(self, request: RepairRequest) -> CanonicalMap:
        """One bounded repair attempt. Returns data; never a callable."""
        if not isinstance(request, RepairRequest):
            raise RecordError(FailureCode.INVALID_TYPE, "request must be a RepairRequest")
        try:
            payload = self.adapter.repair(request)
        except Exception as exc:  # noqa: BLE001 - adapter failures are data
            raise ValidationError(
                FailureCode.ADAPTER_FAILURE, "repair adapter raised", detail=type(exc).__name__
            ) from exc
        if not isinstance(payload, CanonicalMap):
            raise ValidationError(
                FailureCode.INVALID_TYPE, "repair adapter must return a canonical map"
            )
        return payload


# ---------------------------------------------------------------------------
# deterministic_policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PolicyKernel:
    """Pure, total, deterministic policy evaluation."""

    config: PolicyConfig

    def __post_init__(self) -> None:
        if not isinstance(self.config, PolicyConfig):
            raise RecordError(FailureCode.INVALID_TYPE, "config must be a PolicyConfig")

    def decide(self, proposal: ValidatedProposal, template: RegistryTemplate) -> PolicyDecision:
        if not isinstance(proposal, ValidatedProposal):
            raise RecordError(FailureCode.INVALID_TYPE, "proposal must be a ValidatedProposal")
        if not isinstance(template, RegistryTemplate):
            raise RecordError(FailureCode.INVALID_TYPE, "template must be a RegistryTemplate")
        if proposal.tenant_id not in self.config.allowed_tenants:
            raise PolicyError(FailureCode.POLICY_DENIED, "tenant is not allowed by policy")
        identity = (proposal.template_id, proposal.template_version)
        if identity not in self.config.allowed_templates:
            raise PolicyError(FailureCode.POLICY_DENIED, "template identity is not allowlisted")
        if (template.template_id, template.template_version) != identity:
            raise RegistryError(
                FailureCode.TEMPLATE_MISMATCH, "registry template identity does not match proposal"
            )
        if len(proposal.parameters) > self.config.max_parameters:
            raise PolicyError(FailureCode.PARAMETER_NOT_ALLOWED, "too many parameters for policy")
        for binding in proposal.parameters:
            spec = template.spec_for(binding.name)
            if spec is None:
                raise PolicyError(
                    FailureCode.PARAMETER_NOT_ALLOWED,
                    f"parameter {binding.name!r} is not declared by the registry template",
                )
            if not spec.accepts(binding.value):
                raise PolicyError(
                    FailureCode.PARAMETER_INVALID,
                    f"parameter {binding.name!r} is outside its registry-declared domain",
                )
        bound = {binding.name for binding in proposal.parameters}
        for spec in template.parameter_specs:
            if spec.required and spec.name not in bound:
                raise PolicyError(
                    FailureCode.PARAMETER_INVALID, f"required parameter {spec.name!r} is missing"
                )
        return PolicyDecision(
            tenant_id=proposal.tenant_id,
            run_id=proposal.run_id,
            source_digest=proposal.source_digest,
            proposal_digest=proposal.proposal_digest,
            template_id=proposal.template_id,
            template_version=proposal.template_version,
            template_digest=template.template_digest,
            parameters=proposal.parameters,
            policy_id=self.config.policy_id,
            policy_version=self.config.policy_version,
            policy_config_digest=self.config.digest,
            obligations=self.config.obligations,
            allowed=True,
        )


# ---------------------------------------------------------------------------
# vale_verify
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ValeKernel:
    """Independent verification.

    Vale re-derives the decision from its own configuration and compares
    digests. It has no repair path and no widening path: its only two outcomes
    are "verified" and a terminal refusal.
    """

    config: PolicyConfig

    def __post_init__(self) -> None:
        if not isinstance(self.config, PolicyConfig):
            raise RecordError(FailureCode.INVALID_TYPE, "config must be a PolicyConfig")

    def verify(
        self,
        proposal: ValidatedProposal,
        decision: PolicyDecision,
        template: RegistryTemplate,
    ) -> ValeVerdict:
        if not isinstance(decision, PolicyDecision):
            raise RecordError(FailureCode.INVALID_TYPE, "decision must be a PolicyDecision")
        if not decision.allowed:
            raise PolicyError(FailureCode.VALE_REFUSED, "policy did not allow the proposal")
        if decision.proposal_digest != proposal.proposal_digest:
            raise PolicyError(FailureCode.VALE_REFUSED, "decision is not bound to this proposal")
        if decision.template_digest != template.template_digest:
            raise PolicyError(FailureCode.VALE_REFUSED, "decision is not bound to this template")
        if decision.policy_config_digest != self.config.digest:
            raise PolicyError(
                FailureCode.VALE_REFUSED, "decision was taken under a different policy configuration"
            )
        if decision.obligations != self.config.obligations:
            raise PolicyError(FailureCode.VALE_REFUSED, "decision obligations were altered")
        try:
            recomputed = PolicyKernel(self.config).decide(proposal, template)
        except (PolicyError, RegistryError) as exc:
            raise PolicyError(
                FailureCode.VALE_REFUSED, "independent re-evaluation refused", detail=str(exc)
            ) from exc
        if recomputed.digest != decision.digest:
            raise PolicyError(
                FailureCode.VALE_REFUSED, "independent re-evaluation disagreed with the decision"
            )
        for binding in proposal.parameters:
            spec = template.spec_for(binding.name)
            if spec is None or not spec.accepts(binding.value):
                raise PolicyError(
                    FailureCode.VALE_REFUSED,
                    f"parameter {binding.name!r} is not independently verifiable",
                )
        return ValeVerdict(
            tenant_id=proposal.tenant_id,
            run_id=proposal.run_id,
            source_digest=proposal.source_digest,
            proposal_digest=proposal.proposal_digest,
            policy_digest=decision.digest,
            template_digest=template.template_digest,
            obligations=decision.obligations,
            verified=True,
        )


# ---------------------------------------------------------------------------
# Approval boundaries
# ---------------------------------------------------------------------------


def simulation_subject_digest(
    *, plan_digest: str, proposal_digest: str, policy_digest: str, vale_digest: str
) -> str:
    """The subject a simulation approval is asked about."""
    for name, value in (
        ("plan_digest", plan_digest),
        ("proposal_digest", proposal_digest),
        ("policy_digest", policy_digest),
        ("vale_digest", vale_digest),
    ):
        require_digest(value, name)
    return digest_of(
        (
            "trust_spine.simulation_subject.v1",
            plan_digest,
            proposal_digest,
            policy_digest,
            vale_digest,
        )
    )


def build_execution_bundle(
    *,
    proposal: ValidatedProposal,
    decision: PolicyDecision,
    verdict: ValeVerdict,
    simulation_approval: ApprovalRecord,
) -> ExecutionBundle:
    """Assemble everything execution may know, and nothing else.

    The production approval's subject is this bundle's digest, so the second
    approval is answered about a strictly different object than the first.
    """
    if simulation_approval.stage is not Stage.SIMULATION:
        raise ApprovalError(
            FailureCode.APPROVAL_MISMATCH, "bundle requires the simulation approval"
        )
    return ExecutionBundle(
        tenant_id=proposal.tenant_id,
        run_id=proposal.run_id,
        source_digest=proposal.source_digest,
        proposal_digest=proposal.proposal_digest,
        policy_digest=decision.digest,
        vale_digest=verdict.digest,
        simulation_approval_digest=simulation_approval.digest,
        template_id=proposal.template_id,
        template_version=proposal.template_version,
        template_digest=decision.template_digest,
        parameters=proposal.parameters,
    )


def verify_approval(
    record: object,
    *,
    query: ApprovalQuery,
    authority_id: str,
    expected_key: str,
    check_predecessor: bool = True,
) -> ApprovalRecord:
    """Verify an approval record against the exact question that was asked."""
    if not isinstance(record, ApprovalRecord):
        raise ApprovalError(
            FailureCode.INVALID_TYPE, "approval authority returned a non-approval object"
        )
    if record.authority_id != authority_id:
        raise ApprovalError(
            FailureCode.APPROVAL_MISMATCH, "approval was not issued by the injected authority"
        )
    if (record.tenant_id, record.run_id, record.source_digest) != (
        query.tenant_id,
        query.run_id,
        query.source_digest,
    ):
        raise ApprovalError(FailureCode.APPROVAL_MISMATCH, "approval is bound to a different run")
    if record.stage is not query.stage:
        raise ApprovalError(FailureCode.APPROVAL_MISMATCH, "approval is for a different stage")
    if record.subject_digest != query.subject_digest:
        raise ApprovalError(FailureCode.APPROVAL_MISMATCH, "approval is for a different subject")
    if check_predecessor and record.predecessor_digest != query.predecessor_digest:
        raise ApprovalError(
            FailureCode.APPROVAL_MISMATCH, "approval is bound to a different chain position"
        )
    if record.idempotency_key != expected_key:
        raise ApprovalError(
            FailureCode.APPROVAL_REPLAY, "approval key does not match this exact boundary"
        )
    if record.decision is not Decision.APPROVE:
        raise ApprovalError(FailureCode.APPROVAL_REJECTED, "approval authority rejected the run")
    return record


# ---------------------------------------------------------------------------
# Post-approval effect kernels
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FlowKernel:
    """Registry-owned template dispatch.

    ``resolve`` is a pure registry read. ``dispatch`` hands the sealed bundle
    to the dispatcher and validates the receipt: the caller never names a
    command, module, statement, path, image or expression anywhere.
    """

    dispatcher: TemplateDispatcher

    def __post_init__(self) -> None:
        for attribute in ("dispatcher_id", "resolve_template", "dispatch"):
            if not hasattr(self.dispatcher, attribute):
                raise RecordError(FailureCode.INVALID_TYPE, "dispatcher must be a TemplateDispatcher")

    @property
    def dispatcher_id(self) -> str:
        return self.dispatcher.dispatcher_id

    def resolve(self, template_id: str, template_version: str) -> RegistryTemplate:
        try:
            template = self.dispatcher.resolve_template(template_id, template_version)
        except RegistryError:
            raise
        except Exception as exc:  # noqa: BLE001 - registry misses are terminal
            raise RegistryError(
                FailureCode.TEMPLATE_NOT_REGISTERED,
                "registry refused the template identity",
                detail=type(exc).__name__,
            ) from exc
        if not isinstance(template, RegistryTemplate):
            raise RegistryError(
                FailureCode.TEMPLATE_NOT_REGISTERED, "registry returned a non-template object"
            )
        if (template.template_id, template.template_version) != (template_id, template_version):
            raise RegistryError(
                FailureCode.TEMPLATE_MISMATCH, "registry returned a different template identity"
            )
        return template

    def dispatch(self, request: DispatchRequest) -> DispatchReceipt:
        if not isinstance(request, DispatchRequest):
            raise RecordError(FailureCode.INVALID_TYPE, "request must be a DispatchRequest")
        sealed = request.sealed
        expected = expected_effect_digest(sealed)
        try:
            receipt = self.dispatcher.dispatch(request)
        except DispatchError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise DispatchError(
                FailureCode.ADAPTER_FAILURE, "dispatcher raised", detail=type(exc).__name__
            ) from exc
        if not isinstance(receipt, DispatchReceipt):
            raise DispatchError(FailureCode.DISPATCH_MISMATCH, "dispatcher returned a non-receipt")
        bundle = sealed.bundle
        mismatches = tuple(
            name
            for name, actual, wanted in (
                ("tenant_id", receipt.tenant_id, bundle.tenant_id),
                ("run_id", receipt.run_id, bundle.run_id),
                ("seal_digest", receipt.seal_digest, sealed.seal_digest),
                ("bundle_digest", receipt.bundle_digest, bundle.bundle_digest),
                ("template_id", receipt.template_id, bundle.template_id),
                ("template_version", receipt.template_version, bundle.template_version),
                ("template_digest", receipt.template_digest, bundle.template_digest),
                ("effect_digest", receipt.effect_digest, expected),
                ("idempotency_key", receipt.idempotency_key, request.idempotency_key),
                ("dispatcher_id", receipt.dispatcher_id, self.dispatcher_id),
            )
            if actual != wanted
        )
        if mismatches:
            raise DispatchError(
                FailureCode.DISPATCH_MISMATCH, f"receipt does not bind {mismatches!r}"
            )
        return receipt


@dataclass(frozen=True, slots=True)
class LedgerKernel:
    """Ledger reconciliation.

    Reconciliation is a *read*, but it is externally observed, so it is run
    with the same intent-before-effect discipline and the same stable replay
    key as a write. The report is validated against both the receipt and the
    sealed expectations, so a ledger that reconciles some other effect cannot
    satisfy this node.
    """

    reader: ReconciliationReader

    def __post_init__(self) -> None:
        for attribute in ("reader_id", "read_reconciliation"):
            if not hasattr(self.reader, attribute):
                raise RecordError(FailureCode.INVALID_TYPE, "reader must be a ReconciliationReader")

    @property
    def reader_id(self) -> str:
        return self.reader.reader_id

    def reconcile(
        self, query: ReconciliationQuery, *, sealed: SealedBundle, receipt: DispatchReceipt
    ) -> ReconciliationReport:
        if not isinstance(query, ReconciliationQuery):
            raise RecordError(FailureCode.INVALID_TYPE, "query must be a ReconciliationQuery")
        expected_effect = expected_effect_digest(sealed)
        if receipt.effect_digest != expected_effect:
            raise ReconciliationError(
                FailureCode.RECONCILIATION_MISMATCH, "receipt effect is not the sealed effect"
            )
        try:
            report = self.reader.read_reconciliation(query)
        except ReconciliationError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ReconciliationError(
                FailureCode.ADAPTER_FAILURE, "ledger reader raised", detail=type(exc).__name__
            ) from exc
        if not isinstance(report, ReconciliationReport):
            raise ReconciliationError(
                FailureCode.RECONCILIATION_MISMATCH, "ledger returned a non-report object"
            )
        mismatches = tuple(
            name
            for name, actual, wanted in (
                ("tenant_id", report.tenant_id, sealed.tenant_id),
                ("run_id", report.run_id, sealed.run_id),
                ("seal_digest", report.seal_digest, sealed.seal_digest),
                ("bundle_digest", report.bundle_digest, sealed.bundle.bundle_digest),
                ("dispatch_id", report.dispatch_id, receipt.dispatch_id),
                ("effect_digest", report.effect_digest, expected_effect),
                ("idempotency_key", report.idempotency_key, query.idempotency_key),
                ("reader_id", report.reader_id, self.reader_id),
            )
            if actual != wanted
        )
        if mismatches:
            raise ReconciliationError(
                FailureCode.RECONCILIATION_MISMATCH, f"report does not bind {mismatches!r}"
            )
        if not report.reconciled:
            raise ReconciliationError(
                FailureCode.RECONCILIATION_FAILED, "ledger did not reconcile the dispatched effect"
            )
        return report


@dataclass(frozen=True, slots=True)
class ForgeKernel:
    """Certification: whole-chain validation plus separate signing authority."""

    port: CertificationPort

    def __post_init__(self) -> None:
        for attribute in ("signer_id", "sign_and_release"):
            if not hasattr(self.port, attribute):
                raise RecordError(FailureCode.INVALID_TYPE, "port must be a CertificationPort")

    @property
    def signer_id(self) -> str:
        return self.port.signer_id

    def certify(
        self,
        request: CertificationRequest,
        *,
        genesis: str,
        records: tuple[NodeRecord, ...],
        approvals: tuple[ApprovalRecord, ...],
        sealed: SealedBundle,
        report: ReconciliationReport,
    ) -> Certificate:
        if not isinstance(request, CertificationRequest):
            raise RecordError(FailureCode.INVALID_TYPE, "request must be a CertificationRequest")
        # Forge re-walks the entire chain itself; it trusts no running total.
        chain = replay_chain(
            genesis,
            records,
            approvals,
            stop_after=(NodeName.LEDGER_RECONCILE, NodeStatus.SUCCEEDED),
        )
        if request.chain_digest != chain:
            raise CertificationError(
                FailureCode.CHAIN_CORRUPTION, "certification request does not match the trace chain"
            )
        if request.seal_digest != sealed.seal_digest:
            raise CertificationError(
                FailureCode.CERTIFICATION_MISMATCH, "certification request is not bound to the seal"
            )
        if request.reconciliation_digest != report.digest:
            raise CertificationError(
                FailureCode.CERTIFICATION_MISMATCH,
                "certification request is not bound to the reconciliation",
            )
        if len(approvals) != 2 or approvals[0].stage is not Stage.SIMULATION or approvals[1].stage is not Stage.PRODUCTION:
            raise CertificationError(
                FailureCode.CERTIFICATION_MISMATCH,
                "certification requires distinct simulation and production approvals",
            )
        if sealed.production_approval_digest != approvals[1].digest:
            raise CertificationError(
                FailureCode.CERTIFICATION_MISMATCH, "seal is not bound to the production approval"
            )
        try:
            certificate = self.port.sign_and_release(request)
        except CertificationError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise CertificationError(
                FailureCode.ADAPTER_FAILURE, "signer raised", detail=type(exc).__name__
            ) from exc
        if not isinstance(certificate, Certificate):
            raise CertificationError(
                FailureCode.CERTIFICATION_MISMATCH, "signer returned a non-certificate object"
            )
        mismatches = tuple(
            name
            for name, actual, wanted in (
                ("tenant_id", certificate.tenant_id, request.tenant_id),
                ("run_id", certificate.run_id, request.run_id),
                ("seal_digest", certificate.seal_digest, request.seal_digest),
                ("reconciliation_digest", certificate.reconciliation_digest, request.reconciliation_digest),
                ("chain_digest", certificate.chain_digest, request.chain_digest),
                ("idempotency_key", certificate.idempotency_key, request.idempotency_key),
                ("signer_id", certificate.signer_id, self.signer_id),
            )
            if actual != wanted
        )
        if mismatches:
            raise CertificationError(
                FailureCode.CERTIFICATION_MISMATCH, f"certificate does not bind {mismatches!r}"
            )
        if not certificate.released:
            raise CertificationError(FailureCode.CERTIFICATION_MISMATCH, "certificate is unreleased")
        return certificate


# ---------------------------------------------------------------------------
# The sealed execution path
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SealedExecution:
    """The only object that exists after ``APPROVED_FOR_EXECUTION``.

    It carries the sealed bundle and the three effect kernels. It carries no
    model adapter, no model provider, no model-named field and no callable
    field -- :func:`assert_no_model_surface` refuses to construct it otherwise.
    Post-approval model access is therefore not a budget that could be
    overspent; it is a shape that does not exist.
    """

    sealed: SealedBundle
    plan_digest: str
    flow: FlowKernel
    ledger: LedgerKernel
    forge: ForgeKernel

    def __post_init__(self) -> None:
        if not isinstance(self.sealed, SealedBundle):
            raise RecordError(FailureCode.INVALID_TYPE, "sealed must be a SealedBundle")
        require_digest(self.plan_digest, "plan_digest")
        for name, kernel, wanted in (
            ("flow", self.flow, FlowKernel),
            ("ledger", self.ledger, LedgerKernel),
            ("forge", self.forge, ForgeKernel),
        ):
            if not isinstance(kernel, wanted):
                raise RecordError(FailureCode.INVALID_TYPE, f"{name} must be a {wanted.__name__}")
        principals = (self.flow.dispatcher_id, self.ledger.reader_id, self.forge.signer_id)
        if len(set(principals)) != len(principals):
            raise CertificationError(
                FailureCode.SIGNER_SEPARATION, "dispatch, ledger and signing principals must differ"
            )
        objects = (self.flow.dispatcher, self.ledger.reader, self.forge.port)
        if len({id(item) for item in objects}) != len(objects):
            raise CertificationError(
                FailureCode.SIGNER_SEPARATION, "dispatch, ledger and signing objects must differ"
            )
        assert_no_model_surface(self, context="sealed_execution")

    @property
    def tenant_id(self) -> str:
        return self.sealed.tenant_id

    @property
    def run_id(self) -> str:
        return self.sealed.run_id

    @property
    def source_digest(self) -> str:
        return self.sealed.source_digest

    @property
    def seal_digest(self) -> str:
        return self.sealed.seal_digest

    @property
    def proposal_digest(self) -> str:
        return self.sealed.bundle.proposal_digest

    def build_dispatch_request(self, key: str) -> DispatchRequest:
        return DispatchRequest(sealed=self.sealed, idempotency_key=key)

    def build_reconciliation_query(self, receipt: DispatchReceipt, key: str) -> ReconciliationQuery:
        return ReconciliationQuery(
            tenant_id=self.tenant_id,
            run_id=self.run_id,
            seal_digest=self.seal_digest,
            bundle_digest=self.sealed.bundle.bundle_digest,
            dispatch_id=receipt.dispatch_id,
            effect_digest=receipt.effect_digest,
            idempotency_key=key,
        )

    def build_certification_request(
        self, report: ReconciliationReport, chain_digest: str, key: str
    ) -> CertificationRequest:
        return CertificationRequest(
            tenant_id=self.tenant_id,
            run_id=self.run_id,
            seal_digest=self.seal_digest,
            reconciliation_digest=report.digest,
            chain_digest=chain_digest,
            idempotency_key=key,
        )
