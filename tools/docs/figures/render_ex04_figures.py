"""Render every figure the documentation shows, from example 04.

The documentation pictures are outputs of the code, never hand-made. This script
runs the example in a scratch workspace, redraws the figures of the stored runs
and writes them as WebP under ``docs/source/_static/figures/``. The manifest
``tools/docs/figures/figures.toml`` lists every image: the run, the figure request,
the command that makes the run, the command that draws the figure again and the
pages that show it. The script reads the requests from it and writes the sizes back.

Stages (``--stage``), each one idempotent:

``runs``
    Bootstrap the workspace (``hmp workspace init``, ``hmp example add 04``),
    then run the reference, the two solver copies of the reference and the
    two-stage calibration. A run that already exists in the project catalog is
    not run again.
``figures``
    Draw each manifest row with ``run.figure(request=..., theme=...)`` and write the
    manifest.

The ``solvers`` group draws the same figure from two copies of the reference, one
solved by MODFLOW 6 and one by MODFLOW-NWT, both storing their fields at full
precision. The default compact storage keeps 16 mantissa bits, a step of 1 to 2 mm
at the heads of this catchment, larger than the gap between the solvers. The script
writes both copies into the scratch project (``run_mf6_exact.toml``,
``run_nwt_exact.toml``), and the calibration file too (``run_calibration.toml``).
The example ships none of them.

Run it from anywhere, never with the workspace inside the repository::

    python tools/docs/figures/render_ex04_figures.py --workspace ~/scratch/figures --cores 2

The theme is ``default`` for the light variant and ``dark`` for the dark one.
"""

from __future__ import annotations

import argparse
import io
import os
import shlex
import subprocess
import sys
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
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
DPI = 150

# -- the runs ------------------------------------------------------------------


@dataclass(frozen=True)
class RunSpec:
    """One TOML file of the example, and the run it writes."""

    key: str
    toml: str
    run: str
    needs_network: bool = False
    note: str = ""
    args: tuple[str, ...] = ()

    @property
    def command(self) -> str:
        return " ".join(["hmp run", self.toml, *self.args])


REFERENCE = RunSpec("reference", "project.toml", "nancon_intermittence_mf6")
# The two copies of the reference the solvers group compares, written by solver_variant.
SOLVER_MF6 = RunSpec(
    "solver_mf6",
    "run_mf6_exact.toml",
    "nancon_mf6",
    note="project.toml with the fields stored at full precision",
)
SOLVER_NWT = RunSpec(
    "solver_nwt",
    "run_nwt_exact.toml",
    "nancon_nwt",
    note="project.toml solved by MODFLOW-NWT, fields stored at full precision",
)
SOLVER_RUNS = (SOLVER_MF6, SOLVER_NWT)
CALIBRATION = RunSpec(
    "calibrated",
    "run_calibration.toml",
    "nancon_intermittence_mf6_calibrated",
    needs_network=False,
    note="two stages, K on the mapped network then Sy on the gauge",
)
# The calibration the Reading results page draws, written by calibration_file.
CALIBRATION_TOML = """\
base_config = "project.toml"

[workflow]
mode = "calibration"

[simulation]
name = "nancon_intermittence_mf6_calibrated"
description = "Nancon, K from the mapped network then Sy from the gauge."

[calibration.parameters.K]
bounds = [1e-7, 1e-3]

[calibration.parameters.Sy]
bounds = [5e-3, 0.35]

[calibration.outputs.seepage_network]
support = "network"

[calibration.outputs.seepage_network.map]
complete = "nancon_stream_network.gpkg"

[calibration.protocol]
name = "matching_hydrographic_network"
transient_max_trials = 30
transient_precision = 0.05

[display]
figure__append = [
    {variable = "discharge", type = "xy", observed = true, reference = ["one_to_one"]},
]
"""


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
    from hydromodpy.results.catalog.facade import Catalog

    try:
        with Catalog(project) as catalog:
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


def solver_variant(project: Path, spec: RunSpec) -> Path:
    """Write a copy of the reference that stores its fields at full precision.

    The NWT copy also solves the flow with MODFLOW-NWT. Nothing else changes.
    """
    nwt = spec is SOLVER_NWT
    solver = "modflow_nwt" if nwt else "modflow6"
    what = "solved by MODFLOW-NWT" if nwt else "solved by MODFLOW 6"
    target = project / spec.toml
    target.write_text(
        'base_config = "project.toml"\n\n[simulation]\n'
        f'name = "{spec.run}"\n'
        f'description = "The reference {what}, fields stored at full precision."\n\n'
        '[[simulation.process]]\nid = "flow_main"\ntype = "flow"\n'
        f'solvers = ["{solver}"]\n\n'
        '[simulation.results.persistence]\nfield_precision = "exact"\n',
        encoding="utf-8",
    )
    return target


def stage_runs(workspace: Path, cores: int, only: set[str]) -> None:
    bootstrap_workspace(workspace, cores)
    project = workspace / "projects" / EXAMPLE_DIR
    done = _existing_runs(project)
    for spec in (REFERENCE, *SOLVER_RUNS, CALIBRATION):
        if only and spec.key not in only:
            continue
        if spec in SOLVER_RUNS:
            solver_variant(project, spec)
        if spec is CALIBRATION:
            (project / spec.toml).write_text(CALIBRATION_TOML, encoding="utf-8")
        probe = spec.run
        if probe in done:
            print(f"= {spec.toml}: run {probe} exists", flush=True)
            continue
        hmp(
            ["run", spec.toml, *(a for arg in spec.args for a in arg.split(" ", 1))],
            cwd=project,
            cores=cores,
        )


# -- stage 2: drawing ----------------------------------------------------------


def run_names_left(fig, names: Iterable[str]) -> list[str]:
    """Return the texts of ``fig`` that still name a run, which should be none."""
    from matplotlib.text import Text

    names = [n for n in names if n]
    return [
        text.get_text()
        for text in fig.findobj(Text)
        if text.get_text() and any(n in text.get_text() for n in names)
    ]


def to_webp(png: bytes) -> tuple[bytes, tuple[int, int]]:
    """Encode a PNG as WebP within the byte budget: lossless first, then lossy, then smaller."""
    from PIL import Image

    image = Image.open(io.BytesIO(png)).convert("RGB")
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


def redraw_command(subject: str, request: dict[str, Any]) -> str:
    """The command that draws a request again from a stored run or session."""
    fields = dict(request)
    name = fields.pop("preset", None) or fields.pop("variable")
    when = fields.pop("time", None)
    parts = ["hmp show", subject, "--figure", name]
    if when:
        parts += ["--time", str(when)]
    parts += [f"--opt {shlex.quote(f'{k}={_toml_value(v)}')}" for k, v in fields.items()]
    return " ".join(parts)


def stage_figures(workspace: Path, only: set[str]) -> list[dict[str, Any]]:
    """Draw every manifest row of the groups asked, and return the rows with their new sizes."""
    import hydromodpy
    from hydromodpy.display.presets import PRESETS
    from hydromodpy.display.request import FigureRequest, expand

    rows = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))["figure"]
    project = hydromodpy.open(workspace / "projects" / EXAMPLE_DIR)
    leftovers: list[tuple[str, str]] = []
    for row in rows:
        if only and row["kind"] not in only:
            continue
        path = ROOT / row["path"]
        try:
            run = project[row["run"]]
        except Exception as exc:  # the run was never played: the row keeps its old image
            print(f"  {row['path']}: run {row['run']} missing, skipped ({exc})", flush=True)
            continue
        request = row["request"]
        subject, name = run, row["run"]
        if expand(FigureRequest.model_validate(request), PRESETS).when == "session":
            name = list(project.sessions)[-1]
            subject = project.sessions[name]
        fig = subject.figure(request=request, theme="dark" if row["theme"] == "dark" else "default")
        known = [run.name, str(run.sim_id), str(run.sim_id)[:8]]
        leftovers += [(row["path"], text) for text in run_names_left(fig, known)]
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png", dpi=DPI, bbox_inches="tight")
        data, size = to_webp(buffer.getvalue())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        row.update(
            redraw=redraw_command(name, request), width=size[0], height=size[1], bytes=len(data)
        )
        print(f"  {row['path']}  {size[0]}x{size[1]}  {len(data) / 1024:.0f} KB", flush=True)
    if leftovers:
        print("run name still in a figure text:", leftovers, flush=True)
    return rows


# -- manifest ------------------------------------------------------------------


def write_manifest(rows: list[dict[str, Any]]) -> None:
    """Write the manifest, one ``[[figure]]`` per image, and check that it loads."""
    import hydromodpy

    lines = [
        "# Manifest of the documentation figures, read and written by render_ex04_figures.py.",
        "# One [[figure]] per image. `request` is the figure request, drawn with run.figure.",
        "# `command` makes the run, `redraw` draws the figure again from the stored run.",
        '# A dark image is the same request drawn with the theme "dark".',
        "",
        "[meta]",
        f'generated = "{date.today().isoformat()}"',
        f'hydromodpy = "{hydromodpy.__version__}"',
        f'example = "{EXAMPLE_ID}"',
        f'script = "{Path(__file__).resolve().relative_to(ROOT)}"',
        f"budget_bytes = {BUDGET_BYTES}",
        "",
    ]
    for row in rows:
        lines.append("[[figure]]")
        lines += [f"{key} = {_toml_value(value)}" for key, value in row.items()]
        lines.append("")
    MANIFEST.write_text("\n".join(lines), encoding="utf-8")
    tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
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
            "comma list: runs (reference, solver_mf6, solver_nwt, calibrated); "
            "figures (understand, solvers)"
        ),
    )
    args = parser.parse_args(argv)

    workspace = args.workspace.expanduser().resolve()
    refuse_inside_repository(workspace)
    only = {item for item in args.only.split(",") if item}

    if args.stage in ("runs", "all"):
        stage_runs(workspace, args.cores, only)
    if args.stage in ("figures", "all"):
        os.environ.setdefault("MPLBACKEND", "Agg")
        rows = stage_figures(workspace, only)
        write_manifest(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
