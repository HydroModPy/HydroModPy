"""Report profile helpers shared by simulation display and HTML builders."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from hydromodpy.display.report_artifacts import (
    ReportArtifact,
    ReportArtifactManifest,
    ReportArtifactRequirement,
)

REPORT_ARTIFACT_MANIFEST_NAME = "report_artifact_manifest.json"

CATCHMENT_GAUGED_DISPLAY_FIGURES: tuple[str, ...] = (
    "piezometric_map",
    "water_budget",
    "hydrograph",
    "seepage_map",
    "hydrographic_network_reference",
    "hydrographic_network_generated",
    "hydrographic_network_comparison",
    "hydrographic_network_reference_missing_only",
    "hydrographic_network_generated_extra_only",
    "simulated_active_network_reference_overlay",
)

DISPLAY_FIGURES_BY_PROFILE: Mapping[str, tuple[str, ...]] = {
    "catchment_gauged": CATCHMENT_GAUGED_DISPLAY_FIGURES,
    "generic_simulation": (),
    "site_selection": (),
}

SEMANTIC_ARTIFACT_ID_BY_DISPLAY_FIGURE: Mapping[str, str] = {
    "piezometric_map": "simulation.head.piezometric_map",
    "water_budget": "simulation.water_budget.figure",
    "hydrograph": "simulation.discharge.timeseries",
    "seepage_map": "simulation.seepage.map",
    "hydrographic_network_reference": "network.hydrography.reference",
    "hydrographic_network_generated": "network.hydrography.generated",
    "hydrographic_network_comparison": "network.hydrography.reference_generated_comparison",
    "hydrographic_network_reference_missing_only": (
        "network.hydrography.reference_missing_from_generated"
    ),
    "hydrographic_network_generated_extra_only": "network.hydrography.generated_extra",
    "simulated_active_network_reference_overlay": (
        "simulation.network.active_reference_overlay"
    ),
}


def report_html_is_enabled(report_cfg: Any) -> bool:
    html = getattr(report_cfg, "html", None)
    return bool(
        html is not None
        and (getattr(html, "enabled", False) or getattr(html, "build_at_end", False))
    )


def report_html_is_strict(report_cfg: Any) -> bool:
    html = getattr(report_cfg, "html", None)
    return bool(html is not None and getattr(html, "strict", False))


def report_profile_name(report_cfg: Any) -> str:
    html = getattr(report_cfg, "html", None)
    return str(getattr(html, "profile", "catchment_gauged") or "catchment_gauged")


def required_display_figures_for_report(report_cfg: Any) -> tuple[str, ...]:
    """Return display figures required by the active report profile."""

    if not report_html_is_enabled(report_cfg):
        return ()
    return DISPLAY_FIGURES_BY_PROFILE.get(report_profile_name(report_cfg), ())


def merge_display_figures(
    configured_figures: Sequence[str],
    report_cfg: Any,
) -> list[str]:
    """Merge configured display figures with profile-required report figures."""

    merged = list(configured_figures)
    for figure_name in required_display_figures_for_report(report_cfg):
        if figure_name not in merged:
            merged.append(figure_name)
    return merged


def effective_display_config_for_report(
    display_cfg: Any,
    report_cfg: Any,
    *,
    figures: Sequence[str],
) -> Any:
    """Return a display config copy that can render report-required artifacts."""

    if not report_html_is_enabled(report_cfg):
        return display_cfg
    updates = {
        "enabled": True,
        "save": True,
        "figures": list(figures),
    }
    flow = getattr(display_cfg, "flow", None)
    if report_profile_name(report_cfg) == "catchment_gauged" and flow is not None:
        flow_updates = {
            "enabled": True,
            "streamflow": True,
            "piezometry": True,
            "budget": True,
            "hydrography": True,
            "boussinesq_state": True,
        }
        updates["flow"] = _copy_config(flow, **flow_updates)
    return _copy_config(display_cfg, **updates)


def write_display_report_artifact_manifest(
    output_dir: Path,
    *,
    profile: str,
    requested_figures: Sequence[str],
    rendered_figures: Sequence[Path],
    base_dir: Path,
) -> Path:
    rendered_by_name = {path.stem: path for path in rendered_figures}
    requirements = tuple(
        ReportArtifactRequirement(
            artifact_id=SEMANTIC_ARTIFACT_ID_BY_DISPLAY_FIGURE.get(
                figure_name,
                f"simulation.figure.{figure_name}",
            ),
            kind="figure",
            required=True,
            title=figure_name,
            producer="simulation.display",
            metadata={"display_figure": figure_name},
        )
        for figure_name in requested_figures
    )
    manifest = ReportArtifactManifest(
        profile=profile,
        requirements=requirements,
        artifacts=tuple(
            ReportArtifact.from_requirement(
                requirement,
                path=rendered_by_name.get(str(requirement.metadata["display_figure"])),
            )
            for requirement in requirements
        ),
        metadata={
            "artifact_scope": "simulation.display",
            "simulation_name": output_dir.name,
            "simulation_figures": _format_metadata_path(output_dir, base_dir=base_dir),
        },
    )
    return manifest.write_json(
        output_dir / REPORT_ARTIFACT_MANIFEST_NAME,
        base_dir=base_dir,
    )


def _copy_config(config: Any, **updates: Any) -> Any:
    if hasattr(config, "model_copy"):
        return config.model_copy(update=updates)
    clone = copy.copy(config)
    for key, value in updates.items():
        setattr(clone, key, value)
    return clone


def _format_metadata_path(path: Path, *, base_dir: Path) -> str:
    try:
        return path.resolve().relative_to(base_dir.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


__all__ = [
    "CATCHMENT_GAUGED_DISPLAY_FIGURES",
    "DISPLAY_FIGURES_BY_PROFILE",
    "REPORT_ARTIFACT_MANIFEST_NAME",
    "SEMANTIC_ARTIFACT_ID_BY_DISPLAY_FIGURE",
    "effective_display_config_for_report",
    "merge_display_figures",
    "report_html_is_enabled",
    "report_html_is_strict",
    "report_profile_name",
    "required_display_figures_for_report",
    "write_display_report_artifact_manifest",
]
