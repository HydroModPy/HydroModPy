"""Compare a pytest-benchmark JSON run against a stored baseline using ratios.

The gate compares pairwise mean ratios between benchmarks rather than absolute
mean values. This neutralizes the constant machine speed factor: if a CI runner
is uniformly N times slower than the baseline machine, every absolute mean
scales by N but the ratio between any two benchmarks stays invariant.

A regression is flagged when the relative change of any baseline ratio exceeds
``--threshold`` (default 0.30 = 30 percent). Benchmarks present only in the
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
    """Return mapping fullname -> mean (seconds) from a pytest-benchmark JSON."""
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    out: dict[str, float] = {}
    for entry in payload.get("benchmarks", []):
        key = entry.get("fullname") or entry.get("name")
        stats = entry.get("stats") or {}
        mean = stats.get("mean")
        if key is None or mean is None:
            continue
        out[str(key)] = float(mean)
    return out


def compute_ratios(means: dict[str, float]) -> dict[tuple[str, str], float]:
    """Return mean_a / mean_b for every ordered pair (a, b) with a < b."""
    names = sorted(name for name, mean in means.items() if mean > 0)
    ratios: dict[tuple[str, str], float] = {}
    for a, b in combinations(names, 2):
        mean_b = means[b]
        if mean_b > 0:
            ratios[(a, b)] = means[a] / mean_b
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
        default=0.30,
        help="Fractional ratio drift allowed before failing (default 0.30 = 30 pct).",
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

    baseline_means = _load(args.baseline)
    current_means = _load(args.current)

    baseline_ratios = compute_ratios(baseline_means)
    current_ratios = compute_ratios(current_means)

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

    missing = sorted(set(baseline_means) - set(current_means))
    new_benchmarks = sorted(set(current_means) - set(baseline_means))

    lines: list[str] = []
    lines.append("# Performance regression report (ratio-based)\n")
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
            lines.append(f"- `{name}`: {current_means[name]:.6f}s\n")
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
