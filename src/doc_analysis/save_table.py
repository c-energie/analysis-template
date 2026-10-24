import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from doc_analysis.manifest import TABLE_PREFIX, relative_to_manifest, update_manifest
from doc_analysis.save_figure import (
    LEGACY_SECTIONS_DIRNAME,
    SECTIONS_DIRNAME,
    _append_commented_block,
    _check_tex_targets,
    _check_owners,
    _document_relative,
    _local_section_dir,
    _one_of,
    _plan_save,
    _single_or_list,
    search_root,
)

LIBRARY_NAME = "tables.tex"


def _default_column_format(df, index):
    """Build a prescribed booktabs column spec: numeric columns right-aligned, text left.

    An index column, when included, is left-aligned. This keeps every generated table
    aligned the same way regardless of the DataFrame's column order or dtypes.
    """
    cols = ["l"] if index else []
    cols += ["r" if pd.api.types.is_numeric_dtype(dtype) else "l" for dtype in df.dtypes]
    return "".join(cols)


def dataframe_to_latex(df, index=False, decimals=2, escape=False, column_format=None,
                       **to_latex_kwargs):
    """Render a DataFrame as a booktabs LaTeX tabular string with consistent formatting.

    Floats are formatted to a fixed number of decimals (decimals, set None to leave them
    untouched), numeric columns are right-aligned and text columns left-aligned via a
    derived column_format (override with column_format), and the pandas default booktabs
    rules (\\toprule/\\midrule/\\bottomrule) are used. index controls whether the DataFrame
    index is written, and escape whether LaTeX special characters are escaped (kept False
    so cells may contain math/markup). Extra keyword arguments pass through to
    DataFrame.to_latex. Returns just the tabular environment.
    """
    if column_format is None:
        column_format = _default_column_format(df, index)

    float_format = (lambda value: f"{value:.{decimals}f}") if decimals is not None else None

    return df.to_latex(
        index=index,
        escape=escape,
        float_format=float_format,
        column_format=column_format,
        **to_latex_kwargs,
    )


def find_table_reference(section_dir, tag, exclude=()):
    """The .tex file in section_dir that already pulls in table *tag*, or None.

    Matches \\ExecuteMetaData[<any library path>]{tag} whether commented or live, so the
    path spelling (bare ``tables.tex`` or repo-root-relative) does not matter. Mirrors
    find_figure_reference: re-saving a table must not accumulate reference snippets.
    """
    pattern = re.compile(r"\\ExecuteMetaData\s*\[[^\]]*\]\s*\{\s*" + re.escape(tag) + r"\s*\}")
    exclude = set(exclude)
    for tex_path in sorted(Path(section_dir).glob("*.tex")):
        if tex_path.name in exclude:
            continue
        for raw_line in tex_path.read_text(encoding="utf-8").splitlines():
            if pattern.search(raw_line.lstrip().lstrip("%").strip()):
                return tex_path
    return None


def _library_reference_path(section_dir, library_name=LIBRARY_NAME):
    """The library path to write inside \\ExecuteMetaData[...], relative to the document root.

    Sections are pulled into main.tex with \\subfile, so TeX resolves the path from the
    document root, not from the section: a bare ``tables.tex`` loads nothing in the full
    build and the table silently never renders (issue #23). So the path is the section's
    own, e.g. ``Sections/Results/ptg/tables.tex`` — the form the example section uses. A
    section under no Sections/ (or legacy Chapters/) directory, which is what a test's
    temporary section is, has no document root to be relative to and keeps the bare name.
    """
    sections_root = search_root(section_dir)
    if sections_root.name not in (SECTIONS_DIRNAME, LEGACY_SECTIONS_DIRNAME):
        return library_name
    # Lexical, not resolved: sections_root is an ancestor of section_dir by construction,
    # so this cannot fail, whereas resolving a symlinked section follows it out of the
    # document and raises after tables.tex is already written. TeX sees the link's path.
    return (Path(section_dir).relative_to(sections_root.parent) / library_name).as_posix()


def _build_table_block(tabular_latex, caption, label):
    """Wrap a tabular string in a full \\begin{table} environment with caption and label."""
    indented = "\n".join(f"    {line}" if line.strip() else "" for line in tabular_latex.splitlines())
    return (
        "\\begin{table}[H]\n"
        "    \\centering\n"
        f"{indented}\n"
        f"    \\caption{{{caption}}}\n"
        f"    \\label{{Tab: {label}}}\n"
        "\\end{table}"
    )


def _write_table_to_library(library_path, tag, block):
    """Insert (or replace) a tagged table block in the shared library .tex file."""
    return _write_tagged_block(library_path, tag, block, kind="table")


def _write_tagged_block(library_path, tag, block, kind):
    """Insert (or replace) a tagged block in a shared library .tex file.

    Shared by tables.tex and save_value's values.tex; kind only names the block in the
    message.

    The block is bracketed by catchfilebetweentags markers (%<*tag> ... %</tag>) so a
    single table can later be pulled out with \\ExecuteMetaData[<library>]{tag}. If the tag
    already exists in the file its region is replaced (so re-saving updates in place);
    otherwise the tagged block is appended after a blank line. Returns the library Path.
    """
    entry = f"%<*{tag}>\n{block}\n%</{tag}>\n"

    content = library_path.read_text(encoding="utf-8") if library_path.exists() else ""
    pattern = re.compile(re.escape(f"%<*{tag}>") + r".*?" + re.escape(f"%</{tag}>") + r"\n?",
                         re.DOTALL)

    if pattern.search(content):
        content = pattern.sub(lambda _: entry, content)  # callable repl: keep backslashes literal
        action = "Replaced"
    else:
        separator = "" if not content else "\n" if content.endswith("\n\n") else (
            "\n" if content.endswith("\n") else "\n\n")
        content = f"{content}{separator}{entry}"
        action = "Appended"

    library_path.write_text(content, encoding="utf-8")
    print(f"{action} {kind} '{tag}' in: {library_path}")
    return library_path


def _record_library_entry(target, analysis, key, library_path, tag, notebook, **extra):
    """Record a table's or value's owner in its document's manifest.

    The block itself lives in the section's library file; the entry is what makes the
    name owned — the first analysis to write it into a document — and lets
    `check-figure-parity --prune` release it once the block is gone.
    """
    manifest_path = target.manifest_path
    update_manifest(manifest_path, key, {
        "analysis": analysis,
        "notebook": notebook,
        "library": relative_to_manifest(manifest_path, library_path),
        "tag": tag,
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **extra,
    })


def _release_block(library_name, tag):
    """The 'how to release it' half of an ownership error, for a tagged block."""
    return lambda target: (f"delete the %<*{tag}> ... %</{tag}> block from "
                           f"{_document_relative(target, target.section_dir / library_name)}")


def save_document_table(df, name, caption=None, label=None, sections_root=None,
                      library_name=LIBRARY_NAME, add_reference=True, index=False,
                      decimals=2, escape=False, column_format=None, *, section=None,
                      tex=None, chapter=None, chapters_root=None, documents=None,
                      notebook=None, **to_latex_kwargs):
    """Save a DataFrame as a LaTeX table into a per-leaf shared table library file.

    The section directory is chosen interactively unless section is given (a path
    relative to $DOC_REPO/Sections, e.g. "Results/ptg_application"); tex names
    the .tex file that receives the commented reference, so unattended notebook runs
    never prompt. The DataFrame is
    rendered with dataframe_to_latex (booktabs, fixed decimals, aligned columns) and wrapped
    in a full \\begin{table} environment, which is written into a single shared library file
    (library_name, e.g. tables.tex) placed directly in the chosen leaf directory under a
    catchfilebetweentags tag taken from name. Re-saving the same name replaces that table in
    place rather than adding a duplicate, so one file accumulates all of the leaf
    directory's tables.

    Pull an individual table into the prose with
    \\ExecuteMetaData[Sections/<section>/tables.tex]{name}, the path relative to the
    document root because sections are \\subfile-d into main.tex (requires
    \\usepackage{catchfilebetweentags}). When add_reference is True that command is
    appended, commented out, to a .tex file in the chosen directory as a ready-to-place
    snippet — but only if no .tex in the section pulls the tag in already (commented or
    live), so re-saving never accumulates duplicate snippets. tex names the target file,
    tex=False suppresses the snippet, and several candidate .tex files raise rather than
    prompt. caption defaults to a TODO placeholder and label to name (giving
    \\label{Tab: <name>}). index, decimals, escape, column_format and any extra keyword
    arguments are forwarded to dataframe_to_latex. Returns the library file Path, or a
    list of them when it wrote to several documents.

    A relative section is written into every target document, as for
    save_document_figure, and documents= narrows that the same way. Each document's
    manifest records the table as "Tab: <tag>" with its owner and notebook; a tag another
    analysis owns in any chosen document raises before anything is written.

    chapter= and chapters_root= are the pre-rename spellings of section= and
    sections_root=. They still work and warn; passing both spellings raises.

    With no document configured, a relative section's library is written to
    `outputs/<section>/` in the active checkout instead, and no reference is appended.
    """
    section = _one_of("section", section, "chapter", chapter)
    sections_root = _one_of("sections_root", sections_root, "chapters_root", chapters_root)
    plan = _plan_save(section, sections_root, documents)

    tag = Path(name).stem
    caption = caption if caption is not None else "TODO: caption"
    label = label if label is not None else tag
    key = f"{TABLE_PREFIX}{tag}"
    if plan is not None:
        _check_owners(plan, f"The table {tag!r}", _release_block(library_name, tag),
                      keys=(key,))
        if add_reference:
            _check_tex_targets(
                plan, tex,
                lambda section_dir: find_table_reference(
                    section_dir, tag, exclude={library_name}) is not None,
                exclude={library_name})

    tabular = dataframe_to_latex(df, index=index, decimals=decimals, escape=escape,
                                 column_format=column_format, **to_latex_kwargs)
    block = _build_table_block(tabular, caption, label)

    # No document: the library goes to outputs/<section>/ and there is no prose to hold
    # a reference, so none is appended.
    if plan is None:
        library_path = _local_section_dir(section) / library_name
        _write_table_to_library(library_path, tag, block)
        return library_path

    written = []
    for target in plan.targets:
        section_dir = target.section_dir
        library_path = section_dir / library_name
        _write_table_to_library(library_path, tag, block)
        written.append(library_path)
        if target.document is not None:
            _record_library_entry(target, plan.analysis, key, library_path, tag, notebook)

        if not add_reference:
            continue
        already = find_table_reference(section_dir, tag, exclude={library_name})
        if already is not None:
            print(f"Table '{tag}' is already pulled in by {already.name}; "
                  f"no reference appended.")
        elif tex is not False:
            library_ref = _library_reference_path(section_dir, library_name)
            reference = f"\\ExecuteMetaData[{library_ref}]{{{tag}}}"
            _append_commented_block(section_dir, reference, exclude={library_name},
                                    tex_name=None if tex is True else tex)

    return _single_or_list(written)
