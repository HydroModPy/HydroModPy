"""Atomic workflow steps.

Each step is a function that takes a ``WorkflowContext``, mutates it,
and has no knowledge of the pipeline that calls it.
"""
