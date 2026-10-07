import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    return (mo,)


@app.cell
def _(mo):
    mo.md(r"""
    # <<TITLE>>

    What this notebook produces, and for which part of the document.

    ## Setup

    `notebook_savers` binds the routing -- which section, which notebook, which `.tex` file --
    once, so each `save_fig` / `save_table` call is only about its artefact. Whether a call
    writes anything is `figures_config.toml`'s decision, keyed by this notebook's name.
    """)
    return


@app.cell
def _():
    # notebook_setup() loads $DOC_REPO from the .env, styles the installed backend and moves
    # to the analysis repo root, wherever `marimo edit` / `marimo export` was started.
    from doc_analysis import notebook_setup, notebook_savers

    ROOT = notebook_setup()

    # Where this notebook's artefacts belong in the document repo. SECTION is a path under
    # $DOC_REPO/Sections; NOTEBOOK is this file's name and keys its figures_config.toml table;
    # TEX names the .tex file that receives references -- None when the section has only one.
    SECTION = "<<SECTION>>"
    NOTEBOOK = "<<NOTEBOOK>>"
    TEX = "<<TEX>>"

    save_fig, save_table = notebook_savers(section=SECTION, notebook=NOTEBOOK, tex=TEX)
    return ROOT, save_fig, save_table


@app.cell
def _(mo):
    mo.md(r"""
    ## Data
    """)
    return


@app.cell
def _():
    import numpy as np
    import pandas as pd

    # Load or compute what this notebook's figures and tables need.
    return np, pd


@app.cell
def _(mo):
    mo.md(r"""
    ## Figure

    One cell per figure. Name it before running: a `<<...>>` name raises rather than saving.
    """)
    return


# skeleton-backend: plotly
@app.cell
def _(save_fig):
    import plotly.graph_objects as go
    from doc_analysis import figure_size
    from doc_analysis import CATEGORICAL

    fig = go.Figure()
    # One trace per group, palette slots in order, an explicit hovertemplate per trace:
    # fig.add_trace(go.Scatter(x=..., y=..., mode="markers", name=..., marker=dict(color=CATEGORICAL[0]),
    #                          customdata=..., hovertemplate="%{customdata[0]}<br>...<extra></extra>"))
    fig.update_layout(xaxis_title="", yaxis_title="",
                      **figure_size(6.0, 4.5))  # inches; pinned so the committed PNG keeps its size

    save_fig(fig, "<<FIGURE>>.png",
             hover_fields=[],  # the columns the hovertemplate shows
             caption="",
             label="<<FIGURE>>")  # the label mirrors the filename stem
    # The figure as the cell's last expression is what marimo displays; fig.show() would
    # go through plotly's renderer instead, which notebook_setup() sets for Jupyter.
    fig
    return


# skeleton-backend: matplotlib
@app.cell
def _(save_fig):
    import matplotlib.pyplot as plt
    from doc_analysis import figure_size_in
    from doc_analysis import CATEGORICAL

    fig, ax = plt.subplots(**figure_size_in(6.0, 4.5))  # inches; pinned so the committed PNG keeps its size
    # ax.plot(..., color=CATEGORICAL[0])  # palette slots in order
    ax.set(xlabel="", ylabel="")

    save_fig(fig, "<<FIGURE>>.png",
             caption="",
             label="<<FIGURE>>")  # the label mirrors the filename stem
    # The figure as the cell's last expression is what marimo displays; plt.show() is not needed.
    fig
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Table

    Pulled into the prose with `\ExecuteMetaData[Sections/<section>/tables.tex]{<name>}`.
    Delete this cell and the next if the notebook produces no table.
    """)
    return


@app.cell
def _(pd, save_table):
    summary = pd.DataFrame()  # the table as it should read in the document

    save_table(summary, "<<TABLE>>", decimals=2, caption="")
    summary
    return


if __name__ == "__main__":
    app.run()
