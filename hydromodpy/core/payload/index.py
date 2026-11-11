"""``INSTALL.toml``: the install index of a package.

One format for an example, a published run and an exported project. Each
``[[file]]`` names a file by its destination, its size and its sha256, the
keys of ``[[example.file]]`` in the example catalog. A file of a package
also says where it came from: the variable it feeds, the provider that
delivered it, the request it answered, its licence, the digest of its
sidecar and, for a file a provider delivered, the row of the data cache
that serves it. Each ``[[station]]`` is a row a station registry needs, the
keys of ``[[example.station]]``. Each ``[[site]]`` is a row of the site
catalog.

The bytes of a package are stored by content beside the index, under
``inputs/<sha256><suffix>`` (:func:`stored_name`); a sidecar under
``inputs/<sha256>.json``.

A destination is relative to the workspace root (``data/dem/dem.tif``), or to
the project when ``root = "project"`` (``step1.toml``). A reader refuses an
index whose ``schema`` it does not know (:mod:`hydromodpy.core.io.document_version`).
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Final, Literal

import tomlkit

from hydromodpy.core.io.document_version import VersionWindow, check_version
from hydromodpy.core.site.row import SITE_ROW_COLUMNS, SiteRow
from hydromodpy.core.version import __version__ as HYDROMODPY_VERSION

INSTALL_SCHEMA: Final[str] = "hydromodpy.install.v1"
"""Schema id of ``INSTALL.toml``."""

INSTALL_VERSIONS: Final[VersionWindow] = VersionWindow(
    oldest="hydromodpy.install.v1", current=INSTALL_SCHEMA
)
"""Versions of ``INSTALL.toml`` this code reads."""

INSTALL_FILENAME: Final[str] = "INSTALL.toml"
"""Name of the install index at the root of a package."""

SIDECAR_SUFFIX: Final[str] = ".json"
"""Suffix of a sidecar, beside the file it describes (``dem.tif.json``)."""

Root = Literal["workspace", "project"]
"""What a destination is relative to."""

_FILE_KEYS: Final[tuple[str, ...]] = (
    "dest",
    "size",
    "sha256",
    "root",
    "repo_path",
    "variable",
    "provider",
    "product",
    "license",
    "sidecar_sha256",
    "request",
    "cache",
)


@dataclass(frozen=True, slots=True)
class PayloadFile:
    """One file a package installs, addressed by its content."""

    dest: str
    """Destination, relative to the workspace root or, with ``root = "project"``, the project."""
    size: int
    """Size in bytes."""
    sha256: str
    """Digest of the bytes, also the name they are stored under."""
    root: Root = "workspace"
    """What ``dest`` is relative to."""
    repo_path: str | None = None
    """Where an example file lives in the HydroModPy repository."""
    variable: str | None = None
    """Data variable the file feeds, the folder ``data/<variable>/`` it sits in."""
    provider: str | None = None
    """Provider of the bytes: ``custom`` for a user file, else the source slug."""
    product: str | None = None
    """Product of the provider."""
    license: str | None = None
    """SPDX licence of the bytes."""
    sidecar_sha256: str | None = None
    """Digest of the sidecar ``<dest>.json``, stored beside the bytes."""
    request: Mapping[str, Any] | None = field(default=None, compare=False)
    """What the run asked of the file: station, period, box."""
    cache: Mapping[str, Any] | None = field(default=None, compare=False)
    """Row of the data cache, the sidecar of the file, for a file a provider delivered."""

    def to_table(self) -> dict[str, Any]:
        """Return the ``[[file]]`` table, keys without a value left out."""
        values = {key: getattr(self, key) for key in _FILE_KEYS}
        if values["root"] == "workspace":
            values.pop("root")
        return {key: _plain(value) for key, value in values.items() if value is not None}

    @classmethod
    def from_table(cls, table: Mapping[str, Any]) -> PayloadFile:
        """Build a file from its ``[[file]]`` table; a key a later version added is ignored.

        A ``root`` this code does not know is refused: it could not say where the file goes.
        """
        root = str(table.get("root", "workspace"))
        if root not in ("workspace", "project"):
            raise ValueError(f"[[file]] {table.get('dest')!r}: root is {root!r}")
        return cls(
            dest=str(table["dest"]),
            size=int(table["size"]),
            sha256=str(table["sha256"]),
            root=root,  # type: ignore[arg-type]
            repo_path=_text(table.get("repo_path")),
            variable=_text(table.get("variable")),
            provider=_text(table.get("provider")),
            product=_text(table.get("product")),
            license=_text(table.get("license")),
            sidecar_sha256=_text(table.get("sidecar_sha256")),
            request=table.get("request"),
            cache=table.get("cache"),
        )


@dataclass(frozen=True, slots=True)
class PayloadStation:
    """One row a package adds to a station registry, ``<prefix>_<provider>_LOC.csv``.

    The registry is shared by every project of the workspace, so the row is
    merged into it instead of shipping a file that would replace it.
    ``row`` keeps the registry's column order, values as the CSV writes them.
    """

    dest: str
    row: tuple[tuple[str, str], ...]

    @property
    def id(self) -> str:
        """The station id, the key a registry row is matched on."""
        return dict(self.row)["id"]

    def to_table(self) -> dict[str, Any]:
        """Return the ``[[station]]`` table."""
        return {"dest": self.dest, "row": dict(self.row)}

    @classmethod
    def from_table(cls, table: Mapping[str, Any]) -> PayloadStation:
        """Build a row from its ``[[station]]`` table."""
        return cls(
            dest=str(table["dest"]),
            row=tuple((str(key), str(value)) for key, value in table["row"].items()),
        )


@dataclass(frozen=True, slots=True)
class InstallIndex:
    """Everything a package installs: files, station rows, sites."""

    files: tuple[PayloadFile, ...] = ()
    stations: tuple[PayloadStation, ...] = ()
    sites: tuple[SiteRow, ...] = ()
    hydromodpy_version: str = HYDROMODPY_VERSION

    def file_at(self, dest: str, root: Root = "workspace") -> PayloadFile | None:
        """Return the file of one destination, or None."""
        return next((item for item in self.files if (item.root, item.dest) == (root, dest)), None)


def payload_file_of(
    path: Path,
    *,
    workspace: Path,
    project: Path,
    sha256: str,
    provider: str | None,
    license: str | None,
    product: str | None = None,
    request: Mapping[str, Any] | None = None,
    cache: Mapping[str, Any] | None = None,
) -> PayloadFile:
    """Return the index entry of one file of a workspace: its destination, variable and sidecar.

    A file under *project* lands relative to the project (``root =
    "project"``), any other file of *workspace* relative to the workspace; a
    file of ``data/<variable>/`` feeds ``<variable>``.

    Raises
    ------
    ValueError
        A file outside the workspace, which a package cannot install elsewhere.
    """
    from hydromodpy.core.payload.install import sha256_of

    resolved = Path(path).resolve()
    root: Root
    if resolved.is_relative_to(Path(project).resolve()):
        root, dest = "project", resolved.relative_to(Path(project).resolve()).as_posix()
    elif resolved.is_relative_to(Path(workspace).resolve()):
        root, dest = "workspace", resolved.relative_to(Path(workspace).resolve()).as_posix()
    else:
        raise ValueError(
            f"{resolved.name} lies outside the workspace, which a package cannot install "
            "elsewhere. Move it under data/<variable>/ and run the configuration again."
        )
    parts = dest.split("/")
    variable = parts[1] if root == "workspace" and len(parts) == 3 and parts[0] == "data" else None
    sidecar = resolved.with_name(resolved.name + SIDECAR_SUFFIX)
    return PayloadFile(
        dest=dest,
        size=resolved.stat().st_size,
        sha256=sha256,
        root=root,
        variable=variable,
        provider=provider,
        product=product,
        license=license,
        sidecar_sha256=sha256_of(sidecar) if sidecar.is_file() else None,
        request=request,
        cache=cache,
    )


@dataclass(frozen=True, slots=True)
class PayloadBundle:
    """An install index and the local files that hold its bytes, by stored name."""

    index: InstallIndex
    blobs: Mapping[str, Path] = field(default_factory=dict)
    """``<sha256><suffix>`` or ``<sha256>.json`` mapped to the file that holds those bytes."""


def stored_name(sha256: str, dest: str) -> str:
    """Return the name the bytes of *dest* are stored under: ``<sha256><suffix>``."""
    return f"{sha256}{PurePosixPath(dest).suffix}"


def sidecar_name(sha256: str) -> str:
    """Return the name a sidecar is stored under: ``<sha256>.json``."""
    return f"{sha256}{SIDECAR_SUFFIX}"


def render_index(index: InstallIndex) -> str:
    """Return ``INSTALL.toml`` as text: one ``[[file]]``, ``[[station]]`` or ``[[site]]`` each."""
    document = tomlkit.document()
    document["schema"] = INSTALL_SCHEMA
    document["hydromodpy_version"] = index.hydromodpy_version
    for key, tables in (
        ("file", [item.to_table() for item in index.files]),
        ("station", [station.to_table() for station in index.stations]),
        ("site", [_site_table(row) for row in index.sites]),
    ):
        if tables:
            document[key] = _array_of_tables(tables)
    return tomlkit.dumps(document)


def _array_of_tables(tables: list[dict[str, Any]]) -> Any:
    """Return *tables* as an array of tables, nested mappings written inline."""
    array = tomlkit.aot()
    for values in tables:
        table = tomlkit.table()
        for key, value in values.items():
            table[key] = _inline(value) if isinstance(value, Mapping) else value
        array.append(table)
    return array


def _inline(values: Mapping[str, Any]) -> Any:
    table = tomlkit.inline_table()
    for key, value in values.items():
        table[key] = _inline(value) if isinstance(value, Mapping) else value
    return table


def write_index(directory: str | Path, index: InstallIndex) -> Path:
    """Write ``INSTALL.toml`` in *directory* and return its path."""
    path = Path(directory) / INSTALL_FILENAME
    path.write_text(render_index(index), encoding="utf-8")
    return path


def read_index(directory: str | Path) -> InstallIndex:
    """Read ``INSTALL.toml`` of a package; refuse a schema this code does not read."""
    path = Path(directory) / INSTALL_FILENAME
    with path.open("rb") as handle:
        document = tomllib.load(handle)
    check_version(
        document.get("schema"),
        INSTALL_VERSIONS,
        document=path,
        key="schema",
        writer=document.get("hydromodpy_version"),
    )
    return InstallIndex(
        files=tuple(PayloadFile.from_table(table) for table in document.get("file", ())),
        stations=tuple(PayloadStation.from_table(table) for table in document.get("station", ())),
        sites=tuple(
            SiteRow.from_mapping({key: table[key] for key in SITE_ROW_COLUMNS if key in table})
            for table in document.get("site", ())
        ),
        hydromodpy_version=str(document.get("hydromodpy_version") or ""),
    )


def _site_table(row: SiteRow) -> dict[str, Any]:
    mapping = row.to_mapping()
    return {key: mapping[key] for key in SITE_ROW_COLUMNS if mapping[key] not in (None, "")}


def _text(value: Any) -> str | None:
    return None if value in (None, "") else str(value)


def _plain(value: Any) -> Any:
    """Return *value* as TOML writes it: a None key dropped, a None item of a list empty."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items() if item is not None}
    if isinstance(value, (list, tuple)):
        return ["" if item is None else _plain(item) for item in value]
    return value


__all__ = [
    "INSTALL_FILENAME",
    "INSTALL_SCHEMA",
    "SIDECAR_SUFFIX",
    "InstallIndex",
    "PayloadBundle",
    "PayloadFile",
    "PayloadStation",
    "Root",
    "payload_file_of",
    "read_index",
    "render_index",
    "sidecar_name",
    "stored_name",
    "write_index",
]
