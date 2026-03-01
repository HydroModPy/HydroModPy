# -*- coding: utf-8 -*-
"""
Forcing -> MODFLOW-NWT adaptation layer.

Purpose
-------
Convert recharge/evapotranspiration forcing payloads into solver-ready
structures expected by FLOPY MODFLOW packages:

- EVT stress-period dictionary (`evtr` payload),
- RCH payload (`rech` argument, scalar or stress-period dictionary).

Scope
-----
This adapter is intentionally limited to forcing normalization. It does not
instantiate FLOPY packages and does not depend on process-level flow/domain
objects.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np


@dataclass(slots=True)
class ForcingModflowInputs:
    """
    Solver-ready forcing payloads.

    Attributes
    ----------
    evt_spd : dict[int, object] | None
        EVT stress-period payload (None when EVT package is not activated).
    rch_data : object
        Recharge payload passed directly to FLOPY `ModflowRch(rech=...)`.
        Can be a scalar or a stress-period mapping.
    """

    evt_spd: dict[int, object] | None
    rch_data: object


class ForcingToModflowAdapter:
    """
    Build MODFLOW-ready forcing payloads from recharge settings.

    Parameters
    ----------
    recharge : object
        Recharge payload from preprocessing options.
    nper : int
        Number of stress periods.
    flow_regime : str
        Flow regime (`steady` or `transient`).
    first_clim : str | float
        Policy for period-0 recharge when forcing is transient:
        - "mean",
        - "first",
        - numeric scalar.
    """

    def __init__(
        self,
        *,
        recharge: object,
        nper: int,
        flow_regime: str,
        first_clim: str | float,
    ) -> None:
        self.recharge = recharge
        self.nper = int(nper)
        self.flow_regime = str(flow_regime).strip().lower()
        self.first_clim = first_clim

    @staticmethod
    def _is_scalar_number(value: object) -> bool:
        """Return True for numeric scalar values (excluding booleans)."""
        return isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(
            value, bool
        )

    @staticmethod
    def _copy_payload(payload: object) -> object:
        """Return a defensive copy when possible."""
        if isinstance(payload, Mapping):
            return dict(payload)
        if hasattr(payload, "copy"):
            try:
                return payload.copy()
            except Exception:
                return payload
        return payload

    @staticmethod
    def _has_negative_values(payload: object) -> bool:
        """
        Detect negative values in array-like forcing payloads.

        The legacy behavior was oriented toward pandas objects; this helper
        keeps equivalent support while being resilient to numpy/list payloads.
        """
        try:
            return bool((payload < 0).any().any())
        except Exception:
            try:
                as_array = np.asarray(payload, dtype=float)
                return bool(np.nanmin(as_array) < 0)
            except Exception:
                return False

    @staticmethod
    def _series_value(payload: object, kper: int):
        """
        Read one kper forcing value from heterogeneous payload containers.

        Supports pandas-like objects (`.iloc`) and sequence-like objects (`[]`).
        """
        if hasattr(payload, "iloc"):
            value = payload.iloc[kper]
            try:
                return value.values[0]
            except Exception:
                return value
        return payload[kper]

    def _build_evt_and_recharge_payload(self) -> tuple[dict[int, object] | None, object]:
        """
        Build EVT payload and sanitized recharge payload.

        Legacy rule preserved:
        - negative recharge activates EVT from negative values,
        - recharge is then clipped to non-negative values for RCH.
        """
        recharge_payload = self._copy_payload(self.recharge)
        evt_spd: dict[int, object] | None = None

        if not isinstance(recharge_payload, Mapping):
            if not self._is_scalar_number(recharge_payload) and self._has_negative_values(
                recharge_payload
            ):
                evt_payload = self._copy_payload(recharge_payload)
                evt_payload[evt_payload >= 0] = 0
                evt_payload = abs(evt_payload)

                evt_spd = {}
                for kper in range(self.nper):
                    if self._is_scalar_number(evt_payload):
                        evt_spd[kper] = float(evt_payload)
                    else:
                        if kper == 0:
                            evt_spd[kper] = 0
                        else:
                            evt_spd[kper] = self._series_value(evt_payload, kper)

                # Clip recharge to non-negative values for the RCH package.
                recharge_payload[recharge_payload < 0] = 0

        return evt_spd, recharge_payload

    def _build_rch_payload(self, recharge_payload: object) -> object:
        """Build RCH payload from sanitized recharge forcing."""
        if isinstance(recharge_payload, Mapping):
            if self.flow_regime == "steady":
                if len(recharge_payload) == 0:
                    raise ValueError(
                        "recharge mapping cannot be empty in steady regime."
                    )
                return sum(recharge_payload.values()) / len(recharge_payload)
            return dict(recharge_payload)

        rch_data: dict[int, object] = {}
        for kper in range(self.nper):
            if self._is_scalar_number(recharge_payload):
                rch_data[kper] = float(recharge_payload)
                continue

            if kper == 0:
                if self.first_clim == "mean":
                    rch_data[kper] = np.nanmean(recharge_payload)
                elif self.first_clim == "first":
                    rch_data[kper] = self._series_value(recharge_payload, 0)
                elif self._is_scalar_number(self.first_clim):
                    rch_data[kper] = float(self.first_clim)
                else:
                    raise ValueError(
                        "first_clim must be 'mean', 'first', or a numeric value."
                    )
            else:
                rch_data[kper] = self._series_value(recharge_payload, kper)
        return rch_data

    def build(self) -> ForcingModflowInputs:
        """
        Build EVT and RCH payloads for FLOPY package assembly.
        """
        if self.nper <= 0:
            raise ValueError("nper must be > 0")
        if self.flow_regime not in {"steady", "transient"}:
            raise ValueError("flow_regime must be 'steady' or 'transient'")

        evt_spd, recharge_payload = self._build_evt_and_recharge_payload()
        rch_data = self._build_rch_payload(recharge_payload)
        return ForcingModflowInputs(evt_spd=evt_spd, rch_data=rch_data)
