"""The user files the configurations of a project declare, listed and hashed.

``hmp data lock`` pins them in ``hydromodpy.lock`` beside the rows of the data
cache, so that ``--frozen`` refuses a user file that changed. The files are read
from ``project.toml``, from each ``configs/*.toml`` and from each case of the
current plan of a ``[sites]`` project, through :class:`FileSource`, which reads
in place and writes nothing. This module reads ``data`` and ``results`` and
lives here so that both ``project`` and its launcher can call it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.core.state.layout import CONFIGS_DIRNAME, PROJECT_MARKER_FILENAME, plan_dir_for
from hydromodpy.data.provenance.lockfile import USER_FILE_SOURCE, LockedInput, user_file_input


def _config_files(project_root: Path) -> list[Path]:
    files = [project_root / PROJECT_MARKER_FILENAME]
    files.extend(sorted((project_root / CONFIGS_DIRNAME).glob("*.toml")))
    return [path for path in files if path.is_file()]


def _declared_user_files(config: Any) -> list[tuple[str, Path, str | None]]:
    """Return ``(variable, path, licence)`` for each ``source = "file"`` the config reads."""
    data = getattr(config, "data", None)
    if data is None:
        return []
    names = list(getattr(data, "types", None) or type(data).model_fields)
    found: list[tuple[str, Path, str | None]] = []
    for name in names:
        section = getattr(data, name, None)
        for source in getattr(section, "sources", None) or ():
            path = getattr(source, "path", None)
            if getattr(source, "source", None) == USER_FILE_SOURCE and path:
                found.append((name, Path(path), getattr(source, "license", None)))
    return found


def _declares_sites(config_path: Path) -> bool:
    """Whether a ``project.toml`` declares ``[sites]``, read on the raw TOML."""
    import tomllib

    from hydromodpy.config.sites import is_sites_project

    if config_path.name != PROJECT_MARKER_FILENAME:
        return False
    try:
        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    return is_sites_project(raw)


def _plan_cases(project_root: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Return the file and the document of each case of the current plan, if any.

    Only the current plan counts: every prepare phase writes the plan again and
    writes the lockfile again.
    """
    import tomllib

    from hydromodpy.results.plan_store import current_plan_hash, read_plan

    if current_plan_hash(project_root) is None:
        return []
    stored = read_plan(project_root)
    return [
        (stored.directory / case.config_path, tomllib.loads(stored.case_toml(case.case_id)))
        for case in stored.cases
    ]


def user_file_inputs(project_root: Path) -> tuple[list[LockedInput], list[tuple[Path, str]]]:
    """Return the records of every user file the configurations of a project declare.

    Each ``source = "file"`` of ``project.toml``, of ``configs/*.toml`` and of
    each case of the current plan is listed and hashed by
    :class:`~hydromodpy.data.source.file.FileSource`, which writes nothing. A
    ``project.toml`` that declares ``[sites]`` is not loaded alone: the cases
    of its plan stand for it. A configuration that does not load is returned
    with its reason and its files are left out, so a frozen run of it is
    refused while the other configurations are locked.
    """
    from hydromodpy.config.loading import load
    from hydromodpy.data.source.file import FileSource
    from hydromodpy.data.source.port import FetchRequest

    root = Path(project_root).resolve()
    records: dict[tuple[str, str], LockedInput] = {}
    refused: list[tuple[Path, str]] = []

    def add(config: Any) -> None:
        for variable, path, licence in _declared_user_files(config):
            source = FileSource(path=path)
            source.section = variable
            source.variables = (variable,)
            result = source.fetch(FetchRequest(out_dir=root, bounds=Bounds()))
            for record in result.files:
                item = user_file_input(
                    record.path,
                    variable=variable,
                    project_root=root,
                    sha256=record.sha256,
                    license=licence,
                )
                records[(item.variable, item.path)] = item

    def reason(exc: Exception) -> str:
        return str(exc).splitlines()[0] if str(exc) else repr(exc)

    for config_path in _config_files(root):
        if _declares_sites(config_path):
            continue
        try:
            add(load(config_path))
        except Exception as exc:  # noqa: BLE001 - one bad configuration never blocks the others
            refused.append((config_path, reason(exc)))
    try:
        cases = _plan_cases(root)
    except Exception as exc:  # noqa: BLE001 - an unreadable plan is named, never guessed
        refused.append((plan_dir_for(root), reason(exc)))
        cases = []
    for case_path, document in cases:
        try:
            add(load(document, base=root, source_path=case_path))
        except Exception as exc:  # noqa: BLE001 - one bad case never blocks the others
            refused.append((case_path, reason(exc)))
    return list(records.values()), refused


__all__ = ["user_file_inputs"]
