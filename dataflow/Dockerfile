FROM gcr.io/dataflow-templates-base/python311-template-launcher-base:20260803-RC00 AS template_launcher
FROM apache/beam_python3.11_sdk:2.75.0

COPY --from=template_launcher /opt/google/dataflow/python_template_launcher /opt/google/dataflow/python_template_launcher

WORKDIR /template
COPY requirements-dataflow.txt /template/requirements-dataflow.txt
RUN pip install --no-cache-dir -r /template/requirements-dataflow.txt
RUN pip download --dest /tmp/dataflow-requirements-cache -r /template/requirements-dataflow.txt

COPY cloud_runtime /template/cloud_runtime
COPY control_plane /template/control_plane
ENV PYTHONPATH="/template"
ENV FLEX_TEMPLATE_PYTHON_PY_FILE="/template/cloud_runtime/dataflow_template.py"
ENV FLEX_TEMPLATE_PYTHON_REQUIREMENTS_FILE="/template/requirements-dataflow.txt"

RUN python -c "import cloud_runtime.dataflow_template" && pip check

ENTRYPOINT ["/opt/google/dataflow/python_template_launcher"]
