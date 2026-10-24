# AGENTS.md

Guidance for coding agents working in this repository.

`README.md` is the documentation — the two backends, the config, the module map,
publishing — and this file deliberately does not restate it. Read it for how the package
works. What is below is the short list of things that go wrong here and fail *quietly*,
which is what an agent needs before it runs anything.

## This package writes into a different repository

`doc_analysis` exists to write into LaTeX document repos — this analysis's **target
documents** (`target_documents()`, `src/doc_analysis/save_figure.py`).
`save_document_figure()` creates `<document>/Sections/<section>/Figures/<name>.png` and
appends to a `.tex` file beside it; `save_document_table()` rewrites a section's
`tables.tex`, and `save_document_value()` (`save_value`) its `values.tex`; each records
the name in `<document>/figures_manifest.json`. Nothing it writes shows up in this repo's
`git status`.

- **Confirm the target documents are the ones you think before running anything that
  saves:** print `target_documents()`, not just `DOC_REPO`. They come from the structure,
  strictest first (ADR 0003): a `layout.toml` here declaring `analysis-hosts-writing`
  (`src/doc_analysis/layout.py`) puts the one document at `<root>/<nested_dir>`; else a
  `layout.toml` in this checkout's parent declaring `writing-hosts-analysis` with
  `nested_dir` equal to this checkout's directory name makes *that parent* the document —
  so a checkout nested in a document writes into it with no `.env` at all; else this
  checkout's `kind: "analysis"` member in the nearest `.claude/workspace.json`
  (`src/doc_analysis/workspace.py`, matched by `dir`) lists them in `documents`, resolved
  against the workspace root — any number, so **one save can write into several
  documents**. Only when no structure names a document is `DOC_REPO` the source. When one
  does, a `DOC_REPO` naming one of the targets is accepted silently and anything else
  **raises**, quoting both — it no longer wins with a warning.
- **`DOC_REPO` itself** resolves (`src/doc_analysis/env.py`): a real environment variable
  wins, otherwise `$DOC_ENV`, otherwise the nearest `.env` above the cwd, otherwise — only
  via `notebook_setup()` (`src/doc_analysis/notebook.py`) — the `.env` of the active
  checkout: the analysis checkout the cwd is in, else the one the package is installed
  from. The layouts and the workspace are found from the same checkout. So a notebook on
  the wrong interpreter, started outside its repo, can read *another* checkout's
  structure. The config, `figures_html/` and the parity baseline follow the active
  checkout too. A `.env` never overrides an explicit export.
- **Several targets: `documents=` narrows, never adds.** `save_fig`, `save_table` and
  `save_value` (and the `save_document_*` workers) write to every target by default;
  `documents=["paper"]` picks a subset by the `workspace.json` entry (else the document's
  directory name). A name that is not a target raises. Every chosen target is checked
  before anything is written: one missing the section, one with several `.tex` files and
  no `tex=`, or one where another analysis owns the name, fails the whole save. Never
  create a section directory in a document to make a save pass — the section is the
  author's.
- **Names have owners.** The first analysis to write a figure filename (or label), table
  tag or value macro into a document owns it there; the manifest entry's `analysis` says
  who (a workspace analysis's member `dir`, else its directory name). A save from another
  analysis raises `OwnershipError` naming the owner. Do not work around it by renaming or
  prefixing — names are never changed — and do not edit the manifest's `analysis` by
  hand: save under another name, or have the owner release it (delete the PNG or block,
  then `check-figure-parity --prune`).
- **`target_documents()` naming none is no-document mode, not a bug to fix**
  (`document_repo()` returns `None`). It is entered only when *nothing* names a document
  — no `DOC_REPO`, no layout on either side, no workspace member — or when the
  workspace's `documents` is `[]`; the savers then write to this checkout's gitignored
  `outputs/` (figures in `outputs/figures/`, `tables.tex`/`values.tex` in
  `outputs/<section>/`), touch no `.tex`, and print one line saying so. Anything that
  names a document and is wrong still raises; keep it that way, because a
  misconfiguration that fell back to `outputs/` would look like a successful save. It is
  also where a notebook on the wrong interpreter can end up, so when a save reports no
  document, check that before assuming none was intended. Never "fix" it by setting
  `DOC_REPO` or editing `documents`: whether this analysis has a document is the author's
  call (`attach-analysis` / `detach-analysis`), and pointing it at a guess writes into
  someone's document.
- **Never set `DOC_REPO` in a shell profile.** The moment there is a second document it
  points at the wrong one, and the failure is silent — figures land in another document.
- For tests and exploratory runs, don't point `DOC_REPO` at a real document. `section=`
  accepts an **absolute path**, and `html_dir=` is an argument, so a temp directory is
  enough: `save_document_figure(name, fig=fig, section=tmp_section, html_dir=tmp_html)`.
- When you have saved something, report the *document* repo's diff, not this one's.

### If `layout.toml` exists, `nested_dir` is a separate repo with its own remote: commit there, never here

That is the nested layout: the document repo cloned into a gitignored subdirectory of this
one by `setup_nested.py`. Its files are inside this directory tree but not in this repo's
history — `git status` here will never show them, and `git add` here must never try. Run
git for the document from inside `nested_dir`. Here, only `layout.toml` and the
`.gitignore` line are committed. If `nested_dir` is missing (a fresh clone),
`python setup_nested.py` restores it from `nested_remote`; it needs no arguments and does
not prompt.

## Figures

- **Never rename or move a committed figure.** The bare filename is the shared key: LaTeX
  resolves it via `\graphicspath`, the manifest indexes by it, and the publishing engine
  looks it up by name. A rename breaks all three with no error, and two matches report as
  `ambiguous`. Save under a new name instead of renaming.
- **Never describe a figure you have not looked at.** A caption plus a confident
  description is a fabricated result with a real label attached. What exists is recorded in
  each target document's `figures_manifest.json` (with no document, in
  `figures_html/` or `$FIGURES_HTML_DIR`), keyed `"Fig: <label>"`, with the `backend`,
  the owning `analysis`, and `interactive: null` for a static-only figure. A document's
  manifest is shared by every analysis feeding it, and also holds `"Tab: <tag>"` and
  `"Val: <macro>"` entries.
- **The appended `.tex` block is commented out on purpose.** It waits for the author to
  place the figure in the prose. So `check-figure-parity --figures` listing a figure as not
  rendered is the normal state, not a bug to fix: do not uncomment blocks, and do not
  hand-write `\begin{figure}` environments. Appending is gated on the section not already
  referencing the figure — and commented blocks count — so re-saving never duplicates one.
- **A save that appears to do nothing is usually the config.** `figures_config.toml` gates
  every figure and table name that goes through `notebook_savers()`; a name switched off
  returns `None` without writing. Check the config before debugging the saver.
- **Start every notebook from the template.** `notebook-skeleton new <section> <name>` for
  a new one (`--marimo` for a marimo app), `notebook-skeleton retrofit <notebook> --section
  <section>` for one copied in from elsewhere. `NOTEBOOK` must equal the file's name — it
  keys the config table and the manifest — and the script is what keeps it so.
  `notebook_setup()` is the single source of the setup: the templates' setup cell only
  calls it. Change behaviour there, never by adding path logic to a cell — a cell that
  walks the filesystem breaks when a kernel starts outside the repo.
- **`save_value` writes numbers, not figures, by the same rules.** `notebook_savers(...,
  values=True)` returns `(save_fig, save_table, save_value)`; without it, still two — every
  existing notebook unpacks two, so do not make it the default. `save_value(value, name)`
  puts value first, the worker `save_document_value(name, value)` name first; a non-string
  name raises `TypeError` for that reason. Values are gated by the `values` table in
  `figures_config.toml`. Never edit `values.tex` by hand, and never add the
  `\InputIfFileExists{Sections/<section>/values.tex}{}{}` line to the document's preamble
  yourself unless asked: the save warns with the line, and the preamble is the author's.
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
this one via GitHub's "Use this template", it prompts for answers (or takes them as
flags), and it deletes itself when done. In a downstream repo it has already run and this section no longer applies.

## Agent skills

### Workspace skills (Claude Code)

`.claude/settings.json` enables the `project-workspace@c-energie` plugin, auto-updating: the
project-workspace setup and adapt skills, e.g. `/project-workspace:adapt-existing-analysis`.
They act on one document: the one the session is inside (this repo, nested in its document
repo), or one picked from a project workspace's `workspace.toml`.

### Issue tracker

GitHub Issues on this repo, via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five default labels, each named for its role: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` and `docs/adr/` at the repo root, created lazily. See `docs/agents/domain.md`.
