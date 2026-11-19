"""Recreate the synthetic Grafana exports used by the offline analysis example."""
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
STEP = 1000
SIZE = 60
DELAY = 4
LABELS = {"instance": "demo"}
SELECTORS = {
    axis: {"refId": ref, "field": name, "labels": LABELS}
    for axis, ref, name in [("x", "A", "requests"), ("y", "B", "queue")]
}
CONFIG = {
    "step_ms": STEP, "max_lag_steps": 8,
    "stages": {"warm": [0, 30000], "load": [30000, 60000]}, **SELECTORS,
}


def generate(start, increment):
    rng = random.Random(42)
    # Four preceding observations supply the response at the left edge.
    samples = {i: rng.randrange(5, 50) + increment + (25 if i >= 30 else 0)
               for i in range(-DELAY, SIZE)}
    results = {}
    for axis, selector in SELECTORS.items():
        points = []
        for i in range(SIZE):
            if axis == "x" and i in (10, 11):
                continue
            value = samples[i] if axis == "x" else 2 * samples[i - DELAY] + 5
            points.append([start + i * STEP, None if axis == "y" and i == 44 else value])
        results[selector["refId"]] = {"status": "ok", "series": [
            {"field": selector["field"], "labels": LABELS, "points": points}
        ]}
    return {"schema_version": 2, "dashboard": "demo", "panel": 1,
            "title": "Requests and queue", "window_ms": [start, start + SIZE * STEP - 1],
            "variables": {}, "results": results}


if __name__ == "__main__":
    for name, data in [("config", CONFIG), ("run1", generate(1700000000000, 0)),
                       ("run2", generate(1700086400000, 7))]:
        (HERE / f"{name}.json").write_text(json.dumps(data, separators=(",", ":")) + "\n")
