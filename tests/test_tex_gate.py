"""The gate that stops re-saving a figure appending duplicate LaTeX blocks.

`save_document_figure` appends a commented-out \\begin{figure} block for a figure the
document does not reference yet. It used to do that unconditionally, so every re-run of a
notebook added another copy, and `tex=False` had to be passed everywhere to prevent it.
The append is now gated on a scan of the Chapters tree; these tests pin the behaviour
that makes the gate trustworthy enough for `tex` to default to True.

Everything here writes to tmp_path. The assertions against a real document
repo are read-only and skip when DOCUMENT_REPO is unset.
"""
import os
from pathlib import Path

import pandas as pd
import pytest

from PACKAGE_NAME import (add_commented_figure_to_tex, find_figure_reference,
                            find_table_reference, save_document_table)
from PACKAGE_NAME.save_figure import figure_reference_state

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
def chapter(tmp_path):
    """A chapter directory with one .tex holding a live and a commented figure block."""
    (tmp_path / "chapter.tex").write_text(LIVE + "\n" + COMMENTED, encoding="utf-8")
    return tmp_path


# --------------------------------------------------------------- detection

def test_live_block_is_a_reference(chapter):
    assert find_figure_reference(chapter, "already_live.png") is not None


def test_commented_block_is_a_reference(chapter):
    """The migration workflow leaves blocks commented; that is still a reference."""
    assert find_figure_reference(chapter, "already_commented.png") is not None


def test_reference_state_distinguishes_live_from_commented(chapter):
    assert figure_reference_state(chapter, "already_live.png")[0] == "live"
    assert figure_reference_state(chapter, "already_commented.png")[0] == "commented"
    assert figure_reference_state(chapter, "nowhere.png") == (None, None)


def test_unknown_figure_is_not_a_reference(chapter):
    assert find_figure_reference(chapter, "brand_new.png") is None


def test_substring_name_is_not_a_false_positive(chapter):
    """'live.png' must not match \\includegraphics{already_live.png}."""
    assert find_figure_reference(chapter, "live.png") is None


def test_extension_is_optional_in_the_source(tmp_path):
    (tmp_path / "c.tex").write_text("\\includegraphics[width=1cm]{no_ext}\n", encoding="utf-8")
    assert find_figure_reference(tmp_path, "no_ext.png") is not None


def test_label_alone_counts_as_a_reference(tmp_path):
    """A block whose \\includegraphics was renamed still owns the label."""
    (tmp_path / "c.tex").write_text("\\label{Fig: orphan_label}\n", encoding="utf-8")
    assert find_figure_reference(tmp_path, "orphan_label.png") is not None


def test_scan_reaches_other_chapters(tmp_path):
    """Figure names are unique document-wide, so a block in another chapter counts."""
    chapters = tmp_path / "Chapters"
    here = chapters / "Results" / "mine"
    there = chapters / "Method" / "theirs"
    here.mkdir(parents=True)
    there.mkdir(parents=True)
    (here / "mine.tex").write_text("", encoding="utf-8")
    (there / "theirs.tex").write_text(LIVE, encoding="utf-8")
    assert find_figure_reference(here, "already_live.png") is not None


# --------------------------------------------------------------- gating

def test_referenced_figures_are_not_appended(chapter):
    before = (chapter / "chapter.tex").read_text(encoding="utf-8")
    assert add_commented_figure_to_tex("already_live.png", chapter) is None
    assert add_commented_figure_to_tex("already_commented.png", chapter) is None
    assert (chapter / "chapter.tex").read_text(encoding="utf-8") == before


def test_new_figure_is_appended_commented(chapter):
    assert add_commented_figure_to_tex("brand_new.png", chapter, caption="New.") is not None
    appended = (chapter / "chapter.tex").read_text(encoding="utf-8").splitlines()[-6:]
    assert all(line.startswith("%") for line in appended if line.strip())


def test_resaving_does_not_append_twice(chapter):
    add_commented_figure_to_tex("brand_new.png", chapter)
    once = (chapter / "chapter.tex").read_text(encoding="utf-8")
    assert add_commented_figure_to_tex("brand_new.png", chapter) is None
    assert (chapter / "chapter.tex").read_text(encoding="utf-8") == once
    assert once.count("brand_new.png") == 1


def test_tex_false_still_suppresses_the_append(chapter):
    before = (chapter / "chapter.tex").read_text(encoding="utf-8")
    assert add_commented_figure_to_tex("another_new.png", chapter, tex=False) is None
    assert (chapter / "chapter.tex").read_text(encoding="utf-8") == before


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
    tex = tmp_path / "chapter.tex"
    tex.write_text("% \\ExecuteMetaData[Chapters/X/tables.tex]{already_pulled}\n",
                   encoding="utf-8")
    assert find_table_reference(tmp_path, "already_pulled") is not None
    assert find_table_reference(tmp_path, "other_tag") is None

    df = pd.DataFrame({"a": [1.0], "b": ["x"]})
    before = tex.read_text(encoding="utf-8")
    save_document_table(df, "already_pulled", chapter=tmp_path)
    assert tex.read_text(encoding="utf-8") == before


def test_table_snippet_is_appended_once(tmp_path):
    tex = tmp_path / "chapter.tex"
    tex.write_text("", encoding="utf-8")
    df = pd.DataFrame({"a": [1.0]})

    save_document_table(df, "fresh_tag", chapter=tmp_path)
    assert tex.read_text(encoding="utf-8").count("{fresh_tag}") == 1

    save_document_table(df, "fresh_tag", chapter=tmp_path)
    assert tex.read_text(encoding="utf-8").count("{fresh_tag}") == 1
    # The library itself replaces the tagged block in place rather than appending.
    assert (tmp_path / "tables.tex").read_text(encoding="utf-8").count("%<*fresh_tag>") == 1


# --------------------------------------------------------------- real repo

@pytest.mark.skipif(not os.environ.get("DOCUMENT_REPO"),
                    reason="DOCUMENT_REPO is not set")
def test_against_the_real_document():
    """Read-only sanity check against the actual chapter sources.

    The template ships one worked example, so this asserts on that. Once you have replaced
    the Example chapter, point this at a figure of your own that you know is placed in the
    prose — it is the only test that exercises the scan against real LaTeX rather than a
    fixture, and it is worth keeping honest.
    """
    chapters = Path(os.environ["DOCUMENT_REPO"]) / "Chapters"
    example = chapters / "Example"
    if not example.is_dir():
        pytest.skip("no Example chapter; repoint this at a chapter of your own")

    # The worked example's figure is placed in the prose, not merely commented in.
    assert figure_reference_state(example, "example_scatter.png")[0] == "live"
    # ...and a name nothing references is correctly reported as absent.
    assert figure_reference_state(example, "no_such_figure.png")[0] is None
