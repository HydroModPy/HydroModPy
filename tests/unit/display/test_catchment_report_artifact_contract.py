from __future__ import annotations

from pathlib import Path

from hydromodpy.display.catchment_report.artifacts import (
    DEFAULT_ARTIFACT_SPECS,
    copy_real_figures,
    copy_real_figures_with_provenance,
)
from hydromodpy.display.catchment_report.block_specs import DEFAULT_BLOCK_SPECS
from hydromodpy.display.catchment_report.contract import (
    build_catchment_artifact_manifest,
    figure_requirements,
)
from hydromodpy.display.report_artifacts import (
    ReportArtifact,
    ReportArtifactManifest,
    ReportArtifactRequirement,
)


def test_catchment_artifact_contract_uses_semantic_ids() -> None:
    requirements = figure_requirements(
        artifact_specs=DEFAULT_ARTIFACT_SPECS,
        block_specs=DEFAULT_BLOCK_SPECS,
    )
    by_display_figure = {
        requirement.metadata["display_figure"]: requirement for requirement in requirements
    }

    assert by_display_figure["simulated_hydrograph"].artifact_id == (
        "simulation.discharge.timeseries"
    )
    assert by_display_figure["water_budget"].artifact_id == "simulation.water_budget.figure"
    assert by_display_figure["network_generated"].required is False
    assert by_display_figure["simulated_hydrograph"].required is True


def test_catchment_artifact_manifest_reports_context_summary_and_missing_figures(tmp_path) -> None:
    context_summary = tmp_path / "context_summary.json"
    context_summary.write_text("{}\n", encoding="utf-8")
    source_manifest = tmp_path / "block_report_manifest.json"
    source_manifest.write_text("{}\n", encoding="utf-8")

    manifest = build_catchment_artifact_manifest(
        copied_figures={},
        artifact_specs=DEFAULT_ARTIFACT_SPECS,
        block_specs=DEFAULT_BLOCK_SPECS,
        context_summary=context_summary,
        source_manifest=source_manifest,
        site_label="Test",
    )

    payload = manifest.to_dict(base_dir=tmp_path)

    assert payload["profile"] == "catchment_gauged"
    assert payload["source_manifest"] == "block_report_manifest.json"
    assert "context.summary" not in manifest.missing_required
    assert "simulation.discharge.timeseries" in manifest.missing_required


def test_catchment_artifact_manifest_reports_source_resolution(tmp_path) -> None:
    context_summary = tmp_path / "context_summary.json"
    context_summary.write_text("{}\n", encoding="utf-8")
    source_manifest = tmp_path / "block_report_manifest.json"
    source_manifest.write_text("{}\n", encoding="utf-8")
    report_figures = tmp_path / "report" / "figures"
    report_figures.mkdir(parents=True)
    hydrograph = tmp_path / "hydrograph.png"
    hydrograph.write_bytes(b"source")
    requirement = ReportArtifactRequirement(
        "simulation.discharge.timeseries",
        kind="figure",
        metadata={"display_figure": "hydrograph"},
    )
    upstream_manifest = ReportArtifactManifest(
        profile="catchment_gauged",
        requirements=(requirement,),
        artifacts=(ReportArtifact.from_requirement(requirement, path=hydrograph),),
    ).write_json(
        tmp_path / "report_artifact_manifest.json",
        base_dir=tmp_path,
    )
    copied, provenance = copy_real_figures_with_provenance(
        report_figures,
        context_assets=tmp_path / "context_assets",
        overview_figures=tmp_path / "overview_figures",
        data_overview_figures=tmp_path / "data_overview_figures",
        simulation_figures=tmp_path / "simulation_figures",
        source_artifact_manifest=upstream_manifest,
    )

    manifest = build_catchment_artifact_manifest(
        copied_figures=copied,
        figure_provenance=provenance,
        artifact_specs=DEFAULT_ARTIFACT_SPECS,
        block_specs=DEFAULT_BLOCK_SPECS,
        context_summary=context_summary,
        source_manifest=source_manifest,
        site_label="Test",
    )

    assert manifest.metadata["source_resolution"]["manifest_count"] == 1


def test_copy_real_figures_prefers_source_manifest_artifact(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    source_figures = workspace / "figures" / "run_001"
    source_figures.mkdir(parents=True)
    source_hydrograph = source_figures / "source_hydrograph.png"
    source_hydrograph.write_bytes(b"source")
    requirement = ReportArtifactRequirement(
        "simulation.discharge.timeseries",
        kind="figure",
        metadata={"display_figure": "hydrograph"},
    )
    source_manifest = ReportArtifactManifest(
        profile="catchment_gauged",
        requirements=(requirement,),
        artifacts=(ReportArtifact.from_requirement(requirement, path=source_hydrograph),),
    ).write_json(
        source_figures / "report_artifact_manifest.json",
        base_dir=workspace,
    )

    configured_simulation_figures = tmp_path / "configured" / "simulation_figures"
    configured_simulation_figures.mkdir(parents=True)
    (configured_simulation_figures / "hydrograph.png").write_bytes(b"configured")
    report_figures = tmp_path / "report" / "figures"
    report_figures.mkdir(parents=True)

    copied = copy_real_figures(
        report_figures,
        context_assets=tmp_path / "context_assets",
        overview_figures=tmp_path / "overview_figures",
        data_overview_figures=tmp_path / "data_overview_figures",
        simulation_figures=configured_simulation_figures,
        source_artifact_manifest=source_manifest,
    )

    assert copied["simulated_hydrograph"].read_bytes() == b"source"


def test_copy_real_figures_tracks_manifest_provenance(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    source_figures = workspace / "figures" / "run_001"
    source_figures.mkdir(parents=True)
    source_hydrograph = source_figures / "source_hydrograph.png"
    source_hydrograph.write_bytes(b"source")
    requirement = ReportArtifactRequirement(
        "simulation.discharge.timeseries",
        kind="figure",
        metadata={"display_figure": "hydrograph"},
    )
    source_manifest = ReportArtifactManifest(
        profile="catchment_gauged",
        requirements=(requirement,),
        artifacts=(ReportArtifact.from_requirement(requirement, path=source_hydrograph),),
    ).write_json(
        source_figures / "report_artifact_manifest.json",
        base_dir=workspace,
    )
    report_figures = tmp_path / "report" / "figures"
    report_figures.mkdir(parents=True)

    _copied, provenance = copy_real_figures_with_provenance(
        report_figures,
        context_assets=tmp_path / "context_assets",
        overview_figures=tmp_path / "overview_figures",
        data_overview_figures=tmp_path / "data_overview_figures",
        simulation_figures=tmp_path / "simulation_figures",
        source_artifact_manifest=source_manifest,
    )

    assert provenance["simulated_hydrograph"].source.origin == "manifest"
    assert provenance["simulated_hydrograph"].source.source_key == (
        "simulation.discharge.timeseries"
    )


def test_copy_real_figures_requires_manifest_source(
    tmp_path: Path,
) -> None:
    simulation_figures = tmp_path / "simulation_figures"
    simulation_figures.mkdir()
    (simulation_figures / "hydrograph.png").write_bytes(b"configured")
    report_figures = tmp_path / "report" / "figures"
    report_figures.mkdir(parents=True)

    copied, provenance = copy_real_figures_with_provenance(
        report_figures,
        context_assets=tmp_path / "context_assets",
        overview_figures=tmp_path / "overview_figures",
        data_overview_figures=tmp_path / "data_overview_figures",
        simulation_figures=simulation_figures,
    )

    assert "simulated_hydrograph" not in copied
    assert "simulated_hydrograph" not in provenance


def test_copy_real_figures_prefers_manifest_for_overview_artifact(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    overview_dir = workspace / "overview"
    overview_dir.mkdir(parents=True)
    source_map = overview_dir / "regional_context_from_manifest.png"
    source_map.write_bytes(b"source-overview")
    requirement = ReportArtifactRequirement(
        "catchment.context.regional_map",
        kind="figure",
    )
    source_manifest = ReportArtifactManifest(
        profile="catchment_gauged",
        requirements=(requirement,),
        artifacts=(ReportArtifact.from_requirement(requirement, path=source_map),),
    ).write_json(
        workspace / "report_artifact_manifest.json",
        base_dir=workspace,
    )

    configured_overview = tmp_path / "configured" / "overview_figures"
    configured_overview.mkdir(parents=True)
    (configured_overview / "map_regional_context.png").write_bytes(b"configured-overview")
    report_figures = tmp_path / "report" / "figures"
    report_figures.mkdir(parents=True)

    copied = copy_real_figures(
        report_figures,
        context_assets=tmp_path / "context_assets",
        overview_figures=configured_overview,
        data_overview_figures=tmp_path / "data_overview_figures",
        simulation_figures=tmp_path / "simulation_figures",
        source_artifact_manifest=source_manifest,
    )

    assert copied["regional_context"].read_bytes() == b"source-overview"
