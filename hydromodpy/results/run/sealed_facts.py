"""The facts of one sealed run, read from its ``manifest.json`` in the shapes a table reads.

A table of runs (``summary/by_case``, ``hmp ls``) reads from the seal
of each run its metrics at the station and on the variable of its headline
score, its global parameters, the overrides of its lineage, the dotted paths of
its manifest, and where its catchment lies. A seal that does not read under
this version is refused by name: its row would otherwise be missing without a
word.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from pydantic import ValidationError

from hydromodpy.core.exceptions import DataError
from hydromodpy.core.scope import CATCHMENT
from hydromodpy.core.version import __version__ as HYDROMODPY_VERSION
from hydromodpy.results.metric_rule import HEADLINE_WINDOW
from hydromodpy.results.run.ranking import first_present, is_finite

if TYPE_CHECKING:
    from hydromodpy.results.record.manifest import RunSeal


class UnreadableManifestError(DataError):
    """A sealed run or session whose seal does not read under this version."""


@dataclass(frozen=True, slots=True)
class SealedRunFacts:
    """What the seal of one run says, in the shapes a table of runs reads."""

    manifest: RunSeal
    metrics: dict[str, float | None]
    parameters: dict[str, float | None]
    document: dict[str, Any]

    @property
    def overrides(self) -> dict[str, Any]:
        """Dotted paths ``--set`` or ``--overlay`` changed, as the seal recorded them."""
        return dict(self.manifest.lineage.overrides)


def read_run_facts(run_dir: str | Path) -> SealedRunFacts | None:
    """Return the facts of a sealed run directory, ``None`` when it carries no manifest.

    Raises
    ------
    UnreadableManifestError
        When ``manifest.json`` does not read under the current schema.
    """
    from hydromodpy.results.record.label import read_sealed_manifest

    try:
        manifest = read_sealed_manifest(run_dir)
    except ValidationError as exc:
        raise UnreadableManifestError(
            f"{run_dir}: manifest.json does not read under HydroModPy {HYDROMODPY_VERSION} "
            f"({exc.error_count()} error(s), first: {exc.errors()[0]['msg']}). Upgrade HydroModPy "
            "if a newer version sealed it, or move it to the trash with hmp catalog delete."
        ) from exc
    if manifest is None:
        return None
    metrics = _headline_metrics(manifest)
    parameters = {row.name: row.value for row in manifest.parameters if row.zone == CATCHMENT}
    document = manifest.model_dump(mode="json", by_alias=True)
    document["metrics"] = dict(metrics)
    document["parameters"] = dict(parameters)
    return SealedRunFacts(
        manifest=manifest, metrics=metrics, parameters=parameters, document=document
    )


def _headline_metrics(manifest: RunSeal) -> dict[str, float | None]:
    """Return metric -> value at the station and variable of the headline score."""
    score = manifest.score
    rows = [row for row in manifest.metrics if row.window_name in (HEADLINE_WINDOW, None)]
    if score is not None:
        rows = [
            row for row in rows if row.station == score.station and row.variable == score.variable
        ]
    elif len({(row.station, row.variable) for row in rows}) > 1:
        rows = []
    values: dict[str, float | None] = {row.metric: row.value for row in rows}
    if score is not None and score.metric not in values:
        values[score.metric] = score.value
    return values


def overrides_text(overrides: Mapping[str, Any]) -> str:
    """Return ``path=value`` pairs joined by ``, ``, sorted by path; empty without any."""
    return ", ".join(f"{path}={_value_text(overrides[path])}" for path in sorted(overrides))


def _value_text(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, default=str)
    return str(value)


_CATCHMENT_AREA_KEYS: Final[tuple[str, ...]] = ("catch_area", "catchment_area_km2")
"""Keys of ``geometry.catchment`` holding the delineated area, km2."""


def place_of(manifest: RunSeal) -> dict[str, float | None]:
    """Return the area, the DEM cell and the snapped outlet of a run.

    The site block of the seal first, then the catchment metadata of its
    geometry (``catch_area``, ``dem_res``, ``x_outlet_snapped``), which the
    delineation writes.
    """
    site, catchment = manifest.site, manifest.geometry.catchment
    snapped = site.snapped_outlet if site is not None else None
    if snapped is None:
        x, y = (
            _number(catchment.get("x_outlet_snapped")),
            _number(catchment.get("y_outlet_snapped")),
        )
        snapped = (x, y) if x is not None and y is not None else None
    return {
        "area_km2": first_present(
            site.area_km2 if site is not None else None,
            *(_number(catchment.get(key)) for key in _CATCHMENT_AREA_KEYS),
        ),
        "dem_resolution_m": first_present(
            site.dem_resolution_m if site is not None else None,
            _number(catchment.get("dem_res")),
        ),
        "snapped_x": None if snapped is None else snapped[0],
        "snapped_y": None if snapped is None else snapped[1],
    }


def _number(value: Any) -> float | None:
    """Return a metadata value as a finite float, ``None`` when it is not one."""
    return float(value) if is_finite(value) else None


__all__ = [
    "SealedRunFacts",
    "UnreadableManifestError",
    "overrides_text",
    "place_of",
    "read_run_facts",
]
