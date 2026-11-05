"""The part every Whitebox sub-backend shares with its raster backend.

A sub-backend runs its tools in the ``WbEnvironment`` of the raster backend
that created it, so the three of them read and write the same rasters.
"""

from __future__ import annotations

from hydromodpy.core.console import progress
from hydromodpy.spatial.delineation.whitebox_workflows_backend.isolated import run_depression_tool
from hydromodpy.spatial.delineation.whitebox_workflows_backend.raster import WhiteboxRasterBackend

__all__ = [
    "WhiteboxComponent",
]


class WhiteboxComponent:
    """Mixin sharing the WbEnvironment of a parent :class:`WhiteboxRasterBackend`."""

    def __init__(self, raster: WhiteboxRasterBackend) -> None:
        self._raster = raster

    @property
    def env(self):
        """The ``WbEnvironment`` shared with the raster backend."""
        return self._raster.env

    def run(self, operation, *args, **kwargs):
        """Run one Whitebox operation through the raster backend."""
        return self._raster.run_env_operation(operation, *args, **kwargs)

    def read_raster(self, path: str):
        return self._raster.read_raster(path)

    def write_raster(self, raster, path: str) -> None:
        self._raster.write_raster(raster, path)

    def read_vector(self, path: str):
        return self._raster.read_vector(path)

    def write_vector(self, vector, path: str) -> None:
        self._raster.write_vector(vector, path)

    def run_depression_tool(self, tool: str, dem, **options):
        """Run a depression tool on one worker, in a child interpreter.

        One worker makes the output reproducible. The child keeps this
        interpreter alive when Whitebox panics, see :mod:`.isolated`.
        """
        with (
            self._raster.single_threaded(),
            progress.status(f"Whitebox: {tool.replace('_', ' ')}"),
            self._raster.silence_stdio(),
        ):
            return run_depression_tool(
                self.env,
                tool,
                dem,
                options=options,
                max_procs=self.env.max_procs,
                verbose=self._raster.verbose,
            )
