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

image = "grafana/grafana:11.5.2"
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
        {"id":1,"type":"timeseries","title":"Requests per second","datasource":ds,"targets":[target]}]}})
    start = 1704067200000
    orgs = request(url + "/api/user/orgs", "reader", password)
    assert orgs[0]["role"] == "Viewer", orgs
    subprocess.run(cli + ["export","--url",url,"--user","reader","--uid","demo","--panel","1",
        "--start",str(start),"--end",str(start+120000),"--out",str(out/"series.json")], check=True,
        env={**os.environ,"GRAFANA_PASSWORD":password})
    assert json.loads((out/"series.json").read_text())["points"] == [[start,2],[start+60000,7],[start+120000,4]]
finally:
    subprocess.run(["docker","stop",container], check=True, stdout=subprocess.DEVNULL)
subprocess.run(cli + ["chart",str(out/"series.json"),"--out",str(out/"chart.svg")],check=True)
print("Verified Viewer export, three reference points and offline chart.")
