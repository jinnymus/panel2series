"""Export one numeric Grafana panel series and render it offline."""
import argparse
import base64
import json
import math
import os
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.sax.saxutils import escape


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(url, user, password, body=None):
    if urlsplit(url).scheme != "https" and urlsplit(url).hostname not in ("127.0.0.1", "localhost"):
        raise ValueError("Use HTTPS for remote Grafana")
    auth = base64.b64encode(f"{user}:{password}".encode()).decode()
    req = Request(url, headers={"Authorization": "Basic " + auth, "Content-Type": "application/json"},
                  data=None if body is None else json.dumps(body).encode())
    with build_opener(NoRedirect()).open(req, timeout=20) as response:
        return json.load(response)


def export(args):
    if args.start >= args.end:
        raise ValueError("Expected start < end (Unix milliseconds)")
    def api(path, body=None):
        return request(args.url.rstrip("/") + path, args.user, os.environ["GRAFANA_PASSWORD"], body)
    dashboard = api("/api/dashboards/uid/" + quote(args.uid, safe=""))["dashboard"]
    panel = next((p for p in dashboard["panels"] if p["id"] == args.panel), None)
    if not panel or len(panel.get("targets", [])) != 1 or panel.get("transformations"):
        raise ValueError("Expected a top-level single-query panel without transformations")
    target = dict(panel["targets"][0])
    target.setdefault("datasource", panel.get("datasource"))
    if "$" in json.dumps(target) or target.get("hide"):
        raise ValueError("Hidden or templated targets are unsupported")
    reply = api("/api/ds/query", {"from": str(args.start), "to": str(args.end), "queries": [target]})
    result = reply["results"][target["refId"]]
    if result.get("error") or len(result.get("frames", [])) != 1:
        raise ValueError("Expected one successful frame")
    frame = result["frames"][0]
    fields = frame["schema"]["fields"]
    def col(kind):
        indices = [i for i, field in enumerate(fields) if field["type"] == kind]
        if len(indices) != 1:
            raise ValueError("Expected exactly one " + kind + " column")
        return indices[0]
    t, v = col("time"), col("number")
    times, values = [frame["data"]["values"][i] for i in (t, v)]
    if not times or len(times) != len(values) or any(frame["data"].get("entities", [])):
        raise ValueError("Empty, inconsistent or non-finite frame")
    points = list(zip(times, values))
    if any(not args.start <= ts <= args.end for ts in times):
        raise ValueError("Source returned points outside requested window")
    return {"schema_version": 1, "dashboard": args.uid, "panel": args.panel, "title": panel["title"],
            "refId": target["refId"], "window_ms": [args.start, args.end], "labels": fields[v].get("labels", {}),
            "unit": panel.get("fieldConfig", {}).get("defaults", {}).get("unit"), "points": points}


def chart(data):
    points = data["points"]
    values = [y for _, y in points if y is not None]
    if not values or not all(math.isfinite(y) for y in values):
        raise ValueError("Expected finite observations")
    lo, hi = min(values), max(values)
    start, end = data["window_ms"]
    lines, dots, move = [], [], True
    for ts, y in points:
        if y is None:
            move = True
            continue
        x = 80 + 660 * (ts-start)/(end-start)
        h = 210 - 150*(y-lo)/(hi-lo) if hi != lo else 135
        lines.append(f'{"M" if move else "L"}{x:.2f} {h:.2f}')
        dots.append(f'<circle cx="{x}" cy="{h}" r="3" fill="steelblue"/>')
        move = False
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 260"><rect width="800" height="260" fill="white"/>'
            f'<text x="80" y="30">{escape(data["title"])}</text><text x="5" y="63">{hi:g}</text>'
            f'<text x="5" y="213">{lo:g}</text><text x="80" y="245">0 s</text>'
            f'<text x="700" y="245">{(end-start)/1000:g} s</text>'
            f'<path d="{" ".join(lines)}" fill="none" stroke="steelblue"/>{"".join(dots)}</svg>')


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="cmd", required=True)
    e = commands.add_parser("export")
    for name in ("url", "user", "uid"):
        e.add_argument("--" + name, required=True)
    for name in ("panel", "start", "end"):
        e.add_argument("--" + name, required=True, type=int)
    c = commands.add_parser("chart")
    c.add_argument("input", type=Path)
    for cmd in (c, e):
        cmd.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    content = json.dumps(export(args), allow_nan=False, indent=2) if args.cmd == "export" else chart(json.loads(args.input.read_text()))
    args.out.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
