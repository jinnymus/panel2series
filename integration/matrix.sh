#!/usr/bin/env bash
set -eu
cd "$(dirname "$0")"
out=${1:-$(mktemp -d)}
mkdir -p "$out"
out=$(cd "$out" && pwd)
failed=0
for pair in 10.4.19:legacy 11.5.2:legacy 12.0.0:v1beta1 13.3.0:v1; do
  version=${pair%:*}
  adapter=${pair#*:}
  if GRAFANA_VERSION="$version" bash run.sh "$out/$version" >"$out/$version.log" 2>&1 &&
    python3 - "$out/$version" "$adapter" <<'PY'
import json, sys
from pathlib import Path
for name in ("prometheus", "prometheus-multi", "influx", "influx-multi"):
    actual = json.loads((Path(sys.argv[1]) / (name+".json")).read_text())["dashboard_api"]
    if actual != sys.argv[2]:
        raise SystemExit(f"{name}: expected {sys.argv[2]}, got {actual}")
PY
  then
    echo "PASS $version $adapter"
  else
    echo "FAIL $version (see $out/$version.log)"
    failed=1
  fi
done
echo "Evidence: $out"
exit "$failed"
