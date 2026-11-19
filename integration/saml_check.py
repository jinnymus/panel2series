"""Exercise native Grafana Enterprise SAML on a disposable loopback instance."""
import argparse
import csv
import json
import os
import ipaddress
import socket
import shutil
import secrets
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
from urllib.error import HTTPError
from urllib.request import Request, build_opener
from xml.etree import ElementTree

from oidc_matrix import ROOT, docker, port, ready
from panel2series import NoRedirect, request
from playwright.sync_api import sync_playwright
from saml_idp import start_idp, verify_assertion
from sso_login import sign_in


def verify_session_flow(base, idp, out, scratch, args, checks):
    session = scratch / "viewer.json"
    def drive(page):
        page.wait_for_url(idp.idp_base + "/**", timeout=20000)
        page.locator("#username").fill("reader")
        page.locator("#password").fill(idp.password)
        page.locator("#kc-login").click()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=args.channel)
        sign_in(browser, base, session, drive=drive, provider="saml", timeout=45)
        browser.close()

    def authenticated(path):
        cookie = json.loads(session.read_text())["cookie"]
        req = Request(base + path, headers={"Cookie": cookie["name"] + "=" + cookie["value"]})
        with build_opener(NoRedirect()).open(req, timeout=10) as response:
            return json.load(response)

    user = authenticated("/api/user")
    roles = authenticated("/api/user/orgs")
    assert user["login"] == "reader" and not user["isGrafanaAdmin"]
    assert next(org["role"] for org in roles if org["orgId"] == user["orgId"]) == "Viewer"
    checks["viewer_login"] = "passed"
    expiry = time.monotonic() + 125
    target = ["--url", base, "--uid", "sample", "--panel", "1", "--start", "1704067200000",
              "--end", "1704067320000", "--session", str(session)]
    numeric = [sys.executable, ROOT / "panel2series.py", "export", *target]
    expected = [[1704067200000 + i * 60000, v] for i, v in enumerate([2, 7, 4])]
    for name, check in [("first", "export"), ("reuse", "session_reuse")]:
        path = out / f"{name}.json"
        subprocess.run([*numeric, "--out", path], check=True)
        assert json.loads(path.read_text())["points"] == expected
        checks[check] = "passed"
    capture = [sys.executable, ROOT / "browser_export.py", *target, "--out", out]
    if args.channel:
        capture.extend(["--channel", args.channel])
    subprocess.run(capture, check=True)
    with (out / "panel.csv").open(encoding="utf-8-sig", newline="") as file:
        assert [float(row["value"]) for row in csv.DictReader(file)] == [2, 7, 4]
    assert (out / "panel.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    checks["browser_export"] = "passed"
    time.sleep(max(0, expiry - time.monotonic()))
    try:
        authenticated("/api/user")
    except HTTPError as exc:
        assert exc.code == 401
        exc.close()
    else:
        raise AssertionError("Grafana accepted the expired cookie")
    expired = out / "expired.json"
    result = subprocess.run([*numeric, "--out", expired], capture_output=True, text=True)
    assert result.returncode and "session expired or invalid" in result.stderr and not expired.exists()
    checks["session_expiry"] = "passed"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path, help="New evidence directory")
    parser.add_argument("--port", type=int, help="Loopback port matching the test license")
    parser.add_argument("--license-file", type=Path)
    parser.add_argument("--tls-host", help="Licensed DNS name resolving to loopback on this workstation")
    parser.add_argument("--tls-cert", type=Path, help="Server PEM certificate trusted by Python and Chromium")
    parser.add_argument("--tls-key", type=Path)
    parser.add_argument("--channel")
    args = parser.parse_args()
    if args.license_file and not args.license_file.is_file():
        parser.error("License file does not exist")
    if any((args.tls_host, args.tls_cert, args.tls_key)):
        if not all((args.tls_host, args.tls_cert, args.tls_key)):
            parser.error("Supply --tls-host, --tls-cert and --tls-key together")
        if not all(ipaddress.ip_address(row[4][0]).is_loopback for row in
                   socket.getaddrinfo(args.tls_host, None)):
            parser.error("Test hostname must resolve only to loopback")
    args.out.mkdir(parents=True, exist_ok=False)
    checks = {key: "not run" for key in ("viewer_login", "export", "session_reuse",
                                         "browser_export", "session_expiry")}
    evidence = {"grafana_image": "grafana/grafana-enterprise:11.5.2", "checks": checks}
    try:
        gp = args.port or port()
        base = f"http://127.0.0.1:{gp}"
        if args.tls_host:
            base = f"https://{args.tls_host}" + (f":{gp}" if gp != 443 else "")
        with TemporaryDirectory() as tmp, ExitStack() as cleanup:
            scratch = Path(tmp)
            idp = cleanup.enter_context(start_idp(base))
            verify_assertion(idp, base, args.channel)
            evidence["keycloak_idp_issuance"] = "passed"
            (scratch / "idp.xml").write_bytes(idp.metadata)
            subprocess.run(["openssl", "req", "-new", "-x509", "-newkey", "rsa:2048", "-nodes",
                            "-days", "1", "-subj", "/CN=fixture", "-keyout", scratch/"sp.key",
                            "-out", scratch/"sp.crt"], stderr=subprocess.PIPE, check=True)
            admin = secrets.token_urlsafe()
            settings = {"SECURITY_ADMIN_PASSWORD": admin, "SERVER_ROOT_URL": base + "/",
                        "AUTH_LOGIN_MAXIMUM_LIFETIME_DURATION": "2m", "AUTH_SAML_ENABLED": "true",
                        "AUTH_SAML_ENTITY_ID": base + "/saml/metadata", "AUTH_SAML_ALLOW_SIGN_UP": "true",
                        "AUTH_SAML_ASSERTION_ATTRIBUTE_LOGIN": "login", "AUTH_SAML_ASSERTION_ATTRIBUTE_NAME": "login",
                        "AUTH_SAML_ASSERTION_ATTRIBUTE_EMAIL": "email", "AUTH_SAML_ASSERTION_ATTRIBUTE_ROLE": "role",
                        "AUTH_SAML_ROLE_VALUES_VIEWER": "Viewer", "AUTH_SAML_IDP_METADATA_PATH": "/fixture/idp.xml",
                        "AUTH_SAML_CERTIFICATE_PATH": "/fixture/sp.crt", "AUTH_SAML_PRIVATE_KEY_PATH": "/fixture/sp.key"}
            # Only individual files are mounted. Keep the saved session outside Grafana.
            mounts = []
            for name in ("sp.key", "sp.crt", "idp.xml"):
                (scratch / name).chmod(0o644)
                mounts += ["-v", f"{scratch/name}:/fixture/{name}:ro"]
            if args.license_file:
                private_copy = scratch / "license.jwt"
                shutil.copyfile(args.license_file, private_copy)
                private_copy.chmod(0o644)  # private temporary parent, readable by container UID
                mounts += ["-v", f"{private_copy}:/fixture/license.jwt:ro"]
                settings["ENTERPRISE_LICENSE_PATH"] = "/fixture/license.jwt"
            if args.tls_host:
                for source, name in [(args.tls_cert, "tls.crt"), (args.tls_key, "tls.key")]:
                    dest = scratch / name
                    shutil.copyfile(source, dest)
                    dest.chmod(0o644)
                    mounts += ["-v", f"{dest}:/fixture/{name}:ro"]
                settings.update(SERVER_PROTOCOL="https", SERVER_CERT_FILE="/fixture/tls.crt",
                                SERVER_CERT_KEY="/fixture/tls.key")
            env = {**os.environ, **{"GF_" + k: v for k, v in settings.items()}}
            cid = docker("run", "--rm", "-d", "-p", f"127.0.0.1:{gp}:3000", *mounts,
                         *[arg for k in settings for arg in ("-e", "GF_" + k)], evidence["grafana_image"], env=env)
            cleanup.callback(docker, "stop", cid)
            evidence["server_version"] = ready(base + "/api/health")["version"]
            assert evidence["server_version"] == "11.5.2"
            frontend = request(base+"/api/frontend/settings", "admin", admin)
            evidence["edition"] = frontend["buildInfo"]["edition"]
            evidence["saml_enabled"] = frontend.get("samlEnabled")
            evidence["valid_license"] = request(base+"/api/licensing/check", "admin", admin)
            evidence["image_id"] = docker("inspect", "--format", "{{.Image}}", cid)
            try:
                with build_opener(NoRedirect()).open(base + "/login/saml", timeout=10) as response:
                    evidence["saml_login_http"] = response.status
            except HTTPError as exc:
                evidence["saml_login_http"] = exc.code
                # Exclude the query string, which may contain a SAMLRequest.
                evidence["saml_login_redirect_path"] = urlsplit(exc.headers.get("Location", "")).path
                exc.close()
            try:
                with build_opener(NoRedirect()).open(base + "/saml/metadata", timeout=10) as response:
                    evidence["sp_metadata_http"] = response.status
                    metadata = ElementTree.fromstring(response.read())
            except HTTPError as exc:
                evidence["sp_metadata_http"] = exc.code
                exc.close()
                raise SystemExit("Grafana SAML metadata unavailable; see evidence.json")
            assert metadata.attrib["entityID"] == base + "/saml/metadata"
            assert any(el.attrib.get("Location") == base + "/saml/acs" for el in metadata.iter())
            ds = {"uid": "fixture", "type": "grafana-testdata-datasource"}
            request(base+"/api/datasources", "admin", admin, {**ds, "name":"Fixture", "access":"proxy"})
            target = {"refId":"A", "datasource":ds, "scenarioId":"csv_content",
                      "csvContent":"time,value\n2024-01-01T00:00:00Z,2\n2024-01-01T00:01:00Z,7\n2024-01-01T00:02:00Z,4"}
            panel = {"id":1, "type":"timeseries", "title":"Depth", "datasource":ds, "targets":[target],
                     "gridPos":{"x":0,"y":0,"w":12,"h":8}}
            request(base+"/api/dashboards/db", "admin", admin,
                    {"dashboard":{"uid":"sample","title":"Sample","schemaVersion":39,"panels":[panel]}})
            verify_session_flow(base, idp, args.out, scratch, args, checks)
    finally:
        (args.out / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")

if __name__ == "__main__":
    main()
