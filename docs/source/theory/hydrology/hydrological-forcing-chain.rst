Hydrological Forcing Chain
==========================

Purpose
-------

This page documents how HydroModPy moves from hydrological or climatic
information to groundwater-model forcing.

Today that logic exists in code, but the scientific story is scattered between
API pages, PyHELP helpers, data-manager contracts, and solver adapters.

Use this page when the question is mainly:

- where the data enters,
- how it is aligned in time,
- how it is passed to ``Flow``.

Use :doc:`recharge-and-surface-exchange-semantics` when the question is mainly:

- what recharge means,
- how it differs from runoff or drainage,
- what negative recharge and ETP mean physically.

Current Chain At A Glance
-------------------------

The current forcing chain can already be summarized as:

.. code-block:: text

   external data or prepared files
   -> data managers
   -> LoadResult
   -> forcing bridge and time alignment
   -> Flow runtime payloads
   -> solver adapter translation
   -> recharge, ETP, or related solver inputs

Runoff currently follows a different path and is mostly reused on the
observation, calibration, or comparison side rather than injected directly
into the groundwater solve.

One basin example
-----------------

On the Nancon reference case, the data-overview workflow first exposes the
climatic and observation context. The simulation workflow then turns selected
forcing families into solver inputs and result diagnostics.

.. gallery-figure:: /_static/capability_gallery/geographic/geographic_nancon_identity_card_climatic_summary.png
   :alt: Nancon climatic summary before simulation
   :width: 100%

   The climatic panel is still pre-solver evidence: it documents the forcing
   context that will later be normalized and bound to ``Flow``.

.. gallery-figure:: /_static/capability_gallery/simulation/nancon_transient_nwt_water_budget.png
   :alt: Nancon water budget after simulation
   :width: 100%

   The water budget is post-solver evidence. It shows how normalized recharge,
   ETP, storage, and drainage choices appear after backend assembly and solve.

Main Families Involved
----------------------

The repository currently manipulates several distinct families:

- direct recharge data,
- precipitation and climatic variables,
- evapotranspiration data,
- runoff time series,
- PyHELP-derived recharge and hydrological outputs,
- synthetic forcing used by validation or calibration cases.

These families do not all play the same scientific role. Some are direct model
inputs, while others are intermediate hydrological products or observational
comparators.

PyHELP's Role
-------------

PyHELP currently acts as a hydrological preprocessing and coupling layer rather
than as the central scientific narrative of the documentation.

The relevant code path is mainly:

- ``hydromodpy.physics.hydrology.pyhelp``
- ``hydromodpy.physics.hydrology.pyhelp.preprocessing.pipeline``
- ``hydromodpy.physics.flow.structure_binders``

From the repository contents, PyHELP can already produce at least:

- recharge,
- runoff,
- evapotranspiration,
- percolation-related outputs,
- daily or aggregated exported files.

What This Page Now Covers Versus Its Companion
----------------------------------------------

This page now covers mainly the chain and transformation logic:

- data managers,
- forcing resolution,
- time alignment,
- binding into ``Flow``,
- transfer toward solver adapters.

The companion page :doc:`recharge-and-surface-exchange-semantics` now covers
mainly the physical distinctions between:

- recharge,
- ETP,
- runoff,
- and boundary or drainage exchange concepts.

For a dedicated treatment of ``stream``, ``ocean``, and ``drainage``, see
:doc:`stream-ocean-and-drainage-semantics`.

Why This Gap Matters
--------------------

Right now, someone can understand the software path by reading:

- ``hydromodpy.physics.forcing.forcing_bridge``,
- ``hydromodpy.physics.forcing.time_alignment``,
- ``hydromodpy.physics.flow.structure_binders``,
- and the PyHELP package.

What remains hard to recover is the scientific intent:

- which quantity is conceptual versus measured,
- which one is imposed versus derived,
- and why a given forcing path is preferred in one workflow.

Current Source Anchors
----------------------

Useful anchors for the full future version are:

- ``hydromodpy.physics.forcing.forcing_bridge``
- ``hydromodpy.physics.forcing.time_alignment``
- ``hydromodpy.physics.flow.structure_binders``
- ``hydromodpy.physics.hydrology.pyhelp``
- ``hydromodpy.physics.hydrology.synthetic.forcing``
- ``hydromodpy.data`` variable managers
- :doc:`recharge-and-surface-exchange-semantics`
- :doc:`stream-ocean-and-drainage-semantics`
