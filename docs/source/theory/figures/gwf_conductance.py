"""Two cells and the lengths of the conductance between them."""

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle


def span(ax, a, b, text, *, offset=(0, 0), color="C6"):
    """Draw a double arrow from a to b with a label at its middle."""
    ax.annotate("", a, b, arrowprops={"arrowstyle": "<->", "color": color, "lw": 1.1})
    middle = (0.5 * (a[0] + b[0]), 0.5 * (a[1] + b[1]))
    ax.annotate(text, middle, xytext=offset, textcoords="offset points", ha="center", va="center")


# Cell n is wider than cell m, so the two half distances differ.
X_N, X_FACE, X_M = -1.2, 0.0, 0.8
fig, (plan, section) = plt.subplots(1, 2, figsize=(6.4, 3.2))

plan.add_patch(Rectangle((X_N, 0), X_FACE - X_N, 1, fc="C5", alpha=0.35, ec="C6"))
plan.add_patch(Rectangle((X_FACE, 0), X_M - X_FACE, 1, fc="C0", alpha=0.25, ec="C6"))
plan.plot([X_FACE, X_FACE], [0, 1], color="C1", lw=2.5)
centre_n, centre_m = (0.5 * (X_N + X_FACE), 0.5), (0.5 * (X_FACE + X_M), 0.5)
plan.plot(*zip(centre_n, centre_m, strict=True), "o", color="C6", ms=4)
plan.text(centre_n[0], 0.75, "$n$", ha="center", fontsize=12)
plan.text(centre_m[0], 0.75, "$m$", ha="center", fontsize=12)
span(plan, centre_n, (X_FACE, 0.5), "$c_{nm}$", offset=(0, -10))
span(plan, (X_FACE, 0.5), centre_m, "$c_{mn}$", offset=(0, -10))
span(plan, (X_FACE - 0.1, 0.0), (X_FACE - 0.1, 1.0), "$w_{nm}$", offset=(-16, 26), color="C1")
plan.set_title("Plan: the shared face", fontsize=10)

# Section: the same two cells, with their water tables.
Z_BOT, Z_TOP, H_N, H_M = 0.0, 1.0, 0.8, 0.45
section.add_patch(Rectangle((X_N, Z_BOT), X_FACE - X_N, H_N - Z_BOT, fc="C5", alpha=0.35))
section.add_patch(Rectangle((X_FACE, Z_BOT), X_M - X_FACE, H_M - Z_BOT, fc="C0", alpha=0.25))
section.add_patch(Rectangle((X_N, Z_BOT), X_M - X_N, Z_TOP - Z_BOT, fill=False, ec="C6"))
section.plot([X_FACE, X_FACE], [Z_BOT, Z_TOP], color="C6", lw=0.8)
section.plot([X_N, X_FACE], [H_N, H_N], color="C0", lw=1.8)
section.plot([X_FACE, X_M], [H_M, H_M], color="C0", lw=1.8)
span(section, (-0.9, Z_BOT), (-0.9, H_N), "$B_n$", offset=(12, 0))
span(section, (0.55, Z_BOT), (0.55, H_M), "$B_m$", offset=(12, 0))
section.annotate(
    "",
    (0.35, 0.25),
    (-0.45, 0.25),
    arrowprops={"arrowstyle": "-|>", "color": "C1", "lw": 1.8},
)
section.text(-0.6, H_N + 0.06, "$h_n$", fontsize=11)
section.text(0.25, H_M + 0.06, "$h_m$", fontsize=11)
section.text(-0.6, -0.17, "$n$ is upstream:\nits head is higher", ha="center", va="top", fontsize=8)
section.set_title("Section: the flow goes from $n$ to $m$", fontsize=10)

for ax in (plan, section):
    ax.set_xlim(X_N - 0.1, X_M + 0.3)
    ax.set_ylim(-0.45, 1.15)
    ax.set_aspect("equal")
    ax.axis("off")
fig.tight_layout()
