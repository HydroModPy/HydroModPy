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
from typing import Any, ClassVar

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


def _time_grid(cfg: object) -> tuple[Any, int] | None:
    """Return the period edges and the period count of the run, or None if undecidable.

    The store holds one record per stress period, so the grid
    ``[simulation.time]`` resolves to is what a date or an index is read
    against. ``None`` is returned rather than a guess when the grid does not
    resolve here: a config whose window is refused by another validator
    further down. A missed check costs a late error; a wrong grid would refuse
    a run that is correct.
    """
    from hydromodpy.core.time import grid_edges, require_flow_simulation_time_grid

    try:
        grid = require_flow_simulation_time_grid(cfg)
    except ValueError:
        # The window itself is malformed. It has its own message, raised where
        # the grid is built for real; shadowing it here would say the wrong thing.
        return None
    if grid is None:
        return None
    nper = int(getattr(grid, "nper", 0))
    if nper < 1:
        return None
    return grid_edges(grid), nper


def _time_selectors(cfg: object) -> list[tuple[str, str, Any]]:
    """Return every ``(where, kind, selector)`` a config reads a time with.

    ``kind`` is ``"instant"`` for one selector and ``"period"`` for a
    ``(start, end)`` pair. The ``[[export]]`` blocks give ``time`` and
    ``period``; ``[display]`` gives ``time``, and so can the options of each
    figure under ``[display.overrides.<figure>]``.
    """
    selectors: list[tuple[str, str, Any]] = []
    for index, request in enumerate(getattr(cfg, "export", None) or ()):
        selectors.extend((f"export[{index}].time", "instant", item) for item in request.times)
        if request.period is not None:
            selectors.append((f"export[{index}].period", "period", request.period))
    display = getattr(cfg, "display", None)
    display_time = getattr(display, "time", None)
    if display_time is not None:
        selectors.append(("display.time", "instant", display_time))
    for figure, options in (getattr(display, "overrides", None) or {}).items():
        if isinstance(options, dict) and options.get("time") is not None:
            selectors.append((f"display.overrides.{figure}.time", "instant", options["time"]))
    return selectors


def check_time_selectors(cfg: object) -> None:
    """Refuse a date or a step the run will not hold.

    Reads every time selector of ``[[export]]`` and ``[display]`` against the
    stress periods ``[simulation.time]`` resolves to: a date outside the
    record, a date on a steady run without a window, a step index past the
    end. Run by step 0 of ``hmp run`` and by ``hmp config check``, so the
    mistake costs nothing: no solve is paid for before it is caught.
    """
    from hydromodpy.core.time import TimeSelectionError, resolve_instant, resolve_period

    selectors = _time_selectors(cfg)
    if not selectors:
        return
    grid = _time_grid(cfg)
    if grid is None:
        return
    edges, nper = grid
    count = None if edges is not None else nper
    refused: list[str] = []
    for where, kind, selector in selectors:
        try:
            if kind == "period":
                resolve_period(selector[0], selector[1], edges, n_periods=count)
            else:
                resolve_instant(selector, edges, n_periods=count)
        except TimeSelectionError as exc:
            refused.append(f"  {where}: {exc}")
    if refused:
        raise ConfigError(
            "a time names no stress period of this run "
            f"([simulation.time] resolves to {nper} period{'s' if nper > 1 else ''}):\n"
            + "\n".join(refused)
        )


def _run_label(cfg: object) -> str:
    """Return the name the run's exports are filed under."""
    simulation = getattr(cfg, "simulation", None)
    return str(getattr(simulation, "name", "") or "run")


def check_export_variables(cfg: object) -> None:
    """Refuse an ``[[export]]`` block that cannot be written.

    Every name is looked up in the vocabulary of what a run can export, and
    each block is planned file by file with the kind of each name. A name no
    run can hold, a kind the format cannot carry, a ``crs`` or ``resolution``
    no file takes, a ``file`` that would be several files, and two blocks
    writing one file are refused, each naming its block (``export[2]``).
    Step 0 is the earliest place the layer matrix lets a pipeline step read
    ``results``, and ``hmp config check`` runs it too.
    """
    from hydromodpy.core.config_kit.export_spec import plan_outputs
    from hydromodpy.results.exporters.vocabulary import describe_export_names, export_kind

    requests = list(getattr(cfg, "export", None) or ())
    if not requests:
        return
    unknown = [
        f"export[{index}]: {name!r}"
        for index, request in enumerate(requests)
        for name in request.names
        if export_kind(name) is None
    ]
    if unknown:
        raise ConfigError(
            f"no run can export {', '.join(unknown)}. The names a run can export:\n"
            f"{describe_export_names()}\n"
            "'hmp export <run> --list' prints the ones a given run holds."
        )
    label = _run_label(cfg)
    writers: dict[str, int] = {}
    for index, request in enumerate(requests):
        kinds = {name: export_kind(name) for name in request.names}
        try:
            planned = plan_outputs(request, kinds, run_label=label)
        except ValueError as exc:
            raise ConfigError(f"export[{index}]: {exc}") from None
        for item in planned:
            path = str(item.path)
            first = writers.setdefault(path, index)
            if first != index:
                raise ConfigError(
                    f"export[{first}] and export[{index}] both write {path}. Give one of "
                    "them its own file or folder."
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

        check_export_variables(cfg)
        check_time_selectors(cfg)

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
