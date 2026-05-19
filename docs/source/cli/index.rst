CLI Reference
=============

HydroModPy exposes two equivalent console entry points, :command:`hmp`
and :command:`hydromodpy`. The documentation uses :command:`hmp` for
brevity. The surface is split into seven hierarchical families plus a
set of flat top-level verbs kept for fast everyday use. Each leaf
parser carries its own ``--help`` text, so the family pages below stay
short and focus on intent rather than exhaustive flag tables.

Run ``hmp --help`` to discover the top-level layout, or
``hmp <family> --help`` to list the sub-actions of a family.

Families
--------

.. toctree::
   :maxdepth: 1

   project
   catalog
   workspace
   viz
   audit
   privacy
   dev

Operational reference
---------------------

.. toctree::
   :maxdepth: 1

   exit-codes
   completion

Flat top-level verbs
--------------------

The following verbs sit directly under :command:`hmp` and are not (yet)
nested in a family. They cover the most common workflow loop and a few
maintenance helpers: :command:`hmp run`, :command:`hmp calibrate`,
:command:`hmp test`, :command:`hmp report`, :command:`hmp compare`,
:command:`hmp doctor`, :command:`hmp install-binaries`,
:command:`hmp add`, :command:`hmp import`, :command:`hmp export`,
:command:`hmp export-package`, :command:`hmp data`,
:command:`hmp display`, and :command:`hmp index`. The flat
:command:`hmp index` verb is kept for the global workspace index and
will be folded into a family in a later interface iteration.
