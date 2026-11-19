# Called by run.sh after provisioning the isolated data sources and checking the Viewer.
(
  set -euo pipefail
  GRAFANA_TOKEN=$(dc run --rm -e ADMIN_PASSWORD client check.py ci-token)
  export GRAFANA_TOKEN
  server=$(dc run --rm -d -e GRAFANA_TOKEN -e GRAFANA_PASSWORD= \
    -v "$PWD/..:/repo:ro" client /repo/job_api.py \
    --grafana-url https://grafana:3000 --port 8787 --store /tmp/panel2series-jobs)
  trap 'docker rm -f "$server" >/dev/null 2>&1 || true' EXIT
  # Share the loopback interface with the service. This fresh client receives no Grafana credentials.
  docker run --rm --network "container:$server" -v "$PWD/..:/repo:ro" \
    -v "$RESULT_DIR:/out" python:3.10-slim python -B /repo/integration/http_check.py /out/http
)
