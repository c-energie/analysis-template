# analysis-template

Figure and table tooling for a LaTeX document. **One plotly figure object produces both
outputs**, so the PDF and anything you publish from the same source cannot drift:

```
                     ┌─> static PNG   ─> the document repo ─> Overleaf ─> the PDF
notebook ─> figure ──┤
                     └─> interactive HTML + manifest ─> wiki / site
```

The companion is [`writing-template`](https://github.com/c-energie/writing-template), which
this repository takes as a build input through `DOCUMENT_REPO`. Neither imports the other:
the document repo knows nothing about Python, and this package never reads your prose.

## Start here

1. **Use this template** on GitHub to create your repository.
2. `python init.py` — names the package, then deletes itself.
3. Point at your document and install:

```bash
export DOCUMENT_REPO=/path/to/my-document      # $env:DOCUMENT_REPO on Windows
uv sync --extra dev --extra notebooks          # or: pip install -e ".[dev,notebooks]"
```

4. Run `notebooks/example/example_figure.ipynb`. It uses synthetic data, so it works
   before you have wired up anything of your own, and it writes a real figure into the
   document repo.

## Usage

```python
from PACKAGE_NAME import notebook_savers, figure_size

CHAPTER, NOTEBOOK, TEX = "Example", "example_figure.ipynb", "example.tex"
save_fig, save_table = notebook_savers(chapter=CHAPTER, notebook=NOTEBOOK, tex=TEX)

fig.update_layout(**figure_size(6.0, 4.5))     # inches
save_fig(fig, "example_scatter.png", hover_fields=["case", "measured"])
```

`notebook_savers` binds the routing once so individual calls stay about the figure.
Whether a call writes anything is decided by `figures_config.toml`, not by the source.

## The config

```toml
default = true          # what an unlisted name does, and is recorded as
save_figures = true     # master switch; can veto, never turns an entry on
save_tables = true

[example_figure.figures]
example_scatter = true
```

Sections are notebook stems and fill themselves in as notebooks run. An unlisted name
takes `default` and is recorded with it — there is no "first run is special" case, so what
the file says is what happens even for a name it has never seen. Set an entry to `false`
to stop regenerating a figure you have settled on; that is the whole point, that turning
one artefact off never means editing a notebook.

`init-figures-config` creates the file, prompting for the three global flags.

## Checks

```bash
check-figure-parity --snapshot   # record current figure dimensions as the baseline
check-figure-parity              # ...and fail if any has since drifted
check-figure-parity --figures    # which saved figures the document actually renders
pytest tests -q
```

The last one catches the quiet failure: a figure can be regenerated perfectly and still be
invisible in the PDF because its `\begin{figure}` block was never written or is still
commented out.

## Conventions that fail silently

These are the ones worth knowing before you lose an afternoon.

- **Never rename a committed figure.** LaTeX resolves bare filenames via `\graphicspath`
  and a publishing agent indexes by name; a rename breaks both with no error.
- **Pin `width`/`height` on any figure already committed.** The template's default size is
  smaller than most; regenerate without pinning and the document reflows silently.
- **Give every converted figure an explicit `hovertemplate`.** The interactive export is
  the reason for the dual output. `save_fig` warns when no trace has one.
- **Pass `chapter=` explicitly** (`notebook_savers` does). Omitting it drops into an
  interactive picker, which hangs an unattended run.
- **`tex=` only matters where a chapter holds several `.tex` files.** Appending a figure
  block is gated on the document not already referencing the figure — commented blocks
  count — so re-running never duplicates one, and an ambiguous target raises rather than
  guessing.

## Architecture

`src/PACKAGE_NAME/`, six modules:

| Module | What it does |
|---|---|
| `theme.py` | The single plotly template, registered as the default **on import**. Serif stack matching LaTeX, CVD-validated palette (assign slots *in order*), diverging scale. `figure_size(w, h)` in inches. |
| `save_figure.py` | `save_document_figure()`: PNG into `$DOCUMENT_REPO/Chapters/<chapter>/Figures/`, plus HTML and a manifest entry. |
| `save_table.py` | `save_document_table()`: booktabs LaTeX into a per-chapter `tables.tex`, tagged so re-saving replaces in place. |
| `figure_config.py` | Reads `figures_config.toml` (stdlib `tomllib`, no dependency). Appends new entries textually, so your comments survive. |
| `savers.py` | `notebook_savers()` — the pair every notebook uses. |
| `parity.py` | The `check-figure-parity` console script. |

The manifest is keyed by LaTeX label (`"Fig: <label>"`) and records where each figure came
from. HTML is written with `include_plotlyjs="directory"` so exports work offline.

## Publishing the document

The `publish` extra installs [`thesis-agent`](https://github.com/c-energie/thesis-agent),
which turns the document into a queryable corpus, a Notion wiki or a Quarto site:

```bash
uv sync --extra publish
export DOCUMENT_REPO=/path/to/my-document
thesis-agent init      # scaffold the contract into the document repo
thesis-agent build     # LaTeX -> corpus
thesis-agent site      # Quarto site;  `sync` for Notion
```

It lives here rather than in the document repo because this is the Python repo of the
pair — the document repo goes to Overleaf and stays pure LaTeX. It is a **command**, not a
code dependency: nothing in `src/` imports it, which is what keeps this package
installable on its own.

Three things that surprise people:

- **Quarto is a system dependency.** An extra cannot install it — `winget install
  Posit.Quarto`, or the equivalent for your platform.
- **Notion needs a token**, which means a credential in the repo where your analysis runs.
  Use an environment variable; never commit it.
- **Publishing state lives in the *document* repo**, under `.thesis-agent/` — not here.
  So a publish driven from this repo writes state into the other one. That is
  counterintuitive, and losing `notion_manifest.json` duplicates an entire published wiki.

## Keep the tooling free of your data layer

`PACKAGE_NAME` deliberately depends on nothing private. Add your analysis stack as an
*extra* in `pyproject.toml`, import it in notebooks, and never from `src/` — that is what
keeps this repository reusable as a template and installable by someone who has your code
but not your data.
