"""Verify that a docs refresh only changed the expected generated artifacts."""

from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALLOWED_PREFIXES = (
    "docs/source/capability_gallery/",
    "docs/source/_static/capability_gallery/",
    "validation_cases/reports/latest/",
)
DEFAULT_ALLOWED_FILES = (
    "tools/doc_gallery/manifests/xt3d_irregular_tri_method_choice_report.json",
)


@dataclass(frozen=True, slots=True)
class RefreshPathPolicy:
    """Allowlist used to validate changed files after a docs refresh."""

    allowed_prefixes: tuple[str, ...] = DEFAULT_ALLOWED_PREFIXES
    allowed_files: tuple[str, ...] = DEFAULT_ALLOWED_FILES

    def allows(self, repo_relative_path: str) -> bool:
        normalized = str(repo_relative_path).replace("\\", "/")
        if normalized in self.allowed_files:
            return True
        return any(normalized.startswith(prefix) for prefix in self.allowed_prefixes)


def parse_porcelain_paths(status_output: str) -> tuple[str, ...]:
    """Extract repo-relative paths from ``git status --porcelain`` output."""

    paths: list[str] = []
    for raw_line in status_output.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        payload = line[3:] if len(line) >= 4 else ""
        if " -> " in payload:
            payload = payload.split(" -> ", 1)[1]
        normalized = payload.strip().replace("\\", "/")
        if normalized:
            paths.append(normalized)
    return tuple(paths)


def collect_changed_paths(*, repo_root: Path = REPO_ROOT) -> tuple[str, ...]:
    """Return the changed and untracked paths visible to ``git status``."""

    completed = subprocess.run(
        ("git", "status", "--porcelain=v1", "--untracked-files=all"),
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if int(completed.returncode) != 0:
        stderr = completed.stderr.strip()
        raise RuntimeError(stderr or "git status --porcelain failed")
    return parse_porcelain_paths(completed.stdout)


def partition_changed_paths(
    changed_paths: tuple[str, ...],
    *,
    policy: RefreshPathPolicy = RefreshPathPolicy(),
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split changed paths between expected generated outputs and unexpected ones."""

    allowed: list[str] = []
    unexpected: list[str] = []
    for path in changed_paths:
        if policy.allows(path):
            allowed.append(path)
        else:
            unexpected.append(path)
    return tuple(allowed), tuple(unexpected)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for the refresh-output verifier."""

    parser = argparse.ArgumentParser(
        description=(
            "Fail if a docs refresh changed files outside the expected generated "
            "artifact locations."
        )
    )
    parser.add_argument(
        "--allow-prefix",
        action="append",
        default=[],
        help="Additional repo-relative prefix allowed to change.",
    )
    parser.add_argument(
        "--allow-file",
        action="append",
        default=[],
        help="Additional exact repo-relative file allowed to change.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for refresh-output verification."""

    args = build_parser().parse_args(argv)
    changed_paths = collect_changed_paths()
    policy = RefreshPathPolicy(
        allowed_prefixes=DEFAULT_ALLOWED_PREFIXES + tuple(str(item) for item in args.allow_prefix),
        allowed_files=DEFAULT_ALLOWED_FILES + tuple(str(item) for item in args.allow_file),
    )
    allowed, unexpected = partition_changed_paths(changed_paths, policy=policy)

    print("Allowed changed paths:")
    if allowed:
        for path in allowed:
            print(f"- {path}")
    else:
        print("- <none>")

    if unexpected:
        print("")
        print("Unexpected changed paths:")
        for path in unexpected:
            print(f"- {path}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
