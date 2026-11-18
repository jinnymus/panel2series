"""Separate provisioning and Viewer processes."""
import os
import socket
import sys
import time
from panel2series import request

url = "https://grafana:3000"
password = os.environ["GRAFANA_PASSWORD"]
if sys.argv[1] == "viewer":
    for address, port in zip(sys.argv[2:], (9090, 8086)):
        try:
            socket.create_connection((address, port), timeout=2).close()
        except OSError:
            continue
        raise RuntimeError("Datasource reachable from exporter")
    assert request(url+"/api/user/orgs", "reader", password)[0]["role"] == "Viewer"
    sys.exit(0)

def admin(path, data=None):
    return request(url+path, "admin", os.environ["ADMIN_PASSWORD"], data)

for attempt in range(60):
    try:
        admin("/api/health")
        break
    except OSError:
        time.sleep(1)
admin("/api/admin/users", {"name":"Reader","login":"reader","email":"reader@example.test","password":password})
panels = []
for index, (name, kind, address, query) in enumerate([
    ("prometheus","prometheus","http://prometheus:9090",{"expr":"demo_depth","range":True,"interval":"1m"}),
    ("influx","influxdb","http://influx:8086",{"query":'SELECT "value" FROM "depth" WHERE time >= 1704067200000000000 AND time <= 1704067320000000000',"rawQuery":True,"resultFormat":"time_series"})
], 1):
    ds = {"uid":name,"type":kind}
    admin("/api/datasources", {**ds,"name":name,"access":"proxy","url":address, **({"database":"demo"} if name=="influx" else {})})
    panels.append({"id":index,"title":name+" queue depth","type":"timeseries","datasource":ds,
                   "targets":[{"refId":"A","datasource":ds,**query}]})
admin("/api/folders", {"uid":"examples","title":"Examples"})
admin("/api/folders/examples/permissions", {"items":[{"role":"Viewer","permission":1}]})
nested = []
for original in panels:
    panel = dict(original, id=original["id"]+10)
    target = original["targets"][0]
    if original["id"] == 1:
        expr = 'demo_depth{queue="$queue"}'
        queries = [{"expr":expr}, {"expr":"demo_depth{"}, {"expr":expr+" * 2"}]
    else:
        query = target["query"].replace("WHERE", """WHERE "queue" = '${queue}' AND""") + ' GROUP BY "queue"'
        queries = [{"query":query}, {"query":"SELECT FROM"}, {"query":query.replace('"value"', '"value" * 2')}]
    panel["targets"] = [dict(target, **{**query,"refId":ref}) for ref,query in zip("ABC",queries)]
    nested.append(panel)
panels.append({"id":20,"type":"row","title":"Nested","collapsed":True,"panels":nested})
admin("/api/dashboards/db", {"folderUid":"examples","dashboard":{"uid":"stores","title":"Stores","schemaVersion":39,
      "templating":{"list":[{"type":"custom","name":"queue","query":"other,demo","current":{"text":"other","value":"other"}}]},
      "panels":panels}})
