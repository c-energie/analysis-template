import re
from pathlib import Path

import pandas as pd

from PACKAGE_NAME.save_figure import (
    _append_commented_block,
    _resolve_chapter_dir,
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


def find_table_reference(chapter_dir, tag, exclude=()):
    """The .tex file in chapter_dir that already pulls in table *tag*, or None.

    Matches \\ExecuteMetaData[<any library path>]{tag} whether commented or live, so the
    path spelling (bare ``tables.tex`` or repo-root-relative) does not matter. Mirrors
    find_figure_reference: re-saving a table must not accumulate reference snippets.
    """
    pattern = re.compile(r"\\ExecuteMetaData\s*\[[^\]]*\]\s*\{\s*" + re.escape(tag) + r"\s*\}")
    exclude = set(exclude)
    for tex_path in sorted(Path(chapter_dir).glob("*.tex")):
        if tex_path.name in exclude:
            continue
        for raw_line in tex_path.read_text(encoding="utf-8").splitlines():
            if pattern.search(raw_line.lstrip().lstrip("%").strip()):
                return tex_path
    return None


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
    """Insert (or replace) a tagged table block in the shared library .tex file.

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
    print(f"{action} table '{tag}' in: {library_path}")
    return library_path


def save_document_table(df, name, caption=None, label=None, chapters_root=None,
                      library_name=LIBRARY_NAME, add_reference=True, index=False,
                      decimals=2, escape=False, column_format=None, *, chapter=None,
                      tex=None, **to_latex_kwargs):
    """Save a DataFrame as a LaTeX table into a per-leaf shared table library file.

    The chapter directory is chosen interactively unless chapter is given (a path
    relative to $DOC_REPO/Chapters, e.g. "Results/ptg_application"); tex names
    the .tex file that receives the commented reference, so unattended notebook runs
    never prompt. The DataFrame is
    rendered with dataframe_to_latex (booktabs, fixed decimals, aligned columns) and wrapped
    in a full \\begin{table} environment, which is written into a single shared library file
    (library_name, e.g. tables.tex) placed directly in the chosen leaf directory under a
    catchfilebetweentags tag taken from name. Re-saving the same name replaces that table in
    place rather than adding a duplicate, so one file accumulates all of the leaf
    directory's tables.

    Pull an individual table into the prose with \\ExecuteMetaData[tables.tex]{name}
    (requires \\usepackage{catchfilebetweentags}). When add_reference is True that command is
    appended, commented out, to a .tex file in the chosen directory as a ready-to-place
    snippet — but only if no .tex in the chapter pulls the tag in already (commented or
    live), so re-saving never accumulates duplicate snippets. tex names the target file,
    tex=False suppresses the snippet, and several candidate .tex files raise rather than
    prompt. caption defaults to a TODO placeholder and label to name (giving
    \\label{Tab: <name>}). index, decimals, escape, column_format and any extra keyword
    arguments are forwarded to dataframe_to_latex. Returns the library file Path.
    """
    chapter_dir = _resolve_chapter_dir(chapter, chapters_root)
    library_path = chapter_dir / library_name

    tag = Path(name).stem
    caption = caption if caption is not None else "TODO: caption"
    label = label if label is not None else tag

    tabular = dataframe_to_latex(df, index=index, decimals=decimals, escape=escape,
                                 column_format=column_format, **to_latex_kwargs)
    block = _build_table_block(tabular, caption, label)
    _write_table_to_library(library_path, tag, block)

    if add_reference:
        already = find_table_reference(chapter_dir, tag, exclude={library_name})
        if already is not None:
            print(f"Table '{tag}' is already pulled in by {already.name}; "
                  f"no reference appended.")
        elif tex is not False:
            reference = f"\\ExecuteMetaData[{library_name}]{{{tag}}}"
            _append_commented_block(chapter_dir, reference, exclude={library_name},
                                    tex_name=None if tex is True else tex)

    return library_path
