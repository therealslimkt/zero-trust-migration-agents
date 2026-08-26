from __future__ import annotations

import pytest

from cloud_runtime.google_adapters import (
    DataflowRestGateway,
    GCSObjectStore,
    GoogleAdapterError,
)


class _Blob:
    def __init__(self):
        self.data = None
        self.metadata = None

    def upload_from_string(self, payload, **kwargs):
        assert kwargs["if_generation_match"] == 0
        if self.data is not None:
            raise RuntimeError("already exists")
        self.data = payload

    def download_as_bytes(self):
        if self.data is None:
            raise RuntimeError("missing")
        return self.data


class _Bucket:
    def __init__(self):
        self.blobs = {}

    def blob(self, name):
        return self.blobs.setdefault(name, _Blob())


class _StorageClient:
    def __init__(self):
        self.buckets = {}

    def bucket(self, name):
        return self.buckets.setdefault(name, _Bucket())


def test_gcs_store_is_create_only_and_idempotent_only_for_identical_bytes():
    client = _StorageClient()
    store = GCSObjectStore(client)
    kwargs = {
        "bucket": "trusted-bucket",
        "name": "runs/mig_TEST/source/hash.json",
        "payload": b'{"protected":true}',
        "digest": "sha256:" + "1" * 64,
    }
    assert store.ensure_object(**kwargs) == kwargs["digest"]
    assert store.ensure_object(**kwargs) == kwargs["digest"]
    with pytest.raises(GoogleAdapterError, match="^gcs_immutable_mismatch$"):
        store.ensure_object(**{**kwargs, "payload": b'{"different":true}'})


class _Request:
    def __init__(self, response):
        self.response = response

    def execute(self, **kwargs):
        assert kwargs == {"num_retries": 3}
        return self.response


class _FlexTemplates:
    def __init__(self, owner):
        self.owner = owner

    def launch(self, **kwargs):
        self.owner.launch_request = kwargs
        return _Request({"job": {"id": "job-jde-1"}})


class _Jobs:
    def __init__(self, owner):
        self.owner = owner

    def get(self, **kwargs):
        self.owner.get_requests.append(kwargs)
        return _Request({"currentState": self.owner.states.pop(0)})


class _Locations:
    def __init__(self, owner):
        self.owner = owner

    def flexTemplates(self):
        return _FlexTemplates(self.owner)

    def jobs(self):
        return _Jobs(self.owner)


class _Projects:
    def __init__(self, owner):
        self.owner = owner

    def locations(self):
        return _Locations(self.owner)


class _DataflowService:
    def __init__(self, states):
        self.states = list(states)
        self.launch_request = None
        self.get_requests = []

    def projects(self):
        return _Projects(self)


def test_dataflow_adapter_locks_private_workers_and_canonical_terminal_state():
    service = _DataflowService(["JOB_STATE_RUNNING", "JOB_STATE_DONE"])
    clock_values = iter([0.0, 0.0, 1.0])
    gateway = DataflowRestGateway(
        service,
        temp_location="gs://trusted-bucket/temp",
        poll_interval_seconds=0.1,
        timeout_seconds=10,
        sleep=lambda _: None,
        monotonic=lambda: next(clock_values),
    )
    job_id = gateway.launch_flex_template(
        project="ztm-agent-9049c3",
        region="us-central1",
        job_name="ztm-jde-test",
        template_spec_uri="gs://trusted-bucket/template.json",
        worker_service_account="worker@example.iam.gserviceaccount.com",
        parameters={"expected_source_id": "jde"},
        labels={"ztm_source": "jde"},
    )
    assert job_id == "job-jde-1"
    environment = service.launch_request["body"]["launchParameter"]["environment"]
    assert environment["ipConfiguration"] == "WORKER_IP_PRIVATE"
    assert "block_project_ssh_keys" in environment["additionalExperiments"]
    assert "enable_portable_runner" in environment["additionalExperiments"]
    assert (
        gateway.wait_for_terminal(
            project="ztm-agent-9049c3", region="us-central1", job_id=job_id
        )
        == "JOB_STATE_DONE"
    )
