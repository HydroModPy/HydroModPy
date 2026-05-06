MODFLOW 6 Versus MODFLOW-NWT: Scientific Comparison
===================================================

Purpose
-------

This page explains the scientific meaning of keeping both ``modflow6`` and
``modflownwt`` inside HydroModPy.

It is not a software migration guide. Its role is to answer a narrower
question:

"When two HydroModPy runs differ only by MODFLOW backend, what scientific and
numerical differences are still being exercised?"

Primary Official Anchors
------------------------

The discussion here should stay aligned with the official USGS material:

- `USGS TM 6-A55, Documentation for the MODFLOW 6 Groundwater Flow Model <https://pubs.usgs.gov/publication/tm6A55>`_
- `USGS TM 6-A56, Documentation for the XT3D Option in the Node Property Flow Package of MODFLOW 6 <https://pubs.usgs.gov/publication/tm6A56>`_
- `MODFLOW 6 Input Guide <https://modflow6.readthedocs.io/en/latest/mf6io.html>`_
- `USGS TM 6-A37, MODFLOW-NWT, A Newton Formulation for MODFLOW-2005 <https://pubs.usgs.gov/tm/tm6a37/>`_
- `Online Guide to MODFLOW-NWT <https://water.usgs.gov/ogw/modflow-nwt/MODFLOW-NWT-Guide/index.html>`_

HydroModPy documentation should synthesize these sources at project level, not
replace them.

Shared Scientific Core
----------------------

.. mermaid::

   flowchart LR
     Flow["Common HydroModPy flow payload<br/>head unknown, K/Sy/Ss,<br/>boundaries, recharge, wells"]
     NWT["MODFLOW-NWT<br/>structured DIS<br/>UPW + NWT Newton path<br/>legacy MODFLOW-2005 ecosystem"]
     MF6["MODFLOW 6<br/>structured DIS or layered DISV<br/>NPF + IMS<br/>optional Newton path<br/>XT3D when justified"]
     LegacyNeed["Structured benchmark /<br/>legacy continuity"]
     ModernNeed["Irregular support /<br/>modern default /<br/>shared natural mesh"]
     Report["Report explicitly:<br/>support equality<br/>DIS vs DISV<br/>XT3D on/off<br/>storage regime<br/>comparison intent"]

     Flow --> NWT
     Flow --> MF6
     LegacyNeed --> NWT
     ModernNeed --> MF6
     NWT --> Report
     MF6 --> Report

The scientific core stays comparable, but the backend choice still changes the
discretization contract, the internal flow package, and the nonlinear path.

Within HydroModPy, both backends are used to solve the same high-level
groundwater-flow problem:

- hydraulic head is the canonical unknown,
- hydraulic properties are carried by the solver-agnostic ``[flow]`` payload,
- storage, recharge, wells, drains, and imposed-head boundaries are normalized
  before backend translation,
- results are interpreted as cell-based groundwater solutions.

That means a backend comparison is never a comparison between unrelated
physical models. It is a comparison between two members of the MODFLOW family
that share a broad groundwater-flow interpretation, while differing in
discretization options, nonlinear treatment, package contracts, and ecosystem
history.

Why Both Backends Still Exist
-----------------------------

The short answer is:

- ``modflow6`` is the modern and more general path,
- ``modflownwt`` remains useful as a legacy structured benchmark and for
  historical workflows that still depend on the MODFLOW-2005 ecosystem.

HydroModPy therefore keeps both for different reasons:

- scientific comparison on a stable structured case,
- continuity with existing NWT, MT3DMS, or MODPATH habits,
- access to a modern MF6 path for irregular runtime meshes and evolving
  package choices.

High-Level Difference Map
-------------------------

.. list-table::
   :header-rows: 1
   :widths: 20 26 26 28

   * - Topic
     - ``modflownwt``
     - ``modflow6``
     - Scientific consequence in HydroModPy
   * - Grid family
     - Structured ``DIS`` path
     - Structured ``DIS`` or layered ``DISV`` path
     - A backend switch can also be a mesh-contract switch if the support is
       not kept identical
   * - Internal flow package
     - ``UPW`` with Newton-oriented legacy contract
     - ``NPF`` with modern MF6 package semantics
     - The intercell flow law is not identical even when the physical case is
       intended to be the same
   * - Nonlinearity handling
     - NWT-specific Newton formulation for difficult unconfined problems
     - MF6 general framework with optional Newton-Raphson path for complex
       water-table conditions
     - Convergence behaviour and wetting/drying robustness can differ
   * - Irregular runtime meshes
     - Not the HydroModPy path
     - Supported through ``DISV``
     - MF6 is the only public HydroModPy route for those comparisons
   * - XT3D
     - Not applicable in the same way
     - First-class option in ``NPF`` for irregular or anisotropic cases
     - Irregular MF6 runs can differ because of XT3D as well as because of the
       backend itself
   * - Ecosystem continuity
     - Strong historical continuity with MODFLOW-2005 family tools
     - Modern MODFLOW 6 ecosystem
     - Backend choice can also be a compatibility choice, not only a method
       choice

Discretization Contract: DIS Versus DISV
----------------------------------------

For HydroModPy, one of the most important differences is geometric.

``modflownwt`` is currently the structured-grid branch. It is the natural path
when the study deliberately keeps a raster-aligned layered grid and wants
continuity with legacy MODFLOW-2005 practice.

``modflow6`` can reproduce that structured path, but it can also consume
HydroModPy runtime irregular supports through ``DISV``. This makes it the
preferred backend whenever the scientific question requires:

- a catchment-conformal planar support,
- explicit honouring of polygon and hydrography constraints,
- one shared irregular support for solver-comparison workflows.

This also means that a naive MF6-versus-NWT comparison can silently mix two
effects:

1. backend-family differences;
2. discretization-family differences.

Those two effects should be separated whenever possible.

Internal Flow Law: UPW Versus NPF
---------------------------------

The two backends do not expose the same internal flow package.

For ``modflownwt``, the official NWT formulation is tied to the ``UPW``
package. The USGS NWT documentation states that MODFLOW-NWT must be used with
UPW and that UPW treats drying and rewetting nonlinearities through a
continuous head-based function rather than the older discrete wet/dry logic.

For ``modflow6``, the public HydroModPy path uses ``NPF``. In the MF6
documentation, ``NPF`` is part of a generalized control-volume finite-
difference framework and can be combined with options such as XT3D.

At HydroModPy level, the practical conclusion is simple:

- even if two runs share the same ``K``, ``Sy``, ``Ss``, recharge, wells, and
  boundary declarations,
- they are still being interpreted through different package-level flow
  contracts.

That does not make the comparison invalid. It means the package family is part
of the scientific method choice and should be reported as such.

Nonlinearity And Solver Behaviour
---------------------------------

The NWT path exists mainly because difficult unconfined problems are not just a
matter of linear algebra convenience.

The official NWT report describes MODFLOW-NWT as a Newton formulation intended
for drying and rewetting nonlinearities of the unconfined groundwater-flow
equation. It also states that the NWT linearization yields an asymmetric
matrix.

MF6 has a broader numerical framework. TM 6-A55 states that an optional
Newton-Raphson formulation can be activated for complex water-table problems,
and that doing so often improves convergence relative to traditional
wetting-and-drying approaches.

HydroModPy users should therefore read backend differences in two layers:

- the physical case may be the same,
- the nonlinear treatment and convergence path may still differ materially.

When one backend converges more robustly than the other, that should not be
described as an implementation accident. It is often evidence that the chosen
nonlinear formulation is part of the modelling decision.

Why MODFLOW 6 Is Usually Preferred
----------------------------------

For new HydroModPy work, ``modflow6`` is usually the stronger default choice
when:

- the support is irregular or catchment-conformal,
- DISV is required,
- XT3D is scientifically justified,
- one wants the most modern public project path,
- one wants to reduce dependence on legacy MODFLOW-2005 assumptions.

It is also the cleaner choice for comparison workflows where the support itself
is part of the experiment, especially against the in-house Boussinesq backend.

Why MODFLOW-NWT Is Still Worth Keeping
--------------------------------------

``modflownwt`` still matters when the question is specifically about:

- continuity with an established structured-grid workflow,
- legacy comparability with existing NWT studies,
- compatibility with historical transport or particle-tracking paths in the
  MODFLOW-2005 ecosystem,
- a controlled benchmark where the grid family must remain the familiar
  structured ``DIS`` contract.

In other words, keeping NWT alive is not only technical inertia. It preserves a
scientifically interpretable baseline for some classes of structured unconfined
problems and for legacy project continuity.

Concrete Result Anchor
----------------------

The figures below use one committed validation family to make the comparison
less abstract. They are not meant to prove that one backend is always better.
They show how HydroModPy publishes the same physical benchmark through two
MODFLOW-family routes.

.. tab-set::

   .. tab-item:: MODFLOW-NWT

      .. figure:: /_static/capability_gallery/validation/linearized_unconfined_hillslope_drainage_1d__modflownwt.png
         :alt: Linearized unconfined hillslope drainage rendered with MODFLOW-NWT
         :width: 100%

         The NWT result is the legacy structured-grid reading of the same
         hillslope drainage benchmark. It is useful as a continuity baseline
         for older structured MODFLOW studies.

   .. tab-item:: MODFLOW 6

      .. figure:: /_static/capability_gallery/validation/linearized_unconfined_hillslope_drainage_1d__modflow6.png
         :alt: Linearized unconfined hillslope drainage rendered with MODFLOW 6
         :width: 100%

         The MF6 result is the modern package-stack reading. It should be
         compared with the NWT result only after reporting support, package,
         storage, and solver settings.

The detailed metrics live in the committed gallery case:
:doc:`../../capability_gallery/cases/linearized_unconfined_hillslope_drainage_1d`.

What Must Be Reported In Comparisons
------------------------------------

When a page or report says "MF6 versus NWT", the following should be stated
explicitly:

- whether both runs use the exact same support,
- whether the comparison is ``DIS`` versus ``DIS`` or ``DISV`` versus
  structured ``DIS``,
- whether XT3D is active,
- whether the case is steady or transient,
- which storage terms are active,
- whether the case is mainly testing backend continuity, mesh fidelity, or
  nonlinear robustness.

Without those controls, a backend comparison becomes hard to interpret.

Recommended Reading Order
-------------------------

This page is best read together with:

- :doc:`modflow-governing-equation-and-cvfd-formulation`
- :doc:`mesh-and-discretization-strategies`
- :doc:`field-to-cell-parameter-transfer`
- :doc:`vertical-representation-and-storage-assumptions`
- :doc:`modflow-package-semantics-and-boundary-conditions`
- :doc:`xt3d-on-irregular-disv-meshes`
- :doc:`../../user_guide/concepts/comparison-workflow`

Current Limitation
------------------

This page still stays at the synthesis level. It does not yet walk package by
package through all MF6/NWT differences actually exercised by HydroModPy on
every workflow.

Its purpose is narrower: make backend choice scientifically legible before a
reader dives into package pages, comparison pages, or architecture notes.
