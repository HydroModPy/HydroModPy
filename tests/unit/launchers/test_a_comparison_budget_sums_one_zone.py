"""A comparison budget sums one zone of the budget table, and says which.

A run that carries a catchment keeps two rows per component and step, one for
the model domain and one for the whole faces of the basin of D inside it.
Adding them counts the water of the basin twice. The export reads the zone the
comparison asks for, the domain by default, and labels it in every row.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from pydantic import ValidationError

from hydromodpy.analysis.comparison.config import ComparisonSpec
from hydromodpy.analysis.comparison.exports import (
    _load_table_budget_rows,
    write_budget_exports,
)

from ._comparison_builders import (
    _FakeSource,
    _serve_sources,
    _spec_from_toml,
    _write_boussinesq_run_folder,
    _write_simulation_comparison_config,
)

DOMAIN_RECHARGE, DOMAIN_DRAIN = 10.0, 4.0
BASIN_RECHARGE, BASIN_DRAIN = 3.0, 1.5


def _table(zones: tuple[str, ...]) -> pd.DataFrame:
    values = {"0": (DOMAIN_RECHARGE, DOMAIN_DRAIN), "catchment": (BASIN_RECHARGE, BASIN_DRAIN)}
    rows = []
    for zone in zones:
        recharge, drain = values[zone]
        rows += [
            {"timestep": 0, "zone_id": zone, "component": "rcha", "flux_in": recharge},
            {"timestep": 0, "zone_id": zone, "component": "drn", "flux_out": drain},
        ]
    frame = pd.DataFrame(rows).fillna(0.0)
    frame["unit"] = "m3/s"
    return frame


class _BudgetSource(_FakeSource):
    """A run source whose budget table holds the zones given."""

    def __init__(self, run_dir: Path, zones: tuple[str, ...]) -> None:
        super().__init__(run_dir, {})
        self._zones = zones

    def query_budget(self, sim_id: str | None = None, **_: Any) -> pd.DataFrame:
        return _table(self._zones)


class _Store:
    """The one verb ``_load_table_budget_rows`` calls."""

    def __init__(self, zones: tuple[str, ...]) -> None:
        self._zones = zones

    def query_budget(self, sim_id: str) -> pd.DataFrame:
        return _table(self._zones)


def _by_component(rows: list[dict[str, Any]]) -> dict[str, float]:
    return {str(row["component"]): float(row["value"]) for row in rows}


def _summary(run_dir: Path, **extra: Any) -> dict[str, Any]:
    return {
        "id": "mf6",
        "label": "MF6",
        "solver": "modflow6",
        "mesh_mode": "voronoi",
        "status": "completed",
        "run_folder": str(run_dir),
        "run_dir": str(run_dir),
        **extra,
    }


def test_the_domain_is_read_by_default_and_never_added_to_the_catchment() -> None:
    rows = _load_table_budget_rows({"solver": "modflow6"}, _Store(("0", "catchment")), "sim")

    values = _by_component(rows)
    assert values["recharge_total_m3_s"] == pytest.approx(DOMAIN_RECHARGE)
    assert values["drainage_total_m3_s"] == pytest.approx(DOMAIN_DRAIN)


def test_the_catchment_is_read_when_asked() -> None:
    rows = _load_table_budget_rows(
        {"solver": "modflow6"}, _Store(("0", "catchment")), "sim", "catchment"
    )

    values = _by_component(rows)
    assert values["recharge_total_m3_s"] == pytest.approx(BASIN_RECHARGE)
    assert values["drainage_total_m3_s"] == pytest.approx(BASIN_DRAIN)


def test_a_run_with_no_row_in_the_asked_zone_gives_none_and_says_so(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        rows = _load_table_budget_rows({"solver": "modflow6"}, _Store(("0",)), "sim-x", "catchment")

    assert rows == []
    assert "Run sim-x has no 'catchment' budget zone" in caplog.text


@pytest.mark.parametrize(
    ("zone", "recharge"),
    [("domain", DOMAIN_RECHARGE), ("catchment", BASIN_RECHARGE)],
)
def test_every_exported_row_names_its_zone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, zone: str, recharge: float
) -> None:
    run_dir = tmp_path / "run_mf6"
    run_dir.mkdir()
    _serve_sources(monkeypatch, [_BudgetSource(run_dir, ("0", "catchment"))])

    _, rows = write_budget_exports(
        comparison_root=tmp_path / "comparison",
        simulation_summaries=[_summary(run_dir)],
        budget_zone=zone,  # type: ignore[arg-type]
    )

    assert {row["budget_zone"] for row in rows} == {zone}
    assert _by_component(rows)["recharge_total_m3_s"] == pytest.approx(recharge)
    for name in ("budget_timeseries_long.csv", "budget_timeseries_wide.csv"):
        with (tmp_path / "comparison" / name).open(encoding="utf-8") as handle:
            written = list(csv.DictReader(handle))
        assert {row["budget_zone"] for row in written} == {zone}


def test_the_default_zone_is_the_domain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_dir = tmp_path / "run_mf6"
    run_dir.mkdir()
    _serve_sources(monkeypatch, [_BudgetSource(run_dir, ("0", "catchment"))])

    _, rows = write_budget_exports(
        comparison_root=tmp_path / "comparison",
        simulation_summaries=[_summary(run_dir)],
    )

    assert {row["budget_zone"] for row in rows} == {"domain"}
    assert _by_component(rows)["recharge_total_m3_s"] == pytest.approx(DOMAIN_RECHARGE)


def test_a_boussinesq_state_is_the_domain_and_leaves_a_catchment_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    run_folder = tmp_path / "run_bouss"
    store = _write_boussinesq_run_folder(run_folder)
    config_path = tmp_path / "run_bouss.toml"
    config_path.write_text("[flow.param.Sy]\nvalue = 0.08\n", encoding="utf-8")
    _serve_sources(monkeypatch, [store])
    summary = _summary(run_folder, id="bouss", solver="boussinesq", config_path=str(config_path))

    _, domain = write_budget_exports(
        comparison_root=tmp_path / "domain", simulation_summaries=[summary]
    )
    with caplog.at_level(logging.WARNING):
        _, catchment = write_budget_exports(
            comparison_root=tmp_path / "catchment",
            simulation_summaries=[summary],
            budget_zone="catchment",
        )

    assert domain
    assert {row["budget_zone"] for row in domain} == {"domain"}
    assert catchment == []
    assert "has no 'catchment' budget zone" in caplog.text


def test_a_comparison_spec_asks_for_the_domain_unless_told_otherwise(tmp_path: Path) -> None:
    config = tmp_path / "comparison.toml"
    _write_simulation_comparison_config(config, tmp_path)
    spec = _spec_from_toml(config)

    assert spec.budget_zone == "domain"
    assert spec.model_copy(update={"budget_zone": "catchment"}).budget_zone == "catchment"
    with pytest.raises(ValidationError):
        ComparisonSpec.model_validate({**spec.model_dump(), "budget_zone": "basin"})
