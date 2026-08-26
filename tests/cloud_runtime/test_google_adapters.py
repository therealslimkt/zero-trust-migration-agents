from __future__ import annotations

import sys
import types

import pytest

from cloud_runtime.google_adapters import (
    BigQueryWarehouseGateway,
    DataflowRestGateway,
    GCSObjectStore,
    GoogleAdapterError,
)


class _Blob:
    def __init__(self, *, fail_after_store=False):
        self.data = None
        self.metadata = None
        self.fail_after_store = fail_after_store
        self.uploads = []

    def upload_from_string(self, payload, **kwargs):
        assert kwargs["if_generation_match"] == 0
        self.uploads.append((payload, kwargs))
        if self.data is not None:
            raise RuntimeError("already exists")
        self.data = payload
        if self.fail_after_store:
            self.fail_after_store = False
            raise RuntimeError("response was lost after the create")

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


def test_gcs_store_recovers_unacknowledged_create_only_after_byte_identity():
    client = _StorageClient()
    blob = client.bucket("trusted-bucket").blob("runs/mig_TEST/source/hash.json")
    blob.fail_after_store = True
    store = GCSObjectStore(client)
    kwargs = {
        "bucket": "trusted-bucket",
        "name": "runs/mig_TEST/source/hash.json",
        "payload": b'{"protected":true}',
        "digest": "sha256:" + "2" * 64,
    }

    assert store.ensure_object(**kwargs) == kwargs["digest"]
    assert blob.data == kwargs["payload"]
    assert blob.uploads[0][0] == kwargs["payload"]
    assert blob.uploads[0][1]["if_generation_match"] == 0

    assert store.ensure_object(**kwargs) == kwargs["digest"]
    with pytest.raises(GoogleAdapterError, match="^gcs_immutable_mismatch$"):
        store.ensure_object(**{**kwargs, "payload": b'{"protected":false}'})


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
        return _Request({"job": {"id": self.owner.launch_job_id}})


class _Jobs:
    def __init__(self, owner):
        self.owner = owner

    def get(self, **kwargs):
        self.owner.get_requests.append(kwargs)
        return _Request({"currentState": self.owner.states.pop(0)})

    def list(self, **kwargs):
        self.owner.list_request = kwargs
        return _Request({"jobs": self.owner.jobs})


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
    def __init__(self, states, *, jobs=(), launch_job_id="job-jde-1"):
        self.states = list(states)
        self.jobs = list(jobs)
        self.launch_job_id = launch_job_id
        self.launch_request = None
        self.list_request = None
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


def _dataflow_gateway(service):
    return DataflowRestGateway(
        service,
        temp_location="gs://trusted-bucket/temp",
        sleep=lambda _: None,
    )


def test_dataflow_find_job_by_name_returns_exact_opaque_provider_id():
    opaque_job_id = "2026-08-26_17_42_01-1234567890123456789"
    service = _DataflowService(
        [],
        jobs=[
            {"id": "unrelated-id", "name": "ztm-other-run"},
            {"id": opaque_job_id, "name": "ztm-jde-approved-run"},
        ],
    )

    assert (
        _dataflow_gateway(service).find_job_by_name(
            project="ztm-agent-9049c3",
            region="us-central1",
            job_name="ztm-jde-approved-run",
        )
        == opaque_job_id
    )
    assert service.list_request == {
        "projectId": "ztm-agent-9049c3",
        "location": "us-central1",
        "filter": "ALL",
        "pageSize": 1000,
    }


def test_dataflow_find_job_by_name_returns_none_for_no_exact_match():
    service = _DataflowService(
        [], jobs=[{"id": "job-1", "name": "ztm-jde-approved-run-extra"}]
    )

    assert (
        _dataflow_gateway(service).find_job_by_name(
            project="ztm-agent-9049c3",
            region="us-central1",
            job_name="ztm-jde-approved-run",
        )
        is None
    )


def test_dataflow_find_job_by_name_rejects_ambiguous_exact_matches():
    service = _DataflowService(
        [],
        jobs=[
            {"id": "first-id", "name": "ztm-jde-approved-run"},
            {"id": "second-id", "name": "ztm-jde-approved-run"},
        ],
    )

    with pytest.raises(GoogleAdapterError, match="^dataflow_job_ambiguous$"):
        _dataflow_gateway(service).find_job_by_name(
            project="ztm-agent-9049c3",
            region="us-central1",
            job_name="ztm-jde-approved-run",
        )


def test_dataflow_launch_preserves_opaque_real_shaped_job_id():
    opaque_job_id = "2026-08-26_17_42_01-1234567890123456789"
    service = _DataflowService([], launch_job_id=opaque_job_id)

    observed = _dataflow_gateway(service).launch_flex_template(
        project="ztm-agent-9049c3",
        region="us-central1",
        job_name="ztm-jde-approved-run",
        template_spec_uri="gs://trusted-bucket/template.json",
        worker_service_account="worker@example.iam.gserviceaccount.com",
        parameters={"expected_source_id": "jde"},
        labels={"ztm_source": "jde"},
    )

    assert observed == opaque_job_id


class _FakeQueryJobConfig:
    def __init__(self, **kwargs):
        self.query_parameters = kwargs["query_parameters"]
        self.use_legacy_sql = kwargs["use_legacy_sql"]


class _FakeScalarQueryParameter:
    def __init__(self, name, declared_type, value):
        self.name = name
        self.declared_type = declared_type
        self.value = value


class _BoundedQueryResult:
    def __init__(self):
        self.timeout = None

    def result(self, *, timeout):
        assert 0 < timeout <= 300
        self.timeout = timeout
        return [
            {
                "row_count": 1,
                "distinct_ordinal_count": 1,
                "plan_digests": ["sha256:" + "1" * 64],
                "output_digests": ["sha256:" + "2" * 64],
                "bundle_digests": ["sha256:" + "3" * 64],
                "job_names": ["ztm-jde-approved-run"],
            }
        ]


class _BigQueryClient:
    def __init__(self):
        self.query_job = _BoundedQueryResult()
        self.query_call = None

    def query(self, sql, **kwargs):
        self.query_call = (sql, kwargs)
        return self.query_job


def _install_fake_bigquery(monkeypatch):
    google_module = types.ModuleType("google")
    google_module.__path__ = []
    cloud_module = types.ModuleType("google.cloud")
    cloud_module.__path__ = []
    bigquery_module = types.ModuleType("google.cloud.bigquery")
    bigquery_module.QueryJobConfig = _FakeQueryJobConfig
    bigquery_module.ScalarQueryParameter = _FakeScalarQueryParameter
    google_module.cloud = cloud_module
    cloud_module.bigquery = bigquery_module
    monkeypatch.setitem(sys.modules, "google", google_module)
    monkeypatch.setitem(sys.modules, "google.cloud", cloud_module)
    monkeypatch.setitem(sys.modules, "google.cloud.bigquery", bigquery_module)


def test_bigquery_observation_uses_a_bounded_result_timeout(monkeypatch):
    _install_fake_bigquery(monkeypatch)
    client = _BigQueryClient()
    gateway = BigQueryWarehouseGateway(client, location="us-central1")

    observation = gateway.observe_lineage(
        table_spec="ztm-agent-9049c3:legacy_migration.jde_f0101",
        run_id="mig_CLOUDRUNTIME01",
        source_id="jde",
        output_digest="sha256:" + "2" * 64,
    )

    assert observation.row_count == 1
    assert client.query_job.timeout is not None
