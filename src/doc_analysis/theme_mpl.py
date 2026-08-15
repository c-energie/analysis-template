"""Shared matplotlib style for document figures — the fallback backend.

Plotly is the preferred path (one figure object produces the committed PNG *and* the
interactive export). Matplotlib is a first-class alternative for anyone who does not
want the second output, and this module is what stops that choice showing up in the
document: it applies the same palette, the same type and the same export convention as
`theme.py`, both built from `style.py`.

Importing this module applies the style to the global rcParams, mirroring what
importing `theme` does for plotly, so a notebook that never mentions styling still
produces figures that match. Sizes are quoted in inches, as plotly's are:

    fig, ax = plt.subplots(**figure_size_in(6.0, 4.5))

`savefig.dpi` is pinned to PRINT_DPI, so those inches land on the same pixel
dimensions a plotly figure of the same size would, give or take a rounding pixel — which
is what lets `check-figure-parity` hold one baseline across both backends.

Deliberately *not* set: `savefig.bbox = "tight"`. It trims to the ink and makes the
saved pixel dimensions depend on the labels, which is exactly the silent resizing the
parity check exists to catch. `figure.constrained_layout` gives the same "nothing gets
clipped" result while keeping figsize authoritative.
"""

import matplotlib
from matplotlib.colors import LinearSegmentedColormap

from doc_analysis.style import (
    AXIS_COLOR,
    CATEGORICAL,
    DEFAULT_SIZE_IN,
    DIVERGING,
    DIVERGING_NAME,
    GRID_COLOR,
    INK,
    PRINT_DPI,
    SERIF_FAMILIES,
)

__all__ = ["STYLE", "DIVERGING_NAME", "activate_style", "diverging_cmap",
           "figure_size_in"]


def figure_size_in(width_in, height_in):
    """Figure size in inches, as ``{"figsize": (w, h)}``.

    The counterpart of theme.figure_size: the same two numbers give the same exported
    pixel dimensions on either backend, to within a rounding pixel. Spread it into the
    figure constructor — ``plt.subplots(**figure_size_in(6.0, 4.5))``.
    """
    return {"figsize": (width_in, height_in)}


def diverging_cmap():
    """The document's diverging colormap, registered under DIVERGING_NAME.

    Same stops as the plotly diverging colorscale, so a signed quantity reads
    identically whichever backend drew it. Registration is idempotent: re-importing
    this module in a live kernel must not raise.
    """
    if DIVERGING_NAME in matplotlib.colormaps:
        return matplotlib.colormaps[DIVERGING_NAME]
    cmap = LinearSegmentedColormap.from_list(DIVERGING_NAME, DIVERGING)
    matplotlib.colormaps.register(cmap, name=DIVERGING_NAME)
    return cmap


STYLE = {
    "figure.figsize": DEFAULT_SIZE_IN,
    "figure.facecolor": "white",
    "figure.constrained_layout.use": True,
    "savefig.dpi": PRINT_DPI,
    "savefig.facecolor": "white",

    "font.family": "serif",
    "font.serif": list(SERIF_FAMILIES),
    "font.size": 11,
    "text.color": INK,

    "axes.facecolor": "white",
    "axes.edgecolor": AXIS_COLOR,
    "axes.linewidth": 1,
    "axes.labelcolor": INK,
    "axes.labelsize": 12,
    "axes.titlesize": 13,
    "axes.titlelocation": "center",
    "axes.prop_cycle": matplotlib.cycler(color=CATEGORICAL),
    # The template draws only the left and bottom axis lines; matching here keeps a
    # converted figure from gaining a box it never had.
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "axes.axisbelow": True,

    "grid.color": GRID_COLOR,
    "grid.linewidth": 0.5,

    "xtick.color": AXIS_COLOR,
    "ytick.color": AXIS_COLOR,
    "xtick.labelcolor": INK,
    "ytick.labelcolor": INK,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "xtick.direction": "out",
    "ytick.direction": "out",
    "xtick.major.size": 4,
    "ytick.major.size": 4,
    "xtick.major.width": 1,
    "ytick.major.width": 1,

    "legend.fontsize": 10,
    "legend.loc": "upper left",
    "legend.facecolor": "white",
    "legend.edgecolor": GRID_COLOR,
    "legend.framealpha": 0.7,
    "legend.fancybox": False,

    "image.cmap": DIVERGING_NAME,
}


def activate_style(as_default=True):
    """Register the diverging colormap; optionally apply STYLE to the global rcParams.

    as_default=False registers the colormap and returns the mapping without touching
    rcParams — for a notebook that would rather scope it with
    ``plt.rc_context(activate_style(as_default=False))``.
    """
    diverging_cmap()
    if as_default:
        matplotlib.rcParams.update(STYLE)
    return STYLE


activate_style()
