MODFLOW Family Methods
======================

Purpose
-------

This page is a scientific counterpart to the existing MODFLOW architecture
notes. Its purpose is to document what HydroModPy asks the MODFLOW-family
backends to represent physically and numerically.

Scope
-----

The target scope is the HydroModPy use of:

- MODFLOW-NWT as the legacy structured-grid backend,
- MODFLOW 6 as the modern backend that can also consume DISV-style runtime
  meshes,
- the associated transport and particle-tracking ecosystem where relevant.

Common Scientific Role
----------------------

Within HydroModPy, MODFLOW-family backends are used as groundwater-flow
engines that interpret the same solver-agnostic ``[flow]`` payload through
different numerical and package-level contracts.

At a high level, this includes:

- hydraulic properties,
- initial heads,
- imposed-head or head-dependent boundaries,
- recharge and wells,
- storage terms in transient runs.

Backend Split
-------------

MODFLOW-NWT
^^^^^^^^^^^

The current scientific position of MODFLOW-NWT in HydroModPy is:

- structured-grid path,
- compatibility with the historical MT3DMS and MODPATH ecosystem,
- legacy but still important validation and comparison baseline.

MODFLOW 6
^^^^^^^^^

The current scientific position of MODFLOW 6 in HydroModPy is:

- modern flow backend,
- support for both structured and runtime unstructured mesh paths,
- preferred route when irregular DISV meshes are part of the workflow.

Method Choices That Need Explicit Documentation
-----------------------------------------------

The repository already contains parts of the rationale, but they still need
one stronger scientific anchor and one synthesized overview.

The main choices that should be documented together are:

- why structured versus DISV support exists,
- when MODFLOW 6 is preferred over MODFLOW-NWT,
- how HydroModPy maps the ``[flow]`` scientific payload to packages such as
  NPF, STO, RCHA, WEL, CHD, DRN, or EVT,
- why XT3D is auto-enabled on unstructured MODFLOW 6 meshes,
- what numerical trade-off HydroModPy currently accepts for that choice.

Existing Evidence Already Present In The Repository
---------------------------------------------------

Useful material already exists and should later be consolidated here:

- :doc:`../../architecture/solver/modflow6-architecture-notes`
- :doc:`../../architecture/solver/modflownwt-architecture-notes`
- developer note ``docs/developers/modflow_contracts.md``
- developer note ``docs/developers/modflow6_gmsh_disv_development_perspective.md``
- the generated XT3D method-choice assets under
  ``docs/readthedocs/source/_static/capability_gallery/validation/``

Detailed Companion Pages
------------------------

The scientific material now branches into more focused notes:

- :doc:`modflow-governing-equation-and-cvfd-formulation`
- :doc:`modflow6-vs-modflownwt-scientific-comparison`
- :doc:`mesh-and-discretization-strategies`
- :doc:`field-to-cell-parameter-transfer`
- :doc:`vertical-representation-and-storage-assumptions`
- :doc:`modflow-package-semantics-and-boundary-conditions`
- :doc:`xt3d-on-irregular-disv-meshes`

What This Page Still Needs To Add
---------------------------------

The full version should later cover more than the first public synthesis:

1. one tighter package-by-package synthesis spanning ``IMS``, ``NPF``, ``STO``,
   ``RCHA``, ``EVT``, ``CHD``, ``DRN``, ``WEL``, and ``OC``,
2. transport coupling boundaries and the exact current public MT3DMS / GWT
   story,
3. more explicit reasons for keeping MODFLOW-NWT alive and for planning its
   sunset,
4. at least one worked case that follows a real HydroModPy TOML to final
   solver package payloads.

Current Documentation Gap
-------------------------

The gap is narrower than before.

HydroModPy now has a first public scientific block for:

- governing-equation framing,
- MF6 versus NWT comparison,
- package semantics and option selection,
- XT3D rationale,
- mesh and parameter-transfer context.

What still remains missing is not the existence of a scientific narrative, but
its next level of consolidation:

- one worked end-to-end MODFLOW case,
- fuller transport-coupling coverage,
- and a clearer statement of the public package subset actually maintained
  across workflows.
