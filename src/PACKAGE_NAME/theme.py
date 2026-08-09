"""Shared plotly template for document figures.

Every document figure — the static PNG that goes into the LaTeX build and the
interactive HTML that goes to the wiki — is styled by this one template, so there is
no per-figure styling drift. Importing this module registers the template with
plotly.io and makes it the default; notebooks only need

    from PACKAGE_NAME import figure_size

and, where the automatic sizing convention does not fit, an explicit
``fig.update_layout(**figure_size(11, 4.5))``.
"""

import plotly.graph_objects as go
import plotly.io as pio

TEMPLATE_NAME = "document"

# Latin Modern matches the LaTeX default (lmodern); kaleido and
# browsers fall back down this stack when Latin Modern is not installed.
SERIF_STACK = 'Latin Modern Roman, CMU Serif, Georgia, Times New Roman, serif'

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
# midpoint reads as "nothing". Replaces matplotlib's coolwarm in converted figures.
DIVERGING = [
    (0.0, "#1c5cab"),
    (0.25, "#86b6ef"),
    (0.5, "#f0efec"),
    (0.75, "#ec9a8a"),
    (1.0, "#c22f2e"),
]

GRID_COLOR = "#e1e0d9"
AXIS_COLOR = "#4a4945"
INK = "#0b0b0b"

# Export convention: figure_size() is quoted in inches like matplotlib's figsize, and
# PNGs come out at PRINT_DPI once write_image applies STATIC_SCALE — so converted
# figures land at the same pixel dimensions the matplotlib originals were saved at
# (figsize inches x dpi=150).
PRINT_DPI = 150
STATIC_SCALE = 2


def figure_size(width_in, height_in, dpi=PRINT_DPI, scale=STATIC_SCALE):
    """Layout width/height (px) so the exported PNG measures width_in*dpi pixels.

    Plotly layout sizes are pre-scale pixels; write_image multiplies them by scale.
    Returns a dict suitable for fig.update_layout(**figure_size(11, 4.5)).
    """
    return {
        "width": round(width_in * dpi / scale),
        "height": round(height_in * dpi / scale),
    }


def _build_template():
    axis_common = dict(
        showgrid=True,
        gridcolor=GRID_COLOR,
        gridwidth=0.5,
        zeroline=False,
        showline=True,
        linecolor=AXIS_COLOR,
        linewidth=1,
        ticks="outside",
        tickcolor=AXIS_COLOR,
        ticklen=4,
        title_font_size=12,
        tickfont_size=10,
        automargin=True,
    )
    return go.layout.Template(
        layout=go.Layout(
            colorway=CATEGORICAL,
            colorscale=dict(diverging=DIVERGING),
            font=dict(family=SERIF_STACK, size=11, color=INK),
            title=dict(font_size=13, x=0.5, xanchor="center"),
            paper_bgcolor="white",
            plot_bgcolor="white",
            xaxis=axis_common,
            yaxis=axis_common,
            # Legend inside the axes by default; figures where data occupies that
            # corner override position per-figure, not per-style.
            legend=dict(
                x=0.02,
                y=0.98,
                xanchor="left",
                yanchor="top",
                bgcolor="rgba(255,255,255,0.7)",
                bordercolor=GRID_COLOR,
                borderwidth=0.5,
                font_size=10,
            ),
            margin=dict(l=60, r=15, t=40, b=50),
            # Default size = a full-text-width single panel (7.5in x 4.8in).
            **figure_size(7.5, 4.8),
        )
    )


def activate_template(as_default=True):
    """Register the document template with plotly.io; optionally make it the default."""
    pio.templates[TEMPLATE_NAME] = _build_template()
    if as_default:
        pio.templates.default = TEMPLATE_NAME
    return pio.templates[TEMPLATE_NAME]


activate_template()
