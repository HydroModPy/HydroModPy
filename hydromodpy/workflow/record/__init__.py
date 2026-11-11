"""What a run writes about itself, and what is read back to resume or check it.

The claim of the run directory and its outcome, the store opened for one caller, the step
journal, the manifest that signs the step blueprint and the resume plan live here. Nothing
here runs a step. ``record/`` imports ``state`` and ``step`` (and ``core`` and ``results``)
and never ``steps/``, because ``steps/`` imports ``record`` and the other way would close a
cycle. That is also why ``replay_checks.py`` sits at the root of ``workflow``.

A column of the step journal is a field of ``WorkflowStepRow`` in ``journal.py``, with
``JOURNAL_SCHEMA`` changed when the format changes. Something the manifest must match at
resume goes to ``manifest.py``, a rule for choosing the resume step to ``resume.py`` and a
state of the attempt (claim, heartbeat, outcome, withdrawal) to ``attempt.py``. A new kind
of artifact that a step can name goes to ``collect_artifacts`` in ``workflow/runner.py``.
"""
