"""Generic report artifact manifest for site-selection outputs."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hydromodpy.display.report_artifacts import (
    ArtifactKind,
    ReportArtifact,
    ReportArtifactManifest,
    ReportArtifactRequirement,
)
from hydromodpy.display.report_profiles import REPORT_ARTIFACT_MANIFEST_NAME
from hydromodpy.schema.site_selection_manifest import (
    load_selection_manifest,
    manifest_output_path,
    manifest_output_root,
)

SITE_SELECTION_REPORT_PROFILE = "site_selection"
SITE_SELECTION_PLAN_REPORT_PROFILE = "site_selection_plan"
REPORT_ARTIFACT_MANIFEST_OUTPUT_KEY = "report_artifact_manifest_json"


def write_site_selection_report_artifact_manifest(
    selection_manifest_path: str | Path,
) -> Path:
    """Write the generic report-artifact manifest for a site-selection run."""

    manifest_file = Path(selection_manifest_path).expanduser().resolve()
    selection_manifest = load_selection_manifest(manifest_file)
    output_root = manifest_output_root(selection_manifest, manifest_path=manifest_file)
    report_manifest = build_site_selection_report_artifact_manifest(
        selection_manifest,
        selection_manifest_path=manifest_file,
    )
    return report_manifest.write_json(
        output_root / REPORT_ARTIFACT_MANIFEST_NAME,
        base_dir=output_root,
    )


def build_site_selection_report_artifact_manifest(
    selection_manifest: Mapping[str, Any],
    *,
    selection_manifest_path: str | Path,
) -> ReportArtifactManifest:
    """Build a generic artifact contract from ``site_selection_manifest.json``."""

    manifest_file = Path(selection_manifest_path).expanduser().resolve()
    outputs = _outputs(selection_manifest)
    requirements = tuple(
        _requirement_for_output(output_key)
        for output_key in sorted(outputs)
        if output_key != REPORT_ARTIFACT_MANIFEST_OUTPUT_KEY
    )
    return ReportArtifactManifest(
        profile=SITE_SELECTION_REPORT_PROFILE,
        requirements=requirements,
        artifacts=tuple(
            ReportArtifact.from_requirement(
                requirement,
                path=manifest_output_path(
                    selection_manifest,
                    requirement.artifact_id,
                    manifest_path=manifest_file,
                ),
            )
            for requirement in requirements
        ),
        source_manifest=manifest_file,
        metadata={
            "artifact_scope": "site_selection.outputs",
            "selection_id": str(selection_manifest.get("selection_id") or ""),
            "action": str(selection_manifest.get("action") or ""),
            "output_count": len(outputs),
            "counts": dict(selection_manifest.get("counts") or {}),
        },
    )


def write_site_selection_plan_report_artifact_manifest(
    plan_manifest_path: str | Path,
    *,
    report_path: str | Path | None = None,
) -> Path:
    """Write the generic report-artifact manifest for a plan-only run."""

    manifest_file = Path(plan_manifest_path).expanduser().resolve()
    plan_manifest = _load_json_manifest(manifest_file)
    output_root = _plan_output_root(plan_manifest, manifest_file=manifest_file)
    report_manifest = build_site_selection_plan_report_artifact_manifest(
        plan_manifest,
        plan_manifest_path=manifest_file,
        report_path=report_path,
    )
    return report_manifest.write_json(
        output_root / REPORT_ARTIFACT_MANIFEST_NAME,
        base_dir=output_root,
    )


def build_site_selection_plan_report_artifact_manifest(
    plan_manifest: Mapping[str, Any],
    *,
    plan_manifest_path: str | Path,
    report_path: str | Path | None = None,
) -> ReportArtifactManifest:
    """Build a generic artifact contract from ``site_selection_plan.json``."""

    manifest_file = Path(plan_manifest_path).expanduser().resolve()
    output_root = _plan_output_root(plan_manifest, manifest_file=manifest_file)
    resolved_report_path = (
        _resolve_plan_artifact_path(report_path, output_root=output_root)
        if report_path is not None
        else None
    )
    requirements = (
        _plan_manifest_requirement(),
        *(
            (_plan_html_requirement(),)
            if resolved_report_path is not None
            else ()
        ),
    )
    paths = {
        "site_selection_plan_json": manifest_file,
        "site_selection_report_html": resolved_report_path,
    }
    return ReportArtifactManifest(
        profile=SITE_SELECTION_PLAN_REPORT_PROFILE,
        requirements=requirements,
        artifacts=tuple(
            ReportArtifact.from_requirement(
                requirement,
                path=paths.get(requirement.artifact_id),
            )
            for requirement in requirements
        ),
        source_manifest=manifest_file,
        metadata={
            "artifact_scope": "site_selection.plan",
            "selection_id": str(plan_manifest.get("selection_id") or ""),
            "action": "plan",
            "planned_output_count": len(plan_manifest.get("planned_outputs") or ()),
        },
    )


def _outputs(selection_manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    outputs = selection_manifest.get("outputs")
    if isinstance(outputs, Mapping):
        return outputs
    return {}


def _requirement_for_output(output_key: str) -> ReportArtifactRequirement:
    return ReportArtifactRequirement(
        artifact_id=output_key,
        kind=_kind_for_output(output_key),
        required=True,
        title=_title_for_output(output_key),
        producer=_producer_for_output(output_key),
        metadata=_metadata_for_output(output_key),
    )


def _plan_manifest_requirement() -> ReportArtifactRequirement:
    return ReportArtifactRequirement(
        artifact_id="site_selection_plan_json",
        kind="json",
        required=True,
        title="site selection plan",
        producer="site_selection.plan",
        metadata={"site_selection_output": "site_selection_plan_json"},
    )


def _plan_html_requirement() -> ReportArtifactRequirement:
    return ReportArtifactRequirement(
        artifact_id="site_selection_report_html",
        kind="html",
        required=True,
        title="site selection plan HTML report",
        producer="site_selection.report",
        metadata={
            "site_selection_output": "site_selection_report_html",
            "plan_report": True,
        },
    )


def _kind_for_output(output_key: str) -> ArtifactKind:
    if output_key.endswith("_png"):
        return "figure"
    if output_key.endswith("_html"):
        return "html"
    if output_key.endswith("_csv"):
        return "table"
    if output_key.endswith(("_json", "_jsonl", "_geojson")):
        return "json"
    return "file"


def _producer_for_output(output_key: str) -> str:
    if output_key == "site_selection_manifest_json":
        return "site_selection.manifest"
    if output_key in {"site_selection_report_html", "site_selection_map_png"}:
        return "site_selection.report"
    if "decision" in output_key:
        return "site_selection.decisions"
    if "evidence" in output_key:
        return "site_selection.evidence"
    if "flow" in output_key or "network" in output_key:
        return "site_selection.hydrology"
    return "site_selection.outputs"


def _metadata_for_output(output_key: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {"site_selection_output": output_key}
    if output_key == "site_selection_map_png":
        metadata["display_figure"] = "site_selection_map"
    return metadata


def _title_for_output(output_key: str) -> str:
    return output_key.replace("_", " ")


def _load_json_manifest(path: Path) -> dict[str, Any]:
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Plan manifest must be a JSON object: {path}")
    return payload


def _plan_output_root(plan_manifest: Mapping[str, Any], *, manifest_file: Path) -> Path:
    output_root = Path(str(plan_manifest.get("output_root") or manifest_file.parent)).expanduser()
    if output_root.is_absolute():
        return output_root.resolve()
    return (manifest_file.parent / output_root).resolve()


def _resolve_plan_artifact_path(path: str | Path, *, output_root: Path) -> Path:
    artifact_path = Path(path).expanduser()
    if artifact_path.is_absolute():
        return artifact_path.resolve()
    return (output_root / artifact_path).resolve()


__all__ = [
    "REPORT_ARTIFACT_MANIFEST_OUTPUT_KEY",
    "SITE_SELECTION_PLAN_REPORT_PROFILE",
    "SITE_SELECTION_REPORT_PROFILE",
    "build_site_selection_plan_report_artifact_manifest",
    "build_site_selection_report_artifact_manifest",
    "write_site_selection_plan_report_artifact_manifest",
    "write_site_selection_report_artifact_manifest",
]
