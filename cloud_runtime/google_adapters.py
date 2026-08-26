"""Google SDK adapters for the trusted cloud-runtime ports.

Constructors require already-created SDK clients/services; this module never
discovers credentials, reads environment variables, or logs provider payloads.
All provider failures collapse to stable codes.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Callable, Mapping
from typing import Any

from .dataflow_template import parse_table_spec
from .orchestrator import WarehouseObservation


class GoogleAdapterError(RuntimeError):
    """A provider failure with no reflected SDK or cloud-resource text."""


def _fail(code: str) -> None:
    raise GoogleAdapterError(code)


class GCSObjectStore:
    """Create or byte-for-byte verify one small content-addressed object."""

    _MAX_BUNDLE_BYTES = 10 << 20

    def __init__(self, client: Any) -> None:
        if client is None:
            raise ValueError("storage client is required")
        self._client = client

    def ensure_object(
        self, *, bucket: str, name: str, payload: bytes, digest: str
    ) -> str:
        if type(payload) is not bytes or not payload or len(payload) > self._MAX_BUNDLE_BYTES:
            _fail("gcs_payload")
        payload_digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        try:
            blob = self._client.bucket(bucket).blob(name)
            try:
                blob.metadata = {
                    "ztm-bundle-digest": digest,
                    "ztm-payload-digest": payload_digest,
                }
                blob.upload_from_string(
                    payload,
                    content_type="application/json",
                    if_generation_match=0,
                )
            except Exception:
                # A retry after a successful but unacknowledged create is safe
                # only when the existing bytes are identical.
                pass
            observed = blob.download_as_bytes()
        except Exception:
            _fail("gcs_unavailable")
        if type(observed) is not bytes or not hmac.compare_digest(observed, payload):
            _fail("gcs_immutable_mismatch")
        return digest


class DataflowRestGateway:
    """Launch only the configured Flex Template and poll with a hard bound."""

    _TERMINAL_STATES = frozenset(
        {
            "JOB_STATE_DONE",
            "JOB_STATE_FAILED",
            "JOB_STATE_CANCELLED",
            "JOB_STATE_DRAINED",
            "JOB_STATE_UPDATED",
        }
    )

    def __init__(
        self,
        service: Any,
        *,
        temp_location: str,
        poll_interval_seconds: float = 10.0,
        timeout_seconds: float = 1800.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if service is None or not temp_location.startswith("gs://"):
            raise ValueError("Dataflow service and GCS temp location are required")
        if poll_interval_seconds <= 0 or timeout_seconds <= 0:
            raise ValueError("Dataflow polling bounds must be positive")
        self._service = service
        self._temp_location = temp_location.rstrip("/") + "/"
        self._poll_interval = poll_interval_seconds
        self._timeout = timeout_seconds
        self._sleep = sleep
        self._monotonic = monotonic

    @staticmethod
    def _execute(request: Any) -> Mapping[str, object]:
        try:
            response = request.execute(num_retries=3)
        except Exception:
            _fail("dataflow_api")
        if not isinstance(response, Mapping):
            _fail("dataflow_response")
        return response

    def launch_flex_template(
        self,
        *,
        project: str,
        region: str,
        job_name: str,
        template_spec_uri: str,
        worker_service_account: str,
        parameters: Mapping[str, str],
        labels: Mapping[str, str],
    ) -> str:
        body = {
            "launchParameter": {
                "jobName": job_name,
                "parameters": dict(parameters),
                "containerSpecGcsPath": template_spec_uri,
                "environment": {
                    "serviceAccountEmail": worker_service_account,
                    "tempLocation": self._temp_location,
                    "ipConfiguration": "WORKER_IP_PRIVATE",
                    "numWorkers": 1,
                    "maxWorkers": 2,
                    "additionalExperiments": [
                        "block_project_ssh_keys",
                        "enable_portable_runner",
                    ],
                    "additionalUserLabels": dict(labels),
                },
                "update": False,
            }
        }
        try:
            request = (
                self._service.projects()
                .locations()
                .flexTemplates()
                .launch(projectId=project, location=region, body=body)
            )
        except Exception:
            _fail("dataflow_request")
        response = self._execute(request)
        job = response.get("job")
        job_id = job.get("id") if isinstance(job, Mapping) else None
        if not isinstance(job_id, str) or not job_id:
            _fail("dataflow_response")
        return job_id

    def wait_for_terminal(self, *, project: str, region: str, job_id: str) -> str:
        started = self._monotonic()
        while True:
            if self._monotonic() - started > self._timeout:
                _fail("dataflow_timeout")
            try:
                request = (
                    self._service.projects()
                    .locations()
                    .jobs()
                    .get(
                        projectId=project,
                        location=region,
                        jobId=job_id,
                        view="JOB_VIEW_SUMMARY",
                    )
                )
            except Exception:
                _fail("dataflow_request")
            response = self._execute(request)
            state = response.get("currentState")
            if not isinstance(state, str):
                _fail("dataflow_response")
            if state in self._TERMINAL_STATES:
                return state
            self._sleep(self._poll_interval)


class BigQueryWarehouseGateway:
    """Read exact lineage counters with parameterized Standard SQL."""

    def __init__(self, client: Any, *, location: str) -> None:
        if client is None or not location:
            raise ValueError("BigQuery client and location are required")
        self._client = client
        self._location = location

    def observe_lineage(
        self,
        *,
        table_spec: str,
        run_id: str,
        source_id: str,
        output_digest: str,
    ) -> WarehouseObservation:
        del output_digest  # Deliberately observe every digest for this run/source.
        project, dataset, table = parse_table_spec(table_spec)
        sql = f"""
            SELECT
              COUNT(*) AS row_count,
              COUNT(DISTINCT _ztm_row_ordinal) AS distinct_ordinal_count,
              ARRAY_AGG(DISTINCT _ztm_plan_digest IGNORE NULLS) AS plan_digests,
              ARRAY_AGG(DISTINCT _ztm_output_digest IGNORE NULLS) AS output_digests,
              ARRAY_AGG(DISTINCT _ztm_bundle_digest IGNORE NULLS) AS bundle_digests
            FROM `{project}.{dataset}.{table}`
            WHERE _ztm_run_id = @run_id AND _ztm_source_id = @source_id
        """
        try:
            from google.cloud import bigquery

            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("run_id", "STRING", run_id),
                    bigquery.ScalarQueryParameter("source_id", "STRING", source_id),
                ],
                use_legacy_sql=False,
            )
            rows = list(
                self._client.query(
                    sql, job_config=job_config, location=self._location
                ).result()
            )
        except Exception:
            _fail("bigquery_query")
        if len(rows) != 1:
            _fail("bigquery_response")
        row = rows[0]
        try:
            return WarehouseObservation(
                row_count=int(row["row_count"]),
                distinct_ordinal_count=int(row["distinct_ordinal_count"]),
                plan_digests=frozenset(row["plan_digests"] or ()),
                output_digests=frozenset(row["output_digests"] or ()),
                bundle_digests=frozenset(row["bundle_digests"] or ()),
            )
        except Exception:
            _fail("bigquery_response")
