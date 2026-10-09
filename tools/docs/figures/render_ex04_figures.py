"""Render every figure the documentation shows, from example 04 and the synthetic demo.

The documentation pictures are outputs of the code, never hand-made. This script
runs the example in a scratch workspace, redraws the figures of the stored runs
and writes them as WebP under ``docs/source/_static/figures/``. It also writes
the manifest ``tools/docs/figures/figures.toml``: for every image, the run, the
figure, its options, the command that makes it and the page that shows it.

Stages (``--stage``), each one idempotent:

``runs``
    Bootstrap the workspace (``hmp workspace init``, ``hmp example add 04``),
    then run the staircase steps, the frozen reference, the two-stage
    calibration, the files of the modelling guides and the two synthetic demo
    runs. A run that already exists in the project catalog is not run again.
    Steps 3 and 6 and the calibration need the network on their first run.
``figures``
    Redraw the figures from the stored runs (hero, Understand, staircase,
    guides, model, catalog) and write the manifest.

The modelling guides (wells, mesh, terrain, depth, boundaries, zones,
particles, solute, SFR) each ship a file under ``docs/source/guides/recipes/model/``.
The ``model`` group copies it into the example 04 project, runs it, and draws
the figures its page shows from that run.

Run it from anywhere, never with the workspace inside the repository::

    python tools/docs/figures/render_ex04_figures.py --workspace ~/scratch/figures --cores 2

Figures are drawn through ``hydromodpy.display.runs.render_figure``, the path
of ``hmp viz show``. The theme is the ``[display] preset`` of the figure API:
``default`` for the light variant and ``dark`` for the dark one. Every figure
is drawn with ``show_run_name = false``: a page shows a figure, not a dated
run, so no title names the run it came from.
"""

from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DOCS_SOURCE = ROOT / "docs" / "source"
OUT_ROOT = DOCS_SOURCE / "_static" / "figures"
MANIFEST = Path(__file__).with_name("figures.toml")

EXAMPLE_ID = "04"
EXAMPLE_DIR = "04_streamflow_intermittence_in_transient"
BUDGET_BYTES = 150 * 1024
THUMB_WIDTH = 320
DPI = 150

# -- the runs ------------------------------------------------------------------


@dataclass(frozen=True)
class RunSpec:
    """One TOML file of the example, the run it writes and the step it belongs to."""

    key: str
    toml: str
    run: str
    step: int | None = None
    needs_network: bool = False
    note: str = ""
    args: tuple[str, ...] = ()

    @property
    def command(self) -> str:
        return " ".join(["hmp run", self.toml, *self.args])


STEPS: tuple[RunSpec, ...] = (
    RunSpec("step1", "step1_minimal.toml", "nancon_step1_minimal", 1),
    RunSpec("step2", "step2_local_data.toml", "nancon_step2_local", 2),
    RunSpec("step3", "step3_api_data.toml", "nancon_step3_api", 3, True),
    RunSpec("step4", "step4_transient.toml", "nancon_step4_transient", 4),
    RunSpec("step5", "step5_export.toml", "nancon_step5_export", 5),
    RunSpec("step6", "step6_soil_reservoir.toml", "nancon_soil_reservoir_daily", 6, True),
)
REFERENCE = RunSpec("reference", "project.toml", "nancon_intermittence_mf6")
CALIBRATION = RunSpec(
    "calibrated",
    "run_calibration.toml",
    "nancon_intermittence_mf6_calibrated",
    needs_network=False,
    note="two stages, K on the mapped network then Sy on the gauge",
)
# The reference again with the routed drain flux kept, which two guide figures read.
ACTIVE_NETWORK = RunSpec(
    "active_network",
    "project.toml",
    "nancon_ex04_active_network",
    args=(
        "--set simulation.name=nancon_ex04_active_network",
        "--set simulation.results.derived.accumulation_flux=true",
    ),
    note="the reference with accumulation_flux kept",
)
# The promoted run of the second stage: the one the Understand pages describe.
CALIBRATED_RUNS = (
    "nancon_intermittence_mf6_calibrated_transient_storage",
    "nancon_intermittence_mf6_calibrated_steady_conductivity",
)


@dataclass(frozen=True)
class GuideFigure:
    """One figure a modelling guide shows, drawn from the run of its own file."""

    figure: str
    reference: str | None = None


@dataclass(frozen=True)
class GuideRun:
    """The file of a modelling guide, the run it writes and the figures its page shows."""

    spec: RunSpec
    page: str
    figures: tuple[GuideFigure, ...]
    extras: tuple[str, ...] = ()

    @property
    def folder(self) -> str:
        return Path(self.page).stem


RECIPES = DOCS_SOURCE / "guides" / "recipes" / "model"

GUIDE_RUNS: tuple[GuideRun, ...] = (
    GuideRun(
        RunSpec("guide_wells", "guide_wells.toml", "nancon_guide_wells"),
        "guides/add-wells.md",
        (GuideFigure("watertable_depth_map"), GuideFigure("cross_section")),
    ),
    GuideRun(
        RunSpec("guide_mesh", "guide_mesh.toml", "nancon_guide_mesh"),
        "guides/choose-and-build-the-mesh.md",
        (GuideFigure("mesh_map"),),
        extras=("well_w1.geojson",),
    ),
    GuideRun(
        RunSpec("guide_terrain", "guide_terrain.toml", "nancon_guide_terrain"),
        "guides/prepare-the-terrain.md",
        (
            GuideFigure("depression_map"),
            GuideFigure("conditioning_impact_map", reference="nancon_step1_minimal"),
        ),
    ),
    GuideRun(
        RunSpec("guide_depth", "guide_depth.toml", "nancon_guide_depth"),
        "guides/depth-and-substratum.md",
        (GuideFigure("cross_section"), GuideFigure("parameter_section")),
    ),
    GuideRun(
        RunSpec("guide_boundaries", "guide_boundaries.toml", "nancon_guide_boundaries"),
        "guides/boundary-and-initial-conditions.md",
        (GuideFigure("boundary_package_map"),),
    ),
    GuideRun(
        RunSpec("guide_k_zones", "guide_k_zones.toml", "nancon_guide_k_zones"),
        "guides/k-per-zone.md",
        (GuideFigure("parameter_map"),),
    ),
    GuideRun(
        RunSpec("guide_particles", "guide_particles.toml", "nancon_guide_particles"),
        "guides/track-particles.md",
        (GuideFigure("particle_tracks"), GuideFigure("residence_time_distribution")),
    ),
    GuideRun(
        RunSpec("guide_solute", "guide_solute.toml", "nancon_guide_solute"),
        "guides/transport-and-particles.md",
        (GuideFigure("concentration_map"),),
    ),
    GuideRun(
        RunSpec("guide_sfr", "guide_sfr.toml", "nancon_guide_sfr"),
        "guides/route-streams-with-sfr.md",
        (GuideFigure("sfr_reach_network"), GuideFigure("hydrograph_sim_obs")),
    ),
)
"""The modelling guides that show a run of their own file. Their pages are left
out of the ``guides`` group, which draws cited figures from the example runs."""


# Where a guide figure is looked for, first run that can draw it wins.
GUIDE_RUN_ORDER = (
    "nancon_intermittence_mf6_calibrated_transient_storage",
    "nancon_intermittence_mf6_calibrated_steady_conductivity",
    "nancon_intermittence_mf6",
    "nancon_ex04_active_network",
    "nancon_step4_transient",
    "nancon_step3_api",
    "nancon_step2_local",
    "nancon_step1_minimal",
)

# -- what is drawn -------------------------------------------------------------

UNDERSTAND_FIGURES = (
    "watertable_depth_map",
    "seepage_map",
    "seepage_network_confusion_map",
    "downslope_distance_map",
    "flow_persistence_map",
    "flow_intermittence_map",
    "hydrograph_log_nse",
    "flux_timeseries",
)

# The figure that stands for a step on the staircase index and in the step page.
STEP_KEY_FIGURE = {
    1: "watertable_depth_map",
    2: "seepage_network_confusion_map",
    3: "hydrographic_network_permanence",
    4: "flow_intermittence_map",
    5: "watertable_depth_map",
    6: "flux_timeseries",
}

HERO_FIGURE = "flow_intermittence_map"

# Demo figures that compare two runs: the second run is the reference.
DEMO_COMPARISON_FIGURES = ("difference_map", "side_by_side", "conditioning_impact_map")
DEMO_CANDIDATES = (
    "conditioning_impact_map",
    "cross_section",
    "depression_map",
    "difference_map",
    "flow_direction_map",
    "flux_timeseries",
    "mass_balance_error",
    "mesh_map",
    "piezometric_map",
    "seepage_map",
    "side_by_side",
    "water_budget",
    "watershed_id_card",
    "watertable_depth_map",
)


@dataclass
class Entry:
    """One image of the manifest."""

    kind: str
    figure: str
    path: str
    theme: str
    run: str = ""
    config: str = ""
    step: int | None = None
    key: bool = False
    pages: list[str] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)
    command: str = ""
    redraw: str = ""
    width: int = 0
    height: int = 0
    bytes: int = 0
    reference_run: str = ""


# -- shell helpers -------------------------------------------------------------


def _env(cores: int) -> dict[str, str]:
    env = dict(os.environ)
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        env[name] = str(cores)
    env.setdefault("MPLBACKEND", "Agg")
    return env


def hmp(args: list[str], *, cwd: Path, cores: int, check: bool = True) -> int:
    """Run ``python -m hydromodpy <args>`` in ``cwd`` and stream its output."""
    command = [sys.executable, "-m", "hydromodpy", *args]
    print("$", " ".join(args), f"   ({cwd})", flush=True)
    done = subprocess.run(command, cwd=cwd, env=_env(cores), check=False)
    if check and done.returncode != 0:
        raise SystemExit(f"hmp {' '.join(args)} exited with {done.returncode}")
    return done.returncode


def refuse_inside_repository(workspace: Path) -> None:
    if ROOT == workspace or ROOT in workspace.parents:
        raise SystemExit(
            f"The workspace {workspace} is inside the repository {ROOT}. "
            "Use a scratch folder outside it."
        )


# -- stage 1: runs -------------------------------------------------------------


def _existing_runs(project: Path) -> set[str]:
    from hydromodpy.results.catalog import Catalog

    try:
        with Catalog(project, read_only=True) as catalog:
            frame = catalog.list_simulations()
    except Exception:  # no index yet: nothing ran
        return set()
    done = frame[frame["status"] == "completed"] if "status" in frame else frame
    return set(done["name"])


def bootstrap_workspace(workspace: Path, cores: int) -> None:
    if not (workspace / "workspace.toml").is_file():
        hmp(["workspace", "init", str(workspace)], cwd=workspace.parent, cores=cores)
    if not (workspace / "projects" / EXAMPLE_DIR / "project.toml").is_file():
        hmp(["example", "add", EXAMPLE_ID, "-w", str(workspace)], cwd=workspace, cores=cores)


def demo_variant(demo: Path) -> Path:
    """Write the second demo run, the reference of the comparisons.

    K is three times higher and the slope steeper, so the heads and the tops differ.
    """
    target = demo / "run_demo_k3.toml"
    target.write_text(
        'base_config = "run_demo.toml"\n\n[simulation]\nname = "demo_k3"\n'
        'description = "The demo with a K three times higher and a steeper slope."\n\n'
        '[flow.param.K.field]\nkind = "homogeneous"\nvalue = "3.0e-4 m/s"\n\n'
        '[geographic.synthetic.topography]\nkind = "linear"\nbase_elevation = 20.0\n'
        "right_to_left_amplitude = 9.0\n",
        encoding="utf-8",
    )
    return target


def stage_runs(workspace: Path, cores: int, only: set[str]) -> None:
    bootstrap_workspace(workspace, cores)
    project = workspace / "projects" / EXAMPLE_DIR
    done = _existing_runs(project)
    for spec in (*STEPS, REFERENCE, ACTIVE_NETWORK, CALIBRATION):
        if only and spec.key not in only:
            continue
        # A calibration writes several runs; its first stage name is enough to tell.
        probe = (
            "nancon_intermittence_mf6_calibrated_transient_storage"
            if spec is CALIBRATION
            else spec.run
        )
        if probe in done:
            print(f"= {spec.toml}: run {probe} exists", flush=True)
            continue
        hmp(
            ["run", spec.toml, *(a for arg in spec.args for a in arg.split(" ", 1))],
            cwd=project,
            cores=cores,
        )
    for guide in GUIDE_RUNS:
        spec = guide.spec
        if only and "model" not in only and spec.key not in only:
            continue
        if spec.run in done:
            print(f"= {spec.toml}: run {spec.run} exists", flush=True)
            continue
        # The recipe inherits a step file of the example: it runs from the project.
        for name in (spec.toml, *guide.extras):
            (project / name).write_bytes((RECIPES / name).read_bytes())
        hmp(["run", spec.toml], cwd=project, cores=cores)
    demo = workspace / "projects" / "example"
    if only and "demo" not in only:
        return
    done = _existing_runs(demo)
    if "demo" not in done:
        hmp(["run", "run_demo.toml"], cwd=demo, cores=cores)
    if "demo_k3" not in done:
        hmp(["run", demo_variant(demo).name], cwd=demo, cores=cores)


# -- stage 2: drawing ----------------------------------------------------------


def run_names_left(fig, names: Iterable[str]) -> list[str]:
    """Return the texts of ``fig`` that still name a run, which should be none.

    ``show_run_name = false`` keeps the run out of every title; a text found
    here is a figure that writes the run some other way.
    """
    from matplotlib.text import Text

    names = [n for n in names if n]
    return [
        text.get_text()
        for text in fig.findobj(Text)
        if text.get_text() and any(n in text.get_text() for n in names)
    ]


def to_webp(png: bytes, *, width: int | None = None) -> tuple[bytes, tuple[int, int]]:
    """Encode a PNG as WebP within the byte budget: lossless first, then lossy, then smaller."""
    from PIL import Image

    image = Image.open(io.BytesIO(png)).convert("RGB")
    if width is not None and image.width > width:
        height = round(image.height * width / image.width)
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    scale = 1.0
    while True:
        current = image
        if scale < 1.0:
            size = (round(image.width * scale), round(image.height * scale))
            current = image.resize(size, Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        current.save(buffer, "WEBP", lossless=True, method=6)
        if buffer.tell() <= BUDGET_BYTES:
            return buffer.getvalue(), current.size
        for quality in (92, 85, 78, 70):
            buffer = io.BytesIO()
            current.save(buffer, "WEBP", quality=quality, method=6)
            if buffer.tell() <= BUDGET_BYTES:
                return buffer.getvalue(), current.size
        scale *= 0.85


class Drawer:
    """Open the project catalog once and draw figures from its runs."""

    def __init__(self, project: Path) -> None:
        from hydromodpy.results.catalog import Catalog

        self.catalog = Catalog(project, read_only=True)
        self.project = project
        self._runs: dict[str, Any] = {}
        self.leftovers: list[tuple[str, str]] = []

    def close(self) -> None:
        self.catalog.close()

    def run(self, name: str):
        if name not in self._runs:
            try:
                self._runs[name] = self.catalog[self.catalog.resolve(name)]
            except Exception:
                self._runs[name] = None
        return self._runs[name]

    def can_draw(self, name: str, figure: str, **extra) -> str | None:
        """Return why ``figure`` cannot be drawn from run ``name``, or None."""
        from hydromodpy.display.runs import _get_figure

        sim = self.run(name)
        if sim is None:
            return f"run {name} does not exist"
        return _get_figure(figure).unavailable_reason(sim)

    def draw(
        self,
        name: str,
        figure: str,
        *,
        dark: bool,
        reference: str | None = None,
        width: int | None = None,
    ) -> tuple[bytes, tuple[int, int], dict[str, Any]]:
        import matplotlib.pyplot as plt

        from hydromodpy.display.runs import (
            figure_options_from_run,
            matplotlib_backend,
            render_figure,
        )
        from hydromodpy.display.style import apply_theme

        sim = self.run(name)
        options = dict(figure_options_from_run(sim, figure))
        shown = dict(options)
        if reference is not None:
            options["reference"] = self.run(reference)
        with matplotlib_backend(dpi=DPI):
            apply_theme("dark" if dark else "default")
            fig = render_figure(figure, sim, show_run_name=False, **options)
            runs = [sim] + ([options["reference"]] if "reference" in options else [])
            known = [t for r in runs for t in (r.name, str(r.sim_id), str(r.sim_id)[:8])]
            left = run_names_left(fig, known)
            self.leftovers += [(f"{name}/{figure}", text) for text in left]
            buffer = io.BytesIO()
            fig.savefig(buffer, format="png", dpi=DPI, bbox_inches="tight")
            plt.close(fig)
        data, size = to_webp(buffer.getvalue(), width=width)
        return data, size, shown


def write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def theme_name(dark: bool) -> str:
    return "dark" if dark else "light"


def suffix(dark: bool) -> str:
    return "-dark" if dark else ""


def viz_command(run: str, figure: str, options: dict[str, Any]) -> str:
    when = options.get("time")
    tail = f" --time {when}" if when else ""
    return f"hmp viz show {run} {figure}{tail}"


def guide_citations() -> dict[str, list[str]]:
    """Return, for each registered figure, the guides that name it in code font or quotes."""
    from hydromodpy.display.figure_registry import names

    cited: dict[str, list[str]] = {}
    guides = sorted((DOCS_SOURCE / "guides").glob("*.md")) + sorted(
        (DOCS_SOURCE / "guides").glob("*.rst")
    )
    own_runs = {guide.page for guide in GUIDE_RUNS}
    for page in guides:
        if str(page.relative_to(DOCS_SOURCE)) in own_runs:
            continue
        text = page.read_text(encoding="utf-8")
        for figure in names():
            pattern = rf"[`\"']{re.escape(figure)}[`\"']|hmp viz show \S+ {re.escape(figure)}\b"
            if re.search(pattern, text):
                cited.setdefault(figure, []).append(str(page.relative_to(DOCS_SOURCE)))
    return cited


def pages_citing(directory: str, needle: str) -> list[str]:
    pages = []
    for page in sorted((DOCS_SOURCE / directory).rglob("*.md")):
        if needle in page.read_text(encoding="utf-8"):
            pages.append(str(page.relative_to(DOCS_SOURCE)))
    return pages


def stage_figures(workspace: Path, only: set[str], dark_guides: bool) -> list[Entry]:
    project = workspace / "projects" / EXAMPLE_DIR
    entries: list[Entry] = []
    drawer = Drawer(project)
    run_spec = {spec.run: spec for spec in (*STEPS, REFERENCE, ACTIVE_NETWORK)}
    run_spec.update({guide.spec.run: guide.spec for guide in GUIDE_RUNS})
    run_spec.update({name: CALIBRATION for name in CALIBRATED_RUNS})

    def emit(
        kind: str,
        figure: str,
        run: str,
        rel: str,
        *,
        dark: bool,
        step: int | None = None,
        key: bool = False,
        pages: list[str] | None = None,
        width: int | None = None,
        reference: str | None = None,
    ) -> None:
        data, size, options = drawer.draw(run, figure, dark=dark, reference=reference, width=width)
        path = OUT_ROOT / f"{rel}{suffix(dark)}.webp"
        write(path, data)
        spec = run_spec.get(run)
        toml = spec.toml if spec else ""
        command = spec.command if spec else ""
        if dark and command:
            command += " --set display.preset=dark"
        entries.append(
            Entry(
                kind=kind,
                figure=figure,
                path=str(path.relative_to(ROOT)),
                theme=theme_name(dark),
                run=run,
                config=toml,
                step=step,
                key=key,
                pages=pages or [],
                options={k: v for k, v in options.items() if k != "reference"},
                command=command,
                redraw=viz_command(run, figure, options),
                width=size[0],
                height=size[1],
                bytes=len(data),
                reference_run=reference or "",
            )
        )
        print(
            f"  {path.relative_to(ROOT)}  {size[0]}x{size[1]}  {len(data) / 1024:.0f} KB",
            flush=True,
        )

    def wanted(group: str) -> bool:
        return not only or group in only

    calibrated = next((n for n in CALIBRATED_RUNS if drawer.run(n) is not None), None)

    if wanted("hero"):
        print("hero", flush=True)
        source = calibrated or REFERENCE.run
        for dark in (False, True):
            emit(
                "hero",
                HERO_FIGURE,
                source,
                "hero/flow-intermittence-map",
                dark=dark,
                pages=["index.md"],
            )

    if wanted("understand") and calibrated:
        print("understand", flush=True)
        for figure in UNDERSTAND_FIGURES:
            pages = pages_citing("understand", f"img/ex04_{figure}.png")
            for dark in (False, True):
                emit(
                    "understand",
                    figure,
                    calibrated,
                    f"understand/ex04_{figure}",
                    dark=dark,
                    pages=pages,
                )

    if wanted("staircase"):
        print("staircase", flush=True)
        for spec in STEPS:
            sim = drawer.run(spec.run)
            if sim is None:
                print(f"  step {spec.step}: run {spec.run} missing, skipped", flush=True)
                continue
            figures = list(sim.config_snapshot.get("display", {}).get("figures", []))
            page = f"get-started/staircase/step{spec.step}.md"
            for figure in figures:
                reason = drawer.can_draw(spec.run, figure)
                if reason:
                    print(f"  step {spec.step} {figure}: skipped, {reason}", flush=True)
                    continue
                is_key = figure == STEP_KEY_FIGURE[spec.step]
                for dark in (False, True) if is_key else (False,):
                    emit(
                        "staircase",
                        figure,
                        spec.run,
                        f"staircase/step{spec.step}/{figure}",
                        dark=dark,
                        step=spec.step,
                        key=is_key,
                        pages=[page, "get-started/staircase/index.md"] if is_key else [page],
                    )

    if wanted("guides"):
        print("guides", flush=True)
        cited = guide_citations()
        for figure, pages in sorted(cited.items()):
            source = next((n for n in GUIDE_RUN_ORDER if drawer.can_draw(n, figure) is None), None)
            if source is None:
                print(f"  {figure}: no example 04 run can draw it, skipped", flush=True)
                continue
            for dark in (False, True) if dark_guides else (False,):
                emit("guide", figure, source, f"guides/{figure}", dark=dark, pages=pages)

    if wanted("model"):
        print("model", flush=True)
        for guide in GUIDE_RUNS:
            for item in guide.figures:
                reason = drawer.can_draw(guide.spec.run, item.figure)
                if reason:
                    print(f"  {guide.spec.run} {item.figure}: skipped, {reason}", flush=True)
                    continue
                emit(
                    "guide",
                    item.figure,
                    guide.spec.run,
                    f"guides/{guide.folder}/{item.figure}",
                    dark=False,
                    pages=[guide.page],
                    reference=item.reference,
                )

    drawer.close()
    if drawer.leftovers:
        print("run name still in a figure text:", drawer.leftovers, flush=True)
    return entries


def stage_catalog(workspace: Path) -> list[Entry]:
    """Draw the thumbnails of the figure catalog from the synthetic demo of ``workspace init``."""
    from hydromodpy.display.figure_registry import names

    demo = workspace / "projects" / "example"
    drawer = Drawer(demo)
    entries: list[Entry] = []
    registered = set(names())
    print("catalog", flush=True)
    for figure in DEMO_CANDIDATES:
        if figure not in registered:
            continue
        reference = "demo_k3" if figure in DEMO_COMPARISON_FIGURES else None
        if drawer.can_draw("demo", figure) is not None:
            print(f"  {figure}: the demo cannot draw it, skipped", flush=True)
            continue
        for dark in (False, True):
            try:
                data, size, options = drawer.draw(
                    "demo", figure, dark=dark, reference=reference, width=THUMB_WIDTH
                )
            except Exception as exc:
                print(f"  {figure}: failed, {str(exc)[:90]}", flush=True)
                break
            path = OUT_ROOT / "catalog" / f"{figure}{suffix(dark)}.webp"
            write(path, data)
            entries.append(
                Entry(
                    kind="catalog",
                    figure=figure,
                    path=str(path.relative_to(ROOT)),
                    theme=theme_name(dark),
                    run="demo",
                    config="run_demo.toml",
                    pages=["reference/figures.md"],
                    options=options,
                    command="hmp run run_demo.toml"
                    + (" --set display.preset=dark" if dark else ""),
                    redraw=f"hmp viz show demo {figure}",
                    width=size[0],
                    height=size[1],
                    bytes=len(data),
                    reference_run=reference or "",
                )
            )
            print(
                f"  {path.relative_to(ROOT)}  {size[0]}x{size[1]}  {len(data) / 1024:.0f} KB",
                flush=True,
            )
    drawer.close()
    return entries


# -- manifest ------------------------------------------------------------------


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, list | tuple):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{k} = {_toml_value(v)}" for k, v in value.items()) + " }"
    return _toml_value(str(value))


def entry_row(e: Entry) -> dict[str, Any]:
    """Return the manifest row of one image, in the order the file writes it."""
    row: dict[str, Any] = {
        "name": e.figure,
        "path": e.path,
        "kind": e.kind,
        "theme": e.theme,
    }
    if e.step is not None:
        row["step"] = e.step
        row["key"] = e.key
    row["run"] = e.run
    if e.reference_run:
        row["reference_run"] = e.reference_run
    row["config"] = e.config
    row["command"] = e.command
    row["redraw"] = e.redraw
    row["pages"] = e.pages
    if e.options:
        row["options"] = e.options
    row.update(width=e.width, height=e.height, bytes=e.bytes)
    return row


def write_manifest(entries: list[Entry]) -> None:
    """Write the manifest. A partial run replaces the rows of its own paths and keeps the rest."""
    import hydromodpy

    rows = {e.path: entry_row(e) for e in entries}
    if MANIFEST.is_file():
        for old in tomllib.loads(MANIFEST.read_text(encoding="utf-8")).get("figure", []):
            if old["path"] not in rows and (ROOT / old["path"]).is_file():
                rows[old["path"]] = old
    lines = [
        "# Manifest of the documentation figures, written by render_ex04_figures.py.",
        "# Do not edit by hand: run the script. One [[figure]] per image.",
        "# `command` makes the run, `redraw` draws the figure again from the stored run.",
        '# A dark image is the same figure drawn with [display] preset = "dark".',
        "",
        "[meta]",
        f'generated = "{date.today().isoformat()}"',
        f'hydromodpy = "{hydromodpy.__version__}"',
        f'example = "{EXAMPLE_ID}"',
        f'script = "{Path(__file__).resolve().relative_to(ROOT)}"',
        f"budget_bytes = {BUDGET_BYTES}",
        f"thumbnail_width = {THUMB_WIDTH}",
        "",
    ]
    order = {"hero": 0, "understand": 1, "staircase": 2, "guide": 3, "catalog": 4}
    for row in sorted(rows.values(), key=lambda r: (order[r["kind"]], r.get("step", 0), r["path"])):
        lines.append("[[figure]]")
        lines += [f"{key} = {_toml_value(value)}" for key, value in row.items()]
        lines.append("")
    MANIFEST.write_text("\n".join(lines), encoding="utf-8")
    tomllib.loads(MANIFEST.read_text(encoding="utf-8"))  # the manifest must load
    print(f"manifest: {MANIFEST.relative_to(ROOT)}, {len(rows)} images", flush=True)


# -- main ----------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--workspace", type=Path, required=True, help="scratch workspace, outside the repository"
    )
    parser.add_argument("--stage", choices=("runs", "figures", "all"), default="all")
    parser.add_argument("--cores", type=int, default=2, help="threads for each run (default 2)")
    parser.add_argument(
        "--only",
        default="",
        help=(
            "comma list: runs (step1..step6, reference, calibrated, model or one guide_* key, "
            "demo); figures (hero, understand, staircase, guides, model, catalog)"
        ),
    )
    parser.add_argument(
        "--dark-guides", action="store_true", help="also draw the dark variant of the guide figures"
    )
    args = parser.parse_args(argv)

    workspace = args.workspace.expanduser().resolve()
    refuse_inside_repository(workspace)
    only = {item for item in args.only.split(",") if item}

    if args.stage in ("runs", "all"):
        stage_runs(workspace, args.cores, only)
    if args.stage in ("figures", "all"):
        os.environ.setdefault("MPLBACKEND", "Agg")
        entries = stage_figures(workspace, only, args.dark_guides)
        if not only or "catalog" in only:
            entries += stage_catalog(workspace)
        write_manifest(entries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
