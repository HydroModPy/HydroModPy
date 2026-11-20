"""Resolve declared user files and URLs before run registration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.data.contracts.file_record import FileRecord
from hydromodpy.data.loading._dispatch import VARIABLE_SPECS
from hydromodpy.data.provenance.lockfile import LockedInputs
from hydromodpy.data.source.file import FileSource
from hydromodpy.data.source.port import FetchRequest
from hydromodpy.data.source.url import UrlSource


@dataclass
class ResolvedInputs:
    """Pre-resolved FileRecords for all file and url sources of a project."""

    dem: FileRecord | None = None
    records: dict[str, tuple[FileRecord, ...]] = field(default_factory=dict)

    def for_variable(self, variable: str) -> tuple[FileRecord, ...]:
        """Return the resolved FileRecords for a specific data section."""
        return self.records.get(variable, ())

    @property
    def all_records(self) -> tuple[FileRecord, ...]:
        """Return every resolved FileRecord in a single tuple."""
        res: list[FileRecord] = []
        if self.dem is not None:
            res.append(self.dem)
        for recs in self.records.values():
            res.extend(recs)
        return tuple(res)


def resolve_inputs(
    cfg: Any,
    *,
    bounds: Bounds | None = None,
    data_dir: Path | None = None,
    locked: LockedInputs | None = None,
) -> ResolvedInputs:
    """Resolve file and url sources of each data section into FileRecords before run registration.

    Each file source goes through :class:`FileSource`, so ``bounds.allowed_roots``
    holds for every section and not only for the DEM. Each url source fills the
    cache under ``bounds``. The DEM goes through its own resolver, whose refusals
    reach the caller. *locked* is the lockfile of a frozen run: a file or url source
    the lockfile does not pin is refused, and ``None`` is a run that is not frozen.
    """
    from hydromodpy.data.variables.dem.resolver import resolve_dem

    effective_bounds = bounds if bounds is not None else Bounds()
    effective_data_dir = Path(data_dir) if data_dir is not None else Path("data")
    dem_record = resolve_dem(cfg, data_dir=effective_data_dir, bounds=effective_bounds)

    records_by_section: dict[str, list[FileRecord]] = {}
    data_cfg = getattr(cfg, "data", None)
    workspace = getattr(cfg, "workspace", None)
    declared_root = getattr(workspace, "project_root", None)
    project_root = Path(declared_root or Path.cwd()).resolve()

    if data_cfg is not None:
        for var_name in VARIABLE_SPECS:
            if var_name == "dem":
                continue
            section_cfg = getattr(data_cfg, var_name, None)
            if section_cfg is None:
                continue
            sources = getattr(section_cfg, "sources", None) or ()
            for src in sources:
                source_kind = getattr(src, "source", None)
                out_dir = effective_data_dir / var_name

                if source_kind == "file":
                    path_val = getattr(src, "path", None)
                    if path_val:
                        p = Path(path_val)
                        resolved_path = (project_root / p).resolve() if not p.is_absolute() else p
                        fs = FileSource(path=resolved_path, locked=locked)
                        fs.section = var_name
                        fs.variables = (var_name,)
                        req = FetchRequest(out_dir=out_dir, bounds=effective_bounds)
                        fetch_res = fs.fetch(req)
                        records_by_section.setdefault(var_name, []).extend(fetch_res.files)

                elif source_kind == "url":
                    url_val = getattr(src, "url", None)
                    if url_val:
                        sha256_val = getattr(src, "sha256", None)
                        license_val = getattr(src, "license", None)
                        us = UrlSource(
                            url=url_val, sha256=sha256_val, license=license_val, locked=locked
                        )
                        us.section = var_name
                        us.variables = (var_name,)
                        req = FetchRequest(out_dir=out_dir, bounds=effective_bounds)
                        fetch_res = us.fetch(req)
                        records_by_section.setdefault(var_name, []).extend(fetch_res.files)

    final_records = {var: tuple(recs) for var, recs in records_by_section.items()}
    return ResolvedInputs(dem=dem_record, records=final_records)


__all__ = ["ResolvedInputs", "resolve_inputs"]
