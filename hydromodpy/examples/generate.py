"""Generate ``catalog.toml`` from the repository, behind ``hmp dev examples manifest``.

The generator walks an explicit whitelist, resolves each project's data
references the way a run resolves them, hashes every file and writes the
manifest. It only runs from a source checkout: a wheel does not carry
``examples/``.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.toml_io.loader import load_toml_with_base_config
from hydromodpy.examples.manifest import (
    ExampleEntry,
    ExampleFile,
    catalog_path,
    render_catalog,
)

AUTHORED_SUFFIXES: tuple[str, ...] = (".toml", ".md", ".py")
"""What counts as a file the example's author wrote, at the project root."""

_STATION_FILE_RE = re.compile(
    r"^(?P<prefix>.+)_custom_(?P<station>.+)_(?P<start>\d{8})_(?P<end>\d{8})_(?P<freq>[A-Za-z]+)"
    r"\.(?P<suffix>csv|parquet)$"
)
"""The ``data/<variable>/`` naming contract, which is how a station id resolves."""


@dataclass(frozen=True, slots=True)
class ExampleSpec:
    """One whitelisted example and the prose the catalog carries for it."""

    id: str
    directory: str
    title: str
    summary: str
    runtime: str
    entry_config: str
    """The config a first run should start from, a file name of the project."""


# The whitelist is explicit, and it has ONE entry on purpose.
#
# examples/projects/ holds 35 directories. Among them: new_to_sort, three
# competing Nancon variants, and two authored TOMLs carrying absolute Windows
# paths. Only 04_streamflow_intermittence_in_transient is maintained and
# verified end to end. Announcing a catalogue of 35 of which one works is worse
# than announcing one, so `hmp example list` announces one. A project earns a
# line here once it runs from a freshly scaffolded workspace, not before.
WHITELIST: tuple[ExampleSpec, ...] = (
    ExampleSpec(
        id="04",
        directory="04_streamflow_intermittence_in_transient",
        title="Streamflow intermittence in transient",
        summary=(
            "Nancon catchment, monthly transient 2000-2002, MODFLOW 6. Five layered "
            "step files, from the shortest config that solves to a run that exports "
            "its seepage fields."
        ),
        runtime="6 s for step 1, about 50 s for the full transient step 5",
        entry_config="step1_minimal.toml",
    ),
)


def repo_root() -> Path:
    """Return the checkout root, found by walking up to ``examples/projects/``."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "examples" / "projects").is_dir():
            return parent
    raise ConfigError(
        "No examples/projects/ above this module. The manifest generator runs "
        "from a source checkout, not from an installed wheel."
    )


def build_catalog(root: Path | None = None) -> tuple[ExampleEntry, ...]:
    """Build every whitelisted entry, hashing each file it names."""
    base = root if root is not None else repo_root()
    return tuple(_build_entry(spec, base) for spec in WHITELIST)


def write_catalog(
    root: Path | None = None,
    destination: Path | None = None,
) -> tuple[Path, tuple[ExampleEntry, ...]]:
    """Render the catalog and write it, returning the path and the entries.

    The entries come back with it so a caller that wants to report what was
    written does not hash a 90 MiB DEM a second time to find out.
    """
    entries = build_catalog(root)
    target = destination if destination is not None else catalog_path()
    target.write_text(render_catalog(entries), encoding="utf-8")
    return target, entries


def _build_entry(spec: ExampleSpec, root: Path) -> ExampleEntry:
    project_dir = root / "examples" / "projects" / spec.directory
    if not project_dir.is_dir():
        raise ConfigError(f"Whitelisted example {spec.id} has no directory at {project_dir}.")

    authored = [
        _describe(root, path, f"projects/{spec.directory}/{path.name}")
        for path in _authored_files(project_dir)
    ]
    data = [
        _describe(root, path, f"data/{path.parent.name}/{path.name}")
        for path in _data_files(project_dir, root / "examples" / "data")
    ]
    if not any(item.dest.endswith(f"/{spec.entry_config}") for item in authored):
        raise ConfigError(
            f"Whitelisted example {spec.id} names entry_config={spec.entry_config!r}, "
            f"which is not among the files shipped from {project_dir}."
        )
    return ExampleEntry(
        id=spec.id,
        directory=spec.directory,
        title=spec.title,
        summary=spec.summary,
        runtime=spec.runtime,
        entry_config=spec.entry_config,
        files=tuple(sorted(authored, key=lambda item: item.dest)),
        data=tuple(sorted(data, key=lambda item: item.dest)),
    )


def _authored_files(project_dir: Path) -> list[Path]:
    """Return the files at the project root that the example's author wrote.

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


def _authored_configs(project_dir: Path) -> list[Path]:
    return [path for path in _authored_files(project_dir) if path.suffix == ".toml"]


def _data_files(project_dir: Path, data_root: Path) -> list[Path]:
    """Resolve every data file the project's authored TOMLs reference.

    Each config is read through the run pipeline's own loader, so a variant
    that only overrides ``station_ids`` inherits the ``source`` and ``path``
    its parent declared, exactly as it does at run time. The union over all of
    them and not just over one entry point: the step files and the run
    variants are all shipped, so each one has to find its inputs.
    """
    found: set[Path] = set()
    for config in _authored_configs(project_dir):
        document = load_toml_with_base_config(config)
        found.update(_references(document, data_root, config))
    return sorted(found)


def _references(document: dict, data_root: Path, config: Path) -> set[Path]:
    resolved: set[Path] = set()

    data_section = document.get("data")
    if isinstance(data_section, dict):
        for variable, section in data_section.items():
            if not isinstance(section, dict):
                continue
            for source in section.get("sources", ()):
                resolved.update(_source_files(variable, source, data_root, config))

    # Two keys name a file outside [data]: the regional DEM the catchment is cut
    # out of, and the mapped network the network criterion is scored against.
    # Neither says which variable folder it lives in, so they are located by
    # name, and an ambiguous name is an error rather than a pick.
    for path in _loose_paths(document):
        resolved.add(_locate_by_name(path, data_root, config))
    return resolved


def _loose_paths(document: dict) -> list[str]:
    names: list[str] = []
    catchment = document.get("geographic", {}).get("catchment", {})
    if isinstance(catchment, dict) and catchment.get("dem_init_path"):
        names.append(str(catchment["dem_init_path"]))
    outputs = document.get("calibration", {}).get("outputs", {})
    if isinstance(outputs, dict):
        for output in outputs.values():
            if isinstance(output, dict) and output.get("stream_geometry_path"):
                names.append(str(output["stream_geometry_path"]))
    return names


def _source_files(variable: str, source: dict, data_root: Path, config: Path) -> list[Path]:
    """Resolve one ``[[data.<variable>.sources]]`` entry to files on disk."""
    if not isinstance(source, dict) or source.get("source") != "custom":
        return []
    raw = source.get("path")
    if not raw:
        return []

    folder = data_root / variable
    reference = Path(str(raw))
    if reference.suffix:
        candidate = folder / reference.name
        if not candidate.is_file():
            raise ConfigError(f"{config.name} names {raw!r}, which is not at {candidate}.")
        return [candidate]

    # A path without an extension is the variable folder itself: the files are
    # picked by station id, the way a manager picks them at load time.
    stations = [str(item) for item in source.get("station_ids", ())]
    if not stations:
        raise ConfigError(
            f"{config.name} points {variable} at the folder {raw!r} without station_ids, "
            f"so the manifest cannot tell which files the example needs."
        )
    return [_station_file(folder, station, config) for station in stations]


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


def _describe(root: Path, path: Path, dest: str) -> ExampleFile:
    payload = path.read_bytes()
    return ExampleFile(
        repo_path=path.relative_to(root).as_posix(),
        dest=dest,
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )
