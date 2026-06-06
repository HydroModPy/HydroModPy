from __future__ import annotations

from pathlib import Path
from typing import get_args

import pytest

from hydromodpy.spatial.site_selection.config import (
    CandidateMode,
    DemConfig,
    OutletsConfig,
    OutputConfig,
    SpatialSelectionConfig,
    StrategyProfile,
    WorkflowInputMode,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
ACTIVE_TEXT_TARGETS = [
    REPO_ROOT / "hydromodpy" / "spatial" / "site_selection",
    REPO_ROOT / "hydromodpy" / "workflow" / "site_selection.py",
    REPO_ROOT / "hydromodpy" / "cli" / "commands" / "site_selection.py",
    REPO_ROOT / "examples" / "projects" / "17_site_selection_workflow" / "configs",
]
FORBIDDEN_LEGACY_SNIPPETS = (
    "_normalize_report_mode",
    "candidate_outlets_from_rows",
    "write_candidates",
    "write_report_md",
    "write_report_html",
    "soft_score",
    "request_extent",
    "delineation_extent",
    "map_background_extent",
    "reference_network_max_distance_m",
    "snap_dist_m =",
    "reference_network_snap_tolerance_m =",
    "max_generated_candidates",
    "max_rejected_candidate_audit_records",
    "max_generated_network_cells",
    "snap_to_generated_stream",
    "generated_dem_network",
    'source = "data"',
    '"source": "data"',
    "same_mainstem_policy",
    "site_catalog_extent",
    "geoparquet_filter",
    'profile = "dem_only"',
    'profile = "multicriteria"',
    'mode = "report"',
    'mode = "auto"',
    'mode = "generated_candidates"',
    'mode = "dem_area_light"',
    "build-generated",
    "[site_selection.dem_area_light]",
    'candidate_mode = "imported_points"',
    'candidate_mode = "dem_area_target"',
)


def _iter_active_text_files():
    for target in ACTIVE_TEXT_TARGETS:
        if target.is_file():
            yield target
            continue
        for path in target.rglob("*"):
            if "__pycache__" in path.parts:
                continue
            if path.suffix in {".py", ".toml", ".md"}:
                yield path


@pytest.mark.fast
def test_removed_legacy_literals_stay_removed():
    assert "auto" not in get_args(WorkflowInputMode)
    assert "generated_candidates" not in get_args(WorkflowInputMode)
    assert "dem_area_light" not in get_args(WorkflowInputMode)
    assert {"dem_only", "multicriteria"}.isdisjoint(get_args(StrategyProfile))
    assert {"dem_area_target", "imported_points"}.isdisjoint(get_args(CandidateMode))
    assert "same_mainstem_policy" not in SpatialSelectionConfig.model_fields
    assert "write_candidates" not in OutputConfig.model_fields
    assert "write_report_md" not in OutputConfig.model_fields
    assert "request_extent" not in DemConfig.model_fields
    assert "delineation_extent" not in DemConfig.model_fields
    assert "map_background_extent" not in DemConfig.model_fields
    assert "reference_network_max_distance_m" not in OutletsConfig.model_fields
    assert "snap_dist_m" not in OutletsConfig.model_fields
    assert "reference_network_snap_tolerance_m" not in OutletsConfig.model_fields
    assert "max_generated_candidates" not in OutletsConfig.model_fields
    assert "max_rejected_candidate_audit_records" not in OutletsConfig.model_fields
    assert "max_generated_network_cells" not in OutletsConfig.model_fields
    assert "snap_to_generated_stream" not in OutletsConfig.model_fields


@pytest.mark.fast
def test_active_site_selection_files_do_not_reintroduce_legacy_tokens():
    offenders: list[str] = []
    for path in _iter_active_text_files():
        text = path.read_text(encoding="utf-8")
        for snippet in FORBIDDEN_LEGACY_SNIPPETS:
            if snippet in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {snippet}")

    assert offenders == []


@pytest.mark.fast
def test_dem_area_target_examples_declare_profile_and_area_criteria():
    config_dir = (
        REPO_ROOT / "examples" / "projects" / "17_site_selection_workflow" / "configs"
    )
    configs = sorted(
        path
        for path in config_dir.glob("*.toml")
        if 'mode = "dem_area_target"' in path.read_text(encoding="utf-8")
    )
    assert configs

    for path in configs:
        text = path.read_text(encoding="utf-8")
        assert 'mode = "dem_area_target"' in text
        assert '[site_selection.strategy]' in text
        assert 'profile = "area_only"' in text
        assert "[site_selection.criteria.area]" in text
