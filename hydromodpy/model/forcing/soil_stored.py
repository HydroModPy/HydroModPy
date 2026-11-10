"""Write and read the soil reservoir outputs as ``soil.npz`` and ``soil.json``.

The product store keeps one directory per key, and this codec writes the
``soil`` kind into it. Every array is stored with its dtype, so a read rebuilds
the exact object the data step computed. The kernel parameters are rebuilt by
``soil_parameters`` from the stored ``ru_mm`` and the config the caller hands
in, which the key already guarantees equals the one the run read. The three
records are rebuilt by ``grid_field_record`` on the loaded precipitation, so
their bbox and CRS are read back, not stored.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import numpy as np

from hydromodpy.model.contracts import LoadResultProto
from hydromodpy.model.forcing.soil_columns import SoilColumns
from hydromodpy.model.forcing.soil_config import SoilReservoirConfig
from hydromodpy.model.forcing.soil_forcing import SoilForcings, soil_parameters
from hydromodpy.model.forcing.soil_grids import grid_field_record
from hydromodpy.model.soil.kernel import SoilFluxes, SoilState

SCHEMA_VERSION = "hydromodpy.soil_product.v1"
"""Version of this stored format, written in the product key."""

_NPZ = "soil.npz"
_JSON = "soil.json"


def _grid_values(result: LoadResultProto) -> np.ndarray:
    """The ``(T, ny, nx)`` values of the one grid ``result`` holds."""
    record = result.fields[0]
    return np.asarray(record.data[record.variable].values)


def _grid_coord(result: LoadResultProto, name: str) -> np.ndarray:
    """The ``name`` coordinate of the one grid ``result`` holds."""
    return np.asarray(result.fields[0].data[name].values)


def write_soil_forcings(soil: SoilForcings, directory: Path) -> None:
    """Write ``soil`` into ``directory`` as ``soil.npz`` and ``soil.json``."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    fluxes = soil.fluxes
    np.savez(
        directory / _NPZ,
        days=soil.days,
        precipitation=soil.precipitation,
        etp=soil.etp,
        recharge_grid=_grid_values(soil.recharge),
        residual_etp_grid=_grid_values(soil.residual_etp),
        runoff_grid=_grid_values(soil.runoff),
        x=_grid_coord(soil.recharge, "x"),
        y=_grid_coord(soil.recharge, "y"),
        fluxes_etr=fluxes.etr,
        fluxes_residual_etp=fluxes.residual_etp,
        fluxes_recharge=fluxes.recharge,
        fluxes_runoff=fluxes.runoff,
        fluxes_runoff_cn=fluxes.runoff_cn,
        fluxes_soil_storage=fluxes.soil_storage,
        fluxes_transit_storage=fluxes.transit_storage,
        fluxes_cn_storage=fluxes.cn_storage,
        fluxes_lag_storage=fluxes.lag_storage,
        fluxes_soil_storage_start=fluxes.soil_storage_start,
        fluxes_transit_storage_start=fluxes.transit_storage_start,
        fluxes_cn_storage_start=fluxes.cn_storage_start,
        fluxes_lag_storage_start=fluxes.lag_storage_start,
        end_soil_mm=fluxes.end.soil_mm,
        end_transit_mm=fluxes.end.transit_mm,
        end_cn_storage_mm=fluxes.end.cn_storage_mm,
        columns_cell_index=soil.columns.cell_index,
        columns_class_index=soil.columns.class_index,
        columns_x=soil.columns.x,
        columns_y=soil.columns.y,
        columns_ru_shape=soil.columns.ru_shape,
        columns_cell_fraction=soil.columns.cell_fraction,
        columns_basin_weight=soil.columns.basin_weight,
        ru_mm=soil.parameters.ru_mm,
    )
    (directory / _JSON).write_text(
        json.dumps(
            {
                "spinup_cycles": soil.spinup_cycles,
                "never_full_columns": soil.never_full_columns,
                "crs": soil.crs,
                "raster_mean_mm": soil.columns.raster_mean_mm,
            }
        ),
        encoding="utf-8",
    )


def read_soil_forcings(
    directory: Path, *, like: LoadResultProto, config: SoilReservoirConfig
) -> SoilForcings:
    """Rebuild the stored ``SoilForcings``, bit for bit, from ``directory``.

    ``like`` is the loaded precipitation: it gives the wrapper class and the
    record the three grids inherit their bbox and CRS from. ``config`` is the
    config of the run, so ``soil_parameters`` rebuilds the kernel parameters
    from the stored ``ru_mm`` exactly as the data step did.
    """
    directory = Path(directory)
    try:
        with np.load(directory / _NPZ) as stored:
            arrays = {name: stored[name] for name in stored.files}
        meta = json.loads((directory / _JSON).read_text(encoding="utf-8"))
        return _decode(arrays, meta, like=like, config=config)
    except (OSError, KeyError, EOFError, zipfile.BadZipFile) as exc:
        raise ValueError(
            f"The stored soil product in {directory} is unreadable: {exc!r}. Delete it."
        ) from exc


def _decode(
    arrays: dict[str, np.ndarray],
    meta: dict,
    *,
    like: LoadResultProto,
    config: SoilReservoirConfig,
) -> SoilForcings:
    x = arrays["x"]
    y = arrays["y"]
    days = arrays["days"]
    columns = SoilColumns(
        cell_index=arrays["columns_cell_index"],
        class_index=arrays["columns_class_index"],
        x=arrays["columns_x"],
        y=arrays["columns_y"],
        ru_shape=arrays["columns_ru_shape"],
        cell_fraction=arrays["columns_cell_fraction"],
        basin_weight=arrays["columns_basin_weight"],
        raster_mean_mm=meta["raster_mean_mm"],
    )
    fluxes = SoilFluxes(
        etr=arrays["fluxes_etr"],
        residual_etp=arrays["fluxes_residual_etp"],
        recharge=arrays["fluxes_recharge"],
        runoff=arrays["fluxes_runoff"],
        runoff_cn=arrays["fluxes_runoff_cn"],
        soil_storage=arrays["fluxes_soil_storage"],
        transit_storage=arrays["fluxes_transit_storage"],
        cn_storage=arrays["fluxes_cn_storage"],
        lag_storage=arrays["fluxes_lag_storage"],
        soil_storage_start=arrays["fluxes_soil_storage_start"],
        transit_storage_start=arrays["fluxes_transit_storage_start"],
        cn_storage_start=arrays["fluxes_cn_storage_start"],
        lag_storage_start=arrays["fluxes_lag_storage_start"],
        end=SoilState(
            soil_mm=arrays["end_soil_mm"],
            transit_mm=arrays["end_transit_mm"],
            cn_storage_mm=arrays["end_cn_storage_mm"],
        ),
    )

    record = like.fields[0]
    n_cells = x.size * y.size
    recharge_field = grid_field_record(
        "recharge",
        arrays["recharge_grid"].reshape(len(days), n_cells),
        x=x,
        y=y,
        days=days,
        like=record,
    )
    residual_etp_field = grid_field_record(
        "etp",
        arrays["residual_etp_grid"].reshape(len(days), n_cells),
        x=x,
        y=y,
        days=days,
        like=record,
    )
    runoff_field = grid_field_record(
        "runoff",
        arrays["runoff_grid"].reshape(len(days), n_cells),
        x=x,
        y=y,
        days=days,
        like=record,
    )
    holding = type(like)
    return SoilForcings(
        recharge=holding(fields=[recharge_field]),
        residual_etp=holding(fields=[residual_etp_field]),
        runoff=holding(fields=[runoff_field]),
        days=days,
        precipitation=arrays["precipitation"],
        etp=arrays["etp"],
        fluxes=fluxes,
        columns=columns,
        config=config,
        parameters=soil_parameters(config, arrays["ru_mm"]),
        spinup_cycles=meta["spinup_cycles"],
        never_full_columns=meta["never_full_columns"],
        crs=meta["crs"],
    )


__all__ = ["SCHEMA_VERSION", "read_soil_forcings", "write_soil_forcings"]
