from __future__ import annotations

import argparse
import fnmatch
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_TEMP_DIR_PATTERNS = (
    ".codex_*",
    ".codex_pytest_tmp*",
    ".mypy_cache",
    ".pytest*",
    ".ruff_cache",
    ".tmp*",
    "codex_validation_*",
    "hydromodpy.egg-info",
    "mesh-sim-int-*",
    "pytest-cache-files-*",
    "pytest-temp-root",
    "pytestscratch*",
    "river_trace_smoke_*",
    "scratch_*",
    "test_tmp*",
    "timing_reports",
    "tmp",
    "tmp*",
)


def _git(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=check,
        capture_output=True,
        text=True,
    )


def _matches_root_temp_pattern(path: Path) -> bool:
    return any(fnmatch.fnmatch(path.name, pattern) for pattern in ROOT_TEMP_DIR_PATTERNS)


def _is_git_ignored(path: Path) -> bool:
    rel_path = path.relative_to(REPO_ROOT).as_posix()
    result = _git("check-ignore", "-q", "--", rel_path)
    return result.returncode == 0


def _has_tracked_content(path: Path) -> bool:
    rel_path = path.relative_to(REPO_ROOT).as_posix()
    result = _git("ls-files", "--", rel_path)
    return bool(result.stdout.strip())


def _iter_cleanup_candidates() -> list[Path]:
    candidates: list[Path] = []
    for path in sorted(REPO_ROOT.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_dir():
            continue
        if not _matches_root_temp_pattern(path):
            continue
        if not _is_git_ignored(path):
            continue
        if _has_tracked_content(path):
            continue
        candidates.append(path)
    return candidates


def _format_rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _handle_remove_readonly(
    func,
    path: str,
    exc_info,
) -> None:
    _ = exc_info
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    func(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Remove root-level temporary directories already ignored by git. Dry-run by default."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete the selected directories instead of only listing them.",
    )
    args = parser.parse_args(argv)

    candidates = _iter_cleanup_candidates()
    if not candidates:
        print("No ignored root-level temporary directories found.")
        return 0

    action = "DELETE" if args.apply else "DRY-RUN"
    for path in candidates:
        print(f"{action} {_format_rel(path)}")

    if not args.apply:
        print(f"{len(candidates)} candidate(s). Re-run with --apply to delete them.")
        return 0

    failures: list[tuple[Path, Exception]] = []
    for path in candidates:
        try:
            shutil.rmtree(path, onerror=_handle_remove_readonly)
        except Exception as exc:  # pragma: no cover - best-effort cleanup script
            failures.append((path, exc))

    if failures:
        for path, exc in failures:
            print(f"FAILED {_format_rel(path)}: {exc}", file=sys.stderr)
        return 1

    print(f"Deleted {len(candidates)} directory(ies).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
