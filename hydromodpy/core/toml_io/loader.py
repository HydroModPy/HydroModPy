"""TOML loading with ``base_config`` inheritance, and the base of relative paths.

A file inherits another with ``base_config = "project.toml"``; the chain is
read root first and merged by :mod:`hydromodpy.core.toml_io.merge`.
:func:`read_toml_chain` returns the files of the chain with the keys each one
writes itself, :func:`load_toml_with_base_config` the merged document.
:func:`merge_toml_layers` adds the overlays, ``--set`` and ``HMP_SET_*`` on top.

Each file reads under the key names of today before the merge, so an old name in
one file meets a new name in another as the same key does. The rules are the ones of
``config_migration``, held by the :class:`~hydromodpy.core.config_kit.root.RootConfig`
the caller passes as ``root``. With ``root=None`` the files are read the way they are
written. A warning names the file that holds the old key, and nothing here writes a file.

Every relative path a project file declares is read from one base, the
project root: the folder that holds ``project.toml`` above the file, or,
outside a project, the folder of the root file of the chain.
:func:`config_base_dir` returns it. A file two folders down (``plan/<hash>/
<case>.toml``, ``runs/<case>/config.toml``) therefore names the same
``dem_init_path`` as ``project.toml`` does.
"""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from hydromodpy.core.config_kit.root import RootConfig
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME
from hydromodpy.core.state.result_dirs import is_sealed_run_dir, resolve_project_root
from hydromodpy.core.toml_io.merge import merge_toml_payloads
from hydromodpy.core.toml_io.overrides import ENV_SOURCE, SET_SOURCE
from hydromodpy.core.toml_io.paths import is_declared_absolute_path

if TYPE_CHECKING:
    from pydantic import BaseModel

    M = TypeVar("M", bound=BaseModel)
else:
    M = TypeVar("M")

_BASIC_STRING_ASSIGNMENT_RE = re.compile(
    r'^(?P<prefix>\s*[^#=\n]+?=\s*)"(?P<value>[^"\n]*)"(?P<suffix>\s*(?:#.*)?)$'
)
_LOG = get_logger(__name__)


def read_toml(path: Path) -> dict[str, Any]:
    """Read one TOML file and return its raw mapping."""
    raw_text = path.read_text(encoding="utf-8-sig")
    try:
        return tomllib.loads(raw_text)
    except tomllib.TOMLDecodeError:
        repaired_text = _repair_path_like_basic_strings(raw_text)
        if repaired_text == raw_text:
            raise
        _LOG.warning(
            "Retried TOML parse after escaping path-like backslashes in %s",
            path,
        )
        return tomllib.loads(repaired_text)


def _looks_like_path_key(key: str) -> bool:
    token = str(key).strip().strip("'\"").split(".")[-1].lower()
    if token == "base_config":
        return True
    return any(hint in token for hint in ("path", "root", "dir", "folder", "file", "mask"))


def _repair_path_like_basic_strings(text: str) -> str:
    repaired_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        newline = ""
        if line.endswith("\r\n"):
            line_body = line[:-2]
            newline = "\r\n"
        elif line.endswith("\n"):
            line_body = line[:-1]
            newline = "\n"
        else:
            line_body = line
        match = _BASIC_STRING_ASSIGNMENT_RE.match(line_body)
        if match is None:
            repaired_lines.append(line)
            continue
        prefix = match.group("prefix")
        key = prefix.split("=", 1)[0].strip()
        value = match.group("value")
        if ("\\" not in value) or (not _looks_like_path_key(key)):
            repaired_lines.append(line)
            continue
        repaired_value = value.replace("\\", "\\\\")
        repaired_lines.append(f'{prefix}"{repaired_value}"{match.group("suffix")}{newline}')
    return "".join(repaired_lines)


def _strip_empty_strings(data: dict[str, Any], *, _path: str = "") -> dict[str, Any]:
    """Recursively remove keys whose value is the empty string ``""``.

    Empty strings cannot represent ``None`` in TOML (no native null), so the
    auto-generated templates emit ``key = ""`` as a placeholder for optional
    fields.  Stripping them before Pydantic validation lets the model fall
    back to ``default=None``, which is the intended semantics.

    Caveat
    ------
    A field where ``""`` is a meaningful value (e.g. a string with
    ``min_length=0`` semantics) cannot be expressed in TOML under this
    loader. Use a sentinel like ``"<empty>"`` or omit the key entirely.

    Only plain ``""`` values on leaf keys are affected -- non-empty strings,
    nested dicts, and lists are traversed but never removed. Each strip is
    logged at debug level so unexpected drops can be diagnosed.
    """
    cleaned: dict[str, Any] = {}
    for key, value in data.items():
        sub_path = f"{_path}.{key}" if _path else str(key)
        if isinstance(value, dict):
            cleaned[key] = _strip_empty_strings(value, _path=sub_path)
        elif isinstance(value, list):
            cleaned[key] = [
                _strip_empty_strings(item, _path=f"{sub_path}[{idx}]")
                if isinstance(item, dict)
                else item
                for idx, item in enumerate(value)
            ]
        elif value == "":
            _LOG.debug("Stripped empty-string placeholder at %s", sub_path)
            continue
        else:
            cleaned[key] = value
    return cleaned


BASE_CONFIG_KEY = "base_config"
"""Key of a file that names the file it inherits."""


@dataclass(frozen=True, slots=True)
class ChainFile:
    """One file of a ``base_config`` chain and the keys it writes itself."""

    path: Path
    own: dict[str, Any]
    """The document of the file, ``base_config`` removed, directives kept.

    Under the key names of today, unless the chain was read with ``root=None``.
    """


def _base_config_of(path: Path, raw: Mapping[str, Any]) -> Path | None:
    """Return the file *raw* inherits, resolved from the folder of *path*."""
    name = raw.get(BASE_CONFIG_KEY)
    if name in (None, ""):
        return None
    if not isinstance(name, str):
        raise TypeError("base_config must be a TOML string path when provided")
    base_path = Path(name).expanduser()
    if not is_declared_absolute_path(base_path):
        base_path = (path.parent / base_path).resolve()
    return base_path


def read_toml_chain(toml_path: str | Path, *, root: RootConfig | None) -> tuple[ChainFile, ...]:
    """Return the files of the ``base_config`` chain of *toml_path*, root first.

    The last element is *toml_path* itself. A cycle raises ``ValueError``. Each file
    is migrated on its own and warns under its own name, or is left as it is written
    with ``root=None``.
    """
    files: list[ChainFile] = []
    seen: list[Path] = []
    current: Path | None = Path(toml_path).resolve()
    while current is not None:
        if current in seen:
            cycle = " -> ".join(str(path) for path in (*seen, current))
            raise ValueError(f"Detected circular base_config chain: {cycle}")
        seen.append(current)
        raw = read_toml(current)
        own = dict(raw)
        own.pop(BASE_CONFIG_KEY, None)
        files.append(ChainFile(path=current, own=own))
        current = _base_config_of(current, raw)
    files.reverse()
    if root is not None:
        root.migrate_layers([(item.path, item.own) for item in files])
    return tuple(files)


def _merged_files(files: Sequence[ChainFile]) -> dict[str, Any]:
    """Merge the documents of *files*, root first, and strip the empty placeholders."""
    merged: dict[str, Any] = {}
    for item in files:
        merged = merge_toml_payloads(merged, item.own)
    return _strip_empty_strings(merged)


def merge_toml_chain(
    files: tuple[ChainFile, ...] | list[ChainFile], *, root: RootConfig | None
) -> dict[str, Any]:
    """Merge the files of a chain, root first, and strip the empty placeholders.

    With a *root*, the rules that wait for the whole document run on the result.
    """
    merged = _merged_files(files)
    if root is not None:
        root.migrate_merged(merged, [(item.path, item.own) for item in files])
    return merged


def merge_toml_layers(
    chains: Sequence[Sequence[ChainFile]],
    *,
    root: RootConfig | None,
    cli_overrides: dict[str, Any] | None = None,
    env_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge a file, its overlays, ``--set`` and ``HMP_SET_*``, each migrated on its own.

    *chains* holds the chain of the file then the chain of each overlay, as
    :func:`read_toml_chain` reads them with ``root=None``. The two payloads are
    migrated in place.
    """
    layers: list[tuple[Path | str, dict[str, Any]]] = [
        (item.path, item.own) for chain in chains for item in chain
    ]
    if cli_overrides:
        layers.append((SET_SOURCE, cli_overrides))
    if env_overrides:
        layers.append((ENV_SOURCE, env_overrides))
    # File by file: an overlay merged on nothing first would spend its directives.
    if root is not None:
        root.migrate_layers(layers)
    merged = merge_toml_payloads(
        _merged_files(chains[0]),
        overlays=[_strip_empty_strings(item.own) for chain in chains[1:] for item in chain],
        cli_overrides=cli_overrides,
        env_overrides=env_overrides,
    )
    if root is not None:
        root.migrate_merged(merged, layers)
    return merged


def load_toml_with_base_config(toml_path: str | Path, *, root: RootConfig | None) -> dict[str, Any]:
    """Load one TOML file with recursive ``base_config`` inheritance."""
    return merge_toml_chain(read_toml_chain(toml_path, root=root), root=root)


def config_base_dir(toml_path: str | Path) -> Path:
    """Return the folder relative paths of *toml_path* are read from.

    It is the project root: the folder holding ``project.toml`` at or above
    the file, or the project of the run that froze the file. A sealed file writes
    its paths from the project root, so ``HMP_PROJECT_ROOT`` (``-w``) answers for a
    copy of a run. Outside a project it is the folder of the root file of the
    ``base_config`` chain, so a file that inherits another reads its paths
    where that other file does.
    """
    resolved = Path(toml_path).resolve()
    named = os.environ.get("HMP_PROJECT_ROOT")
    if named and is_sealed_run_dir(resolved.parent):
        return Path(named).expanduser().resolve()
    root = resolve_project_root(resolved.parent)
    if root != resolved.parent or (root / PROJECT_MARKER_FILENAME).is_file():
        return root
    return read_toml_chain(resolved, root=None)[0].path.parent


def validate_toml(
    model_cls: type[M],
    path: Path | str,
    *,
    root: RootConfig | None,
    section: str | None = None,
    context: dict[str, Any] | None = None,
    base_dir_resolver: Callable[[M, Path], M | None] | None = None,
) -> M:
    """Load *path* through ``load_toml_with_base_config`` then validate against *model_cls*.

    Single entry point that replaces ad-hoc ``tomllib.load + model_validate``
    duplications scattered across sub-config modules.

    Parameters
    ----------
    model_cls
        Pydantic ``BaseModel`` subclass to validate the payload through.
    path
        Path to the input TOML file. Expanded and resolved.
    root
        Root configuration the file is migrated with, or ``None`` to read the
        file the way it is written.
    section
        Optional dotted section path (e.g. ``"data.precipitation"``) to
        extract from the raw payload before validation. When the section is
        missing, an empty mapping is used so subclasses can still validate
        with their declared defaults.
    context
        Optional context dict forwarded to :meth:`model_validate`.
    base_dir_resolver
        Optional callback invoked with ``(instance, base_dir)`` after
        validation, *base_dir* being :func:`config_base_dir` of the file: the
        project root. Returning a new instance overrides the default;
        returning ``None`` keeps the original. Used by callers that resolve
        relative paths post-validation.
    """
    resolved = Path(path).expanduser().resolve()
    payload: Any = load_toml_with_base_config(resolved, root=root)
    if section is not None:
        for key in section.split("."):
            if not isinstance(payload, Mapping) or key not in payload:
                payload = {}
                break
            payload = payload[key]
        if not isinstance(payload, Mapping):
            payload = {}
    cfg = model_cls.model_validate(payload, context=context)
    if base_dir_resolver is not None:
        replaced = base_dir_resolver(cfg, config_base_dir(resolved))
        if replaced is not None:
            cfg = replaced
    return cfg
