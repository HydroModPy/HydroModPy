"""The generic ``file`` data source reading local files declared by the user.

Serves user-provided files or directories across all data sections.
A path is verified against execution bounds and sealed into FileRecord instances.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core.exceptions import DataRequestError
from hydromodpy.data.source.port import (
    FetchRequest,
    FetchResult,
    PayloadKind,
    PeriodNeed,
    Selector,
    require_period,
    require_selectors,
)

if TYPE_CHECKING:
    from hydromodpy.data.contracts.file_record import FileRecord


class FileSource:
    """Generic DataSource reading user-provided local files or directories."""

    source_id: ClassVar[str] = "file"
    section: ClassVar[str] = ""
    payload_kind: ClassVar[PayloadKind] = "files"
    extent_crs: ClassVar[str] = "EPSG:2154"
    selectors: ClassVar[tuple[Selector, ...]] = ()
    period_need: ClassVar[PeriodNeed] = "optional"
    writes_out_dir: ClassVar[bool] = False

    variables: tuple[str, ...]
    hosts: tuple[str, ...]

    def __init__(self, *, path: str | Path | None = None, **kwargs: object) -> None:
        self.path = Path(path) if path is not None else None
        self.variables = (self.section,) if self.section else ("file",)
        self.hosts = ()

    def fetch(self, request: FetchRequest) -> FetchResult:
        """Read the configured file or directory and return its FileRecords."""
        require_selectors(self, request)
        require_period(self, request)
        if self.path is None:
            raise DataRequestError(f"File source for section '{self.section}' requires a path.")

        if request.bounds is not None and request.bounds.allowed_roots is not None:
            request.bounds.require_path(self.path, why=f"data source '{self.source_id}'")

        if not self.path.exists():
            raise FileNotFoundError(
                f"[data.{self.section}] file source path not found: {self.path}"
            )

        # Deferred: importing the contracts package loads pandas, so the
        # registry must resolve this class without them (the deferred rule).
        from hydromodpy.data.contracts.file_record import FileRecord

        records: tuple[FileRecord, ...]
        if self.path.is_file():
            records = (FileRecord.of(self.path, state=None, origin="file"),)
        elif self.path.is_dir():
            files = sorted(
                f for f in self.path.iterdir() if f.is_file() and not f.name.startswith(".")
            )
            records = tuple(FileRecord.of(f, state=None, origin="file") for f in files)
        else:
            records = ()

        return FetchResult(
            source_id=self.source_id,
            kind=self.payload_kind,
            variables=self.variables,
            extent=request.extent,
            period=request.period,
            files=records,
        )


# Section-specific subclasses for the plugin registry (one subclass per section)
class CrossingsFile(FileSource):
    section = "crossings"


class DemFile(FileSource):
    section = "dem"


class EtpFile(FileSource):
    section = "etp"


class GeologyFile(FileSource):
    section = "geology"


class HumidityFile(FileSource):
    section = "humidity"


class HydrographyFile(FileSource):
    section = "hydrography"


class HydrometryFile(FileSource):
    section = "hydrometry"


class IntermittencyFile(FileSource):
    section = "intermittency"


class LakeAbacusFile(FileSource):
    section = "lake_abacus"


class LakeBathymetryFile(FileSource):
    section = "lake_bathymetry"


class LakeGeometryFile(FileSource):
    section = "lake_geometry"


class LakeInflowFile(FileSource):
    section = "lake_inflow"


class LakeLevelsFile(FileSource):
    section = "lake_levels"


class LakeOutflowFile(FileSource):
    section = "lake_outflow"


class LakeWithdrawalFile(FileSource):
    section = "lake_withdrawal"


class LayerBaseFile(FileSource):
    section = "layer_base"


class OceanicFile(FileSource):
    section = "oceanic"


class PiezometryFile(FileSource):
    section = "piezometry"


class PrecipitationFile(FileSource):
    section = "precipitation"


class RadiationFile(FileSource):
    section = "radiation"


class RechargeFile(FileSource):
    section = "recharge"


class RunoffFile(FileSource):
    section = "runoff"


class SoilCapacityFile(FileSource):
    section = "soil_capacity"


class SoilMoistureFile(FileSource):
    section = "soil_moisture"


class SubstratumFile(FileSource):
    section = "substratum"


class TemperatureFile(FileSource):
    section = "temperature"


class WaterQualityFile(FileSource):
    section = "water_quality"


class WindFile(FileSource):
    section = "wind"


__all__ = [
    "CrossingsFile",
    "DemFile",
    "EtpFile",
    "FileSource",
    "GeologyFile",
    "HumidityFile",
    "HydrographyFile",
    "HydrometryFile",
    "IntermittencyFile",
    "LakeAbacusFile",
    "LakeBathymetryFile",
    "LakeGeometryFile",
    "LakeInflowFile",
    "LakeLevelsFile",
    "LakeOutflowFile",
    "LakeWithdrawalFile",
    "LayerBaseFile",
    "OceanicFile",
    "PiezometryFile",
    "PrecipitationFile",
    "RadiationFile",
    "RechargeFile",
    "RunoffFile",
    "SoilCapacityFile",
    "SoilMoistureFile",
    "SubstratumFile",
    "TemperatureFile",
    "WaterQualityFile",
    "WindFile",
]
