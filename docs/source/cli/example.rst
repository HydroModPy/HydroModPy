hmp example
===========

``hmp example`` drops one shipped example into a scaffolded workspace: the
authored configs into ``projects/<name>/``, the data they read into
``data/<variable>/``.

The catalogue ships inside the wheel, so ``hmp example list`` answers with no
network and cannot promise what the installed version does not know about.

.. code-block:: bash

   hmp example list                    # what this build ships, and what is missing here
   hmp example show 04                 # file by file, each marked cached or missing
   hmp example add 04                  # fetch what is missing and write it into the workspace

What it caches, and why the file is the unit
---------------------------------------------

The payload is dominated by one shared file:
``examples/data/dem/DEM_armorican_massif.tif`` is 90 MiB of the ~92 MiB
example 04 needs, and many example projects read that same regional DEM. So
the unit that is cached is the file, not the example: blobs live under
``<cache>/examples/blobs/<sha256[:2]>/<sha256>``, the DEM is downloaded once,
and a second ``hmp example add`` downloads nothing.

Every file is verified against the ``sha256`` the manifest declares. A
mismatch is a hard failure: the partial download is deleted and the error
names the file and where it came from.

Flags of ``hmp example add``
------------------------------

.. list-table::
   :header-rows: 1
   :widths: 26 74

   * - Flag
     - Meaning
   * - ``-w``, ``--workspace PATH``
     - Workspace root to install into. Default: the usual workspace
       resolution, ``~/hydromodpy``. The workspace must already exist; run
       ``hmp workspace init`` first.
   * - ``--ref REF``
     - Git ref to fetch from. Default: ``v`` followed by the installed
       HydroModPy version, so a release only ever fetches its own files.
   * - ``--force``
     - Overwrite a destination file whose content differs from the manifest.
       Without it such a file is kept and reported, so local edits to a step
       config survive a re-install.

Fetching from somewhere else
------------------------------

Files are fetched from
``https://raw.githubusercontent.com/HydroModPy/HydroModPy/<ref>/<path>``.
The environment variable ``HMP_EXAMPLES_SOURCE`` replaces that whole prefix,
``<ref>`` included, with another URL or a local directory:

.. code-block:: bash

   HMP_EXAMPLES_SOURCE=file:///path/to/HydroModPy hmp example add 04

That is one rule and not a special case: when the variable is set, ``--ref``
no longer applies. It is what makes an offline install, a mirror, and a test
against a checkout the same code path.

Regenerating the catalogue
----------------------------

The manifest is generated from a source checkout, never hand-edited:

.. code-block:: bash

   hmp dev examples manifest

It walks an explicit whitelist, resolves each project's data references
through the run pipeline's own config loader, hashes every file and rewrites
``hydromodpy/examples/catalog.toml``. A unit test regenerates it and compares
the bytes, so the shipped catalogue cannot drift from the repository.

Related pages
-------------

- :doc:`/getting_started/nancon-tutorial` installs example 04 with this
  command and runs it end to end.
- :doc:`/user_guide/concepts/workspace-layout` for the ``data/<variable>/``
  resolution rules the installed files land in.
