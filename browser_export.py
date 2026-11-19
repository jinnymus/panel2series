"""Capture a solo time-series panel and its transformed Inspector CSV."""
import argparse
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote, urlencode, urlsplit

import yaml
from playwright.sync_api import expect, sync_playwright
from panel2series import find_panel


def selectors(version, override):
    config = yaml.safe_load(Path(__file__).with_name("locators.yaml").read_text())
    values = dict(config["defaults"])
    values.update(config["versions"].get(str(version).split(".")[0], {}))
    if override:
        changes = yaml.safe_load(override.read_text())
        if not isinstance(changes, dict) or changes.keys() - values.keys():
            raise ValueError("Unknown locator or invalid override mapping")
        values.update(changes)
    if not all(isinstance(value, str) and value.strip() for value in values.values()):
        raise ValueError("Expected non-empty locator strings")
    return values


def capture(args):
    base = args.url.rstrip("/")
    site = urlsplit(base)
    if site.scheme != "https" and not (site.scheme == "http" and site.hostname in ("localhost","127.0.0.1")):
        raise ValueError("Use HTTPS for remote Grafana")
    if args.start >= args.end:
        raise ValueError("Expected start < end")
    query = [("from",args.start),("to",args.end),("tz","utc")]
    for item in args.var:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise ValueError("Expected --var name=value")
        query.append(("var-"+key,value))
    uid = quote(args.uid, safe="")
    def link(route, **params):
        return base+route+"?"+urlencode(query+list(params.items()))
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=args.channel)
        ctx = browser.new_context(locale="en-US",timezone_id="UTC",viewport={"width":1200,"height":650})
        if args.session:
            from sso_login import restore, save
            cookie_name = restore(ctx, base, args.session)
        else:
            login = ctx.request.post(base+"/login",data={"user":args.user,"password":os.environ["GRAFANA_PASSWORD"]},max_redirects=0)
            if login.status != 200:
                raise RuntimeError(f"Grafana login returned HTTP {login.status}")
        version = ctx.request.get(base+"/api/health").json()["version"]
        loc = selectors(version,args.locators)
        # Read the panel definition to decide whether a transform toggle is required.
        response = ctx.request.get(base+"/api/dashboards/uid/"+uid,max_redirects=0)
        if not response.ok:
            raise RuntimeError(f"Dashboard lookup returned HTTP {response.status}")
        definition = response.json()
        slug = quote(definition["meta"]["slug"],safe="")
        panel = find_panel(definition["dashboard"]["panels"], args.panel)
        if not panel:
            raise ValueError("Panel is missing")
        page = ctx.new_page()
        page.set_default_timeout(45000)
        def locate(key):
            return page.locator(loc[key])
        args.out.mkdir(parents=True,exist_ok=True)
        with TemporaryDirectory(dir=args.out) as temp:
            stage = Path(temp)
            page.goto(link("/d-solo/"+uid+"/"+slug, panelId=args.panel),wait_until="domcontentloaded")
            locate("plot").wait_for()
            locate("panel").screenshot(path=stage/"panel.png")
            if "inspect_data" in loc:
                page.goto(link("/d/"+uid+"/"+slug),wait_until="domcontentloaded")
                title = panel["title"]
                page.locator(loc["header"].replace("{header}", json.dumps("data-testid Panel header "+title))).hover()
                page.locator(loc["menu"].replace("{menu}", json.dumps("data-testid Panel menu "+title))).press("Enter")
                locate("inspect").click()
                locate("inspect_data").click()
            else:
                page.goto(link("/d/"+uid+"/"+slug, inspect=args.panel, inspectTab="data"),wait_until="domcontentloaded")
            locate("download").wait_for()
            if panel.get("transformations"):
                locate("options").click()
                toggle = locate("transform")
                toggle.wait_for(state="attached")
                if not toggle.is_checked():
                    toggle.evaluate("(el) => el.click()")
                    expect(toggle).to_be_checked()
            with page.expect_download() as event:
                locate("download").click()
            event.value.save_as(stage/"panel.csv")
            for name in ("panel.csv","panel.png"):
                (stage/name).replace(args.out/name)
        if args.session:
            save(ctx, base, args.session, cookie_name)
        browser.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    auth = ap.add_mutually_exclusive_group(required=True)
    auth.add_argument("--user")
    auth.add_argument("--session",type=Path)
    for name in ("url","uid"):
        ap.add_argument("--"+name,required=True)
    for name in ("panel","start","end"):
        ap.add_argument("--"+name,type=int,required=True)
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--locators",type=Path)
    ap.add_argument("--channel",help="Installed Chromium channel, e.g. chrome")
    ap.add_argument("--var",action="append",default=[])
    capture(ap.parse_args())
