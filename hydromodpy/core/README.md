# core

The kernel leaf of HydroModPy. Every other package may read `core`, and `core` reads no sibling package, not even under `TYPE_CHECKING`. It holds what several layers need and none should own: the base of every config model, units, the paths of a project and a workspace, run state, the I/O primitives, the typed exceptions and a few kernels that two layers must compute the same way, such as the sign of a budget flux and the digest of a block of values.

A sub-package answers one question, and `scoring/` is the port of the goodness-of-fit metrics, with a README of its own. The modules at the root hold the words every layer shares, for example the step names of `pipeline_steps.py`, the hierarchy of `exceptions.py` and the version string.

Each exception carries one of sixteen `Category` values, set once on the class that owns it and inherited below. `cli` maps a category to its exit code, so a new exception needs no line in the command line. `logging.py` keeps the handlers that a run adds in one `SinkRouter`, so no handler is added to the process logger while a run writes its log.

Importing `hydromodpy.core` loads neither the configuration nor the data stack. A helper used by one layer stays in that layer, and it moves here when a second layer needs it and the layer matrix forbids the edge.

The page of the package in the developer docs lists the modules with the first line of their docstring and tells how the folders fit together.
