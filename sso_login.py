"""Interactive Grafana sign-in for browser and numeric exports."""
import argparse
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit
from urllib.error import HTTPError


def trusted_base(url):
    base = url.rstrip("/")
    site = urlsplit(base)
    if site.username or site.password or site.query or site.fragment or not site.hostname:
        raise ValueError("Expected a Grafana base URL")
    if site.scheme != "https" and not (site.scheme == "http" and site.hostname in ("localhost", "127.0.0.1")):
        raise ValueError("Remote Grafana requires HTTPS")
    return base


def write_cookie(cookies, base, path, name):
    cookies = [c for c in cookies if c["name"] == name]
    if len(cookies) != 1:
        raise ValueError("Expected one Grafana login cookie; check --cookie-name")
    tmp = NamedTemporaryFile(mode="w", dir=path.parent, delete=False)
    try:
        with tmp:
            json.dump({"base":base, "cookie":cookies[0]}, tmp)
        os.replace(tmp.name,path)
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def save(ctx, base, path, name):
    write_cookie(ctx.cookies(base+"/api/user"), base, path, name)


def load_cookie(base, path):
    if path.stat().st_mode & 0o077:
        raise ValueError("Session file requires owner-only permissions (chmod 600)")
    saved = json.loads(path.read_text())
    if saved["base"] != trusted_base(base):
        raise ValueError("Session belongs to a different Grafana URL")
    return saved["cookie"]


def verify_session(client, base):
    response = client.get(base+"/api/user",max_redirects=0)
    if response.status != 200 or not response.json().get("id"):
        raise RuntimeError(f"Grafana session expired or invalid (HTTP {response.status}); run sso_login.py again")


def restore(ctx, base, path):
    cookie = load_cookie(base, path)
    ctx.add_cookies([cookie])
    verify_session(ctx.request, base)
    return cookie["name"]


@contextmanager
def session_api(base, path):
    base = trusted_base(base)
    cookie = load_cookie(base, path)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        client = p.request.new_context(storage_state={"cookies":[cookie],"origins":[]})
        try:
            verify_session(client, base)
            def api(route, body=None):
                response = client.fetch(base+route,method="GET" if body is None else "POST",
                                        data=body,max_redirects=0)
                if not response.ok:
                    raise HTTPError(base+route,response.status,response.status_text,{},None)
                return response.json()
            yield api
            write_cookie(client.storage_state()["cookies"],base,path,cookie["name"])
        finally:
            client.dispose()


def sign_in(browser, base, path, cookie_name="grafana_session", timeout=300, drive=None):
    base = trusted_base(base)
    ctx = browser.new_context()
    try:
        page = ctx.new_page()
        page.goto(base+"/login/generic_oauth",wait_until="domcontentloaded")
        if drive:
            drive(page)
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            if any(c["name"] == cookie_name for c in ctx.cookies(base+"/api/user")):
                response = ctx.request.get(base+"/api/user",max_redirects=0)
                if response.ok and response.json().get("id"):
                    save(ctx,base,path,cookie_name)
                    return
            page.wait_for_timeout(500)
        raise TimeoutError("Interactive Grafana login timed out")
    finally:
        ctx.close()


def login_options(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="JSON login settings")
    parser.add_argument("--url")
    parser.add_argument("--session", type=Path)
    parser.add_argument("--cookie-name")
    parser.add_argument("--channel")
    args = parser.parse_args(argv)
    settings = {}
    if args.config:
        try:
            settings = json.loads(args.config.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            parser.error(f"Cannot read login configuration: {exc}")
        allowed = {"url", "session", "cookie_name", "channel"}
        if not isinstance(settings, dict) or settings.keys() - allowed:
            parser.error("Expected a JSON object with url, session, cookie_name or channel")
        if any(not isinstance(v, str) or not v.strip() for v in settings.values()):
            parser.error("Login settings must be non-empty strings")
        if "session" in settings:
            settings["session"] = args.config.parent / Path(settings["session"]).expanduser()
    for key, value in settings.items():
        if getattr(args, key) is None:
            setattr(args, key, value)
    if not args.url or not args.session:
        parser.error("Supply url and session through --config or command-line options")
    try:
        args.url = trusted_base(args.url)
    except ValueError as exc:
        parser.error(str(exc))
    args.cookie_name = args.cookie_name or "grafana_session"
    return args


if __name__ == "__main__":
    args = login_options()
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False,channel=args.channel)
        sign_in(browser,args.url,args.session,args.cookie_name)
