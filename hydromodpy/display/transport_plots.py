"""Transport concentration plotting and animation helpers.

This module turns transport solver outputs into visual artifacts that are easy
to inspect and share:
- per-time-step PNG frames;
- an animated GIF built from those frames;
- a self-contained HTML animation driven by Plotly.

The core idea is to compute the concentration frames once, then reuse them for
the different export formats.
"""
from __future__ import annotations

import base64
from pathlib import Path


def _resolve_ucn_path(model_transport) -> Path:
    """Resolve the binary concentration file path for a transport run."""

    path_file = getattr(model_transport, "path_file", None)
    if path_file is None:
        raise ValueError("Transport plotting now requires model_transport.path_file")
    return Path(path_file)


def _load_concentration_cube(model_transport):
    """Load the full 3D concentration time cube from binary output."""

    import flopy.utils.binaryfile as bf

    path_ucn = _resolve_ucn_path(model_transport)
    ucnobj = bf.UcnFile(path_ucn)
    concentration = ucnobj.get_alldata(mflay=None)

    concentration = concentration.astype(float)
    concentration[concentration >= 1e30] = float("nan")
    return concentration


def _input_concentration_mg_l(model_transport) -> float:
    """Estimate the injected concentration in ``mg/L`` for plot reference lines.

    This value is used only as a visual reference line in concentration plots.
    Scalar and dictionary-style transport inputs are both accepted; unsupported
    payloads fall back to ``0.0`` so the caller can simply omit the line.
    """

    sconc_input = getattr(model_transport, "sconc_input", None)
    if isinstance(sconc_input, dict) and sconc_input:
        first_key = sorted(sconc_input)[0]
        return float(sconc_input[first_key].mean()) * 1000
    if sconc_input is not None:
        try:
            return float(sconc_input) * 1000
        except Exception:
            pass
    return 0.0


def plot_concentration_frames(
    *,
    model_transport,
    model_modflow,
    workspace,
    geographic,
    hydrography,
    recharge_series,
    output_dir: Path,
    prefix: str,
    dpi: int = 300,
    save_frames: bool = True,
    show_last_frame: bool = False,
) -> list[Path]:
    """Render one concentration frame per stress period and return their paths.

    This is the main plotting routine of the transport display workflow.
    For each usable stress period, it builds one two-panel figure:
- the top panel summarizes the temporal evolution of concentration statistics
  and recharge forcing;
- the bottom panel maps seepage concentration over the watershed.

    The function can either:
- save all frames to ``output_dir`` for later reuse by file exporters;
- keep only the last valid frame open and show it interactively.

    This keeps transport behavior conceptually aligned with the flow plots:
    ``show`` gives the user a visible figure, while batch exports can still
    reuse the full frame sequence when needed.
    """

    # Keep optional plotting/GIS dependencies local to this export routine.
    import geopandas as gpd
    import imageio.v2 as imageio
    import matplotlib.cm as cm
    import matplotlib.colors as mcolors
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import rasterio
    import rasterio.plot
    from mpl_toolkits.axes_grid1 import make_axes_locatable

    if save_frames:
        output_dir.mkdir(parents=True, exist_ok=True)

    concentration_cube = _load_concentration_cube(model_transport) * 1000
    nper = int(model_modflow.nper)
    # Align MT3D outputs with MODFLOW stress periods when warm-up slices exist.
    offset = max(int(concentration_cube.shape[0]) - nper, 0)
    nframes = min(nper, len(recharge_series), max(int(concentration_cube.shape[0]) - offset, 0))
    if nframes <= 0:
        return []

    input_no3 = _input_concentration_mg_l(model_transport)
    recharge_month = recharge_series.iloc[:nframes] * 1000 * 30

    watershed = gpd.read_file(geographic.watershed_shp)
    streams = gpd.read_file(hydrography.streams) if hydrography is not None else None

    dem_path = Path(geographic.watershed_dem)
    hill_path = workspace.stable_folder / "geographic" / "watershed_hill.tif"

    frame_paths: list[Path] = []
    all_box_stats: list[tuple[float, list[dict[str, float | list[float]]]]] = []
    mean_vals: list[float] = []
    mean_times: list[float] = []
    last_figure = None

    with rasterio.open(dem_path) as dem:
        hill = rasterio.open(hill_path) if hill_path.exists() else None
        dem_data = dem.read(1)
        dem_mask = np.ma.masked_where(dem_data < 0, dem_data)
        hill_mask = None
        if hill is not None:
            hill_data = hill.read(1)
            hill_mask = np.ma.masked_where(hill_data < 0, hill_data)

        try:
            for i in range(nframes):
                seep_path = Path(model_modflow.full_path) / "_postprocess" / "_rasters" / f"outflow_drain_t({i}).tif"
                if seep_path.exists():
                    seep = imageio.imread(seep_path)
                else:
                    seep = np.zeros_like(concentration_cube[offset + i][0], dtype=float)

                concentration_surface = concentration_cube[offset + i][0]
                concentration_surface = np.ma.masked_where(seep <= 0, concentration_surface)
                values = np.asarray(concentration_surface).astype(float).ravel()
                values = values[~np.isnan(values)]
                if values.size == 0:
                    # Skip fully dry/no-seepage frames instead of writing blanks.
                    continue

                xpos = mdates.date2num(pd.to_datetime(recharge_month.index[i]))
                q10 = float(np.nanmin(values))
                q90 = float(np.nanmax(values))
                median = float(np.nanmedian(values))
                mean = float(np.nanmean(values))
                box_stats = [{
                    "med": median,
                    "mean": mean,
                    "q1": q10,
                    "q3": q90,
                    "whislo": q10,
                    "whishi": q90,
                    "fliers": [],
                }]
                mean_vals.append(mean)
                mean_times.append(xpos)
                all_box_stats.append((xpos, box_stats))

                fig, axs = plt.subplots(
                    2,
                    1,
                    figsize=(8, 12),
                    dpi=dpi,
                    gridspec_kw={"height_ratios": [1, 3]},
                )
                ax = axs.ravel()
                axb = ax[0].twinx()
                ax[0].zorder, axb.zorder = 1, 0
                ax[0].patch.set_visible(False)

                # Redraw the full history on each frame so the animation is cumulative.
                for xpos_b, box_stat in all_box_stats:
                    ax[0].bxp(
                        box_stat,
                        positions=[xpos_b],
                        widths=5,
                        showfliers=False,
                        showmeans=True,
                        meanline=False,
                        boxprops=dict(color="forestgreen"),
                        medianprops=dict(color="forestgreen"),
                        meanprops=dict(
                            marker="o",
                            markerfacecolor="k",
                            markeredgecolor="k",
                            markersize=5,
                        ),
                    )

                ax[0].axvline(x=xpos, color="black", linestyle="--", lw=0.5, zorder=-1)
                if input_no3 > 0:
                    ax[0].axhline(
                        y=input_no3,
                        color="darkorange",
                        linestyle="-",
                        lw=1,
                        zorder=-1,
                        label=f"Injection: {input_no3:.0f} mg/L",
                    )
                ax[0].set_ylabel("[NO3] mg/L", color="forestgreen")
                ax[0].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
                ax[0].set_xlim(
                    pd.to_datetime(recharge_month.index[0]),
                    pd.to_datetime(recharge_month.index[-1]) + pd.Timedelta(days=31),
                )
                ax[0].plot(mean_times, mean_vals, color="black", lw=2)
                axb.step(recharge_month.index[: nframes], recharge_month.iloc[: nframes], lw=2, color="dodgerblue")
                axb.set_ylabel("Recharge [mm/month]", color="dodgerblue")

                vmin = max(1e-6, float(np.nanmin(values)))
                vmax = max(vmin, float(np.nanmax(values)))
                norm = mcolors.LogNorm(vmin=vmin, vmax=vmax)
                scalar_mappable = cm.ScalarMappable(cmap="turbo", norm=norm)
                scalar_mappable.set_array([])

                if hill is not None:
                    # Prefer hillshade when available because it improves relief cues.
                    rasterio.plot.show(
                        hill_mask,
                        ax=ax[1],
                        transform=hill.transform,
                        cmap="Greys_r",
                        alpha=0.75,
                        zorder=-10,
                    )
                else:
                    rasterio.plot.show(
                        dem_mask,
                        ax=ax[1],
                        transform=dem.transform,
                        cmap="Greys_r",
                        alpha=0.4,
                        zorder=-10,
                    )

                rasterio.plot.show(
                    np.ma.masked_where(dem_data < 0, concentration_surface.copy()),
                    ax=ax[1],
                    transform=dem.transform,
                    cmap="turbo",
                    alpha=1,
                    zorder=1,
                )
                watershed.plot(ax=ax[1], facecolor="None", edgecolor="k", lw=3, zorder=2)
                if streams is not None:
                    streams.plot(ax=ax[1], color="navy", lw=1, zorder=0)

                divider = make_axes_locatable(ax[1])
                cax = divider.new_vertical(size="5%", pad=0.6, pack_start=True)
                fig.add_axes(cax)
                fig.colorbar(scalar_mappable, cax=cax, orientation="horizontal", label="[NO3] mg/L")
                fig.tight_layout()

                if save_frames:
                    frame_path = output_dir / f"{prefix}_{i:03d}_{model_modflow.model_name}.png"
                    fig.savefig(frame_path, dpi=dpi, bbox_inches="tight")
                    frame_paths.append(frame_path)

                if show_last_frame:
                    if last_figure is not None:
                        plt.close(last_figure)
                    last_figure = fig
                else:
                    plt.close(fig)
        finally:
            if hill is not None:
                hill.close()

    if show_last_frame and last_figure is not None:
        plt.show()
        plt.close(last_figure)

    return frame_paths


def build_concentration_gif(
    *,
    frame_paths: list[Path],
    gif_path: Path,
    duration_ms: int = 200,
) -> Path | None:
    """Assemble exported PNG frames into an animated GIF.

    Returns the written GIF path, or ``None`` when no input frames are
    available. The function only handles the assembly step; it assumes the
    individual PNG frames were already created upstream.
    """

    from PIL import Image

    if not frame_paths:
        return None

    images = [Image.open(path) for path in frame_paths]
    try:
        images[0].save(
            gif_path,
            save_all=True,
            append_images=images[1:],
            duration=duration_ms,
            loop=0,
        )
    finally:
        for image in images:
            image.close()
    return gif_path


def plot_web_animation(
    *,
    frame_paths: list[Path],
    html_path: Path | None = None,
    show_in_browser: bool = True,
) -> Path | None:
    """Build a Plotly slider animation from pre-rendered PNG frames.

    The HTML file is written only when ``html_path`` is provided; browser
    display remains optional and controlled separately.

    The animation is image-based rather than data-driven: each step swaps the
    displayed PNG frame, which keeps the exported HTML independent from the
    original numerical arrays.
    """

    if not frame_paths:
        return None

    import plotly.graph_objects as go

    def image_to_base64(path: Path) -> str:
        """Embed one PNG frame directly in the Plotly HTML payload.

        Inlining images keeps the exported HTML self-contained, which makes the
        output easier to share without managing sidecar image files.
        """

        with path.open("rb") as fh:
            raw = fh.read()
        return "data:image/png;base64," + base64.b64encode(raw).decode("utf-8")

    image_sources = [image_to_base64(path) for path in frame_paths]
    base_image = dict(
        source=image_sources[0],
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        sizex=1,
        sizey=1,
        xanchor="center",
        yanchor="middle",
        sizing="contain",
    )

    frames = [
        go.Frame(
            name=str(i),
            layout=go.Layout(images=[dict(base_image, source=src)]),
        )
        for i, src in enumerate(image_sources)
    ]

    fig = go.Figure(
        layout=go.Layout(
            title="Concentration frames",
            images=[base_image],
            updatemenus=[dict(
                type="buttons",
                showactive=False,
                y=1.05,
                x=1.15,
                xanchor="right",
                yanchor="top",
                buttons=[
                    dict(
                        label="Play",
                        method="animate",
                        args=[None, {"frame": {"duration": 500, "redraw": True}, "fromcurrent": True}],
                    ),
                    dict(
                        label="Pause",
                        method="animate",
                        args=[[None], {"frame": {"duration": 0, "redraw": False}, "mode": "immediate"}],
                    ),
                ],
            )],
            sliders=[{
                "steps": [
                    {
                        "method": "animate",
                        "args": [[str(k)], {"mode": "immediate", "frame": {"duration": 0, "redraw": True}}],
                        "label": f"{k + 1}",
                    }
                    for k in range(len(image_sources))
                ],
                "transition": {"duration": 0},
                "x": 0.5,
                "xanchor": "center",
                "y": -0.01,
                "yanchor": "top",
                "len": 0.85,
                "pad": {"t": 40},
            }],
        ),
        frames=frames,
    )

    fig.update_layout(width=1600, height=900, margin=dict(l=60, r=60, t=60, b=90))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)

    if html_path is not None:
        html_path.parent.mkdir(parents=True, exist_ok=True)
        fig.write_html(html_path)

    if show_in_browser:
        fig.show("browser")

    return html_path
