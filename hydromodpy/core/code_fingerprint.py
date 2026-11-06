"""The fingerprint of the code that computes: one digest per layer of the package.

A run is the same computation as another one when their configurations, their
inputs and this fingerprint agree. A release number says nothing about that: a
patch that only rewrites a figure moves it, and an unreleased edit of a solver
does not. So the identity of a run and the cache of a calibration read the code
itself, through :func:`code_fingerprint`.

Each Python file is normalized with :mod:`tokenize`. Comments, docstrings and the
line layout go, so an edit of a docstring or a reflow of a call moves nothing,
while any change of the code does. An f-string is kept as one token, the form
Python 3.11 gives it, so one tree has one fingerprint from Python 3.11 to 3.13.
A trailing comma stays a token: a reformat that adds one is taken for a change,
which errs on the side of computing.

The scope is :data:`COMPUTE_LAYERS`, the layers of
``tests/unit/architecture/layer_matrix.yaml`` that change a computed number. Every
other layer of the matrix is named in :data:`OUTSIDE_LAYERS`, and a test keeps the
two lists equal to the matrix, so a new layer has to be classified. The package
data that a computation reads enters with its layer (:data:`COMPUTE_DATA_FILES`).

Tokenizing the scope costs about a second on Python 3.13 and more on Python 3.11,
so the digest of a normalized file is kept on disk under the digest of its bytes,
and only a file that changed is tokenized again. The table is cached per process.
This module imports nothing heavy, because it runs before a skipped run returns.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import tokenize
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Final

COMPUTE_LAYERS: Final[tuple[str, ...]] = (
    "core",
    "config",
    "physics",
    "data",
    "spatial",
    "simulation",
    "solver",
    "calibration",
    "results",
    "workflow",
)
"""The layers whose code changes a computed number, ``calibration`` included."""

RUN_LAYERS: Final[tuple[str, ...]] = tuple(
    layer for layer in COMPUTE_LAYERS if layer != "calibration"
)
"""What the identity of a run reads. A run computes the same without its search."""

OUTSIDE_LAYERS: Final[tuple[str, ...]] = (
    "<root>",
    "schema",
    "display",
    "analysis",
    "examples",
    "project",
    "cli",
)
"""The layers of the matrix that change no computed number: they draw, read or route."""

OUTSIDE_SUBTREES: Final[tuple[str, ...]] = (
    "results/catalog",
    "results/export",
    "results/exporters",
    "results/importers",
    "results/session",
)
"""Folders of a compute layer that index, copy or convert what a run already computed."""

COMPUTE_DATA_FILES: Final[tuple[str, ...]] = ("spatial/administrative/departement.gpkg",)
"""Package data a computation reads, by path under the package. A wheel ships each of them."""

OTHER_DATA_SUFFIXES: Final[tuple[str, ...]] = (".md", ".tex", ".sql", ".toml", ".txt", ".pyc")
"""Suffixes of the other package files of a compute layer: documents and labels.

``results/known_issues.toml`` and the CF names label a run and change no number.
A test refuses a data file with another suffix that :data:`COMPUTE_DATA_FILES` does
not list, so a new table has to be classified.
"""

_RECIPE: Final[int] = 1
"""Version of the normalization. It enters every digest and names the disk cache."""

_CACHE_FILENAME: Final[str] = f"code_fingerprint.v{_RECIPE}.json"

_CACHE_MAX_FILES: Final[int] = 10_000
"""Digests the disk cache keeps, the newest. Each edit of a file adds one."""

_PACKAGE_ROOT: Final[Path] = Path(__file__).resolve().parents[1]

_DROPPED: Final[frozenset[int]] = frozenset(
    {tokenize.COMMENT, tokenize.NL, tokenize.ENDMARKER, tokenize.ENCODING}
)
_STRUCTURE: Final[frozenset[int]] = frozenset({tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT})
_FSTRING_START: Final[int | None] = getattr(tokenize, "FSTRING_START", None)
_FSTRING_END: Final[int | None] = getattr(tokenize, "FSTRING_END", None)

_per_process: dict[tuple[Path, str], str] = {}


def code_fingerprint(layers: Iterable[str] = COMPUTE_LAYERS) -> dict[str, str]:
    """Return ``{layer: digest}`` for *layers*, the whole compute scope by default.

    The digest of a layer covers the normalized text of its Python files and the
    bytes of its data files, under their paths in the package. The result is
    cached per process, and it is the one function the identity of a run and the
    calibration cache read.
    """
    return fingerprint_tree(_PACKAGE_ROOT, layers)


def fingerprint_tree(package_root: Path, layers: Iterable[str]) -> dict[str, str]:
    """Return the fingerprint of the package tree at *package_root*."""
    wanted = list(layers)
    unknown = [layer for layer in wanted if layer not in COMPUTE_LAYERS]
    if unknown:
        raise ValueError(f"not a compute layer: {', '.join(unknown)}")
    root = Path(package_root).resolve()
    missing = [layer for layer in wanted if (root, layer) not in _per_process]
    if missing:
        digests = _load_disk_cache()
        before = len(digests)
        for layer in missing:
            _per_process[(root, layer)] = _layer_digest(root, layer, digests)
        if len(digests) != before:
            _save_disk_cache(digests)
    return {layer: _per_process[(root, layer)] for layer in wanted}


def clear_fingerprint_cache() -> None:
    """Forget the table of this process, for a test that edits a tree."""
    _per_process.clear()


def normalised_source(source: str) -> str:
    """Return *source* as its tokens, without comments, docstrings and layout.

    One token per line. A logical newline, an indent and a dedent stay as a bare
    mark, since they carry the structure of the code and not its layout.
    """
    return "\n".join(_kept_tokens(source))


def _kept_tokens(source: str) -> Iterator[str]:
    """Yield what a file says once comments, docstrings and layout are gone."""
    tokens = list(_merged_tokens(source))
    at_statement_start = True
    index = 0
    while index < len(tokens):
        kind, text = tokens[index]
        following = tokens[index + 1][0] if index + 1 < len(tokens) else None
        if at_statement_start and kind == tokenize.STRING and following == tokenize.NEWLINE:
            # A bare string is a statement that computes nothing: a docstring.
            index += 2
            continue
        yield text if kind not in _STRUCTURE else tokenize.tok_name[kind]
        at_statement_start = kind in _STRUCTURE
        index += 1


def _merged_tokens(source: str) -> Iterator[tuple[int, str]]:
    """Yield ``(kind, text)`` of the tokens that count, an f-string as one STRING.

    Python 3.12 splits an f-string into its parts where Python 3.11 gives one
    STRING token. The parts are read back from the source, so both give the text.
    """
    lines = source.splitlines(keepends=True)
    depth = 0
    start = (0, 0)
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if _FSTRING_START is not None and token.type == _FSTRING_START:
            if depth == 0:
                start = token.start
            depth += 1
            continue
        if _FSTRING_END is not None and token.type == _FSTRING_END:
            depth -= 1
            if depth == 0:
                yield tokenize.STRING, _source_between(lines, start, token.end)
            continue
        if depth or token.type in _DROPPED:
            continue
        yield token.type, token.string


def _source_between(lines: list[str], start: tuple[int, int], end: tuple[int, int]) -> str:
    """Return the source from *start* to *end*, rows from 1 and columns from 0."""
    if start[0] == end[0]:
        return lines[start[0] - 1][start[1] : end[1]]
    middle = lines[start[0] : end[0] - 1]
    return "".join([lines[start[0] - 1][start[1] :], *middle, lines[end[0] - 1][: end[1]]])


def _layer_digest(root: Path, layer: str, digests: dict[str, str]) -> str:
    """Return the digest of one layer, filling *digests* with what it had to tokenize."""
    digest = hashlib.sha256(f"recipe {_RECIPE}\n".encode())
    for path in _layer_files(root, layer):
        relative = path.relative_to(root).as_posix()
        digest.update(f"{relative}\n{_file_digest(path, digests)}\n".encode())
    return digest.hexdigest()


def _layer_files(root: Path, layer: str) -> list[Path]:
    """Return the files of one layer that enter its digest, sorted by path.

    A layer with no module or a listed data file that is absent is a broken
    install. Its digest would say nothing of the code, so it is refused.
    """
    outside = tuple(f"{subtree}/" for subtree in OUTSIDE_SUBTREES)
    modules = [
        path
        for path in (root / layer).rglob("*.py")
        if not path.relative_to(root).as_posix().startswith(outside)
    ]
    data = [root / name for name in COMPUTE_DATA_FILES if name.startswith(f"{layer}/")]
    absent = [path.relative_to(root).as_posix() for path in data if not path.is_file()]
    if not modules or absent:
        # Imported here: this module has to run alone, with the standard library.
        from hydromodpy.core.exceptions import HydroModPyError

        what = ", ".join(absent) if absent else f"any Python source in {layer}/"
        raise HydroModPyError(
            f"The installed package at {root} is incomplete: it lacks {what}, so the identity of "
            "a run cannot be read from its code. Install HydroModPy again."
        )
    return sorted([*modules, *data])


def _file_digest(path: Path, digests: dict[str, str]) -> str:
    """Return the digest of one file: normalized text for Python, bytes for data."""
    raw = path.read_bytes()
    if path.suffix != ".py":
        return hashlib.sha256(raw).hexdigest()
    key = hashlib.sha256(raw).hexdigest()
    known = digests.get(key)
    if known is None:
        known = hashlib.sha256(normalised_source(raw.decode("utf-8")).encode()).hexdigest()
        digests[key] = known
    return known


def _disk_cache_path() -> Path:
    # Read here and not at import: this is the one import of a run that costs.
    from hydromodpy.core.state.portable import cache_dir

    return Path(str(cache_dir())) / _CACHE_FILENAME


def _load_disk_cache() -> dict[str, str]:
    """Return the digests kept on disk, or nothing when they cannot be read."""
    try:
        payload = json.loads(_disk_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # The cache only saves time: without it the files are tokenized again.
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_disk_cache(digests: dict[str, str]) -> None:
    """Write the digests kept on disk in one rename, or leave them as they were."""
    target = _disk_cache_path()
    staged = target.with_name(f".{target.name}.{os.getpid()}")
    kept = dict(list(digests.items())[-_CACHE_MAX_FILES:])
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text(json.dumps(kept), encoding="utf-8")
        staged.replace(target)
    except OSError:
        # A read-only home costs the next process a second, nothing else.
        _drop_staged(staged)


def _drop_staged(staged: Path) -> None:
    """Remove a staged file if there is one, whatever the file system answers."""
    with contextlib.suppress(OSError):
        staged.unlink()


__all__ = [
    "COMPUTE_DATA_FILES",
    "COMPUTE_LAYERS",
    "OTHER_DATA_SUFFIXES",
    "OUTSIDE_LAYERS",
    "OUTSIDE_SUBTREES",
    "RUN_LAYERS",
    "clear_fingerprint_cache",
    "code_fingerprint",
    "fingerprint_tree",
    "normalised_source",
]
