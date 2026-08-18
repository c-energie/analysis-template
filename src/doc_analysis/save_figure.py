"""Save document figures: one call writes the LaTeX PNG and, for plotly, a wiki HTML.

Which backend you use is read off the figure object you pass — there is no setting to
keep in step with it, because the object already says which it is.

A **plotly** figure (preferred) produces BOTH outputs from the same object, so the PDF
and the wiki can never drift:

- a static PNG into the LaTeX repo's section Figures/ directory — filename and
  location are never changed by this module, because the LaTeX resolves bare
  filenames via \\graphicspath and the publishing agent indexes them;
- an interactive HTML (same stem) into a local figures directory.

A **matplotlib** figure writes the PNG only. That is a supported choice, not an
unfinished migration: you give up the interactive export and nothing else. Downstream
handles it — the publishing engine's figure emitter falls through to the static PNG
whenever an entry has no interactive export.

Either way the figure is recorded in that directory's figures_manifest.json, with a
`backend` field and `interactive: null` for the static-only case. The manifest is the
record of everything this pipeline writes, which is what `check-figure-parity` reads to
guard figure sizes and to report which figures the document actually renders — so a
matplotlib figure is covered by both checks exactly as a plotly one is.

The LaTeX repo is an input, located via the DOC_REPO environment variable (the
same convention the publishing agent uses) — this package never hardcodes a user path.

Publishing note: anything entering this pipeline has already been approved for
publication (standing policy, 2026-08-05), so the gate is upstream rather than here.
The HTML directory is nonetheless gitignored until the publishing route is built —
see .gitignore.
"""

import json
import os
import re
import warnings
from datetime import datetime, timezone
from pathlib import Path

DOC_REPO_ENV = "DOC_REPO"
HTML_DIR_ENV = "FIGURES_HTML_DIR"

FIGURES_DIRNAME = "Figures"
SECTIONS_DIRNAME = "Sections"
#: What the document's section tree was called before the rename. Still accepted, so a
#: document repo laid out before it keeps working; Sections/ wins where both exist.
LEGACY_SECTIONS_DIRNAME = "Chapters"
MANIFEST_NAME = "figures_manifest.json"

# Repo-relative default for the interactive exports (gitignored; see module docstring).
DEFAULT_HTML_DIR = Path(__file__).resolve().parents[2] / "figures_html"

# Artifact sub-directories (figures/tables) are save targets, not sections to descend into.
ARTIFACT_DIRNAMES = (FIGURES_DIRNAME,)


def document_repo():
    """Root of the LaTeX document repo, from $DOC_REPO.

    Raises with an actionable message rather than guessing: writing a figure into the
    wrong tree would silently break the document build.
    """
    value = os.environ.get(DOC_REPO_ENV)
    if not value:
        raise RuntimeError(
            f"{DOC_REPO_ENV} is not set. Add it to this repo's .env (copy .env.example),\n"
            f"    {DOC_REPO_ENV}=/path/to/my-document\n"
            f"pointing at the LaTeX document repo root — the directory containing "
            f"{SECTIONS_DIRNAME}/."
        )
    repo = Path(value)
    if section_root_name(repo) is None:
        raise NotADirectoryError(
            f"{DOC_REPO_ENV}={repo} does not look like the document repo "
            f"(no {SECTIONS_DIRNAME}/ directory)."
        )
    return repo


def section_root_name(repo):
    """"Sections", the legacy "Chapters", or None — whichever *repo* actually has.

    Sections/ wins where both are present, so a half-finished rename resolves to the new
    tree rather than to whichever name happens to be checked first.
    """
    for name in (SECTIONS_DIRNAME, LEGACY_SECTIONS_DIRNAME):
        if (Path(repo) / name).is_dir():
            return name
    return None


def sections_dir():
    """The Sections/ directory of the LaTeX document repo.

    Falls back to a legacy Chapters/ tree when that is the layout the document repo has.
    """
    repo = document_repo()
    return repo / (section_root_name(repo) or SECTIONS_DIRNAME)


def chapters_dir():
    """Deprecated alias for sections_dir(). Chapters/ was renamed to Sections/."""
    warnings.warn("chapters_dir() is deprecated; use sections_dir().",
                  DeprecationWarning, stacklevel=2)
    return sections_dir()


def select_section_dir(sections_root=None, skip_dirnames=ARTIFACT_DIRNAMES):
    """Interactively walk the document's section tree and return a leaf sub-directory.

    Prompts with a numbered menu at each level, hiding the artifact directories (which
    hold outputs rather than sections to descend into). Descending continues until a
    leaf directory is reached, or until "Save here" is chosen. Returns a Path.

    Prefer passing section="Results/ptg_application" to save_document_figure — a
    notebook that prompts cannot be run unattended.
    """
    current = Path(sections_root) if sections_root is not None else sections_dir()
    if not current.is_dir():
        raise NotADirectoryError(f"Sections directory not found: {current}")

    while True:
        sub_dir_names = sorted(
            child.name for child in current.iterdir()
            if child.is_dir() and child.name not in skip_dirnames
        )
        if not sub_dir_names:
            return current  # leaf directory: nowhere left to descend

        print(f"\nCurrent directory: {current}")
        options = sub_dir_names + [f"Save here ({current.name})"]
        for i, option in enumerate(options, start=1):
            print(f"  {i}. {option}")
        choice = input(f"Select 1-{len(options)}: ").strip()
        if not choice.isdigit() or not 1 <= int(choice) <= len(options):
            print("Not a valid choice.")
            continue
        index = int(choice) - 1
        if index == len(sub_dir_names):
            return current  # user chose to stop at this level
        current = current / sub_dir_names[index]


def select_chapter_dir(chapters_root=None, skip_dirnames=ARTIFACT_DIRNAMES):
    """Deprecated alias for select_section_dir()."""
    warnings.warn("select_chapter_dir() is deprecated; use select_section_dir().",
                  DeprecationWarning, stacklevel=2)
    return select_section_dir(chapters_root, skip_dirnames)


def _comment_block(block):
    """Prefix every line of a LaTeX block with "% " so it sits inert in the source."""
    return "\n".join(f"% {line}" if line else "%" for line in block.splitlines())


def _append_commented_block(section_dir, block, exclude=(), tex_name=None):
    """Append a commented-out LaTeX block to a .tex file in section_dir.

    Looks for .tex files directly inside section_dir, ignoring any whose name is in
    exclude (e.g. a generated table library file). tex_name picks the target file
    explicitly; otherwise a single candidate is used automatically and several raise,
    because prompting would hang an unattended notebook run. The block is commented and
    appended after a blank line. Returns the .tex Path written, or None when there is no
    eligible .tex file.
    """
    section_dir = Path(section_dir)
    exclude = set(exclude)
    tex_names = sorted(p.name for p in section_dir.glob("*.tex") if p.name not in exclude)
    if not tex_names:
        print(f"No .tex file found in {section_dir}; skipping reference.")
        return None

    if tex_name is not None:
        if tex_name not in tex_names:
            raise FileNotFoundError(
                f"tex file {tex_name!r} not found in {section_dir} (has: {tex_names})"
            )
    elif len(tex_names) == 1:
        tex_name = tex_names[0]
    else:
        # Ambiguous target. Raise rather than prompt: an input() here hangs an
        # unattended notebook run, and silently picking one risks dropping the block
        # in the wrong section file. The message says exactly how to resolve it.
        raise RuntimeError(
            f"{section_dir.name} has several .tex files ({tex_names}); "
            f"pass tex='<one of them>' to say where the reference should go "
            f"(or tex=False to skip appending one)."
        )

    tex_path = section_dir / tex_name
    commented = _comment_block(block)

    existing = tex_path.read_text(encoding="utf-8")
    separator = "" if existing.endswith("\n\n") else "\n" if existing.endswith("\n") else "\n\n"
    with tex_path.open("a", encoding="utf-8") as tex_file:
        tex_file.write(f"{separator}{commented}\n")

    print(f"Added commented reference to: {tex_path}")
    return tex_path


def _build_figure_block(figure_name, caption, label):
    """Return the (uncommented) LaTeX figure environment referencing figure_name."""
    return (
        "\\begin{figure}[H]\n"
        "    \\centering\n"
        f"    \\includegraphics[width=\\width]{{{figure_name}}}\n"
        f"    \\caption{{{caption}}}\n"
        f"    \\label{{Fig: {label}}}\n"
        "\\end{figure}"
    )


def _reference_state(text, stem, label):
    """"live", "commented" or None for this figure in one LaTeX source.

    Commented-out blocks count as references: the migration workflow leaves the
    \\begin{figure} block commented until the prose is written, and that block is exactly
    what must not be duplicated. A live reference outranks a commented one.
    """
    include = re.compile(
        r"\\includegraphics(?:\[[^\]]*\])?\{\s*" + re.escape(stem) + r"(?:\.\w+)?\s*\}")
    labelled = re.compile(r"\\label\{\s*Fig:\s*" + re.escape(label) + r"\s*\}")
    state = None
    for raw_line in text.splitlines():
        stripped = raw_line.lstrip()
        line = stripped.lstrip("%").strip()
        if include.search(line) or labelled.search(line):
            if not stripped.startswith("%"):
                return "live"
            state = "commented"
    return state


def search_root(section_dir):
    """Widest sensible scope for a reference scan: the Sections tree above section_dir.

    Figure filenames are unique across the document by rule (the LaTeX resolves them by
    bare name via \\graphicspath), so a block for a figure may legitimately sit in another
    section's .tex file and must still count. Falls back to section_dir when there is no
    Sections ancestor, which keeps the helpers usable on a standalone directory. A legacy
    Chapters/ ancestor counts too, so the scan still widens in a pre-rename document repo.
    """
    section_dir = Path(section_dir)
    roots = (SECTIONS_DIRNAME, LEGACY_SECTIONS_DIRNAME)
    for parent in (section_dir, *section_dir.parents):
        if parent.name in roots:
            return parent
    return section_dir


def figure_reference_state(section_dir, figure_name, label=None):
    """(state, tex_path) for figure_name: state is "live", "commented" or None.

    Scans every .tex under the Sections tree containing section_dir (see search_root),
    preferring a live reference over a commented one.
    """
    stem = Path(figure_name).stem
    label = label if label is not None else stem
    found = (None, None)
    for tex_path in sorted(search_root(section_dir).rglob("*.tex")):
        state = _reference_state(tex_path.read_text(encoding="utf-8", errors="replace"),
                                 stem, label)
        if state == "live":
            return state, tex_path
        if state == "commented" and found[0] is None:
            found = (state, tex_path)
    return found


def find_figure_reference(section_dir, figure_name, label=None):
    """The .tex file already referencing figure_name (commented or live), or None."""
    return figure_reference_state(section_dir, figure_name, label)[1]


def add_commented_figure_to_tex(figure_name, section_dir, caption=None, label=None,
                                tex=True):
    """Append a commented-out \\begin{figure} block for figure_name, if it has none yet.

    The append is gated on the figure not already being referenced anywhere in the
    Sections tree (see find_figure_reference) — commented blocks count, and so does a
    block that lives in another section's .tex — so re-saving a figure never accumulates
    duplicate blocks and tex can safely default to True. caption defaults to a TODO
    placeholder and label to the figure name stem, producing a \\label{Fig: <stem>}.

    tex=True (or None) appends only when the figure is unreferenced, choosing the
    section's sole .tex file and raising if there are several; tex='<name>.tex' names the
    target explicitly; tex=False skips the append entirely. Returns the .tex Path
    written, or None when nothing was appended.
    """
    if tex is False:
        return None
    caption = caption if caption is not None else "TODO: caption"
    label = label if label is not None else Path(figure_name).stem

    already = find_figure_reference(section_dir, figure_name, label)
    if already is not None:
        print(f"Figure '{figure_name}' is already referenced in {already.name}; "
              f"no block appended.")
        return None

    block = _build_figure_block(figure_name, caption, label)
    return _append_commented_block(section_dir, block,
                                   tex_name=None if tex is True else tex)


def _is_plotly_figure(fig):
    """True for a Plotly figure (which is saved via write_image, not savefig)."""
    return hasattr(fig, "write_image") and not hasattr(fig, "savefig")


def _resolve_section_dir(section, sections_root=None):
    """Resolve the section directory, interactively unless section is given.

    section may be an absolute path or a path relative to the Sections/ root (e.g.
    "Results/ptg_application"); passing it skips the interactive picker so a notebook
    can run top to bottom unattended.
    """
    if section is None:
        return select_section_dir(sections_root)
    section_dir = Path(section)
    if not section_dir.is_absolute():
        root = Path(sections_root) if sections_root is not None else sections_dir()
        section_dir = root / section_dir
    if not section_dir.is_dir():
        raise NotADirectoryError(f"Section directory not found: {section_dir}")
    return section_dir


def _one_of(new_name, new_value, old_name, old_value):
    """Resolve a renamed keyword argument, warning when the old spelling is used.

    Passing both is an error rather than a precedence rule: the two spellings naming
    different directories is a mistake worth stopping on, not one to resolve silently.
    """
    if old_value is None:
        return new_value
    if new_value is not None:
        raise TypeError(f"pass either {new_name}= or {old_name}=, not both")
    warnings.warn(f"{old_name}= is deprecated; use {new_name}=.",
                  DeprecationWarning, stacklevel=3)
    return old_value


def _resolve_html_dir(html_dir):
    """The figure output directory: argument, else env var, else default.

    Named for the interactive exports because that is what it mostly holds, but it also
    holds figures_manifest.json — so a matplotlib-only project gets this directory too,
    containing the manifest and nothing else.
    """
    html_dir = Path(html_dir or os.environ.get(HTML_DIR_ENV) or DEFAULT_HTML_DIR)
    html_dir.mkdir(parents=True, exist_ok=True)
    return html_dir


def _write_static_png(fig, save_path, **write_image_kwargs):
    """Static plotly export via kaleido, with a clear failure when it is missing."""
    try:
        import kaleido  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "Static PNG export of plotly figures needs the 'kaleido' package, which "
            "the plotly extra installs:\n"
            "    uv sync --extra plotly    (or: uv add kaleido / pip install kaleido)"
        ) from exc
    fig.write_image(str(save_path), **write_image_kwargs)


def _matplotlib_figure():
    """The current matplotlib figure, or an ImportError naming the extra."""
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ImportError(
            "save_document_figure() without a `fig` argument saves the current "
            "matplotlib figure, and matplotlib is not installed:\n"
            "    uv sync --extra matplotlib    (or pass fig=<your figure>)"
        ) from exc
    return plt.gcf()


def _default_hover_warning(fig, stem):
    """Warn when every trace still has plotly's default hover text.

    The interactive export is the reason for the dual output, and a figure whose hover
    text is plotly's default gives a reader nothing the PNG did not already give them.
    """
    if not any(getattr(trace, "hovertemplate", None) for trace in fig.data):
        warnings.warn(
            f"Figure '{stem}' has no hovertemplate on any trace - the interactive "
            "export will show plotly's default hover text. Set an explicit "
            "hovertemplate naming the fields that identify a point, and pass them as "
            "hover_fields=[...].",
            stacklevel=3,
        )


def _detect_notebook():
    """Best-effort name of the calling notebook, for the manifest (None if unknown)."""
    for env_var in ("JPY_SESSION_NAME", "__vsc_ipynb_file__"):
        value = os.environ.get(env_var)
        if value and value.endswith(".ipynb"):
            return Path(value).name
    return None


def _update_manifest(html_dir, key, entry):
    """Create/refresh one entry in <html_dir>/figures_manifest.json.

    Keyed by LaTeX label ("Fig: <label>") to match the publishing agent's figures.json, whose
    FigureEmitter reads `interactive` as a path relative to this manifest file — and
    falls through to the static PNG when it is null, which is how a matplotlib figure
    publishes. The manifest is rewritten on every save rather than maintained by hand.
    """
    manifest_path = Path(html_dir) / MANIFEST_NAME
    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[key] = entry
    manifest_path.write_text(
        json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest_path


def save_document_figure(name, fig=None, caption=None, label=None, *, section=None,
                       tex=None, hover_fields=None, static_scale=2, html_dir=None,
                       sections_root=None, notebook=None, chapter=None,
                       chapters_root=None, **save_kwargs):
    """Save a document figure: PNG into the LaTeX tree, plus interactive HTML if plotly.

    name is the figure file name; if it has no extension, ".png" is assumed. fig may be
    a plotly Figure (preferred) or a matplotlib Figure (static only); omitting it saves
    the current matplotlib figure. The section directory is chosen interactively
    unless section is given (a path relative to $DOC_REPO/Sections, e.g.
    "Results/ptg_application"), and the PNG is written to its Figures/ sub-directory —
    same filename and location as always, since the LaTeX and the publishing agent reference it
    by bare name. A commented-out figure block is appended to a .tex file in the
    section directory; tex names that file explicitly (no prompt) and tex=False skips
    the append.

    chapter= and chapters_root= are the pre-rename spellings of section= and
    sections_root=. They still work and warn; passing both spellings raises.

    Plotly figures additionally write <stem>.html into the local html directory
    (html_dir argument, else $FIGURES_HTML_DIR, else the repo's figures_html/)
    with include_plotlyjs="directory", so one shared plotly.min.js sits alongside and
    the exports work offline — the publishing agent's site builder copies both.

    Every figure, either backend, gets a manifest entry in that directory keyed by
    "Fig: <label>" and carrying {interactive, static, stem, backend, generated,
    notebook, hover_fields}. interactive is null for a matplotlib figure; hover_fields
    documents the identifying fields a plotly figure's hovertemplates expose.
    static_scale is the kaleido export scale (plotly only). Extra keyword arguments are
    forwarded to write_image (plotly) or savefig (matplotlib).

    Returns the saved PNG Path.
    """
    section = _one_of("section", section, "chapter", chapter)
    sections_root = _one_of("sections_root", sections_root, "chapters_root", chapters_root)
    section_dir = _resolve_section_dir(section, sections_root)

    figures_dir = section_dir / FIGURES_DIRNAME
    figures_dir.mkdir(parents=True, exist_ok=True)

    save_path = figures_dir / name
    if not save_path.suffix:
        save_path = save_path.with_suffix(".png")
    stem = save_path.stem

    if fig is None:
        fig = _matplotlib_figure()

    resolved_html_dir = _resolve_html_dir(html_dir)

    if _is_plotly_figure(fig):
        backend = "plotly"
        save_kwargs.setdefault("scale", static_scale)
        _write_static_png(fig, save_path, **save_kwargs)
        print(f"Saved figure to: {save_path}")

        html_path = resolved_html_dir / f"{stem}.html"
        # "directory" (not "cdn"): the publishing agent's site builder copies the sibling
        # plotly*.js alongside the export so the published site works offline.
        fig.write_html(
            str(html_path),
            include_plotlyjs="directory",
            full_html=True,
            config={"displaylogo": False},
        )
        print(f"Saved interactive figure to: {html_path}")
        interactive = html_path.name

        _default_hover_warning(fig, stem)
    else:
        # Not a warning: choosing matplotlib is a choice, and a warning on every save
        # is how a project learns to ignore the channel the checks above rely on.
        # ASCII only - this prints to a Windows console under cp1252.
        backend, interactive = "matplotlib", None
        fig.savefig(save_path, **save_kwargs)
        print(f"Saved figure to: {save_path}")
        print("  static only (matplotlib) - no interactive export")

    _update_manifest(
        resolved_html_dir,
        f"Fig: {label or stem}",
        {
            "interactive": interactive,
            "static": str(save_path),
            "stem": stem,
            "backend": backend,
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "notebook": notebook or _detect_notebook(),
            "hover_fields": list(hover_fields) if hover_fields else [],
        },
    )

    add_commented_figure_to_tex(save_path.name, section_dir, caption=caption, label=label,
                                tex=tex)

    return save_path