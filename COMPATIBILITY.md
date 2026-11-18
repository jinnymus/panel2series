# Grafana compatibility

The suite runs Grafana OSS with Basic authentication over HTTPS in the default organization. Each row is a specific Docker image tag. A pass covers both the single-series legacy bundle and the multi-query bundle. The exporter probes the stable dashboard resource endpoint, then the beta endpoint, then the classic dashboard endpoint. Only HTTP 404 and 405 trigger fallback. The selected adapter is recorded as `dashboard_api` in every JSON export.

| Grafana | Dashboard read adapter | Prometheus 3.15.1 | InfluxDB 1.8.10 (InfluxQL) |
|---|---|---|---|
| 10.4.19 | legacy | pass | pass |
| 11.5.2 | legacy | pass | pass |
| 12.0.0 | v1beta1 | pass | pass |
| 13.3.0 | v1 | pass | pass |

The legacy adapter reads `dashboard` from `/api/dashboards/uid/{uid}`. The resource adapters read classic panel definitions from `spec` under `/apis/dashboard.grafana.app/{version}/namespaces/default/dashboards/{uid}`. All rows use `POST /api/ds/query` for measurements.

## Reproduce

Run `bash integration/matrix.sh` from the repository root. Supply a fresh output directory as the first argument to retain per-version logs, JSON and SVG files at a known location. The runner checks the server-reported version and selected API, attempts each release and exits unsuccessfully if any row fails.

Every row uses a Viewer on a separate internal network. The test checks that the two backend TCP ports are unreachable, exports a top-level and nested panel for each source, overrides a scalar variable, compares timestamps, values and queue labels, and checks that invalid query B leaves A and C available. The chart command runs in a container with networking disabled.

## Coverage limits

The suite uses classic dashboards, the default namespace, one numeric series per successful query and literal UTC windows. Dashboard resource API versions and bundle schema versions are independent. Other patch releases, native dashboard schema v2 layouts, non-default organizations, Grafana Cloud, SSO, browser capture, Flux, multi-select variables and queries that depend on sibling refIds require separate acceptance tests.
