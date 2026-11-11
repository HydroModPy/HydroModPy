"""A result directory relative to its project, and the project that holds it.

The two relative forms of a result directory, ``runs/<name>`` and
``sessions/<name>/trials/<nnnn>``, are spelled by :func:`run_dir_rel`,
:func:`session_dir_rel` and :func:`trial_dir_rel`, and read back by
:func:`parse_rel_dir`. They are the only declared holders of the two forms.

``resolve_project_root`` anchors a project from a run, a session or a trial folder.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.state.layout import (
    CONFIGS_DIRNAME,
    PROJECT_MARKER_FILENAME,
    RUNS_DIRNAME,
    SESSIONS_DIRNAME,
    TRIAL_DIRNAME_WIDTH,
    TRIALS_DIRNAME,
)

# Relative result directories ------------------------------------------------
#
# A result directory is addressed by its path relative to the project root.
# There are two forms, a run or a session at the top of its directory and a
# kept trial inside its session. Index rows, manifests, ledgers and the CLI all
# carry these strings; the five functions below are their only declared
# holders.

RelDirKind = Literal["run", "session", "trial"]


def _check_dir_name(name: str) -> str:
    """Return *name* when it can be one path segment; refuse it otherwise."""
    text = str(name)
    if not text or text in {".", ".."} or "/" in text or "\\" in text:
        raise ValueError(f"{text!r} is not a result directory name")
    return text


def _trial_dirname(trial: int) -> str:
    """Return the zero-padded directory name of a trial number."""
    if isinstance(trial, bool) or not isinstance(trial, int) or trial < 0:
        raise ValueError(f"trial must be a non-negative integer, got {trial!r}")
    return f"{trial:0{TRIAL_DIRNAME_WIDTH}d}"


@dataclass(frozen=True, slots=True)
class RelDir:
    """A result directory relative to the project root, parsed into its parts.

    ``name`` is the run or session directory name with its ``.vN`` suffix;
    this module does not read the version grammar. ``trial`` is set only for
    a kept trial, and ``case`` only for a kept trial of a session of several
    cases, which keeps one directory per case.
    """

    kind: RelDirKind
    name: str
    trial: int | None = None
    case: str | None = None

    def as_posix(self) -> str:
        """Return the relative path in POSIX spelling."""
        if self.kind == "run":
            return run_dir_rel(self.name)
        if self.kind == "session":
            return session_dir_rel(self.name)
        if self.trial is None:
            raise ValueError("a trial directory needs a trial number")
        kept = trial_dir_rel(self.name, self.trial)
        return kept if self.case is None else f"{kept}/{self.case}"


def run_dir_rel(name: str) -> str:
    """Return ``runs/<name>``, the relative path of a run directory."""
    return f"{RUNS_DIRNAME}/{_check_dir_name(name)}"


def session_dir_rel(name: str) -> str:
    """Return ``sessions/<name>``, the relative path of a session directory."""
    return f"{SESSIONS_DIRNAME}/{_check_dir_name(name)}"


def trial_dir_rel(name: str, trial: int) -> str:
    """Return ``sessions/<name>/trials/<nnnn>``, the relative path of a kept trial."""
    return f"{session_dir_rel(name)}/{TRIALS_DIRNAME}/{_trial_dirname(trial)}"


def parse_rel_dir(rel_dir: str) -> RelDir:
    """Read a relative result directory back into its parts.

    Accepts exactly ``runs/<name>``, ``sessions/<name>``,
    ``sessions/<name>/trials/<nnnn>`` and ``sessions/<name>/trials/<nnnn>/<case_id>``,
    with the trial zero-padded to :data:`TRIAL_DIRNAME_WIDTH` digits. Any other
    form raises ``ValueError``.
    """
    text = str(rel_dir)
    parts = text.split("/")
    try:
        if len(parts) == 2 and parts[0] == RUNS_DIRNAME:
            return RelDir("run", _check_dir_name(parts[1]))
        if len(parts) == 2 and parts[0] == SESSIONS_DIRNAME:
            return RelDir("session", _check_dir_name(parts[1]))
        if len(parts) in (4, 5) and parts[0] == SESSIONS_DIRNAME and parts[2] == TRIALS_DIRNAME:
            digits = parts[3]
            if digits.isdigit() and digits.isascii():
                trial = int(digits)
                if _trial_dirname(trial) == digits:
                    case = _check_dir_name(parts[4]) if len(parts) == 5 else None
                    return RelDir("trial", _check_dir_name(parts[1]), trial, case)
    except ValueError:
        pass
    raise ValueError(
        f"{text!r} is not a result directory: write runs/<name>, sessions/<name> or "
        f"sessions/<name>/{TRIALS_DIRNAME}/<{'n' * TRIAL_DIRNAME_WIDTH}>[/<case_id>]"
    )


def is_sealed_run_config(path: str | Path) -> bool:
    """Return whether *path* is a configuration a run froze in its run directory.

    A run directory is ``runs/<name>`` or a kept trial
    ``sessions/<name>/trials/<nnnn>[/<case_id>]`` (:func:`parse_rel_dir`). The frozen file
    is its ``config.toml``.
    """
    parts = Path(path).expanduser().resolve().parent.parts
    for depth in (2, 4, 5):
        if len(parts) < depth:
            continue
        try:
            kind = parse_rel_dir("/".join(parts[-depth:])).kind
        except ValueError:
            continue
        if kind in {"run", "trial"}:
            return True
    return False


def project_of_result_dir(folder: str | Path) -> Path | None:
    """Return the project that holds the run, trial or session directory *folder*, or None.

    A project needs no ``project.toml``, so the path alone does not say it: a folder
    of the user can be called ``runs/first``. The directory has to read as a result
    directory and hold what one holds from its first write on, or from its seal.
    """
    resolved = Path(folder).expanduser().resolve()
    if not any((resolved / name).is_file() for name in ("outcome.json", "manifest.json")):
        return None
    for depth in (2, 4, 5):
        try:
            parse_rel_dir("/".join(resolved.parts[-depth:]))
        except ValueError:
            continue
        return resolved.parents[depth - 1]
    return None


def is_sealed_run_dir(folder: str | Path) -> bool:
    """Return whether *folder* holds a sealed run: its configuration and its manifest."""
    resolved = Path(folder)
    return (resolved / "manifest.json").is_file() and (resolved / "config.toml").is_file()


def refuse_a_sealed_run_as_project(project_root: str | Path) -> None:
    """Refuse to work in *project_root* when it is a sealed run, which nothing writes into.

    A run copied out of its project has no project above it, so the folder of its
    ``config.toml`` would take the role of the project.
    """
    root = Path(project_root)
    if is_sealed_run_dir(root):
        raise ConfigError(
            f"{root} is a sealed run outside any project, and nothing writes into a sealed "
            f"run. Name the project it replays into: hmp replay {root} -w <project>, "
            "which reads its inputs from that project."
        )


def resolve_project_root(start: Path) -> Path:
    """Walk up from ``start`` to the directory holding ``project.toml``.

    The anchor is the project config file, never a database file: the catalog
    is a rebuildable index and may be absent. Without a marker the starting
    directory is the root, so a flat project directory still resolves, and a
    result directory of a flat project answers for that project
    (:func:`project_of_result_dir`). A ``configs/`` directory is the exception:
    anchoring there would scatter the project outputs under the sub-directory, so
    it raises instead.
    """
    base = Path(start)
    for parent in [base, *base.parents]:
        if (parent / PROJECT_MARKER_FILENAME).is_file():
            return parent
    holder = project_of_result_dir(base)
    if holder is not None:
        return holder
    if base.name == CONFIGS_DIRNAME:
        raise ConfigError(
            f"No {PROJECT_MARKER_FILENAME} found above {base}. A config stored in "
            f"{CONFIGS_DIRNAME}/ cannot anchor a project root: add "
            f"{PROJECT_MARKER_FILENAME} to {base.parent}."
        )
    return base


def project_root_at(workspace: str | Path | None) -> Path:
    """Return the project root at or above *workspace*, or above the current directory."""
    return resolve_project_root(Path(workspace or Path.cwd()).expanduser().resolve())


def sites_project_root(target: str | Path) -> Path:
    """Return the root of the ``[sites]`` project *target* names.

    *target* is the project folder, its ``project.toml`` or a folder inside
    it. Raises :class:`FileNotFoundError` when no ``project.toml`` sits at or
    above it.
    """
    path = Path(target).expanduser().resolve()
    start = path.parent if path.is_file() else path
    root = resolve_project_root(start)
    if not (root / PROJECT_MARKER_FILENAME).is_file():
        raise FileNotFoundError(f"no {PROJECT_MARKER_FILENAME} at or above {path}")
    return root


__all__ = (
    "RelDir",
    "RelDirKind",
    "is_sealed_run_config",
    "is_sealed_run_dir",
    "parse_rel_dir",
    "project_of_result_dir",
    "project_root_at",
    "refuse_a_sealed_run_as_project",
    "resolve_project_root",
    "run_dir_rel",
    "session_dir_rel",
    "sites_project_root",
    "trial_dir_rel",
)
