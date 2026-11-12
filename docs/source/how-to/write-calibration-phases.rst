Write calibration phases
========================

This page shows how to split a calibration into phases and how to use a published protocol that writes them for you.

A calibration runs as one or more phases. A phase says which parameters it moves, in which flow
regime, and against which objective blocks with which share for each. The search method follows
from what is scored. A signed criterion (``distance_gap``) on one parameter in log space is a
zero to find, searched by bisection (the stopping rule, the two roots and the budget arithmetic
are in :doc:`/theory/downslope-distance`, section "How a search reaches the zero"). Anything
else is a cost to minimize, by Nelder-Mead. That choice applies to a phase and, the same way, to
a calibration with no phases at all (``optim.optimizer.choose_method``, read through
``CalibrationConfig.method_for``). A ``method`` is written only to choose otherwise
(``"cma_es"``, ``"optuna"``, ``"grid"`` and so on). A protocol is a named recipe tied to a
publication. It writes the phases of a published method, cites it, and lets the user set its
options but not its sequence. Everything a protocol does, phases written by hand can say too,
and ``hmp calibrate FILE --expand`` prints the phases a protocol writes, as TOML to start from.

One rule links the phases, in declaration order. A phase moves the parameters it lists. Every
other parameter holds the last value an earlier settled phase found for it, or the value of the
model file when no phase has calibrated it yet. A phase that lists a parameter an earlier phase
calibrated moves it again, starting from that value when its search method accepts a start
point.

Blocks are declared once under ``[[calibration.objective_blocks]]``. A phase lists the ones it
scores, or gives each a share. Shares are normalized to sum to one, so ``{ hydrograph = 70,
network = 30 }`` reads as 70 % and 30 % of the cost. The share of a cost counts the same as an
influence only when the costs are comparable. An efficiency (``nse_log``) is a pure number and
a network distance is in meters, so ``normalize_cost = true`` is written on the network block.
Each distance is then divided by the ``validity_length`` of the output (Eq. 4, ``"auto"`` is
2 h_obs), and a gap of one validity length costs 1, as much as an NSE of 0. ``normalize_cost``
stays refused on the efficiency, which is already a pure number.

A spin-up is left out by dates. ``window.start`` on the phase, or on ``[calibration]``, is the
first date scored, for every block alike, and a series keeps its stamps inside the window. A
network output reads one state, dated at the stamp that closes its period. ``time = "last"`` is
the default, and ``"first"`` or a date such as ``"2002-10-15"`` reads the period that holds it.
The window has to hold that stamp, and ``hmp check`` says so before any solve when it does not.
The former ``warmup`` and ``warmup_periods`` counted samples, so their span followed the time
step. A file that writes them is refused with the new form, the start date of the window.

Dates can be kept apart from the search with :toml:`calibration.validation_window` on
``[calibration]``, once for the session. ``[metrics] window`` minus those dates is then the
default ``window``. Each trial is scored on them from the series it has already simulated, as
the ``validation.cost`` component, and the promoted run stores it as
``checks.calibrated_by.validation_cost`` with its period in ``windows``. The cost never reads
them. The score uses the blocks that compare a dated record, so a network block and a steady
phase are left out of it. A window that overlaps a calibration window, leaves no data or falls
outside ``[metrics] window`` is refused.

The declarations that the examples below share, since the published method writes its own
objective blocks, are these.

.. code-block:: toml

   [calibration.parameters.K]
   bounds = [1e-7, 1e-3]

   [calibration.parameters.Sy]
   bounds = [5e-3, 0.35]

   [calibration.outputs.streams]
   support = "network"

   [calibration.outputs.streams.map]
   complete = "nancon_stream_network.gpkg"

   [calibration.outputs.streams.model]
   neighbours = "D8"

   [calibration.outputs.gauge]
   support = "point"
   variable = "discharge"
   observes = "NANCON"

   [[calibration.objective_blocks]]
   name = "network"
   metric = "distance_gap"
   uses_outputs = ["streams"]

   [[calibration.objective_blocks]]
   name = "network_share"         # the same gap, counted in validity lengths
   metric = "distance_gap"
   uses_outputs = ["streams"]
   normalize_cost = true

   [[calibration.objective_blocks]]
   name = "hydrograph"
   metric = "nse_log"
   uses_outputs = ["gauge"]

K first, then Sy with K fixed. K alone in steady state against the mapped network, then Sy alone
in transient against the gauge and the network, with 2000 left out as spin-up.

.. code-block:: toml

   # not checked: fragment, continues the declarations of the first block
   [[calibration.phases]]
   name = "k_steady"
   parameters = ["K"]
   regime = "steady"              # one period over [simulation.time], or steady_window
   objective_blocks = ["network"]
   max_trials = 18

   [[calibration.phases]]
   name = "sy_transient"
   parameters = ["Sy"]            # K holds what k_steady found
   regime = "transient"
   objective_blocks = { hydrograph = 0.8, network_share = 0.2 }   # two pure numbers
   max_trials = 30

   [calibration.phases.window]
   start = "2001-01-01"           # the network state read, December 2002, lies inside

Both at once. One phase, both parameters, one regime. Two parameters and a cost to minimize give
Nelder-Mead, and ``method = "cma_es"`` is written for a global search.

.. code-block:: toml

   # not checked: fragment, continues the declarations of the first block
   [[calibration.phases]]
   name = "k_sy_transient"
   parameters = ["K", "Sy"]
   regime = "transient"
   objective_blocks = ["hydrograph"]
   max_trials = 120

In stages, then both together. A third phase after the two stages above moves K and Sy again,
starting from what they found.

.. code-block:: toml

   # not checked: fragment, continues the declarations of the first block
   [[calibration.phases]]
   name = "k_sy_refine"
   parameters = ["K", "Sy"]       # starts at k_steady's K and sy_transient's Sy
   regime = "transient"
   objective_blocks = ["hydrograph"]
   max_trials = 60

Narrower bounds in a later phase. A phase may write ``bounds`` for the parameters it moves,
inside the bounds that ``[calibration.parameters.<name>]`` gives. The first phase searches wide
and the refinement searches around what it found. A phase never widens a search, and bounds
outside the section's are refused when the file loads. ``hmp calibrate --list-phases`` prints
them.

.. code-block:: toml

   # not checked: fragment, continues the declarations of the first block
   [[calibration.phases]]
   name = "k_refine"
   parameters = ["K"]
   bounds = { K = [2e-6, 2e-5] }  # inside the bounds of [calibration.parameters.K]

The published method. The same first two stages, with the options that the paper leaves open
and its citation recorded in the session.

.. code-block:: toml

   # not checked: fragment, continues the declarations of the first block
   [calibration.protocol]
   name = "matching_hydrographic_network"
   steady_max_trials = 18
   transient_max_trials = 30

The transient stage scores itself through an objective block that reads a ``support = "point"``
output observing the gauging station. The output is added to ``[calibration.outputs]`` when
the station is known from the file alone, which means one source named by ``station_ids``, or
``[site] gauge``. ``--expand`` then shows that output beside the two stages. A file that loads
several stations, or one whose source only discovers its station once the data step runs, keeps
the older form of the protocol, with ``variable`` and ``objective`` written on the phase and no
output named.

From Python the keys are the same, as dictionaries. A call with phases writes the document it
ran into the ``sessions/`` of the project as ``<case>.toml``, so a Python run can be replayed
from a file. The case takes the ``[simulation] name`` of the project, else the stem of its
file, as on the command line.

.. code-block:: python

   import hydromodpy as hmp

   project = hmp.Project("project.toml")
   report = project.calibrate(
       parameters={"K": {"bounds": [1e-7, 1e-3]}, "Sy": {"bounds": [5e-3, 0.35]}},
       outputs={
           "streams": {
               "support": "network",
               "map": {"complete": "nancon_stream_network.gpkg"},
               "model": {"neighbours": "D8"},
           },
           "gauge": {"support": "point", "variable": "discharge", "observes": "NANCON"},
       },
       objective_blocks=[
           {"name": "network", "metric": "distance_gap", "uses_outputs": ["streams"]},
           {
               "name": "network_share",
               "metric": "distance_gap",
               "uses_outputs": ["streams"],
               "normalize_cost": True,
           },
           {"name": "hydrograph", "metric": "nse_log", "uses_outputs": ["gauge"]},
       ],
       phases=[
           {
               "name": "k_steady",
               "parameters": ["K"],
               "regime": "steady",
               "objective_blocks": ["network"],
               "max_trials": 18,
           },
           {
               "name": "sy_transient",
               "parameters": ["Sy"],
               "regime": "transient",
               "objective_blocks": {"hydrograph": 0.8, "network_share": 0.2},
               "max_trials": 30,
               "window": {"start": "2001-01-01"},
           },
       ],
   )

A phase takes the search of ``[calibration]`` key by key. ``method``, ``max_trials``,
``precision`` and ``method_options`` written in the phase win, then the ones of the section,
then the default, which is a method chosen from what the phase scores and ``max_trials =
"auto"``. A precision of the section reaches only a phase whose engine stops on one, and not a
phase that writes that stopping option itself. The options of the section reach a phase that
runs the method of the section, and ``method_options = {}`` in a phase states that it takes
none. ``hmp calibrate FILE --list-phases`` says where each key comes from.

Each phase also says how wide its answer is, through ``uncertainty`` with the same keys as
``[calibration.uncertainty]``, which stays the default for every phase. Left unwritten, the
width follows what the phase scores. A phase scored only by network distances takes one mesh
cell, in meters, since a stream cannot move by less, and any other phase takes 5 % of its best
cost. ``cost_margin`` writes it with its unit, ``"5%"`` of the best cost or ``"75 m"`` of
network distance. A bare number is refused, and a length is accepted only on a search scored
by network distances. ``hmp check`` refuses a share on a phase scored only by network
distances. The interval never moves the calibrated value. It says which values the search could
not tell apart from it.

``hmp calibrate FILE --list-phases`` shows, for each phase, the parameters it moves, the ones it
re-opens and from which phase (when it moves a parameter an earlier phase calibrated, and
whether its engine starts from that value), which method it runs and why, the width of its
interval, and for each block what is compared with what, which is the simulated quantity and the
observed source (a station of ``[data.<family>]``, or a network file). After a phase, the report
gives the share of the cost each block actually took, which differs from the declared share when
the blocks have different units. ``overrides`` stays for any other configuration value a phase
must change, as a dotted path into the project configuration.
