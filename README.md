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

This is a **GitHub template**, not a repository to fork or clone: the copy you run your
analysis from is your own repository, with its own history and no link back here.

There are two layouts — how this repo and the document repo sit relative to each other —
and, in a project workspace, a third way to be connected to documents
([several documents](#feeding-several-documents)):

- **Side by side** (the default): two checkouts next to each other, each opened on its own.
  **Do the document repository first.** This one asks for its path during setup, and every
  figure it writes lands there. If you have not created it yet, start at
  [writing-template](https://github.com/c-energie/writing-template) and come back.
- **Nested**: this repo is the one you open, and the document repo lives inside it as a
  separate, gitignored repo. Nothing needs creating first — see
  [Nesting the document inside this repo](#nesting-the-document-inside-this-repo).

**1. Create your repository.** On
[c-energie/analysis-template](https://github.com/c-energie/analysis-template), press
**Use this template → Create a new repository**. Name it for the document it serves
(`<document>-analysis` reads well), and make it private if your data is — a template's
visibility is not inherited.

**2. Clone it and fill in the placeholders.**

```bash
git clone https://github.com/<you>/<your-analysis>.git
cd <your-analysis>
python init.py
```

`init.py` asks four things — project name, author, the path to your document repo (or
whether to nest it here instead), and which plotting backend you want — then writes your
`.env` and deletes itself. Run it once,
in **your** repository; it edits in place and then removes itself, so it is not something
to run in a checkout of the template. The path can be left blank and set later in `.env`.

To run it unattended, pass the answers as flags instead — `--distribution`, `--author`,
`--doc-repo` (optional) or `--nest`, and `--backend` (default `plotly`); `python init.py --help` lists
them. A flag skips its question, and a bad value stops the script with the reason. With no
terminal to ask on, a left-out `--distribution` or `--author` stops it too.

**3. Install, with the backend you chose** (Python 3.11.4+):

```bash
uv sync --extra dev --extra notebooks --extra plotly       # preferred
uv sync --extra dev --extra notebooks --extra matplotlib   # static-only fallback
```

`pip install -e '.[dev,notebooks,plotly]'` does the same if you would rather not use `uv`.
Add `--extra marimo` if you write notebooks in [marimo](https://marimo.io) rather than
Jupyter; nothing else changes. Keep the install editable (`uv sync` and `pip install -e`
both are): an editable install is how a notebook finds this repo from any directory.

**4. Prove the wiring before writing any analysis of your own.** Run
`notebooks/example/example_figure.ipynb`. It uses synthetic data, so it works before
anything of yours is connected, and it writes a real figure into the document repo. (It is
a plotly notebook; on matplotlib, start from the [usage block](#usage) below instead.)

**5. Check the document repo, and commit there.** You should find a new PNG under
`Sections/Example/Figures/` and a commented-out `\begin{figure}` block appended to
`Sections/Example/example.tex`. Committing those is on you — this repository writes them
and nothing more. Then `check-figure-parity --snapshot` here, to record the baseline.

**6. Make it yours.** Add your own analysis stack as an *extra* in `pyproject.toml` and
import it in notebooks, never from `src/` — see
[the last section](#keep-the-tooling-free-of-your-data-layer) for why that matters.

Setting all three repositories up for the first time? The end-to-end order lives in the
document repo: [writing-template/SETUP.md](https://github.com/c-energie/writing-template/blob/main/SETUP.md).

### Nesting the document inside this repo

```
my-study/               <- this repo (the host repo), the one you open
├── layout.toml         <- committed: says where the document is and where it came from
├── src/ notebooks/ ...
└── my-study-writing/   <- the document repo: its own repo and remote, gitignored here
```

**Choose it** when the analysis is where you work and the document is its output — one
folder to open, one place for an agent to start — and you do not need the document checked
out without the analysis. Keep the two side by side when the document has a life of its own
(co-authors who never run the analysis, several analysis repos feeding one document).

**The one command**, run here after `init.py` (or answer yes to its "Nest the document
inside this repo?", which runs it for you):

```bash
python setup_nested.py                     # creates it from writing-template (needs gh)
python setup_nested.py --from <url|path>   # adopts an existing one: GitHub, Overleaf, local
```

Creating calls `gh repo create <owner>/<name> --template c-energie/writing-template
--private --clone`; `--dir`, `--name`, `--owner` and `--public` change the defaults
(`<this repo's name>-writing`, the same name, this repo's GitHub owner, private). Without a
logged-in `gh` it stops before changing anything — run `gh auth login`, or create the repo
yourself and use `--from`. Either way the script clones into the subdirectory, adds it to
`.gitignore` and writes `layout.toml`. It does not write `.env`: `doc_analysis` reads
`DOC_REPO` from `layout.toml`, so every clone works without one.

**What to commit where.** Here: `layout.toml` and the `.gitignore` line, once. Everything
in the document — including every figure and table this package writes — is committed
*in the nested directory*, which is a separate repo with its own remote and history. `git
status` here never shows it.

**On a fresh clone** of this repo the nested directory is absent (it is gitignored). One
command restores it from the `nested_remote` that `layout.toml` recorded:

```bash
python setup_nested.py
```

Until then, saving a figure raises with that command in the message.

### Feeding several documents

In a project workspace an analysis repo can be a **workspace analysis**: a member of the
workspace in its own right, inside no document, attached to any number of documents.
`attach-analysis` / `detach-analysis` (the `project-workspace` plugin) record them in the
workspace's `.claude/workspace.json`:

```json
{ "dir": "validation", "kind": "analysis", "documents": ["thesis", "paper"] }
```

`doc_analysis` finds the nearest `.claude/workspace.json` above this repo, this repo's
member by `dir`, and resolves each entry against the workspace root: those are its
**target documents** (`target_documents()`). Every save writes into each of them — the
same PNG and commented block, the same `tables.tex` and `values.tex` blocks — and
`documents=` narrows one call to a subset:

```python
save_fig(fig, "ptg_scatter.png")                         # thesis and paper
save_fig(fig, "ptg_detail.png", documents=["paper"])     # paper only
```

A name in `documents=` that is not a target raises: it narrows, never adds. Every chosen
target is checked before anything is written, so a save that cannot land in all of them —
one lacks the section, has several `.tex` files and no `tex=`, or another analysis owns
the name there — lands in none. An empty list (`"documents": []`) is
[no-document mode](#no-document-yet). A nested analysis is unaffected: its `layout.toml`
names its one document, whether or not the workspace lists it too.

**Ownership.** One document can be fed by its nested analysis and several workspace
analyses, and the bare filename is the key LaTeX, the manifest and publishing share, so
names are never prefixed. Instead the first analysis to write a figure filename, a table
tag or a value macro into a document **owns** it there, recorded in the document's
`figures_manifest.json`. A save of that name from another analysis raises, naming the
owner; the owner re-saves freely. To give a name up, delete the PNG (or the table's or
value's block) from the document and run `check-figure-parity --prune`.

**`DOC_REPO`** is then not needed. If `.env` sets one — `setup-doc-publish` does, for
doc-publish — it must name one of the targets, which changes nothing; naming any other
directory raises, quoting both ([ADR 0003](docs/adr/0003-target-documents-from-workspace.md)).
The same holds in the nested layout.

### No document yet

An analysis can come before its write-up, or be shared before any document is chosen.
With **nothing** naming a document — no `DOC_REPO` in the environment or a `.env`, no
`layout.toml` here, no host `layout.toml` naming this directory, no workspace member
listing documents — or with a workspace member whose `documents` is `[]`, this repo runs
in **no-document mode**: `document_repo()` returns `None`, and the same notebooks save into
this repo's own `outputs/` (gitignored) instead of raising:

| Saved | Where, with no document |
|---|---|
| figure PNG | `outputs/figures/<name>.png` — the same bare filename, never prefixed |
| interactive HTML, manifest | `figures_html/`; the manifest's `static` names the local PNG |
| `tables.tex`, `values.tex` | `outputs/<section>/` |
| `\begin{figure}` block, table and value references | nothing: there is no prose to put them in |

`figures_config.toml`, `section=` and `notebook=` and every return value behave as before.
The first save of a process prints one line saying no document is configured, where the
output went, and where it looked.

It is entered **only when nothing is configured**. Anything that names a document and is
wrong still raises exactly as before — a `DOC_REPO` without `Sections/`, a nested
directory not cloned yet, a host `layout.toml` whose `nested_dir` is not this directory —
because quietly saving locally would hide the mistake. So a `.env` line pointing at
nothing is not a way to ask for it: leave the line out.

To leave it, set `DOC_REPO` or nest this repo in a document, and re-run the notebooks:
the figures land in the document as if no-document mode had never happened. `outputs/` is
left as it is, not copied anywhere.

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
it with no shell setup. The file used is `$DOC_ENV` if set, else the nearest `.env` above
the working directory — and, for a notebook that has called `notebook_setup()`, this
repo's own `.env` when neither found one, so a kernel started outside the repo still gets
its `DOC_REPO`. In the [nested layout](#nesting-the-document-inside-this-repo), with neither
setting it, `DOC_REPO` comes from `layout.toml`; and when this repo is itself nested
inside the document repo — the parent's `layout.toml` declares `writing-hosts-analysis`
and names this directory as `nested_dir` — it is that parent, so `init.py` asks for no
path ([ADR 0002](docs/adr/0002-doc-repo-from-host-layout.md)). A workspace analysis gets
its documents from `.claude/workspace.json` the same way
([several documents](#feeding-several-documents)). Where a layout or the workspace names
the document, a `DOC_REPO` naming anything else raises rather than overriding it
([ADR 0003](docs/adr/0003-target-documents-from-workspace.md)). **A variable already set
in your shell wins** over `.env`, which keeps CI and one-off overrides working:

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

### Numbers in the prose

A number quoted in the text is a result too, and one typed in by hand drifts the first time
the notebook re-runs on new data. `values=True` adds a third saver, which writes it into
the section's `values.tex` as a LaTeX macro:

```python
save_fig, save_table, save_value = notebook_savers(section=SECTION, notebook=NOTEBOOK,
                                                   tex=TEX, values=True)

save_value(0.873, "ptg_mlr_agreement")                      # \ptgMlrAgreement -> 0.87
save_value(0.412, "heat_pump_share", fmt="percent", decimals=1)    # 41.2\%
save_value(-12.4, "cv_rmse_20", unit="K", signed=True)      # \cvRmseTwoZero -> $-12.40$\,K
```

The macro is the snake_case name in lower camel case, digits spelled out (TeX macro names
are letters only); `macro=` overrides it. `decimals`, `fmt="percent"` (×100 and `\%`),
`scale`, `signed` and `unit` shape the number; a string passes through unchanged. Without
`values=True` the call still returns two savers, so existing notebooks are untouched.

Each value is a tagged block — a `\providecommand` then a `\renewcommand`, so the file
survives being input twice — and re-saving a name replaces its block. The first save
appends a commented `\ptgMlrAgreement` to the section's `.tex` (same `tex=` rules as a
figure) for you to place in a sentence. The document loads the file once, from its root
settings file, with one line per section next to `\graphicspath`:

```latex
\InputIfFileExists{Sections/Results/ptg_application/values.tex}{}{}
```

`save_value` never edits the preamble: when that line is missing it warns, giving the exact
line to add. Never edit a `values.tex` by hand — the next save rewrites it.

### Starting a notebook

```bash
notebook-skeleton new Results/ptg_application ptg_fits
```

copies `notebooks/_template.ipynb` to `notebooks/Results/ptg_application/ptg_fits.ipynb`
with the setup cell filled in (`SECTION`, `NOTEBOOK`, and `TEX` worked out from the
section), and a figure cell and a table cell already calling `save_fig` / `save_table` for
your backend. Name the figure and table before running it: the savers refuse the
template's `<<FIGURE>>` / `<<TABLE>>` placeholders rather than saving a file by that name.

`notebook-skeleton new --marimo Results/ptg_application ptg_fits` does the same for
marimo, writing `notebooks/Results/ptg_application/ptg_fits.py` (it only writes text;
the `marimo` extra is needed to `marimo edit` or `export` it).
`NOTEBOOK` is then the `.py` filename and the config key its stem, exactly as for a
`.ipynb`. `retrofit` is Jupyter-only.

Bringing in a notebook from an existing project instead? Copy it under `notebooks/`, then
`notebook-skeleton retrofit <notebook> --section <section>` grafts the same setup cell on
and lists every line that still saves or exports the old way. It only edits notebooks
inside this repo's `notebooks/`. A notebook that already calls `notebook_savers` is not
grafted; its saver calls are checked against the current signature instead -- `chapter=`,
unknown keywords, three names unpacked without `values=True`, `save_value` without it,
and a `label=` that does not mirror the file stem each fail the run, while a `section=`
without `config_section=` is flagged for a look, since older forks meant the config table
by it.

## Running notebooks

Every notebook starts with the same setup cell:

```python
from doc_analysis import notebook_setup, notebook_savers
ROOT = notebook_setup()
```

`notebook_setup()` loads this repo's `.env`, styles the installed backend, puts
`notebooks/` on `sys.path` (so a helper module kept beside the notebooks imports from any
sub-folder) and moves to this repo's root, which it returns. The repo is the analysis
checkout the working directory is in — the nearest directory above it holding both a
`pyproject.toml` and `src/doc_analysis/` — and, when the kernel started in none, the one
the installed package lives in. `figures_config.toml`, `figures_html/` and the parity
baseline follow the same checkout. So the one thing that matters is that the kernel runs
**the venv `doc_analysis` is installed into**: this repo's own `.venv`, whether it stands
alone or is nested in its document repo:

| | Interpreter |
|---|---|
| Windows | `<venv root>\.venv\Scripts\python.exe` |
| macOS / Linux | `<venv root>/.venv/bin/python` |

Pick any other and `import doc_analysis` fails, or — worse — imports a different checkout,
and a kernel started outside this repo writes into that checkout's document.

Several analysis repos installed into one venv (a project workspace's) work, as long as
each notebook's kernel starts inside its own repo: only the first `doc_analysis` on
`sys.path` is imported, so `notebook_setup()` then warns, naming both checkouts — the code
running is the other checkout's version — but writes into this repo's document.

- **JupyterLab**: `uv run jupyter lab` from this repo. `uv run` uses the right venv, so
  there is nothing to select.
- **VS Code**: *Python: Select Interpreter* → the path above, then pick it as the
  notebook's kernel (top right). Opening the document repo or the project workspace as the
  folder is fine.
- **PyCharm**: *Settings → Project: <name> → Python Interpreter → Add Interpreter → Add
  Local Interpreter → select existing* → the path above. Opening
  the document repo or the whole project workspace as the project is fine — that case is
  what `notebook_setup()` exists for: the kernel starts above this repo, where the old
  upward search never found it.
- **marimo** (`--extra marimo`): `uv run marimo edit notebooks/<section>/<name>.py` from
  this repo; headless, `uv run marimo export html notebooks/<section>/<name>.py -o out.html`,
  which runs every cell exactly as the editor does.

Whichever you use, prove the wiring in a cell before any analysis:

```python
from doc_analysis import notebook_setup, document_repo
notebook_setup(); print(document_repo())
```

It should print your document repo. `None` means nothing named one and this repo is in
[no-document mode](#no-document-yet) — right for an analysis with no document yet, and a
wrong interpreter or a `.env` missing its line otherwise. The first save then prints every
place it looked for a `.env`, which tells those apart. (On a non-editable install there is
no checkout to fall back to, so `notebook_setup()` leaves the working directory alone and
that line says so.)

Notebooks written against the old `from setup_notebook import ROOT` keep working:
`notebooks/setup_notebook.py` is now a shim calling `notebook_setup()`.

## The config

```toml
default = true          # what an unlisted name does, and is recorded as
save_figures = true     # master switch; can veto, never turns an entry on
save_tables = true
save_values = true      # optional; true when absent

[example_figure.figures]
example_scatter = true

[example_figure.values]     # save_value's names, gated the same way
ptg_mlr_agreement = true
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
check-figure-parity --prune      # drop manifest entries (and HTML) whose PNG or block is gone
check-figure-parity --figures    # which saved figures each document actually renders
pytest tests -q
```

The last one catches the quiet failure: a figure can be regenerated perfectly and still be
invisible in the PDF because its `\begin{figure}` block was never written or is still
commented out.

The check runs **per analysis, over all its target documents**: `--snapshot` records this
analysis's own figures in each, keyed by document (`{"documents": {"thesis": {...}}}`, each
path relative to its document), and the default check compares every one. A baseline from
before it was keyed by document is still read, as the baseline of the only target.
`--figures` reports over a document's whole manifest — every analysis feeding it — and
`--prune` also drops a stale entry another analysis owns, which is what releases its name.

In [no-document mode](#no-document-yet) `--snapshot` and the default check run against
`outputs/`, and the baseline records `"target": "local"`. Checking a local baseline once
a document is configured, or a document's baseline with none, fails with the reason
rather than passing; re-snapshot after the move. `--figures` says there is no document
and exits 0.

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

`src/doc_analysis/`, fifteen modules:

| Module | What it does |
|---|---|
| `env.py` | Reads a `.env` into the environment on import — `$DOC_ENV`, else the nearest above the cwd — without overriding what the shell already set. Stdlib; `KEY=value` needs no dependency. |
| `layout.py` | Reads `layout.toml`, which in the nested layout puts the document repo at `<root>/<nested_dir>`, and — the other way up — the host document repo's, which makes the parent the document when it names this directory: `document_repo()`'s last two fallbacks. Stdlib `tomllib`. |
| `workspace.py` | Reads `.claude/workspace.json`: this repo's `kind: "analysis"` member, matched by `dir`, and its `documents`, each resolved against the workspace root. Read-only; ignores the keys other plugins own. Stdlib `json`. |
| `notebook.py` | `notebook_setup()`: the one setup every notebook calls. Falls back to the active checkout's `.env` (the cwd's, else the installed one), styles the backend, chdirs to the repo root. |
| `style.py` | The document's visual constants in no plotting library: serif stack matching LaTeX, CVD-validated palette (assign slots *in order*), diverging stops, print DPI. Both themes are built from it, so the backends cannot drift apart. Imports nothing. |
| `theme.py` | The single plotly template, registered as the default **on import**. `figure_size(w, h)` in inches. Needs the `plotly` extra. |
| `theme_mpl.py` | The matplotlib equivalent: the same values as rcParams, applied **on import**, plus the diverging colormap and `figure_size_in(w, h)`. Needs the `matplotlib` extra. |
| `save_figure.py` | `save_document_figure()`: PNG into each target's `Sections/<section>/Figures/` (`outputs/figures/` with no document), a manifest entry, and — for a plotly figure — the interactive HTML. Also `target_documents()` (with `document_repo()`, its single-document view) and `local_output_dir()`, which all three savers and the parity check share. |
| `manifest.py` | `figures_manifest.json`: atomic writes, ownership checks, and the one-time move of a pre-ADR-0003 manifest from `figures_html/` into the document. |
| `save_table.py` | `save_document_table()`: booktabs LaTeX into a per-section `tables.tex`, tagged so re-saving replaces in place. |
| `save_value.py` | `save_document_value()`: a scalar as a LaTeX macro in a per-section `values.tex`, tagged like `tables.tex`; warns when the document does not load the file. |
| `figure_config.py` | Reads `figures_config.toml` (stdlib `tomllib`, no dependency). Appends new entries textually, so your comments survive. |
| `savers.py` | `notebook_savers()` — the pair every notebook uses, plus `save_value` with `values=True`. |
| `parity.py` | The `check-figure-parity` console script. |
| `notebook_skeleton.py` | The `notebook-skeleton` console script: a new notebook from `notebooks/_template.ipynb` (or, with `--marimo`, a marimo app from `notebooks/_template_marimo.py`), or the Jupyter template's setup cell grafted onto a copied-in one. |

The manifest is keyed by LaTeX label (`"Fig: <label>"`) and records where each figure came
from — including its `backend`, and `interactive: null` for a static-only figure, which
the publishing engine reads as "use the PNG". It covers **every** figure this pipeline
writes, which is what makes both `check-figure-parity` modes work whichever backend you
chose. HTML is written with `include_plotlyjs="directory"` so exports work offline.

In a document it lives at the **document's root** — where doc-publish looks for it — and
is shared by every analysis feeding that document. Each entry records its owner
(`analysis`), and beside the `"Fig: <label>"` entries sit `"Tab: <tag>"` and
`"Val: <macro>"` ones, which doc-publish ignores. Paths are relative to the manifest file:
`static` to the PNG in the document, `interactive` to the HTML, which stays in this repo's
`figures_html/` (or `$FIGURES_HTML_DIR`), e.g. `../my-analysis/figures_html/x.html`. It is
written to a temp file and renamed, so two notebooks saving at once cannot tear it. The
first save into a document moves this repo's older entries for it out of
`figures_html/figures_manifest.json`, printing one line.

With no document, or for a save into an explicit absolute `section=`, the manifest stays in
`figures_html/`. On matplotlib that directory then holds the manifest and nothing else —
the name is for what it usually contains.

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
