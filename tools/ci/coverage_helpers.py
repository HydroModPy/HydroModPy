"""Shared helpers for coverage entrypoints used in CI and regression tests."""

from __future__ import annotations

from pathlib import Path
import tomllib


def repo_root() -> Path:
    """Return the repository root from the helper location."""
    return Path(__file__).resolve().parents[2]


def coverage_sources() -> tuple[str, ...]:
    """Read canonical coverage sources from `pyproject.toml`."""
    pyproject_path = repo_root() / "pyproject.toml"
    try:
        payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return ("hydromodpy",)
    sources = (
        payload.get("tool", {})
        .get("coverage", {})
        .get("run", {})
        .get("source", ())
    )
    if not isinstance(sources, list):
        return ("hydromodpy",)
    normalized = tuple(str(source).strip() for source in sources if str(source).strip())
    return normalized or ("hydromodpy",)


def coverage_include_patterns() -> list[str]:
    """Convert dotted package names to file globs for Coverage API runners."""
    patterns: list[str] = []
    for source in coverage_sources():
        patterns.append(f"*/{source.replace('.', '/')}/*")
    return patterns


__all__ = ["coverage_include_patterns", "coverage_sources", "repo_root"]
