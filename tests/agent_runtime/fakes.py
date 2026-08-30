"""Test-only in-memory implementations of the runtime ports."""

from __future__ import annotations

from agent_runtime.ports import ArtifactLocation, ContractDocument, VersionedDocument


class FakeStateStore:
    async def load(self, *, tenant_id, run_id):
        return None

    async def compare_and_set(
        self, *, tenant_id, run_id, expected_revision, document
    ):
        revision = 0 if expected_revision is None else expected_revision + 1
        return VersionedDocument(revision=revision, document=document)


class FakeArtifactStore:
    async def put_immutable(
        self,
        *,
        tenant_id,
        run_id,
        artifact_name,
        payload,
        media_type,
        expected_digest,
    ):
        return ArtifactLocation(
            uri=f"test://{tenant_id}/{run_id}/{artifact_name}",
            digest=expected_digest,
            media_type=media_type,
            size_bytes=len(payload),
        )

    async def read(self, *, tenant_id, location):
        return b""


class FakeModelProvider:
    async def generate(
        self, *, tenant_id, run_id, request, response_schema_id
    ):
        return ContractDocument(response_schema_id, {"status": "test"})


class FakeEventSink:
    async def append(self, *, event):
        return 1


class FakeApprovalAuthority:
    async def require_verified(self, *, expectation, evidence):
        return evidence


class FakeExecutor:
    async def execute(self, *, command, verified_approval):
        return ContractDocument("ztm.test.execution-result.v1", {"status": "test"})


def runtime_port_fakes():
    from agent_runtime.ports import RuntimePorts

    return RuntimePorts(
        state=FakeStateStore(),
        artifacts=FakeArtifactStore(),
        models=FakeModelProvider(),
        events=FakeEventSink(),
        approvals=FakeApprovalAuthority(),
        executor=FakeExecutor(),
    )
