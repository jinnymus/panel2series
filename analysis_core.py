"""Offline comparison of panel2series exports on an explicit sampling grid."""

from math import fsum, isclose, isfinite, sqrt


def _integer(value, name):
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer")
    return value


def _select(export, selector):
    ref = selector["refId"]
    version = export["schema_version"]
    if version == 1:
        candidates = [export] if export.get("refId") == ref else []
    elif version == 2:
        result = export["results"].get(ref, {})
        if result.get("status") != "ok":
            raise ValueError(f"Query {ref} has status {result.get('status', 'absent')}")
        candidates = result["series"]
    else:
        raise ValueError(f"Unsupported export schema {version}")
    for key in ("field", "labels"):
        if key in selector:
            candidates = [item for item in candidates if item.get(key) == selector[key]]
    if len(candidates) != 1:
        raise ValueError(f"Selector {selector} matched {len(candidates)} series")
    return candidates[0]["points"]


def _grid(points, start, end, step, size):
    values = [None] * size
    seen = set()
    for ts, value in points:
        _integer(ts, "timestamp")
        if not start <= ts <= end or (ts - start) % step:
            raise ValueError(f"Timestamp {ts} is outside the configured sampling grid")
        if ts in seen:
            raise ValueError(f"Duplicate timestamp {ts}")
        seen.add(ts)
        if value is None:
            continue
        if type(value) not in (int, float):
            raise ValueError(f"Expected a number or null at {ts}")
        if isfinite(value):
            values[(ts - start) // step] = value
    return values


def _gaps(values, step):
    intervals = []
    for index, value in enumerate(values):
        if value is not None:
            continue
        offset = index * step
        if intervals and intervals[-1][1] == offset:
            intervals[-1][1] += step
        else:
            intervals.append([offset, offset + step])
    return {"missing": values.count(None), "count_expected": len(values),
            "intervals_ms": intervals}


def _stats(values):
    present = [v for v in values if v is not None]
    return {"count": len(present), "expected": len(values),
            "mean": fsum(present) / len(present) if present else None,
            "min": min(present, default=None), "max": max(present, default=None)}


def _delta(before, after):
    result = {}
    for name in ("x", "y"):
        a, b = before[name]["mean"], after[name]["mean"]
        result[name] = b - a if a is not None and b is not None else None
    return result


def _lag(x, y, step, limit, min_pairs):
    scores = []
    for shift in range(-limit, limit + 1):
        indices = range(max(0, -shift), min(len(x), len(y) - shift))
        pairs = [(x[i], y[i + shift]) for i in indices
                 if x[i] is not None and y[i + shift] is not None]
        corr = None
        if len(pairs) >= min_pairs:
            ax, ay = (fsum(col) / len(pairs) for col in zip(*pairs))
            dx = [a - ax for a, _ in pairs]
            dy = [b - ay for _, b in pairs]
            nx, ny = sqrt(fsum(d*d for d in dx)), sqrt(fsum(d*d for d in dy))
            if nx and ny:
                corr = fsum((a/nx) * (b/ny) for a, b in zip(dx, dy))
                corr = min(1.0, max(-1.0, corr))
        scores.append({"lag_ms": shift * step, "correlation": corr, "pairs": len(pairs)})
    valid = [row for row in scores if row["correlation"] is not None]
    best = max((abs(row["correlation"]) for row in valid), default=None)
    winners = [row for row in valid if isclose(abs(row["correlation"]), best,
                                                abs_tol=1e-12, rel_tol=1e-12)]
    if len(winners) == 1:
        return {"status": "ok", **winners[0], "scores": scores}
    return {"status": "ambiguous" if winners else "insufficient",
            "lag_ms": None, "correlation": None, "pairs": None, "scores": scores}


def analyze(exports, config):
    """Compare two runs at offsets from their inclusive window starts."""
    if len(exports) != 2:
        raise ValueError("Exactly two runs are required")
    step = _integer(config["step_ms"], "step_ms")
    limit = _integer(config["max_lag_steps"], "max_lag_steps")
    minimum = _integer(config.get("min_pairs", 3), "min_pairs")
    if step <= 0 or limit < 0 or minimum < 3:
        raise ValueError("Expected step_ms > 0, max_lag_steps >= 0 and min_pairs >= 3")
    stages = config["stages"]
    if not stages:
        raise ValueError("At least one stage is required")
    for name, (left, right) in stages.items():
        _integer(left, name)
        _integer(right, name)
        if not 0 <= left < right:
            raise ValueError(f"Invalid stage bounds for {name}")
    ordered = sorted(stages, key=lambda name: stages[name][0])
    runs = []
    for export in exports:
        start, end = export["window_ms"]
        _integer(start, "window start")
        _integer(end, "window end")
        if end < start:
            raise ValueError("Invalid export window")
        size = (end - start) // step + 1
        series = {name: _grid(_select(export, config[name]), start, end, step, size)
                  for name in ("x", "y")}
        stats, changes = {}, {}
        previous = None
        for name in ordered:
            left, right = stages[name]
            if right > end - start + 1 or (previous and left < stages[previous][1]):
                raise ValueError(f"Stage {name} overlaps or exceeds the export window")
            first, stop = (left + step - 1) // step, (right + step - 1) // step
            stats[name] = {k: _stats(v[first:stop]) for k, v in series.items()}
            if previous is not None:
                changes[name] = _delta(stats[previous], stats[name])
            previous = name
        runs.append({"offsets_ms": list(range(0, size * step, step)), **series,
                     "gaps": {k: _gaps(v, step) for k, v in series.items()},
                     "stages": stats, "stage_changes": changes,
                     "lag": _lag(series["x"], series["y"], step, limit, minimum)})
    return {"runs": runs, "run_changes": {
        name: _delta(runs[0]["stages"][name], runs[1]["stages"][name]) for name in ordered}}
