"""The document's visual constants, in no particular plotting library.

Both backends style themselves from this one module: `theme.py` builds the plotly
template from it, `theme_mpl.py` builds matplotlib rcParams from it. A document whose
figures come from both backends still has to look like one document, and the only way
to guarantee that is to have a single place where the palette and the type live.

Nothing here imports plotly or matplotlib, so these values stay readable whichever
extra is installed — including neither.
"""

# Latin Modern matches the LaTeX default (lmodern). Both backends fall back down this
# stack when it is not installed; the last entry is a font that always exists.
SERIF_FAMILIES = (
    "Latin Modern Roman",
    "CMU Serif",
    "Georgia",
    "Times New Roman",
    "DejaVu Serif",
)

# plotly wants one CSS-style string, with a generic family to end on.
SERIF_STACK = ", ".join(SERIF_FAMILIES) + ", serif"

# Muted categorical palette, colour-vision-deficiency-validated on a white surface
# (adjacent-pair CVD deltaE >= 8). The ORDER is the safety mechanism — assign slots in
# order, never cycle or re-sort; fold a 9th series into "other" or facet instead.
CATEGORICAL = [
    "#2a78d6",  # blue
    "#eb6834",  # orange
    "#1baf7a",  # aqua-green
    "#eda100",  # yellow
    "#e87ba4",  # magenta
    "#008300",  # green
    "#4a3aa7",  # violet
    "#e34948",  # red
]

# Diverging scale for signed quantities (z-scores): blue <- neutral grey -> red, so the
# midpoint reads as "nothing". Stops are (position, colour), which is the form both
# plotly colorscales and matplotlib's LinearSegmentedColormap.from_list accept.
DIVERGING = [
    (0.0, "#1c5cab"),
    (0.25, "#86b6ef"),
    (0.5, "#f0efec"),
    (0.75, "#ec9a8a"),
    (1.0, "#c22f2e"),
]

DIVERGING_NAME = "document_diverging"

GRID_COLOR = "#e1e0d9"
AXIS_COLOR = "#4a4945"
INK = "#0b0b0b"

# Export convention: figure sizes are quoted in inches like matplotlib's figsize, and
# PNGs come out at PRINT_DPI — plotly by pre-scale layout pixels times STATIC_SCALE,
# matplotlib by savefig at PRINT_DPI. Same numbers in, same pixel dimensions out to
# within a pixel (plotly's pre-scale size is an integer, so a half-pixel rounds), which
# is three orders of magnitude inside check-figure-parity's default 5% tolerance. A
# figure can therefore change backend without the document reflowing.
PRINT_DPI = 150
STATIC_SCALE = 2

# A full-text-width single panel, in inches: the default size for both backends.
DEFAULT_SIZE_IN = (7.5, 4.8)
