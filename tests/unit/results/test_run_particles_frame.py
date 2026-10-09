"""``hmp.read(run, "particles")`` gives the particle paths as a documented frame."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import zarr

from hydromodpy.results.run.particles import PARTICLE_COLUMNS, particle_frame


def _run_with(path: Path) -> SimpleNamespace:
    def open_zarr(_sim_id: str) -> SimpleNamespace:
        return SimpleNamespace(root=zarr.open_group(str(path), mode="r"), close=lambda: None)

    return SimpleNamespace(sim_id="sim", _catalog=SimpleNamespace(open_zarr=open_zarr))


def test_positions_are_rows_and_padding_is_dropped(tmp_path: Path) -> None:
    root = zarr.open_group(str(tmp_path / "fields.zarr"), mode="w")
    group = root.create_group("particles")
    nan = np.nan
    group.create_array("x", data=np.array([[0.0, 1.0, 2.0], [5.0, 6.0, nan]]))
    group.create_array("y", data=np.array([[0.0, 0.0, 0.0], [5.0, 5.0, nan]]))
    group.create_array("z", data=np.array([[9.0, 8.0, 7.0], [4.0, 3.0, nan]]))
    group.create_array("time", data=np.array([[0.0, 12.0, 24.0], [0.0, 2.0, nan]]))
    group.attrs.update(
        {"time_units": "hours", "source_solver": "modflow6_prt", "source_file": "m_prt.trk.csv"}
    )

    frame = particle_frame(_run_with(tmp_path / "fields.zarr"))

    assert list(frame.columns) == list(PARTICLE_COLUMNS)
    assert frame["particle"].tolist() == [0, 0, 0, 1, 1]
    assert frame["step"].tolist() == [0, 1, 2, 0, 1]
    assert frame["time_days"].tolist() == [0.0, 0.5, 1.0, 0.0, 2.0 / 24.0]
    assert frame.attrs == {"source_solver": "modflow6_prt", "source_file": "m_prt.trk.csv"}


def test_a_run_without_particles_gives_an_empty_frame(tmp_path: Path) -> None:
    zarr.open_group(str(tmp_path / "fields.zarr"), mode="w")

    frame = particle_frame(_run_with(tmp_path / "fields.zarr"))

    assert frame.empty
    assert list(frame.columns) == list(PARTICLE_COLUMNS)
    assert str(frame["particle"].dtype) == "int64"


def test_hmp_read_gives_the_particle_frame(monkeypatch) -> None:
    import pandas as pd
    import pytest

    import hydromodpy as hmp
    import hydromodpy.results.run.particles as particles
    from hydromodpy.results.run import Run

    frame = pd.DataFrame(columns=list(PARTICLE_COLUMNS))
    monkeypatch.setattr(particles, "particle_frame", lambda run: frame)
    run = Run.__new__(Run)

    assert hmp.read(run, "particles") is frame
    with pytest.raises(ValueError):
        hmp.read(run, "particles", time=0)
