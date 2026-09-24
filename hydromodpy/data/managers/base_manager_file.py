"""Managers of variables read only from the user's own files.

A lake abacus, a lake bathymetry and a lake footprint have no provider: each
is a file the user supplies, converted once to a storage format and indexed
in the cache. What differs between the three is the converter, the kind of
record it returns and what the index records about it; this base holds the
rest.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, Literal

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.managers.base_manager_common import CUSTOM_SOURCE, SourceTable
from hydromodpy.data.provenance.derived import custom_derived_dir


class BaseFileManager(SourceTable):
    """Load user files through ``read_custom`` and index the converted copies."""

    RECORD_KIND: ClassVar[Literal["tables", "fields"]] = "fields"
    """The member of :class:`LoadResult` the records land in."""

    def __init__(
        self,
        *,
        config: Any,
        catalog: Any,
        project_extent: tuple | None = None,
        project_period: tuple | None = None,
        data_dir: Path | None = None,
    ):
        self.config = config
        self.catalog = catalog
        self.project_extent = project_extent
        self.project_period = project_period
        self.data_dir = Path(data_dir) if data_dir else None

    def load(self) -> LoadResult:
        """Load every configured source."""
        result = LoadResult()
        for source_cfg in self.config.sources:
            getattr(result, self.RECORD_KIND).extend(self._fetch_from_source(source_cfg))
        return result

    def load_custom(self, source_cfg: Any) -> list[Any]:
        """Convert the user's file and index the copy that landed on disk."""
        records = self.read_custom(
            source_cfg, derived_dir=custom_derived_dir(self.data_dir, self.VARIABLE_NAME)
        )
        if self.catalog is not None:
            for record in records:
                if isinstance(record.data, Path):
                    self.catalog.register(
                        variable=self.VARIABLE_NAME,
                        source=CUSTOM_SOURCE,
                        file_path=str(record.data),
                        is_custom=True,
                        **self.index_fields(record),
                    )
        return records

    def read_custom(self, source_cfg: Any, *, derived_dir: Path | None) -> list[Any]:
        """Read one source config into records; each variable names its converter."""
        raise NotImplementedError

    def index_fields(self, record: Any) -> dict[str, Any]:
        """What the cache index records about one converted file, beyond its path."""
        return {"bbox": record.bbox, "crs": record.crs}


__all__ = ["BaseFileManager"]
