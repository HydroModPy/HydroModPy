"""Unit-test package namespace.

This avoids collisions between test subpackages such as ``tests.unit.mesh``
and real top-level packages like ``mesh`` during pytest collection.
"""
