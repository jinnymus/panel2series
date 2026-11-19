"""Compare two Panel2Series archives and render offline SVG charts."""
import argparse
import json
from pathlib import Path
from xml.sax.saxutils import escape

from analysis_core import analyze


def plot(path, title, curves, xlabel, ylabel):
    colors = ["#2065a6", "#b94722"]
    points = [(x, y) for _, values in curves for x, y in values if y is not None]
    xs = [x for _, values in curves for x, _ in values] or [0]
    lo, hi = min(xs), max(xs)
    low, high = (min(y for x, y in points), max(y for x, y in points)) if points else (0, 1)
    if low == high:
        low, high = low - 1, high + 1
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 350">',
           '<rect width="800" height="350" fill="white"/>',
           '<g font-family="sans-serif" font-size="13" fill="#192c41">']

    def label(x, y, value):
        svg.append(f'<text x="{x}" y="{y}">{escape(str(value))}</text>')

    label(75, 28, title)
    label(75, 50, ylabel)
    label(345, 333, xlabel)
    for i in range(5):
        frac = i / 4
        sy = 276 - 210 * frac
        svg.append(f'<path d="M75 {sy}h665" stroke="#d8dfe5"/>')
        label(6, sy + 4, f'{low + (high-low)*frac:.4g}')
        label(72 + 665 * frac, 298, f'{lo + (hi-lo)*frac:.5g}')
    for (name, values), color, legend in zip(curves, colors, [440, 600]):
        label(legend, 48, name)
        svg.append(f'<path d="M{legend-25} 44h18" stroke="{color}" stroke-width="3"/>')
        previous = None
        for x, y in values:
            if y is None:
                previous = None
                continue
            sx = 75 + 665 * (x-lo) / (hi-lo or 1)
            sy = 276 - 210 * (y-low) / (high-low)
            if previous:
                svg.append(f'<path d="M{previous} L{sx:.2f} {sy:.2f}" stroke="{color}" fill="none"/>')
            svg.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="2.3" fill="{color}"/>')
            previous = f'{sx:.2f} {sy:.2f}'
    path.write_text('\n'.join(svg + ['</g></svg>']), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archives', nargs=2, type=Path)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text())
        result = analyze([json.loads(p.read_text()) for p in args.archives], config)
        args.out.mkdir(exist_ok=True, parents=True)
        for metric in ('x', 'y'):
            curves = [(f'Run {i}', list(zip(run['offsets_ms'], run[metric])))
                      for i, run in enumerate(result['runs'], 1)]
            plot(args.out / f'{metric}.svg', f"{metric} · {config[metric].get('field', '')}",
                 curves, 'Elapsed time (ms)', 'Metric value')
        curves = [(f'Run {i}', [(s['lag_ms'], s['correlation']) for s in run['lag']['scores']])
                  for i, run in enumerate(result['runs'], 1)]
        plot(args.out / 'lag.svg', 'Correlation by lag', curves, 'Lag (ms)', 'Pearson r')
        (args.out / 'analysis.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f'Analysis failed: {exc}\n')


if __name__ == '__main__':
    main()
