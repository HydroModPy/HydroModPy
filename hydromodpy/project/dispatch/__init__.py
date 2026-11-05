"""Dispatch adapters that bind workflow launchers to the public ``Project``.

These modules sit above the architectural matrix because they depend on
:class:`hydromodpy.project.Project`. The matrix layers (``calibration``,
``workflow``, ``analysis``) must not reach Project, so the adapters live
here instead.

- :mod:`.workflow` exposes ``dispatch_workflow``, ``DISPATCH`` and the
  ``run_*`` functions used by the CLI and the public ``hmp.run`` facade.
- :mod:`.rerun` exposes the ``Project``-backed rerun provider.
"""
