"""Workflow internals - low-level orchestration primitives.

Houses the ``Pipeline`` engine, ``Step`` protocol, ``PipelineState``
hierarchy, the ``CheckpointStore`` and the ``DerivedRegistry``. Public
re-exports are pinned in S02-04.

TODO P4: ``workflow_steps`` DDL inside ``catalog.duckdb`` will replace the
former ``steps_ledger.duckdb`` once the v2 catalog schema lands.
"""
