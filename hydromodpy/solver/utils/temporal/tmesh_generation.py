# -*- coding: utf-8 -*-
"""
* Copyright (c) 2023 Alexandre Gauvain, Ronan Abherve, Jean-Raynald de Dreuzy
*
* This program and the accompanying materials are made available under the
* terms of the Eclipse Public License 2.0 which is available at
* http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
* which is available at https://www.apache.org/licenses/LICENSE-2.0.
*
* SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
"""

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.core.units import factor_to_seconds, to_pandas_timedelta_unit
from hydromodpy.solver.utils.temporal.tmesh_config import TMeshConfigModel

try:
    from flopy.discretization.modeltime import ModelTime
except ModuleNotFoundError:  # pragma: no cover - used only in minimal local envs
    ModelTime = None


_VALID_FLOW_REGIMES = {"steady", "transient"}
_VALID_GEN_METHODS = {"synthetic_regular", "from_chron"}

# Backward-compatible alias: TMeshConfig was a frozen dataclass, now backed by the
# validated Pydantic model.  Existing code that imports TMeshConfig still works.
TMeshConfig = TMeshConfigModel


def _as_positive_int(name: str, value: Any) -> int:
    try:
        ivalue = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer.") from exc
    if ivalue <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    return ivalue


def _as_positive_float(name: str, value: Any) -> float:
    try:
        fvalue = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive number.") from exc
    if not np.isfinite(fvalue) or fvalue <= 0:
        raise ValueError(f"{name} must be a positive number.")
    return fvalue


def _as_timestamp(name: str, value: Any) -> pd.Timestamp:
    try:
        ts = pd.Timestamp(value)
    except Exception as exc:
        raise ValueError(f"{name} must be a valid datetime value.") from exc
    if pd.isna(ts):
        raise ValueError(f"{name} must be a valid datetime value.")
    return ts


def _inclusive_end_candidate(
    end_datetime: pd.Timestamp,
    *,
    itmuni: str,
) -> pd.Timestamp:
    try:
        unit = to_pandas_timedelta_unit(itmuni)
    except Exception:
        unit = "d"
    # When itmuni is sub-day (seconds, minutes, hours), the inclusive-end
    # convention still works at the *day* granularity because user-facing
    # simulation windows are always specified as dates.  Adding +1 second
    # when the launcher normalised itmuni to "seconds" would produce a
    # negligible offset that never matches the expected period sum.
    if unit in ("s", "ms", "us", "ns", "min"):
        unit = "d"
    return end_datetime + pd.to_timedelta(1, unit=unit)


def _validate_config(config: TMeshConfig) -> None:
    if str(config.itmuni).strip() == "":
        raise ValueError("itmuni cannot be empty.")
    if config.flow_regime not in _VALID_FLOW_REGIMES:
        raise ValueError(
            f"Invalid flow_regime={config.flow_regime!r}. Expected one of: {_VALID_FLOW_REGIMES}."
        )
    if config.genmtd not in _VALID_GEN_METHODS:
        raise ValueError(
            f"Invalid genmtd={config.genmtd!r}. Expected one of: {_VALID_GEN_METHODS}."
        )
    if str(config.chron_time_col).strip() == "":
        raise ValueError("chron_time_col cannot be empty.")
    if config.genmtd == "synthetic_regular":
        _as_positive_int("nper", config.nper)
        if config.lenper is None:
            raise ValueError("lenper cannot be None for genmtd='synthetic_regular'.")
        if np.isscalar(config.lenper):
            _as_positive_float("lenper", config.lenper)
        else:
            lenper_arr = np.asarray(config.lenper, dtype=float).reshape(-1)
            if lenper_arr.size == 0:
                raise ValueError("lenper list cannot be empty for genmtd='synthetic_regular'.")
            if lenper_arr.size != int(config.nper):
                raise ValueError(
                    f"lenper length mismatch: expected nper={int(config.nper)}, got {lenper_arr.size}."
                )
            if not np.all(np.isfinite(lenper_arr)) or np.any(lenper_arr <= 0):
                raise ValueError("lenper values must be strictly positive.")
    if config.genmtd == "from_chron":
        if config.chron_path is None or str(config.chron_path).strip() == "":
            raise ValueError("chron_path is required for genmtd='from_chron'.")
    if config.start_datetime is not None and config.end_datetime is not None:
        start = _as_timestamp("start_datetime", config.start_datetime)
        end = _as_timestamp("end_datetime", config.end_datetime)
        if end < start:
            raise ValueError("end_datetime must be greater than or equal to start_datetime.")


def _read_chron_dates(config: TMeshConfig) -> pd.Series:
    chron_path = Path(str(config.chron_path))
    if not chron_path.exists():
        raise FileNotFoundError(f"Chronicle file not found: {chron_path}")
    df = pd.read_csv(chron_path, sep=config.chron_colsep)
    if df.empty:
        raise ValueError("Chronicle file is empty.")
    if config.chron_time_col not in df.columns:
        raise ValueError(f"Chronicle column {config.chron_time_col!r} not found in {chron_path}.")
    try:
        dates = pd.to_datetime(
            df[config.chron_time_col],
            format=config.chron_dateformat,
            errors="raise",
        )
    except Exception as exc:
        raise ValueError(
            f"Failed to parse chronicle dates with chron_dateformat={config.chron_dateformat!r}."
        ) from exc
    if len(dates) < 2:
        raise ValueError("Chronicle must contain at least two timestamps.")
    deltas = dates.diff().iloc[1:]
    if (deltas <= pd.Timedelta(0)).any():
        raise ValueError("Chronicle timestamps must be strictly increasing.")
    return dates


def _build_period_lengths(config: TMeshConfig) -> tuple[Any, str, np.ndarray]:
    _validate_config(config)

    if config.genmtd == "synthetic_regular":
        start_datetime = (
            pd.to_datetime(0)
            if config.start_datetime is None
            else _as_timestamp("start_datetime", config.start_datetime)
        )
        nper = _as_positive_int("nper", config.nper)
        if np.isscalar(config.lenper):
            lenper = _as_positive_float("lenper", config.lenper)
            lenper_vector = np.full(nper, lenper, dtype=float)
        else:
            lenper_vector = np.asarray(config.lenper, dtype=float).reshape(-1)
            if lenper_vector.size != nper:
                raise ValueError(
                    "synthetic_regular lenper length mismatch: "
                    f"expected nper={nper}, got {lenper_vector.size}."
                )
            if not np.all(np.isfinite(lenper_vector)) or np.any(lenper_vector <= 0):
                raise ValueError("synthetic_regular lenper values must be strictly positive.")
        try:
            deltat = pd.to_timedelta(
                lenper_vector,
                unit=to_pandas_timedelta_unit(config.itmuni),
            )
        except ValueError as exc:
            raise ValueError(
                f"Unsupported itmuni {config.itmuni!r} for synthetic_regular generation."
            ) from exc
        if config.end_datetime is not None:
            end_datetime = _as_timestamp("end_datetime", config.end_datetime)
            expected = pd.to_timedelta(np.sum(deltat))
            actual = end_datetime - start_datetime
            inclusive_actual = (
                _inclusive_end_candidate(
                    end_datetime,
                    itmuni=str(config.itmuni),
                )
                - start_datetime
            )
            if actual < pd.Timedelta(0):
                raise ValueError("end_datetime must be greater than or equal to start_datetime.")
            matches_exclusive = np.isclose(
                actual.total_seconds(),
                expected.total_seconds(),
                rtol=0.0,
                atol=1e-6,
            )
            matches_inclusive = np.isclose(
                inclusive_actual.total_seconds(),
                expected.total_seconds(),
                rtol=0.0,
                atol=1e-6,
            )
            if not (matches_exclusive or matches_inclusive):
                raise ValueError(
                    "synthetic_regular window mismatch: expected nper/lenper duration "
                    "must match either exclusive bounds [start, end) or inclusive "
                    "bounds [start, end]."
                )
    elif config.genmtd == "from_chron":
        dates = _read_chron_dates(config).reset_index(drop=True)
        if config.start_datetime is not None or config.end_datetime is not None:
            start_bound = (
                dates.iloc[0]
                if config.start_datetime is None
                else _as_timestamp("start_datetime", config.start_datetime)
            )
            end_bound = (
                dates.iloc[-1]
                if config.end_datetime is None
                else _as_timestamp("end_datetime", config.end_datetime)
            )
            if end_bound < start_bound:
                raise ValueError("end_datetime must be greater than or equal to start_datetime.")
            if start_bound < dates.iloc[0] or end_bound > dates.iloc[-1]:
                raise ValueError(
                    "Chronicle does not cover requested [start_datetime, end_datetime] window."
                )
            dates = dates[(dates >= start_bound) & (dates <= end_bound)].reset_index(drop=True)
            if len(dates) < 2:
                raise ValueError("Requested chronicle window must contain at least two timestamps.")
            if dates.iloc[0] != start_bound or dates.iloc[-1] != end_bound:
                raise ValueError(
                    "start_datetime and end_datetime must exactly match chronicle timestamps "
                    "when genmtd='from_chron'."
                )
        start_datetime = dates.iloc[0]
        deltat = dates.iloc[1:].reset_index(drop=True) - dates.iloc[:-1].reset_index(drop=True)
    else:  # pragma: no cover - unreachable due to _validate_config
        raise ValueError(f"Unsupported genmtd={config.genmtd!r}.")

    delta_values = pd.to_timedelta(deltat)
    if isinstance(delta_values, pd.Series):
        seconds = delta_values.dt.total_seconds().to_numpy(dtype=float)
    else:
        seconds = np.asarray(delta_values.total_seconds(), dtype=float)
    perlen = seconds / factor_to_seconds(config.itmuni)
    if perlen.size == 0:
        raise ValueError("Temporal mesh requires at least one stress period.")
    if not np.all(np.isfinite(perlen)) or np.any(perlen <= 0):
        raise ValueError("Computed perlen contains non-positive or invalid values.")
    return start_datetime, str(config.itmuni), perlen


def _build_steady_state(config: TMeshConfig, perlen: np.ndarray) -> np.ndarray:
    if config.flow_regime == "steady":
        return np.ones(len(perlen), dtype=bool)
    if config.flow_regime == "transient":
        steady_state = np.zeros(len(perlen), dtype=bool)
        if bool(config.firstpersteady):
            steady_state[0] = True
        return steady_state
    raise ValueError(
        f"Invalid flow_regime={config.flow_regime!r}. Expected one of: {_VALID_FLOW_REGIMES}."
    )


def _expand_ntsp(value: int | list[int] | np.ndarray, nper: int) -> np.ndarray:
    if np.isscalar(value):
        arr = np.full(nper, int(value), dtype=int)
    else:
        arr = np.asarray(value).reshape(-1)
        if arr.size != nper:
            raise ValueError(f"ntsp length mismatch: expected {nper}, got {arr.size}.")
        if not np.all(np.equal(arr, np.floor(arr))):
            raise ValueError("ntsp values must be integers.")
        arr = arr.astype(int)
    if np.any(arr <= 0):
        raise ValueError("ntsp values must be strictly positive.")
    return arr


def _expand_tsmult(
    value: int | float | list[float] | np.ndarray,
    nper: int,
) -> np.ndarray:
    if np.isscalar(value):
        arr = np.full(nper, float(value), dtype=float)
    else:
        arr = np.asarray(value, dtype=float).reshape(-1)
        if arr.size != nper:
            raise ValueError(f"tsmult length mismatch: expected {nper}, got {arr.size}.")
    if not np.all(np.isfinite(arr)) or np.any(arr <= 0):
        raise ValueError("tsmult values must be strictly positive.")
    return arr


def _build_modeltime(
    *,
    time_units: str,
    start_datetime: Any,
    steady_state: np.ndarray,
    perlen: np.ndarray,
    nstp: np.ndarray,
    tsmult: np.ndarray,
):
    if ModelTime is None:
        raise ModuleNotFoundError(
            "flopy is required to build ModelTime. Install flopy to run temporal mesh generation."
        )
    return ModelTime(
        time_units=time_units,
        start_datetime=start_datetime,
        steady_state=steady_state,
        perlen=perlen,
        nstp=nstp,
        tsmult=tsmult,
    )


class TMesh_Generation:
    """
    Temporal mesh builder.

    Backward compatibility is preserved:
    - legacy property names are still available,
    - legacy alias `genmtd_tgrid` maps to `genmtd`,
    - `_tgrid_created` and `_tgrid` are kept synchronized.
    """

    def __init__(self, config: TMeshConfig | None = None, **kwargs):
        if config is not None and kwargs:
            raise ValueError("Provide either config or keyword parameters, not both.")
        if config is None:
            config = TMeshConfig(**kwargs)
        _validate_config(config)
        self._config: TMeshConfig = config
        self._tmesh_created = False
        self._tgrid_created = False
        self._tmesh = None
        self._tgrid = None

    @classmethod
    def from_config(cls, config: TMeshConfig) -> "TMesh_Generation":
        return cls(config=config)

    @property
    def config(self) -> TMeshConfig:
        return self._config

    def apply_config(self, config: TMeshConfig) -> None:
        _validate_config(config)
        self._config = config
        self._invalidate_mesh()

    def _invalidate_mesh(self) -> None:
        self._tmesh_created = False
        self._tgrid_created = False
        self._tmesh = None
        self._tgrid = None

    def _set_config_value(self, key: str, value: Any) -> None:
        new_config = self._config.model_copy(update={key: value})
        _validate_config(new_config)
        self._config = new_config
        self._invalidate_mesh()

    def run(self):
        if not self._tmesh_created:
            self._create_tmesh()
        return self._tmesh

    @property
    def itmuni(self):
        return self._config.itmuni

    @itmuni.setter
    def itmuni(self, value):
        self._set_config_value("itmuni", value)

    @property
    def flow_regime(self):
        return self._config.flow_regime

    @flow_regime.setter
    def flow_regime(self, value):
        self._set_config_value("flow_regime", value)

    @property
    def genmtd(self):
        return self._config.genmtd

    @genmtd.setter
    def genmtd(self, value):
        self._set_config_value("genmtd", value)

    @property
    def genmtd_tgrid(self):
        return self.genmtd

    @genmtd_tgrid.setter
    def genmtd_tgrid(self, value):
        self.genmtd = value

    @property
    def nper(self):
        return self._config.nper

    @nper.setter
    def nper(self, value):
        self._set_config_value("nper", value)

    @property
    def lenper(self):
        return self._config.lenper

    @lenper.setter
    def lenper(self, value):
        self._set_config_value("lenper", value)

    @property
    def chron_path(self):
        return self._config.chron_path

    @chron_path.setter
    def chron_path(self, value):
        self._set_config_value("chron_path", value)

    @property
    def chron_dateformat(self):
        return self._config.chron_dateformat

    @chron_dateformat.setter
    def chron_dateformat(self, value):
        self._set_config_value("chron_dateformat", value)

    @property
    def chron_colsep(self):
        return self._config.chron_colsep

    @chron_colsep.setter
    def chron_colsep(self, value):
        self._set_config_value("chron_colsep", value)

    @property
    def chron_time_col(self):
        return self._config.chron_time_col

    @chron_time_col.setter
    def chron_time_col(self, value):
        self._set_config_value("chron_time_col", value)

    @property
    def start_datetime(self):
        return self._config.start_datetime

    @start_datetime.setter
    def start_datetime(self, value):
        self._set_config_value("start_datetime", value)

    @property
    def end_datetime(self):
        return self._config.end_datetime

    @end_datetime.setter
    def end_datetime(self, value):
        self._set_config_value("end_datetime", value)

    @property
    def firstpersteady(self):
        return self._config.firstpersteady

    @firstpersteady.setter
    def firstpersteady(self, value):
        self._set_config_value("firstpersteady", bool(value))

    @property
    def tsmult(self):
        return self._config.tsmult

    @tsmult.setter
    def tsmult(self, value):
        self._set_config_value("tsmult", value)

    @property
    def ntsp(self):
        return self._config.ntsp

    @ntsp.setter
    def ntsp(self, value):
        self._set_config_value("ntsp", value)

    @property
    def temporal_nodata(self):
        return self._config.temporal_nodata

    @temporal_nodata.setter
    def temporal_nodata(self, value):
        self._set_config_value("temporal_nodata", float(value))

    def _create_tmesh(self):
        start_datetime, time_units, perlen = self._get_period_lengths()
        steady_state = self._get_steady_state_array(perlen)
        nstp = _expand_ntsp(self.ntsp, len(perlen))
        tsmult = _expand_tsmult(self.tsmult, len(perlen))
        tmesh = _build_modeltime(
            time_units=time_units,
            start_datetime=start_datetime,
            steady_state=steady_state,
            perlen=perlen,
            nstp=nstp,
            tsmult=tsmult,
        )
        self._tmesh = tmesh
        self._tgrid = tmesh
        self._tmesh_created = True
        self._tgrid_created = True

    def _get_period_lengths(self):
        return _build_period_lengths(self._config)

    def _get_steady_state_array(self, perlen):
        return _build_steady_state(self._config, np.asarray(perlen, dtype=float))
