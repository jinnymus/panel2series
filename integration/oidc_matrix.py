"""Disposable Keycloak password + TOTP / Grafana Viewer end-to-end test."""
import argparse
import csv
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import socket
import struct
import subprocess
import sys
import time
from contextlib import ExitStack
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from panel2series import request
from sso_login import sign_in
from playwright.sync_api import sync_playwright


def docker(*args, env=None):
    return subprocess.check_output(["docker",*args],env=env,text=True).strip()


def port():
    with socket.socket() as s:
        s.bind(("127.0.0.1",0))
        return s.getsockname()[1]


def ready(url):
    for _ in range(100):
        try:
            with urlopen(url,timeout=2) as response:
                return json.load(response)
        except (URLError,OSError):
            time.sleep(1)
    raise RuntimeError("Timed out waiting for "+url)


def otp(secret):
    digest = hmac.new(secret.encode(),struct.pack(">Q",int(time.time())//30),hashlib.sha1).digest()
    offset = digest[-1] & 15
    return f"{(int.from_bytes(digest[offset:offset+4],'big') & 0x7fffffff)%1000000:06d}"


def realm(callbacks, password, seed, client_secret):
    return {"realm":"test","enabled":True,"sslRequired":"none",
            "clients":[{"clientId":"panel","secret":client_secret,"protocol":"openid-connect",
                        "standardFlowEnabled":True,"redirectUris":callbacks}],
            "users":[{"username":"reader","enabled":True,"emailVerified":True,"email":"reader@example.test",
                      "firstName":"Test","lastName":"Reader","credentials":[
                          {"type":"password","value":password,"temporary":False},
                          {"type":"otp","secretData":json.dumps({"value":seed}),
                           "credentialData":json.dumps({"subType":"totp","digits":6,"period":30,"algorithm":"HmacSHA1","counter":0})}]}]}


def verify(version, graf_port, network, issuer, client_secret, password, seed, out, tmp, channel):
    url = f"http://127.0.0.1:{graf_port}"
    admin = secrets.token_urlsafe()
    backend = "http://idp:8080/realms/test/protocol/openid-connect/"
    settings = {"SECURITY_ADMIN_PASSWORD":admin,"SERVER_ROOT_URL":url,"AUTH_GENERIC_OAUTH_ENABLED":"true",
                "AUTH_GENERIC_OAUTH_CLIENT_ID":"panel","AUTH_GENERIC_OAUTH_CLIENT_SECRET":client_secret,
                "AUTH_GENERIC_OAUTH_SCOPES":"openid profile email","AUTH_GENERIC_OAUTH_AUTH_URL":issuer+"/auth",
                "AUTH_GENERIC_OAUTH_TOKEN_URL":backend+"token","AUTH_GENERIC_OAUTH_API_URL":backend+"userinfo",
                "AUTH_GENERIC_OAUTH_JWK_SET_URL":backend+"certs","AUTH_GENERIC_OAUTH_VALIDATE_ID_TOKEN":"true",
                "AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_PATH":"'Viewer'","AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_STRICT":"true",
                "AUTH_LOGIN_MAXIMUM_LIFETIME_DURATION":"2m"}
    env = {**os.environ,**{"GF_"+k:v for k,v in settings.items()}}
    with ExitStack() as stack:
        cid = docker("run","--rm","-d","--network",network,"-p",f"127.0.0.1:{graf_port}:3000",
                     *[arg for k in settings for arg in ("-e","GF_"+k)],"grafana/grafana:"+version,env=env)
        stack.callback(docker,"stop",cid)
        assert ready(url+"/api/health")["version"] == version
        def setup(path,body):
            return request(url+path,"admin",admin,body)
        ds = {"uid":"fixture","type":"grafana-testdata-datasource"}
        setup("/api/datasources",{**ds,"name":"Fixture","access":"proxy"})
        panel = {"id":1,"type":"timeseries","title":"Depth","datasource":ds,"gridPos":{"x":0,"y":0,"w":12,"h":8},
                 "targets":[{"refId":"A","datasource":ds,"scenarioId":"csv_content",
                             "csvContent":"time,value\n2024-01-01T00:00:00Z,2\n2024-01-01T00:01:00Z,7\n2024-01-01T00:02:00Z,4"}]}
        setup("/api/dashboards/db",{"dashboard":{"uid":"sample","title":"Sample","schemaVersion":39,"panels":[panel]}})
        sa = setup("/api/serviceaccounts",{"name":"ci","role":"Viewer"})
        assert sa["role"] == "Viewer"
        token = setup(f"/api/serviceaccounts/{sa['id']}/tokens",{"name":"test","secondsToLive":25})["key"]
        out.mkdir(parents=True,exist_ok=True)
        args = ["--url",url,"--uid","sample","--panel","1","--start","1704067200000","--end","1704067320000"]
        token_cmd = [sys.executable,str(ROOT/"panel2series.py"),"export","--token",*args,"--out",str(out/"ci.json")]
        subprocess.run(token_cmd,env={**os.environ,"GRAFANA_TOKEN":token},check=True)
        expected = [[1704067200000+i*60000,v] for i,v in enumerate((2,7,4))]
        assert json.loads((out/"ci.json").read_text())["points"] == expected
        session = tmp/("session-"+version)
        def factors(page):
            page.locator("#username").fill("reader")
            page.locator("#password").fill(password)
            page.locator("#kc-login").click()
            page.locator("#otp").fill("invalid")
            page.locator("#kc-login").click()
            page.locator("#otp").wait_for()
            assert not any(c["name"]=="grafana_session" for c in page.context.cookies(url))
            page.locator("#otp").fill(otp(seed))
            page.locator("#kc-login").click()
        with sync_playwright() as p:
            browser = p.chromium.launch(channel=channel)
            sign_in(browser,url,session,timeout=35,drive=factors)
            browser.close()
        saved = json.loads(session.read_text())
        assert session.stat().st_mode & 0o077 == 0
        cookie = saved["cookie"]
        def raw(path):
            req = Request(url+path,headers={"Cookie":cookie["name"]+"="+cookie["value"]})
            with urlopen(req,timeout=10) as response:
                return json.load(response)
        assert raw("/api/user/orgs")[0]["role"] == "Viewer"
        deadline = time.monotonic()+125
        session_cmd = [sys.executable,str(ROOT/"panel2series.py"),"export","--session",str(session),
                       *args,"--out",str(out/"sso.json")]
        subprocess.run(session_cmd,check=True)
        assert json.loads((out/"sso.json").read_text())["points"] == expected
        browser_cmd = [sys.executable,str(ROOT/"browser_export.py"),*args,"--session",str(session)]
        if channel:
            browser_cmd += ["--channel",channel]
        for name in ("first","reuse"):
            subprocess.run(browser_cmd+["--out",str(out/name)],check=True)
            with (out/name/"panel.csv").open(encoding="utf-8-sig") as f:
                assert [float(r["value"]) for r in csv.DictReader(f)] == [2,7,4]
            assert (out/name/"panel.png").read_bytes().startswith(b"\x89PNG")
        # Use the most recently persisted Grafana cookie even after browser-side expiry.
        cookie = json.loads(session.read_text())["cookie"]
        print(version,"Viewer CI export, MFA and fresh-process reuse passed; waiting for server TTL",flush=True)
        time.sleep(max(0,deadline-time.monotonic()))
        try:
            raw("/api/user")
        except HTTPError as error:
            assert error.code == 401, error.code
        else:
            raise AssertionError("Grafana accepted expired login cookie")
        for cmd,environment,marker in [
            (browser_cmd+["--out",str(out/"expired")],os.environ,"session expired or invalid"),
            (session_cmd,os.environ,"session expired or invalid"),
            (token_cmd,{**os.environ,"GRAFANA_TOKEN":token},"401")]:
            result = subprocess.run(cmd,env=environment,capture_output=True,text=True)
            assert result.returncode and marker in result.stderr, "Unexpected response to expired credential"
        for path in out.rglob("*"):
            if path.is_file():
                content = path.read_bytes()
                assert all(secret.encode() not in content for secret in (password,seed,client_secret,token,cookie["value"]))
        print(version,"PASS expired SSO cookie and CI token",flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out",type=Path)
    ap.add_argument("versions",nargs="*",default=["10.4.19","11.5.2","12.0.0","13.3.0"])
    ap.add_argument("--channel")
    a = ap.parse_args()
    with TemporaryDirectory() as temp, ExitStack() as stack:
        tmp = Path(temp)
        network = "p2s-oidc-"+secrets.token_hex(5)
        docker("network","create",network)
        stack.callback(docker,"network","rm",network)
        ports = {v:port() for v in a.versions}
        password,seed,client_secret = (secrets.token_hex(16) for _ in range(3))
        config = tmp/"realm.json"
        config.write_text(json.dumps(realm([f"http://127.0.0.1:{n}/login/generic_oauth" for n in ports.values()],
                                           password,seed,client_secret)))
        kp = port()
        kid = docker("run","--rm","-d","--network",network,"--network-alias","idp","-p",f"127.0.0.1:{kp}:8080",
                     "-v",str(config)+":/opt/keycloak/data/import/test.json:ro","quay.io/keycloak/keycloak:26.2.5",
                     "start-dev","--import-realm","--hostname",f"http://127.0.0.1:{kp}")
        stack.callback(docker,"stop",kid)
        issuer = f"http://127.0.0.1:{kp}/realms/test"
        ready(issuer+"/.well-known/openid-configuration")
        for version, gp in ports.items():
            verify(version,gp,network,issuer+"/protocol/openid-connect",client_secret,password,seed,a.out/version,tmp,a.channel)


if __name__=="__main__":
    main()
