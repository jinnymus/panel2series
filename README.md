# Panel2Series

For a human Viewer using OIDC and MFA, or a CI job using a Grafana service account, see [Authentication](AUTH.md).

See [Browser export](BROWSER.md) for transformed panel CSV, PNG, locator overrides and the browser test matrix.

Export a numeric Grafana panel through its query API and draw an SVG from the saved JSON offline. Python 3.9+ standard library. Local charting and analysis run without Docker. The integration fixtures use Docker.

## Quickstart

From the checkout run:

    bash integration/quickstart.sh

Requires Python 3, Docker with Compose, and OpenSSL with `req -addext`. The script creates a new output directory and prints its path. Open `stores/http/index.html` for the report built from Viewer HTTP exports, `viewer/chart.svg` for the offline chart, and `known-lag/index.html` for a comparison with a verified four-second delay. For an installation with existing Grafana access see [authentication](AUTH.md). For troubleshooting use the [runbook](RUNBOOK.md).

## Reproduce the Viewer check

    out=$(mktemp -d)
    python3 demo.py "$out"
    python3 panel2series.py chart "$out/series.json" --out "$out/chart.svg"

The demo starts Grafana 11.5.2 on a random loopback port. A setup account provisions the TestData source, dashboard and reader. The demo checks the reader's Viewer role, runs the exporter with that user's credentials and verifies all three timestamps and values (2, 7, 4). It removes the container before rendering the chart. Use a fresh output directory to preserve existing files.

## Export from an existing instance

Supply GRAFANA_PASSWORD through the environment. The account needs Basic authentication, dashboard read and datasource query access.

    python3 panel2series.py export --url https://grafana.example.org --user reader --uid demo --panel 1 --start 1704067200000 --end 1704067320000 --out series.json
    python3 panel2series.py chart series.json --out chart.svg

Time boundaries and point timestamps are Unix milliseconds. Schema version 1 contains the requested window, dashboard and panel identifiers, query refId, title, labels, configured panel unit and timestamp/value pairs. A null value breaks the line.

The quickstart uses TestData CSV Content on Grafana 11.5.2. The [compatibility matrix](COMPATIBILITY.md) covers the separate Prometheus and InfluxDB suite. See [the roadmap](PLAN.md) for planned work.

## Prometheus and InfluxDB integration check

Run `bash integration/run.sh` with Docker Compose, Python 3 and OpenSSL supporting `req -addext`. Pass an output directory as the first argument to keep the generated JSON and SVG elsewhere.

The fixture imports three samples into Prometheus v3.15.1 and inserts a distinct series into InfluxDB 1.8.10. Grafana 11.5.2 joins two internal networks. The exporter joins only the frontend network and authenticates over HTTPS as a Viewer. The test probes both backend IPs from the client network, compares every timestamp and value, and runs each SVG render in a container with networking disabled. The InfluxQL fixture uses a fixed UTC window. All ports remain unpublished and the temporary stack is removed on exit.
## Nested panels and independent queries

Panel IDs are resolved recursively inside classic row panels. Supply repeated `--var name=value` options to override saved dashboard selections. The supported forms in PromQL and raw InfluxQL are `$name` and `${name}`. This implementation accepts simple scalar identifiers (ASCII letters, digits, underscore and hyphen). Multi-select, All expansion, format modifiers, query-time variable discovery and Grafana built-ins are outside this profile.

For a single query returning several numeric fields or frames, multiple independent targets, or templated exports, schema version 2 records the selected variables and one result per refId. Each numeric field keeps its name, labels, unit and time/value points. The unit comes from the returned field configuration or the panel default. A plain single-series export retains the flat v1 layout. Older archives may omit field metadata. Long-form frames with string dimension columns require conversion to wide or multi-frame form at the source. The statuses are ok, empty, hidden and error. Inspect the statuses even when the export command succeeds. Server-side expressions depending on sibling refIds require batched execution and are outside this profile.

Run the integration check below to exercise a collapsed row in each datasource. It overrides the saved queue from other to demo, verifies the queue label, checks a failing query B between successful queries A and C, and renders C offline. To redraw a series:

    python3 panel2series.py chart example/stores/influx-multi.json --ref C --series 0 --out /tmp/influx-c.svg

[Офлайн-анализ двух прогонов, ступеней, пропусков и лага](ANALYSIS.md)

[HTTP API заданий, report builder и авторепорт](HTTP_API.md)
