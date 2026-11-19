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

## Authentication

The Prometheus/InfluxDB matrix above also passed with Viewer service-account tokens on all eight combinations, including partial query failure, offline rendering and network isolation.

The OIDC suite uses Keycloak 26.2.5, the password and TOTP browser flow, a Grafana Viewer and the bundled TestData source. On each release the SSO request context and the CI bearer token produced identical JSON, including timestamps and the reference values 2, 7 and 4. Two browser processes reused the saved Grafana login and produced matching CSV plus PNG files. The fixture exercises the actual IdP forms with headless Chrome; the interactive login command opens a visible browser.

| Grafana OSS | OIDC + TOTP and browser export | Saved session reuse | Expired login cookie | Viewer CI token export | Expired CI token |
|---|---|---|---|---|---|
| 10.4.19 | pass | pass | HTTP 401 | pass | HTTP 401 |
| 11.5.2 | pass | pass | HTTP 401 | pass | HTTP 401 |
| 12.0.0 | pass | pass | HTTP 401 | pass | HTTP 401 |
| 13.3.0 | pass | pass | HTTP 401 | pass | HTTP 401 |

The expiry check presents the original credential after Grafana's configured lifetime. It covers Grafana login expiration and service-account token expiration. IdP single logout, refresh-token rotation, SAML, hardware keys and other IdPs are outside this matrix. The OIDC fixture uses loopback browser endpoints and a Docker back channel. See [setup and reproduction](AUTH.md).

## Coverage limits

The separate [browser suite](BROWSER.md) passed on 10.4.19, 11.5.2, 12.0.0 and 13.3.0 under Viewer with Chrome, the TestData source and a calculated field. It checked a solo PNG and native CSV with the original and doubled values. Versions 10–12 open the Data Inspector by URL. Version 13.3.0 opens the panel menu and selects Inspect, then Data. Browser results apply to this fixture independently of the Prometheus/InfluxDB API matrix.

The API suite uses classic dashboards, the default namespace, one numeric series per successful query and literal UTC windows. Dashboard resource API versions and bundle schema versions are independent. Other patch releases, native dashboard schema v2 layouts, non-default organizations, Grafana Cloud, Flux, multi-select variables and queries that depend on sibling refIds require separate acceptance tests.

## HTTP jobs and automated reports

The Viewer-token HTTP flow passed on Grafana OSS 10.4.19, 11.5.2, 12.0.0 and 13.3.0 with Prometheus 3.15.1 and InfluxDB 1.8.10. Each run submitted two numeric exports and one comparison, polled their status, downloaded the artifacts and built an offline HTML report. Both sources used the same reference window. The integration check reconciled points and labels, preserved the partial query failure, and verified the mean changes and chart references. Reproduce all four releases with `CHECK_HTTP_API=1 bash integration/matrix.sh /tmp/new-http-matrix`. See the [HTTP API guide](HTTP_API.md).

## Single query returning several series

The TestData Viewer demo checks a plain single-target panel returning two numeric fields. On Grafana 10.4.19, 11.5.2, 12.0.0 and 13.3.0 the export contained both fields (left and right) and all six reference measurements. The existing one-field panel produced a flat v1 archive. The multi-frame case with per-host labels, different field units and a null sample is covered by a Python regression test. Long-form string dimensions are explicitly rejected. Reproduce the real wide-frame case with `GRAFANA_VERSION=13.3.0 python3 demo.py /tmp/new-viewer-demo`.
