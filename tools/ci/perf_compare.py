"""Compare a pytest-benchmark JSON run against a stored baseline.

Fails (exit code 1) if any benchmark mean regresses by more than ``--threshold``
relative to its baseline value. Benchmarks present only in the current run are
ignored (new tests). Benchmarks present only in the baseline are reported as
missing but do not fail the gate by default.

This script is used by ``.github/workflows/perf.yml``.
"""

from __future__ import annotations

import argparse
import json
import sys
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
        help="Fractional regression allowed before failing (default 0.30 = 30 pct).",
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

    baseline = _load(args.baseline)
    current = _load(args.current)

    rows: list[tuple[str, float, float, float, bool]] = []
    regressions: list[str] = []
    missing: list[str] = []

    for name, base_mean in sorted(baseline.items()):
        if name not in current:
            missing.append(name)
            continue
        cur_mean = current[name]
        delta = (cur_mean - base_mean) / base_mean if base_mean > 0 else 0.0
        failed = delta > args.threshold
        rows.append((name, base_mean, cur_mean, delta, failed))
        if failed:
            regressions.append(name)

    new_benchmarks = sorted(set(current) - set(baseline))

    lines: list[str] = []
    lines.append("# Performance regression report\n")
    lines.append(f"- Threshold: mean delta must stay below {_format_pct(args.threshold)}\n")
    lines.append(f"- Compared benchmarks: {len(rows)}\n")
    lines.append(f"- Regressions: {len(regressions)}\n")
    lines.append(f"- New benchmarks (not in baseline): {len(new_benchmarks)}\n")
    lines.append(f"- Missing benchmarks (only in baseline): {len(missing)}\n\n")
    lines.append("| Benchmark | Baseline mean (s) | Current mean (s) | Delta | Status |\n")
    lines.append("|---|---:|---:|---:|---|\n")
    for name, base_mean, cur_mean, delta, failed in rows:
        status = "FAIL" if failed else "ok"
        lines.append(
            f"| `{name}` | {base_mean:.6f} | {cur_mean:.6f} | {_format_pct(delta)} | {status} |\n"
        )
    if new_benchmarks:
        lines.append("\n## New benchmarks (no baseline)\n\n")
        for name in new_benchmarks:
            lines.append(f"- `{name}`: {current[name]:.6f}s\n")
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
            f"\nFAIL: {len(regressions)} benchmark(s) regressed beyond"
            f" {_format_pct(args.threshold)} on the mean.",
            file=sys.stderr,
        )
        return 1
    print("\nOK: no benchmark regressed beyond the configured threshold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
