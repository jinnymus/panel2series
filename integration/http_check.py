"""Compare HTTP results against the data seeded by run.sh."""
import json
import math
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from xml.etree.ElementTree import parse


def main():
    repo = Path(__file__).resolve().parents[1]
    reporting = repo / "example" / "reporting"
    out = Path(sys.argv[1])
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", 8787), timeout=1):
                break
        except OSError:
            time.sleep(.1)
    else:
        raise RuntimeError("Job service did not start")
    plan = json.loads((reporting / "stores.json").read_text())
    plan["exports"][0].update(end=1704067320000)
    plan["exports"][1].update(panel=12, start=1704067200000)
    plan["config"].update(stages={"window": [0, 120001]}, max_lag_steps=1)
    with tempfile.TemporaryDirectory() as scratch:
        config = Path(scratch) / "plan.json"
        config.write_text(json.dumps(plan))
        subprocess.run([sys.executable, reporting / "autoreport.py", "--api",
                        "http://127.0.0.1:8787", "--plan", config, "--out", out], check=True)

    def artifact(name):
        return json.loads((out / name).read_text())

    analysis = artifact("analysis.json")
    for i, expected in enumerate(([2, 7, 4], [3, 9, 5]), 1):
        exports = artifact(f"run{i}.json")["results"]
        assert exports["B"]["status"] == "error"
        run = analysis["runs"][i-1]
        for ref, axis, scale in (("A", "x", 1), ("C", "y", 2)):
            series, = exports[ref]["series"]
            assert series["labels"]["queue"] == "demo"
            values = [v * scale for v in expected]
            assert series["points"] == [[1704067200000 + j*60000, v] for j, v in enumerate(values)]
            assert run[axis] == values
            assert run["gaps"][axis]["missing"] == 0
        assert run["lag"]["lag_ms"] == 0 and run["lag"]["pairs"] == 3
    for axis, delta in (("x", 4/3), ("y", 8/3)):
        assert math.isclose(analysis["run_changes"]["window"][axis], delta)
    html = (out / "index.html").read_text()
    for chart in ("x.svg", "y.svg", "lag.svg"):
        assert chart in html and parse(out / chart).getroot().tag.endswith("}svg")
    job_ids = artifact("provenance.json")
    assert len(set([*job_ids["exports"], job_ids["analysis"]])) == 3
    print("PASS Viewer HTTP report: Prometheus and InfluxDB points, partial errors, stage changes, lag, SVG and HTML")


if __name__ == "__main__":
    main()
