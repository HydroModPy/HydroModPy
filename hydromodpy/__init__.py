"""Public entry points for HydroModPy.

The top level holds the fifteen verbs of :mod:`hydromodpy.project.api`, the five
objects they take and return, the three readers ``read``, ``index`` and ``Catalog``
that the frozen runs of 2.0.0 are read through, the categories of the exception
hierarchy and ``__version__``. Nothing is imported until it is used, so ``import hydromodpy``
stays cheap.
"""

from __future__ import annotations

import importlib
import warnings

# PROJ_DATA is set once here, before any import loads pyproj, for the CLI and for
# Python alike. Nothing writes it again during a run.
from hydromodpy.core.io.proj_bootstrap import bootstrap_proj as _bootstrap_proj

_bootstrap_proj()

# Public API facade. This is the single allowed exception to the "no aliases / no
# re-exports" rule in CLAUDE.md: the verbs and the objects of hydromodpy.project.api
# are reached here on purpose, through the lazy table.
from hydromodpy._lazy import KEPT_EXCEPTIONS as _KEPT_EXCEPTIONS  # noqa: E402
from hydromodpy._lazy import KEPT_READERS as _KEPT_READERS  # noqa: E402
from hydromodpy._lazy import LAZY_IMPORTS as _LAZY_IMPORTS  # noqa: E402
from hydromodpy._lazy import OBJECTS as _OBJECTS  # noqa: E402
from hydromodpy._lazy import OLD_NAMES as _OLD_NAMES  # noqa: E402
from hydromodpy._lazy import VERBS as _VERBS  # noqa: E402
from hydromodpy.core.logging import DEFAULT_VERBOSITY, LogManager, verbosity_from_env  # noqa: E402
from hydromodpy.core.version import __version__  # noqa: E402

__author__ = "Alexandre Gauvain, Ronan Abherve, Jean-Raynald de Dreuzy"
__email__ = (
    "alexandre.gauvain.ag@gmail.com, ronan.abherve@inrae.fr, jean-raynald.de-dreuzy@univ-rennes.fr"
)

_log_manager = LogManager(
    mode=verbosity_from_env() or DEFAULT_VERBOSITY, log_dir=None, overwrite=False
)


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name].split(":", 1)
        attr = getattr(importlib.import_module(module_path), attr_name)
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


__all__ = [*_VERBS, *_OBJECTS, *_KEPT_READERS, *_KEPT_EXCEPTIONS, "__version__"]
