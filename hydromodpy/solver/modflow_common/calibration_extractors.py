"""Lightweight binary readers for calibration trials.

During a calibration trial, the solver writes ``.hds`` and ``.cbc`` to the
scratch folder but no Zarr / Parquet rows are produced. The optimizer needs
the simulated series ASAP to score one trial — these helpers read the binary
files directly and return a ``pd.Series`` aligned with the simulation time
grid. Both MODFLOW-NWT and MODFLOW 6 use the same binary layout, so the same
helpers are reused across the two backends.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd

# MODFLOW ITMUNI codes -> seconds per native time unit. CBC fluxes are
# expressed in volume / itmuni-time-unit; dividing by this factor yields
# m3/s, which matches the hydrometry observations.
_ITMUNI_TO_SECONDS: dict[int, float] = {
    0: 1.0,
    1: 1.0,
    2: 60.0,
    3: 3600.0,
    4: 86400.0,
    5: 31557600.0,
}


def _read_itmuni_from_dis(dis_path: Path) -> int:
    """Return the ITMUNI integer declared in a MODFLOW DIS file.

    Falls back to ``1`` (seconds) when the file is missing or unparseable.
    """
    if not dis_path.is_file():
        return 1
    try:
        with dis_path.open("r", encoding="utf-8") as fh:
            header_lines: list[str] = []
            for raw in fh:
                stripped = raw.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                header_lines.append(stripped)
                if len(header_lines) >= 2:
                    break
        if len(header_lines) < 2:
            return 1
        tokens = header_lines[1].split()
        if len(tokens) >= 2:
            return int(tokens[1])
    except (OSError, ValueError):
        return 1
    return 1


def extract_discharge_from_cbc(
    output_dir: Path,
    model_name: str,
    time_index: pd.DatetimeIndex | None = None,
) -> pd.Series:
    """Sum the DRAIN budget component per timestep and return a m3/s series.

    Raises when no CBC file is found or no DRAIN component is recorded.
    """
    import flopy.utils.binaryfile as bf

    cbc_path = output_dir / f"{model_name}.cbc"
    if not cbc_path.exists():
        cbc_path = output_dir / f"{model_name}.cbb"
    if not cbc_path.exists():
        raise FileNotFoundError(f"CBC file not found for model {model_name!r} in {output_dir}")

    itmuni = _read_itmuni_from_dis(output_dir / f"{model_name}.dis")
    seconds_per_unit = _ITMUNI_TO_SECONDS.get(itmuni, 1.0)

    cbb = bf.CellBudgetFile(str(cbc_path))
    try:
        record_names = [r.decode().strip() for r in cbb.get_unique_record_names()]
        drain_key = next(
            (key for key in record_names if key.lower() in {"drains", "drn", "drain"}),
            None,
        )
        if drain_key is None:
            raise KeyError(f"No DRAIN component in CBC; components were {record_names}")

        times = cbb.get_times()
        kstpkpers = cbb.get_kstpkper()
        n_timesteps = len(times)
        values = np.zeros(n_timesteps, dtype=float)
        for t, (time, ksk) in enumerate(zip(times, kstpkpers, strict=False)):
            try:
                data = cbb.get_data(text=drain_key, kstpkper=ksk, totim=time, full3D=True)
            except Exception:
                continue
            if not data:
                continue
            arr = np.asarray(data[0], dtype=float)
            values[t] = float(np.abs(np.minimum(arr, 0.0)).sum())
    finally:
        cbb.close()

    values = values / seconds_per_unit

    if time_index is not None and len(time_index) == n_timesteps:
        return pd.Series(values, index=time_index, name="discharge")
    return pd.Series(values, name="discharge")


def extract_head_from_hds(
    output_dir: Path,
    model_name: str,
    *,
    station_cells: Mapping[str, tuple[int, int, int]],
    time_index: pd.DatetimeIndex | None = None,
) -> dict[str, pd.Series]:
    """Return head timeseries keyed by station at the given ``(k, i, j)`` cells."""
    import flopy.utils.binaryfile as bf

    hds_path = output_dir / f"{model_name}.hds"
    if not hds_path.exists():
        raise FileNotFoundError(f"HDS file not found for model {model_name!r} in {output_dir}")

    hf = bf.HeadFile(str(hds_path))
    try:
        times = hf.get_times()
        n_t = len(times)
        values_by_station = {
            station_id: np.full(n_t, np.nan, dtype=float) for station_id in station_cells
        }
        for t, totim in enumerate(times):
            head = hf.get_data(totim=totim)
            for station_id, (k, i, j) in station_cells.items():
                try:
                    values_by_station[station_id][t] = float(head[k, i, j])
                except IndexError as exc:
                    raise IndexError(
                        f"Station {station_id!r} cell {(k, i, j)!r} is outside "
                        f"the head array shape {head.shape!r}."
                    ) from exc
        out: dict[str, pd.Series] = {}
        for station_id, values in values_by_station.items():
            values[np.abs(values) > 1e6] = np.nan
            if time_index is not None and len(time_index) == n_t:
                out[station_id] = pd.Series(values, index=time_index, name=f"head@{station_id}")
            else:
                out[station_id] = pd.Series(values, name=f"head@{station_id}")
    finally:
        hf.close()
    return out


__all__ = ["extract_discharge_from_cbc", "extract_head_from_hds"]
