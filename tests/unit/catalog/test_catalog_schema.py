"""Schema-discovery and single-door behaviour of ``hmp.open`` (interface refactor)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

import hydromodpy as hmp

pytestmark = pytest.mark.fast


def _seed(cat, *, project: str = "naizin", solver: str = "modflow6", nse: float = 0.8) -> str:
    sim_id = str(uuid4())
    cat.register_simulation(
        sim_id=sim_id, project=project, solver=solver, name="demo", flow_regime="transient"
    )
    cat.write_metric(sim_id, station_id="P01", metric_name="nse", value=nse)
    cat.finalize(sim_id, status="completed", duration_s=0.0)
    return sim_id


def test_open_is_single_door_with_objects_and_frame(tmp_path: Path) -> None:
    with hmp.open(tmp_path, create=True) as cat:
        sim_id = _seed(cat)
        group = cat.find(solver="modflow6")
        assert isinstance(group, hmp.SimulationGroup)
        assert group.sim_ids == [sim_id]
        assert len(cat.frame) == 1
        assert cat[sim_id].project == "naizin"


def test_find_unknown_filter_lists_valid_keys(tmp_path: Path) -> None:
    with hmp.open(tmp_path, create=True) as cat:
        _seed(cat)
        with pytest.raises(ValueError, match="Unknown filter"):
            cat.find(catchment="x")


def test_schema_discovery(tmp_path: Path) -> None:
    with hmp.open(tmp_path, create=True) as cat:
        _seed(cat)
        assert "simulations" in cat.tables()
        assert "metrics" in cat.tables()
        assert "project" in cat.columns("simulations")
        assert "nse" in cat.metrics()
        assert "P01" in cat.stations()
        # Zarr field names are always available even without persisted fields.
        assert cat.variables()


def test_describe_is_human_readable(tmp_path: Path) -> None:
    with hmp.open(tmp_path, create=True) as cat:
        _seed(cat)
        text = cat.describe()
        assert "simulations : 1" in text
        assert "naizin" in text
        assert "modflow6" in text


def test_inputs_namespace_via_catalog_package(tmp_path: Path) -> None:
    from hydromodpy.catalog import InputsNamespace

    inputs = InputsNamespace(tmp_path)
    assert inputs.has_cache() is False
    assert inputs.db_path == (tmp_path.resolve() / "data" / "cache.duckdb")
