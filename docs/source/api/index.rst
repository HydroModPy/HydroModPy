API Reference
=============

The API reference is generated automatically from docstrings via
``autosummary :recursive:``. Every public subpackage is walked top-down and
each public class, function, and module gets its own page under
``api/generated/``.

Top-level facade functions live under :mod:`hydromodpy`. The Pydantic
configuration root lives under :mod:`hydromodpy.config`. Domain layers
(``data``, ``solver``, ``calibration``, ...) follow the architecture matrix
documented in :doc:`/architecture/index`.

Top-level entry points
----------------------

.. autosummary::
   :nosignatures:
   :toctree: generated

   hydromodpy.open
   hydromodpy.run
   hydromodpy.calibrate
   hydromodpy.catalog
   hydromodpy.overview
   hydromodpy.batch
   hydromodpy.compare_pair
   hydromodpy.mesh
   hydromodpy.testbed
   hydromodpy.report
   hydromodpy.bootstrap_proj
   hydromodpy.doctor

Subpackages
-----------

.. autosummary::
   :toctree: generated
   :recursive:

   hydromodpy.analysis
   hydromodpy.calibration
   hydromodpy.config
   hydromodpy.core
   hydromodpy.data
   hydromodpy.display
   hydromodpy.physics
   hydromodpy.results
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
