"""Matplotlib figure builders for the compact network synthesis page."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from .io import (
    CompactNetworkSynthesisConfig,
    SimulationRecord,
    _parse_float,
    _row_value,
    read_toml_mapping,
)


def field_stack(run, variable: str):
    import numpy as np

    n_timesteps = int(run.n_timesteps or 1)
    return np.stack(
        [
            np.asarray(run.field(variable, timestep=t), dtype="float64").reshape(-1)
            for t in range(n_timesteps)
        ]
    )


def mean_positive_flux(run, variable: str):
    import numpy as np

    stack = field_stack(run, variable)
    positive = np.where(np.isfinite(stack) & (stack > 0.0), stack, np.nan)
    with np.errstate(invalid="ignore"):
        return np.nanmean(positive, axis=0)


def log10_positive(values):
    import numpy as np

    values = np.asarray(values, dtype="float64").reshape(-1)
    out = np.full(values.shape, np.nan, dtype="float64")
    mask = np.isfinite(values) & (values > 0.0)
    out[mask] = np.log10(values[mask])
    return out


def context_watershed_gdf(
    path: Path | None,
    cache_ref: dict[str, object],
):
    if "value" in cache_ref:
        return cache_ref["value"]

    if path is None:
        cache_ref["value"] = None
        return None
    path = Path(path)
    if not path.exists():
        cache_ref["value"] = None
        return None

    try:
        import geopandas as gpd

        gdf = gpd.read_file(path)
    except Exception:
        gdf = None
    cache_ref["value"] = gdf
    return gdf


def context_dem_path(watershed_path: Path | None) -> Path | None:
    if watershed_path is None:
        return None
    watershed_path = Path(watershed_path)
    candidates = (
        watershed_path.parent / "watershed_box_buff_dem.tif",
        watershed_path.parent / "context_dem.tif",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def run_topography(run):
    import numpy as np

    dem = np.asarray(run.dem, dtype="float64")
    dem = np.where(np.isfinite(dem), dem, np.nan)
    grid = run.grid
    extent = (
        float(grid.extent[0]),
        float(grid.extent[1]),
        float(grid.extent[2]),
        float(grid.extent[3]),
    )
    return dem, extent


def context_topography_layers(run, watershed_path: Path | None):
    import numpy as np

    layers = [run_topography(run)]
    dem_path = context_dem_path(watershed_path)
    if dem_path is not None:
        try:
            import rasterio

            with rasterio.open(dem_path) as src:
                data = src.read(1, masked=True).astype("float64")
                dem = data.filled(np.nan)
                bounds = src.bounds
                extent = (
                    float(bounds.left),
                    float(bounds.right),
                    float(bounds.bottom),
                    float(bounds.top),
                )
            layers.append((dem, extent))
        except Exception:
            pass

    return [(np.where(np.isfinite(dem), dem, np.nan), extent) for dem, extent in layers]


def project_for_plot(gdf, fallback_crs=None):
    if gdf is None or gdf.empty:
        return gdf
    from hydromodpy.display.figures.hydrographic_network import (
        _project_gdf_for_metric_operations,
    )

    return _project_gdf_for_metric_operations(gdf, fallback_crs=fallback_crs)


def run_watershed_gdf(run):
    try:
        return run.geographic("watershed")
    except Exception:
        return None


def plot_watershed_context(
    ax,
    run,
    *,
    config_watershed_path: Path | None,
    watershed_cache: dict[str, object],
) -> str:
    from hydromodpy.display.map_axes import overlay_watershed_contour

    context_watershed = context_watershed_gdf(config_watershed_path, watershed_cache)
    if context_watershed is not None and not context_watershed.empty:
        fallback = run_watershed_gdf(run)
        fallback_crs = None if fallback is None or fallback.empty else fallback.crs
        context_watershed = project_for_plot(
            context_watershed,
            fallback_crs=fallback_crs,
        )
        if context_watershed is not None and not context_watershed.empty:
            context_watershed.boundary.plot(
                ax=ax,
                color="#111827",
                linewidth=1.35,
                alpha=0.95,
                zorder=7,
            )
            return "external"

    try:
        overlay_watershed_contour(ax, run, color="#111827", linewidth=1.15, alpha=0.9)
    except Exception:
        return "none"
    return "support"


def overlay_reference(
    ax,
    run,
    *,
    reference_gdf,
    config_watershed_path: Path | None,
    watershed_cache: dict[str, object],
) -> None:
    from matplotlib.lines import Line2D

    has_reference = False
    try:
        reference = run.hydrographic_network("reference")
    except Exception:
        reference = reference_gdf
    if reference is not None and not reference.empty:
        watershed = run_watershed_gdf(run)
        fallback_crs = None if watershed is None or watershed.empty else watershed.crs
        reference = project_for_plot(reference, fallback_crs=fallback_crs)
        reference.plot(ax=ax, color="#9b1c1c", linewidth=1.25, alpha=0.98, zorder=6)
        has_reference = True
    watershed_context = plot_watershed_context(
        ax,
        run,
        config_watershed_path=config_watershed_path,
        watershed_cache=watershed_cache,
    )
    if has_reference or watershed_context != "none":
        handles = []
        if has_reference:
            handles.append(Line2D([0], [0], color="#9b1c1c", lw=1.6, label="reseau observe"))
        if watershed_context == "external":
            handles.append(Line2D([0], [0], color="#111827", lw=1.4, label="limite bassin versant"))
        elif watershed_context == "support":
            handles.append(Line2D([0], [0], color="#111827", lw=1.4, label="limite bassin versant"))
        ax.legend(
            handles=handles,
            loc="upper right",
            frameon=True,
            framealpha=0.9,
            fontsize=8,
        )


def remove_map_frame(ax) -> None:
    """Keep map coordinates, but avoid a second visual frame inside the HTML card."""
    for spine in ax.spines.values():
        spine.set_visible(False)


def render_log_flux_figure(
    run,
    *,
    variable: str,
    title: str,
    save_path: Path,
    reference_gdf,
    config_watershed_path: Path | None,
    watershed_cache: dict[str, object],
) -> None:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.ticker import FormatStrFormatter, MaxNLocator

    from hydromodpy.display.map_axes import style_map_axes
    from hydromodpy.display.ugrid import render_face_field

    values = log10_positive(mean_positive_flux(run, variable))
    finite = values[np.isfinite(values)]
    if finite.size:
        vmin = float(np.nanpercentile(finite, 5.0))
        vmax = float(np.nanpercentile(finite, 95.0))
        if not np.isfinite(vmin) or not np.isfinite(vmax) or vmin >= vmax:
            vmin = float(np.nanmin(finite))
            vmax = float(np.nanmax(finite))
    else:
        vmin, vmax = -12.0, 0.0

    fig, ax = plt.subplots(figsize=(7.8, 5.8), dpi=180, constrained_layout=True)
    collection = render_face_field(
        ax,
        run,
        values,
        cmap="viridis",
        vmin=vmin,
        vmax=vmax,
        cbar_label="log10(flux moyen positif)",
    )
    ticks = np.linspace(float(vmin), float(vmax), 5)
    tick_labels = [f"{tick:.1f}" for tick in ticks]
    colorbar = getattr(collection, "colorbar", None)
    if colorbar is not None:
        colorbar.set_ticks(ticks)
        colorbar.set_ticklabels(tick_labels)
    elif len(fig.axes) > 1:
        fig.axes[-1].yaxis.set_major_locator(MaxNLocator(nbins=5))
        fig.axes[-1].yaxis.set_major_formatter(FormatStrFormatter("%.1f"))
    overlay_reference(
        ax,
        run,
        reference_gdf=reference_gdf,
        config_watershed_path=config_watershed_path,
        watershed_cache=watershed_cache,
    )
    style_map_axes(ax)
    remove_map_frame(ax)
    ax.set_title(title)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def load_recharge_config(
    path: Path,
    seen: set[Path] | None = None,
) -> dict[str, object]:
    seen = seen or set()
    path = path.resolve()
    if path in seen:
        return {}
    seen.add(path)
    config = read_toml_mapping(path)
    data = config.get("data", {})
    if isinstance(data, dict):
        recharge = data.get("recharge", {})
        if isinstance(recharge, dict) and recharge.get("sources"):
            return config

    nested: list[str] = []
    comparison = config.get("comparison", {})
    if isinstance(comparison, dict) and isinstance(comparison.get("base_simulation_config"), str):
        nested.append(str(comparison["base_simulation_config"]))
    if isinstance(config.get("base_config"), str):
        nested.append(str(config["base_config"]))
    for raw_path in nested:
        child = (path.parent / raw_path).resolve()
        found = load_recharge_config(child, seen)
        if found:
            return found
    return {}


def first_recharge_source(base_config: Path | None) -> dict[str, object]:
    if base_config is None:
        return {}
    config = load_recharge_config(Path(base_config))
    data = config.get("data", {})
    if not isinstance(data, dict):
        return {}
    recharge = data.get("recharge", {})
    if not isinstance(recharge, dict):
        return {}
    sources = recharge.get("sources", [])
    if not isinstance(sources, list) or not sources:
        return {}
    source = sources[0]
    return source if isinstance(source, dict) else {}


def recharge_values_from_config(base_config: Path | None) -> list[float]:
    source = first_recharge_source(base_config)
    values = source.get("values", [])
    if not isinstance(values, list):
        values = [values] if values not in ("", None) else []
    parsed: list[float] = []
    for value in values:
        try:
            parsed.append(float(value))
        except (TypeError, ValueError):
            continue
    return parsed


def add_months(start: date, months: int) -> date:
    month_index = start.month - 1 + int(months)
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def recharge_month_labels(base_config: Path | None, n_values: int) -> list[str]:
    source = first_recharge_source(base_config)
    raw_start = source.get("start_date") or "2000-01-01"
    if isinstance(raw_start, date):
        start = raw_start
    else:
        start = date.fromisoformat(str(raw_start)[:10])
    return [
        f"{add_months(start, index):%b} {add_months(start, index).year}"
        for index in range(n_values)
    ]


def recharge_summary_text(base_config: Path | None) -> str:
    values = recharge_values_from_config(base_config)
    if not values:
        return "chronique de recharge non trouvee"
    return (
        f"{len(values)} mois; moyenne {sum(values) / len(values):.2f} mm/j; "
        f"min {min(values):.2f}; max {max(values):.2f}"
    )


def generate_recharge_figure(base_config: Path | None, save_path: Path) -> bool:
    values = recharge_values_from_config(base_config)
    if not values:
        return False

    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    labels = recharge_month_labels(base_config, len(values))
    mean_value = sum(values) / len(values)
    fig, ax = plt.subplots(figsize=(6.6, 1.9), dpi=180, constrained_layout=True)
    x_values = list(range(len(values)))
    ax.bar(x_values, values, color="#4c78a8", width=0.72)
    ax.axhline(mean_value, color="#b23a48", linewidth=1.2, linestyle="--", label="moyenne")
    ax.set_title("Recharge mensuelle imposee", fontsize=10)
    ax.set_ylabel("mm/j")
    ax.set_xticks(x_values)
    ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=7)
    ax.grid(axis="y", color="#d8dee6", linewidth=0.7, alpha=0.8)
    ax.legend(loc="upper right", frameon=False, fontsize=8)
    ax.tick_params(axis="y", labelsize=8)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return True


def render_topographic_context_figure(
    run,
    save_path: Path,
    *,
    config_watershed_path: Path | None,
    watershed_cache: dict[str, object],
    reference_provider: Callable[[Any], object],
) -> None:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.lines import Line2D

    from hydromodpy.display.map_axes import style_map_axes

    layers = context_topography_layers(run, config_watershed_path)
    finite_values = [dem[np.isfinite(dem)] for dem, _extent in layers if dem[np.isfinite(dem)].size]
    finite = np.concatenate(finite_values) if finite_values else np.asarray([])
    if finite.size:
        vmin = float(np.nanpercentile(finite, 2.0))
        vmax = float(np.nanpercentile(finite, 98.0))
    else:
        vmin, vmax = 0.0, 1.0

    fig, ax = plt.subplots(figsize=(8.2, 6.1), dpi=180, constrained_layout=True)
    image = None
    for index, (dem, extent) in enumerate(layers):
        image = ax.imshow(
            dem,
            extent=extent,
            origin="upper",
            cmap="terrain",
            vmin=vmin,
            vmax=vmax,
            zorder=1 + index,
        )
    if image is None:
        return
    colorbar = fig.colorbar(image, ax=ax, fraction=0.042, pad=0.015)
    colorbar.set_label("altitude (m)")
    colorbar.ax.tick_params(labelsize=8)

    reference = reference_provider(run)
    has_reference = False
    if reference is not None and not reference.empty:
        watershed = run_watershed_gdf(run)
        fallback_crs = None if watershed is None or watershed.empty else watershed.crs
        reference = project_for_plot(reference, fallback_crs=fallback_crs)
        reference.plot(ax=ax, color="#9b1c1c", linewidth=1.25, alpha=0.98, zorder=6)
        has_reference = True

    watershed_context = plot_watershed_context(
        ax,
        run,
        config_watershed_path=config_watershed_path,
        watershed_cache=watershed_cache,
    )
    handles = []
    if has_reference:
        handles.append(Line2D([0], [0], color="#9b1c1c", lw=1.6, label="reseau observe"))
    if watershed_context == "external":
        handles.append(Line2D([0], [0], color="#111827", lw=1.4, label="limite bassin versant"))
    elif watershed_context == "support":
        handles.append(Line2D([0], [0], color="#111827", lw=1.4, label="limite bassin versant"))
    if handles:
        ax.legend(handles=handles, loc="upper right", frameon=True, framealpha=0.92, fontsize=8)
    style_map_axes(ax)
    remove_map_frame(ax)
    ax.set_title("Contexte topographique")
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def short_configuration_label(record: SimulationRecord) -> str:
    return record.meta.short_label or record.meta.label


def generate_metric_synthesis_figure(
    records: list[SimulationRecord],
    save_path: Path,
    *,
    routed_distance_for: Callable[[SimulationRecord], dict[str, str] | None],
) -> bool:
    items: list[tuple[str, float | None, float | None, float | None, float | None]] = []
    for record in records:
        release = record.release_distance
        routed = routed_distance_for(record)
        release_distance = _parse_float(_row_value(release, "bidirectional_distance_mean_m"))
        routed_distance_mean = _parse_float(_row_value(routed, "bidirectional_distance_mean_m"))
        release_ratio = _parse_float(_row_value(release, "planar_distance_ratio"))
        routed_ratio = _parse_float(_row_value(routed, "planar_distance_ratio"))
        if any(
            value is not None
            for value in (release_distance, routed_distance_mean, release_ratio, routed_ratio)
        ):
            items.append(
                (
                    short_configuration_label(record),
                    release_distance,
                    routed_distance_mean,
                    release_ratio,
                    routed_ratio,
                )
            )
    if not items:
        return False

    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    import numpy as np

    labels = [item[0] for item in items]
    y_values = np.arange(len(items), dtype=float)
    release_distances = [item[1] for item in items]
    routed_distances = [item[2] for item in items]
    release_ratios = [item[3] for item in items]
    routed_ratios = [item[4] for item in items]

    fig, axes = plt.subplots(
        1,
        2,
        figsize=(9.4, 3.8),
        dpi=180,
        sharey=True,
        constrained_layout=True,
    )
    styles = (
        ("Emergences avant routage", "#4c78a8", "o"),
        ("Emergences accumulees vers l'aval", "#f58518", "s"),
    )
    for ax, title, xlabel, first, second in (
        (axes[0], "Distance moyenne symetrique", "m", release_distances, routed_distances),
        (
            axes[1],
            "Ratio des distances",
            "calc -> obs / obs -> calc",
            release_ratios,
            routed_ratios,
        ),
    ):
        for values, (method_label, color, marker), offset in (
            (first, styles[0], -0.12),
            (second, styles[1], 0.12),
        ):
            xs = [float(value) if value is not None else np.nan for value in values]
            ax.scatter(xs, y_values + offset, label=method_label, color=color, marker=marker, s=34)
            for x_value, y_value in zip(xs, y_values + offset, strict=True):
                if np.isfinite(x_value):
                    label = f" {x_value:.0f}" if xlabel == "m" else f" {x_value:.2f}"
                    ax.text(x_value, y_value, label, va="center", fontsize=7)
        ax.set_title(title, fontsize=10)
        ax.set_xlabel(xlabel)
        ax.grid(axis="x", color="#d8dee6", linewidth=0.7, alpha=0.8)
        ax.tick_params(labelsize=8)
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
    axes[0].set_yticks(y_values)
    axes[0].set_yticklabels(labels, fontsize=8)
    axes[0].invert_yaxis()
    axes[1].axvline(1.0, color="#808b96", linewidth=1.0, linestyle="--")
    axes[0].legend(loc="lower right", frameon=False, fontsize=8)

    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return True


__all__ = [
    "CompactNetworkSynthesisConfig",
    "field_stack",
    "log10_positive",
    "mean_positive_flux",
    "context_watershed_gdf",
    "context_dem_path",
    "run_topography",
    "context_topography_layers",
    "project_for_plot",
    "run_watershed_gdf",
    "plot_watershed_context",
    "overlay_reference",
    "remove_map_frame",
    "render_log_flux_figure",
    "load_recharge_config",
    "first_recharge_source",
    "recharge_values_from_config",
    "add_months",
    "recharge_month_labels",
    "recharge_summary_text",
    "generate_recharge_figure",
    "render_topographic_context_figure",
    "short_configuration_label",
    "generate_metric_synthesis_figure",
]
