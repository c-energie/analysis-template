"""The gate that stops re-saving a figure appending duplicate LaTeX blocks.

`save_document_figure` appends a commented-out \\begin{figure} block for a figure the
document does not reference yet. It used to do that unconditionally, so every re-run of a
notebook added another copy, and `tex=False` had to be passed everywhere to prevent it.
The append is now gated on a scan of the Sections tree; these tests pin the behaviour
that makes the gate trustworthy enough for `tex` to default to True.

Everything here writes to tmp_path. The assertions against a real document
repo are read-only and skip when DOC_REPO is unset.
"""
import os
from pathlib import Path

import pandas as pd
import pytest

from doc_analysis import (add_commented_figure_to_tex, find_figure_reference,
                            find_table_reference, save_document_table)
from doc_analysis.save_figure import figure_reference_state

LIVE = """\\begin{figure}[H]
    \\centering
    \\includegraphics[width=\\width]{already_live.png}
    \\caption{A figure already placed in the prose.}
    \\label{Fig: already_live}
\\end{figure}
"""

COMMENTED = """% [TODO: uncomment when the prose lands]
% \\begin{figure}[H]
%     \\centering
%     \\includegraphics[width=\\width]{already_commented.png}
%     \\caption{Not yet placed.}
%     \\label{Fig: already_commented}
% \\end{figure}
"""


@pytest.fixture
def section(tmp_path):
    """A section directory with one .tex holding a live and a commented figure block."""
    (tmp_path / "section.tex").write_text(LIVE + "\n" + COMMENTED, encoding="utf-8")
    return tmp_path


# --------------------------------------------------------------- detection

def test_live_block_is_a_reference(section):
    assert find_figure_reference(section, "already_live.png") is not None


def test_commented_block_is_a_reference(section):
    """The migration workflow leaves blocks commented; that is still a reference."""
    assert find_figure_reference(section, "already_commented.png") is not None


def test_reference_state_distinguishes_live_from_commented(section):
    assert figure_reference_state(section, "already_live.png")[0] == "live"
    assert figure_reference_state(section, "already_commented.png")[0] == "commented"
    assert figure_reference_state(section, "nowhere.png") == (None, None)


def test_unknown_figure_is_not_a_reference(section):
    assert find_figure_reference(section, "brand_new.png") is None


def test_substring_name_is_not_a_false_positive(section):
    """'live.png' must not match \\includegraphics{already_live.png}."""
    assert find_figure_reference(section, "live.png") is None


def test_extension_is_optional_in_the_source(tmp_path):
    (tmp_path / "c.tex").write_text("\\includegraphics[width=1cm]{no_ext}\n", encoding="utf-8")
    assert find_figure_reference(tmp_path, "no_ext.png") is not None


def test_label_alone_counts_as_a_reference(tmp_path):
    """A block whose \\includegraphics was renamed still owns the label."""
    (tmp_path / "c.tex").write_text("\\label{Fig: orphan_label}\n", encoding="utf-8")
    assert find_figure_reference(tmp_path, "orphan_label.png") is not None


def test_scan_reaches_other_sections(tmp_path):
    """Figure names are unique document-wide, so a block in another section counts."""
    sections = tmp_path / "Sections"
    here = sections / "Results" / "mine"
    there = sections / "Method" / "theirs"
    here.mkdir(parents=True)
    there.mkdir(parents=True)
    (here / "mine.tex").write_text("", encoding="utf-8")
    (there / "theirs.tex").write_text(LIVE, encoding="utf-8")
    assert find_figure_reference(here, "already_live.png") is not None


# --------------------------------------------------------------- gating

def test_referenced_figures_are_not_appended(section):
    before = (section / "section.tex").read_text(encoding="utf-8")
    assert add_commented_figure_to_tex("already_live.png", section) is None
    assert add_commented_figure_to_tex("already_commented.png", section) is None
    assert (section / "section.tex").read_text(encoding="utf-8") == before


def test_new_figure_is_appended_commented(section):
    assert add_commented_figure_to_tex("brand_new.png", section, caption="New.") is not None
    appended = (section / "section.tex").read_text(encoding="utf-8").splitlines()[-6:]
    assert all(line.startswith("%") for line in appended if line.strip())


def test_resaving_does_not_append_twice(section):
    add_commented_figure_to_tex("brand_new.png", section)
    once = (section / "section.tex").read_text(encoding="utf-8")
    assert add_commented_figure_to_tex("brand_new.png", section) is None
    assert (section / "section.tex").read_text(encoding="utf-8") == once
    assert once.count("brand_new.png") == 1


def test_tex_false_still_suppresses_the_append(section):
    before = (section / "section.tex").read_text(encoding="utf-8")
    assert add_commented_figure_to_tex("another_new.png", section, tex=False) is None
    assert (section / "section.tex").read_text(encoding="utf-8") == before


# --------------------------------------------------------------- ambiguity

def test_several_tex_files_raise_rather_than_prompt(tmp_path):
    """An input() here would hang an unattended notebook run."""
    (tmp_path / "one.tex").write_text("", encoding="utf-8")
    (tmp_path / "two.tex").write_text("", encoding="utf-8")
    with pytest.raises(RuntimeError) as excinfo:
        add_commented_figure_to_tex("brand_new.png", tmp_path)
    assert "one.tex" in str(excinfo.value) and "two.tex" in str(excinfo.value)


def test_explicit_tex_resolves_the_ambiguity(tmp_path):
    (tmp_path / "one.tex").write_text("", encoding="utf-8")
    (tmp_path / "two.tex").write_text("", encoding="utf-8")
    written = add_commented_figure_to_tex("brand_new.png", tmp_path, tex="two.tex")
    assert written.name == "two.tex"


# --------------------------------------------------------------- tables

def test_table_reference_gate(tmp_path):
    """\\ExecuteMetaData matches on the tag, whatever the library path spelling."""
    tex = tmp_path / "section.tex"
    tex.write_text("% \\ExecuteMetaData[Sections/X/tables.tex]{already_pulled}\n",
                   encoding="utf-8")
    assert find_table_reference(tmp_path, "already_pulled") is not None
    assert find_table_reference(tmp_path, "other_tag") is None

    df = pd.DataFrame({"a": [1.0], "b": ["x"]})
    before = tex.read_text(encoding="utf-8")
    save_document_table(df, "already_pulled", section=tmp_path)
    assert tex.read_text(encoding="utf-8") == before


def test_table_snippet_is_appended_once(tmp_path):
    tex = tmp_path / "section.tex"
    tex.write_text("", encoding="utf-8")
    df = pd.DataFrame({"a": [1.0]})

    save_document_table(df, "fresh_tag", section=tmp_path)
    assert tex.read_text(encoding="utf-8").count("{fresh_tag}") == 1

    save_document_table(df, "fresh_tag", section=tmp_path)
    assert tex.read_text(encoding="utf-8").count("{fresh_tag}") == 1
    # The library itself replaces the tagged block in place rather than appending.
    assert (tmp_path / "tables.tex").read_text(encoding="utf-8").count("%<*fresh_tag>") == 1


def test_table_snippet_path_is_relative_to_the_document_root(tmp_path):
    """Sections are \\subfile-d into main.tex, so TeX resolves the library path from the
    document root: a bare `tables.tex` rendered nothing in the full build (issue #23)."""
    section = tmp_path / "doc" / "Sections" / "Results" / "ptg"
    section.mkdir(parents=True)
    tex = section / "ptg.tex"
    tex.write_text("", encoding="utf-8")

    save_document_table(pd.DataFrame({"a": [1.0]}), "fresh_tag", section=section)
    text = tex.read_text(encoding="utf-8")
    assert "\\ExecuteMetaData[Sections/Results/ptg/tables.tex]{fresh_tag}" in text
    assert "[tables.tex]" not in text


def test_table_snippet_path_in_a_pre_rename_document(tmp_path):
    """A document still laid out under Chapters/ gets the path it actually has."""
    section = tmp_path / "doc" / "Chapters" / "Intro"
    section.mkdir(parents=True)
    tex = section / "intro.tex"
    tex.write_text("", encoding="utf-8")

    save_document_table(pd.DataFrame({"a": [1.0]}), "fresh_tag", section=section)
    assert ("\\ExecuteMetaData[Chapters/Intro/tables.tex]{fresh_tag}"
            in tex.read_text(encoding="utf-8"))


def test_table_snippet_outside_a_document_keeps_the_bare_name(tmp_path):
    """With no Sections/ ancestor there is no document root to be relative to."""
    tex = tmp_path / "section.tex"
    tex.write_text("", encoding="utf-8")
    save_document_table(pd.DataFrame({"a": [1.0]}), "fresh_tag", section=tmp_path)
    assert "\\ExecuteMetaData[tables.tex]{fresh_tag}" in tex.read_text(encoding="utf-8")


# --------------------------------------------------------------- \end{document}

SUBFILE = ("\\documentclass[../../main.tex]{subfiles}\n"
           "\\begin{document}\n"
           "Last paragraph of the section.\n"
           "\\end{document}\n")


def _write_bytes(path, text):
    """Write exactly these bytes: write_text would translate \n to CRLF on Windows."""
    path.write_bytes(text.encode("utf-8"))
    return path


def test_subfile_block_goes_before_end_document(tmp_path):
    """LaTeX ignores everything after \\end{document}: a block appended there would be
    uncommented by the author and then silently never render (issue #4)."""
    tex = _write_bytes(tmp_path / "section.tex", SUBFILE)
    add_commented_figure_to_tex("brand_new.png", tmp_path, caption="New.")
    text = tex.read_bytes().decode("utf-8")
    assert text.index("brand_new.png") < text.index("\\end{document}")
    assert text.rstrip("\n").splitlines()[-1] == "\\end{document}"
    # One blank line above the block and one below it, before \end{document}.
    assert "Last paragraph of the section.\n\n% \\begin{figure}[H]\n" in text
    assert text.endswith("% \\end{figure}\n\n\\end{document}\n")


def test_subfile_table_reference_goes_before_end_document(tmp_path):
    """save_document_table shares the helper, so its \\ExecuteMetaData line had the same bug."""
    tex = _write_bytes(tmp_path / "section.tex", SUBFILE)
    save_document_table(pd.DataFrame({"a": [1.0]}), "fresh_tag", section=tmp_path)
    text = tex.read_bytes().decode("utf-8")
    assert text.index("{fresh_tag}") < text.index("\\end{document}")
    assert text.rstrip("\n").splitlines()[-1] == "\\end{document}"


def test_successive_blocks_stay_before_end_document_in_order(tmp_path):
    """The second block must not be placed after \\end{document} by the first one's
    commented `% \\end{figure}` lines, nor ahead of the first block."""
    tex = _write_bytes(tmp_path / "section.tex", SUBFILE)
    add_commented_figure_to_tex("first.png", tmp_path)
    add_commented_figure_to_tex("second.png", tmp_path)
    text = tex.read_bytes().decode("utf-8")
    assert text.index("first.png") < text.index("second.png") < text.index("\\end{document}")
    assert "% \\end{figure}\n\n% \\begin{figure}[H]" in text
    assert text.endswith("% \\end{figure}\n\n\\end{document}\n")


def test_commented_end_document_is_not_an_insertion_point(tmp_path):
    """A `% \\end{document}` ends nothing, so the block is appended as for a plain fragment."""
    tex = _write_bytes(tmp_path / "section.tex", "Some prose.\n% \\end{document}\n")
    add_commented_figure_to_tex("brand_new.png", tmp_path)
    text = tex.read_bytes().decode("utf-8")
    assert text.startswith("Some prose.\n% \\end{document}\n\n% \\begin{figure}[H]")
    assert text.endswith("% \\end{figure}\n")


def test_last_live_end_document_wins(tmp_path):
    """Only the last live \\end{document} is the end of what LaTeX reads."""
    tex = _write_bytes(tmp_path / "section.tex",
                       "\\begin{document}\nA\n\\end{document}\nB\n  \\end{document}\n")
    add_commented_figure_to_tex("brand_new.png", tmp_path)
    text = tex.read_bytes().decode("utf-8")
    assert text.startswith("\\begin{document}\nA\n\\end{document}\nB\n\n% \\begin{figure}")
    assert text.endswith("% \\end{figure}\n\n  \\end{document}\n")


def test_fragment_without_end_document_is_appended_as_before(tmp_path):
    """A plain \\input fragment keeps the old placement exactly."""
    tex = _write_bytes(tmp_path / "section.tex", "Some prose.\n")
    add_commented_figure_to_tex("brand_new.png", tmp_path, caption="New.", label="new")
    assert tex.read_bytes().decode("utf-8") == (
        "Some prose.\n"
        "\n"
        "% \\begin{figure}[H]\n"
        "%     \\centering\n"
        "%     \\includegraphics[width=\\width]{brand_new.png}\n"
        "%     \\caption{New.}\n"
        "%     \\label{Fig: new}\n"
        "% \\end{figure}\n")


def test_text_after_end_document_is_preserved(tmp_path):
    """Trailing blank lines (or anything else) after \\end{document} come back unchanged."""
    tail = "\\end{document}\n\n\n% trailing note\n"
    tex = _write_bytes(tmp_path / "section.tex", "Prose.\n" + tail)
    add_commented_figure_to_tex("brand_new.png", tmp_path)
    assert tex.read_bytes().decode("utf-8").endswith("% \\end{figure}\n\n" + tail)


def test_crlf_file_keeps_crlf_line_endings(tmp_path):
    """The whole file is rewritten; a CRLF document must not come back half LF."""
    tex = _write_bytes(tmp_path / "section.tex", SUBFILE.replace("\n", "\r\n"))
    add_commented_figure_to_tex("brand_new.png", tmp_path)
    raw = tex.read_bytes().decode("utf-8")
    assert "brand_new.png" in raw
    assert "\n" not in raw.replace("\r\n", "")
    assert raw.startswith(SUBFILE.replace("\n", "\r\n").split("\\end{document}")[0].rstrip())
    assert raw.endswith("% \\end{figure}\r\n\r\n\\end{document}\r\n")


def test_crlf_fragment_keeps_crlf_line_endings(tmp_path):
    """The append branch wrote the block in the platform's endings, not the file's: an LF
    section on Windows came back with a CRLF block, and a CRLF one elsewhere with an LF
    block -- mixed endings either way (issue #17)."""
    tex = _write_bytes(tmp_path / "section.tex", "Some prose.\r\n")
    add_commented_figure_to_tex("brand_new.png", tmp_path)
    raw = tex.read_bytes().decode("utf-8")
    assert "\n" not in raw.replace("\r\n", "")
    assert raw.startswith("Some prose.\r\n\r\n% \\begin{figure}[H]\r\n")
    assert raw.endswith("% \\end{figure}\r\n")


def test_crlf_fragment_ending_in_blank_line_gets_no_extra_one(tmp_path):
    """A CRLF file already ending in a blank line ends in \\r\\n\\r\\n, which a check for
    "\\n\\n" misses: the block would be appended after two blank lines instead of one."""
    tex = _write_bytes(tmp_path / "section.tex", "Some prose.\r\n\r\n")
    add_commented_figure_to_tex("brand_new.png", tmp_path)
    raw = tex.read_bytes().decode("utf-8")
    assert raw.startswith("Some prose.\r\n\r\n% \\begin{figure}[H]\r\n")


# --------------------------------------------------------------- real repo

@pytest.mark.skipif(not os.environ.get("DOC_REPO"),
                    reason="DOC_REPO is not set")
def test_against_the_real_document():
    """Read-only sanity check against the actual section sources.

    The template ships one worked example, so this asserts on that. Once you have replaced
    the Example section, point this at a figure of your own that you know is placed in the
    prose — it is the only test that exercises the scan against real LaTeX rather than a
    fixture, and it is worth keeping honest.
    """
    sections = Path(os.environ["DOC_REPO"]) / "Sections"
    example = sections / "Example"
    if not example.is_dir():
        pytest.skip("no Example section; repoint this at a section of your own")

    # The worked example's figure is placed in the prose, not merely commented in.
    assert figure_reference_state(example, "example_scatter.png")[0] == "live"
    # ...and a name nothing references is correctly reported as absent.
    assert figure_reference_state(example, "no_such_figure.png")[0] is None
