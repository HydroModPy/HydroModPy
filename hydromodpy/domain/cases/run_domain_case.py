"""Run a domain-only case from a TOML configuration."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import matplotlib.pyplot as plt
from matplotlib.ticker import ScalarFormatter
import numpy as np

# Support direct execution from file path and ensure local package precedence.
# Example: python hydromodpy/domain/cases/run_domain_case.py
repo_root = Path(__file__).resolve().parents[3]
if (repo_root / "hydromodpy").exists() and str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.domain import Domain
from hydromodpy.geographic.geographic import Geographic
from hydromodpy.watershed.workspace import Workspace


def run_domain_case_from_toml(
    config_toml: str | Path,
    *,
    build_geology: bool = True,
):
    """Build Workspace + Geographic + Domain from one global TOML file."""
    cfg = HydroModPyConfig.from_toml(config_toml)
    workspace = Workspace(config=cfg.workspace)
    geographic = Geographic(config=cfg.geographic, initializing=workspace)

    surface_topo = geographic.get_domain_surface_topo()
    domain = Domain(
        config=cfg.domain,
        surface_topo=surface_topo,
    )

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

    summary = {
        "catch_folder": str(workspace.catch_folder),
        "surface_topo_shape": tuple(int(v) for v in domain.surface_topo.as_array().shape),
        "substratum_shape": tuple(int(v) for v in domain.substratum.as_array().shape),
        "depth_model_type": str(domain.config.depth_model.type),
        "geology_loaded": bool(geology_loaded),
        "geology_reason": geology_reason,
    }
    return workspace, geographic, domain, summary


def _surface_extent(surface) -> tuple[float, float, float, float] | None:
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
    arr = np.asarray(values, dtype=float)
    mask = np.isfinite(arr)
    if nodata is not None:
        mask &= arr != float(nodata)
    return np.where(mask, arr, np.nan)


def _format_axes(ax) -> None:
    ax.tick_params(labelsize=7)
    ax.ticklabel_format(style="plain", useOffset=False, axis="both")
    ax.xaxis.set_major_formatter(ScalarFormatter(useOffset=False))
    ax.yaxis.set_major_formatter(ScalarFormatter(useOffset=False))
    ax.set_xlabel("x", fontsize=8)
    ax.set_ylabel("y", fontsize=8)


def plot_domain_summary(
    domain: Domain,
    output_dir: Path,
    *,
    case_id: str = "base",
    show_plot: bool = True,
) -> Path:
    """Save a quick validation figure for domain top/bottom/thickness (+ geology)."""
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

    geology = domain.zones.get("geology")
    has_geology = geology is not None and hasattr(geology, "encoded_codes")
    ncols = 4 if has_geology else 3

    fig, axes = plt.subplots(1, ncols, figsize=(4.1 * ncols, 3.2), dpi=110)
    if ncols == 1:
        axes = [axes]

    im_top = axes[0].imshow(top, cmap="terrain", origin="upper", extent=extent)
    axes[0].set_title("surface_topo", fontsize=8)
    _format_axes(axes[0])
    cbar_top = plt.colorbar(im_top, ax=axes[0], fraction=0.046, pad=0.03)
    cbar_top.ax.tick_params(labelsize=7)
    cbar_top.set_label("m", fontsize=8)

    im_bot = axes[1].imshow(bot, cmap="terrain", origin="upper", extent=extent)
    axes[1].set_title("substratum", fontsize=8)
    _format_axes(axes[1])
    cbar_bot = plt.colorbar(im_bot, ax=axes[1], fraction=0.046, pad=0.03)
    cbar_bot.ax.tick_params(labelsize=7)
    cbar_bot.set_label("m", fontsize=8)

    im_thk = axes[2].imshow(thick, cmap="viridis", origin="upper", extent=extent)
    axes[2].set_title("thickness (top - bottom)", fontsize=8)
    _format_axes(axes[2])
    cbar_thk = plt.colorbar(im_thk, ax=axes[2], fraction=0.046, pad=0.03)
    cbar_thk.ax.tick_params(labelsize=7)
    cbar_thk.set_label("m", fontsize=8)

    if has_geology:
        geology_codes = np.asarray(geology.encoded_codes, dtype=float)
        geology_codes = np.where(geology_codes > 0, geology_codes, np.nan)
        im_geo = axes[3].imshow(
            geology_codes,
            cmap="tab20",
            origin="upper",
            extent=extent,
            interpolation="nearest",
        )
        axes[3].set_title("geology (encoded classes)", fontsize=8)
        _format_axes(axes[3])
        cbar_geo = plt.colorbar(im_geo, ax=axes[3], fraction=0.046, pad=0.03)
        cbar_geo.ax.tick_params(labelsize=7)
        cbar_geo.set_label("code", fontsize=8)

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
    fig.subplots_adjust(top=0.86)
    fig.savefig(fig_path, bbox_inches="tight", pad_inches=0.03)
    if show_plot:
        plt.show(block=True)
    else:
        plt.close(fig)
    return fig_path


def _build_parser() -> argparse.ArgumentParser:
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
    args = _build_parser().parse_args(argv)
    workspace, _geographic, domain, summary = run_domain_case_from_toml(
        args.config,
        build_geology=(not bool(args.no_build_geology)),
    )

    fig_path = plot_domain_summary(
        domain,
        output_dir=Path(__file__).resolve().parent / "outputs",
        case_id=str(args.case_id),
        show_plot=(not bool(args.no_show_plot)),
    )

    print(f"[{args.case_id}] catch_folder={workspace.catch_folder}")
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
