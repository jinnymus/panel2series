#!/usr/bin/env bash
set -eu
cd "$(dirname "$0")/.."
out=${1:-$(mktemp -d)}
mkdir -p "$out"
for version in 10.4.19 11.5.2 12.0.0 13.3.0; do
  GRAFANA_VERSION=$version BROWSER_CHECK=1 BROWSER_LOCATORS="${BROWSER_LOCATORS:-integration/browser-locators.yaml}" \
    "${PYTHON:-python3}" demo.py "$out/$version"
  echo "PASS $version: transformed CSV and PNG"
done
echo "Evidence: $out"
