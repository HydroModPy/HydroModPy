"""HydroModPyLauncher — generic pipeline orchestrator.

Usage::

    from launcher import HydroModPyLauncher

    result = HydroModPyLauncher("path/to/config.toml").run()

Or from the CLI::

    python -m launcher run path/to/config.toml
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from launcher.hook_registry import HookRegistry
from launcher.phases import PHASE_FN
from launcher.run_result import RunResult

_VALID_PHASES = frozenset(PHASE_FN.keys())


class HydroModPyLauncher:
    """Orchestrates HydroModPy phases driven by a TOML configuration file.

    Parameters
    ----------
    config_path : str | Path
        Path to the ``config.toml`` file.  A ``hooks.py`` file placed in the
        same directory is automatically discovered and loaded.
    """

    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path).resolve()
        self.cfg = HydroModPyConfig.from_toml(self.config_path)

        # Allow tests (and CI) to redirect outputs without touching config.toml.
        # Mirrors the pattern used in example12.py:
        #   if os.environ.get("HYDROMODPY_OUT_PATH"):
        #       cfg.workspace.out_dir_path = Path(os.environ["HYDROMODPY_OUT_PATH"])
        if out_path_env := os.environ.get("HYDROMODPY_OUT_PATH"):
            self.cfg.workspace.out_dir_path = Path(out_path_env)

        with self.config_path.open("rb") as fh:
            raw_toml = tomllib.load(fh)

        self.result = RunResult(
            cfg=self.cfg,
            config_path=self.config_path,
            raw_toml=raw_toml,
        )
        self.registry = HookRegistry.discover(self.config_path)

    def run(self) -> RunResult:
        """Execute all phases listed in ``cfg.run.phases`` in order.

        Before and after each phase the corresponding hooks are called
        (``on_before_<phase>`` / ``on_after_<phase>``).

        Returns
        -------
        RunResult
            The fully populated result object.
        """
        unknown = [p for p in self.cfg.run.phases if p not in _VALID_PHASES]
        if unknown:
            raise ValueError(
                f"Unknown phase(s) in [run].phases: {unknown}. "
                f"Allowed: {sorted(_VALID_PHASES)}"
            )

        for phase in self.cfg.run.phases:
            print(f"[Launcher] -- phase: {phase} --------------------------")
            self.registry.call(f"on_before_{phase}", self.result)
            PHASE_FN[phase](self.result)
            self.registry.call(f"on_after_{phase}", self.result)

        print("[Launcher] Done.")
        return self.result
