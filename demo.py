"""Run an isolated Grafana, export as Viewer, remove it, then render offline."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from urllib.error import URLError

from panel2series import request

version = os.getenv("GRAFANA_VERSION", "11.5.2")
image = "grafana/grafana:" + version
admin = secrets.token_urlsafe()
password = secrets.token_urlsafe()
out = Path(sys.argv[1])
out.mkdir(exist_ok=True)
cli = [sys.executable, str(Path(__file__).with_name("panel2series.py"))]
container = subprocess.check_output(["docker", "run", "--rm", "-d", "-p", "127.0.0.1::3000",
    "-e", "GF_SECURITY_ADMIN_PASSWORD", image], env={**os.environ, "GF_SECURITY_ADMIN_PASSWORD": admin}, text=True).strip()
try:
    addr = subprocess.check_output(["docker", "port", container, "3000/tcp"], text=True).strip()
    url = "http://" + addr
    def setup(path, body=None):
        return request(url + path, "admin", admin, body)
    for attempt in range(90):
        try:
            setup("/api/health")
            break
        except (URLError, OSError):
            time.sleep(1)
    setup("/api/admin/users", {"name":"Viewer", "login":"reader", "email":"reader@example.test","password":password})
    ds = {"uid":"fixture", "type":"grafana-testdata-datasource"}
    setup("/api/datasources", {**ds, "name":"Fixture","access":"proxy"})
    target = {"refId":"A","datasource":ds,"scenarioId":"csv_content",
              "csvContent":"time,value\n2024-01-01T00:00:00Z,2\n2024-01-01T00:01:00Z,7\n2024-01-01T00:02:00Z,4"}
    setup("/api/folders", {"uid":"examples","title":"Examples"})
    setup("/api/folders/examples/permissions", {"items":[{"role":"Viewer","permission":1}]})
    setup("/api/dashboards/db", {"folderUid":"examples","dashboard":{"uid":"demo","title":"Example","schemaVersion":39,"panels":[
        {"id":1,"type":"timeseries","title":"Requests per second","datasource":ds,"targets":[target]},
        {"id":3,"type":"timeseries","title":"Two metrics","datasource":ds,
         "targets":[dict(target, csvContent="time,left,right\n2024-01-01T00:00:00Z,2,4\n2024-01-01T00:01:00Z,7,14\n2024-01-01T00:02:00Z,4,8")]},
        {"id":2,"type":"timeseries","title":"Double depth","datasource":ds,"targets":[target],
         "gridPos":{"x":0,"y":8,"w":12,"h":8},
         "transformations":[{"id":"calculateField","options":{"mode":"binary","alias":"double_depth",
             "binary":{"left":"value","operator":"*","right":"2"}}}]}]}})
    start = 1704067200000
    orgs = request(url + "/api/user/orgs", "reader", password)
    assert orgs[0]["role"] == "Viewer", orgs
    subprocess.run(cli + ["export","--url",url,"--user","reader","--uid","demo","--panel","1",
        "--start",str(start),"--end",str(start+120000),"--out",str(out/"series.json")], check=True,
        env={**os.environ,"GRAFANA_PASSWORD":password})
    assert json.loads((out/"series.json").read_text())["points"] == [[start,2],[start+60000,7],[start+120000,4]]
    subprocess.run(cli + ["export","--url",url,"--user","reader","--uid","demo","--panel","3",
        "--start",str(start),"--end",str(start+120000),"--out",str(out/"multi.json")], check=True,
        env={**os.environ,"GRAFANA_PASSWORD":password})
    archive = json.loads((out/"multi.json").read_text())
    assert archive["schema_version"] == 2
    series = archive["results"]["A"]["series"]
    assert [s["field"] for s in series] == ["left", "right"], series
    for item, values in zip(series, ([2,7,4], [4,14,8])):
        assert item["points"] == [[start + n*60000,v] for n,v in enumerate(values)]
    if os.getenv("BROWSER_CHECK") == "1":
        import csv
        import struct
        assert setup("/api/health")["version"] == version
        export = [sys.executable,str(Path(__file__).with_name("browser_export.py")), "--url",url,
                  "--user","reader","--uid","demo","--panel","2","--start",str(start),
                  "--end",str(start+120000),"--out",str(out)]
        if os.getenv("BROWSER_CHANNEL"):
            export += ["--channel",os.environ["BROWSER_CHANNEL"]]
        if os.getenv("BROWSER_LOCATORS"):
            export += ["--locators",os.environ["BROWSER_LOCATORS"]]
        subprocess.run(export,check=True,env={**os.environ,"GRAFANA_PASSWORD":password})
        with (out/"panel.csv").open(encoding="utf-8-sig",newline="") as f:
            rows = list(csv.DictReader(f))
        assert [float(r["value"]) for r in rows] == [2,7,4], rows
        assert [float(r["double_depth"]) for r in rows] == [4,14,8], rows
        png = (out/"panel.png").read_bytes()
        assert png.startswith(b"\x89PNG\r\n\x1a\n") and min(struct.unpack(">II",png[16:24])) >= 200
finally:
    subprocess.run(["docker","stop",container], check=True, stdout=subprocess.DEVNULL)
subprocess.run(cli + ["chart",str(out/"series.json"),"--out",str(out/"chart.svg")],check=True)
print("Verified Viewer export, three reference points and offline chart.")
