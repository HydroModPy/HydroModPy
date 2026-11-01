"""The site selection code and its command name none of the retired tokens."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
ACTIVE_TEXT_TARGETS = [
    REPO_ROOT / "hydromodpy" / "site_selection",
    REPO_ROOT / "hydromodpy" / "workflow" / "site_selection",
    REPO_ROOT / "hydromodpy" / "cli" / "commands" / "site",
]
FORBIDDEN_LEGACY_SNIPPETS = (
    "_normalize_report_mode", "candidate_outlets_from_rows", "write_candidates", "write_report_md",
    "same_mainstem_policy", "site_catalog_extent", "geoparquet_filter", 'profile = "dem_only"',
    'profile = "multicriteria"', 'mode = "report"', 'mode = "auto"',
    'candidate_mode = "imported_points"', 'candidate_mode = "dem_area_light"',
)  # fmt: skip


@pytest.mark.fast
def test_active_site_selection_files_do_not_reintroduce_legacy_tokens():
    offenders = [
        f"{path.relative_to(REPO_ROOT)}: {snippet}"
        for target in ACTIVE_TEXT_TARGETS
        for path in target.rglob("*")
        if "__pycache__" not in path.parts and path.suffix in {".py", ".toml", ".md"}
        for snippet in FORBIDDEN_LEGACY_SNIPPETS
        if snippet in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
