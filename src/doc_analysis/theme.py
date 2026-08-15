"""Shared plotly template for document figures.

Every plotly document figure — the static PNG that goes into the LaTeX build and the
interactive HTML that goes to the wiki — is styled by this one template, so there is
no per-figure styling drift. Importing this module registers the template with
plotly.io and makes it the default; notebooks only need

    from doc_analysis import figure_size

and, where the automatic sizing convention does not fit, an explicit
``fig.update_layout(**figure_size(11, 4.5))``.

The colours, type and export convention come from `style.py`, which knows about no
plotting library at all — `theme_mpl.py` builds the matplotlib equivalent from the same
constants. This module needs the `plotly` extra; importing it without one installed is
the caller's error, and `doc_analysis/__init__` says so before it gets that far.
"""

import plotly.graph_objects as go
import plotly.io as pio

from doc_analysis.style import (
    AXIS_COLOR,
    CATEGORICAL,
    DEFAULT_SIZE_IN,
    DIVERGING,
    GRID_COLOR,
    INK,
    PRINT_DPI,
    SERIF_STACK,
    STATIC_SCALE,
)

TEMPLATE_NAME = "document"

__all__ = [
    "TEMPLATE_NAME",
    "activate_template",
    "figure_size",
    # Re-exported so `from doc_analysis.theme import CATEGORICAL` keeps working; the
    # definitions live in style.py.
    "AXIS_COLOR",
    "CATEGORICAL",
    "DIVERGING",
    "GRID_COLOR",
    "INK",
    "PRINT_DPI",
    "SERIF_STACK",
    "STATIC_SCALE",
]


def figure_size(width_in, height_in, dpi=PRINT_DPI, scale=STATIC_SCALE):
    """Layout width/height (px) so the exported PNG measures width_in*dpi pixels.

    Plotly layout sizes are pre-scale pixels; write_image multiplies them by scale.
    Returns a dict suitable for fig.update_layout(**figure_size(11, 4.5)). The
    matplotlib counterpart is theme_mpl.figure_size_in, which takes the same inches and
    lands within a rounding pixel of the same export (see style.py).
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
            # Default size = a full-text-width single panel.
            **figure_size(*DEFAULT_SIZE_IN),
        )
    )


def activate_template(as_default=True):
    """Register the document template with plotly.io; optionally make it the default."""
    pio.templates[TEMPLATE_NAME] = _build_template()
    if as_default:
        pio.templates.default = TEMPLATE_NAME
    return pio.templates[TEMPLATE_NAME]


activate_template()
