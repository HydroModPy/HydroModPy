"""The stage products of a run come from the store, and survive a rebuild.

One project folder, the transient island of ``factory.py`` played by MODFLOW 6
on the triangle mesh, with a soil reservoir whose rain and ETP are two fixed
2 x 2 NetCDF grids under ``inputs/``. Five runs, in order:

1. ``hmp run project.toml``: the run is sealed, ``.hmp/products/`` holds the
   two products (mesh, soil), ``runs/a/products.json`` cites them in the order
   the steps first asked for them, and ``.hmp/mesh_cache/`` is gone.
2. The same document under another name, ``--set flow.param.K.field.value=2e-5``:
   ``products.json`` cites the same two keys, the store still holds two
   products, and their ``meta.json`` files did not change.
3. The same run again under another name, after ``rm -rf .hmp/products``: it
   rebuilds, and its fields equal the first run's the way ``refhash/1`` reads
   them (values, float64, one NaN, not file bytes).
4. A run stopped at ``setup_process`` (the first step that owns a run
   directory, and the step right after ``build_mesh``; a window stopped at
   ``build_mesh`` itself writes no run directory, so nothing to resume), then
   ``rm -rf .hmp/products``, then ``hmp run --resume``: the resume rebuilds on
   the miss and the run seals, its fields equal the first run's.
5. ``[workspace] products_cap_mb = 1`` on a last run: after it the store holds
   only that run's own products.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
import zarr

from hydromodpy.results.manifest import is_sealed
from hydromodpy.results.products.cited import read_cited
from hydromodpy.results.products.store import ProductStore, products_root
from tests.scenarios.factory import TRIANGLE_MESH, transient_island, write_project
from tests.scenarios.launcher import link_binaries

MF6_FILES = ("mf6", "libmf6.so")
DAYS = pd.date_range("2003-01-01", periods=90, freq="D")
GRID_X = np.array([152.5, 457.5])
GRID_Y = np.array([152.5, 457.5])


def _hmp(root: Path, env: dict[str, str], *argv: str) -> subprocess.CompletedProcess[str]:
    """Run ``python -m hydromodpy`` in *root* with the environment of the scenario."""
    return subprocess.run(
        [sys.executable, "-m", "hydromodpy", *argv],
        cwd=root,
        env=dict(env),
        capture_output=True,
        text=True,
        timeout=600,
    )


def _island_soil_toml(name: str, *, products_cap_mb: int | None = None) -> str:
    """Return the transient MODFLOW 6 island on a triangle mesh, with a soil reservoir.

    The soil replaces the fixed recharge of the island: rain and ETP are read
    from the two NetCDF grids under ``inputs/``, the first period is no longer
    steady, and the initial condition is a steady state. ``products_cap_mb``
    caps the store for the eviction step.
    """
    text = transient_island(name, "modflow6", mesh=TRIANGLE_MESH)
    text = text.replace("first_period_steady = true", "first_period_steady = false")
    text = text.replace(
        'types = ["oceanic"]',
        'types = ["oceanic", "precipitation", "etp"]',
    )
    text = text.replace(
        '[[data.oceanic.sources]]\nsource = "constant"\nvalue = 0.0\n',
        '[[data.oceanic.sources]]\nsource = "constant"\nvalue = 0.0\n\n'
        '[[data.precipitation.sources]]\nsource = "file"\npath = "inputs/precipitation.nc"\n\n'
        '[[data.etp.sources]]\nsource = "file"\npath = "inputs/etp.nc"\n',
    )
    text = text.replace(
        "[flow.sinks_sources.recharge]\nvalues = [1.0, 4.0, 2.0]",
        '[flow.ic]\nkind = "steady_state"\n\n'
        '[flow.sinks_sources.recharge.soil]\nru = "150 mm"\nspinup = "none"\n'
        'transit_time = "5 days"\n\n'
        '[flow.sinks_sources.etp]\nextinction_depth = "2 m"',
    )
    if products_cap_mb is not None:
        text = text.replace("[workspace]\n", f"[workspace]\nproducts_cap_mb = {products_cap_mb}\n")
    return text


def _write_forcings(root: Path) -> None:
    """Write the two fixed 2 x 2 NetCDF grids the soil reads, under ``inputs/``."""
    inputs = root / "inputs"
    inputs.mkdir(parents=True)
    rain = np.broadcast_to(
        np.linspace(1.0, 4.0, len(DAYS))[:, None, None], (len(DAYS), 2, 2)
    ).copy()
    etp = np.broadcast_to(np.linspace(0.5, 3.0, len(DAYS))[:, None, None], (len(DAYS), 2, 2)).copy()
    for name, values in (("precipitation", rain), ("etp", etp)):
        dataset = xr.Dataset(
            {name: (("time", "y", "x"), values)},
            coords={"time": DAYS.values, "y": GRID_Y, "x": GRID_X},
        )
        dataset.attrs["crs"] = "EPSG:2154"
        dataset[name].attrs["nodata"] = -9999.0
        dataset.to_netcdf(inputs / f"{name}.nc")


def _canonical(values: np.ndarray) -> np.ndarray:
    """Return an array the way ``refhash/1`` reads it: float64, -0.0 as 0.0, one NaN."""
    values = np.asarray(values)
    if values.dtype.kind != "f":
        return values
    out = np.array(values, dtype=np.float64, copy=True)
    with np.errstate(invalid="ignore"):
        np.add(out, 0.0, out=out)
    np.copyto(out, np.nan, where=np.isnan(out))
    return out


def _zarr_arrays(store: Path) -> dict[str, np.ndarray]:
    """Return every array of a ``fields.zarr`` store, keyed by its path."""
    root = zarr.open_group(str(store), mode="r", use_consolidated=False)
    found: dict[str, np.ndarray] = {}

    def walk(group, prefix: str) -> None:
        for name, array in group.arrays():
            found[prefix + name] = np.asarray(array[...])
        for name, sub in group.groups():
            walk(sub, prefix + name + "/")

    walk(root, "")
    return found


def _fields_equal(left: Path, right: Path) -> None:
    """Assert two run folders hold the same fields, the comparison of ``refhash/1``."""
    left_arrays = _zarr_arrays(left / "fields.zarr")
    right_arrays = _zarr_arrays(right / "fields.zarr")
    assert set(left_arrays) == set(right_arrays), "the runs write different field arrays"
    for name in left_arrays:
        a = _canonical(left_arrays[name])
        b = _canonical(right_arrays[name])
        assert np.array_equal(a, b, equal_nan=True), f"field {name!r} differs between the runs"


def _said(result: subprocess.CompletedProcess[str]) -> str:
    """The tail of the run output, the part a failure prints."""
    return result.stderr[-3000:]


def test_products_come_from_the_store(
    tmp_path: Path, scenario_env: dict[str, str], scenario_cache: Path
) -> None:
    link_binaries(scenario_cache, MF6_FILES)
    root = tmp_path / "project"
    write_project(root, {"project.toml": _island_soil_toml("a")})
    _write_forcings(root)
    store = ProductStore(products_root(root))

    # 1. One sealed run, two products in the store, cited in first-demand order.
    first = _hmp(root, scenario_env, "run", "project.toml")
    assert first.returncode == 0, _said(first)
    run_a = root / "runs" / "a"
    assert is_sealed(run_a)
    entries = store.entries()
    assert {entry.kind for entry in entries} == {"mesh", "soil"}
    assert len(entries) == 2
    cited_a = read_cited(run_a)
    assert [product.kind for product in cited_a] == ["soil", "mesh"]
    assert not (root / ".hmp" / "mesh_cache").exists()

    # 2. The same document, another name, another K: same keys, nothing rewritten.
    meta_before = {
        entry.key: (store.path(entry.key) / "meta.json").read_bytes() for entry in entries
    }
    second = _hmp(
        root,
        scenario_env,
        "run",
        "project.toml",
        "--case",
        "b",
        "--set",
        "flow.param.K.field.value=2e-5",
    )
    assert second.returncode == 0, _said(second)
    assert is_sealed(root / "runs" / "b")
    cited_b = read_cited(root / "runs" / "b")
    assert [product.key for product in cited_b] == [product.key for product in cited_a]
    entries = store.entries()
    assert {entry.kind for entry in entries} == {"mesh", "soil"}
    assert len(entries) == 2
    meta_after = {
        entry.key: (store.path(entry.key) / "meta.json").read_bytes() for entry in entries
    }
    assert meta_after == meta_before

    # 3. Delete the store, run the first document again: it rebuilds, same fields.
    shutil.rmtree(root / ".hmp" / "products")
    third = _hmp(root, scenario_env, "run", "project.toml", "--case", "c")
    assert third.returncode == 0, _said(third)
    run_c = root / "runs" / "c"
    assert is_sealed(run_c)
    _fields_equal(run_a, run_c)
    assert {entry.kind for entry in store.entries()} == {"mesh", "soil"}
    assert len(store.entries()) == 2

    # 4. A partial run, the store deleted, then a resume: it rebuilds and seals.
    partial = _hmp(
        root, scenario_env, "run", "project.toml", "--case", "d", "--until", "setup_process"
    )
    assert partial.returncode == 0, _said(partial)
    run_d = root / "runs" / "d"
    assert not is_sealed(run_d)
    shutil.rmtree(root / ".hmp" / "products")
    resumed = _hmp(root, scenario_env, "run", "--resume", "d")
    assert resumed.returncode == 0, _said(resumed)
    assert is_sealed(run_d)
    _fields_equal(run_a, run_d)

    # 5. A cap of 1 MB on a last run: after it the store holds only its products.
    (root / "project_cap.toml").write_text(
        _island_soil_toml("e", products_cap_mb=1), encoding="utf-8"
    )
    cap = _hmp(root, scenario_env, "run", "project_cap.toml")
    assert cap.returncode == 0, _said(cap)
    assert is_sealed(root / "runs" / "e")
    cited_e = read_cited(root / "runs" / "e")
    entries = store.entries()
    assert {entry.key for entry in entries} == {product.key for product in cited_e}
    assert len(entries) == 2
