Packages
========

One page per top-level subpackage of ``hydromodpy/``. Each page is the
``README.md`` of the package, so the page and the folder cannot disagree. A README
gives the parts of the package in dependency order, its import rules, how the
main flow goes through it, and a "where to add what" table. A package that has a
layout contract also has an ``*_layout.yaml`` beside the architecture gate.

The cards, with the role of each package and the counts read from the code
(variables, figures, steps), are generated: :doc:`../generated/packages`. For the
import rules between packages, see :doc:`../layered-architecture`. For the
recipes, see :doc:`../how-to/index`.

``validity_frame`` is the one page that is not a package of ``hydromodpy/``. It
describes the experimental observability project next to it.

.. toctree::
   :maxdepth: 1

   ../generated/packages
   core
   config
   physics
   data
   spatial
   solver
   simulation
   calibration
   results
   catalog
   display
   analysis
   reporting
   workflow
   project
   examples
   schema
   cli
   validity_frame
