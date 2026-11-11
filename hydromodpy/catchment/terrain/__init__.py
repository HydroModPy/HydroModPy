"""Terrain port and the engines that serve it.

The port is importable without any flow-routing library: ``port`` holds the
Protocol and its value types and imports nothing heavier than the exception
module. The two engines, ``numpy_engine`` and ``whitebox_engine``, are imported
by name, so a caller that only needs the vocabulary never pulls in
``whitebox_workflows``.

``registry`` is the selection point, and every caller of an engine goes
through it. It
resolves the two engines of this tree and anything installed under the
``hydromodpy.terrain.engine`` entry-point group, and it certifies a candidate on
the members the port declares. That is all a registry can certify: the port also
requires artifacts on disk, and only
``tests/ports/test_terrain.py`` sees those. It is
parametrized on what the registry resolves, so it runs an outside engine without
naming it.
"""
