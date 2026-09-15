API Reference
=============

The API reference is generated automatically from docstrings via
``autosummary``. It documents the public facade and the top level of each
subpackage, one page each, under ``api/generated/``.

It is deliberately *not* recursive. Recursing produced 1290 pages of which
11 rendered a single Python object, and those empty pages dominated the
site search. Reference material with a declared contract lives where the
contract lives: TOML configuration in :doc:`/user_guide/config_reference/index`,
command-line verbs in :doc:`/cli/index`, the supported Python verbs in
:doc:`/python_api/index`. To read a submodule, follow the source link on
its parent page.

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
   hydromodpy.read
   hydromodpy.export
   hydromodpy.run
   hydromodpy.calibrate
   hydromodpy.index
   hydromodpy.compare_pair
   hydromodpy.report
   hydromodpy.bootstrap_proj
   hydromodpy.doctor

Public subpackages
------------------

These subpackages expose stable, user-facing APIs (configuration root,
project catalog, run facade, display registry, calibration helpers).
Each gets one page carrying its module docstring and a summary of its
direct members.

.. autosummary::
   :toctree: generated

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
:doc:`/architecture/index`. Listings are not recursive; read the layer
matrix and the source rather than expecting a page per module.

.. autosummary::
   :toctree: generated

   hydromodpy.analysis
   hydromodpy.core
   hydromodpy.data
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
