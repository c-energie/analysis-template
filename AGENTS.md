# AGENTS.md

Guidance for coding agents working in this repository.

`README.md` is the documentation — the two backends, the config, the module map,
publishing — and this file deliberately does not restate it. Read it for how the package
works. What is below is the short list of things that go wrong here and fail *quietly*,
which is what an agent needs before it runs anything.

## This package writes into a different repository

`doc_analysis` exists to write into the LaTeX document repo, located by `DOC_REPO`.
`save_document_figure()` creates `$DOC_REPO/Sections/<section>/Figures/<name>.png` and
appends to a `.tex` file beside it; `save_document_table()` rewrites a section's
`tables.tex`. Nothing it writes shows up in this repo's `git status`.

- **Confirm `DOC_REPO` points at the document you think it does before running anything
  that saves.** Resolution (`src/doc_analysis/env.py`): a real environment variable wins,
  otherwise `$DOC_ENV`, otherwise the nearest `.env` above the cwd. A `.env` never
  overrides an explicit export.
- **Never set `DOC_REPO` in a shell profile.** The moment there is a second document it
  points at the wrong one, and the failure is silent — figures land in another document.
- For tests and exploratory runs, don't point `DOC_REPO` at a real document. `section=`
  accepts an **absolute path**, and `html_dir=` is an argument, so a temp directory is
  enough: `save_document_figure(name, fig=fig, section=tmp_section, html_dir=tmp_html)`.
- When you have saved something, report the *document* repo's diff, not this one's.

## Figures

- **Never rename or move a committed figure.** The bare filename is the shared key: LaTeX
  resolves it via `\graphicspath`, the manifest indexes by it, and the publishing engine
  looks it up by name. A rename breaks all three with no error, and two matches report as
  `ambiguous`. Save under a new name instead of renaming.
- **Never describe a figure you have not looked at.** A caption plus a confident
  description is a fabricated result with a real label attached. What exists is recorded in
  `figures_html/figures_manifest.json` (or `$FIGURES_HTML_DIR`), keyed `"Fig: <label>"`,
  with the `backend` and `interactive: null` for a static-only figure.
- **The appended `.tex` block is commented out on purpose.** It waits for the author to
  place the figure in the prose. So `check-figure-parity --figures` listing a figure as not
  rendered is the normal state, not a bug to fix: do not uncomment blocks, and do not
  hand-write `\begin{figure}` environments. Appending is gated on the section not already
  referencing the figure — and commented blocks count — so re-saving never duplicates one.
- **A save that appears to do nothing is usually the config.** `figures_config.toml` gates
  every figure and table name that goes through `notebook_savers()`; a name switched off
  returns `None` without writing. Check the config before debugging the saver.
- **Pin `width`/`height` on any figure already committed.** The default size is smaller
  than most, so regenerating without pinning reflows the document silently.

## Working on the code

```bash
uv sync --extra dev --extra notebooks
uv run python -m pytest tests -q     # not `uv run pytest` — the trampoline can fail to
                                     # canonicalize the script path
```

- **The test suite must keep running on a bare install.** Tests hand the saver stub figure
  objects that duck-type only what it asks for, never a real plotly or matplotlib figure.
  A test that imports a backend makes every run wait on kaleido's headless Chrome
  download.
- **`src/` depends on nothing private and nothing document-specific.** Both backends are
  extras, probed with `find_spec`, and a missing one must raise an `ImportError` naming the
  extra. A project's own analysis stack goes in an extra and is imported from notebooks —
  never from `src/`. That boundary is what keeps this repo reusable.
- **Keep the pre-rename spellings.** `Chapters/` is still accepted alongside `Sections/`,
  and `chapter=` / `chapters_root=` / `chapters_dir()` / `select_chapter_dir()` warn but
  work. A pre-rename document repo depends on them; don't tidy them away.
- **Nothing may prompt.** An `input()` on a code path a notebook reaches hangs an
  unattended run — an ambiguous target raises with the fix in the message instead.
- There is no linter or formatter configured. Match the surrounding style: module
  docstrings explain *why*, and comments name the failure the code prevents.

## If `init.py` is still here

This is then the unfilled template: the distribution name and author in `pyproject.toml`
are still placeholder tokens. **Do not run `init.py`** — it belongs to a repo created from
this one via GitHub's "Use this template", it prompts for answers, and it deletes itself
when done. In a downstream repo it has already run and this section no longer applies.
