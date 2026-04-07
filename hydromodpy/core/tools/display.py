"""Plot parameter helpers and ASCII banner."""

from __future__ import annotations

import sys

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties


def plot_params(small, interm, medium, large):
    """Apply a consistent matplotlib style and return a FontProperties object."""
    mpl.style.use("classic")
    mpl.rcParams["figure.facecolor"] = "white"
    mpl.rcParams["grid.color"] = "darkgrey"
    mpl.rcParams["grid.linestyle"] = "-"
    mpl.rcParams["grid.alpha"] = 0.8
    mpl.rcParams["axes.axisbelow"] = True
    mpl.rcParams["axes.linewidth"] = 1.5
    mpl.rcParams["figure.dpi"] = 300
    mpl.rcParams["savefig.dpi"] = 300
    mpl.rcParams["patch.force_edgecolor"] = True
    mpl.rcParams["image.interpolation"] = "nearest"
    mpl.rcParams["image.resample"] = True
    mpl.rcParams["axes.autolimit_mode"] = "data"
    mpl.rcParams["axes.xmargin"] = 0.05
    mpl.rcParams["axes.ymargin"] = 0.05
    mpl.rcParams["xtick.direction"] = "in"
    mpl.rcParams["ytick.direction"] = "in"
    mpl.rcParams["xtick.major.size"] = 5
    mpl.rcParams["xtick.minor.size"] = 3
    mpl.rcParams["xtick.major.width"] = 1.5
    mpl.rcParams["xtick.minor.width"] = 1
    mpl.rcParams["ytick.major.size"] = 5
    mpl.rcParams["ytick.minor.size"] = 1.5
    mpl.rcParams["ytick.major.width"] = 1.5
    mpl.rcParams["ytick.minor.width"] = 1
    mpl.rcParams["xtick.top"] = True
    mpl.rcParams["ytick.right"] = True
    mpl.rcParams["legend.numpoints"] = 1
    mpl.rcParams["legend.scatterpoints"] = 1
    mpl.rcParams["legend.edgecolor"] = "grey"
    mpl.rcParams["date.autoformatter.year"] = "%Y"
    mpl.rcParams["date.autoformatter.month"] = "%Y-%m"
    mpl.rcParams["date.autoformatter.day"] = "%Y-%m-%d"
    mpl.rcParams["date.autoformatter.hour"] = "%H:%M"
    mpl.rcParams["date.autoformatter.minute"] = "%H:%M:%S"
    mpl.rcParams["date.autoformatter.second"] = "%H:%M:%S"
    mpl.rcParams.update({"mathtext.default": "regular"})

    plt.rc("font", size=small)
    plt.rc("figure", titlesize=large)
    plt.rc("legend", fontsize=small)
    plt.rc("axes", titlesize=medium, labelpad=10)
    plt.rc("axes", labelsize=medium, labelpad=12)
    plt.rc("xtick", labelsize=interm)
    plt.rc("ytick", labelsize=interm)
    plt.rc("font", family="sans serif")

    fontprop = FontProperties()
    fontprop.set_family("sans serif")
    return fontprop


_banner_printed = False


def print_hydromodpy():
    """Print the HydroModPy ASCII banner once."""
    global _banner_printed
    if _banner_printed:
        return
    banner_lines = [
        r"      __  __          __           __  ____          ________     ",
        r"     / / / /         / /          /  \/   /         / / __  /     ",
        r"    / /_/ /_  ______/ /________  /       /___  ____/ / /_/ /_  __ ",
        r"   / __  / / / / __  / ___/ __ \/ /\,-/ / __ \/ __  / ____/ / / / ",
        r"  / / / / /_/ / /_/ / /  / /_/ / /   / / /_/ / /_/ / /   / /_/ /  ",
        r" /_/ /_/\__, /_____/_/   \____/_/   /_/\____/_____/_/____\__, /   ",
        r"       /____/ Hydrological Modelling in Python /_____________/    ",
        r"                                                                  ",
    ]
    print("\n".join(banner_lines), file=sys.stderr)
    _banner_printed = True
