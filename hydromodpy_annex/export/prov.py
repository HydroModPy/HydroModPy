"""W3C PROV-O JSON-LD lineage view for HydroModPy simulations.

Moved here from ``hydromodpy.results.export.prov`` so that the standalone PROV
view lives in the annex and registers on the export port. RO-Crate keeps reading
``build_prov_document`` and the PROV identifiers from the wheel.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from hydromodpy.results.export.context import FairExportContext, to_json
from hydromodpy.results.export.directory import context_from_directory, sealed_root_of
from hydromodpy.results.export.prov import HYDROMODPY_NAMESPACE, build_prov_document
from hydromodpy.results.exporters.port import RUN_VIEW
from hydromodpy.schema.generated_views import PROV_VIEW_FILENAME

if TYPE_CHECKING:
    from hydromodpy.results.exporters.export_spec import PlannedFile
    from hydromodpy.results.exporters.job import ExportJob

PROV_CONTEXT: dict[str, str] = {
    "prov": "http://www.w3.org/ns/prov#",
    "schema": "http://schema.org/",
    "hydromodpy": HYDROMODPY_NAMESPACE,
    "xsd": "http://www.w3.org/2001/XMLSchema#",
}


def serialise_prov(context: FairExportContext) -> dict[str, Any]:
    """Return a standalone JSON-LD PROV-O document for *context*."""
    parts = build_prov_document(context)
    return {
        "@context": PROV_CONTEXT,
        "@graph": [parts["createAction"], *parts["activities"]],
    }


def write_prov(context: FairExportContext, output_path: Path | str) -> Path:
    """Materialize the JSON-LD PROV-O document of *context*."""
    payload = serialise_prov(context)
    out = Path(output_path)
    if out.is_dir() or out.suffix == "":
        out = out / PROV_VIEW_FILENAME
    return to_json(payload, out)


def write_prov_view(
    directory: Path | str,
    *,
    context: FairExportContext | None = None,
) -> Path:
    """Render the PROV-O lineage of a sealed run or job directory, inside it.

    Written as ``prov.jsonld`` beside the seal, from the directory alone.
    """
    root = Path(directory)
    ctx = context or context_from_directory(root)
    return to_json(serialise_prov(ctx), root / PROV_VIEW_FILENAME)


class ProvView:
    """W3C PROV-O JSON-LD lineage for the simulation."""

    name: ClassVar[str] = "prov"
    suffix: ClassVar[str] = ".jsonld"
    writes: ClassVar[tuple[str, ...]] = (RUN_VIEW,)
    natural: ClassVar[tuple[str, ...]] = ()
    instants: ClassVar[str] = "many"
    reprojects: ClassVar[bool] = False
    help: ClassVar[str] = "The PROV provenance record of the run (.jsonld)."

    def write(
        self,
        job: ExportJob | None,
        item: PlannedFile | None,
        dest: Path,
    ) -> list[Path]:
        """Write one planned PROV view file at *dest* and return the paths written."""
        del job, item
        out = Path(dest)
        if out.is_dir() or out.suffix == "":
            out = out / PROV_VIEW_FILENAME
        root = sealed_root_of(out)
        context = context_from_directory(root)
        return [to_json(serialise_prov(context), out)]


__all__ = [
    "PROV_CONTEXT",
    "ProvView",
    "serialise_prov",
    "write_prov",
    "write_prov_view",
]
