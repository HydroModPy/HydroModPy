"""``rerun`` of MODFLOW 6: solve a model again for a new K or Sy, without a build.

A calibration trial changes K or Sy of one ``Model`` between two solves. A
build would make every FloPy object again and write every input file. A rerun
takes the solved run before it, copies its input files into the folder of the
new slot, and rewrites only the packages the change touches: NPF and DRN for K,
STO for Sy, and the file of the properties the extractor reads. DISV, IC, RCHA,
CHD, OC, TDIS, IMS, LAK, SFR, MVR and the soil files stay the copied ones.

A package is rewritten when its new value differs from what the solver object
holds, not when the parameter says so: the object of a chain of reruns holds
the values of the last one. The result is bit-identical to a build of the same
``Model``: the input files are equal once the FloPy header line is set aside,
and the head and budget files are equal byte for byte.

A rerun consumes the run it starts from. The solver object of ``previous`` is
changed in place and then describes the new run, so only the returned
``SolverRun`` serves as a parent afterwards. The files keep the names of the
first build: the extractor finds them by their ``.hds``, never by the slot.

``plan_rerun`` checks everything before anything is touched, and says why a
rerun is refused. A refusal is no error: the runner builds instead.

It returns ``None``, and the runner builds, in five cases. The earlier run is not
solved, not written, or no longer owns its solver model. The model starts from a steady
or a cyclic solve, which depend on K and Sy. The change turns XT3D on or off, which
changes IMS and HFB. The drain cells or the MVR lines are no longer the ones of the
earlier run. The simulation of the earlier run carries a model other than the GWF flow,
because a rerun that copied it would solve a transport again without saying so.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.model.initial.state import HeadRule, PriorState
from hydromodpy.model.properties.property_table import require_positive_storage
from hydromodpy.solver.base.plan import RunSlot, SolverRun
from hydromodpy.solver.base.rerun import changed_properties
from hydromodpy.solver.modflow6.build import (
    FLOW_PROPERTY_FIELDS,
    _save_flow_property_sidecar,
    flow_property_fields,
)
from hydromodpy.solver.modflow6.builders.boundary_conditions import (
    build_drain_stress_period_data,
)
from hydromodpy.solver.modflow6.builders.sfr import remove_drain_cells
from hydromodpy.solver.modflow6.builders.solver_options import (
    k_tensor_is_off_axis,
    xt3d_requested_value,
)
from hydromodpy.solver.modflow6.support.property_mapping import k_tensor_npf_kwargs

logger = get_logger(__name__)

NPF_FIELDS: tuple[str, ...] = ("hk", "k33", "k22", "angle1", "angle2", "angle3")
"""The solver attributes NPF writes. A change of one rewrites NPF."""

STO_FIELDS: tuple[str, ...] = ("sy", "ss")
"""The solver attributes STO writes. A change of one rewrites STO."""

RERUN_STARTS: tuple[type, ...] = (HeadRule, PriorState)
"""The initial states a rerun keeps. A steady or cyclic start solves a model that depends on K and Sy."""


@dataclass(frozen=True)
class RerunPlan:
    """What a rerun rewrites, or why it is refused.

    ``refusal`` is ``None`` when the rerun can go, and then ``fields`` holds the
    per-cell arrays of the new ``Model`` (``FLOW_PROPERTY_FIELDS``), ``npf`` and
    ``sto`` name the attributes whose values change, and ``drain`` holds the new
    DRN rows when the drain conductance follows K and changes.
    """

    refusal: str | None = None
    fields: Mapping[str, np.ndarray | None] = field(default_factory=dict)
    npf: frozenset[str] = frozenset()
    sto: frozenset[str] = frozenset()
    drain: Mapping[int, list[list[float]]] | None = None


class _WithFields:
    """The solver object seen with the new per-cell arrays, for a builder that reads them.

    Reading an attribute of ``fields`` returns the new array, any other the one
    of the solver. Writing stays on this view, so a builder that marks the
    object leaves the solver untouched.
    """

    def __init__(self, solver: Any, fields: Mapping[str, np.ndarray | None]) -> None:
        self._solver = solver
        self._fields = fields

    def __getattr__(self, name: str) -> Any:
        fields = self.__dict__["_fields"]
        if name in fields:
            return fields[name]
        return getattr(self.__dict__["_solver"], name)


def _same(left: Any, right: Any) -> bool:
    """Whether two per-cell arrays are equal, ``None`` equal only to ``None``."""
    if left is None or right is None:
        return left is None and right is None
    return bool(np.array_equal(np.asarray(left), np.asarray(right)))


def _resolved(path: str | os.PathLike[str]) -> Path:
    return Path(path).resolve()


def _refusal_of_the_run(previous: SolverRun, model: Any, slot: RunSlot) -> str | None:
    """Why the run ``previous`` cannot serve as a parent of ``model`` in ``slot``, or None."""
    solver = previous.solver_model
    if solver is None or previous.output_dir is None:
        return "the previous run holds no solver model and no output folder"
    if not (previous.written and previous.solved):
        return "the previous run is not solved"
    if getattr(solver, "inputs", None) is not previous.model:
        return "the solver model no longer describes the previous run, a rerun consumed it"
    sim = getattr(solver, "sim", None)
    if sim is None or _resolved(sim.sim_path) != _resolved(previous.output_dir):
        return "the solver model no longer writes into the folder of the previous run"
    if len(getattr(sim, "model_names", ())) > 1:
        return "the simulation of the previous run was solved more than once"
    if not previous.input_files:
        return "the previous run lists no input files"
    missing = [name for name in previous.input_files if not (previous.output_dir / name).is_file()]
    if missing:
        return f"{len(missing)} input files of the previous run are gone, {missing[0]} first"
    if slot.shared_forcing_dir != previous.slot.shared_forcing_dir:
        return "the shared forcing folder of the slot is not the one the input files name"
    if slot.bin_dir != previous.slot.bin_dir:
        return "the binaries of the slot are not the ones of the previous run"
    if not isinstance(model.initial, RERUN_STARTS):
        return (
            f"the run starts from a {type(model.initial).__name__}, a solve that depends "
            "on K and Sy"
        )
    return None


def _refusal_of_the_change(previous: SolverRun, model: Any, mutable: frozenset[str]) -> str | None:
    """Why the change from ``previous.model`` to ``model`` needs a build, or None."""
    changed = changed_properties(previous.model, model)
    if changed is None:
        return "a member of the Model other than its properties changes"
    outside = sorted(changed - mutable)
    if outside:
        return f"{', '.join(outside)} change, and only {', '.join(sorted(mutable))} can"
    return None


def _xt3d_switches(solver: Any, fields: Mapping[str, np.ndarray | None]) -> bool:
    """Whether the new K turns XT3D on or off.

    An XT3D written in the options holds whatever K is. Otherwise K takes part
    in the automatic choice only through the check that K22 differs from K off
    the axes of the grid; every other input of the choice stays.
    """
    if xt3d_requested_value(solver) is not None:
        return False
    mesh = solver._property_mesh
    return k_tensor_is_off_axis(_WithFields(solver, fields), mesh) != k_tensor_is_off_axis(
        solver, mesh
    )


def _drain_rows(solver: Any, fields: Mapping[str, np.ndarray | None]) -> dict[int, list]:
    """The DRN rows a build would write with the new K, the dropped cells dropped."""
    rows = build_drain_stress_period_data(
        _WithFields(solver, fields),
        solver_mesh=solver.solver_mesh,
        drainage_cond_series=np.asarray(solver._drainage_cond_series, dtype=float),
        ocean_support_mask=np.asarray(solver._ocean_support_mask, dtype=bool),
        stream_support_mask=np.asarray(solver._stream_support_mask, dtype=bool),
    )
    return remove_drain_cells(rows, cells=set(solver._drain_dropped_cells))


def _held_drain_rows(drn: Any) -> dict[int, list[tuple]]:
    """The DRN rows the package holds, as ``(layer, cell, elevation, conductance)``."""
    held: dict[int, list[tuple]] = {}
    for kper, records in (drn.stress_period_data.get_data() or {}).items():
        if records is None:
            continue
        held[int(kper)] = [
            (int(row["cellid"][0]), int(row["cellid"][1]), float(row["elev"]), float(row["cond"]))
            for row in records
        ]
    return held


def _drain_change(solver: Any, fields: Mapping[str, np.ndarray | None]) -> tuple[str | None, Any]:
    """Return ``(refusal, rows)``: the new DRN rows when they change, ``None`` when they do not.

    The rows a K reaches are the conductances of the drains whose conductance
    follows K. Their cells and the mover lines that index them must stay those
    of the previous run, or the change needs a build.
    """
    drn = getattr(solver, "drn", None)
    if drn is None or not getattr(solver, "_drainage_uses_hk", False):
        return None, None
    rows = _drain_rows(solver, fields)
    held = _held_drain_rows(drn)
    if sorted(rows) != sorted(held):
        return "the stress periods of the drains change", None
    for kper, period_rows in rows.items():
        cells = [(int(row[0]), int(row[1])) for row in period_rows]
        if cells != [(layer, cell) for layer, cell, _, _ in held[kper]]:
            return "the drain cells change, and the movers index them", None
    unchanged = all(
        [(float(row[2]), float(row[3])) for row in rows[kper]]
        == [(elevation, conductance) for _, _, elevation, conductance in held[kper]]
        for kper in rows
    )
    return None, None if unchanged else rows


def plan_rerun(
    previous: SolverRun, model: Any, slot: RunSlot, *, mutable: frozenset[str]
) -> RerunPlan:
    """Check that ``model`` can be solved from ``previous`` in ``slot``, and say what to rewrite.

    A rerun is refused when the previous run is not solved, its solver model
    no longer describes it or its input files are gone, when the slot takes
    other binaries or another shared forcing folder, when the run starts from a
    steady or cyclic solve, when a member of the ``Model`` other than the
    properties ``mutable`` names changes, when the new K turns XT3D on or off,
    and when the drain cells change. Nothing is touched: the solver object, the
    folders and the files stay as they were.
    """
    refusal = _refusal_of_the_run(previous, model, slot) or _refusal_of_the_change(
        previous, model, mutable
    )
    if refusal is not None:
        return RerunPlan(refusal=refusal)
    solver = previous.solver_model
    fields = flow_property_fields(solver, model, solver._property_mesh)
    toggled = [
        name for name in NPF_FIELDS if (fields[name] is None) != (getattr(solver, name) is None)
    ]
    if toggled:
        return RerunPlan(refusal=f"the K tensor gains or loses {', '.join(toggled)}")
    npf = frozenset(name for name in NPF_FIELDS if not _same(fields[name], getattr(solver, name)))
    sto = frozenset(name for name in STO_FIELDS if not _same(fields[name], getattr(solver, name)))
    if npf and _xt3d_switches(solver, fields):
        return RerunPlan(refusal="the new K turns XT3D on or off, which changes IMS and HFB")
    refusal, drain = _drain_change(solver, fields) if "hk" in npf else (None, None)
    if refusal is not None:
        return RerunPlan(refusal=refusal)
    if sto:
        steady = [bool(solver.steady[i]) for i in range(int(solver.nper))]
        require_positive_storage(
            fields["sy"],
            fields["ss"],
            active_mask=solver.solver_mesh.idomain > 0,
            iconvert=np.ones((solver.nlay,), dtype=int),
            steady=steady,
            profiles=model.properties.profiles,
        )
    return RerunPlan(fields=fields, npf=npf, sto=sto, drain=drain)


def _copy_input_files(previous: SolverRun, directory: Path) -> None:
    """Copy the input files of ``previous`` into ``directory``, under their names."""
    source = Path(previous.output_dir)
    if _resolved(source) == _resolved(directory):
        return
    for name in previous.input_files:
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, target)


def _move_to(solver: Any, slot: RunSlot) -> None:
    """Point the solver object and its simulation at the folder of ``slot``.

    The model name stays the one of the first build, so the file names do not
    change. A path the build left inside the old folder follows the files.
    """
    old = os.fspath(solver.full_path)
    new = os.fspath(slot.directory)
    solver.model_folder = slot.folder
    solver.full_path = new
    solver.slot = slot
    solver.sim.set_sim_path(new)
    template = getattr(solver, "dem_watershed_path", None)
    if template and os.path.dirname(os.fspath(template)) == old:
        solver.dem_watershed_path = os.path.join(new, os.path.basename(os.fspath(template)))
    grid_ctx = getattr(solver, "grid_ctx", None)
    raster = getattr(grid_ctx, "template_raster_path", None)
    if raster and os.path.dirname(os.fspath(raster)) == old:
        grid_ctx.template_raster_path = os.path.join(new, os.path.basename(os.fspath(raster)))


def _rewrite(solver: Any, plan: RerunPlan) -> None:
    """Set the new values on the solver object and write the packages they change."""
    if plan.npf:
        held = {"k": solver.hk, "k33": solver.k33, **k_tensor_npf_kwargs(solver)}
        for name in plan.npf:
            setattr(solver, name, plan.fields[name])
        wanted = {"k": solver.hk, "k33": solver.k33, **k_tensor_npf_kwargs(solver)}
        for name, values in wanted.items():
            if not _same(values, held.get(name)):
                getattr(solver.npf, name).set_data(values)
        solver.npf.write()
    if plan.drain is not None:
        solver.drn.stress_period_data.set_data(dict(plan.drain))
        solver.drn.write()
    if plan.sto:
        for name in plan.sto:
            setattr(solver, name, plan.fields[name])
            getattr(solver.sto, name).set_data(plan.fields[name])
        solver.sto.write()
    if plan.npf or plan.sto:
        _save_flow_property_sidecar(solver)


def rerun_modflow6(
    previous: SolverRun, model: Any, slot: RunSlot, *, mutable: frozenset[str]
) -> SolverRun | None:
    """Return the run of ``model`` in ``slot``, rewritten from ``previous``, or ``None``.

    ``None`` means the change needs a build, and nothing was touched (see
    :func:`plan_rerun`). Otherwise the input files of ``previous`` are copied
    into ``slot.directory``, the solver object moves there and takes ``model``,
    and the packages the change reaches are written. The run returned has
    ``written`` true and ``solved`` false, lists the same input files, and is
    solved by ``run``, which writes nothing more.

    A rerun refuses a run whose simulation was solved a second time by a
    transport run: after GWT or PRT solve in the same folder, the simulation of
    ``previous`` carries packages no build of this adapter wrote, and a reprise
    would relaunch the transports without saying so. The previous run is then
    left untouched and the runner builds instead.
    """
    solver = previous.solver_model
    if solver is None:
        logger.debug("MODFLOW 6 builds run %r instead of a rerun: no solver model.", slot.name)
        return None
    plan = plan_rerun(previous, model, slot, mutable=mutable)
    if plan.refusal is not None:
        logger.debug("MODFLOW 6 builds run %r instead of a rerun: %s.", slot.name, plan.refusal)
        return None
    solver = previous.solver_model
    _copy_input_files(previous, slot.directory)
    _move_to(solver, slot)
    _rewrite(solver, plan)
    solver.inputs = model
    solver.input_files = tuple(previous.input_files)
    return SolverRun(
        slot=slot,
        model=model,
        options=previous.options,
        solver_model=solver,
        input_files=previous.input_files,
        written=True,
        solved=False,
    )


__all__ = [
    "FLOW_PROPERTY_FIELDS",
    "NPF_FIELDS",
    "RERUN_STARTS",
    "STO_FIELDS",
    "RerunPlan",
    "plan_rerun",
    "rerun_modflow6",
]
