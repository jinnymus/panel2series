"""Build an offline HTML report beside the downloaded analysis and SVG files."""
import argparse
import json
from html import escape
from pathlib import Path

CHARTS = {"x.svg": "Metric x by elapsed time", "y.svg": "Metric y by elapsed time",
          "lag.svg": "Correlation by lag"}


def display(value):
    if value is None:
        return "—"
    return escape(format(value, ".6g") if isinstance(value, float) else str(value))


def table(headers, rows):
    head = "".join(f'<th scope="col">{display(cell)}</th>' for cell in headers)
    body = "".join("<tr>" + "".join(f"<td>{display(cell)}</td>" for cell in row) + "</tr>"
                   for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def build(directory):
    analysis = json.loads((directory / "analysis.json").read_text(encoding="utf-8"))
    sections = []
    for index, run in enumerate(analysis["runs"], 1):
        sections.append(f"<h2>Run {index}</h2>")
        archive = directory / f"run{index}.json"
        if archive.is_file():
            source = json.loads(archive.read_text(encoding="utf-8"))
            title = escape(source.get("title", "Panel"))
            sections.append(f'<p><a href="{archive.name}">{title}</a></p>')
            sections.append(table(["Dashboard", "Panel", "From (Unix ms)", "To (Unix ms)"],
                                  [[source["dashboard"], source["panel"], *source["window_ms"]]]))
            issues = [[ref, item["status"]] for ref, item in source.get("results", {}).items()
                      if item["status"] != "ok"]
            if issues:
                sections.append(table(["Query", "Export status"], issues))
        rows = []
        for stage, metrics in run["stages"].items():
            for name, stats in metrics.items():
                rows.append([stage, name, stats["mean"], stats["min"], stats["max"],
                             stats["count"], stats["expected"]])
        sections.append(table(["Stage", "Metric", "Mean", "Min", "Max", "Observed", "Expected"], rows))
        lag = run["lag"]
        sections.append(table(["Lag status", "Lag (ms)", "Pearson r", "Paired observations"],
                              [[lag["status"], lag["lag_ms"], lag["correlation"], lag["pairs"]]]))
    sections.append("<h2>Mean change from run 1 to run 2</h2>")
    sections.append(table(["Stage", "Change in x", "Change in y"],
                          [[stage, row["x"], row["y"]] for stage, row in analysis["run_changes"].items()]))
    for name, caption in CHARTS.items():
        if not (directory / name).is_file():
            raise ValueError(f"Missing chart {name}")
        sections.append(f'<figure><img src="{name}" alt="{caption}"><figcaption>{caption}</figcaption></figure>')
    html = """<!doctype html>
<html lang="en"><meta charset="utf-8"><title>Run comparison</title>
<style>body{font:16px system-ui;max-width:54rem;margin:2rem auto;padding:0 1rem}
table{border-collapse:collapse;margin:1rem 0}td,th{border:1px solid #bbb;padding:.35rem .65rem}
img{max-width:100%}figure{margin:2rem 0}</style><main>
<h1>Run comparison</h1><a href="analysis.json">Download numerical results</a>
"""
    (directory / "index.html").write_text(html + "\n".join(sections) + "</main></html>\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="Directory containing analysis.json and all three SVGs")
    args = parser.parse_args()
    try:
        build(args.directory)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"Report failed: {exc}\n")
