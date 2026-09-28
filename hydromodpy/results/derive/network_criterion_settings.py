"""The network criterion settings a run was scored with, read back from its sealed config.

A figure of the stream network redraws the partition a trial scored. The trial
cut it by the settings of its ``[calibration.outputs.<n>]`` network output: the
seepage threshold, the neighbour graph, the rasterisation of the map, the
weighting and, in the two-bound mode, the extent rules and the years its
``scoring_window`` holds. A figure drawn with the defaults instead shows
another partition than the one the numbers describe, so this module reads
those settings from the configuration the run sealed.

The results layer may not import the calibration layer, so the output is read
as the plain mapping the snapshot holds, with the defaults of
:mod:`hydromodpy.core.stream_criterion_defaults` and
:mod:`hydromodpy.core.stream_extent` where a key is absent. A run that sealed
no network output reads the defaults, and says so.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import pandas as pd

from hydromodpy.core.logging import get_logger
from hydromodpy.core.stream_criterion_defaults import (
    STREAM_CRITERION_DEFAULTS,
    ObservedRasterization,
)
from hydromodpy.core.stream_extent import DEFAULT_VISIBLE_FLOW, parse_visible_flow
from hydromodpy.core.stream_snap import SnapStreamsConfig
from hydromodpy.core.units.length import parse_to_m
from hydromodpy.results.derive.snapped_network import snap_settings_of_run

if TYPE_CHECKING:
    from hydromodpy.results.run import Run

logger = get_logger(__name__)

__all__ = (
    "DEFAULT_CRITERION_SETTINGS",
    "DEFAULT_EXTENT_RULES",
    "NetworkCriterionSettings",
    "NetworkExtentRules",
    "ScoringWindow",
    "network_criterion_settings",
    "network_outputs_of_run",
)

_NETWORK_SUPPORT = "network"
_RASTERIZATIONS = ("crossing", "touch")
_WEIGHTINGS = ("cell", "area")
_TIMESTEP_OF_TIME = {"last": -1, "first": 0}
"""The state a single-state output reads, as the timestep index a run field takes."""

_MISSING_SNAPSHOT = (KeyError, ValueError, FileNotFoundError, RuntimeError)

ScoringWindow = tuple[pd.Timestamp | None, pd.Timestamp | None]
"""The ``(start, end)`` of a scoring window, naive, either bound None when open."""


@dataclass(frozen=True, slots=True)
class NetworkExtentRules:
    """The rules of ``[calibration.outputs.<n>.extent]``, with its defaults."""

    maximal_flowing_steps: int = 1
    minimal_dry_steps: int = 1
    year_quorum: float = 0.5
    visible_flow: str = DEFAULT_VISIBLE_FLOW


DEFAULT_EXTENT_RULES = NetworkExtentRules()
"""The extent rules a figure reads a run with when the run sealed none."""


@dataclass(frozen=True, slots=True)
class NetworkCriterionSettings:
    """What one network output cut its partition by, or the defaults."""

    output: str | None
    """Name of the calibration output read, None for the defaults."""

    tau_specific_ratio: float = STREAM_CRITERION_DEFAULTS.tau_specific_ratio
    diagonal_neighbors: bool = STREAM_CRITERION_DEFAULTS.diagonal_neighbors
    observed_rasterization: ObservedRasterization = STREAM_CRITERION_DEFAULTS.observed_rasterization
    weighting: Literal["cell", "area"] = "cell"
    observed_position_accuracy_m: float | None = None
    timestep: int = -1
    """The state a single-state output reads: ``-1`` for ``last``, ``0`` for ``first``."""

    extent: NetworkExtentRules | None = None
    """The two-bound rules, None when the output reads one state."""

    n_network_outputs: int = 0
    """How many network outputs the run sealed: more than one means a choice was made."""

    scoring_window: ScoringWindow | None = None
    """The ``[calibration] scoring_window`` the run sealed, None when it sealed none.

    The two-bound mode scores only the complete years it holds: a spin-up year
    outside it is left out of the extents and of the year quorum.
    """

    snap: SnapStreamsConfig | None = field(default=None, compare=False)
    """The ``[geographic.snap_streams]`` setting the run sealed, None when off."""

    @property
    def extent_rules(self) -> NetworkExtentRules:
        """Return the extent rules of the output, or the defaults."""
        return DEFAULT_EXTENT_RULES if self.extent is None else self.extent

    def note(self) -> str:
        """Say where the settings on the page come from, for a figure note."""
        if self.output is None:
            source = "criterion settings: the defaults, this run sealed no network output"
        elif self.n_network_outputs > 1:
            source = (
                f"criterion settings: calibration output {self.output!r}, "
                f"one of {self.n_network_outputs} network outputs"
            )
        else:
            source = f"criterion settings: calibration output {self.output!r}"
        if self.snap is not None:
            source += f", snap_streams {self.snap.mode}"
        if self.scoring_window is not None:
            start, end = self.scoring_window
            source += f", scoring_window {_date_or_open(start)} to {_date_or_open(end)}"
        return source


def _date_or_open(bound: pd.Timestamp | None) -> str:
    """Return one bound of a scoring window for a note."""
    return "open" if bound is None else bound.date().isoformat()


DEFAULT_CRITERION_SETTINGS = NetworkCriterionSettings(output=None)
"""The settings of a run that sealed no network output."""


def network_outputs_of_run(sim: Run) -> dict[str, Mapping[str, Any]]:
    """Return the network outputs a run sealed, by name, in declaration order."""
    outputs = _calibration_section(sim).get("outputs")
    if not isinstance(outputs, Mapping):
        return {}
    return {
        str(name): payload
        for name, payload in outputs.items()
        if isinstance(payload, Mapping) and payload.get("support") == _NETWORK_SUPPORT
    }


def _calibration_section(sim: Run) -> Mapping[str, Any]:
    """Return the ``[calibration]`` table a run sealed, empty when it sealed none."""
    try:
        snapshot = getattr(sim, "config_snapshot", None)
    except _MISSING_SNAPSHOT as exc:
        logger.debug("Run %s: no configuration snapshot (%s).", getattr(sim, "sim_id", "?"), exc)
        return {}
    if not isinstance(snapshot, Mapping):
        return {}
    calibration = snapshot.get("calibration")
    return calibration if isinstance(calibration, Mapping) else {}


def network_criterion_settings(sim: Run, *, output: str | None = None) -> NetworkCriterionSettings:
    """Return the settings the run's network output was scored with.

    ``output`` names the calibration output to read. Left None, the run's only
    network output is read, or its first one when it sealed several, and the
    note says so. A run that sealed none reads the defaults. A named output the
    run does not hold is refused, and so is a sealed value no trial could have
    read.
    """
    outputs = network_outputs_of_run(sim)
    snap = snap_settings_of_run(sim)
    window = _scoring_window(_calibration_section(sim).get("scoring_window"))
    if output is not None and output not in outputs:
        held = ", ".join(repr(name) for name in outputs) or "none"
        raise ValueError(
            f"run {getattr(sim, 'sim_id', '?')} sealed no network output {output!r} "
            f"(network outputs: {held})."
        )
    if not outputs:
        return NetworkCriterionSettings(output=None, snap=snap)
    name = next(iter(outputs)) if output is None else output
    return _settings_of_output(
        name, outputs[name], n_outputs=len(outputs), snap=snap, scoring_window=window
    )


def _settings_of_output(
    name: str,
    payload: Mapping[str, Any],
    *,
    n_outputs: int,
    snap: SnapStreamsConfig | None,
    scoring_window: ScoringWindow | None,
) -> NetworkCriterionSettings:
    """Read one sealed network output, with the defaults for an absent key."""
    where = f"calibration output {name!r}"
    defaults = DEFAULT_CRITERION_SETTINGS
    tau = float(payload.get("tau_specific_ratio", defaults.tau_specific_ratio))
    if not tau >= 0.0:
        raise ValueError(f"{where}: tau_specific_ratio must be positive, got {tau!r}.")
    rasterization = payload.get("observed_rasterization", defaults.observed_rasterization)
    if rasterization not in _RASTERIZATIONS:
        raise ValueError(f"{where}: unknown observed_rasterization {rasterization!r}.")
    weighting = payload.get("weighting", defaults.weighting)
    if weighting not in _WEIGHTINGS:
        raise ValueError(f"{where}: unknown weighting {weighting!r}.")
    time = payload.get("time", "last")
    if time not in _TIMESTEP_OF_TIME:
        raise ValueError(f"{where}: a network output reads 'last' or 'first', got {time!r}.")
    return NetworkCriterionSettings(
        output=name,
        tau_specific_ratio=tau,
        diagonal_neighbors=bool(payload.get("diagonal_neighbors", defaults.diagonal_neighbors)),
        observed_rasterization=rasterization,
        weighting=weighting,
        observed_position_accuracy_m=_accuracy_m(
            payload.get("observed_position_accuracy"), where=where
        ),
        timestep=_TIMESTEP_OF_TIME[time],
        extent=_extent_rules(payload.get("extent"), where=where),
        n_network_outputs=n_outputs,
        snap=snap,
        scoring_window=scoring_window,
    )


def _accuracy_m(value: Any, *, where: str) -> float | None:
    """Return a sealed positional accuracy in metres, or None when unset.

    A snapshot dumps a length as its magnitude in metres; a hand-written
    mapping may still carry its unit.
    """
    if value is None:
        return None
    metres, _ = parse_to_m(value, location=f"{where}.observed_position_accuracy")
    return float(metres)


def _extent_rules(payload: Any, *, where: str) -> NetworkExtentRules | None:
    """Return the sealed extent rules, or None for a single-state output."""
    if payload is None:
        return None
    if not isinstance(payload, Mapping):
        raise ValueError(f"{where}: the extent table is not a mapping, got {payload!r}.")
    defaults = DEFAULT_EXTENT_RULES
    visible = str(payload.get("visible_flow", defaults.visible_flow))
    parse_visible_flow(visible)
    return NetworkExtentRules(
        maximal_flowing_steps=int(
            payload.get("maximal_flowing_steps", defaults.maximal_flowing_steps)
        ),
        minimal_dry_steps=int(payload.get("minimal_dry_steps", defaults.minimal_dry_steps)),
        year_quorum=float(payload.get("year_quorum", defaults.year_quorum)),
        visible_flow=visible,
    )


def _scoring_window(payload: Any) -> ScoringWindow | None:
    """Return the sealed scoring window as naive timestamps, or None when unset.

    A zoned bound keeps its wall clock, the clock
    :func:`hydromodpy.results.derive.stream_extent.run_step_edges` reads a run
    on. A window with both bounds open is no window.
    """
    if payload is None:
        return None
    where = "calibration.scoring_window"
    if not isinstance(payload, Mapping):
        raise ValueError(f"{where} is not a mapping, got {payload!r}.")
    bounds: list[pd.Timestamp | None] = []
    for key in ("start", "end"):
        raw = payload.get(key)
        if raw is None:
            bounds.append(None)
            continue
        try:
            stamp = pd.Timestamp(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{where}.{key} {raw!r} is not a date.") from exc
        bounds.append(stamp.tz_localize(None) if stamp.tz is not None else stamp)
    if bounds[0] is None and bounds[1] is None:
        return None
    return (bounds[0], bounds[1])
