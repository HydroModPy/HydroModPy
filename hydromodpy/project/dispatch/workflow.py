"""Workflow dispatch adapters that bind launchers to ``Project``.

Wires the user-facing entry points (``run_simulation``, ``run_overview``,
``run_calibration``) to the matching workflow launchers. Lives under :mod:`hydromodpy.project.dispatch` because
it depends on :class:`hydromodpy.project.Project`; the lower
``hydromodpy.workflow`` package stays independent from that facade.

It also owns the staged-calibration routing question
(:func:`declared_calibration_phases`, :func:`calibration_phases_or_raise`),
which every calibration entry point asks before choosing a runner.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast


def run_overview(config_path: str | Path) -> dict[str, Any]:
    """Generate a watershed identity card from a TOML file."""
    from hydromodpy.workflow.pipelines.overview import DataOverviewLauncher

    return DataOverviewLauncher(config_path).run()


def declared_calibration_phases(config_path: str | Path) -> list[str]:
    """Names of the ``[[calibration.phases]]`` a calibration TOML declares.

    Non-fatal on purpose: this answers the routing question and nothing else. A
    file that cannot be read declares no phase here, and its real error is
    raised by the runner that reads it next, with its context. Callers whose
    answer depends on reading the file use :func:`calibration_phases_or_raise`
    instead.
    """
    from hydromodpy.calibration.runners.cli_runner import load_toml_calibration

    try:
        cfg, _raw = load_toml_calibration(Path(config_path).expanduser().resolve())
    except Exception:
        return []
    return [decl.name for decl in (cfg.phases or [])]


def calibration_phases_or_raise(config_path: str | Path) -> list[str]:
    """Names of the declared phases, reporting a file that cannot be read.

    The raising sibling of :func:`declared_calibration_phases`, for the caller
    that reaches no runner afterwards: selecting a phase by name answers from
    the file itself, so a file that fails to validate must be reported as such
    and not as a file declaring no phase.
    """
    from hydromodpy.calibration.runners.cli_runner import load_toml_calibration
    from hydromodpy.core.exceptions import ConfigError

    target = Path(config_path).expanduser().resolve()
    try:
        cfg, _raw = load_toml_calibration(target)
    except Exception as exc:
        raise ConfigError(f"{target} cannot be read: {exc}") from exc
    return [decl.name for decl in (cfg.phases or [])]


def no_such_phase(source: str, phase: str) -> str:
    """Message refusing a phase that ``source`` does not declare."""
    return f"{source} declares no [[calibration.phases]], so there is no phase {phase!r} to run."


def run_calibration(config_path: str | Path, *, phase: str | None = None) -> dict[str, Any]:
    """Run a parameter calibration campaign from a TOML file.

    Routes to the staged runner when the file declares
    ``[[calibration.phases]]``, so a phased configuration is never flattened
    into a single calibration over the union of its parameters. The staged
    report is summarized as a mapping, because every caller of this dispatcher
    expects one.
    """
    from hydromodpy.core.exceptions import CalibrationError

    target = Path(config_path).expanduser().resolve()
    # A caller naming a phase gets the reading that raises: answering "declares
    # no phases" for a file that declares them but fails to validate sends the
    # user to a block that is present and correct while the real error is lost.
    declared = (
        calibration_phases_or_raise(target)
        if phase is not None
        else declared_calibration_phases(target)
    )
    if declared:
        from hydromodpy.calibration.runners.staged_runner import (
            StagedCalibrationReport,
            run_staged_calibration,
        )

        staged = run_staged_calibration(target, phase=phase)
        return cast(StagedCalibrationReport, staged).to_dict()
    if phase is not None:
        raise CalibrationError(no_such_phase(target.name, phase))
    from hydromodpy.calibration.runners.cli_runner import run_calibration_cli

    return cast(dict[str, Any], run_calibration_cli(target))


def completed_identical_run(config: Any, *, name: str) -> tuple[str | None, str] | None:
    """Return ``(name, sim_id)`` of a completed run identical to this one, or None.

    Identical means the same run identity hash
    (:func:`~hydromodpy.results.catalog.registration.run_identity_hash`): the
    resolved configuration, without the per-run members, the contents of the
    input files it names and the HydroModPy version. It is the
    ``identity.config_hash`` a run seals, so two runs of an unchanged file on
    unchanged data match. The run must carry the name ``name`` or be a
    version of it (``name.v2``): every version is looked at, newest first,
    because the user asks for this configuration and any sealed run of it
    answers, whichever version last ran it. Read from the manifests under
    ``runs/``, never from the index; a directory without a seal, or whose
    seal cannot be read, never matches.
    """
    from hydromodpy.core.state.paths import runs_dir_for
    from hydromodpy.results.catalog.registration import (
        input_file_digests,
        run_identity_hash,
        split_stem_version,
    )
    from hydromodpy.results.manifest import read_manifest
    from hydromodpy.results.storage.sealing import sealed_config_hash

    root = Path(config.workspace.project_root)
    runs = runs_dir_for(root)
    if not runs.is_dir():
        return None
    config_hash = run_identity_hash(
        config.model_dump(mode="json"), inputs=input_file_digests(config)
    )
    if config_hash is None:
        return None
    versions: list[tuple[int, Path]] = []
    for entry in runs.iterdir():
        if not entry.is_dir():
            continue
        stem, version = split_stem_version(entry.name)
        if stem == name:
            versions.append((1 if version is None else version, entry))
    for _version, run_dir in sorted(versions, reverse=True):
        if sealed_config_hash(run_dir) != config_hash:
            continue
        sim_id = str(read_manifest(run_dir)["run"]["sim_id"])
        return (run_dir.name, sim_id)
    return None


def identical_run_message(name: str | None, sim_id: str) -> str:
    """The line that says an identical completed run made this one unnecessary."""
    label = name or sim_id[:8]
    return f"Config identical to completed run '{label}' [{sim_id[:8]}]; nothing to do."


def run_simulation(
    config_path: str | Path,
    *,
    name: str | None = None,
    resume: str | None = None,
    from_step: str | int | None = None,
    until_step: str | int | None = None,
    no_display: bool = False,
    frozen: bool = False,
    dry_run: bool = False,
    parallel: bool = True,
    force: bool = False,
    fresh: bool = False,
    overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute one attempt of a case from a TOML file, the worker verb.

    The run is named ``name``, else ``[simulation] name`` (which a TOML file
    defaults to its own stem). A plain run identical to an already completed
    run (:func:`completed_identical_run`) is skipped and returns a
    ``{"skipped": True, "name", "sim_id", "project_root"}`` summary, unless
    ``force`` is set. Resume, partial and dry runs always proceed. The index
    is never opened here: the summary comes from the run directory, and the
    caller indexes it afterwards. ``overrides`` are the dotted paths a
    ``--set`` or an overlay changed, sealed in ``lineage.overrides``.
    """
    from hydromodpy.project import Project
    from hydromodpy.results.lineage import Lineage

    with Project(config_path, no_display=no_display) as project:
        run_name = name or project.config.simulation.name or Path(config_path).stem
        project_root = str(Path(project.config.workspace.project_root))
        plain_run = (
            not force
            and resume is None
            and from_step is None
            and until_step is None
            and not dry_run
        )
        if plain_run:
            existing = completed_identical_run(project.config, name=run_name)
            if existing is not None:
                exist_name, exist_sid = existing
                return {
                    "skipped": True,
                    "name": exist_name,
                    "sim_id": exist_sid,
                    "project_root": project_root,
                }
        lineage = Lineage(overrides=dict(overrides)) if overrides else None
        result = project.execute(
            name=run_name,
            resume=resume,
            from_step=from_step,
            until_step=until_step,
            dry_run=dry_run,
            frozen=frozen,
            no_display=no_display,
            parallel=parallel,
            fresh=fresh,
            force=force,
            lineage=lineage,
        )
        if result is None:
            return {}
        summary: dict[str, Any] = {
            "name": result.name,
            "sim_id": result.sim_id,
            "project_root": project_root,
            "run_dir": str(result.run_dir),
            "status": result.status,
        }
        project_ctx = getattr(project, "_ctx", None)
        project_setup = getattr(project_ctx, "setup", None)
        project_plan = getattr(getattr(project_ctx, "execution", None), "simulation_plan", None)
        mesh_summary = getattr(project_setup, "mesh_summary", None)
        has_mesh_process = any(
            getattr(run, "process_type", None) == "mesh"
            for run in getattr(project_plan, "runs", ()) or ()
        )
        if has_mesh_process and isinstance(mesh_summary, Mapping):
            summary.update(dict(mesh_summary))
        return summary


DISPATCH: dict[str, Callable[..., dict[str, Any]]] = {
    "simulation": run_simulation,
    "overview": run_overview,
    "calibration": run_calibration,
}


def dispatch_workflow(workflow: str, config_path: Path, **kwargs: Any) -> dict[str, Any]:
    """Dispatch to the adapter for a resolved workflow name."""
    runner = DISPATCH[workflow]
    return runner(config_path, **kwargs)


__all__ = [
    "DISPATCH",
    "calibration_phases_or_raise",
    "completed_identical_run",
    "declared_calibration_phases",
    "dispatch_workflow",
    "identical_run_message",
    "no_such_phase",
    "run_calibration",
    "run_overview",
    "run_simulation",
]
