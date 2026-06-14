"""``.hmp`` package import/export wrappers.

Both methods are thin shims around
:mod:`hydromodpy.results.exporters.hmp_package`. They live here so the
catalog facade exposes a single, discoverable entry point for portable
archive round-trips.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from hydromodpy.results.catalog.audit import audited


class PackageIOMixin:
    """``.hmp`` archive helpers for :class:`Catalog`."""

    @audited("export")
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

    @audited("export", sim_id_arg="__none__", project_arg=None)
    def export_package_multi(
        self,
        sim_ids: list[str],
        output_path: Path | str,
    ) -> Path:
        """Export several simulations as one multi-run ``.hmp`` archive.

        Each run is a self-contained single-run archive nested in the
        container; :meth:`import_package_multi` restores them all.
        """
        from hydromodpy.results.exporters.hmp_package import (
            export_hmp_package_multi,
        )

        return export_hmp_package_multi(self, sim_ids, output_path)

    @audited("import", sim_id_arg="__none__", project_arg=None)
    def import_package_multi(
        self,
        package_path: Path | str,
        *,
        force: bool = False,
        dematerialise_inputs: bool = True,
        dry_run: bool = False,
    ) -> list[str]:
        """Import a ``.hmp`` archive (single- or multi-run); return the sim_ids.

        Auto-detects the archive type: a single-run archive yields a one-element
        list, a multi-run container yields one id per nested run.
        """
        from hydromodpy.results.exporters.hmp_package import (
            import_hmp_package_multi,
        )

        return import_hmp_package_multi(
            self,
            package_path,
            force=force,
            dematerialise_inputs=dematerialise_inputs,
            dry_run=dry_run,
        )

    @audited("import", sim_id_arg="__none__", project_arg=None)
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
