"""SFR PERIOD forcings and the per-reach OBS6 spec.

Private helpers behind the public ``build_sfr_period_data`` / ``build_sfr_obs_spec``
re-exported from ``builders.sfr``: the per-network forcing distribution (inflow,
runoff, rainfall, evaporation) with the inline-vs-TS6 arbitration, and the
continuous observation request the extractor re-keys per reach.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from hydromodpy.physics.flow.time_forcing import resolve_period_values_from_forcing
from hydromodpy.solver.modflow6.builders.period_forcing import (
    constant_forcing_value,
    forcing_to_si,
    forcing_unit,
    resolve_forcing_mode,
    resolve_use_ts6,
    ts6_times_and_values,
)
from hydromodpy.solver.modflow6.common.time_series import Ts6Series

if TYPE_CHECKING:
    from hydromodpy.solver.modflow6.builders.sfr import ResolvedSfrNetwork, SfrReachRecord

# (keyword, config field, volumetric) for the per-network forcings. Volumetric
# forcings [m3/s] are distributed over their target reaches; rates [m/s] apply
# uniformly per reach.
_SFR_FORCINGS: tuple[tuple[str, str, bool], ...] = (
    ("inflow", "headwater_inflow", True),
    ("runoff", "runoff", True),
    ("rainfall", "rainfall", False),
    ("evaporation", "evaporation", False),
)


def build_sfr_period_data(
    model,
    *,
    network: ResolvedSfrNetwork,
) -> tuple[dict[int, list[list[Any]]], list[Ts6Series]]:
    """Build the SFR PERIOD rows and any external TS6 series for the forcings.

    ``headwater_inflow`` lands on the headwater reaches, split by drainage area
    (equally when areas are unknown). ``runoff`` is distributed over every reach
    by length fraction. ``rainfall`` / ``evaporation`` are rates applied to every
    reach unscaled. Constant forcings emit inline period-0 rows; non-constant
    forcings follow the shared TS6-vs-inline arbitration (`resolve_use_ts6`),
    with one pre-scaled TS6 series per reach when the distribution is uneven.
    """
    definition = network.definition
    reaches = network.reaches
    mode, min_periods = resolve_forcing_mode(model)
    nper = int(getattr(model, "nper", 0) or 0)
    period_rows: dict[int, list[list[Any]]] = {}
    ts_series: list[Ts6Series] = []
    location_root = f"flow.sinks_sources.sfr.{network.network_id}"

    for keyword, field, volumetric in _SFR_FORCINGS:
        forcing = definition.get(field)
        if forcing is None:
            continue
        targets = _forcing_targets(keyword, reaches)
        if not targets:
            continue
        _emit_network_forcing(
            model,
            keyword=keyword,
            forcing=forcing,
            volumetric=volumetric,
            targets=targets,
            location=f"{location_root}.{field}",
            mode=mode,
            min_periods=min_periods,
            nper=nper,
            period_rows=period_rows,
            ts_series=ts_series,
        )
    return period_rows, ts_series


def _forcing_targets(keyword: str, reaches: Sequence[SfrReachRecord]) -> dict[int, float]:
    """Return ``{ifno: scale}`` for one forcing keyword."""
    if keyword == "inflow":
        headwaters = [record for record in reaches if record.is_headwater]
        if not headwaters:
            headwaters = [record for record in reaches if not record.upstream]
        total_area = sum(record.area_km2 for record in headwaters)
        if total_area > 0.0:
            return {record.ifno: record.area_km2 / total_area for record in headwaters}
        count = len(headwaters)
        return {record.ifno: 1.0 / count for record in headwaters} if count else {}
    if keyword == "runoff":
        total_length = sum(record.rlen for record in reaches)
        if total_length <= 0.0:
            return {}
        return {record.ifno: record.rlen / total_length for record in reaches}
    # Rates (rainfall / evaporation) apply per reach, unscaled.
    return {record.ifno: 1.0 for record in reaches}


def _emit_network_forcing(
    model,
    *,
    keyword: str,
    forcing: object,
    volumetric: bool,
    targets: Mapping[int, float],
    location: str,
    mode: str,
    min_periods: int,
    nper: int,
    period_rows: dict[int, list[list[Any]]],
    ts_series: list[Ts6Series],
) -> None:
    """Append SFR PERIOD rows (inline floats or TS6 names) for one forcing."""
    value = constant_forcing_value(forcing)
    use_ts6 = resolve_use_ts6(forcing, mode=mode, nper=nper, min_periods=min_periods)
    if value is not None and not use_ts6:
        si_value = float(forcing_to_si(value, forcing, location, volumetric))
        for ifno, scale in targets.items():
            period_rows.setdefault(0, []).append([int(ifno), keyword, si_value * float(scale)])
        return

    if nper <= 0:
        return

    per_period = resolve_period_values_from_forcing(
        forcing=forcing,
        simulation_window=None if model.time_grid is None else model.time_grid.window,
        nper=nper,
        label=location,
    )
    unit = forcing_unit(forcing)
    per_period_si = tuple(
        float(forcing_to_si(raw, forcing, f"{location}[{idx}]", volumetric, explicit_unit=unit))
        for idx, raw in enumerate(per_period)
    )

    if use_ts6:
        uniform = all(float(scale) == 1.0 for scale in targets.values())
        if uniform:
            series_name = _ts6_series_name(keyword)
            for ifno in targets:
                period_rows.setdefault(0, []).append([int(ifno), keyword, series_name])
            times, values = ts6_times_and_values(model, per_period_si)
            ts_series.append(
                Ts6Series(name=series_name, times=times, values=values, interpolation="stepwise")
            )
            return
        for ifno, scale in targets.items():
            series_name = _ts6_series_name(keyword, ifno)
            period_rows.setdefault(0, []).append([int(ifno), keyword, series_name])
            scaled = tuple(value * float(scale) for value in per_period_si)
            times, values = ts6_times_and_values(model, scaled)
            ts_series.append(
                Ts6Series(name=series_name, times=times, values=values, interpolation="stepwise")
            )
        return

    # Inline expansion: one row per reach per stress period whenever the value
    # changes (period 0 always); MF6 carries each value forward.
    for ifno, scale in targets.items():
        previous: float | None = None
        for kper, si_value in enumerate(per_period_si):
            scaled = si_value * float(scale)
            if previous is None or scaled != previous:
                period_rows.setdefault(kper, []).append([int(ifno), keyword, scaled])
                previous = scaled


# Short tags keeping per-reach TS6 names inside the MF6 16-char identifier field.
_TS6_KEYWORD_TAGS = {
    "inflow": "in",
    "runoff": "ro",
    "rainfall": "rain",
    "evaporation": "evap",
}


def _ts6_series_name(keyword: str, ifno: int | None = None) -> str:
    """Return a unique, MF6-length-safe TS6 series name for one SFR forcing."""
    tag = _TS6_KEYWORD_TAGS.get(keyword, keyword[:4])
    if ifno is None:
        return f"sfr_{tag}"[:16]
    return f"sfr_{tag}_{int(ifno)}"[:16]


# Per-reach scalar observation types, mapped to the HMP-side series name the
# extractor stores. Requested by integer reach id (flopy chokes on boundname
# ids), every reach. 'sfr' (reach-aquifer exchange) only exists for connected
# reaches; ext-inflow / ext-outflow are requested everywhere and read 0 where
# unused so the extraction stays uniform.
_SFR_SCALAR_OBSTYPES: tuple[tuple[str, str], ...] = (
    ("stage", "stage"),
    ("depth", "depth"),
    ("downstream-flow", "downstream_flow"),
    ("ext-inflow", "ext_inflow"),
    ("ext-outflow", "ext_outflow"),
    # Diffuse overland inflow added to the reach (the routed catchment runoff
    # forcing). Requested everywhere, reads 0 where no runoff is applied.
    ("runoff", "runoff"),
)


def build_sfr_obs_spec(
    *,
    stem: str,
    network: ResolvedSfrNetwork,
    has_mover: bool = False,
) -> tuple[dict[str, list[tuple[Any, ...]]], dict[str, Any]]:
    """Return ``(obs_continuous, sfr_obs_meta)`` for the SFR package.

    ``obs_continuous`` is the flopy ``continuous`` mapping ``{csv_file: [(name,
    type, id), ...]}`` with 0-based integer reach ids. ``sfr_obs_meta`` is the
    JSON-serialisable sidecar mapping each observation name to its network /
    reach / quantity so the extractor can re-key the obs CSV by
    ``(reach_ifno, totim)``.
    """
    obs_csv = f"{stem}.sfr.obs.csv"
    obslist: list[tuple[Any, ...]] = []
    entries: list[dict[str, Any]] = []

    def _add(obsname: str, obstype: str, ifno: int, quantity: str) -> None:
        obslist.append((obsname, obstype, (int(ifno),)))
        entries.append(
            {
                "obsname": obsname,
                "network_id": network.network_id,
                "reach": int(ifno),
                "quantity": quantity,
            }
        )

    for record in network.reaches:
        for obstype, quantity in _SFR_SCALAR_OBSTYPES:
            _add(f"r{record.ifno}_{quantity}", obstype, record.ifno, quantity)
        if record.cellid is not None:
            # Reach-aquifer exchange; positive = the stream loses to the aquifer.
            _add(f"r{record.ifno}_gw_exchange", "sfr", record.ifno, "gw_exchange")
        if has_mover:
            _add(f"r{record.ifno}_to_mvr", "to-mvr", record.ifno, "to_mvr")
            _add(f"r{record.ifno}_from_mvr", "from-mvr", record.ifno, "from_mvr")

    obs_continuous = {obs_csv: obslist}
    sfr_obs_meta = {
        "obs_csv": obs_csv,
        "network_id": network.network_id,
        "reach_count": len(network.reaches),
        "entries": entries,
    }
    return obs_continuous, sfr_obs_meta
