"""The terrain a run routes comes from the store, and survives a rebuild.

One project folder, an 80 x 80 pixel valley at 25 m written by the test under
``inputs/``, played by MODFLOW 6 steady on the regular mesh with the river
network on. Five runs, in order:

1. ``hmp run project.toml``: the run is sealed, ``.hmp/products/`` holds the
   terrain and the mesh, ``products.json`` cites the terrain key, and the old
   ``.hmp/mesh_cache/`` folder and the ``_geographic_cache_manifest.json`` file
   are gone.
2. The same document under another name, ``--set flow.param.K.field.value=2e-5``:
   ``products.json`` cites the same terrain key, and the terrain ``meta.json``
   did not change.
3. The first document under a third name after ``rm -rf .hmp/products``: it
   rebuilds, and its fields equal the first run's.
4. The ``dem_fill.tif`` of the product copied under ``inputs/`` and declared
   ``state = "conditioned"``: the journal holds no conditioning line, the
   catchment area and polygon equal the first run's, zero cells are without
   descent, and the metadata records ``dem_correc_type = "provided"``.
5. A run stopped after ``setup_process`` then resumed: the terrain comes from
   the store, the run seals, and its fields equal the first run's.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import zarr

from hydromodpy.results.products.cited import read_cited
from hydromodpy.results.products.store import ProductStore, products_root
from hydromodpy.results.record.manifest import is_sealed
from tests.scenarios.launcher import link_binaries

MF6_FILES = ("mf6", "libmf6.so")

OUTLET_X = 1012.5
OUTLET_Y = 37.5


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


def _write_valley(root: Path) -> None:
    """Write the 80 x 80 pixel valley DEM under ``inputs/``, one cell pit included."""
    import rasterio
    from rasterio.transform import from_origin

    inputs = root / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    rows = cols = 80
    yy, xx = np.mgrid[0:rows, 0:cols]
    elev = 100.0 + 0.05 * (rows - 1 - yy) + 0.1 * np.abs(xx - 40.0)
    elev[5, 40] -= 1.0
    with rasterio.open(
        inputs / "dem.tif",
        "w",
        driver="GTiff",
        height=rows,
        width=cols,
        count=1,
        dtype="float64",
        crs="EPSG:2154",
        nodata=-9999.0,
        transform=from_origin(0.0, 2000.0, 25.0, 25.0),
    ) as dst:
        dst.write(elev, 1)


def _project_toml(name: str, *, conditioned: bool = False) -> str:
    """Return the TOML of the valley, MODFLOW 6 steady on the regular mesh."""
    dem_source = (
        'state = "conditioned"\npath = "inputs/dem_fill.tif"'
        if conditioned
        else 'path = "inputs/dem.tif"'
    )
    correc = "" if conditioned else 'dem_correc_type = "fill"\n'
    return f"""\
[site]
name = "valley"

[workflow]
mode = "simulation"

[workspace]

[geographic]
crs_project = "EPSG:2154"
{correc}
[geographic.catchment]
kind = "from_outlet_coord"
x_outlet = {OUTLET_X}
y_outlet = {OUTLET_Y}
snap_dist = "50 m"
buff_area = "10%"

[geographic.river_network]
enabled = true
threshold_mode = "area_km2"
threshold_area_km2 = 0.1
compute_stream_links = true
compute_strahler_order = true

[domain]
[domain.depth_model]
kind = "constant_thickness"
thickness = "20.0 m"

[simulation]
name = "{name}"

[simulation.time]
start_datetime = "2003-01-01 00:00:00"
end_datetime = "2003-01-02 00:00:00"
step_value = "1 day"
coverage_policy = "ignore"

[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["modflow6"]

[flow]
flow_regime = "steady"
param_list = ["K"]

[flow.param.K.field]
kind = "homogeneous"
value = "5e-5 m/s"

[flow.bc.drainage]
application_domain = "top"
value = "0.0 m2/s"

[flow.sinks_sources.recharge]
first_clim = "mean"

[data]
types = ["recharge"]

[[data.recharge.sources]]
source = "synthetic"
values = [1.0]

[[data.dem.sources]]
source = "file"
{dem_source}

[domain.layers]
nlay = 1

[display]
enabled = false
"""


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


def _terrain_key(cited: list) -> str:
    return next(product.key for product in cited if product.kind == "terrain")


def _catchment_metadata(run_dir: Path) -> dict:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    return manifest["geometry"]["catchment"]


def _watershed_wkb(run_dir: Path) -> list[bytes]:
    from hydromodpy.core.io.geoparquet import read_geoparquet

    path = run_dir / "tables.parquet" / "geographic_watershed.parquet"
    return [geometry.wkb for geometry in read_geoparquet(path).geometry]


def _said(result: subprocess.CompletedProcess[str]) -> str:
    return result.stderr[-3000:]


def test_terrain_comes_from_the_store(
    tmp_path: Path, scenario_env: dict[str, str], scenario_cache: Path
) -> None:
    link_binaries(scenario_cache, MF6_FILES)
    root = tmp_path / "project"
    root.mkdir(parents=True)
    _write_valley(root)
    (root / "project.toml").write_text(_project_toml("a"), encoding="utf-8")
    store = ProductStore(products_root(root))

    # 1. One sealed run, terrain and mesh in the store, the terrain cited.
    first = _hmp(root, scenario_env, "run", "project.toml")
    assert first.returncode == 0, _said(first)
    run_a = root / "runs" / "a"
    assert is_sealed(run_a)
    entries = store.entries()
    assert {entry.kind for entry in entries} == {"terrain", "mesh"}
    cited_a = read_cited(run_a)
    assert [product.kind for product in cited_a] == ["terrain", "mesh"]
    assert not (root / ".hmp" / "mesh_cache").exists()
    assert not any(root.rglob("_geographic_cache_manifest.json"))

    # 2. The same document, another name, another K: same terrain key, nothing rewritten.
    terrain_meta_before = (store.path(_terrain_key(cited_a)) / "meta.json").read_bytes()
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
    cited_b = read_cited(root / "runs" / "b")
    assert _terrain_key(cited_b) == _terrain_key(cited_a)
    assert (store.path(_terrain_key(cited_b)) / "meta.json").read_bytes() == terrain_meta_before

    # 3. Delete the store, run the first document again: it rebuilds, same fields.
    shutil.rmtree(root / ".hmp" / "products")
    third = _hmp(root, scenario_env, "run", "project.toml", "--case", "c")
    assert third.returncode == 0, _said(third)
    run_c = root / "runs" / "c"
    assert is_sealed(run_c)
    _fields_equal(run_a, run_c)

    # 4. The conditioned DEM of the product, declared as already conditioned.
    dem_fill = store.path(_terrain_key(cited_a)) / "dem_fill.tif"
    shutil.copyfile(dem_fill, root / "inputs" / "dem_fill.tif")
    (root / "conditioned.toml").write_text(_project_toml("d", conditioned=True), encoding="utf-8")
    fourth = _hmp(root, scenario_env, "run", "conditioned.toml")
    assert fourth.returncode == 0, _said(fourth)
    run_d = root / "runs" / "d"
    assert is_sealed(run_d)
    meta_d = _catchment_metadata(run_d)
    assert meta_d["dem_correc_type"] == "provided"
    assert meta_d["dem_cells_without_descent"] == "0"
    assert meta_d["dem_strict_pits"] == "0"
    assert meta_d["catch_area"] == _catchment_metadata(run_a)["catch_area"]
    assert _watershed_wkb(run_d) == _watershed_wkb(run_a)
    assert "Correcting DEM" not in fourth.stdout + fourth.stderr

    # 5. A partial run, then a resume: the terrain comes from the store, the run seals.
    partial = _hmp(
        root, scenario_env, "run", "project.toml", "--case", "e", "--until", "setup_process"
    )
    assert partial.returncode == 0, _said(partial)
    run_e = root / "runs" / "e"
    assert not is_sealed(run_e)
    terrain_meta_before_resume = (store.path(_terrain_key(cited_a)) / "meta.json").read_bytes()
    resumed = _hmp(root, scenario_env, "run", "--resume", "e")
    assert resumed.returncode == 0, _said(resumed)
    assert is_sealed(run_e)
    assert _terrain_key(read_cited(run_e)) == _terrain_key(cited_a)
    assert (
        store.path(_terrain_key(cited_a)) / "meta.json"
    ).read_bytes() == terrain_meta_before_resume
    _fields_equal(run_a, run_e)
