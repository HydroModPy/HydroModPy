"""``--list-phases`` and ``--check`` show what each block compares with what.

Per objective block: its criterion, its normalised share, the simulated
quantity (support, variable, where) and the observed source: a station and
the ``[data.<family>]`` section it comes from for a point output that
``observes`` one, or the mapped file for a network output. A phase that scores
no block (or a phase-less calibration with none either) takes the
single-metric route, one row.

No solver runs: the table reads declarations only, which is also what lets
``--list-phases`` build it without the project's data on disk.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.calibration.config import validate_calib_output
from hydromodpy.calibration.runners.cli_runner import load_toml_calibration
from hydromodpy.calibration.runners.staged_runner import (
    _observed_source,
    objective_comparison_table,
    phase_summaries,
)

pytestmark = pytest.mark.fast

SECTION = """
[calibration]
max_iter = 5

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
transform = "log"
target = "flow.param.K.field.value"

[calibration.parameters.Sy]
bounds = [0.005, 0.35]
target = "flow.param.Sy.field.value"

[calibration.outputs.net]
support = "network"
stream_geometry_path = "streams.gpkg"

[calibration.outputs.gauge]
variable = "discharge"
support = "point"
x = 10.0
y = 20.0
observes = "G1"

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["net"]

[[calibration.objective_blocks]]
name = "hydrograph"
metric = "nse_log"
uses_outputs = ["gauge"]
"""

PHASES = """
[[calibration.phases]]
name = "k_network"
parameters = ["K"]
objective_blocks = ["network"]

[[calibration.phases]]
name = "sy_hydrograph"
parameters = ["Sy"]
objective_blocks = { hydrograph = 99, network = 1 }
depends_on = "k_network"
"""

SINGLE_METRIC_PHASE = """
[[calibration.phases]]
name = "sy_single"
parameters = ["Sy"]
variable = "discharge"
objective = "nse_log"
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "calibration.toml"
    path.write_text(text, encoding="utf-8")
    return path


def _config(tmp_path: Path, text: str):
    cfg, _raw = load_toml_calibration(_write(tmp_path, text))
    return cfg


def _rows_by_phase(cfg) -> dict[str, list[dict]]:
    return {row["name"]: row["comparisons"] for row in phase_summaries(cfg)}


def test_a_network_block_names_the_mapped_file(tmp_path: Path) -> None:
    cfg = _config(tmp_path, SECTION + PHASES)

    rows = _rows_by_phase(cfg)["k_network"]

    assert len(rows) == 1
    assert rows[0]["block"] == "network"
    assert rows[0]["metric"] == "distance_gap"
    assert rows[0]["share"] == pytest.approx(1.0)
    assert rows[0]["quantity"] == "release_flux (network)"
    assert rows[0]["source"].endswith("streams.gpkg")


def test_a_point_block_that_observes_names_the_station_and_its_data_family(
    tmp_path: Path,
) -> None:
    cfg = _config(tmp_path, SECTION + PHASES)

    rows = {row["block"]: row for row in _rows_by_phase(cfg)["sy_hydrograph"]}

    hydrograph = rows["hydrograph"]
    assert hydrograph["metric"] == "nse_log"
    assert hydrograph["quantity"] == "discharge (point, (10, 20))"
    assert hydrograph["source"] == "station G1 ([data.hydrometry])"


def test_a_share_table_normalises_like_the_composite_objective(tmp_path: Path) -> None:
    cfg = _config(tmp_path, SECTION + PHASES)

    rows = {row["block"]: row for row in _rows_by_phase(cfg)["sy_hydrograph"]}

    # weights 99 and 1, normalised: 0.99 and 0.01.
    assert rows["hydrograph"]["share"] == pytest.approx(0.99)
    assert rows["network"]["share"] == pytest.approx(0.01)
    assert sum(row["share"] for row in rows.values()) == pytest.approx(1.0)


def test_the_single_metric_route_is_one_row(tmp_path: Path) -> None:
    cfg = _config(tmp_path, SECTION + PHASES + SINGLE_METRIC_PHASE)

    rows = _rows_by_phase(cfg)["sy_single"]

    assert len(rows) == 1
    assert rows[0]["block"] is None
    assert rows[0]["metric"] == "nse_log"
    assert rows[0]["share"] == pytest.approx(1.0)
    assert "every loaded station" in rows[0]["source"]
    assert "[data.hydrometry]" in rows[0]["source"]


def test_a_phase_level_observed_station_id_names_the_station(tmp_path: Path) -> None:
    text = (
        SECTION
        + PHASES
        + SINGLE_METRIC_PHASE.replace(
            'objective = "nse_log"', 'objective = "nse_log"\nobserved_station_id = "G1"'
        )
    )
    cfg = _config(tmp_path, text)

    rows = _rows_by_phase(cfg)["sy_single"]

    assert rows[0]["source"] == "station G1 ([data.hydrometry])"


def test_a_phase_less_calibration_still_gets_a_table_for_its_one_search(
    tmp_path: Path,
) -> None:
    cfg = _config(tmp_path, SECTION)

    assert cfg.phases is None or cfg.phases == []
    rows = objective_comparison_table(cfg, None)

    assert {row["block"] for row in rows} == {"network", "hydrograph"}
    assert all(row["share"] == pytest.approx(0.5) for row in rows)


def test_list_phases_still_works_without_the_project_data_on_disk(tmp_path: Path) -> None:
    """``streams.gpkg`` is never written to ``tmp_path``: the table must not need it."""
    cfg = _config(tmp_path, SECTION + PHASES)

    rows = phase_summaries(cfg)

    assert [row["name"] for row in rows] == ["k_network", "sy_hydrograph"]
    assert all("comparisons" in row for row in rows)


def test_a_network_output_mapped_from_the_project_names_its_source(tmp_path: Path) -> None:
    text = SECTION.replace(
        'stream_geometry_path = "streams.gpkg"', 'observed_network = "data.hydrography"'
    )
    cfg = _config(tmp_path, text + PHASES)

    rows = _rows_by_phase(cfg)["k_network"]

    assert rows[0]["source"] == "data.hydrography"


def test_observed_values_with_no_observes_names_the_count() -> None:
    output = validate_calib_output(
        dict(
            variable="discharge",
            support="boundary",
            boundary_id="outlet",
            observed_values=[1.0, 2.0, 3.0],
        )
    )

    assert _observed_source(output) == "3 value(s) written in the file"


def test_nothing_declared_falls_back_to_saying_so() -> None:
    output = validate_calib_output(
        dict(variable="discharge", support="boundary", boundary_id="outlet")
    )

    assert _observed_source(output) == "nothing declared"
