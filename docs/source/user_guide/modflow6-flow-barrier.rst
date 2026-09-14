Flow Barriers and Dam Cutoff Walls (MODFLOW 6 HFB)
==================================================

Use a flow barrier to represent a thin, near-impermeable vertical wall inside the
aquifer: a dam cutoff wall (grout curtain), a sheet pile, a sealed fault. It is
modeled with the MODFLOW 6 Horizontal Flow Barrier (HFB) package, which lowers
the horizontal conductance across the cell faces a trace line crosses, without
refining the grid. The barrier is face-based and grid-independent (DIS / DISV).

The flow barrier is MODFLOW 6 only. Declare the flow process with
``solvers = ["modflow6"]``.

Two ways to declare it
----------------------

The same payload (:class:`~hydromodpy.physics.flow.FlowBarrierConfig`) is used in
two places:

* **General addon** ``[flow.sinks_sources.flow_barriers.<id>]`` for any model.
* **Dam cutoff wall** ``[flow.sinks_sources.lakes.<id>.cutoff_wall]``, the
  lake-derived use, where the barrier sits on the dam axis and forces the
  under-dam seepage below the wall instead of leaking through the top layers.

Both resolve through the same builder and end up as a single ``HFB`` package.

Payload
-------

A barrier needs a trace and a resistance:

* ``line`` -- inline vertices ``[[x, y], ...]`` in the project CRS, **or**
  ``line_path`` -- a vector file (gpkg / shapefile / GeoJSON). Exactly one.
* ``depths`` -- depth below the model top, in metres. One value is uniform; a
  list is interpolated per vertex along the trace. The HFB blocks every top
  layer down to this depth, so a depth shallower than the aquifer thickness
  leaves a path *under* the wall.
* ``hydchr`` (+ ``hydchr_unit``, default ``1/s``) -- the HFB hydraulic
  characteristic ``K_barrier / thickness_barrier`` [1/T]; a near-zero value
  (e.g. ``1e-9 1/s``) is a quasi-impermeable wall. **Or** give ``k`` (+
  ``k_unit``) and ``thickness`` (+ ``thickness_unit``) and let ``hydchr``
  derive from them. Exactly one of the two groups.

Declaring a dam cutoff wall
---------------------------

Add the ``cutoff_wall`` sub-table to the lake. The trace runs across the valley
on the dam axis, at the downstream edge of the reservoir:

.. code-block:: toml

   [flow.sinks_sources.lakes.reservoir_cheze.cutoff_wall]
   line = [[331142.0, 6780439.3], [331119.4, 6780718.7]]
   depths = [10.0]
   hydchr = 1e-9
   hydchr_unit = "1/s"

A general flow barrier (no lake)
--------------------------------

.. code-block:: toml

   [flow.sinks_sources.flow_barriers.fault_seal]
   line_path = "fault_seal.gpkg"
   depths = [30.0]
   k = 1e-9
   k_unit = "m/s"
   thickness = 0.5
   thickness_unit = "m"

Execution model
---------------

1. the structure binders resolve each trace (inline coords or vector file) into a
   shapely line and attach it to the runtime payload
   (``apply_cutoff_wall_to_flow`` for lakes, ``apply_flow_barriers_to_flow`` for
   the general addon); the binders run on both the normal and the
   calibration / override plan paths;
2. at model build the trace is mapped onto the interior mesh faces it crosses,
   spanning each layer from the model top down to ``depths``;
3. a single ``HFB`` package is written after ``LAK`` and after ``NPF`` (it scales
   the NPF-computed horizontal conductance); it carries no MVR coupling.

The barrier is static (one stress-period entry, period 0).

Behaviour
---------

A partial wall (``depths`` shallower than the aquifer) seals the top layers and
forces the flow to dive underneath: in the Cheze reservoir example the top-layer
horizontal flow across the dam collapses to near zero, the remaining seepage is
deepened into the layer below the wall, and the net under-dam seepage toward the
outlet drops. The lake-aquifer exchange rises because blocking the shallow
downstream outflow raises the head on the lake side. To cut the seepage further,
deepen the wall so it also spans the lower layers.

See also
--------

* :doc:`modflow6-lake` -- the lake / reservoir boundary the cutoff wall attaches to.
* :doc:`solvers` -- the MODFLOW 6 backend and the DISV grid the HFB sits on.
