"""Resolve the data a project's TOML files reference, the way a run resolves them.

One resolver for the example catalog (``python -m tools.dev examples manifest``) and for
``hmp publish --package``: it reads every authored configuration through the
loader of a run, so a step file that only overrides ``station_ids``
inherits the source of its parent, and returns the files of ``data/`` each
one names, the station rows their registries hold, and the files of the
project it names. A reference it cannot resolve to exactly one file is an
error, never a pick.

``authored_configs``, ``authored_files`` and ``project_data`` find the data that the
TOML files of a project reference, the way a run resolves them.
"""

from __future__ import annotations

import csv
import os
import re
from pathlib import Path

from hydromodpy.core.config_kit.root import RootConfig
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.payload.index import PayloadStation
from hydromodpy.core.toml_io.loader import load_toml_with_base_config

AUTHORED_SUFFIXES: tuple[str, ...] = (".toml", ".md", ".py")
"""What counts as a file the author of a project wrote, at the project root."""

_STATION_FILE_RE = re.compile(
    r"^(?P<prefix>.+)_custom_(?P<station>.+)_(?P<start>\d{8})_(?P<end>\d{8})_(?P<freq>[A-Za-z]+)"
    r"\.(?P<suffix>csv|parquet)$"
)
"""The ``data/<variable>/`` naming contract, which is how a station id resolves."""


def authored_files(project_dir: Path) -> list[Path]:
    """Return the files at the project root that its author wrote.

    A leading underscore or dot marks a scratch or machine-local file, which
    is how a working checkout keeps its own clutter out of what ships.
    """
    return sorted(
        path
        for path in project_dir.iterdir()
        if path.is_file()
        and path.suffix in AUTHORED_SUFFIXES
        and not path.name.startswith(("_", "."))
    )


def authored_configs(project_dir: Path) -> list[Path]:
    """Return the TOML configurations among the authored files of a project."""
    return [path for path in authored_files(project_dir) if path.suffix == ".toml"]


def project_data(
    project_dir: Path, data_root: Path, *, root: RootConfig | None
) -> tuple[list[Path], tuple[PayloadStation, ...]]:
    """Resolve every data file and station row the project's authored TOMLs reference.

    Each config is read through the run pipeline's own loader, so a variant
    that only overrides ``station_ids`` inherits the ``source`` and ``path``
    its parent declared, exactly as it does at run time. The union over all of
    them and not just over one entry point: every step file and run variant
    travels with the project, so each one has to find its inputs. A path that
    names a file of the project is returned as it is. The caller passes the
    ``RootConfig`` it holds, or ``None`` to read a file the way it is written.
    """
    found: set[Path] = set()
    stations: dict[tuple[str, str], PayloadStation] = {}
    for config in authored_configs(project_dir):
        document = load_toml_with_base_config(config, root=root)
        found.update(_references(document, data_root, config))
        for station in _station_rows(document, data_root, config):
            stations[(station.dest, station.id)] = station
    return sorted(found), tuple(stations[key] for key in sorted(stations))


def _references(document: dict, data_root: Path, config: Path) -> set[Path]:
    resolved: set[Path] = set()

    data_section = document.get("data")
    if isinstance(data_section, dict):
        for variable, section in data_section.items():
            if not isinstance(section, dict):
                continue
            for source in section.get("sources", ()):
                resolved.update(_source_files(variable, source, document, data_root, config))

    # A solver section may name a mesh bundle it reads as its cell mesh.
    for solver_options in document.get("solver", {}).values():
        if not (isinstance(solver_options, dict) and solver_options.get("exchange_mesh")):
            continue
        mesh_ref = str(solver_options["exchange_mesh"])
        local = (config.parent / mesh_ref).resolve()
        if local.exists():
            resolved.add(local)
        else:
            resolved.add(_locate_by_name(mesh_ref, data_root, config))

    # Loose paths outside [data]: the mapped networks of a calibration output.
    for path in _loose_paths(document):
        resolved.add(_locate_by_name(path, data_root, config))
    return resolved


_OLD_MAP_KEYS = {"stream_geometry_path", "minimal_stream_geometry_path"}


def _loose_paths(document: dict) -> list[str]:
    names: list[str] = []
    outputs = document.get("calibration", {}).get("outputs", {})
    if isinstance(outputs, dict):
        for output in outputs.values():
            if isinstance(output, dict) and _OLD_MAP_KEYS & output.keys():
                raise ConfigError(
                    f"a network output names its map with {', '.join(sorted(_OLD_MAP_KEYS & output.keys()))}, "
                    "which only a pre-release of 2.0 wrote, so no file would ship. Write it as "
                    "map.complete or map.permanent."
                )
            maps = output.get("map") if isinstance(output, dict) else None
            for role in ("complete", "permanent"):
                named = maps.get(role) if isinstance(maps, dict) else None
                if named and named != "data.hydrography":
                    names.append(str(named))
    return names


def _stations_of(source: dict, document: dict) -> list[str]:
    """Return the stations a folder source reads: its ``station_ids``, else the gauge.

    A station source that names no station reads ``[site] gauge`` at run time
    (``hydromodpy.data.sites.gauge``), so the manifest ships the files of the gauge.
    """
    stations = [str(item) for item in source.get("station_ids", ())]
    if stations:
        return stations
    site = document.get("site")
    gauge = site.get("gauge") if isinstance(site, dict) else None
    return [str(gauge)] if gauge else []


def _source_files(
    variable: str, source: dict, document: dict, data_root: Path, config: Path
) -> list[Path]:
    """Resolve one ``[[data.<variable>.sources]]`` entry to files on disk."""
    if not isinstance(source, dict) or source.get("source") != "file":
        return []
    raw = source.get("path")
    if not raw:
        return []

    # Lexical normalisation: '../../data/x.tif' and the data root name one file
    # once, so the union over the configs does not list it twice.
    local = Path(os.path.normpath(config.parent / str(raw)))
    if local.is_file():
        return [local]
    folder = data_root / variable
    reference = Path(str(raw))
    if reference.suffix:
        candidate = folder / reference.name
        if not candidate.is_file():
            raise ConfigError(f"{config.name} names {raw!r}, which is not at {candidate}.")
        return [candidate]

    # A path without an extension is the variable folder itself: the files are
    # picked by station id, the way a manager picks them at load time.
    stations = _stations_of(source, document)
    if not stations:
        raise ConfigError(
            f"{config.name} points {variable} at the folder {raw!r} with neither "
            f"station_ids nor [site] gauge, so the manifest cannot tell which files the "
            f"example needs."
        )
    return [_station_file(folder, station, config) for station in stations]


def _station_rows(document: dict, data_root: Path, config: Path) -> list[PayloadStation]:
    """Return the registry row of every station a folder source names.

    A station file carries values only: its coordinates, CRS and unit live in
    ``<variable>_custom_LOC.csv``, and a load without that row fails.
    """
    rows: list[PayloadStation] = []
    data_section = document.get("data")
    if not isinstance(data_section, dict):
        return rows
    for variable, section in data_section.items():
        if not isinstance(section, dict):
            continue
        for source in section.get("sources", ()):
            if not isinstance(source, dict) or source.get("source") != "file":
                continue
            if not source.get("path") or Path(str(source["path"])).suffix:
                continue
            registry = data_root / variable / f"{variable}_file_LOC.csv"
            if not registry.is_file():
                registry = data_root / variable / f"{variable}_custom_LOC.csv"
            if not registry.is_file():
                raise ConfigError(
                    f"{config.name} reads {variable} stations, and {registry} does not exist."
                )
            with registry.open(newline="", encoding="utf-8") as handle:
                known = {row["id"]: row for row in csv.DictReader(handle)}
            for station in _stations_of(source, document):
                row = known.get(str(station))
                if row is None:
                    raise ConfigError(
                        f"{config.name} asks for station {station!r}, which has no row in "
                        f"{registry}."
                    )
                rows.append(
                    PayloadStation(
                        dest=f"data/{variable}/{registry.name}",
                        row=tuple((key, value) for key, value in row.items() if key is not None),
                    )
                )
    return rows


def _station_file(folder: Path, station: str, config: Path) -> Path:
    matches = [
        path
        for path in sorted(folder.glob("*"))
        if (match := _STATION_FILE_RE.match(path.name)) and match.group("station") == station
    ]
    if len(matches) != 1:
        raise ConfigError(
            f"{config.name} asks for station {station!r} in {folder}: "
            f"{len(matches)} file(s) match the data naming contract, expected exactly 1."
        )
    return matches[0]


def _locate_by_name(name: str, data_root: Path, config: Path) -> Path:
    target = Path(name).name
    matches = sorted(path for path in data_root.glob(f"*/{target}") if path.is_file())
    if len(matches) != 1:
        raise ConfigError(
            f"{config.name} names {name!r}: {len(matches)} file(s) carry that name under "
            f"{data_root}, expected exactly 1."
        )
    return matches[0]


__all__ = ["AUTHORED_SUFFIXES", "authored_configs", "authored_files", "project_data"]
