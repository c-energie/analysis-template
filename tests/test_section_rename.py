"""The Chapters/ -> Sections/ rename, and what still has to work after it.

The rename touches the one name shared with the document repo and the publishing
engine, so the compatibility it promises is worth pinning: a document repo laid out
before the rename must still resolve, and the old keyword spellings must still reach
the same directory. Everything here writes to tmp_path.
"""
import warnings

import pytest

from doc_analysis.save_figure import (
    LEGACY_SECTIONS_DIRNAME,
    SECTIONS_DIRNAME,
    search_root,
    section_root_name,
    sections_dir,
)


def _repo(tmp_path, *dirnames):
    """A document repo root holding each of dirnames as a section tree."""
    for name in dirnames:
        (tmp_path / name / "Example").mkdir(parents=True)
    return tmp_path


# ------------------------------------------------------- locating the tree

def test_sections_is_found(tmp_path):
    assert section_root_name(_repo(tmp_path, "Sections")) == SECTIONS_DIRNAME


def test_legacy_chapters_is_still_found(tmp_path):
    assert section_root_name(_repo(tmp_path, "Chapters")) == LEGACY_SECTIONS_DIRNAME


def test_sections_wins_over_a_leftover_chapters(tmp_path):
    """A half-finished rename must resolve to the new tree, not to either one."""
    assert section_root_name(_repo(tmp_path, "Sections", "Chapters")) == SECTIONS_DIRNAME


def test_neither_tree_is_not_a_document_repo(tmp_path):
    assert section_root_name(tmp_path) is None


def test_sections_dir_follows_a_legacy_repo(tmp_path, monkeypatch):
    monkeypatch.setenv("DOC_REPO", str(_repo(tmp_path, "Chapters")))
    assert sections_dir() == tmp_path / "Chapters"


def test_a_repo_with_neither_tree_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("DOC_REPO", str(tmp_path))
    with pytest.raises(NotADirectoryError, match=SECTIONS_DIRNAME):
        sections_dir()


# ------------------------------------------------------- widening the scan

@pytest.mark.parametrize("root", [SECTIONS_DIRNAME, LEGACY_SECTIONS_DIRNAME])
def test_scan_widens_to_either_root(tmp_path, root):
    """Figure names are unique document-wide, so the scan must climb to the tree root."""
    leaf = tmp_path / root / "Results" / "mine"
    leaf.mkdir(parents=True)
    assert search_root(leaf) == tmp_path / root


def test_scan_falls_back_to_a_standalone_directory(tmp_path):
    assert search_root(tmp_path) == tmp_path


# ------------------------------------------------------ deprecated spellings

def test_chapter_keyword_still_resolves_and_warns(tmp_path):
    from doc_analysis import save_document_table

    import pandas as pd

    (tmp_path / "section.tex").write_text("", encoding="utf-8")
    df = pd.DataFrame({"a": [1]})
    with pytest.warns(DeprecationWarning, match="chapter="):
        library = save_document_table(df, "legacy_tag", chapter=tmp_path)
    assert library == tmp_path / "tables.tex"


def test_passing_both_spellings_raises(tmp_path):
    from doc_analysis import save_document_table

    import pandas as pd

    with pytest.raises(TypeError, match="not both"):
        save_document_table(pd.DataFrame({"a": [1]}), "t",
                            section=tmp_path, chapter=tmp_path)


def test_section_keyword_is_silent(tmp_path):
    """The new spelling must not warn — otherwise the warning channel gets ignored."""
    from doc_analysis import save_document_table

    import pandas as pd

    (tmp_path / "section.tex").write_text("", encoding="utf-8")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        save_document_table(pd.DataFrame({"a": [1]}), "fresh_tag", section=tmp_path)
    assert [str(w.message) for w in caught] == []
