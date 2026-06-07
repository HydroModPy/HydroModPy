Visual identity and style guide
===============================

Reference for the colours, typography, and figure conventions used
across the HydroModPy documentation, the Python figures emitted by the
results layer, and the gallery thumbnails.

Logo and favicon
----------------

Source files live in ``docs/source/images/``:

- ``logoHydroModPy.png`` square logo, used as favicon and as the
  light-theme navbar icon at small sizes.
- ``logoHydroModPy_long.png`` horizontal lock-up, used as the navbar
  logo and the LaTeX cover.
- ``logoHydroModPy_fond.png`` background variant for hero sections.
- ``logoHydroModPy.ico`` Windows-friendly favicon.

The Sphinx config wires them in through ``html_logo``, ``html_favicon``
and ``html_theme_options.logo``. Vector SVG variants will replace the
PNG assets when the brand kit is finalised.

Colour palette
--------------

The palette is anchored on two scientific cues: groundwater (cool blue)
and weathered bedrock (warm ochre). Both are intentionally desaturated
so they read well behind dense plots and in print.

.. list-table::
   :header-rows: 1
   :widths: 18 15 67

   * - Role
     - Hex
     - Usage
   * - Primary water
     - ``#1f6feb``
     - Headings accent, primary CTA, hydraulic head colour ramp anchor
   * - Secondary rock
     - ``#d97706``
     - Catchment boundaries, ochre accents, callouts
   * - Vegetation
     - ``#15803d``
     - Land cover overlays, recharge-related diagrams
   * - Substratum
     - ``#52525b``
     - Bedrock cross sections, neutral text accents
   * - Background mute
     - ``#f4f5f7``
     - Card surfaces, inactive panels

Matplotlib figures emitted by ``hydromodpy.display`` follow the same
roles. The colourmap defaults remain ``viridis`` for continuous fields
and a custom diverging map anchored on the primary water blue for
signed quantities (drawdown, residuals).

Typography
----------

- Body text: ``Inter`` with ``IBM Plex Sans`` as a fallback. Both ship
  through the PyData theme via Google Fonts when available.
- Code: ``JetBrains Mono``. Pygments style remains ``sphinx`` for
  consistency with the rendered theme.
- Headings: same family as body, weight 600 for ``h1``/``h2``, weight
  500 for ``h3``/``h4``. Keep line length below ~75 characters for the
  text width set in ``_static/custom.css``.

Figures and diagrams
--------------------

- Mermaid is the default for simple flowcharts, decision trees, and
  family overviews (``modflow_family_map``,
  ``solver_choice_decision``).
- PlantUML stays for detailed UML class diagrams and sequence diagrams
  where Mermaid does not have feature parity.
- Static raster screenshots use PNG. SVG is preferred whenever the
  figure is generated, not captured.
- Every gallery case carries a 1024 x 720 PNG thumbnail. Source for
  generated thumbnails sits in ``tools/doc_gallery/``.

Open Graph and social cards
---------------------------

The future ``sphinxext-opengraph`` integration (Phase 2 step 25) will
produce a 1200 x 630 PNG card per page. The default card composes the
horizontal logo with the page title on the
``#f4f5f7`` background mute.

Accessibility
-------------

- Contrast ratio targeted at 4.5:1 for body text, 3:1 for large
  headings.
- Colours never carry meaning alone. Always pair colour with a label,
  hatching, or a marker shape on plots.
- Animations follow ``prefers-reduced-motion``. The CSS rules in
  ``_static/custom.css`` honour the system preference.
