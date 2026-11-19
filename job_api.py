"""Local HTTP job service for numerical export and offline analysis."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from threading import BoundedSemaphore
from urllib.parse import urlsplit
from uuid import uuid4


HERE = Path(__file__).resolve().parent
JOB_ID = re.compile(r"[0-9a-f]{32}")
ARTIFACTS = {"export": ["series.json"], "analysis": ["analysis.json", "x.svg", "y.svg", "lag.svg"]}


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def require(condition, message):
    if not condition:
        raise ApiError(400, message)


def write_json(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, allow_nan=False), encoding="utf-8")
    tmp.replace(path)


class Jobs:
    def __init__(self, store, grafana):
        self.store = store.resolve()
        self.store.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.lock_file = (self.store / ".lock").open("a")
        fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.grafana = grafana
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.capacity = BoundedSemaphore(16)
        for path in self.store.glob("*/status.json"):
            if JOB_ID.fullmatch(path.parent.name):
                state = json.loads(path.read_bytes())
                if state["status"] in ("queued", "running"):
                    state.update(status="failed", error="Service restarted before job completion")
                    write_json(path, state)

    def status(self, job_id):
        if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
            raise ApiError(404, "Unknown job")
        try:
            return json.loads((self.store / job_id / "status.json").read_bytes())
        except FileNotFoundError:
            raise ApiError(404, "Unknown job") from None

    def submit(self, kind, body):
        require(isinstance(body, dict), "Expected a JSON object")
        if kind == "export":
            required = {"uid", "panel", "start", "end"}
            require(required <= body.keys() <= required | {"variables"}, "Invalid export keys")
            require(isinstance(body["uid"], str) and re.fullmatch(r"[A-Za-z0-9_-]+", body["uid"]),
                    "Invalid dashboard UID")
            require(all(type(body[k]) is int for k in ("panel", "start", "end"))
                    and body["panel"] > 0 and body["start"] < body["end"], "Invalid panel or window")
            variables = body.get("variables", {})
            require(isinstance(variables, dict) and all(re.fullmatch(r"\w+", k)
                    and isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_-]+", v)
                    for k, v in variables.items()), "Invalid variables")
        else:
            require(body.keys() == {"exports", "config"} and isinstance(body["config"], dict)
                    and isinstance(body["exports"], list) and len(body["exports"]) == 2,
                    "Expected two export IDs and an analysis config")
            config = body["config"]
            step, lag = config.get("step_ms"), config.get("max_lag_steps")
            require(type(step) is int and step > 0 and type(lag) is int and lag >= 0,
                    "Invalid grid step or lag limit")
            for ref in body["exports"]:
                record = self.status(ref)
                if record["kind"] != "export" or record["status"] != "succeeded":
                    raise ApiError(409, "Analysis requires completed export jobs")
                left, right = record["window_ms"]
                slots = (right - left) // step + 1
                require(slots <= 100000 and slots * (2 * lag + 1) <= 5000000
                        and lag <= 10000, "Analysis grid or lag search exceeds job limit")
        if not self.capacity.acquire(blocking=False):
            raise ApiError(429, "Job queue is full")
        try:
            job_id = uuid4().hex
            directory = self.store / job_id
            directory.mkdir(mode=0o700)
            state = {"id": job_id, "kind": kind, "status": "queued", "artifacts": []}
            if kind == "export":
                state["window_ms"] = [body["start"], body["end"]]
            write_json(directory / "status.json", state)
            self.pool.submit(self.run, directory, state.copy(), body)
            return state
        except BaseException:
            self.capacity.release()
            raise

    def run(self, directory, state, body):
        path = directory / "status.json"
        kind = state["kind"]
        try:
            state["status"] = "running"
            write_json(path, state)
            if kind == "export":
                cmd = [sys.executable, HERE / "panel2series.py", "export", "--token",
                       "--url", self.grafana, "--out", directory / "series.json"]
                cmd.extend(f"--{key}={body[key]}" for key in ("uid", "panel", "start", "end"))
                for key, value in body.get("variables", {}).items():
                    cmd.extend(["--var", f"{key}={value}"])
            else:
                write_json(directory / "config.json", body["config"])
                archives = [self.store / ref / "series.json" for ref in body["exports"]]
                cmd = [sys.executable, HERE / "offline_analysis.py", *archives,
                       "--config", directory / "config.json", "--out", directory]
            env = os.environ.copy()
            if kind == "analysis":
                env.pop("GRAFANA_TOKEN", None)
            result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=180)
            if result.returncode:
                detail = result.stderr.strip().splitlines()
                raise ValueError(detail[-1][:500] if detail else "Worker failed")
            state.update(status="succeeded", artifacts=ARTIFACTS[kind])
        except subprocess.TimeoutExpired:
            state.update(status="failed", error="Job exceeded 180 seconds")
        except Exception as exc:
            state.update(status="failed", error=str(exc)[:500])
        finally:
            try:
                write_json(path, state)
            finally:
                self.capacity.release()


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def reply(self, status, obj):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        try:
            if self.path not in ("/jobs/export", "/jobs/analysis"):
                raise ApiError(404, "Unknown route")
            if self.headers.get_content_type() != "application/json":
                raise ApiError(415, "Expected application/json")
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                raise ApiError(411, "Expected Content-Length") from None
            if not 0 < length <= 65536:
                raise ApiError(413, "Expected a body of 1 to 65536 bytes")
            try:
                body = json.loads(self.rfile.read(length))
            except (ValueError, RecursionError):
                raise ApiError(400, "Malformed JSON") from None
            state = self.server.jobs.submit(self.path.split("/")[-1], body)
            self.reply(HTTPStatus.ACCEPTED, state)
        except ApiError as exc:
            self.reply(exc.status, {"error": str(exc)})

    def do_GET(self):
        parts = self.path.split("/")
        try:
            if len(parts) not in (3, 5) or parts[1] != "jobs":
                raise ApiError(404, "Unknown route")
            state = self.server.jobs.status(parts[2])
            if len(parts) == 3:
                self.reply(200, state)
                return
            name = parts[4]
            if parts[3] != "artifacts" or name not in state["artifacts"]:
                raise ApiError(404, "Unknown artifact")
            with (self.server.jobs.store / state["id"] / name).open("rb") as src:
                self.send_response(200)
                self.send_header("Content-Type", "image/svg+xml" if name.endswith(".svg") else "application/json")
                self.send_header("Content-Disposition", f'attachment; filename="{name}"')
                self.send_header("Content-Length", str(os.fstat(src.fileno()).st_size))
                self.end_headers()
                shutil.copyfileobj(src, self.wfile)
        except ApiError as exc:
            self.reply(exc.status, {"error": str(exc)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grafana-url", required=True)
    parser.add_argument("--store", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1", help="Bind address within the trusted network")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not os.environ.get("GRAFANA_TOKEN", "").strip():
        parser.error("Set GRAFANA_TOKEN to a Grafana Viewer service account token")
    site = urlsplit(args.grafana_url)
    if not site.hostname or site.username or site.password or site.query or site.fragment or not (
            site.scheme == "https" or site.scheme == "http" and site.hostname in ("localhost", "127.0.0.1")):
        parser.error("Expected a Grafana HTTPS URL or local HTTP URL")
    with ThreadingHTTPServer((args.host, args.port), Handler) as server:
        server.jobs = Jobs(args.store, args.grafana_url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.jobs.pool.shutdown()
            server.jobs.lock_file.close()


if __name__ == "__main__":
    main()
