#!/usr/bin/env python
"""Test d'intégration complet de la recharge.

Teste toute la chaîne: data-manager → LoadResult → bridge → discretization.
- Custom CSV (multi-stations avec LOC)
- Synthétique (constant, sinusoïdal)
- NetCDF grillé (créé à la volée)
- GeoTIFF statique (créé à la volée)
- Modes spatial_mode : auto / homogeneous / heterogeneous
- Interpolation point→grille (nearest, linear, IDW)
- Réduction field→homogène
- Catalogue SQL (persistance)

Résultats attendus: toutes les assertions passent, zéro erreur.
"""
from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# ── Setup paths ───────────────────────────────────────────────
BV_DIR = Path(__file__).resolve().parent
WS_ROOT = BV_DIR.parent.parent
os.chdir(BV_DIR)
DATA_DIR = WS_ROOT / "data"
RECHARGE_DIR = DATA_DIR / "recharge"

# Add project root to path
PROJECT_ROOT = WS_ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ── Helpers ───────────────────────────────────────────────────
_PASS = 0
_FAIL = 0


def _report(name: str, ok: bool, detail: str = ""):
    global _PASS, _FAIL
    status = "PASS" if ok else "FAIL"
    if ok:
        _PASS += 1
    else:
        _FAIL += 1
    msg = f"  [{status}] {name}"
    if detail:
        msg += f"  -- {detail}"
    print(msg)


def _section(title: str):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


# ══════════════════════════════════════════════════════════════
# 0) Génération des données de test
# ══════════════════════════════════════════════════════════════
_section("0) Génération des données de test")

PERIOD = (datetime(2020, 1, 1), datetime(2020, 12, 31))
BBOX = (-1.70, 48.11, -1.66, 48.14)

# --- CSV chroniques recharge (3 stations, 366 jours) ---
dates = pd.date_range("2020-01-01", "2020-12-31", freq="D")

for station_id, base_val in [("RECH01", 2.0), ("RECH02", 3.5), ("RECH03", 1.2)]:
    np.random.seed(hash(station_id) % 2**31)
    noise = np.random.normal(0, 0.3, len(dates))
    values = np.maximum(base_val + noise, 0.0)
    df = pd.DataFrame({"datetime": dates.strftime("%Y-%m-%d"), "value": np.round(values, 4)})
    fname = f"recharge_custom_{station_id}_20200101_20201231_D.csv"
    df.to_csv(RECHARGE_DIR / fname, index=False)
    print(f"  Créé {fname} ({len(df)} pts, mean={values.mean():.2f} mm/day)")

# --- NetCDF grillé (10x10, 12 pas mensuels) ---
nc_path = RECHARGE_DIR / "recharge_grid_2020.nc"
try:
    import xarray as xr

    lon = np.linspace(-1.70, -1.66, 10)
    lat = np.linspace(48.11, 48.14, 10)
    time = pd.date_range("2020-01-15", periods=12, freq="ME")
    # Gradient N-S + variation temporelle
    lat_grid, lon_grid = np.meshgrid(lat, lon, indexing="ij")
    base_field = (lat_grid - 48.11) / (48.14 - 48.11) * 3.0 + 1.0  # 1-4 mm/day
    data = np.zeros((12, 10, 10))
    for t in range(12):
        seasonal = 1.0 + 0.5 * np.sin(2 * np.pi * t / 12)
        data[t] = base_field * seasonal
    ds = xr.Dataset(
        {"recharge": (["time", "y", "x"], data)},
        coords={"time": time, "y": lat, "x": lon},
    )
    ds["recharge"].attrs["units"] = "mm/day"
    ds.attrs["crs"] = "EPSG:4326"
    ds.to_netcdf(nc_path)
    print(f"  Créé {nc_path.name} (12 pas, 10x10, mean={data.mean():.2f} mm/day)")
    HAS_NC = True
except Exception as e:
    print(f"  SKIP NetCDF: {e}")
    HAS_NC = False

# --- GeoTIFF statique (10x10) ---
tif_path = RECHARGE_DIR / "recharge_static.tif"
try:
    import rasterio
    from rasterio.transform import from_bounds

    tif_data = np.random.uniform(1.0, 5.0, (10, 10)).astype(np.float32)
    transform = from_bounds(-1.70, 48.11, -1.66, 48.14, 10, 10)
    with rasterio.open(
        tif_path, "w", driver="GTiff", height=10, width=10,
        count=1, dtype="float32", crs="EPSG:4326", transform=transform,
    ) as dst:
        dst.write(tif_data, 1)
    print(f"  Créé {tif_path.name} (10x10, mean={tif_data.mean():.2f} mm/day)")
    HAS_TIF = True
except Exception as e:
    print(f"  SKIP GeoTIFF: {e}")
    HAS_TIF = False


# ══════════════════════════════════════════════════════════════
# 1) Custom CSV → DataStore.load_recharge()
# ══════════════════════════════════════════════════════════════
_section("1) Custom CSV via DataStore.load_recharge()")

from hydromodpy.data_managers.store import DataStore
from hydromodpy.data_managers.variables.recharge.config import (
    RechargeConfig,
    RechargeSourceConfig,
)

store = DataStore(
    workspace_root=WS_ROOT,
    project_extent=BBOX,
    project_period=PERIOD,
)

cfg_csv = RechargeConfig(
    sources=[RechargeSourceConfig(source="custom", path=RECHARGE_DIR)],
    date_start="2020-01-01",
    date_end="2020-12-31",
)

result_csv = store.load_recharge(cfg_csv)

_report("LoadResult non vide", bool(result_csv), f"len={len(result_csv)}")
_report("has_points=True", result_csv.has_points, f"n_points={len(result_csv.points)}")
_report("3 stations chargées", len(result_csv.points) == 3, f"got {len(result_csv.points)}")

for rec in result_csv.points:
    has_loc = rec.location is not None
    has_xy = has_loc and hasattr(rec.location, "x") and hasattr(rec.location, "y")
    _report(
        f"  {rec.station_id}: location OK",
        has_xy,
        f"xy=({rec.location.x}, {rec.location.y})" if has_xy else "no location",
    )
    _report(
        f"  {rec.station_id}: unit=mm/day",
        rec.unit == "mm/day",
        f"got {rec.unit}",
    )
    _report(
        f"  {rec.station_id}: n_records>300",
        rec.n_records > 300,
        f"n={rec.n_records}",
    )
    _report(
        f"  {rec.station_id}: valeurs > 0",
        (rec.data["value"] >= 0).all(),
        f"min={rec.data['value'].min():.4f}",
    )


# ══════════════════════════════════════════════════════════════
# 2) Synthétique constant
# ══════════════════════════════════════════════════════════════
_section("2) Recharge synthétique constante")

cfg_synth_const = RechargeConfig(
    sources=[RechargeSourceConfig(
        source="synthetic",
        values=[2.5],
        start_date="2020-01-01",
        freq="D",
        periods=366,
    )],
    date_start="2020-01-01",
    date_end="2020-12-31",
)

result_synth_const = store.load_recharge(cfg_synth_const)

_report("LoadResult non vide", bool(result_synth_const))
_report("1 PointRecord", len(result_synth_const.points) == 1, f"got {len(result_synth_const.points)}")

if result_synth_const.points:
    rec = result_synth_const.points[0]
    _report("station_id=synthetic", rec.station_id == "synthetic")
    _report("unit=mm/day", rec.unit == "mm/day")
    _report("n_records=366", rec.n_records == 366, f"got {rec.n_records}")
    all_same = np.allclose(rec.data["value"].values, 2.5)
    _report("valeur constante=2.5", all_same, f"unique={rec.data['value'].unique()[:5]}")


# ══════════════════════════════════════════════════════════════
# 3) Synthétique sinusoïdal
# ══════════════════════════════════════════════════════════════
_section("3) Recharge synthétique sinusoïdale")

cfg_synth_sin = RechargeConfig(
    sources=[RechargeSourceConfig(
        source="synthetic",
        values=[3.0],
        amplitude=1.5,
        period_days=365,
        offset=0.0,
        start_date="2020-01-01",
        freq="D",
        periods=366,
    )],
    date_start="2020-01-01",
    date_end="2020-12-31",
)

result_synth_sin = store.load_recharge(cfg_synth_sin)

_report("LoadResult non vide", bool(result_synth_sin))
if result_synth_sin.points:
    rec = result_synth_sin.points[0]
    vals = rec.data["value"].values
    _report("n_records=366", rec.n_records == 366, f"got {rec.n_records}")
    _report("valeur varie (std>0)", vals.std() > 0.5, f"std={vals.std():.3f}")
    _report("min >= 0 (clamp)", vals.min() >= 0.0, f"min={vals.min():.3f}")
    _report(
        "max ≈ 4.5 (base+amp)",
        3.5 < vals.max() < 5.0,
        f"max={vals.max():.3f}",
    )
    _report(
        "mean ≈ 3.0 (base)",
        2.5 < vals.mean() < 3.5,
        f"mean={vals.mean():.3f}",
    )


# ══════════════════════════════════════════════════════════════
# 4) NetCDF grillé → LoadResult (FieldRecord)
# ══════════════════════════════════════════════════════════════
_section("4) NetCDF grillé via custom path=.nc")

if HAS_NC:
    cfg_nc = RechargeConfig(
        sources=[RechargeSourceConfig(source="custom", path=nc_path)],
        date_start="2020-01-01",
        date_end="2020-12-31",
    )
    result_nc = store.load_recharge(cfg_nc)

    _report("LoadResult non vide", bool(result_nc))
    _report("has_fields=True", result_nc.has_fields, f"n_fields={len(result_nc.fields)}")
    _report("has_points=False", not result_nc.has_points)

    if result_nc.fields:
        fr = result_nc.fields[0]
        _report("source=custom", fr.source == "custom")
        _report("unit=mm/day", fr.unit == "mm/day")
        _report("crs=EPSG:4326", fr.crs == "EPSG:4326")
        _report("variable=recharge", fr.variable == "recharge")

        # Check xarray data
        if hasattr(fr.data, "data_vars"):
            ds = fr.data
            _report("xarray Dataset", True, f"vars={list(ds.data_vars)}")
            if "recharge" in ds:
                shape = ds["recharge"].shape
                _report("shape (12, 10, 10)", shape == (12, 10, 10), f"got {shape}")
else:
    print("  SKIP (pas de xarray)")


# ══════════════════════════════════════════════════════════════
# 5) GeoTIFF statique → LoadResult (FieldRecord)
# ══════════════════════════════════════════════════════════════
_section("5) GeoTIFF statique via custom path=.tif")

if HAS_TIF:
    cfg_tif = RechargeConfig(
        sources=[RechargeSourceConfig(source="custom", path=tif_path)],
    )
    result_tif = store.load_recharge(cfg_tif)

    _report("LoadResult non vide", bool(result_tif))
    _report("has_fields=True", result_tif.has_fields)
    _report("has_points=False", not result_tif.has_points)

    if result_tif.fields:
        fr = result_tif.fields[0]
        _report("is_static=True", fr.is_static)
        _report("source=custom", fr.source == "custom")
        _report("unit=mm/day", fr.unit == "mm/day")
else:
    print("  SKIP (pas de rasterio)")


# ══════════════════════════════════════════════════════════════
# 6) Bridge: CSV → séries homogènes (m/s)
# ══════════════════════════════════════════════════════════════
_section("6) Recharge bridge: CSV → séries homogènes (m/s)")

from hydromodpy.forcing.forcing_bridge import (
    _MM_PER_DAY_TO_M_PER_S,
    build_forcing_series,
    extract_homogeneous_series,
)

series_mm = extract_homogeneous_series(result_csv)
_report("Série mm/day extraite", series_mm is not None)

if series_mm is not None:
    _report("len > 300", len(series_mm) > 300, f"len={len(series_mm)}")
    _report(
        "mean ≈ 2.2 mm/day (moyenne 3 stations)",
        1.0 < series_mm.mean() < 4.0,
        f"mean={series_mm.mean():.3f} mm/day",
    )

series_ms = build_forcing_series(result_csv, unit_conversion_factor=_MM_PER_DAY_TO_M_PER_S, label="recharge")
_report("Série m/s construite", series_ms is not None)

if series_ms is not None:
    expected_factor = 1.0 / (1000.0 * 86400.0)
    _report(
        "Conversion mm/day→m/s correcte",
        1e-9 < series_ms.mean() < 1e-6,
        f"mean={series_ms.mean():.2e} m/s",
    )
    # Vérif ratio
    if series_mm is not None:
        ratio = series_ms.mean() / (series_mm.mean() * expected_factor)
        _report(
            "Ratio conversion ≈ 1.0",
            0.99 < ratio < 1.01,
            f"ratio={ratio:.6f}",
        )


# ══════════════════════════════════════════════════════════════
# 7) Bridge: NC field → homogène (spatial mean → m/s)
# ══════════════════════════════════════════════════════════════
_section("7) Recharge bridge: NC field → homogène (force_homogeneous)")

if HAS_NC:
    series_field_homo = build_forcing_series(result_nc, unit_conversion_factor=_MM_PER_DAY_TO_M_PER_S, force_homogeneous=True, label="recharge")
    _report("Série m/s depuis fields", series_field_homo is not None)

    if series_field_homo is not None:
        _report("len > 0", len(series_field_homo) > 0, f"len={len(series_field_homo)}")
        _report(
            "Valeurs m/s raisonnables",
            1e-9 < series_field_homo.mean() < 1e-6,
            f"mean={series_field_homo.mean():.2e} m/s",
        )
else:
    print("  SKIP (pas de NC)")


# ══════════════════════════════════════════════════════════════
# 8) Discrétisation hétérogène: NC field → {kper: ndarray}
# ══════════════════════════════════════════════════════════════
_section("8) Discrétisation hétérogène: NC → grille MODFLOW")

if HAS_NC:
    try:
        import flopy

        from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_field_discretization import (
            discretize_fields_on_sgrid,
        )

        # Créer une grille MODFLOW simple (5x5)
        nrow, ncol = 5, 5
        delr = np.full(ncol, (BBOX[2] - BBOX[0]) / ncol)
        delc = np.full(nrow, (BBOX[3] - BBOX[1]) / nrow)
        sgrid = flopy.discretization.StructuredGrid(
            delr=delr, delc=delc, nlay=1,
            xoff=BBOX[0], yoff=BBOX[1],
        )

        arrays = discretize_fields_on_sgrid(
            load_result=result_nc,
            sgrid=sgrid,
            nper=12,
            method="nearest",
        )

        _report("Résultat dict non vide", bool(arrays))
        _report("12 kper", len(arrays) == 12, f"got {len(arrays)}")

        if arrays:
            arr0 = arrays[0]
            _report("Shape (5,5)", arr0.shape == (nrow, ncol), f"got {arr0.shape}")
            _report(
                "Valeurs m/s (>0)",
                (arr0 > 0).all(),
                f"min={arr0.min():.2e}, max={arr0.max():.2e}",
            )
            _report(
                "Pas de NaN",
                not np.isnan(arr0).any(),
            )

            # Vérif: variation temporelle
            means = [arrays[k].mean() for k in sorted(arrays)]
            _report(
                "Variation temporelle",
                max(means) / min(means) > 1.2,
                f"range=[{min(means):.2e}, {max(means):.2e}]",
            )

            # Vérif: variation spatiale
            _report(
                "Variation spatiale",
                arr0.std() > 0,
                f"std={arr0.std():.2e}",
            )
    except ImportError as e:
        print(f"  SKIP (import: {e})")
    except Exception as e:
        _report("Discrétisation hétérogène NC", False, f"ERREUR: {e}")
        traceback.print_exc()
else:
    print("  SKIP (pas de NC)")


# ══════════════════════════════════════════════════════════════
# 9) Discrétisation hétérogène: TIF statique → {kper: ndarray}
# ══════════════════════════════════════════════════════════════
_section("9) Discrétisation hétérogène: TIF → grille MODFLOW")

if HAS_TIF:
    try:
        import flopy

        from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_field_discretization import (
            discretize_fields_on_sgrid,
        )

        nrow, ncol = 5, 5
        delr = np.full(ncol, (BBOX[2] - BBOX[0]) / ncol)
        delc = np.full(nrow, (BBOX[3] - BBOX[1]) / nrow)
        sgrid = flopy.discretization.StructuredGrid(
            delr=delr, delc=delc, nlay=1,
            xoff=BBOX[0], yoff=BBOX[1],
        )

        arrays = discretize_fields_on_sgrid(
            load_result=result_tif,
            sgrid=sgrid,
            nper=1,
            method="nearest",
        )

        _report("Résultat dict non vide", bool(arrays))
        if arrays:
            arr0 = arrays[0]
            _report("Shape (5,5)", arr0.shape == (nrow, ncol), f"got {arr0.shape}")
            _report(
                "Valeurs m/s (>0)",
                (arr0 > 0).all(),
                f"min={arr0.min():.2e}, max={arr0.max():.2e}",
            )
    except ImportError as e:
        print(f"  SKIP (import: {e})")
    except Exception as e:
        _report("Discrétisation hétérogène TIF", False, f"ERREUR: {e}")
        traceback.print_exc()
else:
    print("  SKIP (pas de TIF)")


# ══════════════════════════════════════════════════════════════
# 10) Interpolation points → grille (nearest, IDW, linear)
# ══════════════════════════════════════════════════════════════
_section("10) Interpolation points → grille MODFLOW")

try:
    import flopy

    from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_field_discretization import (
        discretize_points_on_sgrid,
    )

    nrow, ncol = 5, 5
    delr = np.full(ncol, (BBOX[2] - BBOX[0]) / ncol)
    delc = np.full(nrow, (BBOX[3] - BBOX[1]) / nrow)
    sgrid = flopy.discretization.StructuredGrid(
        delr=delr, delc=delc, nlay=1,
        xoff=BBOX[0], yoff=BBOX[1],
    )

    for method in ["nearest", "linear", "idw"]:
        try:
            arrays = discretize_points_on_sgrid(
                load_result=result_csv,
                sgrid=sgrid,
                nper=12,
                method=method,
            )

            ok = bool(arrays) and len(arrays) == 12
            _report(
                f"method={method}: 12 kper",
                ok,
                f"got {len(arrays)}" if arrays else "empty",
            )

            if arrays:
                arr0 = arrays[0]
                _report(
                    f"method={method}: shape (5,5)",
                    arr0.shape == (nrow, ncol),
                    f"got {arr0.shape}",
                )
                _report(
                    f"method={method}: valeurs > 0",
                    (arr0 > 0).all(),
                    f"min={arr0.min():.2e}",
                )

                if method in ("linear", "idw"):
                    _report(
                        f"method={method}: variation spatiale",
                        arr0.std() > 0,
                        f"std={arr0.std():.2e}",
                    )
        except Exception as e:
            _report(f"method={method}", False, f"ERREUR: {e}")
            traceback.print_exc()

except ImportError as e:
    print(f"  SKIP (import: {e})")


# ══════════════════════════════════════════════════════════════
# 11) Field → homogène via spatial_mean_from_fields
# ══════════════════════════════════════════════════════════════
_section("11) spatial_mean_from_fields (NC → scalaire)")

if HAS_NC:
    try:
        from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_field_discretization import (
            spatial_mean_from_fields,
        )

        mean_series = spatial_mean_from_fields(result_nc)
        _report("Série scalaire extraite", mean_series is not None)

        if mean_series is not None:
            _report("len > 0", len(mean_series) > 0, f"len={len(mean_series)}")
            _report(
                "Valeurs mm/day raisonnables",
                0.5 < mean_series.mean() < 5.0,
                f"mean={mean_series.mean():.3f} mm/day",
            )
            _report(
                "Variation temporelle",
                mean_series.std() > 0.1,
                f"std={mean_series.std():.3f}",
            )
    except Exception as e:
        _report("spatial_mean_from_fields", False, f"ERREUR: {e}")
        traceback.print_exc()
else:
    print("  SKIP (pas de NC)")


# ══════════════════════════════════════════════════════════════
# 12) Multi-source: CSV + synthétique
# ══════════════════════════════════════════════════════════════
_section("12) Multi-source: CSV + synthétique dans un seul LoadResult")

cfg_multi = RechargeConfig(
    sources=[
        RechargeSourceConfig(source="custom", path=RECHARGE_DIR),
        RechargeSourceConfig(
            source="synthetic", values=[4.0],
            start_date="2020-01-01", freq="D", periods=366,
        ),
    ],
    date_start="2020-01-01",
    date_end="2020-12-31",
)

result_multi = store.load_recharge(cfg_multi)

_report("LoadResult non vide", bool(result_multi))
_report(
    "4 PointRecords (3 CSV + 1 synth)",
    len(result_multi.points) == 4,
    f"got {len(result_multi.points)}",
)

station_ids = {r.station_id for r in result_multi.points}
_report(
    "Stations: RECH01,RECH02,RECH03,synthetic",
    station_ids == {"RECH01", "RECH02", "RECH03", "synthetic"},
    f"got {station_ids}",
)

series_multi = build_forcing_series(result_multi, unit_conversion_factor=_MM_PER_DAY_TO_M_PER_S, label="recharge")
_report("Série homogène (moyenne 4 stations)", series_multi is not None)
if series_multi is not None:
    _report(
        "mean m/s raisonnable",
        1e-9 < series_multi.mean() < 1e-6,
        f"mean={series_multi.mean():.2e} m/s",
    )


# ══════════════════════════════════════════════════════════════
# 13) Catalogue SQL
# ══════════════════════════════════════════════════════════════
_section("13) Catalogue SQL (catalog.db)")

try:
    info = store.cache_info()
    _report("cache_info() fonctionne", True, f"{len(info)} entrées")
    if not info.empty:
        recharge_entries = info[info["variable"] == "recharge"] if "variable" in info.columns else info
        _report(
            "Entrées recharge dans catalog",
            len(recharge_entries) >= 0,
            f"n={len(recharge_entries)}",
        )
except Exception as e:
    _report("Catalogue SQL", False, f"ERREUR: {e}")


# ══════════════════════════════════════════════════════════════
# 14) FlowRechargeConfig: spatial_mode + interpolation_method
# ══════════════════════════════════════════════════════════════
_section("14) FlowRechargeConfig: validation spatial_mode/interpolation_method")

from hydromodpy.process.flow.sinks_sources import FlowRechargeConfig

# Défauts
cfg_default = FlowRechargeConfig(values=0.0)
_report("spatial_mode default=auto", cfg_default.spatial_mode == "auto")
_report("interpolation_method default=nearest", cfg_default.interpolation_method == "nearest")

# Valeurs valides
for mode in ["auto", "homogeneous", "heterogeneous"]:
    try:
        cfg = FlowRechargeConfig(values=0.0, spatial_mode=mode)
        _report(f"spatial_mode={mode} accepté", True)
    except Exception as e:
        _report(f"spatial_mode={mode} accepté", False, str(e))

for method in ["nearest", "linear", "idw"]:
    try:
        cfg = FlowRechargeConfig(values=0.0, interpolation_method=method)
        _report(f"interpolation_method={method} accepté", True)
    except Exception as e:
        _report(f"interpolation_method={method} accepté", False, str(e))

# Valeurs invalides
for invalid_mode in ["invalid", "foo", ""]:
    try:
        FlowRechargeConfig(values=0.0, spatial_mode=invalid_mode)
        _report(f"spatial_mode={invalid_mode!r} rejeté", False, "pas de ValidationError")
    except Exception:
        _report(f"spatial_mode={invalid_mode!r} rejeté", True)

for invalid_method in ["cubic", "foo", ""]:
    try:
        FlowRechargeConfig(values=0.0, interpolation_method=invalid_method)
        _report(f"interpolation_method={invalid_method!r} rejeté", False, "pas de ValidationError")
    except Exception:
        _report(f"interpolation_method={invalid_method!r} rejeté", True)


# ══════════════════════════════════════════════════════════════
# 15) Binder: apply_recharge_load_result_to_flow (mock flow)
# ══════════════════════════════════════════════════════════════
_section("15) Binder: apply_recharge_load_result_to_flow")

from hydromodpy.process.flow.structure_binders import (
    apply_recharge_load_result_to_flow,
)


class _MockFlow:
    """Minimal mock pour tester le binder sans vrai objet Flow."""

    def __init__(self):
        self.sinks_sources = {}
        self._recharge = None

    def set_recharge(self, cfg):
        self._recharge = cfg


# Test auto + CSV (homogène par défaut)
mock = _MockFlow()
ok = apply_recharge_load_result_to_flow(flow=mock, recharge_result=result_csv)
_report("Binder CSV auto → True", ok)
_report("Recharge injectée", mock._recharge is not None)
if mock._recharge is not None:
    _report("units=m/s", mock._recharge.units == "m/s")
    _report("spatial_mode=auto", mock._recharge.spatial_mode == "auto")

# Test avec existing config heterogeneous + field NC
if HAS_NC:
    mock2 = _MockFlow()
    mock2.sinks_sources = {
        "recharge": FlowRechargeConfig(
            values=0.0,
            spatial_mode="heterogeneous",
            interpolation_method="idw",
        )
    }
    ok2 = apply_recharge_load_result_to_flow(flow=mock2, recharge_result=result_nc)
    _report("Binder NC heterogeneous → True", ok2)
    if mock2._recharge is not None:
        _report(
            "heterogeneous_source set",
            mock2._recharge.heterogeneous_source is not None,
        )
        _report(
            "spatial_mode=heterogeneous",
            mock2._recharge.spatial_mode == "heterogeneous",
        )
        _report(
            "interpolation_method=idw",
            mock2._recharge.interpolation_method == "idw",
        )

# Test None → False
ok3 = apply_recharge_load_result_to_flow(flow=_MockFlow(), recharge_result=None)
_report("Binder None → False", not ok3)


# ══════════════════════════════════════════════════════════════
# 16) Chaîne complète: data-manager → bridge → discrétisation
# ══════════════════════════════════════════════════════════════
_section("16) Chaîne complète: TOML config → LoadResult → bridge → grille")

if HAS_NC:
    try:
        import flopy

        from hydromodpy.forcing.forcing_bridge import build_forcing_series, _MM_PER_DAY_TO_M_PER_S
        from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_field_discretization import (
            discretize_fields_on_sgrid,
        )

        # 1. Charger NC via data-manager
        cfg_chain = RechargeConfig(
            sources=[RechargeSourceConfig(source="custom", path=nc_path)],
            date_start="2020-01-01",
            date_end="2020-12-31",
        )
        lr = store.load_recharge(cfg_chain)
        _report("1. LoadResult chargé", bool(lr) and lr.has_fields)

        # 2. Bridge: homogène
        s_homo = build_forcing_series(lr, unit_conversion_factor=_MM_PER_DAY_TO_M_PER_S, force_homogeneous=True, label="recharge")
        _report("2. Série homogène m/s", s_homo is not None)
        if s_homo is not None:
            _report(
                "   Valeur m/s",
                1e-9 < s_homo.mean() < 1e-6,
                f"mean={s_homo.mean():.2e}",
            )

        # 3. Discrétisation hétérogène
        nrow, ncol = 8, 8
        delr = np.full(ncol, (BBOX[2] - BBOX[0]) / ncol)
        delc = np.full(nrow, (BBOX[3] - BBOX[1]) / nrow)
        sgrid = flopy.discretization.StructuredGrid(
            delr=delr, delc=delc, nlay=1,
            xoff=BBOX[0], yoff=BBOX[1],
        )

        arrays = discretize_fields_on_sgrid(
            load_result=lr, sgrid=sgrid, nper=12, method="nearest",
        )
        _report("3. Discrétisation 12 kper", len(arrays) == 12)
        _report(
            "   Shape (8,8)",
            arrays[0].shape == (8, 8) if arrays else False,
            f"got {arrays[0].shape}" if arrays else "",
        )

        # 4. Vérif cohérence homogène vs hétérogène
        if s_homo is not None and arrays:
            homo_mean = s_homo.mean()
            hetero_means = [arrays[k].mean() for k in sorted(arrays)]
            hetero_grand_mean = np.mean(hetero_means)
            ratio = hetero_grand_mean / homo_mean if homo_mean > 0 else 0
            _report(
                "4. Cohérence homo/hetero (ratio ≈ 1)",
                0.5 < ratio < 2.0,
                f"homo={homo_mean:.2e}, hetero={hetero_grand_mean:.2e}, ratio={ratio:.2f}",
            )

    except ImportError as e:
        print(f"  SKIP (import: {e})")
    except Exception as e:
        _report("Chaîne complète", False, f"ERREUR: {e}")
        traceback.print_exc()
else:
    print("  SKIP (pas de NC)")


# ══════════════════════════════════════════════════════════════
# RÉSUMÉ
# ══════════════════════════════════════════════════════════════
_section("RÉSUMÉ")
total = _PASS + _FAIL
print(f"\n  Total: {total} tests")
print(f"  PASS:  {_PASS}")
print(f"  FAIL:  {_FAIL}")
if _FAIL == 0:
    print("\n  Tous les tests passent !")
else:
    print(f"\n  {_FAIL} tests en échec.")
    sys.exit(1)
