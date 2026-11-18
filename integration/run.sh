#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p "${1:-../example/stores}"
export RESULT_DIR="$(cd "${1:-../example/stores}" && pwd)"
scratch="$(mktemp -d)"
export TLS_DIR="$scratch/tls"
mkdir -m 755 "$TLS_DIR"
export ADMIN_PASSWORD="$(openssl rand -hex 24)" VIEWER_PASSWORD="$(openssl rand -hex 24)"
export COMPOSE_PROJECT_NAME="p2s-$(openssl rand -hex 5)"
dc() { docker compose -f compose.yaml "$@"; }
cleanup() {
  dc down -v >/dev/null
  rm -f "$TLS_DIR/key.pem" "$TLS_DIR/cert.pem"
  rmdir "$TLS_DIR" "$scratch"
}
trap cleanup EXIT
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=grafana -addext subjectAltName=DNS:grafana -keyout "$TLS_DIR/key.pem" -out "$TLS_DIR/cert.pem" 2>/dev/null
chmod 644 "$TLS_DIR/key.pem"
dc up -d grafana prometheus influx
for i in {1..60}; do
  if dc exec -T influx influx -execute 'CREATE DATABASE demo' >/dev/null 2>&1; then break; fi
  sleep 1
done
dc exec -T influx influx -database demo -execute 'INSERT depth value=3 1704067200000000000'
dc exec -T influx influx -database demo -execute 'INSERT depth value=9 1704067260000000000'
dc exec -T influx influx -database demo -execute 'INSERT depth value=5 1704067320000000000'
dc run --rm -e ADMIN_PASSWORD client check.py setup
ip() { docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$(dc ps -q "$1")"; }
dc run --rm client check.py viewer "$(ip prometheus)" "$(ip influx)"
i=0
for source in prometheus influx; do
  i=$((i+1))
  dc run --rm client panel2series.py export --url https://grafana:3000 --user reader --uid stores --panel "$i" --start 1704067200000 --end 1704067320000 --out "/out/$source.json"
done
python3 - "$RESULT_DIR" <<'PY'
import json, sys
from pathlib import Path
for source, values in [('prometheus',[2,7,4]),('influx',[3,9,5])]:
    data = json.loads((Path(sys.argv[1]) / (source+'.json')).read_text())
    expected = [[1704067200000+60000*i,v] for i,v in enumerate(values)]
    if data['points'] != expected:
        raise ValueError((source, expected, data['points']))
PY
for source in prometheus influx; do
  docker run --rm --network none -v "$PWD/../panel2series.py:/app.py:ro" -v "$RESULT_DIR:/out" python:3.10-slim python /app.py chart "/out/$source.json" --out "/out/$source.svg"
done
