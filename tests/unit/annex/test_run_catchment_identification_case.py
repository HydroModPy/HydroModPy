from __future__ import annotations

from pathlib import Path

from hydromodpy_annex.preprocess.catchment_identification_scan.run_catchment_identification_case import (
    _format_cli_summary,
)


def test_format_cli_summary_compact_mode_is_short_and_informative(tmp_path: Path) -> None:
    summary = {
        "basins_count": 12,
        "outlets_count": 12,
        "outlet_candidates_count": 87,
        "output_dir": str(tmp_path / "identification"),
        "outlets_csv_path": str(tmp_path / "identification" / "outlets.csv"),
        "figures_dir": str(tmp_path / "identification" / "figures"),
    }

    rendered = _format_cli_summary(
        summary,
        compact=True,
        summary_json_path=tmp_path / "identification" / "summary.json",
    )

    assert "Catchment identification completed:" in rendered
    assert "basins=12" in rendered
    assert "outlets=12" in rendered
    assert "candidates=87" in rendered
    assert "outlets_csv_path:" in rendered
    assert "summary_json_path:" in rendered
    assert "{" not in rendered


def test_format_cli_summary_full_mode_returns_json() -> None:
    summary = {
        "basins_count": 2,
        "outlets_count": 2,
    }

    rendered = _format_cli_summary(summary, compact=False)

    assert rendered.startswith("{")
    assert '"basins_count": 2' in rendered
