"""Turn the nitrate field of the Naizin run into an animation.

``project.toml`` writes one concentration map, at the end of the drought. The
plume is a story about time, though, so this script renders the same registry
figure once per stress period and stitches the frames into a GIF and into a
plotly slider, the two artefacts the legacy example produced.

Nothing is hand-drawn: every frame is ``concentration_map`` with a different
``timestep``, exactly what ``[display.overrides]`` would pass.

    python examples/projects/09_transport_model_for_an_agricultural_catchment/build_concentration_animation.py
"""

# %% ---- IMPORTS AND PATHS

from pathlib import Path

import hydromodpy as hmp
from hydromodpy.display.animation import build_gif, build_plotly_slider

HERE = Path(__file__).resolve().parent


# %% ---- READ THE LAST RUN BACK, RENDER, STITCH
#
# Everything stays inside the catalog context: a Run reads its rows through the
# catalog connection, so it stops answering the moment the context closes.

with hmp.open(HERE) as catalog:
    # The run is read back rather than replayed: the animation is a view on
    # results that already exist.
    run = catalog.latest()
    out = catalog.run_dir_for(run.sim_id) / "figures" / "animation"
    out.mkdir(parents=True, exist_ok=True)

    n_steps = int(run.n_timesteps or 0)
    print(f"run {run.name}: {n_steps} stress periods")

    # A shared colour scale, otherwise every frame renormalises and the plume
    # looks static while the numbers fall.
    frames = []
    for step in range(n_steps):
        path = out / f"concentration_{step:02d}.png"
        hmp.figure(run, "concentration_map", save=path, timestep=step, vmin=0.0, vmax=0.12)
        frames.append(path)
    print(f"{len(frames)} frames written under {out}")

gif = build_gif(frame_paths=frames, gif_path=out / "concentration.gif", duration_ms=400)
print(f"GIF: {gif}")

slider = build_plotly_slider(
    frame_paths=frames,
    html_path=out / "concentration_slider.html",
    show_in_browser=False,
    title="Naizin nitrate, monthly",
)
print(f"slider: {slider}")
