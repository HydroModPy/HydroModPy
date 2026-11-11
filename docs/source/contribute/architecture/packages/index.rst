Packages
========

One page per top-level subpackage of ``hydromodpy/``. Each page is the
README of the package, then the table of its modules generated from their first
docstring line, then what holds the package together: the parts in dependency
order, the import rules inside it, the main flow and where to add what. A package
that has a layout contract also has an ``*_layout.yaml`` beside the architecture
gate. ``python -m tools.docs.check_readmes`` checks that a README sits only in a
package or a port folder.

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
   model
   data
   catchment
   mesh
   solver
   calibration
   results
   display
   workflow
   project
   schema
   cli
   validity_frame
