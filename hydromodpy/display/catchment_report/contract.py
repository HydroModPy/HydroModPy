"""Catchment-report adapter for the generic report artifact contract."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from hydromodpy.display.catchment_report.artifacts import (
    CopiedReportFigure,
    ReportArtifactSpec,
)
from hydromodpy.display.catchment_report.block_specs import ReportBlockSpec
from hydromodpy.display.catchment_report.resources import REPO_ROOT
from hydromodpy.display.catchment_report.semantic_artifacts import (
    SEMANTIC_ARTIFACT_ID_BY_FIGURE_ID,
    semantic_artifact_id,
)
from hydromodpy.display.report_artifacts import (
    ReportArtifact,
    ReportArtifactManifest,
    ReportArtifactRequirement,
)

CATCHMENT_GAUGED_PROFILE = "catchment_gauged"
REPORT_ARTIFACT_MANIFEST_NAME = "report_artifact_manifest.json"

def write_catchment_artifact_manifest(
    output_dir: Path,
    *,
    copied_figures: Mapping[str, Path],
    artifact_specs: Iterable[ReportArtifactSpec],
    block_specs: Sequence[ReportBlockSpec],
    context_summary: Path,
    source_manifest: Path,
    site_label: str,
    figure_provenance: Mapping[str, CopiedReportFigure] | None = None,
    upstream_artifact_manifest: Path | None = None,
    upstream_artifact_manifests: Iterable[Path] = (),
    profile: str = CATCHMENT_GAUGED_PROFILE,
) -> Path:
    """Write the generic artifact manifest alongside the block report manifest."""

    manifest = build_catchment_artifact_manifest(
        copied_figures=copied_figures,
        figure_provenance=figure_provenance,
        artifact_specs=artifact_specs,
        block_specs=block_specs,
        context_summary=context_summary,
        source_manifest=source_manifest,
        upstream_artifact_manifest=upstream_artifact_manifest,
        upstream_artifact_manifests=upstream_artifact_manifests,
        site_label=site_label,
        profile=profile,
    )
    return manifest.write_json(
        output_dir / REPORT_ARTIFACT_MANIFEST_NAME,
        base_dir=REPO_ROOT,
    )


def build_catchment_artifact_manifest(
    *,
    copied_figures: Mapping[str, Path],
    artifact_specs: Iterable[ReportArtifactSpec],
    block_specs: Sequence[ReportBlockSpec],
    context_summary: Path,
    source_manifest: Path,
    site_label: str,
    figure_provenance: Mapping[str, CopiedReportFigure] | None = None,
    upstream_artifact_manifest: Path | None = None,
    upstream_artifact_manifests: Iterable[Path] = (),
    profile: str = CATCHMENT_GAUGED_PROFILE,
) -> ReportArtifactManifest:
    requirements = (
        _context_summary_requirement(),
        *figure_requirements(artifact_specs=artifact_specs, block_specs=block_specs),
    )
    artifacts = tuple(
        ReportArtifact.from_requirement(
            requirement,
            path=_resolved_artifact_path(requirement, copied_figures, context_summary),
        )
        for requirement in requirements
    )
    return ReportArtifactManifest(
        profile=profile,
        requirements=requirements,
        artifacts=artifacts,
        source_manifest=source_manifest,
        metadata={
            "site_label": site_label,
            **_upstream_metadata(
                upstream_artifact_manifest,
                upstream_artifact_manifests,
            ),
            **_source_resolution_metadata(figure_provenance or {}),
        },
    )


def figure_requirements(
    *,
    artifact_specs: Iterable[ReportArtifactSpec],
    block_specs: Sequence[ReportBlockSpec],
) -> tuple[ReportArtifactRequirement, ...]:
    figure_contract = _figure_contract_from_blocks(block_specs)
    requirements: list[ReportArtifactRequirement] = []
    for spec in artifact_specs:
        block_contract = figure_contract.get(spec.figure_id, {})
        requirements.append(
            ReportArtifactRequirement(
                artifact_id=semantic_artifact_id(spec.figure_id),
                kind="figure",
                required=bool(block_contract.get("required", False)),
                title=str(block_contract.get("title", "")),
                producer=_producer_from_roots(candidate.root for candidate in spec.candidates),
                metadata={
                    "display_figure": spec.figure_id,
                    "candidate_paths": tuple(
                        f"{candidate.root}:{candidate.relative_path}"
                        for candidate in spec.candidates
                    ),
                    **_minimum_level_metadata(block_contract),
                },
            )
        )
    return tuple(requirements)


def _context_summary_requirement() -> ReportArtifactRequirement:
    return ReportArtifactRequirement(
        artifact_id="context.summary",
        kind="json",
        required=True,
        title="Resume contexte bassin",
        producer="catchment.context",
    )


def _resolved_artifact_path(
    requirement: ReportArtifactRequirement,
    copied_figures: Mapping[str, Path],
    context_summary: Path,
) -> Path | None:
    if requirement.artifact_id == "context.summary":
        return context_summary
    display_figure = str(requirement.metadata.get("display_figure", ""))
    return copied_figures.get(display_figure)


def _figure_contract_from_blocks(
    block_specs: Sequence[ReportBlockSpec],
) -> dict[str, dict[str, Any]]:
    contract: dict[str, dict[str, Any]] = {}
    for block in block_specs:
        for figure in block.figures:
            entry = contract.setdefault(
                figure.figure_id,
                {
                    "required": False,
                    "titles": [],
                    "minimum_levels": [],
                },
            )
            entry["required"] = bool(entry["required"] or figure.required)
            entry["titles"].append(figure.title)
            entry["minimum_levels"].append(figure.minimum_level)
    for figure_id, entry in contract.items():
        titles = tuple(dict.fromkeys(str(item) for item in entry["titles"]))
        levels = tuple(dict.fromkeys(str(item) for item in entry["minimum_levels"]))
        entry["title"] = titles[0] if titles else figure_id
        entry["titles"] = titles
        entry["minimum_levels"] = levels
    return contract


def _minimum_level_metadata(contract: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    levels = contract.get("minimum_levels")
    if isinstance(levels, tuple):
        return {"minimum_levels": levels}
    return {}


def _producer_from_roots(roots: Iterable[str]) -> str:
    roots = tuple(dict.fromkeys(roots))
    if roots == ("context_assets",):
        return "catchment.context"
    if roots == ("simulation_figures",):
        return "simulation.display"
    if all(root in {"overview_figures", "data_overview_figures"} for root in roots):
        return "data_overview.display"
    return "mixed"


def _upstream_metadata(
    path: Path | None,
    paths: Iterable[Path],
) -> dict[str, Any]:
    upstream_paths = _merged_upstream_paths(path, paths)
    if not upstream_paths:
        return {}
    formatted = tuple(_format_upstream_path(item) for item in upstream_paths)
    metadata: dict[str, Any] = {"upstream_artifact_manifest": formatted[0]}
    if len(formatted) > 1:
        metadata["upstream_artifact_manifests"] = formatted
    return metadata


def _merged_upstream_paths(
    path: Path | None,
    paths: Iterable[Path],
) -> tuple[Path, ...]:
    merged: list[Path] = []
    if path is not None:
        merged.append(Path(path))
    merged.extend(Path(item) for item in paths)
    deduped: list[Path] = []
    seen: set[Path] = set()
    for item in merged:
        resolved = item.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(resolved)
    return tuple(deduped)


def _format_upstream_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _source_resolution_metadata(
    provenance: Mapping[str, CopiedReportFigure],
) -> dict[str, Any]:
    if not provenance:
        return {}
    origins: dict[str, int] = {}
    for item in provenance.values():
        origins[item.source.origin] = origins.get(item.source.origin, 0) + 1
    return {
        "source_resolution": {
            "figure_count": len(provenance),
            "origin_counts": dict(sorted(origins.items())),
            "manifest_count": origins.get("manifest", 0),
        }
    }


__all__ = [
    "CATCHMENT_GAUGED_PROFILE",
    "REPORT_ARTIFACT_MANIFEST_NAME",
    "SEMANTIC_ARTIFACT_ID_BY_FIGURE_ID",
    "build_catchment_artifact_manifest",
    "figure_requirements",
    "write_catchment_artifact_manifest",
]
