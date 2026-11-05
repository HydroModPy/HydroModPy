"""Checks of the time selectors and export variables of a configuration.

Pure validation of ``[[export]]`` and ``[display]`` against what the run will
hold, run by step 0 of ``hmp run`` and by ``hmp config check``, so a mistake
costs nothing: no solve is paid for before it is caught.
"""

from __future__ import annotations

from typing import Any

from hydromodpy.core.exceptions import ConfigError


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

    ``kind`` is ``"instant"`` for one selector, ``"dates"`` for a list of them
    and ``"period"`` for a ``(start, end)`` pair. The ``[[export]]`` blocks give
    ``time`` and ``period``; ``[display]`` gives ``time``, and so can the options
    of each figure under ``[display.overrides.<figure>]``.
    """
    selectors: list[tuple[str, str, Any]] = []
    for index, request in enumerate(getattr(cfg, "export", None) or ()):
        selectors.append((f"export[{index}].time", "dates", request.times))
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
    end, two dates of one list that read the same period. Run by step 0 of ``hmp run`` and by ``hmp config check``, so the
    mistake costs nothing: no solve is paid for before it is caught.
    """
    from hydromodpy.core.time import (
        TimeSelectionError,
        resolve_instant,
        resolve_instants,
        resolve_period,
    )

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
            elif kind == "dates":
                resolve_instants(selector, edges, n_periods=count)
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
    from hydromodpy.results.exporters.export_spec import plan_outputs
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


__all__ = ["check_export_variables", "check_time_selectors"]
