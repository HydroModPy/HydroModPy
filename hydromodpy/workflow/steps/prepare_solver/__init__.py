"""The step that opens a run on disk: plan, facts, inputs and frozen configuration.

``PrepareSolverStep`` lives in ``step.py``. This folder imports ``record``, ``state``
and ``step``, never the reverse, and ``resolved.py`` is read by
``workflow/replay_checks.py`` at the root. In the order a run reaches the modules,
``step`` plans, ``dispatch`` opens the run (it calls ``facts``, ``freeze``, ``resolved``
and ``prepare``), ``model`` builds the ``Model``, and then ``step`` persists the
parameters, the provenance and the forcings. A run that writes nothing, such as a
calibration trial, skips the run directory and still builds its ``Model``. A fact
recorded at the start of a run goes to ``facts.py`` with a field of ``RunFacts`` in
``results/storage/run_facts.py``. A new input persisted for the run goes to
``forcings.py`` for forcings or to ``prepare.py`` for the parameters, the mesh and the
geographic data. A form of ``restart_from`` goes to ``restart.py``, a key of the frozen
configuration to ``freeze.py`` and its resolved form to ``resolved.py``, and work done
when the run directory opens goes to ``dispatch.py``.
"""
