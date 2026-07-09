from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.display.report_artifacts import (
    HtmlReportIntent,
    ReportArtifact,
    ReportArtifactIndex,
    ReportArtifactManifest,
    ReportArtifactRequirement,
)


def test_html_report_intent_build_at_end_implies_enabled() -> None:
    intent = HtmlReportIntent.from_mapping(
        {"build_at_end": True, "profile": "catchment_gauged"},
    )

    assert intent.enabled is True
    assert intent.build_at_end is True
    assert intent.profile == "catchment_gauged"
    assert intent.strict is False


def test_html_report_intent_explicit_enabled_can_prepare_without_building() -> None:
    intent = HtmlReportIntent.from_mapping(
        {"enabled": True, "profile": "catchment_gauged"},
    )

    assert intent.enabled is True
    assert intent.build_at_end is False
    assert intent.strict is False


def test_html_report_intent_rejects_non_boolean_flags() -> None:
    with pytest.raises(ValueError, match="build_at_end"):
        HtmlReportIntent.from_mapping({"build_at_end": "yes"})


def test_report_artifact_manifest_summarizes_missing_required(tmp_path: Path) -> None:
    present = tmp_path / "figure.png"
    present.write_bytes(b"png")
    requirements = (
        ReportArtifactRequirement("simulation.discharge.timeseries", kind="figure"),
        ReportArtifactRequirement(
            "simulation.water_budget.figure",
            kind="figure",
            required=False,
        ),
    )
    manifest = ReportArtifactManifest(
        profile="catchment_gauged",
        requirements=requirements,
        artifacts=(
            ReportArtifact.from_requirement(requirements[0], path=present),
            ReportArtifact.from_requirement(requirements[1], path=None),
        ),
    )

    payload = manifest.to_dict(base_dir=tmp_path)

    assert manifest.missing_required == ()
    assert manifest.missing_optional == ("simulation.water_budget.figure",)
    assert payload["summary"] == {
        "artifact_count": 2,
        "missing_optional_count": 1,
        "missing_required_count": 0,
        "present_count": 1,
        "requirement_count": 2,
    }
    assert payload["artifacts"][0]["path"] == "figure.png"


def test_report_artifact_index_resolves_display_manifest_relative_paths(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    figures_dir = workspace / "figures" / "run_001"
    figures_dir.mkdir(parents=True)
    hydrograph = figures_dir / "hydrograph.png"
    hydrograph.write_bytes(b"manifest")
    requirement = ReportArtifactRequirement(
        "simulation.discharge.timeseries",
        kind="figure",
        metadata={"display_figure": "hydrograph"},
    )
    manifest_path = ReportArtifactManifest(
        profile="catchment_gauged",
        requirements=(requirement,),
        artifacts=(ReportArtifact.from_requirement(requirement, path=hydrograph),),
    ).write_json(
        figures_dir / "report_artifact_manifest.json",
        base_dir=workspace,
    )

    index = ReportArtifactIndex.from_manifest(manifest_path)

    assert index.get("simulation.discharge.timeseries") == hydrograph.resolve()
    assert index.get("hydrograph") == hydrograph.resolve()


def test_report_artifact_index_merges_manifests_with_first_manifest_priority(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    first_figure = first / "figure.png"
    second_figure = second / "figure.png"
    extra_figure = second / "extra.png"
    first_figure.write_bytes(b"first")
    second_figure.write_bytes(b"second")
    extra_figure.write_bytes(b"extra")
    requirement = ReportArtifactRequirement("shared.figure", kind="figure")
    extra_requirement = ReportArtifactRequirement("extra.figure", kind="figure")
    first_manifest = ReportArtifactManifest(
        profile="catchment_gauged",
        requirements=(requirement,),
        artifacts=(ReportArtifact.from_requirement(requirement, path=first_figure),),
    ).write_json(first / "report_artifact_manifest.json", base_dir=tmp_path)
    second_manifest = ReportArtifactManifest(
        profile="catchment_gauged",
        requirements=(requirement, extra_requirement),
        artifacts=(
            ReportArtifact.from_requirement(requirement, path=second_figure),
            ReportArtifact.from_requirement(extra_requirement, path=extra_figure),
        ),
    ).write_json(second / "report_artifact_manifest.json", base_dir=tmp_path)

    index = ReportArtifactIndex.from_manifests(
        (first_manifest, second_manifest),
        base_dir=tmp_path,
    )

    assert index.get("shared.figure") == first_figure.resolve()
    assert index.get("extra.figure") == extra_figure.resolve()
