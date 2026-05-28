API Reference
=============

The API reference is generated automatically from docstrings via
``autosummary :recursive:``. Every public subpackage is walked top-down
and each public class, function, and module gets its own page under
``api/generated/``.

Top-level facade functions live under :mod:`hydromodpy`. The Pydantic
configuration root lives under :mod:`hydromodpy.config`. Domain layers
(``data``, ``solver``, ``calibration``, ...) follow the architecture
matrix documented in :doc:`/architecture/index`.

Public facade
-------------

The single supported import path is ``import hydromodpy as hmp``. The
V1 facade re-exports the verbs and helpers below from
``hydromodpy._api``. For the structural contracts and the field
registry, see :doc:`/architecture/overview/contracts`.

.. autosummary::
   :nosignatures:
   :toctree: generated

   hydromodpy.open
   hydromodpy.open_catalog
   hydromodpy.read
   hydromodpy.run
   hydromodpy.calibrate
   hydromodpy.index
   hydromodpy.overview
   hydromodpy.compare_pair
   hydromodpy.mesh
   hydromodpy.testbed
   hydromodpy.report
   hydromodpy.bootstrap_proj
   hydromodpy.doctor

Public subpackages
------------------

These subpackages expose stable, user-facing APIs (configuration root,
project catalog, run facade, display registry, calibration helpers).
Their listings are recursive: every public class, function, and
submodule gets its own generated page.

.. autosummary::
   :toctree: generated
   :recursive:

   hydromodpy.config
   hydromodpy.results
   hydromodpy.display
   hydromodpy.calibration
   hydromodpy.catalog
   hydromodpy.project

Internal subpackages
--------------------

These subpackages are exposed for contributors extending HydroModPy.
They follow the strict layered architecture documented in
:doc:`/architecture/index`. Listings are not recursive; click through
to a module to read its direct members.

.. autosummary::
   :toctree: generated
   :recursive:

   hydromodpy.analysis
   hydromodpy.core
   hydromodpy.data
   hydromodpy.discretization
   hydromodpy.physics
   hydromodpy.reporting
   hydromodpy.schema
   hydromodpy.simulation
   hydromodpy.solver
   hydromodpy.spatial
   hydromodpy.workflow

Docstring policy
----------------

.. toctree::
   :maxdepth: 1

   docstring-policy
