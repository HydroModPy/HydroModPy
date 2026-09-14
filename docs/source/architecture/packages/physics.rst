physics
=======

``hydromodpy.physics`` is the process layer. It turns validated
configuration into the runtime ``Flow`` and ``Transport`` objects
that solver adapters consume. Forcing alignment and the optional
``pyhelp`` coupling also live here.

Sub-modules
-----------

- ``physics/base/`` -- generic process contracts.
  ``ProcessSpatial[TIC]`` ABC plus the prototypes for
  ``InitialCondition``, ``BoundaryCondition``, ``SinkSource``, and
  ``ProcessSpatialConfig``.
- ``physics/flow/`` -- concrete groundwater-flow process. ``Flow``
  runtime, ``FlowConfig`` Pydantic, dedicated initial / boundary /
  sinks-sources payloads.
- ``physics/transport/`` -- concrete transport process. ``Transport``
  runtime plus per-solver parameter blocks
  (``modpath.parameters``, ``mt3dms.parameters``,
  ``modflow6gwt.parameters``).
- ``physics/forcing/`` -- ``ForcingBridge`` and ``time_alignment``
  helpers that turn ``LoadResult`` into solver-ready
  series. ``resolve_forcing`` dispatches on spatial mode
  (homogeneous vs heterogeneous).
- ``physics/hydrology/`` -- conceptual helpers: ``pyhelp/`` wraps
  PyHELP (preprocessing ERA5 grids, output JSON / NetCDF);
  ``synthetic/`` generates analytical recharge and ETP series.

Key public symbols
------------------

- ``hydromodpy.physics.base.process_spatial.ProcessSpatial``
- ``hydromodpy.physics.flow.flow.Flow``
- ``hydromodpy.physics.flow.flow_config.FlowConfig``
- ``hydromodpy.physics.transport.transport.Transport``
- ``hydromodpy.physics.transport.transport_config.TransportConfig``
- ``hydromodpy.physics.forcing.forcing_bridge.resolve_forcing``
- ``hydromodpy.physics.forcing.time_alignment.align_forcing_series_to_simulation_window``

Process contract
----------------

Every concrete process inherits ``ProcessSpatial[TIC]``:

.. code-block:: python

   class ProcessSpatial(ABC, Generic[TIC]):
       parameters: dict[str, FieldParam]
       initial_conditions: TIC | None
       boundary_conditions: dict[str, BoundaryCondition]
       sinks_sources: dict[str, SinkSource]

       @abstractmethod
       def build_initial_conditions(self, ...) -> TIC | None: ...
       @abstractmethod
       def set_boundary_conditions(self, ...): ...
       @abstractmethod
       def set_sinks_sources(self, ...): ...

The shared base is intentionally narrow: the per-process payload
(``FlowInitialConditions``, ``TransportInitialConditions``) carries
the meaning, the abstract methods carry the lifecycle.

Recommended reading path
------------------------

1. ``hydromodpy/physics/base/README.md``
2. ``hydromodpy/physics/base/process_spatial.py``
3. ``hydromodpy/physics/flow/README.md``
4. ``hydromodpy/physics/flow/flow.py`` and ``flow_config.py``
5. ``hydromodpy/physics/forcing/forcing_bridge.py``
6. ``hydromodpy/physics/transport/transport.py`` once the flow path
   is clear.

Layer-matrix neighbours
-----------------------

- Allowed targets: ``core``, ``schema``, ``physics``.
- Documented tolerance: ``physics`` -> ``spatial`` because
  ``FlowConfig`` embeds a discriminated union of ``FieldSection``
  variants. Do not extend that tolerance to other models.
- Allowed sources: ``simulation``, ``solver``, ``calibration``,
  ``analysis``, ``config``, ``workflow``, ``cli``.

See also
--------

- :doc:`solver` for the backend adapters that consume process
  objects.
- :doc:`spatial` for the ``FieldSection`` discriminated union and
  the mesh contract.
- :doc:`/architecture/how-to/add-a-process` -- step-by-step recipe.
- :doc:`/architecture/how-to/add-a-config-field` for the per-field
  conventions on ``FlowConfig`` / ``TransportConfig``.
