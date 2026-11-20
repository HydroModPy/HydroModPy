"""Dispatch adapters that bind workflow launchers to the public ``Project``.

These modules sit above the architectural matrix because they depend on
:class:`hydromodpy.project.facade.Project`. The matrix layers (``calibration``,
``workflow``, ``analysis``) must not reach Project, so the adapters live
here instead.

- :mod:`.workflow` exposes ``dispatch_workflow``, ``DISPATCH`` and the
  ``run_*`` functions used by the CLI and the public ``hmp.run`` facade.
- :mod:`.rerun` runs a sealed configuration again, for ``hmp catalog rerun``.

``dispatch/`` is the one place in ``project`` that imports ``Project`` outside
``TYPE_CHECKING``, and only inside functions. ``launch/`` and ``exchange/`` never do.
``cli`` calls ``rerun_config`` directly, and no lower layer reaches ``rerun.py``. The
``rerun`` of this folder replays a run from its configuration, which has nothing to do
with the ``rerun`` of a solver adapter. A new workflow name is a ``run_*`` function and
an entry of ``DISPATCH`` in ``workflow.py``, and the list of names lives in
``workflow/dispatch.py``. A run option that reaches ``hmp run`` is a keyword of
``run_simulation``, the same as on ``Project.execute``.
"""
