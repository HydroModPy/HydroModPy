Conceptual Model
================

Purpose
-------

This page is didactic. It does not start from package names or output files.
It starts from one physical scene: a land surface, a groundwater head, and
possibly a line support on the surface.

The same scene can lead to three different modelling decisions:

- impose an exchange condition on a known stream support;
- let groundwater emerge where the solved head reaches the surface;
- convert simulated emergence into an active-network diagnostic.

Those decisions are close in space but different in meaning. Keeping them
separate is what prevents the documentation from treating a river line, a
seepage flux, and a validation mask as if they were the same object.

In the sketches below, a river is intentionally drawn as a line or support on
the land surface, not as a cross-sectional water body with thickness. The
question is groundwater-surface exchange: where is the groundwater head
relative to the local topographic or channel surface?

The Shared Physical Reading
---------------------------

Before choosing a method, read the section in the same way each time.

``z_s(x)``
   The local surface elevation. It may be a topographic surface or a channel
   bed elevation, but in these sketches it remains a surface line.

``h(x)``
   The groundwater head solved by the groundwater model. It is not prescribed
   by the seepage method; it is the state that decides whether emergence is
   possible.

``S``
   The support where an exchange or diagnostic is evaluated. Depending on the
   method, it can be a known stream line, a set of surface-adjacent cells, or a
   post-processing graph.

``q``
   An exchanged flux. In the methods below it is computed from the solved head
   and the chosen support; it is not a raw rainfall or runoff forcing.

This reading gives the progression used below: first decide what is known,
then decide what the solver computes, then decide whether the result should be
interpreted as a budget term or as a network diagnostic.

Three Questions, Three Methods
------------------------------

.. list-table::
   :header-rows: 1
   :widths: 27 28 25 20

   * - Scientific question
     - Method family
     - Prescribed object
     - Computed object
   * - I know the surface support and want exchange against a known hydraulic
       level.
     - Stream-style boundary
     - support ``S_stream`` and ``H_stream``
     - exchange flux ``q_stream``
   * - I want the model to decide where groundwater emerges at the surface.
     - Seepage or drainage operator
     - support ``S_seep`` and local surface ``z_s``
     - one-way outflow ``q_seep``
   * - I want a map of the stream network implied by simulated emergence.
     - Simulated-active diagnostic
     - positive seepage field and routing graph
     - accumulation ``A_i`` and mask ``m_i``

The methods are therefore not a hierarchy of increasingly detailed rivers.
They answer different questions. The stream boundary is a hydraulic exchange
condition. Seepage is a surface-emergence condition. The simulated-active
network is an interpretation of model outputs.

Method 1 - Stream Boundary
--------------------------

Use this method when a surface support is known and a hydraulic level can be
assigned to it. The support may come from observed linework, generated
hydrography, or a model-specific package input, but the important point is
that the support and its stage/head exist before the groundwater solve.

.. figure:: /_static/concepts/streams_and_seepage/method_stream_stage_boundary.svg
   :alt: Didactic stream boundary sketch showing prescribed stage or head and computed exchange flux
   :width: 100%

   The method starts from a zero-thickness surface support. The prescribed
   value is the hydraulic level on that support, not a drawn volume of river
   water. The solver computes the exchange flux after solving ``h``.

Once this physical reading is fixed, the schematic law is:

.. math::

   \begin{aligned}
   q_\mathrm{stream}
   &=
   C_\mathrm{stream}
   \left(H_\mathrm{stream} - h\right)
   \end{aligned}

In this notation, positive ``q_stream`` is drawn toward the aquifer. If
``H_stream > h``, the boundary supplies water to the aquifer. If
``H_stream < h``, the sign reverses and the aquifer discharges toward the
support. The conductance controls the strength of the coupling. It does not
turn the support into a surface-water routing model.

The intelligent use of this method is therefore not "there is a river, so use
stream". It is: "I have a support and I accept prescribing its hydraulic level
as an external condition."

Method 2 - Seepage Or Drainage
------------------------------

Use this method when the active exchange should be decided by the solved
groundwater head. The support still exists, but the method does not prescribe a
stream stage. It asks whether the solved head reaches the local surface.

.. figure:: /_static/concepts/streams_and_seepage/method_seepage_drainage_operator.svg
   :alt: Didactic seepage and drainage sketch showing conditional release controlled by solved head
   :width: 100%

   The surface line is the activation reference. Where ``h_i`` remains below
   ``z_s,i``, there is no surface outflow. Where ``h_i`` reaches or exceeds the
   surface, groundwater can emerge and the excess is released as seepage or
   drainage outflow.

The compact expression is:

.. math::

   \begin{aligned}
   q_{\mathrm{seep}, i}
   &=
   C_i
   \max \left(h_i - z_{s,i}, 0\right)
   \end{aligned}

The equation is best read as a surface inequality, not as a small river
formula. Below the surface, the outflow is zero. Above the surface, the
positive excess head is converted into an outflow controlled by conductance.
In HydroModPy outputs, this local positive release may still be stored or
compared under drainage names such as ``outflow_drain``.

The intelligent use of this method is: "I do not want to prescribe the active
river level. I want emergence to be a consequence of the groundwater solution."

Method 3 - Simulated Active Network
-----------------------------------

Use this method after the solve, when the question becomes geographical rather
than hydraulic: which parts of the landscape are active according to the
simulated seepage or drainage field?

.. figure:: /_static/concepts/streams_and_seepage/method_simulated_active_postprocess.svg
   :alt: Didactic simulated active network sketch showing postprocessed routed drainage outflow
   :width: 100%

   The active network is inferred from surface-emergence points and routed
   downstream. It is not a new boundary condition and it does not create a
   river volume in the groundwater solve.

The post-processing logic is:

.. math::

   \begin{aligned}
   q_i^+ &= \max\left(q_{\mathrm{seep}, i}, 0\right) \\
   A_i   &= q_i^+ + \sum_{j \in U(i)} A_j \\
   m_i   &= \mathbf{1}\left[A_i \ge Q_\mathrm{thr}\right]
   \end{aligned}

Here ``A_i`` is an accumulated diagnostic flux, ``U(i)`` is the set of upstream
cells or mesh faces, and ``m_i`` is a thresholded active-network mask. The mask
is useful for visual interpretation or comparison against reference linework,
but it is not itself a water-budget term.

The intelligent use of this method is: "I need a map-like interpretation of
where the model predicts active seepage-connected drainage, and I must state
the threshold or time-window rule used to obtain that map."

Choosing Between The Methods
----------------------------

.. list-table::
   :header-rows: 1
   :widths: 34 32 34

   * - If your known information is...
     - Prefer...
     - Because...
   * - A known stream support and an acceptable prescribed stage/head.
     - Stream boundary.
     - The main uncertainty is the exchange magnitude, not the existence of the
       boundary level.
   * - A surface where groundwater may or may not emerge.
     - Seepage or drainage operator.
     - The active outflow must be decided by the solved groundwater head.
   * - A simulated outflow field and an observed network to compare against.
     - Simulated-active diagnostic.
     - The hydraulic solve is finished; the remaining question is spatial
       interpretation and validation.
   * - A need for routed channel hydraulics, water depth, or downstream surface
       flow storage.
     - A surface-water routing concept, not the methods on this page.
     - These sketches intentionally do not represent river thickness or channel
       water volume.

This is the key separation: stream boundaries prescribe a hydraulic level,
seepage operators impose an emergence rule, and simulated-active networks
interpret outputs. They can be connected in a workflow, but they should not be
collapsed into one vocabulary word.

From Concept To Evidence
------------------------

After choosing the method, do not jump directly to the most attractive figure.
Use examples that preserve the same separation:

- if the question is conceptual choice, stay on this page and compare the
  three method sketches;
- if the question is what is implemented and what is still a non-contract,
  read :doc:`status-and-limitations`;
- if the question is the MODFLOW 6 implementation path, read
  :doc:`../hydrology/simulated-active-network` and check the sequence
  ``head`` -> ``outflow_drain`` -> ``accumulation_flux`` -> mask;
- if the question is sensitivity on a real basin, read
  :doc:`nancon-k-sweep-results`;
- if the question is a legacy MODFLOW-NWT baseline, read the Nancon capability
  gallery case linked from :doc:`worked-examples`;
- if the question is what to open after a comparison run, use
  :doc:`worked-examples` and
  :doc:`../../getting_started/comparison-output-reading-order`.

The rule is the same in every example: the files are useful only when the
method role, support role, computed field, and validation target are explicit.

Implementation Maps
-------------------

The diagrams below are implementation maps. They are useful after the method
logic above is clear.

.. uml:: diagrams/boundary_vs_seepage_operator.wsd

Read this diagram left to right:

1. A stream-style exchange starts from a support and a known stage/head.
2. A seepage/drainage exchange starts from a support, conductance, and local
   surface elevation.
3. In both cases, the exchanged flux is a solver result, not an observed runoff
   time series.

.. uml:: diagrams/active_network_decision_tree.wsd

This decision tree is useful when reading results.

- If the question is water balance, use ``outflow_drain``.
- If the question is active stream structure, use ``accumulation_flux`` or a
  mask derived from it.
- If the question is validation against observed hydrography, compare the mask
  with ``reference`` linework.
- If the question is a persisted vector stream network, define the threshold,
  timestep/window, and vectorization rule first. HydroModPy does not silently
  invent that canonical vector role.

Common Mistakes
---------------

Avoid these interpretations:

- ``stream`` does not currently mean full surface-water routing.
- ``seepage`` is not diffuse recharge in reverse; it is a conditional surface
  release controlled by ``h - z_s``.
- ``outflow_drain`` is not the same object as a river line.
- ``accumulation_flux`` should not be summed as a water-budget term.
- ``simulated_active`` is not a measured network unless it is explicitly
  compared with ``reference``.

Related Reading
---------------

- :doc:`../hydrology/stream-ocean-and-drainage-semantics`
- :doc:`../hydrology/simulated-active-network`
- :doc:`worked-examples`
- :doc:`status-and-limitations`
- :doc:`nancon-k-sweep-results`
- :doc:`../../architecture/overview/hydrographic-network-simulated-active-inventory`
