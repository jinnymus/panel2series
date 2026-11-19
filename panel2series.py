"""Export one numeric Grafana panel series and render it offline."""
import argparse
import base64
import json
import math
import os
import re
import sys
from urllib.error import HTTPError, URLError
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.sax.saxutils import escape


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(url, user, password, body=None, *, token=None):
    site = urlsplit(url)
    if site.scheme != "https" and not (site.scheme == "http" and site.hostname in ("127.0.0.1", "localhost")):
        raise ValueError("Use HTTPS for remote Grafana")
    auth = ("Bearer " + token if token else "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode())
    req = Request(url, headers={"Authorization": auth, "Content-Type": "application/json"},
                  data=None if body is None else json.dumps(body).encode())
    with build_opener(NoRedirect()).open(req, timeout=20) as response:
        return json.load(response)


def find_panel(panels, panel_id):
    for panel in panels:
        if panel.get("id") == panel_id:
            return panel
        nested = find_panel(panel.get("panels", []), panel_id)
        if nested is not None:
            return nested


def expand(text, variables):
    def replace(match):
        name = match.group(1) or match.group(2)
        value = variables.get(name)
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("Expected a simple scalar value for " + name)
        return value
    expanded = re.sub(r"\$\{(\w+)\}|\$(\w+)", replace, text)
    if "$" in expanded or "[[" in expanded:
        raise ValueError("Unsupported variable syntax")
    return expanded


def unpack(frames):
    series = []
    for frame in frames:
        fields = frame["schema"]["fields"]
        columns = frame["data"]["values"]
        times, = [columns[i] for i,f in enumerate(fields) if f["type"] == "time"]
        if any(frame["data"].get("entities", [])):
            raise ValueError("Non-finite frame")
        for i, field in enumerate(fields):
            if field["type"] == "number" and times:
                if len(times) != len(columns[i]):
                    raise ValueError("Inconsistent column lengths")
                series.append({"field":field["name"], "labels":field.get("labels", {}),
                               "points":list(zip(times, columns[i]))})
    return series


def read_dashboard(api, uid):
    uid = quote(uid, safe="")
    for version in ("v1", "v1beta1"):
        path = f"/apis/dashboard.grafana.app/{version}/namespaces/default/dashboards/{uid}"
        try:
            resource = api(path)
        except HTTPError as error:
            if error.code in (404, 405):
                continue
            raise
        return resource["spec"], version
    return api("/api/dashboards/uid/" + uid)["dashboard"], "legacy"


def export(args):
    if args.start >= args.end:
        raise ValueError("Expected start < end (Unix milliseconds)")
    if args.session:
        from sso_login import session_api
        with session_api(args.url,args.session) as api:
            return export_panel(args,api)
    def api(path, body=None):
        token = os.environ["GRAFANA_TOKEN"] if args.token else None
        if args.token and not token.strip():
            raise ValueError("GRAFANA_TOKEN is empty")
        return request(args.url.rstrip("/") + path, args.user,
                       None if args.token else os.environ["GRAFANA_PASSWORD"], body, token=token)
    return export_panel(args,api)


def export_panel(args, api):
    dashboard, dashboard_api = read_dashboard(api, args.uid)
    panel = find_panel(dashboard["panels"], args.panel)
    if not panel or not panel.get("targets") or panel.get("transformations"):
        raise ValueError("Expected a query panel without transformations")
    definitions = dashboard.get("templating", {}).get("list", [])
    variables = {v["name"]:v.get("current", {}).get("value") for v in definitions}
    for item in args.var:
        key, sep, value = item.partition("=")
        if not sep or key not in variables:
            raise ValueError("Expected --var declared_name=value")
        variables[key] = value
    if len(panel["targets"]) > 1 or "$" in json.dumps(panel["targets"]) or args.var:
        results = {}
        for saved in panel["targets"]:
            ref = saved["refId"]
            if ref in results:
                raise ValueError("Duplicate refId")
            if saved.get("hide"):
                results[ref] = {"status":"hidden"}
                continue
            try:
                target = dict(saved)
                target.setdefault("datasource", panel.get("datasource"))
                for key in ("expr", "query"):
                    if key in target:
                        target[key] = expand(target[key], variables)
                if "$" in json.dumps(target):
                    raise ValueError("Unsupported target variable")
                reply = api("/api/ds/query", {"from":str(args.start), "to":str(args.end), "queries":[target]})
                result = reply["results"][ref]
                if result.get("error"):
                    raise ValueError("Datasource rejected query")
                series = unpack(result.get("frames", []))
                if any(not args.start <= ts <= args.end for s in series for ts,_ in s["points"]):
                    raise ValueError("Point outside requested window")
                results[ref] = {"status":"ok" if series else "empty", "series":series}
            except (URLError, ValueError, KeyError, IndexError) as error:
                if isinstance(error, HTTPError) and error.code == 401:
                    raise
                results[ref] = {"status":"error", "reason":str(error)}
        return {"schema_version":2, "dashboard_api":dashboard_api, "dashboard":args.uid, "panel":args.panel, "title":panel["title"],
                "window_ms":[args.start,args.end], "variables":variables,"results":results,
                "unit":panel.get("fieldConfig", {}).get("defaults", {}).get("unit")}
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
    return {"schema_version": 1, "dashboard_api":dashboard_api, "dashboard": args.uid, "panel": args.panel, "title": panel["title"],
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
    e.add_argument("--var", action="append", default=[])
    auth = e.add_mutually_exclusive_group(required=True)
    auth.add_argument("--user")
    auth.add_argument("--session", type=Path, help="Reuse an interactive Grafana login")
    auth.add_argument("--token", action="store_true", help="Read service account token from GRAFANA_TOKEN")
    for name in ("url", "uid"):
        e.add_argument("--" + name, required=True)
    for name in ("panel", "start", "end"):
        e.add_argument("--" + name, required=True, type=int)
    c = commands.add_parser("chart")
    c.add_argument("--ref", default="A")
    c.add_argument("--series", type=int, default=0)
    c.add_argument("input", type=Path)
    for cmd in (c, e):
        cmd.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.cmd == "export":
        content = json.dumps(export(args), allow_nan=False, indent=2)
    else:
        data = json.loads(args.input.read_text())
        if data["schema_version"] == 2:
            data.update(data["results"][args.ref]["series"][args.series])
        content = chart(data)
    args.out.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except HTTPError as error:
        if error.code == 401:
            sys.exit("Grafana rejected authentication (HTTP 401). Check the credential and its expiration.")
        raise
