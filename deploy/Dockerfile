# docker build -f deploy/Dockerfile --build-arg HERMES_IMAGE=<hermes image> -t <registry>/noc-engineer .
ARG HERMES_IMAGE
FROM ${HERMES_IMAGE}
# OTLP export and the Langfuse SDK baked into the Python that runs `hermes` (not the system pip):
# the pod may not reach PyPI. Air-gapped build: --build-arg PIP_INDEX_URL=https://<mirror>/simple
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN HPY="$(head -1 "$(command -v hermes)" | sed 's/^#!//; s/^.*env //')" \
 && PKGS="opentelemetry-sdk opentelemetry-exporter-otlp-proto-http langfuse" \
 && { "$HPY" -m pip install --no-cache-dir --index-url "$PIP_INDEX_URL" $PKGS \
      || uv pip install --python "$HPY" --index-url "$PIP_INDEX_URL" $PKGS; } \
 && "$HPY" -c "import langfuse, opentelemetry.sdk"
COPY SOUL.md config.yaml distribution.yaml /opt/noc-engineer/
COPY skills /opt/noc-engineer/skills
COPY scripts /opt/noc-engineer/scripts
COPY cron /opt/noc-engineer/cron
COPY deploy/start.sh deploy/cron_settings.py deploy/e2e_check.py deploy/upgrade_settings.py deploy/settings-lock.yaml /opt/noc-engineer/
COPY evals/run_evals.py evals/cases.example.yaml /opt/noc-engineer/evals/
ENTRYPOINT ["/bin/sh", "/opt/noc-engineer/start.sh"]
