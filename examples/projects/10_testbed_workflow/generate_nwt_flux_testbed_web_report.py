"""Generate the MODFLOW-NWT small-catchment flux testbed HTML report."""

from __future__ import annotations

import csv
import html
import json
import math
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = ROOT / "outputs" / "nwt_small_catchment_flux"
WEB_DIR = OUTPUT_ROOT / "web"
SITE_CATALOG_PATH = ROOT / "site_tables" / "armorican_demo_sites.csv"
REGIONAL_NETWORK_PATH = (ROOT / "../../data/hydrography/regional_stream_network.shp").resolve()
REGIONAL_DEM_PATH = (ROOT / "../../data/dem/DEM_armorican_massif.tif").resolve()

FIGURES = (
    ("site_regional_location", "Situation regionale", "Site courant dans le reseau regional."),
    ("watershed_id_card", "Identite bassin", "Domaine, exutoire et metadonnees du run."),
    (
        "water_budget",
        "Bilan solveur domaine complet",
        "Budget MODFLOW agrege sur le domaine de calcul, tampon inclus.",
    ),
    (
        "catchment_flux_balance_rates",
        "Entrees vs sorties bassin",
        "Bilan du bassin hors tampon en mm/j avec flux lateraux de contour.",
    ),
    (
        "recharge_discharge_overlay",
        "Recharge vs decharge",
        "Recharge budgetaire et debit sortant sur la meme echelle.",
    ),
    (
        "head_timeseries_points",
        "Charges ponctuelles",
        "Evolution de la charge sur quelques cellules du bassin.",
    ),
    ("piezometric_map", "Charge", "Structure spatiale des charges simulees."),
    (
        "hydrographic_network_overlay",
        "Reseau genere vs observe",
        "Comparaison du reseau extrait du domaine au reseau hydrographique de reference.",
    ),
    (
        "observed_network_seepage_overlay",
        "Reseau observe vs suintement",
        "Reseau observe et zones de drainage/suintement produites par le calcul.",
    ),
)

INDEX_PREVIEW_FIGURES = (
    "site_regional_location",
    "watershed_id_card",
    "catchment_flux_balance_rates",
    "recharge_discharge_overlay",
    "head_timeseries_points",
    "hydrographic_network_overlay",
    "observed_network_seepage_overlay",
)

INDEX_SCATTER_FIGURES = (
    (
        "scatter_surface_vs_qmax.png",
        "Surface vs debit max",
        "Debit de pointe simule en fonction de la surface du bassin.",
    ),
    (
        "scatter_surface_vs_drained_volume.png",
        "Surface vs volume draine",
        "Volume draine cumule sur le run en fonction de la surface.",
    ),
    (
        "scatter_slope_vs_lag.png",
        "Pente vs delai de reponse",
        "Delai pic recharge - pic decharge en fonction de la pente moyenne.",
    ),
)


@dataclass(frozen=True)
class SiteCase:
    variant_id: str
    site_id: str
    label: str
    status: str
    duration_seconds: float | None
    config_path: Path | None
    run_name: str
    sim_id: str
    x_outlet: float | None
    y_outlet: float | None
    area_km2: float | None
    tags: tuple[str, ...]
    display_output_dir: Path | None
    workspace_root: Path | None
    metrics: dict[str, str]


@dataclass(frozen=True)
class SiteDiagnostics:
    area_km2: float | None = None
    outlet_elevation_m: float | None = None
    mean_slope_percent: float | None = None
    q_max_m3_s: float | None = None
    q_mean_m3_s: float | None = None
    q_max_l_s_km2: float | None = None
    q_mean_l_s_km2: float | None = None
    q_max_mm_d: float | None = None
    q_mean_mm_d: float | None = None
    response_lag_days: float | None = None
    drained_volume_m3: float | None = None
    balance_error_percent: float | None = None


def _load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_toml(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8-sig"))


def _safe_text(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value)


def _float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except Exception:
        return None
    return parsed if math.isfinite(parsed) else None


def _format_float(value: Any, *, digits: int = 3) -> str:
    parsed = _float(value)
    if parsed is None:
        return ""
    if parsed == 0.0:
        return "0"
    if abs(parsed) >= 10000 or abs(parsed) < 0.001:
        return f"{parsed:.{digits}e}"
    return f"{parsed:.{digits}f}".rstrip("0").rstrip(".")


def _format_duration(value: Any) -> str:
    parsed = _float(value)
    if parsed is None:
        return "n/a"
    parsed = max(parsed, 0.0)
    if parsed < 60:
        return f"{parsed:.1f} s"
    minutes = int(parsed // 60)
    seconds = int(round(parsed - minutes * 60))
    if seconds == 60:
        minutes += 1
        seconds = 0
    if minutes < 60:
        return f"{minutes} min {seconds:02d} s"
    hours = minutes // 60
    return f"{hours} h {minutes % 60:02d} min"


def _resolve_path(raw_value: Any, *, base_dir: Path) -> Path | None:
    if raw_value in (None, ""):
        return None
    path = Path(str(raw_value)).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _link(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return path.resolve().relative_to(WEB_DIR.resolve()).as_posix()
    except Exception:
        return Path(os.path.relpath(path.resolve(), WEB_DIR.resolve())).as_posix()


def _site_catalog_by_id() -> dict[str, dict[str, str]]:
    return {
        str(row.get("site_id", "")).strip(): row
        for row in _load_csv(SITE_CATALOG_PATH)
        if row.get("site_id")
    }


def _metrics_by_variant() -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in _load_csv(OUTPUT_ROOT / "testbed_metrics.csv"):
        variant = str(row.get("variant_id", "")).strip()
        if variant:
            result[variant] = row
    return result


def _case_rows() -> list[dict[str, str]]:
    rows = _load_csv(OUTPUT_ROOT / "testbed_cases.csv")
    if rows:
        return rows
    manifest = _load_json(OUTPUT_ROOT / "testbed_manifest.json")
    return [case for case in manifest.get("cases", []) if isinstance(case, dict)]


def _case_from_row(
    row: dict[str, str],
    *,
    site_catalog: dict[str, dict[str, str]],
    metrics_by_variant: dict[str, dict[str, str]],
) -> SiteCase:
    variant_id = str(row.get("variant_id", "")).strip()
    site_id = variant_id.removeprefix("site_") if variant_id else ""
    site_row = site_catalog.get(site_id, {})
    config_path = _resolve_path(row.get("config_path"), base_dir=OUTPUT_ROOT)
    config = _load_toml(config_path)
    simulation = config.get("simulation", {}) if isinstance(config.get("simulation"), dict) else {}
    geographic = config.get("geographic", {}) if isinstance(config.get("geographic"), dict) else {}
    display = config.get("display", {}) if isinstance(config.get("display"), dict) else {}
    workspace = config.get("workspace", {}) if isinstance(config.get("workspace"), dict) else {}
    label = (
        str(site_row.get("site_label") or "").strip()
        or str(row.get("variant_label") or "").strip()
        or variant_id
    )
    return SiteCase(
        variant_id=variant_id,
        site_id=site_id,
        label=label,
        status=str(row.get("status", "")).strip(),
        duration_seconds=_float(row.get("duration_seconds")),
        config_path=config_path,
        run_name=str(row.get("name") or simulation.get("name") or simulation.get("run_id") or variant_id),
        sim_id=str(row.get("sim_id") or ""),
        x_outlet=_float(geographic.get("x_outlet") or site_row.get("x_outlet")),
        y_outlet=_float(geographic.get("y_outlet") or site_row.get("y_outlet")),
        area_km2=_float(site_row.get("area_km2")),
        tags=tuple(item.strip() for item in str(site_row.get("tags", "")).split(";") if item.strip()),
        display_output_dir=_resolve_path(display.get("output_dir"), base_dir=ROOT),
        workspace_root=_resolve_path(workspace.get("project_root"), base_dir=ROOT),
        metrics=metrics_by_variant.get(variant_id, {}),
    )


def _load_cases() -> list[SiteCase]:
    site_catalog = _site_catalog_by_id()
    metrics = _metrics_by_variant()
    return [
        _case_from_row(row, site_catalog=site_catalog, metrics_by_variant=metrics)
        for row in _case_rows()
    ]


def _figure_path(case: SiteCase, figure_name: str) -> Path | None:
    if case.display_output_dir is None:
        return None
    return case.display_output_dir / case.run_name / f"{figure_name}.png"


def _diagnostic_output_dir(case: SiteCase) -> Path | None:
    if case.display_output_dir is None:
        return None
    return case.display_output_dir / case.run_name


def _open_run(case: SiteCase):
    if case.workspace_root is None or not case.workspace_root.exists():
        return None, None
    try:
        from hydromodpy.results.catalog import SimulationCatalog

        catalog = SimulationCatalog(case.workspace_root)
        if case.sim_id:
            return catalog, catalog[case.sim_id]
        return catalog, catalog.latest()
    except Exception:
        try:
            catalog.close()  # type: ignore[name-defined]
        except Exception:
            pass
        return None, None


def _generate_diagnostic_figures(cases: list[SiteCase]) -> None:
    for case in cases:
        out_dir = _diagnostic_output_dir(case)
        if out_dir is None:
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        _render_site_regional_location_map(case, cases, out_dir / "site_regional_location.png")
        _render_watershed_id_card(case, out_dir / "watershed_id_card.png")
        _render_water_budget(case, out_dir / "water_budget.png")
        _render_catchment_flux_balance(case, out_dir)
        _render_recharge_discharge_overlay(case, out_dir / "recharge_discharge_overlay.png")
        _render_head_timeseries_points(case, out_dir / "head_timeseries_points.png")
        _render_hydrographic_network_overlay(case, out_dir / "hydrographic_network_overlay.png")
        _render_observed_network_seepage_overlay(case, out_dir / "observed_network_seepage_overlay.png")


def _site_short_label(case: SiteCase) -> str:
    token = case.site_id or case.variant_id.rsplit("_", 1)[-1]
    return token.zfill(2) if token.isdigit() else token


def _regional_location_path() -> Path:
    return WEB_DIR / "assets" / "regional_site_locations.png"


def _generate_regional_location_map(cases: list[SiteCase]) -> None:
    _render_regional_location_map(
        cases,
        output_path=_regional_location_path(),
        current_case=None,
        title="Localisation regionale des sites",
    )


def _render_site_regional_location_map(case: SiteCase, cases: list[SiteCase], output_path: Path) -> None:
    _render_regional_location_map(
        cases,
        output_path=output_path,
        current_case=case,
        title=f"Situation regionale - {case.label}",
    )


def _render_watershed_id_card(case: SiteCase, output_path: Path) -> None:
    catalog, run = _open_run(case)
    if run is None:
        return
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        from hydromodpy.display.figures.watershed_id_card import WatershedIdCardFigure

        fig = WatershedIdCardFigure().plot(run, save_path=output_path)
        plt.close(fig)
    except Exception:
        return
    finally:
        if catalog is not None:
            catalog.close()


def _render_water_budget(case: SiteCase, output_path: Path) -> None:
    catalog, run = _open_run(case)
    if run is None:
        return
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        from hydromodpy.display.figures.water_budget import WaterBudget

        fig = WaterBudget().plot(run, save_path=output_path)
        plt.close(fig)
    except Exception:
        return
    finally:
        if catalog is not None:
            catalog.close()


def _render_catchment_flux_balance(case: SiteCase, out_dir: Path) -> None:
    catalog, run = _open_run(case)
    if run is None:
        return
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        balance = _catchment_flux_balance_dataframe(catalog, run)
        if balance is None or balance.empty:
            return
        balance.to_csv(out_dir / "catchment_flux_balance.csv", index_label="time")
        _render_catchment_flux_balance_rates_plot(
            balance,
            case=case,
            output_path=out_dir / "catchment_flux_balance_rates.png",
        )
        plt.close("all")
    except Exception:
        return
    finally:
        if catalog is not None:
            catalog.close()


def _catchment_flux_balance_dataframe(catalog: Any, run: Any):
    import numpy as np
    import pandas as pd

    sz = catalog.open_zarr(run.sim_id)
    try:
        budget = sz.root.get("budget")
        if budget is None:
            return None
        required = ("recharge", "drains", "storage", "flow right face", "flow front face")
        if any(name not in budget for name in required):
            return None
        centroids = _mesh_face_centroids(run.mesh)
        shape = _structured_shape_from_centroids(centroids)
        if shape is None:
            return None
        nrow, ncol = shape
        n = int(run.n_timesteps or budget["recharge"].shape[0])
        cell_mask = _model_catchment_mask(run, centroids=centroids, shape=shape)
        if cell_mask is None or not np.any(cell_mask):
            return None
        area_m2 = _model_cell_area_m2(run, shape) * float(np.count_nonzero(cell_mask))
        if not np.isfinite(area_m2) or area_m2 <= 0.0:
            return None

        def read(name: str) -> np.ndarray:
            return _budget_array_2d(budget, name=name, n=n, shape=shape)

        recharge_in, recharge_out = _positive_negative_inside(read("recharge"), cell_mask)
        drains_in, drains_out = _positive_negative_inside(read("drains"), cell_mask)
        storage_in, storage_out = _positive_negative_inside(read("storage"), cell_mask)
        chd_in, chd_out = (
            _positive_negative_inside(read("constant head"), cell_mask)
            if "constant head" in budget
            else (np.zeros(n), np.zeros(n))
        )
        lateral_in, lateral_out = _lateral_boundary_exchange(
            right_face=read("flow right face"),
            front_face=read("flow front face"),
            cell_mask=cell_mask,
        )

        total_in = recharge_in + drains_in + storage_in + chd_in + lateral_in
        total_out = recharge_out + drains_out + storage_out + chd_out + lateral_out
        residual = total_in - total_out
        time_index = _run_time_index(run, n)
        factor_mm_d = 86400.0 * 1000.0 / area_m2
        durations_s = _time_durations_seconds(time_index)
        data = {
            "area_m2": np.full(n, area_m2),
            "recharge_in_m3_s": recharge_in,
            "recharge_out_m3_s": recharge_out,
            "drains_in_m3_s": drains_in,
            "drains_out_m3_s": drains_out,
            "storage_release_in_m3_s": storage_in,
            "storage_fill_out_m3_s": storage_out,
            "boundary_condition_in_m3_s": chd_in,
            "boundary_condition_out_m3_s": chd_out,
            "lateral_boundary_in_m3_s": lateral_in,
            "lateral_boundary_out_m3_s": lateral_out,
            "total_in_m3_s": total_in,
            "total_out_m3_s": total_out,
            "residual_m3_s": residual,
        }
        df = pd.DataFrame(data, index=time_index)
        for column in [col for col in df.columns if col.endswith("_m3_s")]:
            df[column.replace("_m3_s", "_mm_d")] = df[column] * factor_mm_d
            df[column.replace("_m3_s", "_cum_mm")] = np.cumsum(
                df[column].to_numpy(dtype=float) * durations_s * 1000.0 / area_m2
            )
        return df
    finally:
        sz.close()


def _structured_shape_from_centroids(centroids: Any) -> tuple[int, int] | None:
    import numpy as np

    values = np.asarray(centroids, dtype=float)
    if values.ndim != 2 or values.shape[1] < 2 or values.shape[0] == 0:
        return None
    xs = np.unique(np.round(values[:, 0], 6))
    ys = np.unique(np.round(values[:, 1], 6))
    if xs.size * ys.size != values.shape[0]:
        return None
    return int(ys.size), int(xs.size)


def _model_cell_area_m2(run: Any, shape: tuple[int, int]) -> float:
    try:
        xmin, xmax, ymin, ymax = [float(value) for value in run.grid.extent]
        nrow, ncol = shape
        return abs((xmax - xmin) / float(ncol) * (ymax - ymin) / float(nrow))
    except Exception:
        try:
            return float(run.grid.cell_size) ** 2
        except Exception:
            return 1.0


def _budget_array_2d(group: Any, *, name: str, n: int, shape: tuple[int, int]):
    import numpy as np

    raw = np.asarray(group[name][:], dtype=float)
    if raw.ndim == 3:
        raw = raw.reshape(raw.shape[0], raw.shape[1], -1).sum(axis=1)
    elif raw.ndim > 2:
        raw = raw.reshape(raw.shape[0], -1)
    elif raw.ndim == 1:
        raw = raw.reshape(1, -1)
    return raw[:n].reshape(n, shape[0], shape[1])


def _clean_budget_values(values: Any):
    import numpy as np

    arr = np.asarray(values, dtype=float)
    return np.where(np.isfinite(arr) & (arr > -9000.0), arr, 0.0)


def _positive_negative_inside(values: Any, cell_mask: Any):
    import numpy as np

    arr = np.where(np.asarray(cell_mask, dtype=bool)[None, :, :], _clean_budget_values(values), 0.0)
    return np.maximum(arr, 0.0).sum(axis=(1, 2)), np.maximum(-arr, 0.0).sum(axis=(1, 2))


def _lateral_boundary_exchange(*, right_face: Any, front_face: Any, cell_mask: Any):
    import numpy as np

    mask = np.asarray(cell_mask, dtype=bool)
    n = np.asarray(right_face).shape[0]
    lateral_in = np.zeros(n, dtype=float)
    lateral_out = np.zeros(n, dtype=float)

    values = _clean_budget_values(right_face)[:, :, :-1]
    left = mask[:, :-1][None, :, :]
    right = mask[:, 1:][None, :, :]
    left_in = left & ~right
    right_in = ~left & right
    lateral_in += (
        np.where(left_in, np.maximum(-values, 0.0), 0.0)
        + np.where(right_in, np.maximum(values, 0.0), 0.0)
    ).sum(axis=(1, 2))
    lateral_out += (
        np.where(left_in, np.maximum(values, 0.0), 0.0)
        + np.where(right_in, np.maximum(-values, 0.0), 0.0)
    ).sum(axis=(1, 2))

    values = _clean_budget_values(front_face)[:, :-1, :]
    upper = mask[:-1, :][None, :, :]
    lower = mask[1:, :][None, :, :]
    upper_in = upper & ~lower
    lower_in = ~upper & lower
    lateral_in += (
        np.where(upper_in, np.maximum(-values, 0.0), 0.0)
        + np.where(lower_in, np.maximum(values, 0.0), 0.0)
    ).sum(axis=(1, 2))
    lateral_out += (
        np.where(upper_in, np.maximum(values, 0.0), 0.0)
        + np.where(lower_in, np.maximum(-values, 0.0), 0.0)
    ).sum(axis=(1, 2))
    return lateral_in, lateral_out


def _model_catchment_mask(run: Any, *, centroids: Any, shape: tuple[int, int]):
    try:
        import numpy as np
        from shapely.geometry import Point

        geom = _catchment_geometry(run)
        if geom is None:
            return None
        values = np.asarray(centroids, dtype=float)
        inside = [bool(geom.covers(Point(float(x), float(y)))) for x, y in values[:, :2]]
        return np.asarray(inside, dtype=bool).reshape(shape)
    except Exception:
        return None


def _time_durations_seconds(index: Any):
    import numpy as np
    import pandas as pd

    try:
        dt_index = pd.DatetimeIndex(index)
        if len(dt_index) >= 2:
            deltas = np.diff(dt_index.view("int64") / 1e9)
            last = float(np.nanmedian(deltas)) if deltas.size else 30.0 * 86400.0
            return np.concatenate([deltas, [last]])[: len(dt_index)]
    except Exception:
        pass
    return np.full(len(index), 30.0 * 86400.0, dtype=float)


def _render_catchment_flux_balance_rates_plot(balance: Any, *, case: SiteCase, output_path: Path) -> None:
    import numpy as np
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9.0, 4.9), dpi=150)
    x = balance.index
    inputs = (
        ("recharge_in_mm_d", "recharge", "#2f8f46"),
        ("lateral_boundary_in_mm_d", "lateral entrant", "#4f81bd"),
        ("storage_release_in_mm_d", "destockage", "#8d6ab8"),
        ("boundary_condition_in_mm_d", "limite entrante", "#7aa6a1"),
    )
    outputs = (
        ("drains_out_mm_d", "drainage/suintement", "#c45a2a"),
        ("lateral_boundary_out_mm_d", "lateral sortant", "#d69f35"),
        ("storage_fill_out_mm_d", "stockage", "#7e6b5a"),
        ("boundary_condition_out_mm_d", "limite sortante", "#9a9a9a"),
    )
    _signed_stack(ax, x, balance, inputs, sign=1.0)
    _signed_stack(ax, x, balance, outputs, sign=-1.0)
    residual = balance["residual_mm_d"].to_numpy(dtype=float)
    ax.plot(x, residual, color="#17202a", lw=1.3, label="residu")
    ax.axhline(0.0, color="#17202a", lw=0.8)
    ax.set_title(f"Entrees et sorties bassin hors tampon - {case.label}")
    ax.set_ylabel("Flux specifique (mm/j)")
    ax.set_xlabel("Date")
    ax.grid(True, ls=":", lw=0.45, color="#cfd8df")
    max_abs = np.nanmax(np.abs(np.r_[residual, balance["total_in_mm_d"], balance["total_out_mm_d"]]))
    if np.isfinite(max_abs) and max_abs > 0:
        ax.set_ylim(-1.15 * max_abs, 1.15 * max_abs)
    ax.legend(loc="upper right", fontsize=8, ncols=2)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)


def _signed_stack(ax: Any, x: Any, frame: Any, columns: tuple[tuple[str, str, str], ...], *, sign: float) -> None:
    import numpy as np

    base = np.zeros(len(frame), dtype=float)
    for column, label, color in columns:
        if column not in frame:
            continue
        values = np.nan_to_num(frame[column].to_numpy(dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
        if not np.any(values > 0.0):
            continue
        lower = sign * base
        upper = sign * (base + values)
        ax.fill_between(x, lower, upper, color=color, alpha=0.72, linewidth=0, label=label)
        base += values


def _plot_dem_background(ax: Any, bounds: tuple[float, float, float, float]) -> None:
    if not REGIONAL_DEM_PATH.exists():
        return
    try:
        import numpy as np
        import rasterio
        from matplotlib.colors import LightSource
        from rasterio.windows import from_bounds

        minx, maxx, miny, maxy = bounds
        with rasterio.open(REGIONAL_DEM_PATH) as src:
            window = from_bounds(minx, miny, maxx, maxy, transform=src.transform)
            dem = src.read(1, window=window, masked=True)
            transform = src.window_transform(window)
        values = np.asarray(dem.filled(np.nan), dtype=float)
        if not np.isfinite(values).any():
            return
        ls = LightSource(azdeg=315, altdeg=45)
        shade = ls.hillshade(np.nan_to_num(values, nan=float(np.nanmean(values))), vert_exag=1.8)
        extent = (
            transform.c,
            transform.c + transform.a * values.shape[1],
            transform.f + transform.e * values.shape[0],
            transform.f,
        )
        ax.imshow(shade, extent=extent, cmap="Greys", alpha=0.36, zorder=0)
        ax.imshow(values, extent=extent, cmap="terrain", alpha=0.28, zorder=1)
    except Exception:
        return


def _render_regional_location_map(
    cases: list[SiteCase],
    *,
    output_path: Path,
    current_case: SiteCase | None,
    title: str,
) -> None:
    valid_cases = [
        case
        for case in cases
        if case.x_outlet is not None and case.y_outlet is not None
    ]
    if not valid_cases:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        xs = [float(case.x_outlet) for case in valid_cases]
        ys = [float(case.y_outlet) for case in valid_cases]
        network = None
        if REGIONAL_NETWORK_PATH.exists():
            try:
                import geopandas as gpd

                network = gpd.read_file(REGIONAL_NETWORK_PATH)
            except Exception:
                network = None

        margin_x = max((max(xs) - min(xs)) * 0.12, 2500.0)
        margin_y = max((max(ys) - min(ys)) * 0.12, 2500.0)
        if network is not None and not network.empty:
            minx, miny, maxx, maxy = [float(value) for value in network.total_bounds]
            xlim = (minx - margin_x, maxx + margin_x)
            ylim = (miny - margin_y, maxy + margin_y)
        else:
            xlim = (min(xs) - margin_x, max(xs) + margin_x)
            ylim = (min(ys) - margin_y, max(ys) + margin_y)

        fig, ax = plt.subplots(figsize=(8.4, 7.2), dpi=150)
        _plot_dem_background(ax, (*xlim, *ylim))
        if network is not None and not network.empty:
            network.plot(ax=ax, color="#255f76", linewidth=0.45, alpha=0.75, zorder=2)

        other_cases = [
            case
            for case in valid_cases
            if current_case is None or case.variant_id != current_case.variant_id
        ]
        other_xs = [float(case.x_outlet) for case in other_cases]
        other_ys = [float(case.y_outlet) for case in other_cases]
        if other_xs:
            ax.scatter(
                other_xs,
                other_ys,
                s=42,
                color="#5f7480",
                edgecolor="white",
                linewidth=0.7,
                alpha=0.90,
                zorder=3,
            )
        if current_case is None:
            ax.scatter(xs, ys, s=58, color="#b63d2e", edgecolor="white", linewidth=0.8, zorder=4)
        elif current_case.x_outlet is not None and current_case.y_outlet is not None:
            ax.scatter(
                [float(current_case.x_outlet)],
                [float(current_case.y_outlet)],
                s=100,
                color="#b63d2e",
                edgecolor="white",
                linewidth=1.1,
                zorder=5,
            )
        for case, x, y in zip(valid_cases, xs, ys, strict=False):
            is_current = current_case is not None and case.variant_id == current_case.variant_id
            ax.annotate(
                _site_short_label(case),
                xy=(x, y),
                xytext=(5, 5),
                textcoords="offset points",
                fontsize=9 if is_current else 8,
                fontweight="bold",
                color="#17202a" if is_current else "#44545f",
                zorder=6 if is_current else 4,
            )

        ax.set_xlim(*xlim)
        ax.set_ylim(*ylim)
        ax.set_aspect("equal", adjustable="box")
        ax.set_title(title)
        ax.set_xlabel("X Lambert-93 (m)")
        ax.set_ylabel("Y Lambert-93 (m)")
        ax.grid(True, ls=":", lw=0.35, color="#c7d2d9")
        fig.tight_layout()
        fig.savefig(output_path)
        plt.close(fig)
    except Exception:
        return


def _render_recharge_discharge_overlay(case: SiteCase, output_path: Path) -> None:
    catalog, run = _open_run(case)
    if run is None:
        return
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import pandas as pd

        budget = run.budget()
        discharge = run.timeseries("discharge", station="_catchment")
        if budget.empty or discharge.empty:
            return
        n = int(run.n_timesteps or len(discharge.index))
        time_index = _run_time_index(run, n, fallback=discharge.index)
        recharge = _budget_component_series(
            budget,
            component="recharge",
            column="flux_in",
            time_index=time_index,
        )
        drains = _budget_component_series(
            budget,
            component="drains",
            column="flux_out",
            time_index=time_index,
        )
        discharge = pd.Series(discharge.values[: len(time_index)], index=time_index)

        fig, ax = plt.subplots(figsize=(8.2, 4.4), dpi=150)
        ax.plot(recharge.index, recharge.values, color="#2f8f46", lw=1.8, label="recharge budgetaire")
        ax.fill_between(recharge.index, recharge.values, color="#2f8f46", alpha=0.16, linewidth=0)
        ax.plot(discharge.index, discharge.values, color="#1f5f9c", lw=1.8, label="decharge exutoire")
        if drains.notna().any():
            ax.plot(drains.index, drains.values, color="#9b5b1a", lw=1.1, ls="--", label="sortie drains")
        ax.set_title(f"Recharge et decharge - {case.label}")
        ax.set_ylabel("Flux (m3/s)")
        ax.set_xlabel("Date")
        ax.grid(True, ls=":", lw=0.45)
        ax.legend(loc="best")
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(output_path)
        plt.close(fig)
    except Exception:
        return
    finally:
        if catalog is not None:
            catalog.close()


def _render_hydrographic_network_overlay(case: SiteCase, output_path: Path) -> None:
    catalog, run = _open_run(case)
    if run is None:
        return
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.lines import Line2D

        comparison = run.hydrographic_network_comparison()
        reference = getattr(comparison, "reference_gdf", None)
        candidate = getattr(comparison, "candidate_gdf", None)
        if reference is None and candidate is None:
            return
        fig, ax = plt.subplots(figsize=(7.2, 6.2), dpi=150)
        if reference is not None and not reference.empty:
            reference.plot(ax=ax, color="#1f6f78", linewidth=2.0, alpha=0.90, zorder=2)
        if candidate is not None and not candidate.empty:
            candidate.plot(ax=ax, color="#c45a2a", linewidth=1.5, alpha=0.95, linestyle="--", zorder=3)
        _plot_catchment_boundary(ax, run)
        if case.x_outlet is not None and case.y_outlet is not None:
            ax.scatter([case.x_outlet], [case.y_outlet], s=42, color="#17202a", edgecolor="white", zorder=4)
        ax.set_title(f"Reseau genere et observe - {case.label}")
        ax.set_xlabel("X Lambert-93 (m)")
        ax.set_ylabel("Y Lambert-93 (m)")
        ax.set_aspect("equal", adjustable="box")
        ax.grid(True, ls=":", lw=0.35, color="#d5dde3")
        ax.legend(
            handles=[
                Line2D([0], [0], color="#1f6f78", lw=2.0, label="observe"),
                Line2D([0], [0], color="#c45a2a", lw=1.5, ls="--", label="genere"),
                Line2D([0], [0], color="#17202a", lw=1.6, label="bassin"),
            ],
            loc="best",
            frameon=True,
        )
        fig.tight_layout()
        fig.savefig(output_path)
        plt.close(fig)
    except Exception:
        return
    finally:
        if catalog is not None:
            catalog.close()


def _render_observed_network_seepage_overlay(case: SiteCase, output_path: Path) -> None:
    catalog, run = _open_run(case)
    if run is None:
        return
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.lines import Line2D

        comparison = run.hydrographic_network_comparison()
        reference = getattr(comparison, "reference_gdf", None)
        seepage_mask, seepage_label = _seepage_like_mask(run)
        if (reference is None or reference.empty) and seepage_mask is None:
            return
        fig, ax = plt.subplots(figsize=(7.2, 6.2), dpi=150)
        _plot_catchment_boundary(ax, run)
        if seepage_mask is not None:
            centroids = _mesh_face_centroids(run.mesh)
            if centroids.shape[0] == seepage_mask.size:
                points = centroids[seepage_mask]
                if points.size:
                    ax.scatter(
                        points[:, 0],
                        points[:, 1],
                        s=8,
                        marker="s",
                        color="#d05a27",
                        alpha=0.70,
                        linewidth=0,
                        zorder=2,
                    )
        if reference is not None and not reference.empty:
            reference.plot(ax=ax, color="#1f6f78", linewidth=1.8, alpha=0.95, zorder=3)
        if case.x_outlet is not None and case.y_outlet is not None:
            ax.scatter([case.x_outlet], [case.y_outlet], s=42, color="#17202a", edgecolor="white", zorder=4)
        ax.set_title(f"Reseau observe et zones de suintement - {case.label}")
        ax.set_xlabel("X Lambert-93 (m)")
        ax.set_ylabel("Y Lambert-93 (m)")
        ax.set_aspect("equal", adjustable="box")
        ax.grid(True, ls=":", lw=0.35, color="#d5dde3")
        ax.legend(
            handles=[
                Line2D([0], [0], color="#1f6f78", lw=1.8, label="reseau observe"),
                Line2D([0], [0], color="#d05a27", marker="s", markersize=6, lw=0, label=seepage_label),
                Line2D([0], [0], color="#17202a", lw=1.6, label="bassin"),
            ],
            loc="best",
            frameon=True,
        )
        fig.tight_layout()
        fig.savefig(output_path)
        plt.close(fig)
    except Exception:
        return
    finally:
        if catalog is not None:
            catalog.close()


def _seepage_like_mask(run: Any) -> tuple[Any | None, str]:
    try:
        import numpy as np

        for field_name, label in (
            ("seepage_areas", "suintement"),
            ("seepage_area", "suintement"),
        ):
            try:
                if run.has_field(field_name):
                    values = np.asarray(run.field(field_name, timestep=-1), dtype=float).reshape(-1)
                    return values > 0.5, label
            except Exception:
                pass
        if run.has_field("outflow_drain"):
            values = np.asarray(run.field("outflow_drain", timestep=-1), dtype=float).reshape(-1)
            finite_positive = np.isfinite(values) & (values > 0.0)
            return finite_positive, "drainage/suintement"
        if run.has_field("watertable_depth"):
            values = np.asarray(run.field("watertable_depth", timestep=-1), dtype=float).reshape(-1)
            near_surface = np.isfinite(values) & (values <= 0.05)
            return near_surface, "nappe proche surface"
    except Exception:
        return None, "suintement"
    return None, "suintement"


def _plot_catchment_boundary(ax: Any, run: Any) -> bool:
    try:
        geometry = _catchment_geometry(run)
        if geometry is None:
            return False
        _plot_shapely_boundary(ax, geometry, color="#17202a", linewidth=1.6, zorder=4)
        return True
    except Exception:
        return _plot_catchment_boundary_contour(ax, run)


def _catchment_geometry(run: Any) -> Any | None:
    try:
        import numpy as np
        from rasterio.features import shapes
        from rasterio.transform import from_origin
        from shapely.geometry import shape
        from shapely.ops import unary_union

        mask = np.asarray(run.catchment_mask, dtype=bool)
        if mask.ndim != 2 or not mask.any():
            return None
        xmin, _xmax, _ymin, ymax = [float(value) for value in run.grid.extent]
        cell = float(run.grid.cell_size)
        transform = from_origin(xmin, ymax, cell, cell)
        geometries = [
            shape(geom)
            for geom, value in shapes(mask.astype("uint8"), mask=mask, transform=transform)
            if int(value) == 1
        ]
        if not geometries:
            return None
        return unary_union(geometries)
    except Exception:
        return None


def _plot_shapely_boundary(ax: Any, geom: Any, *, color: str, linewidth: float, zorder: int) -> None:
    geom_type = getattr(geom, "geom_type", "")
    if geom_type == "Polygon":
        x, y = geom.exterior.xy
        ax.plot(x, y, color=color, linewidth=linewidth, zorder=zorder)
        for interior in geom.interiors:
            ix, iy = interior.xy
            ax.plot(ix, iy, color=color, linewidth=max(linewidth * 0.6, 0.6), zorder=zorder)
        return
    if hasattr(geom, "geoms"):
        for part in geom.geoms:
            _plot_shapely_boundary(ax, part, color=color, linewidth=linewidth, zorder=zorder)


def _plot_catchment_boundary_contour(ax: Any, run: Any) -> bool:
    try:
        import numpy as np

        mask = np.asarray(run.catchment_mask, dtype=float)
        if mask.ndim != 2 or not np.isfinite(mask).any() or np.nanmax(mask) <= 0:
            return False
        xmin, xmax, ymin, ymax = [float(value) for value in run.grid.extent]
        cell = float(run.grid.cell_size)
        xs = np.linspace(xmin + 0.5 * cell, xmax - 0.5 * cell, mask.shape[1])
        ys = np.linspace(ymax - 0.5 * cell, ymin + 0.5 * cell, mask.shape[0])
        xx, yy = np.meshgrid(xs, ys)
        ax.contour(xx, yy, mask, levels=[0.5], colors="#17202a", linewidths=1.6, zorder=4)
        return True
    except Exception:
        return False


def _render_head_timeseries_points(case: SiteCase, output_path: Path) -> None:
    catalog, run = _open_run(case)
    if run is None:
        return
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        n = int(run.n_timesteps or 0)
        if n <= 0 or not run.has_field("head"):
            return
        heads = []
        for timestep in range(n):
            values = np.asarray(run.field("head", timestep=timestep), dtype=float)
            if values.ndim == 2:
                values = values[0]
            heads.append(values.reshape(-1))
        head_stack = np.vstack(heads)
        centroids = _mesh_face_centroids(run.mesh)
        if centroids.shape[0] != head_stack.shape[1]:
            return
        finite = np.isfinite(head_stack)
        valid = finite.any(axis=0) & (np.nanmax(np.where(finite, head_stack, np.nan), axis=0) > -1000.0)
        valid &= np.isfinite(centroids).all(axis=1)
        valid_indices = np.flatnonzero(valid)
        if valid_indices.size == 0:
            return
        selected = _select_head_probe_indices(
            centroids,
            head_stack,
            valid_indices=valid_indices,
            outlet_xy=getattr(run, "outlet", None),
        )
        if not selected:
            return
        time_index = _run_time_index(run, n)
        fig, ax = plt.subplots(figsize=(8.2, 4.4), dpi=150)
        for label, index in selected:
            x, y = centroids[index]
            ax.plot(time_index, head_stack[:, index], lw=1.35, label=f"{label} ({x:.0f}, {y:.0f})")
        ax.set_title(f"Charges ponctuelles - {case.label}")
        ax.set_ylabel("Charge hydraulique (m)")
        ax.set_xlabel("Date")
        ax.grid(True, ls=":", lw=0.45)
        ax.legend(loc="best", fontsize=8)
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(output_path)
        plt.close(fig)
    except Exception:
        return
    finally:
        if catalog is not None:
            catalog.close()


def _run_time_index(run: Any, n: int, *, fallback: Any = None):
    import pandas as pd

    try:
        idx = run.time_index
    except Exception:
        idx = fallback
    if idx is None or len(idx) < n:
        idx = fallback if fallback is not None and len(fallback) >= n else pd.RangeIndex(n)
    idx = pd.Index(idx[:n])
    try:
        dt_idx = pd.DatetimeIndex(idx)
        if dt_idx.tz is not None:
            dt_idx = dt_idx.tz_convert("UTC").tz_localize(None)
        return dt_idx
    except Exception:
        return idx


def _budget_component_series(budget: Any, *, component: str, column: str, time_index: Any):
    import pandas as pd

    subset = budget[budget["component"].astype(str).str.lower() == component.lower()]
    if subset.empty or column not in subset:
        return pd.Series([float("nan")] * len(time_index), index=time_index)
    values = subset.groupby("timestep")[column].sum()
    return pd.Series([float(values.get(timestep, float("nan"))) for timestep in range(len(time_index))], index=time_index)


def _compute_site_diagnostics(cases: list[SiteCase]) -> dict[str, SiteDiagnostics]:
    return {case.variant_id: _compute_one_site_diagnostics(case) for case in cases}


def _compute_one_site_diagnostics(case: SiteCase) -> SiteDiagnostics:
    catalog, run = _open_run(case)
    if run is None:
        return SiteDiagnostics(area_km2=case.area_km2)
    try:
        import numpy as np
        import pandas as pd

        area_km2 = case.area_km2
        try:
            area_km2 = float(run.grid.catchment_area_m2) / 1_000_000.0
        except Exception:
            pass

        outlet_elevation_m = _outlet_elevation_m(run)
        mean_slope_percent = _mean_slope_percent(run)
        discharge = run.timeseries("discharge", station="_catchment")
        q_values = pd.Series(discharge).astype(float)
        q_max = float(q_values.max()) if len(q_values) else None
        q_mean = float(q_values.mean()) if len(q_values) else None
        q_max_l_s_km2 = _specific_l_s_km2(q_max, area_km2)
        q_mean_l_s_km2 = _specific_l_s_km2(q_mean, area_km2)
        q_max_mm_d = _specific_mm_d(q_max, area_km2)
        q_mean_mm_d = _specific_mm_d(q_mean, area_km2)

        n = int(run.n_timesteps or len(q_values))
        time_index = _run_time_index(run, n, fallback=getattr(discharge, "index", None))
        q_series = pd.Series(q_values.values[: len(time_index)], index=time_index)
        budget = run.budget()
        recharge = _budget_component_series(
            budget,
            component="recharge",
            column="flux_in",
            time_index=time_index,
        )
        drains = _budget_component_series(
            budget,
            component="drains",
            column="flux_out",
            time_index=time_index,
        )
        response_lag_days = _peak_lag_days(recharge, q_series)
        drained_volume_m3 = _integrate_flux_series_m3(drains)
        if drained_volume_m3 is None:
            drained_volume_m3 = _integrate_flux_series_m3(q_series)

        return SiteDiagnostics(
            area_km2=area_km2,
            outlet_elevation_m=outlet_elevation_m,
            mean_slope_percent=mean_slope_percent,
            q_max_m3_s=q_max,
            q_mean_m3_s=q_mean,
            q_max_l_s_km2=q_max_l_s_km2,
            q_mean_l_s_km2=q_mean_l_s_km2,
            q_max_mm_d=q_max_mm_d,
            q_mean_mm_d=q_mean_mm_d,
            response_lag_days=response_lag_days,
            drained_volume_m3=drained_volume_m3,
            balance_error_percent=_mass_balance_error_percent(run),
        )
    except Exception:
        return SiteDiagnostics(area_km2=case.area_km2)
    finally:
        if catalog is not None:
            catalog.close()


def _specific_l_s_km2(q_m3_s: float | None, area_km2: float | None) -> float | None:
    if q_m3_s is None or area_km2 is None or area_km2 <= 0:
        return None
    return q_m3_s * 1000.0 / area_km2


def _specific_mm_d(q_m3_s: float | None, area_km2: float | None) -> float | None:
    if q_m3_s is None or area_km2 is None or area_km2 <= 0:
        return None
    return q_m3_s * 86.4 / area_km2


def _outlet_elevation_m(run: Any) -> float | None:
    try:
        import numpy as np

        dem = np.asarray(run.dem, dtype=float)
        x, y = run.outlet
        grid = run.grid
        xmin, xmax, ymin, ymax = [float(value) for value in grid.extent]
        cell = float(grid.cell_size)
        col = int(round((float(x) - (xmin + 0.5 * cell)) / cell))
        row = int(round(((ymax - 0.5 * cell) - float(y)) / cell))
        row = max(0, min(row, dem.shape[0] - 1))
        col = max(0, min(col, dem.shape[1] - 1))
        value = float(dem[row, col])
        return value if math.isfinite(value) else None
    except Exception:
        return None


def _mean_slope_percent(run: Any) -> float | None:
    try:
        import numpy as np

        dem = np.asarray(run.dem, dtype=float)
        mask = np.asarray(run.catchment_mask, dtype=bool)
        cell = float(run.grid.cell_size)
        grad_y, grad_x = np.gradient(dem, cell, cell)
        slope = np.sqrt(grad_x * grad_x + grad_y * grad_y) * 100.0
        value = float(np.nanmean(np.where(mask, slope, np.nan)))
        return value if math.isfinite(value) else None
    except Exception:
        return None


def _peak_lag_days(recharge: Any, discharge: Any) -> float | None:
    try:
        if recharge.empty or discharge.empty or not recharge.notna().any() or not discharge.notna().any():
            return None
        lag = discharge.idxmax() - recharge.idxmax()
        return float(lag.total_seconds() / 86400.0)
    except Exception:
        return None


def _integrate_flux_series_m3(series: Any) -> float | None:
    try:
        import numpy as np
        import pandas as pd

        values = pd.Series(series).astype(float)
        if values.empty or not values.notna().any():
            return None
        idx = pd.DatetimeIndex(values.index)
        if len(idx) >= 2:
            deltas = np.diff(idx.view("int64") / 1e9)
            last = float(np.nanmedian(deltas)) if deltas.size else 30.0 * 86400.0
            durations = np.concatenate([deltas, [last]])
        else:
            durations = np.array([30.0 * 86400.0])
        return float(np.nansum(values.to_numpy(dtype=float) * durations[: len(values)]))
    except Exception:
        return None


def _mass_balance_error_percent(run: Any) -> float | None:
    try:
        mb = run.mass_balance
        if mb is None or mb.empty or "percent_error" not in mb:
            return None
        value = float(mb["percent_error"].abs().max())
        return value if math.isfinite(value) else None
    except Exception:
        return None


def _mesh_face_centroids(mesh: Any):
    import numpy as np

    vertices = np.asarray(mesh.vertices, dtype=float)
    faces = np.asarray(mesh.face_node_connectivity)
    centroids = np.full((faces.shape[0], 2), np.nan, dtype=float)
    for i, face in enumerate(faces):
        node_ids = np.asarray(face, dtype=int)
        node_ids = node_ids[node_ids >= 0]
        if node_ids.size:
            centroids[i] = np.nanmean(vertices[node_ids, :2], axis=0)
    return centroids


def _select_head_probe_indices(centroids: Any, heads: Any, *, valid_indices: Any, outlet_xy: tuple[float, float] | None):
    import numpy as np

    valid_centroids = centroids[valid_indices]
    selected: list[tuple[str, int]] = []
    if outlet_xy is not None:
        outlet = np.asarray(outlet_xy, dtype=float)
        d = np.sum((valid_centroids - outlet) ** 2, axis=1)
        selected.append(("exutoire", int(valid_indices[int(np.nanargmin(d))])))
    center = np.nanmedian(valid_centroids, axis=0)
    d_center = np.sum((valid_centroids - center) ** 2, axis=1)
    selected.append(("centre", int(valid_indices[int(np.nanargmin(d_center))])))
    if outlet_xy is not None:
        outlet = np.asarray(outlet_xy, dtype=float)
        d = np.sum((valid_centroids - outlet) ** 2, axis=1)
        selected.append(("amont eloigne", int(valid_indices[int(np.nanargmax(d))])))
    first_heads = heads[0, valid_indices]
    finite_first = np.isfinite(first_heads)
    if finite_first.any():
        local = int(np.nanargmax(np.where(finite_first, first_heads, np.nan)))
        selected.append(("charge haute", int(valid_indices[local])))
    deduped: list[tuple[str, int]] = []
    seen: set[int] = set()
    for label, index in selected:
        if index in seen:
            continue
        seen.add(index)
        deduped.append((label, index))
    return deduped


def _figure_title_caption(figure_name: str) -> tuple[str, str]:
    for name, title, caption in FIGURES:
        if name == figure_name:
            return title, caption
    return figure_name, ""


def _figure_html(case: SiteCase, figure_name: str, *, compact: bool = False) -> str:
    title, caption = _figure_title_caption(figure_name)
    path = _figure_path(case, figure_name)
    if path is not None and path.exists():
        image = f'<a href="{_safe_text(_link(path))}"><img src="{_safe_text(_link(path))}" alt="{_safe_text(title)}"></a>'
    else:
        image = '<div class="missing">Figure non generee</div>'
    klass = "figure-card compact" if compact else "figure-card"
    return f"""
      <figure class="{klass}">
        {image}
        <figcaption><strong>{_safe_text(title)}</strong><span>{_safe_text(caption)}</span></figcaption>
      </figure>
    """


def _regional_location_html() -> str:
    path = _regional_location_path()
    if path.exists():
        image = f'<a href="{_safe_text(_link(path))}"><img src="{_safe_text(_link(path))}" alt="Localisation regionale des sites"></a>'
    else:
        image = '<div class="missing">Carte regionale non generee</div>'
    return f"""
      <figure class="figure-card wide">
        {image}
        <figcaption>
          <strong>Localisation regionale</strong>
          <span>Exutoires numerotes sur le reseau hydrographique de reference.</span>
        </figcaption>
      </figure>
    """


def _asset_figure_html(filename: str, title: str, caption: str) -> str:
    path = WEB_DIR / "assets" / filename
    if path.exists():
        image = f'<a href="{_safe_text(_link(path))}"><img src="{_safe_text(_link(path))}" alt="{_safe_text(title)}"></a>'
    else:
        image = '<div class="missing">Figure non generee</div>'
    return f"""
      <figure class="figure-card">
        {image}
        <figcaption><strong>{_safe_text(title)}</strong><span>{_safe_text(caption)}</span></figcaption>
      </figure>
    """


def _scatter_gallery_html() -> str:
    figures = "\n".join(_asset_figure_html(filename, title, caption) for filename, title, caption in INDEX_SCATTER_FIGURES)
    return f'<div class="figure-grid">{figures}</div>'


def _status_class(status: str) -> str:
    token = status.strip().lower()
    if token == "ok":
        return "ok"
    if token in {"failed", "error"}:
        return "bad"
    if token in {"planned", "disabled"}:
        return "planned"
    return "warn"


def _status_label(status: str) -> str:
    token = status.strip().lower()
    if token == "ok":
        return "Simulation terminee"
    if token in {"failed", "error"}:
        return "Simulation echouee"
    if token in {"planned", "disabled"}:
        return "Simulation non executee"
    return "Statut a verifier"


def _case_counts(cases: list[SiteCase]) -> dict[str, int]:
    counts = {"total": len(cases), "ok": 0, "bad": 0, "planned": 0, "warn": 0}
    for case in cases:
        counts[_status_class(case.status)] += 1
    return counts


def _total_duration_seconds(cases: list[SiteCase]) -> float | None:
    durations = [case.duration_seconds for case in cases if case.duration_seconds is not None]
    if not durations:
        return None
    return sum(durations)


def _status_summary_html(cases: list[SiteCase]) -> str:
    counts = _case_counts(cases)
    pending = counts["planned"] + counts["warn"]
    tiles = (
        ("Sites", counts["total"], "cas declares", ""),
        ("OK", counts["ok"], "simulations terminees", "ok"),
        ("Echecs", counts["bad"], "simulations en erreur", "bad"),
        ("A verifier", pending, "non executees ou statut inconnu", "planned"),
        ("Temps total", _format_duration(_total_duration_seconds(cases)), "temps cumule workflow", ""),
    )
    return "\n".join(
        f"""
        <article class="summary-tile {klass}">
          <div class="summary-value">{_safe_text(value)}</div>
          <div class="summary-label">{_safe_text(label)}</div>
          <p>{_safe_text(caption)}</p>
        </article>
        """
        for label, value, caption, klass in tiles
    )


def _metric(case: SiteCase, key: str) -> str:
    value = case.metrics.get(key, "")
    return _format_float(value) if value != "" else ""


def _summary_cards(cases: list[SiteCase]) -> str:
    cards = []
    for case in cases:
        page = f"{_safe_id(case.variant_id)}.html"
        cards.append(
            f"""
            <article class="site-card">
              <div class="site-card-head">
                <h3>{_safe_text(case.label)}</h3>
                <span class="status {_status_class(case.status)}">{_safe_text(case.status or "unknown")}</span>
              </div>
              <dl>
                <div><dt>Temps calcul</dt><dd>{_format_duration(case.duration_seconds)}</dd></div>
                <div><dt>Exutoire X</dt><dd>{_format_float(case.x_outlet)}</dd></div>
                <div><dt>Exutoire Y</dt><dd>{_format_float(case.y_outlet)}</dd></div>
                <div><dt>Cellules</dt><dd>{_metric(case, "n_cells") or "n/a"}</dd></div>
                <div><dt>Erreur bilan max</dt><dd>{_metric(case, "max_abs_balance_error_percent") or "n/a"} %</dd></div>
              </dl>
              <a class="button" href="{_safe_text(page)}">Voir le site</a>
            </article>
            """
        )
    return "\n".join(cards)


def _metrics_table(cases: list[SiteCase]) -> str:
    columns = (
        ("label", "Site"),
        ("status", "Statut"),
        ("duration", "Temps calcul"),
        ("n_cells", "Cellules"),
        ("n_timesteps", "Pas"),
        ("max_abs_balance_error_percent", "Bilan % max"),
        ("head_range_m", "Amplitude charge m"),
        ("budget_recharge_total_in_m3_s", "Recharge in m3/s"),
        ("budget_drains_total_out_m3_s", "Drain out m3/s"),
    )
    rows = []
    for case in cases:
        cells = []
        for key, label in columns:
            if key == "label":
                value = case.label
            elif key == "status":
                value = case.status
            elif key == "duration":
                value = _format_duration(case.duration_seconds)
            else:
                value = _metric(case, key)
            cells.append(f"<td>{_safe_text(value or '')}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    header = "".join(f"<th>{_safe_text(label)}</th>" for _, label in columns)
    body = "\n".join(rows) or f'<tr><td colspan="{len(columns)}">Aucune metrique disponible.</td></tr>'
    return f'<div class="table-wrap"><table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>'


def _diagnostic_value(diag: SiteDiagnostics | None, key: str) -> float | None:
    if diag is None:
        return None
    return getattr(diag, key)


def _format_diag(value: float | None, *, digits: int = 2, scale: float = 1.0, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    return f"{_format_float(value * scale, digits=digits)}{suffix}"


def _site_comparison_table(cases: list[SiteCase], diagnostics: dict[str, SiteDiagnostics]) -> str:
    columns = (
        ("label", "Site"),
        ("area_km2", "Surface km2"),
        ("outlet_elevation_m", "Alt. exutoire m"),
        ("mean_slope_percent", "Pente moy. %"),
        ("q_max_m3_s", "Debit max m3/s"),
        ("q_mean_m3_s", "Debit moyen m3/s"),
        ("q_max_l_s_km2", "Debit max L/s/km2"),
        ("q_mean_l_s_km2", "Debit moyen L/s/km2"),
        ("response_lag_days", "Delai reponse j"),
        ("drained_volume_m3", "Volume draine Mm3"),
        ("balance_error_percent", "Erreur bilan %"),
    )
    rows = []
    for case in cases:
        diag = diagnostics.get(case.variant_id)
        cells = []
        for key, label in columns:
            if key == "label":
                value = case.label
            elif key == "drained_volume_m3":
                value = _format_diag(_diagnostic_value(diag, key), digits=3, scale=1e-6)
            elif key in {"area_km2", "q_max_m3_s", "q_mean_m3_s"}:
                value = _format_diag(_diagnostic_value(diag, key), digits=3)
            elif key in {"outlet_elevation_m", "mean_slope_percent", "q_max_l_s_km2", "q_mean_l_s_km2", "response_lag_days", "balance_error_percent"}:
                value = _format_diag(_diagnostic_value(diag, key), digits=2)
            else:
                value = "n/a"
            cells.append(f"<td>{_safe_text(value)}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    header = "".join(f"<th>{_safe_text(label)}</th>" for _, label in columns)
    body = "\n".join(rows) or f'<tr><td colspan="{len(columns)}">Aucun site disponible.</td></tr>'
    return f'<div class="table-wrap"><table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>'


def _generate_index_scatter_figures(cases: list[SiteCase], diagnostics: dict[str, SiteDiagnostics]) -> None:
    assets = WEB_DIR / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    _render_scatter(
        cases,
        diagnostics,
        output_path=assets / "scatter_surface_vs_qmax.png",
        x_key="area_km2",
        y_key="q_max_m3_s",
        xlabel="Surface du bassin (km2)",
        ylabel="Debit max (m3/s)",
        title="Surface vs debit max",
    )
    _render_scatter(
        cases,
        diagnostics,
        output_path=assets / "scatter_surface_vs_drained_volume.png",
        x_key="area_km2",
        y_key="drained_volume_m3",
        y_scale=1e-6,
        xlabel="Surface du bassin (km2)",
        ylabel="Volume draine (Mm3)",
        title="Surface vs volume draine",
    )
    _render_scatter(
        cases,
        diagnostics,
        output_path=assets / "scatter_slope_vs_lag.png",
        x_key="mean_slope_percent",
        y_key="response_lag_days",
        xlabel="Pente moyenne (%)",
        ylabel="Delai de reponse (jours)",
        title="Pente vs delai de reponse",
    )


def _render_scatter(
    cases: list[SiteCase],
    diagnostics: dict[str, SiteDiagnostics],
    *,
    output_path: Path,
    x_key: str,
    y_key: str,
    xlabel: str,
    ylabel: str,
    title: str,
    y_scale: float = 1.0,
) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        points = []
        for case in cases:
            diag = diagnostics.get(case.variant_id)
            x_value = _diagnostic_value(diag, x_key)
            y_value = _diagnostic_value(diag, y_key)
            if x_value is None or y_value is None:
                continue
            points.append((case, float(x_value), float(y_value) * y_scale))
        if not points:
            return
        fig, ax = plt.subplots(figsize=(6.2, 4.4), dpi=150)
        xs = [item[1] for item in points]
        ys = [item[2] for item in points]
        ax.scatter(xs, ys, s=54, color="#1f6f78", edgecolor="white", linewidth=0.8, zorder=3)
        for case, x_value, y_value in points:
            ax.annotate(_site_short_label(case), (x_value, y_value), xytext=(5, 5), textcoords="offset points", fontsize=8, fontweight="bold")
        ax.set_title(title)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.grid(True, ls=":", lw=0.45, color="#cfd8df")
        fig.tight_layout()
        fig.savefig(output_path)
        plt.close(fig)
    except Exception:
        return


def _preview_gallery(cases: list[SiteCase]) -> str:
    sections = []
    for case in cases:
        figures = "\n".join(_figure_html(case, figure_name, compact=True) for figure_name in INDEX_PREVIEW_FIGURES)
        sections.append(
            f"""
            <section class="site-preview" id="{_safe_id(case.variant_id)}">
              <div class="section-head">
                <h3>{_safe_text(case.label)}</h3>
                <a href="{_safe_text(_safe_id(case.variant_id))}.html">Page detail</a>
              </div>
              <div class="figure-grid preview">{figures}</div>
            </section>
            """
        )
    return "\n".join(sections)


def _checklist_html() -> str:
    items = (
        "Le bassin et l'exutoire sont plausibles sur la carte d'identite.",
        "Les entrees et sorties bassin se regardent en mm/j hors zone tampon.",
        "Le bilan solveur est lu comme diagnostic du domaine complet, pas comme fermeture bassin.",
        "La figure recharge-decharge montre l'amplitude et le delai de reponse.",
        "Les charges ponctuelles evoluent differemment selon leur position.",
        "Le reseau genere reste coherent avec le reseau observe.",
    )
    return "<ul>" + "".join(f"<li>{_safe_text(item)}</li>" for item in items) + "</ul>"


def _site_page(case: SiteCase) -> str:
    figures = "\n".join(_figure_html(case, name) for name, _, _ in FIGURES)
    return _page_shell(
        title=f"{case.label} - flux NWT",
        body=f"""
        <header class="hero compact-hero">
          <nav><a href="index.html">Retour index</a></nav>
          <p class="eyebrow">Testbed MODFLOW-NWT</p>
          <h1>{_safe_text(case.label)}</h1>
          <p>Lecture des flux transitoires et des charges ponctuelles.</p>
        </header>
        <main>
          <section class="panel">
            <h2>Controle rapide</h2>
            <div class="two-col">
              <dl class="facts">
                <div><dt>Variant</dt><dd>{_safe_text(case.variant_id)}</dd></div>
                <div><dt>Statut</dt><dd><span class="status {_status_class(case.status)}">{_safe_text(case.status or "unknown")}</span></dd></div>
                <div><dt>Indicateur</dt><dd>{_safe_text(_status_label(case.status))}</dd></div>
                <div><dt>Temps calcul</dt><dd>{_format_duration(case.duration_seconds)}</dd></div>
                <div><dt>Run</dt><dd>{_safe_text(case.run_name)}</dd></div>
                <div><dt>X outlet</dt><dd>{_format_float(case.x_outlet)}</dd></div>
                <div><dt>Y outlet</dt><dd>{_format_float(case.y_outlet)}</dd></div>
              </dl>
              <div class="checklist"><h3>Ce qu'il faut voir</h3>{_checklist_html()}</div>
            </div>
          </section>
          <section class="panel"><h2>Metriques</h2>{_metrics_table([case])}</section>
          <section class="panel"><h2>Figures</h2><div class="figure-grid">{figures}</div></section>
        </main>
        """,
    )


def _index_page(cases: list[SiteCase], diagnostics: dict[str, SiteDiagnostics]) -> str:
    manifest = _load_json(OUTPUT_ROOT / "testbed_manifest.json")
    return _page_shell(
        title="Testbed flux MODFLOW-NWT",
        body=f"""
        <header class="hero">
          <p class="eyebrow">Testbed regional</p>
          <h1>Flux MODFLOW-NWT par exutoire</h1>
          <p>Lecture cote a cote des sorties de flux et des charges ponctuelles pour huit exutoires.</p>
          <div class="hero-actions">
            <a class="button" href="../testbed_cases.csv">Cas CSV</a>
            <a class="button" href="../testbed_report.md">Rapport testbed</a>
            <a class="button" href="../_generated_configs/">Configs generees</a>
          </div>
        </header>
        <main>
          <section class="panel">
            <div class="section-head"><h2>Etat des simulations</h2><span class="pill">execute = {_safe_text(manifest.get("execute", ""))}</span></div>
            <div class="summary-grid">{_status_summary_html(cases)}</div>
          </section>
          <section class="panel">
            <h2>Localisation regionale</h2>
            {_regional_location_html()}
          </section>
          <section class="panel"><h2>Comparaison inter-sites</h2>{_site_comparison_table(cases, diagnostics)}</section>
          <section class="panel"><h2>Relations inter-sites</h2>{_scatter_gallery_html()}</section>
          <section class="panel">
            <div class="section-head"><h2>Sites</h2></div>
            <div class="site-grid">{_summary_cards(cases)}</div>
          </section>
          <section class="panel"><h2>Ce qui valide le run</h2>{_checklist_html()}</section>
          <section class="panel"><h2>Figures par site</h2>{_preview_gallery(cases)}</section>
        </main>
        """,
    )


def _page_shell(*, title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_safe_text(title)}</title>
  <style>
    :root {{ --ink: #17202a; --muted: #62707f; --line: #d9e0e7; --panel: #fff; --page: #f3f6f8; --accent: #1f6f78; --accent-dark: #14505b; --bad: #9b2c2c; --ok: #247447; --warn: #9b6a1b; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Inter, Segoe UI, Roboto, Arial, sans-serif; color: var(--ink); background: var(--page); line-height: 1.5; }}
    a {{ color: var(--accent-dark); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .hero {{ padding: 42px min(6vw, 72px) 30px; background: #dce9ec; border-bottom: 1px solid var(--line); }}
    .compact-hero {{ padding-bottom: 22px; }}
    .hero h1 {{ margin: 4px 0 10px; max-width: 900px; font-size: 34px; line-height: 1.15; letter-spacing: 0; }}
    .hero p {{ max-width: 920px; margin: 0 0 16px; color: #324653; }}
    .eyebrow {{ margin: 0; text-transform: uppercase; font-size: 12px; font-weight: 700; color: var(--accent-dark); }}
    .hero-actions {{ display: flex; flex-wrap: wrap; gap: 10px; }}
    main {{ padding: 22px min(6vw, 72px) 52px; }}
    .panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 20px; margin: 0 0 18px; }}
    .section-head, .site-card-head {{ display: flex; align-items: start; justify-content: space-between; gap: 12px; }}
    h2, h3 {{ margin: 0 0 12px; letter-spacing: 0; }}
    h2 {{ font-size: 21px; }}
    h3 {{ font-size: 17px; }}
    .summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-top: 14px; }}
    .summary-tile {{ min-height: 104px; border: 1px solid var(--line); border-radius: 6px; padding: 13px; background: #fbfcfd; }}
    .summary-tile.ok {{ border-color: #b9dcc8; background: #f0f8f3; }}
    .summary-tile.bad {{ border-color: #e6b9b9; background: #fff4f4; }}
    .summary-tile.planned {{ border-color: #ead2a6; background: #fff8e8; }}
    .summary-value {{ font-size: 28px; line-height: 1; font-weight: 800; font-variant-numeric: tabular-nums; }}
    .summary-label {{ margin-top: 8px; font-weight: 700; }}
    .summary-tile p {{ margin: 3px 0 0; color: var(--muted); font-size: 13px; }}
    .site-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; }}
    .site-card {{ border: 1px solid var(--line); border-radius: 6px; padding: 14px; background: #fbfcfd; }}
    dl {{ margin: 0; }}
    dl div {{ display: flex; justify-content: space-between; gap: 12px; border-bottom: 1px solid #edf1f4; padding: 6px 0; }}
    dt {{ color: var(--muted); }}
    dd {{ margin: 0; text-align: right; font-variant-numeric: tabular-nums; }}
    .button {{ display: inline-flex; align-items: center; min-height: 34px; padding: 7px 11px; margin-top: 12px; border-radius: 4px; border: 1px solid var(--accent); color: white; background: var(--accent); font-weight: 600; }}
    .button:hover {{ background: var(--accent-dark); text-decoration: none; }}
    .status, .pill {{ display: inline-flex; align-items: center; min-height: 24px; padding: 3px 8px; border-radius: 999px; font-size: 12px; font-weight: 700; background: #edf2f5; color: #40505c; white-space: nowrap; }}
    .status.ok {{ color: var(--ok); background: #e8f4ed; }}
    .status.bad {{ color: var(--bad); background: #faeaea; }}
    .status.planned {{ color: var(--warn); background: #fff3dc; }}
    .two-col {{ display: grid; grid-template-columns: minmax(280px, 1fr) minmax(280px, 1fr); gap: 20px; }}
    .checklist ul, .panel ul {{ margin: 0; padding-left: 20px; }}
    .table-wrap {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 6px; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 760px; background: white; }}
    th, td {{ padding: 9px 10px; border-bottom: 1px solid #edf1f4; text-align: left; vertical-align: top; font-size: 13px; }}
    th {{ background: #f7f9fa; color: #364854; }}
    .figure-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 14px; }}
    .figure-grid.preview {{ grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }}
    .figure-card {{ margin: 0; border: 1px solid var(--line); border-radius: 6px; overflow: hidden; background: #fbfcfd; }}
    .figure-card img {{ display: block; width: 100%; height: 260px; object-fit: contain; background: white; border-bottom: 1px solid var(--line); }}
    .figure-card.wide img {{ height: min(62vh, 560px); }}
    .figure-card.compact img {{ height: 190px; }}
    figcaption {{ display: grid; gap: 2px; padding: 9px 10px; color: var(--muted); font-size: 13px; }}
    figcaption strong {{ color: var(--ink); }}
    .missing {{ min-height: 260px; display: grid; place-items: center; color: var(--muted); background: #eef3f5; border-bottom: 1px solid var(--line); font-weight: 700; }}
    .compact .missing {{ min-height: 190px; }}
    .site-preview {{ margin-bottom: 18px; }}
    nav {{ margin-bottom: 14px; }}
    @media (max-width: 760px) {{ .hero {{ padding: 28px 18px 22px; }} .hero h1 {{ font-size: 27px; }} main {{ padding: 18px; }} .two-col {{ grid-template-columns: 1fr; }} .section-head {{ flex-direction: column; }} .figure-card img, .missing {{ height: auto; min-height: 190px; }} }}
  </style>
</head>
<body>
{body}
</body>
</html>
"""


def build() -> list[Path]:
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    for stale_page in WEB_DIR.glob("*.html"):
        stale_page.unlink()
    cases = _load_cases()
    diagnostics = _compute_site_diagnostics(cases)
    _generate_diagnostic_figures(cases)
    _generate_regional_location_map(cases)
    _generate_index_scatter_figures(cases, diagnostics)
    written: list[Path] = []
    index_path = WEB_DIR / "index.html"
    index_path.write_text(_index_page(cases, diagnostics), encoding="utf-8")
    written.append(index_path)
    for case in cases:
        path = WEB_DIR / f"{_safe_id(case.variant_id)}.html"
        path.write_text(_site_page(case), encoding="utf-8")
        written.append(path)
    return written


def main() -> None:
    written = build()
    print("Generated NWT flux testbed web report:")
    for path in written:
        print(f"  {path}")


if __name__ == "__main__":
    main()
