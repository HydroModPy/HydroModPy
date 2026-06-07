Solver binaries policy
======================

HydroModPy wraps native solvers (MODFLOW 6, MODFLOW-NWT, MODPATH 6/7,
MT3D-USGS). These executables are **not** shipped inside the wheel: the
wheel stays under 5 MB and binaries land lazily in a per-user cache on
first use.

Cache layout
------------

The managed cache lives at ``~/.cache/hydromodpy/bin/`` (or the platform
equivalent via the OS XDG/AppData conventions). Solvers are stored in a
flat layout produced by ``flopy.utils.get_modflow``:

.. code-block:: text

   ~/.cache/hydromodpy/bin/
   ├── mf6
   ├── mfnwt
   ├── mp6
   ├── mp7
   ├── mt3dusgs
   └── .manifest.json

``.manifest.json`` records the MODFLOW-ORG/executables release tag and the download
timestamp:

.. code-block:: json

   {
     "release": "23.0",
     "downloaded_at": "2026-04-29T12:34:56+00:00",
     "solvers": ["mf6", "mfnwt", "mp6", "mp7", "mt3dusgs"]
   }

A custom directory can be passed via the ``HYDROMODPY_BIN`` env var or the
``--bindir`` flag of ``hmp install-binaries``. When ``bin_path`` is
user-supplied, HydroModPy never writes into it: missing binaries surface
at solver execution time with a clear ``FileNotFoundError``.

Pre-warming the cache
---------------------

.. code-block:: bash

   # Install all solvers (default)
   hmp install-binaries

   # Restrict to a subset
   hmp install-binaries --subset mf6,mfnwt

   # Force re-download of the pinned release
   hmp install-binaries --upgrade

   # Pin a specific release tag (reproducibility)
   hmp install-binaries --release 18.0

The default release is ``23.0``. Once a binary lands in the cache it is
**not** auto-refreshed: the same version stays in place for the lifetime
of the cache so a run started today yields the same results a year from
now. Upgrades are explicit (``--upgrade``).

Lazy download on first use
--------------------------

Solvers also download on first use. When a ``flow_modflow6`` or
``flow_modflow_nwt`` adapter is invoked and the matching binary is missing
from the managed cache, ``ensure_solver_binary`` calls
``download_solver_binaries`` automatically. Subsequent runs go offline.

For air-gapped or CI deployments, run ``hmp install-binaries`` once during
provisioning so subsequent runs are deterministic and offline-safe.

Source and integrity
--------------------

The binaries are pulled from the MODFLOW-ORG Executables release on GitHub
(``MODFLOW-ORG/executables``) by ``flopy.utils.get_modflow``. Integrity is
guaranteed by GitHub TLS (HTTPS) plus the release tag pin. We do not
ship a separate SHA-256 manifest because the upstream release is the
authoritative source, and pinning ``--release`` to a specific tag is the
recommended reproducibility lever.

If your environment requires offline-verifiable hashes, drop the
binaries manually into a directory and pass it via ``HYDROMODPY_BIN`` or
``--bindir``: HydroModPy will use the files as-is without re-downloading.

Wheel build invariants
----------------------

* ``pyproject.toml`` ``[tool.setuptools.package-data]`` must not list
  ``bin/**/*`` or any solver executable name.
* ``MANIFEST.in`` ``prune bin`` plus the ``global-exclude`` line on solver
  filenames keep stray binaries out of sdists and wheels.
* CI build sanity-check: ``python -m build`` followed by
  ``unzip -l dist/hydromodpy-*.whl | grep -E 'mf6|mfnwt|mt3dusgs'`` must
  return nothing.
