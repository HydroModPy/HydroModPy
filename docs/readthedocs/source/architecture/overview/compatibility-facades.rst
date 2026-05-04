Compatibility Facades
=====================

HydroModPy keeps a small number of compatibility facades so documentation,
notebooks, and older scripts can keep stable import paths while implementation
modules move.

These facades should stay thin:

- they re-export public objects from their canonical implementation modules;
- they should not own solver, workflow, or result-store logic;
- they are acceptable when they unblock documented public imports;
- they should be removed only through an explicit deprecation path.

Current examples include:

- ``hydromodpy.compare`` as a public alias for the pairwise comparison facade;
- ``hydromodpy.pipeline`` as a re-export layer for workflow pipeline classes;
- ``hydromodpy.results.config`` as a re-export layer for result persistence
  configuration.

The canonical implementation remains in the lower-level packages. The facade
exists only to keep the public surface and generated API documentation stable.
