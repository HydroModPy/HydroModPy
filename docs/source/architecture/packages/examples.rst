examples
========

``hydromodpy.examples`` is what ``hmp example`` stands on: the catalogue of
shipped examples, the cache their files are fetched into, and the generator
that writes the catalogue from a checkout. It is a leaf above ``core`` and
nothing else imports it but the CLI.

Why a file cache and not an archive
-----------------------------------

The payload of one example is dominated by one shared file.
``examples/data/dem/DEM_armorican_massif.tif`` is 90 MiB of the ~92 MiB
example 04 needs, and 15 of the example projects point at that same DEM. So
the unit that is cached is the **file**, not the example: a zip per example
would re-ship the DEM every time, while a blob keyed by its ``sha256`` is
downloaded once and every later example that reads it costs nothing.

Blobs live at ``<cache>/examples/blobs/<sha256[:2]>/<sha256>``, beside the
solver binaries ``hmp install-binaries`` caches, under
:func:`hydromodpy.core.state.paths.cache_dir`.

Sub-modules
-----------

- ``manifest.py`` -- the dataclasses (``ExampleFile``, ``ExampleEntry``),
  the reader for the packaged ``catalog.toml``, and ``render_catalog``,
  the emitter that produces its exact bytes. The emitter is hand-written
  rather than delegated to a TOML writer because a test compares the file
  byte for byte.

- ``catalog.toml`` -- the manifest itself, shipped inside the wheel through
  ``[tool.setuptools.package-data]``. ``hmp example list`` therefore answers
  with no network, and cannot promise what the installed version does not
  know about.

- ``blobs.py`` -- the content-addressed cache and the download. A sha256
  that does not match what the manifest declares is a hard failure: the
  partial blob is deleted and the error names the file and the source it
  came from. ``HMP_EXAMPLES_SOURCE`` replaces the whole
  ``https://raw.githubusercontent.com/HydroModPy/HydroModPy/<ref>`` prefix,
  so the same code path serves a release tag, a ``file://`` URL and a local
  checkout.

- ``install.py`` -- writing one example into a scaffolded workspace: the
  authored files under ``projects/<directory>/``, the data files under
  ``data/<variable>/``. A destination that already matches the manifest is
  left alone; one that differs is a file somebody edited and is kept, and
  reported, unless ``--force`` is given.

- ``generate.py`` -- the whitelist and the generator behind
  ``hmp dev examples manifest``. It reads each project config through the
  run pipeline's own ``load_toml_with_base_config``, so a variant that only
  overrides ``station_ids`` inherits the ``source`` and ``path`` its parent
  declared, exactly as it does at run time.

The whitelist has one entry
---------------------------

``examples/projects/`` holds 35 directories, including ``new_to_sort``,
three competing Nançon variants, and two authored TOMLs carrying absolute
Windows paths. One of them, ``04_streamflow_intermittence_in_transient``, is
maintained and verified end to end. Announcing a catalogue of 35 of which
one works is worse than announcing one, so the whitelist is explicit and a
project earns a line in it once it runs from a freshly scaffolded
workspace.

Layer-matrix neighbours
-----------------------

``examples`` imports only ``core``: an example is described by paths, sizes
and hashes, never by a loaded configuration. ``cli`` imports ``examples``
through ``cli/_workers/example.py``. Nothing imports it in the other
direction.
