News & Timeline
===============

Keep track of releases, compatibility notes, and events related to HydroModPy.
Add a new card whenever a version ships, a breaking change lands, or the toolbox
appears in a conference.

.. dropdown:: How to read this page?
   :color: info
   :icon: info

   The cards below only highlight major events or updates (public releases,
   announcements, conferences). Treat this view as a mini HydroModPy blog that
   spotlights key milestones.

   For the full history, minor fixes included, rely on the raw ``CHANGELOG.md``
   embedded at the bottom of this page. It remains the authoritative log of
   every change per release.

.. grid:: 1 1 2 2
   :gutter: 2

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: news/v0_3_0
      :link-type: doc

      **November 2025 – v0.3.0**
      ^^^
      - Python baseline bumped to 3.11+.
      - The package layout now exposes ``hydromodpy`` directly (no ``src`` package).
      - Breaks compatibility with scripts importing from ``src``.


   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: news/v0_2_0
      :link-type: doc

      **October 2025 – v0.2.0**
      ^^^
      Maintenance line for Python 3.8–3.10 with documentation cleanup.

Full changelog
--------------

The raw ``CHANGELOG.md`` is embedded below so it always stays in sync with the
repository history.

.. literalinclude:: ../../../CHANGELOG.md
   :language: md

.. toctree::
   :hidden:

   news/v0_3_0
   news/v0_2_0
