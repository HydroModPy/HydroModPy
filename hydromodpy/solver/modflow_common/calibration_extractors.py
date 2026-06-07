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

from hydromodpy.core.units.time import factor_to_seconds


def _seconds_per_itmuni(itmuni: int) -> float:
    """Seconds per MODFLOW ITMUNI code; 0 (undefined) means seconds."""
    if itmuni == 0:
        return 1.0
    try:
        return factor_to_seconds(int(itmuni))
    except ValueError:
        return 1.0


def _read_time_units_from_tdis(tdis_path: Path) -> str | None:
    """Return the MF6 TDIS TIME_UNITS token, or None when unreadable."""
    if not tdis_path.is_file():
        return None
    try:
        with tdis_path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                tokens = raw.strip().split()
                if len(tokens) >= 2 and tokens[0].upper() == "TIME_UNITS":
                    return tokens[1].upper()
    except OSError:
        return None
    return None


def _resolve_seconds_per_unit(output_dir: Path, model_name: str) -> float:
    """Seconds per native solver time unit, to convert CBC fluxes to m3/s.

    MODFLOW 6 declares the unit as TIME_UNITS in ``{stem}.tdis`` (the TDIS file
    name may differ from the CBC stem, so glob for it). MODFLOW-NWT declares it
    as ITMUNI in ``{model_name}.dis``. Defaults to seconds (1.0).
    """
    tdis_path = output_dir / f"{model_name}.tdis"
    if not tdis_path.is_file():
        tdis_path = next(iter(output_dir.glob("*.tdis")), tdis_path)
    token = _read_time_units_from_tdis(tdis_path)
    if token is not None:
        if token in ("", "UNKNOWN"):
            return 1.0
        try:
            return factor_to_seconds(token)
        except ValueError:
            return 1.0
    return _seconds_per_itmuni(_read_itmuni_from_dis(output_dir / f"{model_name}.dis"))


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

    seconds_per_unit = _resolve_seconds_per_unit(output_dir, model_name)

    cbb = bf.CellBudgetFile(str(cbc_path))
    try:
        drain_key = _find_drain_component(cbb)

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


def _find_drain_component(cbb: object) -> str:
    record_names = [r.decode().strip() for r in cbb.get_unique_record_names()]
    drain_key = next(
        (key for key in record_names if key.lower() in {"drains", "drn", "drain"}),
        None,
    )
    if drain_key is None:
        raise KeyError(f"No DRAIN component in CBC; components were {record_names}")
    return drain_key


def drain_budget_array_to_positive_outflow_by_cell(
    component_field: object,
    *,
    n_cells: int | None = None,
) -> np.ndarray:
    """Convert one signed DRAIN budget array to positive per-cell outflow.

    MODFLOW budgets usually store groundwater release to drains as negative
    fluxes. Some derived arrays are already positive; when no negative finite
    value exists but positive finite values do, the helper keeps the positive
    convention. If ``n_cells`` is provided, leading dimensions are summed as
    layers/stress-period components for the same cell support.
    """

    field = np.asarray(component_field, dtype=float)
    if field.size == 0:
        return np.zeros(0, dtype="float64")
    finite = np.isfinite(field)
    signed = np.where(finite, field, 0.0)
    positive = np.maximum(-signed, 0.0)
    if (
        np.any(finite)
        and not np.any(positive[finite] > 0.0)
        and np.any(signed[finite] > 0.0)
        and not np.any(signed[finite] < 0.0)
    ):
        positive = np.where(finite, signed, 0.0)

    if n_cells is None:
        return positive.reshape(-1).astype("float64", copy=False)

    n_cells_int = int(n_cells)
    if n_cells_int <= 0:
        raise ValueError("n_cells must be > 0 when provided.")
    if positive.size % n_cells_int != 0:
        raise ValueError(
            "DRAIN budget array size must be a multiple of n_cells "
            f"({positive.size} % {n_cells_int} != 0)."
        )
    return positive.reshape(-1, n_cells_int).sum(axis=0).astype("float64", copy=False)


def extract_drain_outflow_by_cell_from_cbc(
    output_dir: Path,
    model_name: str,
    *,
    time_index: pd.DatetimeIndex | None = None,
    n_cells: int | None = None,
) -> pd.DataFrame:
    """Return positive DRAIN outflow by timestep and cell in m3/s.

    The returned frame has one row per CBC timestep and integer cell columns.
    For single-layer B0 runs, ``n_cells`` can be omitted because the full DRAIN
    array is already the cell support. For multi-layer outputs, pass
    ``n_cells`` so layers are summed onto the cell index.
    """

    import flopy.utils.binaryfile as bf

    cbc_path = output_dir / f"{model_name}.cbc"
    if not cbc_path.exists():
        cbc_path = output_dir / f"{model_name}.cbb"
    if not cbc_path.exists():
        raise FileNotFoundError(f"CBC file not found for model {model_name!r} in {output_dir}")

    seconds_per_unit = _resolve_seconds_per_unit(output_dir, model_name)

    cbb = bf.CellBudgetFile(str(cbc_path))
    try:
        drain_key = _find_drain_component(cbb)
        times = cbb.get_times()
        kstpkpers = cbb.get_kstpkper()
        rows: list[np.ndarray | None] = []
        detected_n_cells = int(n_cells) if n_cells is not None else None

        for time, ksk in zip(times, kstpkpers, strict=False):
            try:
                data = cbb.get_data(text=drain_key, kstpkper=ksk, totim=time, full3D=True)
            except Exception:
                data = None
            if not data:
                rows.append(None)
                continue
            vec = drain_budget_array_to_positive_outflow_by_cell(
                data[0],
                n_cells=detected_n_cells,
            )
            if detected_n_cells is None:
                detected_n_cells = int(vec.size)
            elif vec.size != detected_n_cells:
                raise ValueError(
                    "DRAIN per-cell vector length changed across timesteps "
                    f"({vec.size} != {detected_n_cells})."
                )
            rows.append(vec / seconds_per_unit)
    finally:
        cbb.close()

    if detected_n_cells is None:
        raise KeyError("No readable DRAIN data array was found in the CBC file.")

    filled_rows = [
        np.zeros(detected_n_cells, dtype="float64") if row is None else row for row in rows
    ]
    if time_index is not None and len(time_index) == len(filled_rows):
        index = time_index
    else:
        index = pd.Index(times, name="totim")
    return pd.DataFrame(filled_rows, index=index, columns=np.arange(detected_n_cells))


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


__all__ = [
    "drain_budget_array_to_positive_outflow_by_cell",
    "extract_discharge_from_cbc",
    "extract_drain_outflow_by_cell_from_cbc",
    "extract_head_from_hds",
]
