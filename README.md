# Panel2Series

Export a numeric Grafana panel through its query API and draw an SVG from the saved JSON offline. Python 3.9+ standard library. Docker is needed only for the demo.

## Reproduce the Viewer check

    python3 demo.py example
    python3 panel2series.py chart example/series.json --out example/chart.svg

The demo starts Grafana 11.5.2 on a random loopback port. A setup account provisions the TestData source, dashboard and reader. The demo checks the reader's Viewer role, runs the exporter with that user's credentials and verifies all three timestamps and values (2, 7, 4). It removes the container before rendering the chart. Use a fresh output directory to preserve existing files.

## Export from an existing instance

Supply GRAFANA_PASSWORD through the environment. The account needs Basic authentication, dashboard read and datasource query access.

    python3 panel2series.py export --url https://grafana.example.org --user reader --uid demo --panel 1 --start 1704067200000 --end 1704067320000 --out series.json
    python3 panel2series.py chart series.json --out chart.svg

Time boundaries and point timestamps are Unix milliseconds. Schema version 1 contains the requested window, dashboard and panel identifiers, query refId, title, labels, configured panel unit and timestamp/value pairs. A null value breaks the line.

Validated scope: Grafana 11.5.2, TestData CSV Content, one top-level panel with one time column and one numeric column, Basic authentication. The first slice handles static query targets. See [the roadmap](PLAN.md) for additional sources, versions, variable resolution and SSO.

## Prometheus and InfluxDB integration check

Run `bash integration/run.sh` with Docker Compose, Python 3 and OpenSSL supporting `req -addext`. Pass an output directory as the first argument to keep the generated JSON and SVG elsewhere.

The fixture imports three samples into Prometheus v3.15.1 and inserts a distinct series into InfluxDB 1.8.10. Grafana 11.5.2 joins two internal networks. The exporter joins only the frontend network and authenticates over HTTPS as a Viewer. The test probes both backend IPs from the client network, compares every timestamp and value, and runs each SVG render in a container with networking disabled. The InfluxQL fixture uses a fixed UTC window. All ports remain unpublished and the temporary stack is removed on exit.
## Nested panels and independent queries

Panel IDs are resolved recursively inside classic row panels. Supply repeated `--var name=value` options to override saved dashboard selections. The supported forms in PromQL and raw InfluxQL are `$name` and `${name}`. This implementation accepts simple scalar identifiers (ASCII letters, digits, underscore and hyphen). Multi-select, All expansion, format modifiers, query-time variable discovery and Grafana built-ins are outside this profile.

For multiple independent targets or templated exports, schema version 2 records the selected variables and one result per refId. Each numeric field keeps its labels and time/value points. The statuses are ok, empty, hidden and error. Inspect the statuses even when the export command succeeds. Server-side expressions depending on sibling refIds require batched execution and are outside this profile.

Run the integration check below to exercise a collapsed row in each datasource. It overrides the saved queue from other to demo, verifies the queue label, checks a failing query B between successful queries A and C, and renders C offline. To redraw a series:

    python3 panel2series.py chart example/stores/influx-multi.json --ref C --series 0 --out /tmp/influx-c.svg
