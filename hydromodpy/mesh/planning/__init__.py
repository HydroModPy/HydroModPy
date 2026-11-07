"""The mesh planner: from ``[mesh]`` and the project inputs to one mesh request.

One entry point, ``plan.plan_mesh_request``, and ``plan.smoothed_catchment``,
which gives the catchment outline it smoothed. The other modules build what the
planner reads: the size field and its gap terms, the geology contacts (a vector
map, or an analytical support), a triangulation from a ``.msh`` file, the
refinement zones (vector layers, or thresholds on the height above the stream or
on a field of an earlier run), and the hydraulic structures of the lakes.
"""
