"""Workflow dispatch adapters that bind launchers to ``Project``.

Wires user-facing entry points (``run_simulation``, ``run_overview``,
``run_calibration``, ``run_comparison``, ``run_testbed``) to the matching
workflow launchers. Lives under :mod:`hydromodpy.project.dispatch` because
it depends on :class:`hydromodpy.project.Project`; the lower
``hydromodpy.workflow`` package stays independent from that facade.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast


def run_overview(config_path: str | Path) -> dict[str, Any]:
    """Generate a watershed identity card from a TOML file."""
    from hydromodpy.workflow.pipelines.overview import DataOverviewLauncher

    return DataOverviewLauncher(config_path).run()


def run_calibration(config_path: str | Path) -> dict[str, Any]:
    """Run a parameter calibration campaign from a TOML file."""
    from hydromodpy.calibration.runners.cli_runner import run_calibration_cli

    return cast(dict[str, Any], run_calibration_cli(config_path))


def run_comparison(config_path: str | Path) -> dict[str, Any]:
    """Run a comparison workflow from a TOML file."""
    from hydromodpy.analysis.comparison.dispatch import run_comparison_config

    return run_comparison_config(config_path)


def _completed_run_with_same_config(project: Any) -> tuple[str | None, str] | None:
    """Return ``(name, sim_id)`` of a completed run whose resolved config is
    byte-identical to ``project``'s, or None.

    Mirrors the ``config_hash`` the catalog records at registration
    (``sha256`` of the resolved config JSON). Read-only and fail-open: any
    error returns None so the run proceeds normally.
    """
    import hashlib
    import json

    from hydromodpy.core.state.paths import catalog_path_for
    from hydromodpy.results.catalog import Catalog

    try:
        config_dict = project.config.model_dump(mode="json")
        config_hash = hashlib.sha256(json.dumps(config_dict, sort_keys=True).encode()).hexdigest()
        root = Path(project.config.workspace.project_root)
        if not (catalog_path_for(root)).exists():
            return None
        with Catalog(root, read_only=True) as catalog:
            matches = catalog.find(config_hash=config_hash, status="completed")
            if len(matches) == 0:
                return None
            run = matches[0]
            return (run.name, run.sim_id)
    except Exception:
        return None


def run_simulation(
    config_path: str | Path,
    *,
    resume: str | None = None,
    from_step: str | int | None = None,
    until_step: str | int | None = None,
    no_display: bool = False,
    frozen: bool = False,
    dry_run: bool = False,
    parallel: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Execute a single simulation from a TOML file.

    A plain run whose resolved config matches an already-completed run is
    skipped (returns a ``{"skipped": True, ...}`` summary) unless ``force`` is
    set; resume / partial / dry runs always proceed.
    """
    from hydromodpy.project import Project

    with Project(config_path, no_display=no_display) as project:
        # ``[simulation] name`` is the single identity entry (it defaults to the
        # run_-stripped TOML stem at config load). Honour it so the CLI matches
        # the Python API and the declared name is not silently dropped.
        run_name = project.config.simulation.name or Path(config_path).stem
        plain_run = (
            not force
            and resume is None
            and from_step is None
            and until_step is None
            and not dry_run
        )
        if plain_run:
            existing = _completed_run_with_same_config(project)
            if existing is not None:
                exist_name, exist_sid = existing
                return {"skipped": True, "name": exist_name, "sim_id": exist_sid}
        result = project.simulate(
            name=run_name,
            resume=resume,
            from_step=from_step,
            until_step=until_step,
            dry_run=dry_run,
            frozen=frozen,
            no_display=no_display,
            parallel=parallel,
        )
        if result is None:
            return {}
        summary: dict[str, Any] = {
            "name": result.name,
            "sim_id": result.sim_id,
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


class ProjectTestbedRunnerProvider:
    """Testbed runner provider backed by public workflow adapters."""

    def run_simulation(self, config_path: Path, *, no_display: bool) -> Mapping[str, Any]:
        """Run one simulation child configuration."""
        return dict(run_simulation(config_path, no_display=no_display))

    def run_comparison(self, config_path: Path) -> Mapping[str, Any]:
        """Run one comparison child configuration."""
        return dict(run_comparison(config_path))

    def run_calibration(self, config_path: Path) -> Mapping[str, Any]:
        """Run one calibration child configuration."""
        return dict(run_calibration(config_path))


def run_testbed(config_path: str | Path) -> dict[str, Any]:
    """Run a method-testbed workflow from a TOML file."""
    from hydromodpy.analysis.testbed.profiles import (
        GENERIC_TESTBED_PROFILE,
        REGIONAL_LAB_PROFILE,
        resolve_testbed_profile,
    )
    from hydromodpy.analysis.testbed.runtime import TestbedLauncher
    from hydromodpy.core.toml_io import load_toml_with_base_config

    raw_toml = load_toml_with_base_config(Path(config_path).expanduser().resolve())
    profile = resolve_testbed_profile(raw_toml)
    if profile == REGIONAL_LAB_PROFILE:
        from hydromodpy.analysis.testbed.regional_lab import RegionalLabProfileLauncher

        return RegionalLabProfileLauncher(config_path).run()
    if profile != GENERIC_TESTBED_PROFILE:
        raise ValueError(f"Unsupported testbed profile: {profile}")
    return TestbedLauncher(config_path).run()


def run_site_selection(config_path: str | Path) -> dict[str, Any]:
    """Run a site-selection workflow from a TOML file."""
    from hydromodpy.workflow.site_selection import run_site_selection_workflow

    return run_site_selection_workflow(config_path)


DISPATCH: dict[str, Callable[..., dict[str, Any]]] = {
    "simulation": run_simulation,
    "overview": run_overview,
    "calibration": run_calibration,
    "comparison": run_comparison,
    "testbed": run_testbed,
    "site_selection": run_site_selection,
}


def dispatch_workflow(workflow: str, config_path: Path, **kwargs: Any) -> dict[str, Any]:
    """Dispatch to the adapter for a resolved workflow name."""
    runner = DISPATCH[workflow]
    return runner(config_path, **kwargs)


__all__ = [
    "DISPATCH",
    "ProjectTestbedRunnerProvider",
    "dispatch_workflow",
    "run_calibration",
    "run_comparison",
    "run_overview",
    "run_simulation",
    "run_site_selection",
    "run_testbed",
]
