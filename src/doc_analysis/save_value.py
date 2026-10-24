"""Save a computed scalar into the document as a LaTeX macro.

A number quoted in the prose is a result, and a result typed in by hand drifts from the
analysis the first time the notebook is re-run on new data. So the prose says
\\ptgMlrAgreement rather than 0.87, and the number lives in the section's values.tex,
written here::

    save_value(0.873, "ptg_mlr_agreement", decimals=2)

    %<*ptg_mlr_agreement>
    % written by save_value; edit the notebook, not this file
    \\providecommand{\\ptgMlrAgreement}{}
    \\renewcommand{\\ptgMlrAgreement}{0.87}
    %</ptg_mlr_agreement>

values.tex is a library like a section's tables.tex: one tagged block per value, and
re-saving a name replaces its block in place. \\providecommand then \\renewcommand is
deliberate: \\newcommand fails the second time the file is input, and \\providecommand
alone would keep whichever value was defined first.

The document loads each section's values.tex once, from its root settings file (the one
holding \\graphicspath), with one \\InputIfFileExists line per section — writing-template's
convention. That file is hand-edited and never touched here: a save only warns, with the
exact line to add, when the line is missing.
"""

import math
import re
import warnings
from pathlib import Path

from doc_analysis.save_figure import (
    LEGACY_SECTIONS_DIRNAME,
    SECTIONS_DIRNAME,
    _append_commented_block,
    _local_section_dir,
    _one_of,
    _resolve_save_target,
    search_root,
)
from doc_analysis.save_table import _write_tagged_block

LIBRARY_NAME = "values.tex"
#: The root settings file writing-template keeps \graphicspath in, and the values lines.
SETTINGS_NAME = "document_settings.sty"
PERCENT = "percent"

_DIGIT_WORDS = ("Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight",
                "Nine")
# A name is also the catchfilebetweentags tag and the figures_config.toml key, so it is
# held to characters all three accept unchanged; entry_name() would cut "a.b" to "a".
_NAME_RE = re.compile(r"[A-Za-z0-9_-]+")


def check_value_name(name):
    """Raise unless *name* is a usable value name.

    The worker takes (name, value) and the notebook saver (value, name), so a call with the
    two swapped is the easy mistake; a number where the name belongs raises here instead
    of being saved under a tag called 0.873.
    """
    if not isinstance(name, str):
        raise TypeError(f"value name must be a string, got {type(name).__name__} "
                        f"{name!r}; are the value and the name swapped?")
    if not _NAME_RE.fullmatch(name):
        raise ValueError(f"value name {name!r}: letters, digits, '_' and '-' only "
                         f"(it is the values.tex tag and the figures_config.toml key).")


def macro_name(name):
    """The lower-camel-case TeX macro for a snake_case value name, without the backslash.

    TeX control words are letters only, so digits are spelled out, each as a capitalised
    word: "ptg_mlr_agreement" -> "ptgMlrAgreement", "cv_rmse_20" -> "cvRmseTwoZero".
    """
    words = []
    for part in re.split(r"[^A-Za-z0-9]+", name):
        for run in re.findall(r"[A-Za-z]+|[0-9]", part):
            words.append(_DIGIT_WORDS[int(run)] if run.isdigit() else run.capitalize())
    if not words:
        raise ValueError(f"value name {name!r} gives no macro name; pass macro=.")
    return words[0].lower() + "".join(words[1:])


def _check_macro(macro):
    """The override with any leading backslash dropped, refused unless it is letters only."""
    macro = macro.lstrip("\\")
    if not re.fullmatch(r"[A-Za-z]+", macro):
        raise ValueError(f"macro={macro!r}: a TeX macro name is letters only.")
    return macro


def format_value(value, fmt=None, decimals=2, unit=None, scale=None, signed=False):
    """Render *value* as the LaTeX the macro expands to.

    A string passes through unchanged, so a value already formatted (or not a number at
    all) can still go through save_value. Otherwise: scale multiplies the value first;
    fmt="percent" multiplies by 100 unless scale is given and appends \\%; decimals sets
    the decimal places (None leaves Python's shortest form); signed=True writes the sign
    in math mode, $+x$ or $-x$; unit is appended after a thin space, \\,.
    """
    if isinstance(value, str):
        return value
    if fmt not in (None, PERCENT):
        raise ValueError(f"fmt={fmt!r}: use None or {PERCENT!r}.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"value {value!r} is neither a number nor a string.") from exc
    # A failed computation is NaN, not an exception; written through, the prose would read
    # "nan" in the compiled document with nothing having complained.
    if not math.isfinite(number):
        raise ValueError(f"value {value!r} is not finite; pass a string to write it as text.")

    if scale is None and fmt == PERCENT:
        scale = 100
    if scale is not None:
        number *= scale

    text = f"{number:.{decimals}f}" if decimals is not None else f"{number:g}"
    # A value that rounds to zero must not print as -0.00, signed or not.
    if text.startswith("-") and float(text) == 0:
        text = text[1:]
    if signed:
        text = f"${text}$" if text.startswith("-") else f"$+{text}$"
    if fmt == PERCENT:
        text += "\\%"
    if unit:
        text += f"\\,{unit}"
    return text


def _build_value_block(macro, rendered, notebook=None):
    """The macro definition that goes inside the value's tagged block."""
    source = f" by {notebook}" if notebook else ""
    return (
        f"% written by save_value{source}; edit the notebook, not this file\n"
        f"\\providecommand{{\\{macro}}}{{}}\n"
        f"\\renewcommand{{\\{macro}}}{{{rendered}}}"
    )


def _refuse_macro_clash(library_path, tag, macro):
    """Raise when another tag in the library already defines *macro*.

    "a_b" and "a__b" are two tags but one macro; both blocks would be loaded and the later
    one would silently win in the prose.
    """
    if not library_path.exists():
        return
    content = library_path.read_text(encoding="utf-8")
    own = re.compile(re.escape(f"%<*{tag}>") + r".*?" + re.escape(f"%</{tag}>"), re.DOTALL)
    defines = re.compile(r"\\renewcommand\{\\" + re.escape(macro) + r"\}")
    if defines.search(own.sub("", content)):
        raise ValueError(f"\\{macro} is already defined by another value in {library_path}; "
                         f"rename this value or pass macro=.")


def find_value_reference(section_dir, macro, exclude=(LIBRARY_NAME,)):
    """The .tex file in section_dir that already uses \\<macro>, commented or live, or None.

    A commented use counts, as it does for figures and tables, so that the hint appended
    on the first save is what stops a second one being appended on the next.
    """
    pattern = re.compile(r"\\" + re.escape(macro) + r"(?![A-Za-z])")
    exclude = set(exclude)
    for tex_path in sorted(Path(section_dir).glob("*.tex")):
        if tex_path.name in exclude:
            continue
        if pattern.search(tex_path.read_text(encoding="utf-8", errors="replace")):
            return tex_path
    return None


def _live_lines(text):
    """The lines of a LaTeX source that are not comments."""
    return (line for line in text.splitlines() if not line.lstrip().startswith("%"))


def check_values_loaded(section_dir, library_name=LIBRARY_NAME):
    """Warn when the document's root settings do not load this section's values.tex.

    A macro used in the prose but never loaded fails the build as an undefined control
    sequence, which is loud; the warning is here so it says the fix, the exact line to add,
    on the save rather than at the next compile. The preamble is hand-edited (like
    \\graphicspath) and is never written to. Returns the missing line, or None when it is
    present or there is no document root to look in — a section that sits under no
    Sections/ directory, which is what a test's temporary section is.
    """
    sections_root = search_root(section_dir)
    if sections_root.name not in (SECTIONS_DIRNAME, LEGACY_SECTIONS_DIRNAME):
        return None
    doc_root = sections_root.parent
    relative = (Path(section_dir).resolve().relative_to(doc_root.resolve())
                / library_name).as_posix()
    line = f"\\InputIfFileExists{{{relative}}}{{}}{{}}"

    # Accept the line in any root-level file, so a document that loads it from main.tex
    # rather than the settings file is not nagged; only a live line counts.
    # \input{.../values} without the extension is how LaTeX is usually written, and loads
    # the same file; not accepting it would warn about a document that is fine.
    loads = re.compile(r"\\(?:InputIfFileExists|input)\s*\{\s*(?:\./)?"
                       + re.escape(relative.removesuffix(".tex")) + r"(?:\.tex)?\s*\}")
    candidates = sorted([*doc_root.glob("*.sty"), *doc_root.glob("*.tex")])
    for path in candidates:
        if any(loads.search(l) for l in _live_lines(path.read_text(encoding="utf-8",
                                                                     errors="replace"))):
            return None

    settings = doc_root / SETTINGS_NAME
    if not settings.exists():
        settings = next((p for p in candidates if any(
            "\\graphicspath" in l for l in _live_lines(
                p.read_text(encoding="utf-8", errors="replace")))), None)
    where = (f"{settings.name}, next to \\graphicspath" if settings is not None
             else f"the root settings file of {doc_root} (the one holding \\graphicspath)")
    warnings.warn(f"{relative} is not loaded by the document, so its macros are undefined "
                  f"in the prose. Add this line to {where}:\n    {line}", stacklevel=3)
    return line


def save_document_value(name, value, fmt=None, decimals=2, unit=None, scale=None,
                        signed=False, macro=None, *, section=None, tex=None,
                        sections_root=None, library_name=LIBRARY_NAME,
                        add_reference=True, notebook=None, chapter=None,
                        chapters_root=None):
    """Write *value* into the section's values.tex as the macro for *name*.

    The section is a path relative to $DOC_REPO/Sections or an absolute path, as for
    save_document_figure. name is snake_case and gives both the tag and, via macro_name,
    the macro — macro= overrides the latter. fmt, decimals, unit, scale and signed are
    format_value's. Re-saving a name replaces its block rather than adding a second.

    When add_reference is True and no .tex in the section but the library uses the macro
    yet, a commented \\<macro> is appended as a ready-to-place snippet, by the same
    mechanism and with the same tex= target (tex=False to skip) as a figure's block. The
    document's root settings are then checked for the line that loads values.tex, with a
    warning if it is missing. Returns the library file Path.

    chapter= and chapters_root= are the pre-rename spellings of section= and
    sections_root=. They still work and warn; passing both spellings raises.

    With no document configured, a relative section's values.tex is written to
    `outputs/<section>/` in the active checkout instead; nothing else is touched.
    """
    check_value_name(name)
    section = _one_of("section", section, "chapter", chapter)
    sections_root = _one_of("sections_root", sections_root, "chapters_root", chapters_root)
    section_dir = _resolve_save_target(section, sections_root)
    # No document: values.tex goes to outputs/<section>/, with no reference to append and
    # no preamble to check for the line that loads it.
    in_document = section_dir is not None
    if not in_document:
        section_dir = _local_section_dir(section)
    library_path = section_dir / library_name

    macro = _check_macro(macro) if macro is not None else macro_name(name)
    rendered = format_value(value, fmt=fmt, decimals=decimals, unit=unit, scale=scale,
                            signed=signed)
    _refuse_macro_clash(library_path, name, macro)
    _write_tagged_block(library_path, name, _build_value_block(macro, rendered, notebook),
                        kind="value")

    if not in_document:
        return library_path

    if add_reference:
        already = find_value_reference(section_dir, macro, exclude={library_name})
        if already is not None:
            print(f"\\{macro} is already used in {already.name}; no reference appended.")
        elif tex is not False:
            _append_commented_block(section_dir, f"\\{macro}", exclude={library_name},
                                    tex_name=None if tex in (None, True) else tex)

    check_values_loaded(section_dir, library_name)
    return library_path
