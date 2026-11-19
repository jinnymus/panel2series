# Building and scheduling a report

The standalone builder consumes a directory containing `analysis.json`, `x.svg`, `y.svg` and `lag.svg`. Try it with the bundled offline example:

```sh
mkdir -p /tmp/panel2series-offline
cp example/analysis/report/* /tmp/panel2series-offline/
python3 example/reporting/report_builder.py /tmp/panel2series-offline
```

Open `index.html` in that directory. Share the directory as a unit to preserve its chart and data links. An existing report builder can read the stage statistics, lag status, sample counts and run differences directly from the same JSON file.

For unattended runs, start the job API and give the report process its base URL. `stores.json` requests two adjacent one-minute windows of the integration fixture's Prometheus panel and compares the two samples in each window. The shared endpoint appears in both windows. With two samples per run, the lag status is `insufficient`. For production runs, set the dashboard UID, panel ID, absolute window boundaries, metric selectors and stages for the two measurements.

```sh
python3 example/reporting/autoreport.py --api http://127.0.0.1:8765 \
  --plan example/reporting/stores.json --out /tmp/panel2series-report-001
```

A scheduler can invoke the same command after each pair of completed runs. Supply the plan with their measured timestamps and a fresh output directory for each invocation. The command exits successfully after publishing the completed directory. The bundle contains both raw exports, numerical analysis, SVGs, HTML and the submitted plan with job IDs in `provenance.json`. The API owns the Grafana Viewer credential. The report process only needs access to the job API. A polling timeout includes the job URL for checking its final state.
