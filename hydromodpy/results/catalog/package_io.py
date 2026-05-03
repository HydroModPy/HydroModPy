"""``.hmp`` package import/export wrappers.

Both methods are thin shims around
:mod:`hydromodpy.results.exporters.hmp_package`. They live here so the
catalog facade exposes a single, discoverable entry point for portable
archive round-trips.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID


class PackageIOMixin:
    """``.hmp`` archive helpers for :class:`SimulationCatalog`."""

    def export_package(
        self,
        sim_id: str | UUID,
        output_path: Path | str,
    ) -> Path:
        """Export a simulation as a portable ``.hmp`` archive (tar.zst).

        Returns the path to the produced ``.hmp`` file.
        """
        from hydromodpy.results.exporters.hmp_package import (
            export_hmp_package,
        )

        return export_hmp_package(self, sim_id, output_path)

    def import_package(
        self,
        package_path: Path | str,
        *,
        force: bool = False,
        as_project: str | None = None,
        dematerialise_inputs: bool = True,
        dry_run: bool = False,
    ) -> str:
        """Import a ``.hmp`` archive into this workspace.

        SHA-256 checksums in the archive manifest are verified before
        any catalog mutation. ``as_project`` overrides the project
        column on import. ``dematerialise_inputs`` copies the bundled
        inputs into ``<workspace>/data/<role>/`` and rewrites the stored
        config paths to point at the new locations.
        """
        from hydromodpy.results.exporters.hmp_package import (
            import_hmp_package,
        )

        return import_hmp_package(
            self,
            package_path,
            force=force,
            as_project=as_project,
            dematerialise_inputs=dematerialise_inputs,
            dry_run=dry_run,
        )
