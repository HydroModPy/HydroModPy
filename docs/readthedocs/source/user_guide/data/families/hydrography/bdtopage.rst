Hydrography Source: bdtopage
============================

Use ``source = "bdtopage"`` when the French BD Topage hydrographic network is
the expected reference.

Minimal example
---------------

.. code-block:: toml

   [[data.hydrography.sources]]
   source = "bdtopage"

Operational checks
------------------

- Check network density against the intended drainage interpretation.
- Check outlet alignment before comparing observed and simulated active
  networks.
- Use a source-specific overlay when documenting that BD Topage itself is the
  provider under test.

Visual reference
----------------

.. figure:: /_static/capability_gallery/geographic/geographic_bdtopage_hydrography_overlay.png
   :alt: BD Topage hydrography overlay
   :width: 100%

   This figure isolates the BD Topage layer so the provider result can be read
   independently from geology or station panels.
