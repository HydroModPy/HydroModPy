"""Step 0 - config validation.

Loads the TOML config (if a path is present in ``state.data["config_path"]``)
and instantiates the Pydantic ``HydroModPyConfig``. If ``state.data["cfg"]``
is already a Pydantic config, it is re-validated to ensure immutability.

The resolved configuration is then written beside the run's resume checkpoint,
in the workspace the pipeline says it owns a record in. It is the step's
product: the user TOML says a fraction of it, and everything downstream reads
the resolved form. The only frozen copy used to be written into the run
directory by ``prepare_solver``, step six, so a run that died while building
its model left none - and the digest the resume checkpoint carries pointed at
a document nobody held.

Inputs
------
``config_path`` : str or Path (optional if ``cfg`` already present)

Outputs
-------
``cfg`` : HydroModPyConfig
``config_path`` : Path
``<project_root>/.hmp/checkpoints/<run_id>/resolved_config.json``
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.workflow.internals.manifest import (
    resolved_config_path,
    state_config_payload,
    write_resolved_config,
)
from hydromodpy.workflow.internals.state import PipelineState


def _run_workspace_for(state: PipelineState) -> Path | None:
    """Return the workspace this run owns a record in, or None.

    The pipeline decides, never the config: a window that stops before
    ``setup_process`` registers no simulation and is handed no workspace, and a
    calibration prefix runs with none at all. Either of them writing where the
    config points would overwrite the documents of the run that carries the
    same name.
    """
    workspace = state.get("run_workspace")
    if workspace is None:
        return None
    path = Path(str(workspace))
    return path if path.is_dir() else None


def _export_field_names(export: object) -> list[tuple[str, str]]:
    """Return every (key, field name) the ``[export]`` section asks for.

    ``[export] variables`` and the ``var`` of each ``[[export.artifacts]]``
    entry name the same vocabulary, so both are checked. Two artifact kinds are
    left out on purpose: a ``csv`` artifact selects a timeseries column, a
    disjoint vocabulary the field registry does not hold, and an ``hmp``
    artifact packages the whole run and reads no variable at all.
    """
    from hydromodpy.core.config_kit.export_spec import ExportFormat

    named: list[tuple[str, str]] = []
    for name in getattr(export, "variables", ()) or ():
        named.append(("export.variables", str(name)))
    for index, artifact in enumerate(getattr(export, "artifacts", ()) or ()):
        if artifact.fmt in (ExportFormat.csv, ExportFormat.hmp):
            continue
        for name in artifact.var_list:
            named.append((f"export.artifacts[{index}].var", str(name)))
    return named


def _check_export_variables(cfg: object) -> None:
    """Refuse an ``[export]`` field name the field registry does not know.

    Step 0 is the earliest place the layer matrix lets a pipeline step read
    ``results``, and a typo costs nothing here: it is caught before the solve
    is paid for, instead of by the exporter once the run is over.
    """
    from hydromodpy.results import field_registry

    export = getattr(cfg, "export", None)
    if export is None:
        return
    unknown = [
        (key, name) for key, name in _export_field_names(export) if not field_registry.has(name)
    ]
    if not unknown:
        return
    available = ", ".join(field_registry.all_names())
    plural = "s" if len(unknown) > 1 else ""
    offenders = ", ".join(f"{name!r} ({key})" for key, name in unknown)
    raise ConfigError(
        f"unregistered export field{plural}: {offenders}. "
        f"Available fields: {available}. "
        "'hmp data export <project> --sim <name> --list' prints the ones a given run holds."
    )


def _export_time_indices(export: object) -> list[tuple[str, int]]:
    """Return every (key, integer timestep index) the ``[export]`` section asks for.

    ``[export] time`` and the ``time`` of each ``[[export.artifacts]]`` entry
    share one spelling, so both are collected. The string selectors and ``None``
    name a step without counting it and can never be out of range.
    """
    named: list[tuple[str, int]] = []
    selectors: list[tuple[str, object]] = [("export.time", getattr(export, "time", None))]
    for index, artifact in enumerate(getattr(export, "artifacts", ()) or ()):
        selectors.append((f"export.artifacts[{index}].time", getattr(artifact, "time", None)))
    for key, selector in selectors:
        values = selector if isinstance(selector, list) else [selector]
        named.extend((key, int(value)) for value in values if isinstance(value, int))
    return named


def _stress_period_count(cfg: object) -> int | None:
    """Return how many stress periods the run will hold, or None if undecidable.

    The store holds exactly one record per stress period, so the period count
    the canonical time grid derives from ``[simulation.time]`` is the length a
    timestep index is read against. ``None`` is returned rather than a guess
    whenever the grid does not resolve here: a run with no flow process, a
    config whose window is refused by another validator further down. A missed
    check costs the late error this one was added to replace; a wrong period
    count would refuse a run that is correct.
    """
    from hydromodpy.core.time import require_flow_simulation_time_grid

    try:
        grid = require_flow_simulation_time_grid(cfg)
    except ValueError:
        # The window itself is malformed. It has its own message, raised where
        # the grid is built for real; shadowing it here would say the wrong thing.
        return None
    if grid is None:
        return None
    nper = int(getattr(grid, "nper", 0))
    return nper if nper > 0 else None


def _check_export_timesteps(cfg: object) -> None:
    """Refuse an ``[export]`` timestep index the run has no stress period for.

    Sibling of :func:`_check_export_variables`, and for the same reason: an
    index past the end of the record is caught before the solve is paid for,
    instead of by the store reading a run that is already over.
    """
    export = getattr(cfg, "export", None)
    if export is None:
        return
    declared = _export_time_indices(export)
    if not declared:
        return
    nper = _stress_period_count(cfg)
    if nper is None:
        return
    out_of_range = [(key, index) for key, index in declared if not 0 <= index < nper]
    if not out_of_range:
        return
    plural = "es" if len(out_of_range) > 1 else ""
    offenders = ", ".join(f"{index} ({key})" for key, index in out_of_range)
    if nper == 1:
        simulation = getattr(cfg, "simulation", None)
        declared_window = getattr(simulation, "time", None) is not None
        source = (
            "[simulation.time] resolves to 1 stress period"
            if declared_window
            else "A steady run with no [simulation.time] holds one stress period"
        )
        allowed = "0 is the only index it holds"
    else:
        source = f"[simulation.time] resolves to {nper} stress periods"
        allowed = f"an index runs from 0 to {nper - 1}"
    raise ConfigError(
        f"export timestep index{plural} out of range: {offenders}. "
        f"{source}, so {allowed}. "
        "Write 'first', 'last' or 'all' to name a step without counting it, "
        "or an index inside that range."
    )


class ValidateStep:
    """Validate the config via Pydantic."""

    name = "validate"
    reads: ClassVar[tuple[str, ...]] = (
        "cfg",
        "config_path",
        "raw_toml",
        "run_workspace",
    )
    writes: ClassVar[tuple[str, ...]] = (
        "cfg",
        "config_path",
    )
    config_sections: ClassVar[tuple[str, ...]] = ("workspace", "simulation")

    def depends_on(self) -> tuple[str, ...]:
        return ()

    def rebuild_state(
        self,
        *,
        prior_state: PipelineState,
        workspace: Path,
        run_id: str,
    ) -> PipelineState:
        """Re-run validation: idempotent, and it rewrites what it resolved."""
        return self.run(prior_state)

    def artifacts(self, state_out: PipelineState) -> tuple[str, ...]:
        """Return the resolved configuration this step wrote, when it wrote one."""
        workspace = _run_workspace_for(state_out)
        if workspace is None:
            return ()
        path = resolved_config_path(workspace, state_out.run_id)
        return (str(path),) if path.is_file() else ()

    def run(self, state: PipelineState) -> PipelineState:
        from hydromodpy.config import HydroModPyConfig

        cfg = state.get("cfg")
        config_path = state.get("config_path")

        if cfg is None:
            if config_path is None:
                raise ConfigError("ValidateStep requires 'cfg' or 'config_path' in state.data")
            path = Path(config_path).expanduser().resolve()
            cfg = HydroModPyConfig.from_toml(path)
            config_path = path
        elif not isinstance(cfg, HydroModPyConfig):
            cfg = HydroModPyConfig.model_validate(cfg)

        _check_export_variables(cfg)
        _check_export_timesteps(cfg)

        out = state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            cfg=cfg,
            config_path=Path(config_path) if config_path is not None else None,
        )
        workspace = _run_workspace_for(out)
        if workspace is not None:
            write_resolved_config(workspace, out.run_id, state_config_payload(out))
        return out
