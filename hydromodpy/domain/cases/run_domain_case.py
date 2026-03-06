"""Domain case runner from a single HydroModPy TOML configuration.

This module exposes:
- ``run_domain_case_from_toml`` to build ``Workspace``, geographic context, and ``Domain``.
- ``plot_domain_summary`` to export a quick validation PNG (top, bottom, thickness,
  and optional geology classes).
- a CLI entrypoint (``main``) for local runs and smoke checks.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MaxNLocator, ScalarFormatter
import numpy as np

# Support direct execution from file path and ensure local package precedence.
# Example: python hydromodpy/domain/cases/run_domain_case.py
repo_root = Path(__file__).resolve().parents[3]
if (repo_root / "hydromodpy").exists() and str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.domain import Domain
from hydromodpy.geographic_v2.domain_geographic_pipeline import (
    DomainGeographicContext,
    build_domain_geographic_context,
)
from hydromodpy.simulation.workspace import Workspace


def run_domain_case_from_toml(
    config_toml: str | Path,
    *,
    build_geology: bool = True,
):
    """Build the domain stack from one global TOML file.

    Parameters
    ----------
    config_toml:
        Path to the HydroModPy configuration file.
    build_geology:
        If ``True``, attempt to build and attach the ``geology`` zone when it is
        declared in ``domain.zone_ids``.

    Returns
    -------
    tuple
        ``(workspace, geographic_context, domain, summary)`` where ``summary`` is a compact
        dictionary intended for logging and quick checks.
    """
    # 1) Load validated config and initialize workspace/geographic context.
    cfg = HydroModPyConfig.from_toml(config_toml)
    workspace = Workspace(config=cfg.workspace)
    geographic_context = build_domain_geographic_context(
        config=cfg.geographic,
        workspace=workspace,
    )

    # 2) Build the domain from prepared topography support.
    surface_topo = geographic_context.surface_topo
    domain = Domain(
        config=cfg.domain,
        surface_topo=surface_topo,
    )

    # 3) Optionally attach the geology zone if requested and configured.
    geology_loaded = False
    geology_reason: str | None = None
    if build_geology and "geology" in cfg.domain.zone_ids:
        if cfg.data.geology is None:
            geology_reason = (
                "geology requested in domain.zone_ids but [data.geology] is missing"
            )
        else:
            from hydromodpy.data_managers.geology.geology_field import GeologyField

            geology = GeologyField.from_watershed_config(
                cfg.data.geology,
                raster_support=surface_topo.support,
            )
            domain.set_zone("geology", geology)
            geology_loaded = True

    # 4) Return a small summary payload used by CLI logs/tests.
    summary = {
        "catch_folder": str(workspace.catch_folder),
        "watershed_shp": str(geographic_context.watershed_shp),
        "catchment_area_km2": float(geographic_context.catchment_area_km2),
        "surface_topo_shape": tuple(int(v) for v in domain.surface_topo.as_array().shape),
        "substratum_shape": tuple(int(v) for v in domain.substratum.as_array().shape),
        "depth_model_type": str(domain.config.depth_model.type),
        "geology_loaded": bool(geology_loaded),
        "geology_reason": geology_reason,
    }
    return workspace, geographic_context, domain, summary


def _surface_extent(surface) -> tuple[float, float, float, float] | None:
    """Return raster extent (xmin, xmax, ymin, ymax) when support is available."""
    support = getattr(surface, "support", None)
    if support is None:
        return None
    if (
        support.xmin is None
        or support.xmax is None
        or support.ymin is None
        or support.ymax is None
    ):
        return None
    return (
        float(support.xmin),
        float(support.xmax),
        float(support.ymin),
        float(support.ymax),
    )


def _mask_nodata(values: np.ndarray, *, nodata: float | None) -> np.ndarray:
    """Convert values to float and replace nodata/non-finite cells by NaN."""
    arr = np.asarray(values, dtype=float)
    mask = np.isfinite(arr)
    if nodata is not None:
        mask &= arr != float(nodata)
    return np.where(mask, arr, np.nan)


def _format_axes(
    ax,
    *,
    show_xlabel: bool = True,
    show_ylabel: bool = True,
    extent: tuple[float, float, float, float] | None = None,
    km_origin: tuple[float, float] | None = None,
) -> None:
    """Apply consistent axis formatting across all summary subplots."""
    ax.tick_params(labelsize=6)
    if extent is not None:
        xmin, xmax, ymin, ymax = extent
        # Keep ticks light and force bounds ticks so lower-left starts at 0 km after formatting.
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)
        ax.set_xticks(np.linspace(xmin, xmax, 4))
        ax.set_yticks(np.linspace(ymin, ymax, 4))
    else:
        ax.xaxis.set_major_locator(MaxNLocator(nbins=4))
        ax.yaxis.set_major_locator(MaxNLocator(nbins=4))

    if km_origin is not None:
        x0, y0 = km_origin
        ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _pos: f"{(value - x0) / 1000.0:.1f}"))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: f"{(value - y0) / 1000.0:.1f}"))
        ax.set_xlabel("x (km)" if show_xlabel else "", fontsize=7)
        ax.set_ylabel("y (km)" if show_ylabel else "", fontsize=7)
    else:
        ax.ticklabel_format(style="plain", useOffset=False, axis="both")
        ax.xaxis.set_major_formatter(ScalarFormatter(useOffset=False))
        ax.yaxis.set_major_formatter(ScalarFormatter(useOffset=False))
        ax.set_xlabel("x" if show_xlabel else "", fontsize=7)
        ax.set_ylabel("y" if show_ylabel else "", fontsize=7)


def plot_domain_summary(
    domain: Domain,
    output_dir: Path,
    *,
    geographic: DomainGeographicContext | None = None,
    case_id: str = "base",
    show_plot: bool = True,
) -> Path:
    """Save a quick domain validation figure and return its path.

    The figure always includes:
    - surface topography
    - substratum
    - thickness (top - bottom)

    A fourth subplot is added when a geology zone with ``encoded_codes`` is present.
    When ``geographic`` is provided, the watershed boundary is overlaid on maps.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    fig_path = output_dir / f"{case_id}_domain_summary.png"

    nodata = None
    support = domain.surface_topo.support
    if support is not None:
        nodata = support.nodata

    top = _mask_nodata(domain.surface_topo.as_array(), nodata=nodata)
    bot = _mask_nodata(domain.substratum.as_array(), nodata=nodata)
    thick = top - bot
    extent = _surface_extent(domain.surface_topo)
    km_origin = (extent[0], extent[2]) if extent is not None else None

    # Add geology panel only when encoded class ids are available.
    geology = domain.zones.get("geology")
    has_geology = geology is not None and hasattr(geology, "encoded_codes")

    # Use a 2x2 grid to keep the summary readable on standard screens.
    fig, axes = plt.subplots(2, 2, figsize=(7.2, 5.6), dpi=110)
    ax_top = axes[0, 0]
    ax_bot = axes[0, 1]
    ax_thk = axes[1, 0]
    ax_geo = axes[1, 1]

    im_top = ax_top.imshow(top, cmap="terrain", origin="upper", extent=extent)
    ax_top.set_title("surface_topo", fontsize=8)
    _format_axes(
        ax_top,
        show_xlabel=False,
        show_ylabel=True,
        extent=extent,
        km_origin=km_origin,
    )
    cbar_top = plt.colorbar(im_top, ax=ax_top, fraction=0.046, pad=0.03)
    cbar_top.ax.tick_params(labelsize=7)
    cbar_top.set_label("m", fontsize=8)

    im_bot = ax_bot.imshow(bot, cmap="terrain", origin="upper", extent=extent)
    ax_bot.set_title("substratum", fontsize=8)
    _format_axes(
        ax_bot,
        show_xlabel=False,
        show_ylabel=False,
        extent=extent,
        km_origin=km_origin,
    )
    cbar_bot = plt.colorbar(im_bot, ax=ax_bot, fraction=0.046, pad=0.03)
    cbar_bot.ax.tick_params(labelsize=7)
    cbar_bot.set_label("m", fontsize=8)

    im_thk = ax_thk.imshow(thick, cmap="viridis", origin="upper", extent=extent)
    ax_thk.set_title("thickness (top - bottom)", fontsize=8)
    _format_axes(
        ax_thk,
        show_xlabel=True,
        show_ylabel=True,
        extent=extent,
        km_origin=km_origin,
    )
    cbar_thk = plt.colorbar(im_thk, ax=ax_thk, fraction=0.046, pad=0.03)
    cbar_thk.ax.tick_params(labelsize=7)
    cbar_thk.set_label("m", fontsize=8)

    if has_geology:
        geology_codes = np.asarray(geology.encoded_codes, dtype=float)
        geology_codes = np.where(geology_codes > 0, geology_codes, np.nan)
        im_geo = ax_geo.imshow(
            geology_codes,
            cmap="tab20",
            origin="upper",
            extent=extent,
            interpolation="nearest",
        )
        ax_geo.set_title("geology (encoded classes)", fontsize=8)
        _format_axes(
            ax_geo,
            show_xlabel=True,
            show_ylabel=False,
            extent=extent,
            km_origin=km_origin,
        )
        cbar_geo = plt.colorbar(im_geo, ax=ax_geo, fraction=0.046, pad=0.03)
        cbar_geo.ax.tick_params(labelsize=7)
        cbar_geo.set_label("code", fontsize=8)
    else:
        ax_geo.axis("off")
        ax_geo.text(
            0.5,
            0.5,
            "No geology zone",
            ha="center",
            va="center",
            fontsize=8,
            transform=ax_geo.transAxes,
        )

    # Optional watershed boundary overlay from geographic outputs.
    if geographic is not None:
        watershed_shp = Path(str(getattr(geographic, "watershed_shp", "")))
        if watershed_shp.exists():
            try:
                import geopandas as gpd

                boundary = gpd.read_file(watershed_shp).boundary
                overlay_axes = [ax_top, ax_bot, ax_thk]
                if has_geology:
                    overlay_axes.append(ax_geo)
                for axis in overlay_axes:
                    boundary.plot(ax=axis, color="black", linewidth=0.8, alpha=0.9)

                # Make the outlet clearly visible on all displayed map panels.
                x_outlet = getattr(geographic, "x_outlet", None)
                y_outlet = getattr(geographic, "y_outlet", None)
                if x_outlet is not None and y_outlet is not None:
                    for axis in overlay_axes:
                        axis.plot(
                            float(x_outlet),
                            float(y_outlet),
                            marker="o",
                            markersize=8,
                            markerfacecolor="red",
                            markeredgecolor="white",
                            markeredgewidth=1.2,
                            zorder=8,
                        )
            except Exception:
                # Keep plotting robust even if shapefile loading fails.
                pass

    finite_top = np.isfinite(top)
    finite_bot = np.isfinite(bot)
    finite_thick = np.isfinite(thick)
    top_mean = float(np.nanmean(top[finite_top])) if np.any(finite_top) else float("nan")
    bot_mean = float(np.nanmean(bot[finite_bot])) if np.any(finite_bot) else float("nan")
    thick_mean = (
        float(np.nanmean(thick[finite_thick])) if np.any(finite_thick) else float("nan")
    )
    fig.suptitle(
        f"Domain summary | top_mean={top_mean:.2f} m | "
        f"bottom_mean={bot_mean:.2f} m | thick_mean={thick_mean:.2f} m",
        fontsize=9,
    )

    fig.tight_layout(pad=0.35)
    fig.subplots_adjust(top=0.90)
    fig.savefig(fig_path, bbox_inches="tight", pad_inches=0.03)
    # ``show_plot`` is useful for interactive runs; tests can disable it.
    if show_plot:
        plt.show(block=True)
    else:
        plt.close(fig)
    return fig_path


def _build_parser() -> argparse.ArgumentParser:
    """Build CLI parser for the standalone domain-case runner."""
    parser = argparse.ArgumentParser(
        description=(
            "Run a domain-only pipeline from TOML and save one validation figure "
            "(topography, substratum, thickness, optional geology)."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("run_domain_config.toml"),
        help="Path to a HydroModPy TOML file.",
    )
    parser.add_argument(
        "--case-id",
        type=str,
        default="base",
        help="Case label used for output figure naming.",
    )
    parser.add_argument(
        "--no-build-geology",
        action="store_true",
        help="Skip optional geology zone build even if declared in domain.zone_ids.",
    )
    parser.add_argument(
        "--no-show-plot",
        action="store_true",
        help="Do not display figure interactively (still saves PNG file).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint used by ``python .../run_domain_case.py``."""
    args = _build_parser().parse_args(argv)
    # Core pipeline: config -> workspace/geographic/domain (+ optional geology).
    workspace, geographic_context, domain, summary = run_domain_case_from_toml(
        args.config,
        build_geology=(not bool(args.no_build_geology)),
    )

    # Save one compact visual QA artifact in ``cases/outputs``.
    fig_path = plot_domain_summary(
        domain,
        output_dir=Path(__file__).resolve().parent / "outputs",
        geographic=geographic_context,
        case_id=str(args.case_id),
        show_plot=(not bool(args.no_show_plot)),
    )

    # Print concise key/value diagnostics for quick inspection and CI logs.
    print(f"[{args.case_id}] catch_folder={workspace.catch_folder}")
    print(f"[{args.case_id}] watershed_shp={summary['watershed_shp']}")
    print(f"[{args.case_id}] catchment_area_km2={summary['catchment_area_km2']:.3f}")
    print(
        f"[{args.case_id}] surface_topo_shape="
        f"{summary['surface_topo_shape'][0]}x{summary['surface_topo_shape'][1]}"
    )
    print(
        f"[{args.case_id}] substratum_shape="
        f"{summary['substratum_shape'][0]}x{summary['substratum_shape'][1]}"
    )
    print(f"[{args.case_id}] depth_model_type={summary['depth_model_type']}")
    print(f"[{args.case_id}] geology_loaded={summary['geology_loaded']}")
    if summary["geology_reason"] is not None:
        print(f"[{args.case_id}] geology_note={summary['geology_reason']}")
    print(f"[{args.case_id}] figure={fig_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
