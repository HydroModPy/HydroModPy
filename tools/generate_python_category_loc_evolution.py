from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "metrics" / "python_loc_by_category"
PYTHON_PATHSPEC = "*.py"


@dataclass(frozen=True)
class CategorySpec:
    key: str
    label: str
    color: str


CATEGORIES = [
    CategorySpec("algorithms", "Noyau scientifique / algorithmes", "#0b7285"),
    CategorySpec("spatial", "Spatial / maillage / geotraitement", "#2f9e44"),
    CategorySpec("solver_connectors", "Connectique solveurs externes", "#e67700"),
    CategorySpec("data_connectors", "Connectique donnees / formats / APIs", "#5f3dc4"),
    CategorySpec("orchestration", "Orchestration produit", "#1c7ed6"),
    CategorySpec("results", "Persistance / catalogue de resultats", "#495057"),
    CategorySpec("visualization", "Visualisation / reporting", "#d6336c"),
    CategorySpec("support", "Qualite / validation / support", "#868e96"),
]

CATEGORY_BY_KEY = {category.key: category for category in CATEGORIES}

EXACT_RULES = {
    "hydromodpy/__init__.py": "orchestration",
    "hydromodpy/__main__.py": "orchestration",
    "hydromodpy/exceptions.py": "orchestration",
    "hydromodpy/main.py": "orchestration",
    "hydromodpy/project.py": "orchestration",
    "hydromodpy/simulation.py": "orchestration",
    "hydromodpy/watershed_root.py": "orchestration",
    "hydromodpy/calibration/cli.py": "orchestration",
    "hydromodpy/calibration/persistence.py": "results",
    "hydromodpy/calibration/report.py": "visualization",
}

PREFIX_RULES = [
    ("tests/", "support"),
    ("validation_cases/", "support"),
    ("examples/", "support"),
    ("tools/", "support"),
    ("hydromodpy_annex/", "support"),
    ("scratch_tests/", "support"),
    ("tmp/", "support"),
    ("docs/", "support"),
    (".github/", "support"),
    ("hydromodpy/display/", "visualization"),
    ("hydromodpy/analysis/", "visualization"),
    ("hydromodpy/postprocess/", "visualization"),
    ("hydromodpy/results/", "results"),
    ("hydromodpy/data/", "data_connectors"),
    ("hydromodpy/data_managers/", "data_connectors"),
    ("hydromodpy/spatial/", "spatial"),
    ("hydromodpy/domain/", "spatial"),
    ("hydromodpy/field/", "spatial"),
    ("hydromodpy/geographic/", "spatial"),
    ("hydromodpy/geography/", "spatial"),
    ("hydromodpy/physics/", "algorithms"),
    ("hydromodpy/hydrology/", "algorithms"),
    ("hydromodpy/process/", "algorithms"),
    ("hydromodpy/calibration/", "algorithms"),
    ("hydromodpy/solver/boussinesq/", "algorithms"),
    ("hydromodpy/solver/", "solver_connectors"),
    ("hydromodpy/modeling/", "solver_connectors"),
    ("hydromodpy/simulation/", "orchestration"),
    ("hydromodpy/workflow/", "orchestration"),
    ("hydromodpy/core/", "orchestration"),
    ("hydromodpy/config/", "orchestration"),
    ("hydromodpy/schema/", "orchestration"),
    ("hydromodpy/runners/", "orchestration"),
    ("hydromodpy/watershed/", "orchestration"),
    ("hydromodpy/launchers/", "orchestration"),
    ("hydromodpy/launcher/", "orchestration"),
    ("hydromodpy/cli/", "orchestration"),
    ("hydromodpy/pyhelp/", "support"),
    ("hydromodpy/tools/", "support"),
]


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _git_text(*args: str) -> str:
    return _git(*args).stdout.strip()


def _iter_days(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _commit_before(day: date) -> str:
    return _git_text(
        "rev-list", "--first-parent", "-n", "1", f"--before={day.isoformat()} 23:59:59", "HEAD"
    )


def _short_sha(commit: str) -> str:
    return _git_text("rev-parse", "--short=8", commit)


def _subject(commit: str) -> str:
    return _git_text("log", "-1", "--pretty=%s", commit)


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/")


def _classify_path(path: str) -> tuple[str, str, str]:
    normalized = _normalize_path(path)
    exact_match = EXACT_RULES.get(normalized)
    if exact_match is not None:
        return exact_match, "exact", normalized
    for prefix, category_key in PREFIX_RULES:
        if normalized.startswith(prefix):
            return category_key, "prefix", prefix
    if normalized.startswith("hydromodpy/"):
        raise ValueError(f"Unclassified hydromodpy path: {normalized}")
    return "support", "fallback", "top_level_python"


def _parse_grep_count_line(raw_line: str) -> tuple[str, int]:
    commit_and_path, count_text = raw_line.rsplit(":", 1)
    _commit, path = commit_and_path.split(":", 1)
    return path, int(count_text)


def _snapshot_category_counts(commit: str) -> dict[str, int]:
    result = _git("grep", "-I", "--count", "-e", ".", commit, "--", PYTHON_PATHSPEC, check=False)
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.strip() or "git grep failed")

    counts = {category.key: 0 for category in CATEGORIES}
    for raw_line in result.stdout.splitlines():
        if not raw_line.strip():
            continue
        path, nonblank_lines = _parse_grep_count_line(raw_line)
        category_key, _rule_type, _rule_value = _classify_path(path)
        counts[category_key] += nonblank_lines
    return counts


def _head_file_assignments(commit: str) -> list[dict[str, str | int]]:
    tree_text = _git_text("ls-tree", "-r", "--name-only", commit)
    grep_result = _git(
        "grep", "-I", "--count", "-e", ".", commit, "--", PYTHON_PATHSPEC, check=False
    )
    if grep_result.returncode not in (0, 1):
        raise RuntimeError(grep_result.stderr.strip() or "git grep failed")

    lines_by_path: dict[str, int] = {}
    for raw_line in grep_result.stdout.splitlines():
        if not raw_line.strip():
            continue
        path, nonblank_lines = _parse_grep_count_line(raw_line)
        lines_by_path[_normalize_path(path)] = nonblank_lines

    rows: list[dict[str, str | int]] = []
    for raw_path in tree_text.splitlines():
        normalized = _normalize_path(raw_path)
        if not normalized.endswith(".py"):
            continue
        category_key, rule_type, rule_value = _classify_path(normalized)
        rows.append(
            {
                "path": normalized,
                "category_key": category_key,
                "category_label": CATEGORY_BY_KEY[category_key].label,
                "rule_type": rule_type,
                "rule_value": rule_value,
                "head_nonblank_lines": lines_by_path.get(normalized, 0),
            }
        )
    return rows


def _write_csv(path: Path, rows: list[dict[str, str | int | float]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _pct_change(start: int, end: int) -> float:
    if start == 0:
        return math.inf if end > 0 else 0.0
    return (end - start) / start * 100.0


def _format_pct_change(value: float) -> str:
    if math.isinf(value):
        return "nouveau"
    return f"{value:+.1f}%"


def _plot_stacked_area(
    *,
    path_png: Path,
    path_svg: Path,
    daily_rows: list[dict[str, str | int]],
    title: str,
) -> None:
    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(13.5, 7.5))

    x = [datetime.fromisoformat(str(row["date"])) for row in daily_rows]
    series = [[int(row[category.key]) for row in daily_rows] for category in CATEGORIES]
    labels = [category.label for category in CATEGORIES]
    colors = [category.color for category in CATEGORIES]
    total = [int(row["total_nonblank_lines"]) for row in daily_rows]
    pct_total = [_pct_change(total[0], value) for value in total]

    ax.stackplot(x, *series, labels=labels, colors=colors, alpha=0.9)
    ax.plot(x, total, color="#212529", linewidth=1.7, label="Total")
    ax_pct = ax.twinx()
    ax_pct.plot(
        x,
        pct_total,
        color="#c92a2a",
        linewidth=1.8,
        linestyle="--",
        label="Evolution totale (%)",
    )
    ax.set_title(title, fontsize=15, pad=14)
    ax.set_xlabel("Date")
    ax.set_ylabel("Lignes Python non vides")
    ax_pct.set_ylabel("Evolution totale (%)")
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1 if len(x) <= 45 else 2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    ax.yaxis.set_major_formatter(lambda value, pos: f"{int(value):,}".replace(",", " "))
    ax_pct.yaxis.set_major_formatter(lambda value, pos: f"{value:+.0f}%")

    start_total = total[0]
    end_total = total[-1]
    delta = end_total - start_total
    pct = _pct_change(start_total, end_total)
    ax_pct.annotate(
        _format_pct_change(pct_total[-1]),
        xy=(x[-1], pct_total[-1]),
        xytext=(-38, 10),
        textcoords="offset points",
        fontsize=9,
        color="#8f1d1d",
        bbox={"boxstyle": "round,pad=0.2", "facecolor": "white", "edgecolor": "#f1b0b0"},
    )
    handles, legend_labels = ax.get_legend_handles_labels()
    handles_pct, labels_pct = ax_pct.get_legend_handles_labels()
    ax.legend(
        handles + handles_pct, legend_labels + labels_pct, loc="upper left", ncol=2, fontsize=9
    )
    ax.text(
        0.99,
        0.02,
        f"{daily_rows[0]['date']} -> {daily_rows[-1]['date']} : {start_total:,} -> {end_total:,} ({delta:+,} {_format_pct_change(pct)})".replace(
            ",", " "
        ),
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=10,
        bbox={"boxstyle": "round,pad=0.35", "facecolor": "white", "edgecolor": "#d8d8d8"},
    )
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path_png, dpi=180)
    fig.savefig(path_svg)
    plt.close(fig)


def _plot_delta_bars(
    *,
    path_png: Path,
    path_svg: Path,
    summary_rows: list[dict[str, str | int | float]],
    title: str,
) -> None:
    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(11.5, 6.5))

    ordered_rows = sorted(
        summary_rows, key=lambda row: abs(int(row["delta_nonblank_lines"])), reverse=True
    )
    y_labels = [str(row["category_label"]) for row in ordered_rows]
    delta_values = [int(row["delta_nonblank_lines"]) for row in ordered_rows]
    colors = [CATEGORY_BY_KEY[str(row["category_key"])].color for row in ordered_rows]
    y_positions = np.arange(len(ordered_rows))

    ax.barh(y_positions, delta_values, color=colors, alpha=0.9)
    ax.set_yticks(y_positions, labels=y_labels)
    ax.invert_yaxis()
    ax.axvline(0, color="#212529", linewidth=1)
    ax.xaxis.set_major_formatter(lambda value, pos: f"{int(value):,}".replace(",", " "))
    ax.set_xlabel("Variation de lignes Python non vides")
    ax.set_title(title, fontsize=15, pad=14)
    ax.margins(x=0.22)

    for index, row in enumerate(ordered_rows):
        value = int(row["delta_nonblank_lines"])
        pct_label = str(row["pct_change_display"])
        ha = "left" if value >= 0 else "right"
        offset = 600 if value >= 0 else -600
        label = f"{value:+,} ({pct_label})".replace(",", " ")
        ax.text(value + offset, index, label, va="center", ha=ha, fontsize=9)

    ax.text(
        0.99,
        0.02,
        "Pourcentage calcule par categorie: (fin - debut) / debut",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=9,
        bbox={"boxstyle": "round,pad=0.25", "facecolor": "white", "edgecolor": "#d8d8d8"},
    )

    fig.tight_layout()
    fig.savefig(path_png, dpi=180)
    fig.savefig(path_svg)
    plt.close(fig)


def _build_summary_rows(
    daily_rows: list[dict[str, str | int]],
    head_file_rows: list[dict[str, str | int]],
) -> list[dict[str, str | int | float]]:
    start_row = daily_rows[0]
    end_row = daily_rows[-1]
    file_counts: dict[str, int] = {category.key: 0 for category in CATEGORIES}
    for file_row in head_file_rows:
        file_counts[str(file_row["category_key"])] += 1

    total_end = int(end_row["total_nonblank_lines"])
    rows: list[dict[str, str | int | float]] = []
    for category in CATEGORIES:
        start_lines = int(start_row[category.key])
        end_lines = int(end_row[category.key])
        delta = end_lines - start_lines
        pct_change = _pct_change(start_lines, end_lines)
        share = (end_lines / total_end * 100.0) if total_end else 0.0
        rows.append(
            {
                "category_key": category.key,
                "category_label": category.label,
                "head_python_files": file_counts[category.key],
                "start_nonblank_lines": start_lines,
                "end_nonblank_lines": end_lines,
                "delta_nonblank_lines": delta,
                "pct_change_from_start": None if math.isinf(pct_change) else round(pct_change, 2),
                "pct_change_display": _format_pct_change(pct_change),
                "share_of_end_percent": round(share, 2),
            }
        )
    return rows


def _build_markdown_summary(
    *,
    path: Path,
    start: date,
    end: date,
    branch: str,
    head_commit: str,
    daily_rows: list[dict[str, str | int]],
    summary_rows: list[dict[str, str | int | float]],
) -> None:
    total_start = int(daily_rows[0]["total_nonblank_lines"])
    total_end = int(daily_rows[-1]["total_nonblank_lines"])
    total_delta = total_end - total_start
    total_pct = total_delta / total_start * 100.0 if total_start else math.nan

    lines = [
        "# Evolution Python par categorie",
        "",
        f"- Branche analysee : `{branch}`",
        f"- Fenetre : `{start.isoformat()}` -> `{end.isoformat()}`",
        f"- Commit HEAD : `{head_commit}`",
        f"- Lignes Python non vides : `{total_start:,}` -> `{total_end:,}` (`{total_delta:+,}`, `{total_pct:+.1f}%`)".replace(
            ",", " "
        ),
        "",
        "## Taxonomie",
        "",
    ]
    for category in CATEGORIES:
        lines.append(f"- `{category.label}`")
    lines.extend(
        [
            "",
            "## Synthese par categorie",
            "",
            "| Categorie | Fichiers HEAD | Debut | Fin | Delta | Evolution % | Part finale |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in sorted(summary_rows, key=lambda item: int(item["end_nonblank_lines"]), reverse=True):
        lines.append(
            "| {label} | {files} | {start} | {end} | {delta} | {pct} | {share:.2f}% |".format(
                label=row["category_label"],
                files=int(row["head_python_files"]),
                start=f"{int(row['start_nonblank_lines']):,}".replace(",", " "),
                end=f"{int(row['end_nonblank_lines']):,}".replace(",", " "),
                delta=f"{int(row['delta_nonblank_lines']):+,}".replace(",", " "),
                pct=row["pct_change_display"],
                share=float(row["share_of_end_percent"]),
            )
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a category-based Python LOC evolution report over a date window."
    )
    parser.add_argument("--start", required=True, help="Start date in YYYY-MM-DD.")
    parser.add_argument("--end", required=True, help="End date in YYYY-MM-DD.")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="Output directory for CSV, charts, and summaries.",
    )
    parser.add_argument(
        "--tag",
        default="last_2_months",
        help="Filename suffix used for generated artifacts.",
    )
    parser.add_argument(
        "--title",
        default="Evolution des lignes Python par categorie",
        help="Stacked area chart title.",
    )
    args = parser.parse_args(argv)

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    if end < start:
        raise ValueError("end date must be on or after start date")

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    branch = _git_text("rev-parse", "--abbrev-ref", "HEAD")
    head_commit = _git_text("rev-parse", "HEAD")

    snapshot_cache: dict[str, dict[str, int]] = {}
    short_sha_cache: dict[str, str] = {}
    subject_cache: dict[str, str] = {}
    daily_rows: list[dict[str, str | int]] = []
    previous_commit: str | None = None

    for current_day in _iter_days(start, end):
        commit = _commit_before(current_day)
        category_counts = snapshot_cache.get(commit)
        if category_counts is None:
            category_counts = _snapshot_category_counts(commit)
            snapshot_cache[commit] = category_counts
        short_commit = short_sha_cache.setdefault(commit, _short_sha(commit))
        subject = subject_cache.setdefault(commit, _subject(commit))
        row: dict[str, str | int] = {
            "date": current_day.isoformat(),
            "commit": commit,
            "short_commit": short_commit,
            "commit_changed_from_previous_day": str(commit != previous_commit).lower(),
            "subject": subject,
        }
        total_nonblank_lines = 0
        for category in CATEGORIES:
            value = int(category_counts[category.key])
            row[category.key] = value
            total_nonblank_lines += value
        row["total_nonblank_lines"] = total_nonblank_lines
        daily_rows.append(row)
        previous_commit = commit

    head_file_rows = _head_file_assignments(head_commit)
    summary_rows = _build_summary_rows(daily_rows, head_file_rows)

    daily_csv_path = out_dir / f"python_loc_by_category_{args.tag}.csv"
    head_files_csv_path = out_dir / f"python_head_file_categories_{args.tag}.csv"
    summary_csv_path = out_dir / f"python_category_summary_{args.tag}.csv"
    area_png_path = out_dir / f"python_loc_by_category_{args.tag}.png"
    area_svg_path = out_dir / f"python_loc_by_category_{args.tag}.svg"
    delta_png_path = out_dir / f"python_loc_by_category_delta_{args.tag}.png"
    delta_svg_path = out_dir / f"python_loc_by_category_delta_{args.tag}.svg"
    summary_json_path = out_dir / f"python_category_summary_{args.tag}.json"
    summary_md_path = out_dir / f"python_category_summary_{args.tag}.md"

    _write_csv(daily_csv_path, daily_rows)
    _write_csv(head_files_csv_path, head_file_rows)
    _write_csv(summary_csv_path, summary_rows)
    _plot_stacked_area(
        path_png=area_png_path, path_svg=area_svg_path, daily_rows=daily_rows, title=args.title
    )
    _plot_delta_bars(
        path_png=delta_png_path,
        path_svg=delta_svg_path,
        summary_rows=summary_rows,
        title="Variation des lignes Python par categorie sur la periode",
    )

    summary_payload = {
        "branch": branch,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "head_commit": head_commit,
        "categories": [
            {
                "key": category.key,
                "label": category.label,
                "color": category.color,
            }
            for category in CATEGORIES
        ],
        "summary_rows": summary_rows,
        "daily_csv": str(daily_csv_path),
        "head_files_csv": str(head_files_csv_path),
        "summary_csv": str(summary_csv_path),
        "area_png": str(area_png_path),
        "area_svg": str(area_svg_path),
        "delta_png": str(delta_png_path),
        "delta_svg": str(delta_svg_path),
        "markdown_summary": str(summary_md_path),
    }
    summary_json_path.write_text(
        json.dumps(summary_payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _build_markdown_summary(
        path=summary_md_path,
        start=start,
        end=end,
        branch=branch,
        head_commit=head_commit,
        daily_rows=daily_rows,
        summary_rows=summary_rows,
    )

    print(f"DAILY_CSV={daily_csv_path}")
    print(f"HEAD_FILES_CSV={head_files_csv_path}")
    print(f"SUMMARY_CSV={summary_csv_path}")
    print(f"AREA_PNG={area_png_path}")
    print(f"DELTA_PNG={delta_png_path}")
    print(f"SUMMARY_JSON={summary_json_path}")
    print(f"SUMMARY_MD={summary_md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
