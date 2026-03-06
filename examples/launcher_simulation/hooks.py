# -*- coding: utf-8 -*-
"""Study-specific hooks for ``examples/launcher_simulation``.

The launcher discovers this file next to ``config.toml`` and imports any
function named ``on_before_<phase>`` or ``on_after_<phase>``. Each hook
receives the shared :class:`launchers.LauncherRunState` instance and mutates it
in-place. The launcher owns object creation and solver execution; this file only
injects the parts that are specific to Example 12.

Execution model
---------------
The hook names in this file map to two kinds of lifecycle events:

- ``setup`` and ``data`` are launcher phases executed exactly once.
- ``flow`` and ``transport`` are process families executed by
  ``SimulationRunner``. Their hooks fire once per contiguous process-family
  block, not once per solver.

That distinction matters for state interpretation:

- ``on_before_flow`` prepares inputs shared by every flow solver in the block.
- ``on_before_transport`` is now a compatibility hook kept as a no-op. Runtime
  flow-to-transport preprocessing moved to transport solver adapters.

This file intentionally does not recreate the generic launcher boilerplate
(workspace, geographic context, domain, solver instances, etc.). Those objects
already exist on ``LauncherRunState`` when the relevant hook is called.

Postprocess actions that were previously in ``on_after_flow`` and
``on_after_transport`` are now driven by the `[postprocess]` TOML section.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from hydromodpy.process.flow.sinks_sources import FlowRechargeConfig
from launchers import LauncherRunState


def _as_mapping(value, *, name: str) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    raise ValueError(f"{name} must be a mapping")


def _resolve_config_path(result: LauncherRunState, path_value: object) -> Path:
    if not isinstance(path_value, str) or not path_value.strip():
        raise ValueError("recharge_chronicle path must be a non-empty string")
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = (result.config_path.parent / path).resolve()
    return path


def _normalize_recharge_mode(result: LauncherRunState) -> str:
    cfg = _as_mapping(result.raw_toml.get("recharge_chronicle"), name="recharge_chronicle")
    mode = str(cfg.get("mode", "synthetic_generated")).strip().lower()
    allowed = {"observed_csv", "synthetic_generated", "synthetic_csv"}
    if mode not in allowed:
        raise ValueError(
            "recharge_chronicle.mode must be one of "
            "'observed_csv', 'synthetic_generated', 'synthetic_csv'."
        )
    return mode


def _to_m_per_day(series: pd.Series, *, units: object, label: str) -> pd.Series:
    unit = str(units).strip().lower()
    if unit in {"m/day", "m/d"}:
        return series.astype(float)
    if unit in {"mm/day", "mm/d"}:
        return series.astype(float) / 1000.0
    raise ValueError(f"{label} units must be 'mm/day' or 'm/day'. Got: {units!r}")


def _build_synthetic_generated_series(
    result: LauncherRunState,
    *,
    recharge_config: FlowRechargeConfig | None,
) -> tuple[pd.Series, pd.Series]:
    cfg_root = _as_mapping(result.raw_toml.get("recharge_chronicle"), name="recharge_chronicle")
    cfg = _as_mapping(cfg_root.get("synthetic_generated"), name="recharge_chronicle.synthetic_generated")

    raw_values = cfg.get("values_mm_day")
    if raw_values is None and recharge_config is not None:
        # Backward-compatible fallback for previous config style.
        raw_values = recharge_config.values

    if isinstance(raw_values, (list, tuple)):
        values = [float(v) for v in raw_values]
        periods = int(cfg.get("periods", len(values)))
        if len(values) != periods:
            raise ValueError(
                "recharge_chronicle.synthetic_generated.values_mm_day length must match periods."
            )
    elif isinstance(raw_values, (int, float)) and not isinstance(raw_values, bool):
        periods = int(cfg.get("periods", 12))
        values = [float(raw_values)] * periods
    else:
        raise ValueError(
            "recharge_chronicle.synthetic_generated.values_mm_day must be "
            "a scalar or a list of numeric values."
        )

    start_date = str(cfg.get("start_date", "2003-01-01"))
    freq = str(cfg.get("freq", "ME"))
    index = pd.date_range(start=start_date, periods=periods, freq=freq)
    recharge_raw = pd.Series(values, index=index, dtype=float)
    recharge = _to_m_per_day(
        recharge_raw,
        units=cfg.get("units", "mm/day"),
        label="synthetic_generated recharge",
    )

    runoff_ratio = float(cfg.get("runoff_ratio", 0.1))
    runoff = recharge * runoff_ratio
    return recharge, runoff


def _build_synthetic_csv_series(result: LauncherRunState) -> tuple[pd.Series, pd.Series]:
    cfg_root = _as_mapping(result.raw_toml.get("recharge_chronicle"), name="recharge_chronicle")
    cfg = _as_mapping(cfg_root.get("synthetic_csv"), name="recharge_chronicle.synthetic_csv")

    path_file = _resolve_config_path(result, cfg.get("path_file", ""))
    sep = str(cfg.get("sep", ","))
    date_column = str(cfg.get("date_column", "date"))
    recharge_column = str(cfg.get("recharge_column", "recharge_mm_day"))
    date_format = cfg.get("date_format")
    runoff_column = cfg.get("runoff_column")

    df = pd.read_csv(path_file, sep=sep)
    if date_column not in df.columns:
        raise ValueError(
            f"Column '{date_column}' not found in synthetic recharge CSV: {path_file}"
        )
    if recharge_column not in df.columns:
        raise ValueError(
            f"Column '{recharge_column}' not found in synthetic recharge CSV: {path_file}"
        )

    if date_format is None:
        dates = pd.to_datetime(df[date_column])
    else:
        dates = pd.to_datetime(df[date_column], format=str(date_format))

    recharge_raw = pd.Series(df[recharge_column].astype(float).values, index=dates)
    recharge_raw = recharge_raw.sort_index()
    recharge = _to_m_per_day(
        recharge_raw,
        units=cfg.get("units", "mm/day"),
        label="synthetic_csv recharge",
    )

    if isinstance(runoff_column, str) and runoff_column in df.columns:
        runoff_raw = pd.Series(df[runoff_column].astype(float).values, index=dates).sort_index()
        runoff = _to_m_per_day(
            runoff_raw,
            units=cfg.get("runoff_units", cfg.get("units", "mm/day")),
            label="synthetic_csv runoff",
        )
    else:
        runoff_ratio = float(cfg.get("runoff_ratio", 0.1))
        runoff = recharge * runoff_ratio

    time_step = cfg.get("time_step")
    if isinstance(time_step, str) and time_step.strip():
        recharge = recharge.resample(time_step).mean().ffill()
        runoff = runoff.resample(time_step).mean().ffill()

    return recharge, runoff


def on_after_data(result: LauncherRunState) -> None:
    """Seed climate forcing once generic data-manager loading is complete.

    This hook extends the generic launcher ``data`` phase. At this point the
    launcher has already created:

    - ``result.data.climatic``
    - ``result.data.hydrography``
    - ``result.data.intermittency``
    - ``result.data.hydrometry``

    Those datasets now come from ``[data.*]`` TOML sections via the generic
    runtime loader. This hook keeps only the study-specific climate bootstrap.
    """
    mode = _normalize_recharge_mode(result)
    if mode != "observed_csv":
        return

    cfg_root = _as_mapping(result.raw_toml.get("recharge_chronicle"), name="recharge_chronicle")
    cfg = _as_mapping(cfg_root.get("observed_csv"), name="recharge_chronicle.observed_csv")

    default_path = result.cfg.workspace.data_path / "_climate_REANALYSIS.csv"
    path_file = _resolve_config_path(result, cfg.get("path_file", str(default_path)))
    clim_mod = str(cfg.get("clim_mod", "REA"))
    clim_sce = str(cfg.get("clim_sce", "historic"))
    first_year = int(cfg.get("first_year", 2003))
    last_year = int(cfg.get("last_year", first_year))
    time_step = str(cfg.get("time_step", "ME"))
    sim_state = str(cfg.get("sim_state", "transient"))

    result.data.climatic.update_recharge_reanalysis(
        path_file=path_file,
        clim_mod=clim_mod,
        clim_sce=clim_sce,
        first_year=first_year,
        last_year=last_year,
        time_step=time_step,
        sim_state=sim_state,
    )
    result.data.climatic.update_runoff_reanalysis(
        path_file=path_file,
        clim_mod=clim_mod,
        clim_sce=clim_sce,
        first_year=first_year,
        last_year=last_year,
        time_step=time_step,
        sim_state=sim_state,
    )


def on_before_flow(result: LauncherRunState) -> None:
    """Prepare the shared flow inputs used by the whole flow process family.

    This hook runs once before the first flow solver in the current process
    block. If several flow solvers are declared, they all consume the same
    ``result.setup.flow`` object configured here.

    The hook performs four tasks:

    - load the selected recharge chronicle mode from ``[recharge_chronicle]``
    - derive runoff from recharge when needed
    - set study-specific model naming and preprocessing options
    - inject the final recharge policy into ``result.setup.flow``
    """
    mode = _normalize_recharge_mode(result)
    recharge_config = result.setup.flow.sinks_sources.get("recharge")

    if mode == "observed_csv":
        recharge = result.data.climatic.recharge
        runoff = result.data.climatic.runoff
        if recharge is None:
            raise ValueError(
                "Observed recharge mode requires on_after_data to load climatic.recharge."
            )
        if runoff is None:
            cfg_root = _as_mapping(
                result.raw_toml.get("recharge_chronicle"),
                name="recharge_chronicle",
            )
            obs_cfg = _as_mapping(
                cfg_root.get("observed_csv"),
                name="recharge_chronicle.observed_csv",
            )
            runoff_ratio = float(obs_cfg.get("runoff_ratio", 0.1))
            runoff = recharge * runoff_ratio
    elif mode == "synthetic_generated":
        recharge, runoff = _build_synthetic_generated_series(
            result,
            recharge_config=recharge_config,
        )
    elif mode == "synthetic_csv":
        recharge, runoff = _build_synthetic_csv_series(result)
    else:
        raise RuntimeError(f"Unhandled recharge mode: {mode}")

    result.data.climatic.update_recharge(recharge, sim_state=result.setup.flow.flow_regime)
    result.data.climatic.update_runoff(runoff, sim_state=result.setup.flow.flow_regime)

    alpha = 15
    hydraulic_conductivity = 5e-5 * 24 * 3600
    specific_yield = 2 / 100

    model_version = "TRANS1"
    model_name = (
        f"{model_version}_K{hydraulic_conductivity / 24 / 3600:.1e}"
        f"_a{alpha:.1f}_Sy{specific_yield * 100:.1f}"
    )
    result.setup.settings.model_name = model_name
    result.setup.settings.box = True
    result.setup.settings.sink_fill = False
    result.setup.settings.check_grid = True

    # Reuse the policy declared in TOML for stress period 0 and negative
    # recharge handling. The time series values themselves are the synthetic
    # series computed above.
    first_clim = recharge_config.first_clim if recharge_config is not None else "mean"
    result.data.climatic.update_first_clim(first_clim)

    negative_to_evt = recharge_config.negative_to_evt if recharge_config is not None else True
    result.setup.flow.set_recharge(
        FlowRechargeConfig(
            values=result.data.climatic.recharge,
            first_clim=result.data.climatic.first_clim,
            negative_to_evt=negative_to_evt,
        )
    )


def on_before_transport(result: LauncherRunState) -> None:
    """Compatibility no-op.

    Transport runtime preprocessing is now handled in transport adapters:

    - concentration payload expansion from flow grid (mt3dms/modflow6gwt),
    - seepage raster clipping for ``zone_partic='seepage_clip'`` (modpath).
    """
    _ = result
