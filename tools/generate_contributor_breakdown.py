from __future__ import annotations

import argparse
import csv
import math
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "code_lines"
PATHSPECS = [
    "*.py",
    "*.pyi",
    "*.sh",
    "*.bash",
    "*.zsh",
    "*.fish",
    "*.ps1",
    "*.psm1",
    "*.bat",
    "*.cmd",
    "*.js",
    "*.jsx",
    "*.ts",
    "*.tsx",
    "*.mjs",
    "*.cjs",
    "*.html",
    "*.htm",
    "*.css",
    "*.scss",
    "*.sass",
    "*.c",
    "*.h",
    "*.cc",
    "*.cpp",
    "*.cxx",
    "*.hpp",
    "*.hxx",
    "*.f",
    "*.f90",
    "*.f95",
    "*.for",
    "*.f03",
    "*.f08",
    "*.java",
    "*.cs",
    "*.go",
    "*.rs",
    "*.rb",
    "*.php",
    "*.pl",
    "*.pm",
    "*.lua",
    "*.r",
    "*.jl",
    "*.m",
    "*.sql",
    "*.cmake",
    "Dockerfile",
    "Makefile",
    "CMakeLists.txt",
    ":(exclude)bin/**",
    ":(exclude)docs/_build*/**",
    ":(exclude)docs/readthedocs/_build*/**",
    ":(exclude)docs/readthedocs/source/api/generated/**",
    ":(exclude)docs/readthedocs/source/_generated/**",
    ":(exclude)hydromodpy.egg-info/**",
]


@dataclass(frozen=True)
class SnapshotCount:
    files: int
    nonblank_lines: int


@dataclass
class CommitDelta:
    commit: str
    landing_day: date
    author_name: str
    author_email: str
    subject: str
    added_nonblank: int = 0
    deleted_nonblank: int = 0

    @property
    def net_nonblank(self) -> int:
        return self.added_nonblank - self.deleted_nonblank

    @property
    def contributor_id(self) -> str:
        return f"{self.author_name}\t{self.author_email}"


@dataclass
class ContributorSummary:
    contributor_id: str
    display_name: str
    author_name: str
    author_email: str
    commits: int = 0
    added_nonblank: int = 0
    deleted_nonblank: int = 0

    @property
    def net_nonblank(self) -> int:
        return self.added_nonblank - self.deleted_nonblank


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


def _count_snapshot(commit: str) -> SnapshotCount:
    result = _git("grep", "-I", "--count", "-e", ".", commit, "--", *PATHSPECS, check=False)
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.strip() or "git grep failed")
    files = 0
    nonblank_lines = 0
    for raw_line in result.stdout.splitlines():
        if not raw_line.strip():
            continue
        try:
            count = int(raw_line.rsplit(":", 1)[1])
        except (IndexError, ValueError):
            continue
        files += 1
        nonblank_lines += count
    return SnapshotCount(files=files, nonblank_lines=nonblank_lines)


def _commit_before(day: date) -> str:
    return _git_text("rev-list", "-n", "1", f"--before={day.isoformat()} 23:59:59", "HEAD")


def _parse_nonblank_patch_delta(text: str) -> tuple[int, int]:
    added_nonblank = 0
    deleted_nonblank = 0
    for raw_line in text.splitlines():
        if not raw_line:
            continue
        if raw_line.startswith(
            ("diff --git ", "index ", "@@ ", "new file mode ", "deleted file mode ")
        ):
            continue
        if raw_line.startswith(
            ("rename from ", "rename to ", "similarity index ", "dissimilarity index ")
        ):
            continue
        if raw_line.startswith(("--- ", "+++ ", "Binary files ")):
            continue
        if raw_line.startswith("+"):
            if raw_line[1:].strip():
                added_nonblank += 1
            continue
        if raw_line.startswith("-"):
            if raw_line[1:].strip():
                deleted_nonblank += 1
            continue
    return added_nonblank, deleted_nonblank


def _snapshot_commits_by_day(start: date, end: date) -> list[tuple[date, str]]:
    snapshots: list[tuple[date, str]] = []
    for current_day in _iter_days(start, end):
        snapshots.append((current_day, _commit_before(current_day)))
    return snapshots


def _collect_commit_deltas_for_window(
    previous_commit: str,
    current_commit: str,
    *,
    landing_day: date,
) -> list[CommitDelta]:
    if previous_commit == current_commit:
        return []

    rev_list = _git_text("rev-list", "--reverse", f"{previous_commit}..{current_commit}")
    commits: list[CommitDelta] = []
    for commit_sha in rev_list.splitlines():
        commit_sha = commit_sha.strip()
        if not commit_sha:
            continue
        metadata = _git_text("show", "--no-patch", "--format=%P\t%an\t%ae\t%s", commit_sha)
        parent_text, author_name, author_email, subject = metadata.split("\t", 3)
        parents = [item for item in parent_text.split() if item]
        if len(parents) != 1:
            continue
        diff_text = _git(
            "diff",
            "-M",
            "--unified=0",
            parents[0],
            commit_sha,
            "--",
            *PATHSPECS,
        ).stdout
        added_nonblank, deleted_nonblank = _parse_nonblank_patch_delta(diff_text)
        if added_nonblank == 0 and deleted_nonblank == 0:
            continue
        commits.append(
            CommitDelta(
                commit=commit_sha,
                landing_day=landing_day,
                author_name=author_name,
                author_email=author_email,
                subject=subject,
                added_nonblank=added_nonblank,
                deleted_nonblank=deleted_nonblank,
            )
        )
    return commits


def _collect_commit_deltas(
    start: date, end: date
) -> tuple[list[tuple[date, str]], list[CommitDelta]]:
    snapshots = _snapshot_commits_by_day(start, end)
    if not snapshots:
        return [], []

    commits: list[CommitDelta] = []
    previous_commit = snapshots[0][1]
    for landing_day, current_commit in snapshots[1:]:
        commits.extend(
            _collect_commit_deltas_for_window(
                previous_commit,
                current_commit,
                landing_day=landing_day,
            )
        )
        previous_commit = current_commit
    return snapshots, commits


def _build_display_names(commits: list[CommitDelta]) -> dict[str, str]:
    emails_by_name: defaultdict[str, set[str]] = defaultdict(set)
    names_by_email: defaultdict[str, set[str]] = defaultdict(set)
    for item in commits:
        emails_by_name[item.author_name].add(item.author_email)
        names_by_email[item.author_email].add(item.author_name)

    display_names: dict[str, str] = {}
    for item in commits:
        contributor_id = item.contributor_id
        if contributor_id in display_names:
            continue
        ambiguous_name = len(emails_by_name[item.author_name]) > 1
        ambiguous_email = len(names_by_email[item.author_email]) > 1
        if ambiguous_name or ambiguous_email:
            display_names[contributor_id] = f"{item.author_name} <{item.author_email}>"
        else:
            display_names[contributor_id] = item.author_name
    return display_names


def _build_summaries(
    commits: list[CommitDelta], display_names: dict[str, str]
) -> list[ContributorSummary]:
    summaries: dict[str, ContributorSummary] = {}
    for item in commits:
        contributor_id = item.contributor_id
        summary = summaries.get(contributor_id)
        if summary is None:
            summary = ContributorSummary(
                contributor_id=contributor_id,
                display_name=display_names[contributor_id],
                author_name=item.author_name,
                author_email=item.author_email,
            )
            summaries[contributor_id] = summary
        summary.commits += 1
        summary.added_nonblank += item.added_nonblank
        summary.deleted_nonblank += item.deleted_nonblank
    return sorted(summaries.values(), key=lambda item: item.net_nonblank, reverse=True)


def _select_chart_contributors(
    summaries: list[ContributorSummary],
    top_n: int,
) -> tuple[list[str], set[str], bool]:
    ordered_ids = [item.contributor_id for item in summaries if item.net_nonblank != 0]
    kept_ids = ordered_ids[:top_n]
    grouped_ids = set(ordered_ids[top_n:])
    include_other = bool(grouped_ids)
    return kept_ids, grouped_ids, include_other


def _build_daily_rows(
    *,
    start: date,
    end: date,
    baseline_lines: int,
    exact_totals_by_day: dict[date, int],
    commits: list[CommitDelta],
    display_names: dict[str, str],
    kept_ids: list[str],
    grouped_ids: set[str],
    include_other: bool,
) -> list[dict[str, int | str]]:
    deltas_by_day: defaultdict[date, defaultdict[str, int]] = defaultdict(lambda: defaultdict(int))
    for item in commits:
        deltas_by_day[item.landing_day][item.contributor_id] += item.net_nonblank

    running_by_contributor: defaultdict[str, int] = defaultdict(int)
    rows: list[dict[str, int | str]] = []
    residual_label = "Residuel merges/renommages"
    needs_residual_band = False

    for current_day in _iter_days(start, end):
        for contributor_id, delta in deltas_by_day[current_day].items():
            running_by_contributor[contributor_id] += delta

        row: dict[str, int | str] = {
            "date": current_day.isoformat(),
            "Code deja present au debut de periode": baseline_lines,
        }
        total_lines = baseline_lines

        for contributor_id in kept_ids:
            value = running_by_contributor[contributor_id]
            row[display_names[contributor_id]] = value
            total_lines += value

        if include_other:
            other_value = sum(
                running_by_contributor[contributor_id] for contributor_id in grouped_ids
            )
            row["Autres contributeurs"] = other_value
            total_lines += other_value

        exact_total = exact_totals_by_day[current_day]
        residual = exact_total - total_lines
        row[residual_label] = residual
        row["Total lignes source non vides"] = exact_total
        if residual != 0:
            needs_residual_band = True
        rows.append(row)

    if not needs_residual_band:
        for row in rows:
            del row[residual_label]
    return rows


def _write_daily_csv(path: Path, rows: list[dict[str, int | str]]) -> None:
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_summary_csv(
    path: Path,
    summaries: list[ContributorSummary],
    grouped_ids: set[str],
    growth_total: int,
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "display_name",
                "author_name",
                "author_email",
                "commits",
                "added_nonblank_lines",
                "deleted_nonblank_lines",
                "net_nonblank_lines",
                "share_of_period_growth_pct",
                "grouped_in_chart",
            ]
        )
        for item in summaries:
            share = (item.net_nonblank / growth_total * 100.0) if growth_total else math.nan
            writer.writerow(
                [
                    item.display_name,
                    item.author_name,
                    item.author_email,
                    item.commits,
                    item.added_nonblank,
                    item.deleted_nonblank,
                    item.net_nonblank,
                    f"{share:.4f}",
                    str(item.contributor_id in grouped_ids).lower(),
                ]
            )


def _plot_breakdown(
    *,
    path_png: Path,
    path_svg: Path,
    rows: list[dict[str, int | str]],
    start: date,
    end: date,
    baseline_label: str,
    title: str,
) -> None:
    x = [datetime.fromisoformat(str(row["date"])) for row in rows]
    columns = [
        column
        for column in rows[0].keys()
        if column not in {"date", "Total lignes source non vides"}
    ]
    series = [[int(row[column]) for row in rows] for column in columns]
    totals = [int(row["Total lignes source non vides"]) for row in rows]

    cmap = plt.get_cmap("tab20")
    colors: list[str] = []
    palette_index = 0
    for index, column in enumerate(columns):
        if index == 0:
            colors.append("#D9D9D9")
        elif column.startswith("Residuel merges/renommages"):
            colors.append("#F0C36D")
        else:
            colors.append(cmap(palette_index))
            palette_index += 1

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(13, 7))
    ax.stackplot(x, *series, labels=columns, colors=colors, alpha=0.95)
    ax.plot(x, totals, color="#126A66", linewidth=2.2, label="Total")

    start_total = totals[0]
    end_total = totals[-1]
    delta = end_total - start_total
    pct = delta / start_total * 100.0 if start_total else math.nan

    ax.set_title(title, fontsize=15, pad=14)
    ax.set_xlabel("Date")
    ax.set_ylabel("Lignes source non vides")
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    ax.yaxis.set_major_formatter(lambda value, pos: f"{int(value):,}".replace(",", " "))
    ax.legend(loc="upper left", ncol=2, fontsize=9)
    ax.text(
        0.99,
        0.03,
        f"{start.isoformat()} -> {end.isoformat()} : {start_total:,} -> {end_total:,} ({delta:+,} {pct:+.1f}%)".replace(
            ",", " "
        ),
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=10,
        bbox={"boxstyle": "round,pad=0.35", "facecolor": "white", "edgecolor": "#d8d8d8"},
    )
    fig.text(
        0.01,
        0.01,
        (
            f"{baseline_label} = base initiale.\n"
            "Les bandes colorees montrent le delta net non vide par auteur de commit. "
            "Le residuel couvre surtout merges et renommages."
        ),
        fontsize=9,
        ha="left",
        va="bottom",
    )
    fig.autofmt_xdate()
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(path_png, dpi=180)
    fig.savefig(path_svg)
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a contributor breakdown of source-line evolution over one period. "
            "The baseline band is the code already present at the start snapshot; "
            "contributor bands are cumulative net nonblank-line deltas by commit author "
            "on the day each commit becomes visible in the end-of-day snapshot."
        )
    )
    parser.add_argument("--start", required=True, help="Start date in YYYY-MM-DD.")
    parser.add_argument("--end", required=True, help="End date in YYYY-MM-DD.")
    parser.add_argument(
        "--top-n",
        type=int,
        default=8,
        help="Number of contributor bands kept explicitly in the chart before grouping the rest.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="Output directory for chart and CSV files.",
    )
    parser.add_argument(
        "--tag",
        default="3_months",
        help="Filename suffix used for generated artifacts, for example '3_months' or 'last_month'.",
    )
    parser.add_argument(
        "--title",
        default="Evolution des lignes de code - decomposition par contributeur",
        help="Chart title.",
    )
    args = parser.parse_args(argv)

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    if end < start:
        raise ValueError("end date must be on or after start date")

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    snapshots, commits = _collect_commit_deltas(start, end)
    if not snapshots:
        raise RuntimeError("no snapshots found for the requested date range")

    start_commit = snapshots[0][1]
    end_commit = snapshots[-1][1]
    snapshot_count_cache: dict[str, SnapshotCount] = {}
    exact_totals_by_day: dict[date, int] = {}
    for current_day, commit in snapshots:
        count = snapshot_count_cache.get(commit)
        if count is None:
            count = _count_snapshot(commit)
            snapshot_count_cache[commit] = count
        exact_totals_by_day[current_day] = count.nonblank_lines

    baseline = snapshot_count_cache[start_commit]
    end_snapshot = snapshot_count_cache[end_commit]
    display_names = _build_display_names(commits)
    summaries = _build_summaries(commits, display_names)
    kept_ids, grouped_ids, include_other = _select_chart_contributors(
        summaries, top_n=max(int(args.top_n), 0)
    )
    daily_rows = _build_daily_rows(
        start=start,
        end=end,
        baseline_lines=baseline.nonblank_lines,
        exact_totals_by_day=exact_totals_by_day,
        commits=commits,
        display_names=display_names,
        kept_ids=kept_ids,
        grouped_ids=grouped_ids,
        include_other=include_other,
    )

    growth_total = end_snapshot.nonblank_lines - baseline.nonblank_lines

    chart_csv = out_dir / f"code_lines_breakdown_by_contributor_{args.tag}.csv"
    summary_csv = out_dir / f"code_lines_contributor_summary_{args.tag}.csv"
    chart_png = out_dir / f"code_lines_breakdown_by_contributor_{args.tag}.png"
    chart_svg = out_dir / f"code_lines_breakdown_by_contributor_{args.tag}.svg"

    _write_daily_csv(chart_csv, daily_rows)
    _write_summary_csv(summary_csv, summaries, grouped_ids, growth_total)
    _plot_breakdown(
        path_png=chart_png,
        path_svg=chart_svg,
        rows=daily_rows,
        start=start,
        end=end,
        baseline_label="Code deja present au debut de periode",
        title=args.title,
    )

    print(f"CSV={chart_csv}")
    print(f"SUMMARY={summary_csv}")
    print(f"PNG={chart_png}")
    print(f"SVG={chart_svg}")
    print(
        f"START {start.isoformat()} commit={start_commit[:8]} lines={baseline.nonblank_lines} files={baseline.files}"
    )
    print(
        f"END {end.isoformat()} commit={end_commit[:8]} lines={end_snapshot.nonblank_lines} files={end_snapshot.files}"
    )
    print(
        f"GROWTH total={growth_total} contributors={len(summaries)} shown={len(kept_ids) + int(include_other)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
