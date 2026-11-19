#!/usr/bin/env bash
# Reproduce the release smoke checks and retain the exported evidence.
set -euo pipefail

if (( $# > 1 )); then
  echo "Usage: $0 [new-output-directory]" >&2
  exit 2
fi
if (( $# == 1 )); then
  mkdir -- "$1"
  out=$(cd -- "$1" && pwd)
else
  out=$(mktemp -d "${TMPDIR:-/tmp}/panel2series-quickstart.XXXXXXXX")
fi
echo "Quickstart results: $out"
cd "$(dirname "$0")/.."

BROWSER_CHECK=0 python3 demo.py "$out/viewer"
python3 offline_analysis.py example/analysis/run1.json example/analysis/run2.json \
  --config example/analysis/config.json --out "$out/known-lag"
python3 example/reporting/report_builder.py "$out/known-lag"
python3 - "$out" <<'PY'
import json
import sys
from pathlib import Path
from xml.etree.ElementTree import parse

root = Path(sys.argv[1])
report = root / "known-lag"
analysis = json.loads((report / "analysis.json").read_text())
for run in analysis["runs"]:
    lag = run["lag"]
    if lag["status"] != "ok" or lag["lag_ms"] != 4000 or lag["pairs"] != 53:
        raise SystemExit(f"Unexpected known-lag result: {lag}")
for path in [root / "viewer" / "chart.svg", *(report / f"{key}.svg" for key in ("x", "y", "lag"))]:
    if parse(path).getroot().tag != "{http://www.w3.org/2000/svg}svg":
        raise SystemExit(f"Invalid SVG: {path}")
if 'src="lag.svg"' not in (report / "index.html").read_text():
    raise SystemExit("Offline report is missing the lag chart")
print("Verified +4000 ms on 53 observed pairs in both runs and the offline report.")
PY
CHECK_HTTP_API=1 bash integration/run.sh "$out/stores"
echo "Viewer HTTP autoreport: $out/stores/http/index.html"
