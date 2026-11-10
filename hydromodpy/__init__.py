"""Public entry points for HydroModPy."""

from __future__ import annotations

import importlib
import warnings

# Public API facade. This is the single allowed exception to the
# "no aliases / no re-exports" rule in CLAUDE.md. CLI verbs and Python
# user code must reach the same canonical symbols through this module,
# so the verbs in `hydromodpy/_api` are re-exported here on purpose.
from hydromodpy._api import (
    calibrate,
    calibration_phases,
    compare,
    compare_pair,
    doctor,
    example_add,
    example_list,
    example_show,
    export,
    figure,
    index,
    open,
    read,
    replay,
    report,
    run,
    spinup,
)
from hydromodpy._lazy import LAZY_IMPORTS as _LAZY_IMPORTS
from hydromodpy._lazy import MODULE_EXPORTS as _MODULE_EXPORTS
from hydromodpy._lazy import OLD_NAMES as _OLD_NAMES
from hydromodpy.core.logging import DEFAULT_VERBOSITY, LogManager, verbosity_from_env
from hydromodpy.core.version import __version__

# ``bootstrap()`` is deferred to first real use (config validation, a verb,
# Project, or the CLI handler) via ``core.runtime.bootstrap_hook``. A
# calibration fills its own trial pipeline at session start, so ``import
# hydromodpy`` and ``hmp --help`` stay cheap. The symbol ``hydromodpy.bootstrap``
# is gone: the module carried a start-up hook, and a hook the library calls
# itself is a provider, not a capability of the package.

__author__ = "Alexandre Gauvain, Ronan Abherve, Jean-Raynald de Dreuzy"
__email__ = (
    "alexandre.gauvain.ag@gmail.com, ronan.abherve@inrae.fr, jean-raynald.de-dreuzy@univ-rennes.fr"
)

_log_manager = LogManager(
    mode=verbosity_from_env() or DEFAULT_VERBOSITY, log_dir=None, overwrite=False
)

_DIRECT_EXPORTS = [
    "open",
    "index",
    "read",
    "example_add",
    "example_list",
    "example_show",
    "export",
    "figure",
    "run",
    "replay",
    "calibrate",
    "calibration_phases",
    "spinup",
    "compare",
    "compare_pair",
    "report",
    "doctor",
    "__version__",
]


def __getattr__(name: str):
    if name in _MODULE_EXPORTS:
        module = importlib.import_module(_MODULE_EXPORTS[name])
        globals()[name] = module
        return module
    if name in _LAZY_IMPORTS:
        target = _LAZY_IMPORTS[name]
        if ":" in target:
            module_path, attr_name = target.split(":", 1)
        else:
            module_path, attr_name = target, name
        module = importlib.import_module(module_path)
        attr = getattr(module, attr_name)
        globals()[name] = attr
        return attr
    if name in _OLD_NAMES:
        entry = _OLD_NAMES[name]
        if entry.refused:
            from hydromodpy.core.exceptions import OldNameError

            raise OldNameError(
                f"hydromodpy.{name} left the top level before {entry.since}. Use {entry.new}."
            )
        # stacklevel=1 names this file: the console routing hides a deprecation it
        # reads as a third party's, and the reader of this one wrote the call.
        warnings.warn(
            f"hydromodpy.{name} is now hydromodpy.{entry.new}. The old name keeps working for "
            f"two minor versions from {entry.since}.",
            FutureWarning,
            stacklevel=1,
        )
        return getattr(importlib.import_module(__name__), entry.new)
    raise AttributeError(f"module 'hydromodpy' has no attribute {name!r}")


__all__ = [*_DIRECT_EXPORTS, *_LAZY_IMPORTS]
