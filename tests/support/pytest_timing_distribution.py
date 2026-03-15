"""Build an actionable runtime distribution from a pytest JUnit XML report.

Usage example:

    python -m pytest tests/unit -q --junitxml timing_reports/unit_junit.xml
    python tests/support/pytest_timing_distribution.py \
        --junitxml timing_reports/unit_junit.xml \
        --out-json timing_reports/unit_timing_distribution.json \
        --out-csv timing_reports/unit_test_durations.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from xml.etree import ElementTree


@dataclass(frozen=True)
class TestTiming:
    nodeid: str
    module: str
    status: str
    duration_s: float


def _parse_status_filter(raw: str) -> set[str]:
    allowed = {"passed", "failed", "error", "skipped"}
    tokens = {token.strip().lower() for token in str(raw).split(",") if token.strip() != ""}
    if not tokens:
        raise ValueError("status-filter cannot be empty")
    unknown = sorted(tokens - allowed)
    if unknown:
        raise ValueError(f"Unsupported status values in status-filter: {', '.join(unknown)}")
    return tokens


def _parse_bins(raw: str) -> list[float]:
    tokens = [token.strip() for token in str(raw).split(",") if token.strip() != ""]
    if not tokens:
        raise ValueError("bins cannot be empty")
    bins = [float(token) for token in tokens]
    if any((not math.isfinite(value)) or (value <= 0.0) for value in bins):
        raise ValueError("bins must contain finite values > 0")
    bins = sorted(set(bins))
    return bins


def _quantile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    if q <= 0.0:
        return float(sorted_values[0])
    if q >= 1.0:
        return float(sorted_values[-1])
    position = (len(sorted_values) - 1) * float(q)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return float(sorted_values[lower])
    weight = position - lower
    return float((1.0 - weight) * sorted_values[lower] + weight * sorted_values[upper])


def _status_from_testcase(node) -> str:
    if node.find("failure") is not None:
        return "failed"
    if node.find("error") is not None:
        return "error"
    if node.find("skipped") is not None:
        return "skipped"
    return "passed"


def _module_from_testcase(node) -> str:
    file_attr = node.attrib.get("file")
    if file_attr:
        return str(file_attr).replace("\\", "/")
    classname = str(node.attrib.get("classname", "")).strip()
    if classname == "":
        return "<unknown>"
    return str(classname).replace(".", "/")


def _nodeid_from_testcase(node, module: str) -> str:
    classname = str(node.attrib.get("classname", "")).strip()
    name = str(node.attrib.get("name", "")).strip()
    if classname and name:
        return f"{classname}::{name}"
    if name:
        return f"{module}::{name}"
    return module


def _load_test_timings(junitxml_path: Path) -> list[TestTiming]:
    root = ElementTree.parse(junitxml_path).getroot()
    timings: list[TestTiming] = []
    for testcase in root.iter("testcase"):
        duration = float(testcase.attrib.get("time", 0.0))
        module = _module_from_testcase(testcase)
        nodeid = _nodeid_from_testcase(testcase, module)
        timings.append(
            TestTiming(
                nodeid=nodeid,
                module=module,
                status=_status_from_testcase(testcase),
                duration_s=float(duration),
            )
        )
    return timings


def _build_histogram(values: list[float], bins: list[float]) -> list[dict[str, Any]]:
    if not values:
        return []
    edges = [0.0, *bins]
    counts = [0 for _ in range(len(edges))]
    for value in values:
        idx = len(bins)
        for pos, upper in enumerate(bins):
            if value < upper:
                idx = pos
                break
        counts[idx] += 1

    total = float(len(values))
    payload: list[dict[str, Any]] = []
    for idx, count in enumerate(counts):
        low = edges[idx]
        if idx < len(bins):
            high = bins[idx]
            label = f"[{low:.3g}, {high:.3g})"
        else:
            label = f"[{low:.3g}, +inf)"
        payload.append(
            {
                "range_s": label,
                "count": int(count),
                "share_pct": round((count / total) * 100.0, 3),
            }
        )
    return payload


def _aggregate_by_module(timings: list[TestTiming]) -> list[dict[str, Any]]:
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for timing in timings:
        totals[timing.module] = totals.get(timing.module, 0.0) + float(timing.duration_s)
        counts[timing.module] = counts.get(timing.module, 0) + 1

    rows = [
        {
            "module": module,
            "tests": int(counts[module]),
            "total_duration_s": round(float(total), 6),
            "mean_duration_s": round(float(total) / max(int(counts[module]), 1), 6),
        }
        for module, total in totals.items()
    ]
    rows.sort(key=lambda row: float(row["total_duration_s"]), reverse=True)
    return rows


def _build_report(
    timings: list[TestTiming],
    *,
    junitxml_path: Path,
    bins: list[float],
    top_n: int,
    status_filter: set[str],
) -> dict[str, Any]:
    all_count = int(len(timings))
    included = [timing for timing in timings if timing.status in status_filter]
    durations = sorted(float(timing.duration_s) for timing in included)
    total_duration = float(sum(durations))

    status_counts: dict[str, int] = {}
    for timing in timings:
        status_counts[timing.status] = status_counts.get(timing.status, 0) + 1

    top_tests = sorted(included, key=lambda row: float(row.duration_s), reverse=True)[:top_n]
    by_module = _aggregate_by_module(included)

    report = {
        "source_junitxml": str(junitxml_path),
        "total_testcases_in_xml": int(all_count),
        "included_testcases": int(len(included)),
        "excluded_testcases": int(all_count - len(included)),
        "status_filter": sorted(str(status) for status in status_filter),
        "status_counts": {key: int(value) for key, value in sorted(status_counts.items())},
        "total_duration_s": round(total_duration, 6),
        "mean_duration_s": round(total_duration / max(len(included), 1), 6),
        "median_duration_s": round(_quantile(durations, 0.50), 6),
        "quantiles_s": {
            "p50": round(_quantile(durations, 0.50), 6),
            "p75": round(_quantile(durations, 0.75), 6),
            "p90": round(_quantile(durations, 0.90), 6),
            "p95": round(_quantile(durations, 0.95), 6),
            "p99": round(_quantile(durations, 0.99), 6),
            "max": round(_quantile(durations, 1.00), 6),
        },
        "histogram_s": _build_histogram(durations, bins),
        "top_slowest_tests": [
            {
                "nodeid": timing.nodeid,
                "module": timing.module,
                "status": timing.status,
                "duration_s": round(float(timing.duration_s), 6),
            }
            for timing in top_tests
        ],
        "top_modules_by_time": by_module[:top_n],
    }
    return report


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path, timings: list[TestTiming], *, status_filter: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [timing for timing in timings if timing.status in status_filter]
    rows.sort(key=lambda row: float(row.duration_s), reverse=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["nodeid", "module", "status", "duration_s"])
        for row in rows:
            writer.writerow([row.nodeid, row.module, row.status, f"{float(row.duration_s):.6f}"])


def _print_summary(report: Mapping[str, Any], *, top_n: int) -> None:
    print("=== Pytest Timing Distribution ===")
    print(f"source: {report['source_junitxml']}")
    print(
        "tests: "
        f"{report['included_testcases']} included "
        f"(excluded={report['excluded_testcases']}, status_filter={report['status_filter']})"
    )
    print(
        "duration: "
        f"total={report['total_duration_s']:.3f}s "
        f"mean={report['mean_duration_s']:.4f}s "
        f"median={report['median_duration_s']:.4f}s"
    )
    quantiles = report["quantiles_s"]
    print(
        "quantiles: "
        f"p75={quantiles['p75']:.4f}s "
        f"p90={quantiles['p90']:.4f}s "
        f"p95={quantiles['p95']:.4f}s "
        f"p99={quantiles['p99']:.4f}s "
        f"max={quantiles['max']:.4f}s"
    )
    print("histogram:")
    for row in report["histogram_s"]:
        print(f"  {row['range_s']}: {row['count']} ({row['share_pct']:.2f}%)")
    print(f"top {top_n} tests by duration:")
    for row in report["top_slowest_tests"]:
        print(f"  {row['duration_s']:.3f}s  {row['nodeid']}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build runtime distribution from pytest JUnit XML")
    parser.add_argument("--junitxml", required=True, help="Path to pytest JUnit XML report")
    parser.add_argument(
        "--status-filter",
        default="passed,failed,error",
        help="Comma-separated statuses to include: passed,failed,error,skipped",
    )
    parser.add_argument(
        "--bins",
        default="0.01,0.05,0.1,0.25,0.5,1,2,5,10,20,60",
        help="Comma-separated upper bounds in seconds for histogram bins",
    )
    parser.add_argument("--top-n", type=int, default=20, help="Number of slow tests/modules to list")
    parser.add_argument(
        "--include-skipped",
        action="store_true",
        help="Include skipped tests in duration distribution",
    )
    parser.add_argument("--out-json", default=None, help="Optional path to save JSON report")
    parser.add_argument("--out-csv", default=None, help="Optional path to save raw sorted durations as CSV")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    junitxml_path = Path(args.junitxml).expanduser().resolve()
    if not junitxml_path.exists():
        raise FileNotFoundError(f"JUnit XML not found: {junitxml_path}")

    bins = _parse_bins(args.bins)
    status_filter = _parse_status_filter(args.status_filter)
    if args.include_skipped:
        status_filter.add("skipped")
    timings = _load_test_timings(junitxml_path)
    report = _build_report(
        timings,
        junitxml_path=junitxml_path,
        bins=bins,
        top_n=max(int(args.top_n), 1),
        status_filter=status_filter,
    )
    _print_summary(report, top_n=max(int(args.top_n), 1))

    if args.out_json:
        _write_json(Path(args.out_json).expanduser().resolve(), report)
    if args.out_csv:
        _write_csv(
            Path(args.out_csv).expanduser().resolve(),
            timings,
            status_filter=status_filter,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
