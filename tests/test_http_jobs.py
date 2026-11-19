"""Exercise the public HTTP contract with a Grafana double that rejects its token."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from job_api import Jobs
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


class RejectToken(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_error(401)

    def log_message(self, *args):
        pass


class JobContractTest(unittest.TestCase):
    def setUp(self):
        upstream = HTTPServer(("127.0.0.1", 0), RejectToken)
        threading.Thread(target=upstream.serve_forever, daemon=True).start()
        self.addCleanup(upstream.server_close)
        self.addCleanup(upstream.shutdown)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.base = f"http://127.0.0.1:{port}"
        store = tempfile.TemporaryDirectory()
        self.addCleanup(store.cleanup)
        server = subprocess.Popen(
            [sys.executable, str(ROOT / "job_api.py"), "--grafana-url",
             f"http://127.0.0.1:{upstream.server_port}", "--port", str(port),
             "--store", store.name], env={**os.environ, "GRAFANA_TOKEN": "test-value"},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(server.wait, 10)
        self.addCleanup(server.terminate)
        for _ in range(100):
            if server.poll() is not None:
                self.fail("HTTP service failed to start")
            try:
                self.call("/unknown")
            except HTTPError as exc:
                exc.close()
                return
            except URLError:
                time.sleep(.05)
        self.fail("HTTP service did not become ready")

    def call(self, path, data=None):
        req = Request(self.base + path,
                      data=None if data is None else json.dumps(data).encode(),
                      headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=5) as response:
            return response.status, json.load(response)

    def test_rejected_token_fails_job_without_publishing_artifacts(self):
        status, job = self.call("/jobs/export", dict(uid="demo", panel=1, start=1, end=1001))
        self.assertEqual(status, 202)
        path = "/jobs/" + job["id"]
        for _ in range(100):
            _, result = self.call(path)
            if result["status"] == "failed":
                break
            time.sleep(.05)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["artifacts"], [])
        self.assertNotIn("test-value", json.dumps(result))
        with self.assertRaises(HTTPError) as caught:
            self.call(path + "/artifacts/series.json")
        caught.exception.close()

    def test_invalid_window(self):
        with self.assertRaises(HTTPError) as caught:
            self.call("/jobs/export", dict(uid="demo", panel=1, start=2, end=1))
        caught.exception.close()
        self.assertEqual(caught.exception.code, 400)

class RecoveryTest(unittest.TestCase):
    def test_restart_retains_completed_and_marks_interrupted_jobs_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            ids = {}
            for i, status in enumerate(("queued", "running", "succeeded")):
                job_id = f"{i:032x}"
                ids[status] = job_id
                directory = store / job_id
                directory.mkdir()
                artifacts = ["series.json"] if status == "succeeded" else []
                state = dict(id=job_id, kind="export", status=status, artifacts=artifacts)
                (directory / "status.json").write_text(json.dumps(state))
            jobs = Jobs(store, "http://localhost")
            try:
                for status in ("queued", "running"):
                    self.assertEqual(jobs.status(ids[status])["status"], "failed")
                self.assertEqual(jobs.status(ids["succeeded"])["artifacts"], ["series.json"])
            finally:
                jobs.pool.shutdown()
                jobs.lock_file.close()
