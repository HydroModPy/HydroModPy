"""The generic ``url`` data source downloading a single remote file.

Caches downloaded files under data/<variable>/ with a sidecar describing provenance.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import ClassVar
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hydromodpy.core.exceptions import DataRequestError
from hydromodpy.core.io.fetch import download, guard_url, resolve_final_url
from hydromodpy.core.io.file_digest import sha256_of
from hydromodpy.data.provenance.sidecars import (
    Sidecar,
    data_path_for_sidecar,
    load_sidecar,
    write_sidecar,
)
from hydromodpy.data.source.port import (
    FetchRequest,
    FetchResult,
    PayloadKind,
    PeriodNeed,
    Selector,
    require_period,
    require_selectors,
)

_SHA256_PATTERN = r"^[0-9a-fA-F]{64}$"


class UrlSourceOptions(BaseModel):
    """TOML options of a ``source = "url"`` entry.

    ``url`` is mandatory and goes through the same guard as every download
    (scheme, credentials, signature keys, no DNS at read time). ``sha256`` is
    optional; when given it pins the file and must be 64 hexadecimal digits.
    """

    model_config = ConfigDict(extra="forbid")

    url: str = Field(description="Remote URL of the one file this source reads.")
    sha256: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
        description="SHA256 checksum pinning the downloaded file, 64 hexadecimal digits.",
    )
    license: str | None = Field(
        default=None,
        description=(
            "Licence of the downloaded file, written to its sidecar. Unset means undetermined."
        ),
    )

    @model_validator(mode="after")
    def _guarded_url(self) -> UrlSourceOptions:
        guard_url(self.url, pinned=bool(self.sha256), resolve_dns=False)
        return self


class UrlSource:
    """Generic DataSource downloading a remote URL into the local data cache."""

    source_id: ClassVar[str] = "url"
    section: ClassVar[str] = ""
    payload_kind: ClassVar[PayloadKind] = "files"
    extent_crs: ClassVar[str] = "EPSG:2154"
    selectors: ClassVar[tuple[Selector, ...]] = ()
    period_need: ClassVar[PeriodNeed] = "optional"
    writes_out_dir: ClassVar[bool] = True

    variables: tuple[str, ...]
    hosts: tuple[str, ...]

    def __init__(
        self,
        *,
        url: str = "",
        sha256: str | None = None,
        license: str | None = None,
        **kwargs: object,
    ) -> None:
        # url defaults to "" so the contract suite can build the class with no
        # argument; fetch refuses a source that carries no URL.
        self.url = str(url)
        self.sha256 = sha256.strip().lower() if sha256 else None
        self.license = license
        self.variables = (self.section,) if self.section else ("url",)
        host = urlsplit(self.url).hostname
        self.hosts = (host.lower(),) if host else ()

    def fetch(self, request: FetchRequest) -> FetchResult:
        """Download or retrieve from cache the file at self.url."""
        require_selectors(self, request)
        require_period(self, request)
        # Deferred: importing the contracts package loads pandas, so the
        # registry must resolve this class without them.
        from hydromodpy.data.contracts.file_record import FileRecord

        if not self.url:
            raise DataRequestError(f"Url source for section '{self.section}' requires a URL.")

        out_dir = Path(request.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        parsed = urlsplit(self.url)
        host = (parsed.hostname or "unknown").lower().replace(".", "-")[:32]
        suffix = Path(parsed.path).suffix or ".bin"

        # Check existing cached file
        if self.sha256:
            sha8 = self.sha256[:8]
            pattern = f"{self.section}_url_*_{sha8}.*"
            for candidate in out_dir.glob(pattern):
                if (
                    candidate.is_file()
                    and not candidate.name.endswith(".json")
                    and not candidate.name.endswith(".part")
                ):
                    if sha256_of(candidate) == self.sha256:
                        rec = FileRecord.of(candidate, state=None, origin="url")
                        return FetchResult(
                            source_id=self.source_id,
                            kind=self.payload_kind,
                            variables=self.variables,
                            extent=request.extent,
                            period=request.period,
                            files=(rec,),
                        )

        if not self.sha256:
            for sidecar_path in out_dir.glob(f"{self.section}_url_*.json"):
                data_file = data_path_for_sidecar(sidecar_path)
                if data_file and data_file.exists():
                    try:
                        sc = load_sidecar(data_file)
                        if sc.origin == self.url:
                            try:
                                final_info = resolve_final_url(self.url, bounds=request.bounds)
                                if (
                                    (final_info.etag and sc.etag and final_info.etag == sc.etag)
                                    or (
                                        final_info.last_modified
                                        and sc.last_modified
                                        and final_info.last_modified == sc.last_modified
                                    )
                                    or (not final_info.etag and not final_info.last_modified)
                                ):
                                    rec = FileRecord.of(data_file, state=None, origin="url")
                                    return FetchResult(
                                        source_id=self.source_id,
                                        kind=self.payload_kind,
                                        variables=self.variables,
                                        extent=request.extent,
                                        period=request.period,
                                        files=(rec,),
                                    )
                            except Exception:
                                pass
                    except Exception:
                        pass

        # Otherwise download
        sha8 = (
            self.sha256[:8]
            if self.sha256
            else hashlib.sha256(self.url.encode("utf-8")).hexdigest()[:8]
        )
        dest = out_dir / f"{self.section}_url_{host}_{sha8}{suffix}"

        fetched = download(self.url, dest, bounds=request.bounds, sha256=self.sha256)
        sidecar = Sidecar(
            source="url",
            origin=self.url,
            sha256=fetched.sha256,
            etag=fetched.etag,
            last_modified=fetched.last_modified,
            license=self.license,
            state="raw",
        )
        write_sidecar(dest, sidecar)
        rec = FileRecord.of(dest, state=None, origin="url")

        return FetchResult(
            source_id=self.source_id,
            kind=self.payload_kind,
            variables=self.variables,
            extent=request.extent,
            period=request.period,
            files=(rec,),
        )


# Section-specific subclasses for single-file sections
class CrossingsUrl(UrlSource):
    section = "crossings"


class DemUrl(UrlSource):
    section = "dem"


class EtpUrl(UrlSource):
    section = "etp"


class GeologyUrl(UrlSource):
    section = "geology"


class HumidityUrl(UrlSource):
    section = "humidity"


class HydrographyUrl(UrlSource):
    section = "hydrography"


class LakeAbacusUrl(UrlSource):
    section = "lake_abacus"


class LakeBathymetryUrl(UrlSource):
    section = "lake_bathymetry"


class LakeGeometryUrl(UrlSource):
    section = "lake_geometry"


class LayerBaseUrl(UrlSource):
    section = "layer_base"


class PrecipitationUrl(UrlSource):
    section = "precipitation"


class RadiationUrl(UrlSource):
    section = "radiation"


class RechargeUrl(UrlSource):
    section = "recharge"


class RunoffUrl(UrlSource):
    section = "runoff"


class SoilCapacityUrl(UrlSource):
    section = "soil_capacity"


class SoilMoistureUrl(UrlSource):
    section = "soil_moisture"


class SubstratumUrl(UrlSource):
    section = "substratum"


class TemperatureUrl(UrlSource):
    section = "temperature"


class WindUrl(UrlSource):
    section = "wind"


__all__ = [
    "CrossingsUrl",
    "DemUrl",
    "EtpUrl",
    "GeologyUrl",
    "HumidityUrl",
    "HydrographyUrl",
    "LakeAbacusUrl",
    "LakeBathymetryUrl",
    "LakeGeometryUrl",
    "LayerBaseUrl",
    "PrecipitationUrl",
    "RadiationUrl",
    "RechargeUrl",
    "RunoffUrl",
    "SoilCapacityUrl",
    "SoilMoistureUrl",
    "SubstratumUrl",
    "TemperatureUrl",
    "UrlSource",
    "UrlSourceOptions",
    "WindUrl",
]
