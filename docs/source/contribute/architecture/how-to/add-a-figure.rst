Add a figure
============

A figure is a request. It names a variable, a preset or a list of panels, in TOML
(``[[display.figure]]``), in Python (``run.figure(...)``) or on the command line
(``hmp show RUN --figure NAME``). A variable is a named quantity of a run, such as ``head``
or ``discharge``. A run is one finished simulation read from disk, for example
``hmp.open(project_dir).store["name"]``. A panel is one plot of a figure, drawn by a frame,
a module of ``hydromodpy/display/frames/`` for one kind of plot such as a map or a time
series. A preset is a named list of panels.

Each example is a block of ``tests/unit/display/test_add_a_figure.py``, which runs on a
small stored run, and each case ends with the answer the package gives when its last step
is missing. Four commands serve the page, from the root of the repository.

- ``run.figure(...)`` returns a matplotlib ``Figure``. Save it with
  ``figure.savefig("name.png")``, or from a shell with ``hmp show RUN --figure NAME --to name.png``.
- Run a script with ``PYTHONPATH=. python script.py``. A script puts its own folder first
  on the import path, so an editable install from another clone may answer instead. Check
  with ``python -c "import hydromodpy; print(hydromodpy.__file__)"``, which must print a
  path inside this checkout.
- List the variables with the command below (options: :doc:`/reference/figure-requests`).
- Guard the tables with ``python -m pytest tests/unit/results/test_field_registry_kinds.py
  tests/unit/display -q``.

.. code-block:: bash

   python -c "from hydromodpy.results import field_registry as r; \
   print(*r.all_names(), *r.REBUILT_FIELDS, *r.COLUMN_REGISTRY, sep='\n')"

Draw a variable that exists
---------------------------

Nothing to write. Give the name and the options of a panel as keywords. The frame follows
the shape of the variable, the set of axes of its values: a field over time and cells is a
map, a series over time is a line.

.. literalinclude:: /../../tests/unit/display/test_add_a_figure.py
   :start-after: # example: variable
   :end-before: # end of example
   :dedent: 4

In a shell it is ``hmp show RUN --figure head --opt time=last --opt layer=0``. A misspelt
name ends with ``Unknown figure 'hed'. Did you mean head?``

Write a composition of panels
-----------------------------

In Python a composition is a list of panels given as ``request``, and it needs no file.

.. literalinclude:: /../../tests/unit/display/test_add_a_figure.py
   :start-after: # example: panels
   :end-before: # end of example
   :dedent: 4

To keep it under a name, write a preset in the TOML file you run, the one next to
``project.toml`` that ``hmp run`` reads, as the table ``[display.presets.NAME]``. A panel
lists its ``holes``, the fields a figure may fill, and the value written in the panel is
the default.

.. literalinclude:: /../../tests/unit/display/test_add_a_figure.py
   :start-after: # example: toml
   :end-before: # end of example
   :dedent: 4

Draw the preset by its name, or with
``hmp show RUN --figure head_and_flow --opt time=first``.

.. literalinclude:: /../../tests/unit/display/test_add_a_figure.py
   :start-after: # example: preset
   :end-before: # end of example
   :dedent: 4

A preset is a way of looking at a run, so a run that already exists finds a preset
written afterwards in a TOML file of its project. A name the run was sealed with keeps its
sealed definition, so an old figure is drawn again the same. The shipped presets are in
``hydromodpy/display/presets.py``. A name that is no variable and no preset is refused with
``Unknown figure 'head_and_flow'. Did you mean ...? A figure is a variable or a preset.``

Add a variable
--------------

A registry is a Python dict of ``hydromodpy/results/field_registry.py`` that figures read.
A column of a table is one row of ``COLUMN_REGISTRY``, keyed ``table.column``. The column
must exist in ``TABLE_SCHEMAS`` of ``hydromodpy/results/storage/parquet_schemas.py``. The
row holds a quantity, the kind of value, which decides the display unit and the colours (see
the last case), and a label. The unit comes from the schema. Write the line inside the
dict. ``ColumnDescriptor`` is defined just above it, so there is nothing to import.

.. literalinclude:: /../../tests/unit/display/test_add_a_figure.py
   :start-after: # example: column
   :end-before: # end of example
   :dedent: 8

The gate, ``tests/unit/results/test_field_registry_kinds.py``, checks every row of the
registries. The quantity must exist, the label has at most 40 characters, and the unit
converts to the display unit. Without the row, a table panel ends with ``the panel:
'simulation.budget_pct' has no row in COLUMN_REGISTRY (results/field_registry.py). Known
columns of 'simulation': ... Add a row 'simulation.budget_pct' there``.

A cell field rebuilt at read time is not stored. A function computes it when a figure asks,
one row of values per time step. Here each cell gets its recharge minus the mean of the
cells. It takes four steps.

1. In ``hydromodpy/results/field_registry.py``, add its descriptor, the record of its
   name, label, quantity, stored unit and shape, inside ``REBUILT_FIELDS``. The stored unit
   is the unit of the arrays, the one of the quantity. ``_rebuilt`` and ``SHAPE_TIME_FACE``
   (one value per time and cell) are in that file.

.. literalinclude:: /../../tests/unit/display/test_add_a_figure.py
   :start-after: # example: descriptor
   :end-before: # end of example
   :dedent: 8

2. In ``hydromodpy/results/derive/stream_network/cell_fields.py``, add the rows function
   above ``REBUILT_FIELD_ROWS``. It takes the run and a list of time step numbers.
   ``run.field("recharge", time=step)`` gives an array of layers by cells.

.. literalinclude:: /../../tests/unit/display/test_add_a_figure.py
   :start-after: # example: rows function
   :end-before: # end of example
   :dedent: 4

3. In the same file, add the row inside ``REBUILT_FIELD_ROWS``, where ``RebuiltField`` is
   defined. The second argument says why a run cannot serve the field, or returns ``None``.

.. literalinclude:: /../../tests/unit/display/test_add_a_figure.py
   :start-after: # example: rows row
   :end-before: # end of example
   :dedent: 8

4. If the rows function reads budget terms, the per-cell flows of the solver, add a row
   inside ``FIELD_TERMS`` of ``hydromodpy/core/budget/terms.py``, so that a run keeps them.

.. literalinclude:: /../../tests/unit/display/test_add_a_figure.py
   :start-after: # example: terms row
   :end-before: # end of example
   :dedent: 8

Then ``run.figure("recharge_anomaly", time="last")`` draws it, and the gate checks the
descriptor. With the descriptor and no row of ``REBUILT_FIELD_ROWS``, the read ends with
``Rebuilt field 'recharge_anomaly' has no row in REBUILT_FIELD_ROWS
(hydromodpy/results/derive/stream_network/cell_fields.py). Add one.``

Add a quantity
--------------

A quantity is one row of ``QUANTITY_KINDS`` in ``hydromodpy/core/units/kinds.py``, where
``QuantityKind`` is defined. It says the stored unit, the display unit a figure shows, the
sign, the log scale, how layers are reduced and what a running sum gives. Stored in ``1``
and shown in ``%``, this row multiplies the values by 100 on a figure.

.. literalinclude:: /../../tests/unit/display/test_add_a_figure.py
   :start-after: # example: quantity
   :end-before: # end of example
   :dedent: 8

No test lists the quantities, so none needs an edit. The gate checks that the stored unit
converts to the display unit, and that every variable of the quantity has the stored unit
and a label of at most 40 characters. A variable that names a quantity with no row ends
with ``Quantity 'share' has no row in QUANTITY_KINDS (hydromodpy/core/units/kinds.py). Add
one.``

Draw what the frames cannot
---------------------------

A figure no frame draws is a plain matplotlib function ``draw(subject, ax, theme)``, given
as ``run.figure(draw=my_function)``. The subject is the run, a session (the record of one
calibration) or a set of runs. The theme is the frozen set of colours, widths and fonts of
``hydromodpy/display/theme.py``, and a colour of it is ``theme.roles["name"]``.
``read_series`` returns a pandas ``Series`` of the variable at a station (a gauge, a lake, a
reach, or ``zone:catchment`` for the sum over the catchment). Its values are in the stored
unit, and its index is the start of each period of the run.

.. literalinclude:: /../../tests/unit/display/test_add_a_figure.py
   :start-after: # example: draw
   :end-before: # end of example
   :dedent: 4

The imports are ``from hydromodpy.display import static`` and
``from hydromodpy.display.subject import read_series``. ``static`` is the matplotlib
engine of ``hydromodpy/display/static.py``. Its helpers (``line_style``, ``text_style``,
``style_axes``, ``note``, ``colorbar``, ``legend``, ``map_axes``) give the look of the
other figures. The keywords ``station`` and ``time`` are filled when the signature
declares them. A file never names the function, so a TOML file reaches it only through a
preset that carries it, a module of ``hydromodpy/display/special/``. A TOML ``draw`` ends
with ``draw takes a Python function and is never written in a file. To draw a figure from a
function in a TOML file, name the preset that carries it.``
