"""Compare a pytest-benchmark JSON run against a stored baseline using ratios.

The gate compares pairwise median ratios between benchmarks rather than
absolute values. This neutralizes the constant machine speed factor: if a CI
runner is uniformly N times slower than the baseline machine, every absolute
timing scales by N but the ratio between any two benchmarks stays invariant.

The median (not the mean) is used because the I/O micro-benchmarks have a high
coefficient of variation (the Zarr field write/read are tiny filesystem ops);
the mean is pulled around by scheduling and disk jitter on shared runners,
while the median is stable. The threshold is wide for the same reason: a real
regression in these thin storage wrappers shows up as a multi-fold ratio shift,
well past the gate, so the gate stays useful without flagging noise.

A regression is flagged when the relative change of any baseline ratio exceeds
``--threshold`` (default 0.50 = 50 percent). Benchmarks present only in the
current run are ignored (new tests). Benchmarks present only in the baseline
are reported as missing but do not fail the gate.

This script is used by ``.github/workflows/perf.yml``.
"""

from __future__ import annotations

import argparse
import json
import sys
from itertools import combinations
from pathlib import Path


def _load(path: Path) -> dict[str, float]:
    """Return mapping fullname -> median (seconds) from a pytest-benchmark JSON."""
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    out: dict[str, float] = {}
    for entry in payload.get("benchmarks", []):
        key = entry.get("fullname") or entry.get("name")
        stats = entry.get("stats") or {}
        median = stats.get("median")
        if key is None or median is None:
            continue
        out[str(key)] = float(median)
    return out


def compute_ratios(values: dict[str, float]) -> dict[tuple[str, str], float]:
    """Return value_a / value_b for every ordered pair (a, b) with a < b."""
    names = sorted(name for name, value in values.items() if value > 0)
    ratios: dict[tuple[str, str], float] = {}
    for a, b in combinations(names, 2):
        value_b = values[b]
        if value_b > 0:
            ratios[(a, b)] = values[a] / value_b
    return ratios


def _format_pct(value: float) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value * 100:.1f}%"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--current", required=True, type=Path)
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.50,
        help="Fractional ratio drift allowed before failing (default 0.50 = 50 pct).",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional Markdown report path (always written when set).",
    )
    args = parser.parse_args(argv)

    if not args.baseline.is_file():
        print(f"baseline not found: {args.baseline}", file=sys.stderr)
        return 2
    if not args.current.is_file():
        print(f"current not found: {args.current}", file=sys.stderr)
        return 2

    baseline_values = _load(args.baseline)
    current_values = _load(args.current)

    baseline_ratios = compute_ratios(baseline_values)
    current_ratios = compute_ratios(current_values)

    rows: list[tuple[str, str, float, float, float, bool]] = []
    regressions: list[tuple[str, str]] = []

    for pair, base_ratio in sorted(baseline_ratios.items()):
        if pair not in current_ratios:
            continue
        cur_ratio = current_ratios[pair]
        delta = (cur_ratio - base_ratio) / base_ratio if base_ratio > 0 else 0.0
        failed = abs(delta) > args.threshold
        rows.append((pair[0], pair[1], base_ratio, cur_ratio, delta, failed))
        if failed:
            regressions.append(pair)

    missing = sorted(set(baseline_values) - set(current_values))
    new_benchmarks = sorted(set(current_values) - set(baseline_values))

    lines: list[str] = []
    lines.append("# Performance regression report (median ratio-based)\n")
    lines.append(
        f"- Threshold: pairwise ratio drift must stay within {_format_pct(args.threshold)}\n"
    )
    lines.append(f"- Compared pairs: {len(rows)}\n")
    lines.append(f"- Regressions: {len(regressions)}\n")
    lines.append(f"- New benchmarks (not in baseline): {len(new_benchmarks)}\n")
    lines.append(f"- Missing benchmarks (only in baseline): {len(missing)}\n\n")
    lines.append("| Benchmark A | Benchmark B | Baseline A/B | Current A/B | Drift | Status |\n")
    lines.append("|---|---|---:|---:|---:|---|\n")
    for name_a, name_b, base_ratio, cur_ratio, delta, failed in rows:
        status = "FAIL" if failed else "ok"
        lines.append(
            f"| `{name_a}` | `{name_b}` | {base_ratio:.6f} | {cur_ratio:.6f} | "
            f"{_format_pct(delta)} | {status} |\n"
        )
    if new_benchmarks:
        lines.append("\n## New benchmarks (no baseline)\n\n")
        for name in new_benchmarks:
            lines.append(f"- `{name}`: {current_values[name]:.6f}s\n")
    if missing:
        lines.append("\n## Missing benchmarks (skipped this run)\n\n")
        for name in missing:
            lines.append(f"- `{name}`\n")

    report = "".join(lines)
    print(report)

    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")

    if regressions:
        print(
            f"\nFAIL: {len(regressions)} ratio(s) drifted beyond"
            f" {_format_pct(args.threshold)} relative to baseline.",
            file=sys.stderr,
        )
        return 1
    print("\nOK: every pairwise ratio stayed within the configured drift.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
