from __future__ import annotations

import argparse
import csv
import math
import subprocess
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
    ":(exclude)docs/_build*/**",
    ":(exclude)docs/source/api/generated/**",
    ":(exclude)docs/source/_generated/**",
    ":(exclude)hydromodpy.egg-info/**",
]
WORKTREE_EXTENSIONS = {
    ".py",
    ".pyi",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".ps1",
    ".psm1",
    ".bat",
    ".cmd",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".cjs",
    ".html",
    ".htm",
    ".css",
    ".scss",
    ".sass",
    ".c",
    ".h",
    ".cc",
    ".cpp",
    ".cxx",
    ".hpp",
    ".hxx",
    ".f",
    ".f90",
    ".f95",
    ".for",
    ".f03",
    ".f08",
    ".java",
    ".cs",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".pl",
    ".pm",
    ".lua",
    ".r",
    ".jl",
    ".m",
    ".sql",
    ".cmake",
}
WORKTREE_FILENAMES = {"Dockerfile", "Makefile", "CMakeLists.txt"}
EXCLUDED_PREFIXES = (
    "bin/",
    "docs/_build",
    "docs/_build",
    "docs/source/api/generated/",
    "docs/source/_generated/",
    "hydromodpy.egg-info/",
)


@dataclass(frozen=True)
class SnapshotCount:
    files: int
    nonblank_lines: int


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


def _short_sha(commit: str) -> str:
    return _git_text("rev-parse", "--short=8", commit)


def _subject(commit: str) -> str:
    return _git_text("log", "-1", "--pretty=%s", commit)


def _is_worktree_code_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if any(normalized.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
        return False
    name = normalized.rsplit("/", 1)[-1]
    return name in WORKTREE_FILENAMES or Path(name).suffix.lower() in WORKTREE_EXTENSIONS


def _count_worktree() -> SnapshotCount:
    tracked_and_untracked = _git_text("ls-files", "--cached", "--others", "--exclude-standard")
    files = 0
    nonblank_lines = 0
    for rel in tracked_and_untracked.splitlines():
        if not _is_worktree_code_path(rel):
            continue
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        files += 1
        nonblank_lines += sum(1 for line in text.splitlines() if line.strip())
    return SnapshotCount(files=files, nonblank_lines=nonblank_lines)


def _write_csv(path: Path, rows: list[dict[str, str | int]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _plot(
    *,
    path_png: Path,
    path_svg: Path,
    rows: list[dict[str, str | int]],
    worktree_count: SnapshotCount | None,
    title: str,
) -> None:
    git_rows = [row for row in rows if row["source"] == "git"]
    x = [datetime.fromisoformat(str(row["date"])) for row in git_rows]
    y = [int(row["nonblank_source_lines"]) for row in git_rows]
    start = date.fromisoformat(str(git_rows[0]["date"]))
    end = date.fromisoformat(str(git_rows[-1]["date"]))
    start_value = y[0]
    end_value = y[-1]
    delta = end_value - start_value
    pct = delta / start_value * 100.0 if start_value else math.nan

    days = len(git_rows)
    tick_interval = 1 if days <= 45 else 2

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(12, 6.5))
    ax.plot(
        x, y, color="#126A66", linewidth=2.4, marker="o", markersize=3.2, label="Snapshots commites"
    )
    ax.fill_between(x, y, min(y), color="#126A66", alpha=0.08)

    if worktree_count is not None and worktree_count.nonblank_lines != end_value:
        worktree_x = datetime.combine(end, datetime.min.time())
        ax.scatter(
            [worktree_x],
            [worktree_count.nonblank_lines],
            color="#C43C39",
            s=75,
            zorder=5,
            label="Arbre de travail",
        )
        ax.annotate(
            f"Arbre de travail : {worktree_count.nonblank_lines:,}".replace(",", " "),
            xy=(worktree_x, worktree_count.nonblank_lines),
            xytext=(-150, 28),
            textcoords="offset points",
            arrowprops={"arrowstyle": "->", "color": "#C43C39", "lw": 1.2},
            fontsize=9,
            color="#4A1F1F",
        )

    ax.set_title(title, fontsize=15, pad=14)
    ax.set_xlabel("Date")
    ax.set_ylabel("Lignes source non vides")
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=tick_interval))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    ax.yaxis.set_major_formatter(lambda value, pos: f"{int(value):,}".replace(",", " "))
    ax.legend(loc="upper left")
    ax.text(
        0.99,
        0.03,
        f"{start.isoformat()} -> {end.isoformat()} : {start_value:,} -> {end_value:,} ({delta:+,} {pct:+.1f}%)".replace(
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate one code-line evolution chart over a date window using end-of-day git snapshots."
    )
    parser.add_argument("--start", required=True, help="Start date in YYYY-MM-DD.")
    parser.add_argument("--end", required=True, help="End date in YYYY-MM-DD.")
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
        default="Evolution des lignes de code",
        help="Chart title.",
    )
    parser.add_argument(
        "--include-worktree",
        action="store_true",
        help="Add the current working tree as a separate point when it differs from the end snapshot.",
    )
    args = parser.parse_args(argv)

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    if end < start:
        raise ValueError("end date must be on or after start date")

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, str | int]] = []
    snapshot_cache: dict[str, SnapshotCount] = {}
    previous_commit: str | None = None

    for current_day in _iter_days(start, end):
        commit = _commit_before(current_day)
        count = snapshot_cache.get(commit)
        if count is None:
            count = _count_snapshot(commit)
            snapshot_cache[commit] = count
        rows.append(
            {
                "date": current_day.isoformat(),
                "source": "git",
                "commit": commit,
                "short_commit": _short_sha(commit),
                "commit_changed_from_previous_day": str(commit != previous_commit).lower(),
                "source_files": count.files,
                "nonblank_source_lines": count.nonblank_lines,
                "subject": _subject(commit),
            }
        )
        previous_commit = commit

    worktree_count: SnapshotCount | None = _count_worktree() if args.include_worktree else None
    if worktree_count is not None:
        rows.append(
            {
                "date": end.isoformat(),
                "source": "working_tree",
                "commit": "WORKTREE",
                "short_commit": "WORKTREE",
                "commit_changed_from_previous_day": "n/a",
                "source_files": worktree_count.files,
                "nonblank_source_lines": worktree_count.nonblank_lines,
                "subject": "Etat courant incluant modifications non commitees et fichiers non ignores",
            }
        )

    csv_path = out_dir / f"code_lines_evolution_{args.tag}.csv"
    png_path = out_dir / f"code_lines_evolution_{args.tag}.png"
    svg_path = out_dir / f"code_lines_evolution_{args.tag}.svg"

    _write_csv(csv_path, rows)
    _plot(
        path_png=png_path,
        path_svg=svg_path,
        rows=rows,
        worktree_count=worktree_count,
        title=args.title,
    )

    print(f"CSV={csv_path}")
    print(f"PNG={png_path}")
    print(f"SVG={svg_path}")
    if rows:
        first = rows[0]
        last_git = [row for row in rows if row["source"] == "git"][-1]
        print(
            f"START {first['date']} {first['short_commit']} {first['nonblank_source_lines']} files={first['source_files']}"
        )
        print(
            f"END_HEAD {last_git['date']} {last_git['short_commit']} {last_git['nonblank_source_lines']} files={last_git['source_files']}"
        )
    if worktree_count is not None:
        print(f"WORKTREE {worktree_count.nonblank_lines} files={worktree_count.files}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
