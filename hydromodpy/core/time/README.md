# Core Time

`hydromodpy/core/time/` contains simulation time-window resolution and
coverage checks shared by higher layers.

Neutral temporal grid generation lives in `hydromodpy/discretization/time/`.

`selection.py` is the one date-to-period resolver figures and exports share.
Period `i` is `[edges[i], edges[i + 1])`, the convention of
`period_aggregation.py`. `resolve_instant` reads an ISO date, `"first"`,
`"last"` or an index; the last edge is the last period; a date outside the
record raises `TimeSelectionError`, which names the record span. `edges=None`
is a steady run without a window: it has no dates. `period_label` names a
period (`"2002-10"`, `"2002-10-15"`, or a span), and `grid_edges` reads the
edges of a resolved time grid at config check.
