"""Submit two exports and their comparison, then build a portable HTML report."""
import argparse
import json
import math
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from report_builder import CHARTS, build


def request(url, payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    req = Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=30) as response:
            return response.read()
    except HTTPError as exc:
        raise ValueError(f"HTTP {exc.code} from {url}: {exc.read(2048).decode(errors='replace')}") from exc


def complete_job(api, kind, payload, timeout):
    job = json.loads(request(f"{api}/jobs/{kind}", payload))
    job_id = job["id"]
    url = f"{api}/jobs/{quote(job_id, safe='')}"
    deadline = time.monotonic() + timeout
    while job["status"] in ("queued", "running"):
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Job {job_id} exceeded {timeout:g}s; check {url}")
        job = json.loads(request(url))
        if job["status"] in ("queued", "running"):
            time.sleep(0.25)
    if job["status"] != "succeeded":
        raise ValueError(f"Job {job_id} ended with {job['status']}: {job.get('error', '')}")
    return job, url


def run(api, plan, out, timeout):
    if out.exists():
        raise ValueError(f"Choose a new report directory: {out}")
    if len(plan["exports"]) != 2:
        raise ValueError("Expected two export requests")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Expected a positive timeout")
    api = api.rstrip("/")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent) as scratch:
        bundle = Path(scratch) / "report"
        bundle.mkdir()
        ids = []
        for index, payload in enumerate(plan["exports"], 1):
            job, url = complete_job(api, "export", payload, timeout)
            ids.append(job["id"])
            (bundle / f"run{index}.json").write_bytes(request(url + "/artifacts/series.json"))
        job, url = complete_job(api, "analysis", {"exports": ids, "config": plan["config"]}, timeout)
        for filename in ("analysis.json", *CHARTS):
            (bundle / filename).write_bytes(request(f"{url}/artifacts/{filename}"))
        (bundle / "provenance.json").write_text(json.dumps({"exports": ids, "analysis": job["id"],
                                                          "plan": plan}, indent=2) + "\n")
        build(bundle)
        bundle.rename(out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", required=True, help="Base URL of the job API")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="New directory for the report bundle")
    parser.add_argument("--timeout", type=float, default=300, help="Job polling timeout in seconds")
    args = parser.parse_args()
    try:
        run(args.api, json.loads(args.plan.read_text()), args.out, args.timeout)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"Autoreport failed: {exc}\n")
    print(args.out / "index.html")
