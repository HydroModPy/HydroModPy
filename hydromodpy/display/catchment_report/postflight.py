"""Post-render checks for catchment report figures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hydromodpy.display.catchment_report.artifacts import rel
from hydromodpy.display.catchment_report.resources import REPO_ROOT


class CatchmentReportPostflightError(RuntimeError):
    """Raised when strict figure postflight detects incomplete report figures."""

    def __init__(self, postflight_path: Path, missing: tuple[str, ...]) -> None:
        self.postflight_path = postflight_path
        self.missing = missing
        details = "\n".join(f"- {figure_id}" for figure_id in missing)
        super().__init__(
            "Catchment report figure postflight failed. Missing expected figures:\n"
            f"{details}\nPostflight report: {postflight_path}"
        )


def write_figure_postflight_report(
    config: Any,
    *,
    strict: bool,
) -> Path:
    """Write a figure-completeness report and optionally fail on missing figures."""
    manifest_path = config.output_dir / "block_report_manifest.json"
    postflight_path = config.output_dir / "block_report_postflight.json"
    manifest = _load_manifest(manifest_path)
    expected = _expected_figure_ids(config, manifest)
    copied = _copied_figures(manifest)
    present = tuple(sorted(figure_id for figure_id in expected if figure_id in copied))
    missing = tuple(sorted(figure_id for figure_id in expected if figure_id not in copied))
    dangling = tuple(
        sorted(figure_id for figure_id, path in copied.items() if not _resolve_path(path).exists())
    )
    payload = {
        "report_type": "catchment_report_figure_postflight",
        "strict": strict,
        "manifest": rel(manifest_path),
        "expected_count": len(expected),
        "copied_count": len(copied),
        "present_count": len(present),
        "missing_count": len(missing),
        "dangling_count": len(dangling),
        "expected_figures": list(expected),
        "present_figures": list(present),
        "missing_figures": list(missing),
        "dangling_figures": list(dangling),
        "copied_figures": copied,
    }
    postflight_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    failures = tuple(sorted({*missing, *dangling}))
    if strict and failures:
        raise CatchmentReportPostflightError(postflight_path, failures)
    return postflight_path


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.exists():
        return {}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _expected_figure_ids(config: Any, manifest: dict[str, Any]) -> tuple[str, ...]:
    from_manifest = manifest.get("expected_figure_ids")
    if isinstance(from_manifest, list):
        return tuple(sorted(str(item) for item in from_manifest))
    specs = (
        config.artifact_specs if config.artifact_specs is not None else config.preset.artifact_specs
    )
    return tuple(sorted(spec.figure_id for spec in specs))


def _copied_figures(manifest: dict[str, Any]) -> dict[str, str]:
    copied = manifest.get("copied_figures")
    if not isinstance(copied, dict):
        return {}
    return {str(key): str(value) for key, value in copied.items()}


def _resolve_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


__all__ = [
    "CatchmentReportPostflightError",
    "write_figure_postflight_report",
]
