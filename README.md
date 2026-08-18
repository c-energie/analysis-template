# analysis-template

Figure and table tooling for a LaTeX document. **One plotly figure object produces both
outputs**, so the PDF and anything you publish from the same source cannot drift:

```
                     ┌─> static PNG   ─> the document repo ─> Overleaf ─> the PDF
notebook ─> figure ──┤
                     └─> interactive HTML + manifest ─> wiki / site
```

Plotly is the preferred backend and the reason for the shape above. **Matplotlib is
supported as a static-only fallback** — same PNG, same LaTeX append, same manifest, no
interactive export. Pick one at install time; nothing else changes (see
[Choosing a backend](#choosing-a-backend)).

The companion is [`writing-template`](https://github.com/c-energie/writing-template), which
this repository takes as a build input through `DOC_REPO` (see `.env`). Neither imports the other:
the document repo knows nothing about Python, and this package never reads your prose.

## Start here

Setting all three repositories up for the first time? The end-to-end order lives in the
document repo: [writing-template/SETUP.md](https://github.com/c-energie/writing-template/blob/main/SETUP.md).

1. **Use this template** on GitHub to create your repository.
2. `python init.py` — names the project, asks which plotting backend you want, writes
   your `.env`, then deletes itself.
3. Install, with the backend you chose:

```bash
uv sync --extra dev --extra notebooks --extra plotly       # preferred
uv sync --extra dev --extra notebooks --extra matplotlib   # static-only fallback
```

4. Run `notebooks/example/example_figure.ipynb`. It uses synthetic data, so it works
   before you have wired up anything of your own, and it writes a real figure into the
   document repo. (It is a plotly notebook; on matplotlib, start from the usage block
   below instead.)

## Choosing a backend

Neither backend is a hard dependency — you install exactly the one you use. There is no
setting to keep in step with the choice: `save_fig` reads the backend off the figure
object you hand it, so passing a plotly figure gets you the plotly behaviour and passing
a matplotlib figure gets you the other, in the same notebook if you like.

| | `--extra plotly` | `--extra matplotlib` |
|---|---|---|
| PNG into the document repo | yes | yes |
| Interactive HTML for the wiki/site | yes | — |
| Commented `\begin{figure}` append | yes | yes |
| `figures_config.toml` gate | yes | yes |
| Manifest entry | yes | yes, with `interactive: null` |
| Both `check-figure-parity` modes | yes | yes |
| Shared palette, type and sizing | plotly template | matplotlib rcParams |
| Install weight | kaleido downloads a headless Chrome to render PNGs | small |

**Prefer plotly.** The interactive export is the whole reason a published figure can be
better than the one in the PDF, and it costs nothing extra at the call site. Choose
matplotlib if you are not publishing beyond the PDF, if you have existing figure code
you would rather not port, or if the Chrome download is unwelcome in your environment.

Whichever you install styles itself **on import of `doc_analysis`**, from the same
constants in `style.py` — so a document with figures from both backends still looks like
one document. Reaching for a name that needs the other extra raises an `ImportError`
naming it, rather than failing somewhere further along.

### Configuration lives in `.env`

`init.py` writes it; `.env.example` documents every variable. It is gitignored, because
these are per-machine paths rather than project settings:

```bash
DOC_REPO=/path/to/my-document      # must contain Sections/
```

Loaded on import of `doc_analysis`, so notebooks, tests and the console scripts all see
it with no shell setup. **A variable already set in your shell wins**, which keeps CI and
one-off overrides working:

```bash
DOC_REPO=/tmp/scratch pytest tests -q
```

Nothing needs to go in your shell profile — deliberately. A user-level `DOC_REPO` is
wrong the moment you have a second checkout, and it fails silently: figures land in the
other document.

### Naming

`init.py` sets the **distribution** name (`pyproject.toml`) and leaves the **import**
package as `doc_analysis`. That split is on purpose — renaming the package would rewrite
every import in `src/`, `tests/` and your notebooks to no benefit, and the two names are
independent in Python anyway (`pillow` imports as `PIL`, `scikit-learn` as `sklearn`).
So `import doc_analysis` is the same line in every project built from this template.

## Usage

```python
from doc_analysis import notebook_savers, figure_size

SECTION, NOTEBOOK, TEX = "Example", "example_figure.ipynb", "example.tex"
save_fig, save_table = notebook_savers(section=SECTION, notebook=NOTEBOOK, tex=TEX)

fig.update_layout(**figure_size(6.0, 4.5))     # inches
save_fig(fig, "example_scatter.png", hover_fields=["case", "measured"])
```

The same thing on matplotlib — the call site is identical, minus the `hover_fields`
there is nothing to hover over:

```python
import matplotlib.pyplot as plt
from doc_analysis import notebook_savers, figure_size_in

SECTION, NOTEBOOK, TEX = "Example", "example_figure.ipynb", "example.tex"
save_fig, save_table = notebook_savers(section=SECTION, notebook=NOTEBOOK, tex=TEX)

fig, ax = plt.subplots(**figure_size_in(6.0, 4.5))     # inches, same numbers
ax.scatter(x, y)
save_fig(fig, "example_scatter.png")
```

`figure_size(w, h)` and `figure_size_in(w, h)` take the same inches and produce the same
exported pixel dimensions — within a pixel, since plotly's pre-scale layout size is an
integer. A figure can change backend without the document reflowing, and one
`check-figure-parity` baseline covers both.

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

The tables are keyed by **notebook stem** — not by document section — and fill themselves
in as notebooks run. An unlisted name takes `default` and is recorded with it: there is no
"first run is special" case, so what the file says is what happens even for a name it has
never seen. Set an entry to `false` to stop regenerating a figure you have settled on;
that is the whole point, that turning one artefact off never means editing a notebook.

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
- **Give every plotly figure an explicit `hovertemplate`.** The interactive export is the
  reason for the dual output, and default hover text gives a reader nothing the PNG did
  not. `save_fig` warns when no trace has one. (Not applicable on matplotlib, which does
  not warn about anything — a static figure is a complete figure.)
- **Pass `section=` explicitly** (`notebook_savers` does). Omitting it drops into an
  interactive picker, which hangs an unattended run.
- **`tex=` only matters where a section holds several `.tex` files.** Appending a figure
  block is gated on the document not already referencing the figure — commented blocks
  count — so re-running never duplicates one, and an ambiguous target raises rather than
  guessing.

## Architecture

`src/doc_analysis/`, nine modules:

| Module | What it does |
|---|---|
| `env.py` | Reads the checkout's `.env` into the environment on import, without overriding what the shell already set. Stdlib; `KEY=value` needs no dependency. |
| `style.py` | The document's visual constants in no plotting library: serif stack matching LaTeX, CVD-validated palette (assign slots *in order*), diverging stops, print DPI. Both themes are built from it, so the backends cannot drift apart. Imports nothing. |
| `theme.py` | The single plotly template, registered as the default **on import**. `figure_size(w, h)` in inches. Needs the `plotly` extra. |
| `theme_mpl.py` | The matplotlib equivalent: the same values as rcParams, applied **on import**, plus the diverging colormap and `figure_size_in(w, h)`. Needs the `matplotlib` extra. |
| `save_figure.py` | `save_document_figure()`: PNG into `$DOC_REPO/Sections/<section>/Figures/`, a manifest entry, and — for a plotly figure — the interactive HTML. |
| `save_table.py` | `save_document_table()`: booktabs LaTeX into a per-section `tables.tex`, tagged so re-saving replaces in place. |
| `figure_config.py` | Reads `figures_config.toml` (stdlib `tomllib`, no dependency). Appends new entries textually, so your comments survive. |
| `savers.py` | `notebook_savers()` — the pair every notebook uses. |
| `parity.py` | The `check-figure-parity` console script. |

The manifest is keyed by LaTeX label (`"Fig: <label>"`) and records where each figure came
from — including its `backend`, and `interactive: null` for a static-only figure, which
the publishing engine reads as "use the PNG". It covers **every** figure this pipeline
writes, which is what makes both `check-figure-parity` modes work whichever backend you
chose. HTML is written with `include_plotlyjs="directory"` so exports work offline.

It lives in `figures_html/` (or `$FIGURES_HTML_DIR`). On matplotlib that directory holds
the manifest and nothing else — the name is for what it usually contains.

## Publishing the document

The `publish` extra installs [`doc-publish`](https://github.com/c-energie/doc-publish),
which turns the document into a queryable corpus, a Notion wiki or a Quarto site:

```bash
uv sync --extra publish
doc-publish init      # scaffold the contract into the document repo
doc-publish build     # LaTeX -> corpus
doc-publish site      # Quarto site;  `sync` for Notion
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
- **Publishing state lives in the *document* repo**, under `.doc-publish/` — not here.
  So a publish driven from this repo writes state into the other one. That is
  counterintuitive, and losing `notion_manifest.json` duplicates an entire published wiki.

## Keep the tooling free of your data layer

`doc_analysis` deliberately depends on nothing private. Add your analysis stack as an
*extra* in `pyproject.toml`, import it in notebooks, and never from `src/` — that is what
keeps this repository reusable as a template and installable by someone who has your code
but not your data.
