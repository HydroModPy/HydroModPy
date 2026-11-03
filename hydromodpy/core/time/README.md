# Core Time

`hydromodpy/core/time/` contains simulation time-window resolution and
coverage checks shared by higher layers.

Neutral temporal grid generation lives in `hydromodpy/discretization/time/`.

`selection.py` is the one date-to-period resolver figures and exports share.
A date reads the period `(edges[i], edges[i + 1]]` that holds it, the first edge
in the first period. `resolve_instant` reads an ISO date, `"first"`,
`"last"` or an index; a date outside the
record raises `TimeSelectionError`, which names the record span. `edges=None`
is a steady run without a window: it has no dates. `period_label` names a
period (`"2002-10"`, `"2002-10-15"`, or a span), and `grid_edges` reads the
edges of a resolved time grid at config check. `in_series_window` is the one
reading of a window over a series: it keeps the periods `resolve_period` keeps, a
simulated value by its stamp and a measurement by its date.
