"""The catchment report context reads the run, whatever solver made it.

The cell count comes from the simulated run, not from a solver section of the
TOML. A context figure that cannot be drawn is logged with its name and the
reason, instead of disappearing from the report without a word.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.core.logging import get_logger


@pytest.fixture
def hmp_log_records():
    """Capture ``hydromodpy`` records (the parent logger disables propagation)."""
    parent = get_logger("hydromodpy")
    previous_level = parent.level
    parent.setLevel(logging.DEBUG)
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture(level=logging.DEBUG)
    parent.addHandler(handler)
    try:
        yield records
    finally:
        parent.removeHandler(handler)
        parent.setLevel(previous_level)


def _inputs(tmp_path: Path) -> SimpleNamespace:
    transient = tmp_path / "transient.toml"
    transient.write_text('[workflow]\nmode = "simulation"\n', encoding="utf-8")
    return SimpleNamespace(
        context_summary=tmp_path / "context" / "context_summary.json",
        context_assets=tmp_path / "web" / "assets",
        transient_config=transient,
        observed_discharge_path=None,
        observed_discharge_station_id=None,
        simulation_figures=tmp_path / "figures",
        simulation_name="baseline",
        site_label="Nancon",
    )


@pytest.mark.parametrize("n_cells", [4321, None])
def test_the_cell_count_is_the_one_of_the_simulated_run(monkeypatch, tmp_path, n_cells) -> None:
    """The TOML holds no ``[modflownwt]``, as for any MODFLOW 6 or Boussinesq run."""
    import hydromodpy.display.catchment_report.context as context_module

    @contextmanager
    def open_run(inputs):
        yield object(), SimpleNamespace(n_cells=n_cells)

    discharge = pd.DataFrame(
        {"datetime": pd.date_range("2020-01-01", periods=3, freq="D"), "value": [1.0, 2.0, 3.0]}
    )
    monkeypatch.setattr(context_module, "open_simulation_run", open_run)
    monkeypatch.setattr(context_module, "read_simulated_discharge", lambda run: discharge)
    monkeypatch.setattr(context_module, "simulation_parquet_dir", lambda catalog, run: None)

    summary_path = context_module.build_context(_inputs(tmp_path))

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["baseline_run"]["n_cells"] == n_cells


def test_an_unreadable_generated_network_is_logged_by_figure_name(
    tmp_path, hmp_log_records
) -> None:
    from hydromodpy.display.catchment_report.artifacts import (
        generate_generated_network_context_figure,
    )
    from hydromodpy.results.storage.contract import PARQUET_FILE_SUFFIX, TABLES_DIRNAME

    runs = tmp_path / "runs"
    tables = runs / "baseline" / TABLES_DIRNAME
    tables.mkdir(parents=True)
    (tables / f"geographic_hydrographic_network_generated{PARQUET_FILE_SUFFIX}").write_bytes(
        b"not parquet"
    )
    scratch = tmp_path / "geographic"
    scratch.mkdir()
    (scratch / "watershed_box_buff_dem.tif").write_bytes(b"not a raster")
    (scratch / "watershed.shp").write_bytes(b"not a shapefile")
    copied: dict[str, Path] = {}

    generate_generated_network_context_figure(
        copied,
        figures_dir=tmp_path / "figures",
        config={},
        generated_network_root=runs,
        geographic_scratch=scratch,
    )

    assert copied == {}
    warnings = [r.getMessage() for r in hmp_log_records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "context figure 'network_generated' skipped" in warnings[0]


def test_a_missing_generated_network_is_logged_as_information(tmp_path, hmp_log_records) -> None:
    """The figure is optional: saying why it is absent must not read as a fault."""
    from hydromodpy.display.catchment_report.artifacts import (
        generate_generated_network_context_figure,
    )

    generate_generated_network_context_figure(
        {},
        figures_dir=tmp_path / "figures",
        config={},
        generated_network_root=tmp_path / "runs",
        geographic_scratch=tmp_path / "geographic",
    )

    messages = [(r.levelno, r.getMessage()) for r in hmp_log_records]
    assert [level for level, _ in messages] == [logging.INFO]
    assert (
        "context figure 'network_generated' not drawn, missing the generated network"
        in (messages[0][1])
    )
