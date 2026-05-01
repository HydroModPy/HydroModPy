"""Export adapter for a single :class:`Run`.

Routes file-write operations off the ``Run`` facade so the latter stays a
read-only view. Delegates the heavy lifting to
:meth:`SimulationCatalog.export`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from hydromodpy.results.run import Run


_EXT_BY_FMT: dict[str, str] = {
    "csv": "csv",
    "netcdf": "nc",
    "vtu": "vtu",
    "geotiff": "tif",
    "shapefile": "shp",
}


class RunExportAdapter:
    """File-write helpers bound to a single :class:`Run`."""

    def __init__(self, run: Run) -> None:
        self._run = run

    def to_csv(self, path: Path | str | None = None) -> pd.DataFrame:
        run = self._run
        df = run._catalog.connection.execute(
            "SELECT station_id, variable, datetime, value, unit "
            "FROM timeseries WHERE sim_id = ? "
            "ORDER BY station_id, variable, datetime",
            [run.sim_id],
        ).fetchdf()
        if path is not None:
            df.to_csv(str(path), index=False)
        return df

    def export(
        self,
        variable: str = "*",
        fmt: str = "csv",
        path: str | Path | None = None,
        **kwargs,
    ) -> None:
        """Export results to a file.

        Parameters
        ----------
        variable : str
            Variable name or ``"*"`` for all timeseries.
        fmt : str
            ``"csv"``, ``"netcdf"``, ``"geotiff"``, ``"vtu"``, ``"shapefile"``.
        path : Path, optional
            Output file path. Defaults to
            ``<workspace>/exports/<name>/<variable>.<ext>``.
        """
        run = self._run
        if path is None:
            ext = _EXT_BY_FMT.get(fmt, fmt)
            out_dir = run._catalog.project_path / "exports" / (run.name or run.sim_id)
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / (f"{variable}.{ext}" if variable != "*" else f"timeseries.{ext}")
        run._catalog.export(run.sim_id, variable, fmt, path, **kwargs)
