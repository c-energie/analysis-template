"""Target documents: a workspace analysis writing into several documents (issue #25).

A temporary project workspace stands in for a real one: `.claude/workspace.json` at its
root, written in the schema claude-tools ADR 0002 and #41 define, two documents (`thesis`,
`paper`), two workspace analyses (`validation`, feeding both; `survey`, feeding `thesis`)
and a nested analysis inside `thesis`, placed by the host's `layout.toml`. What is worth
pinning, each the failure it prevents:

- every target gets the PNG, the commented block and a manifest entry naming its owner,
  and `documents=` can narrow that but never add a document;
- every target is checked before any is written, so a save cannot land in one document
  and fail in the next;
- a name another analysis owns in a document is refused, never renamed, until the owner
  gives it up — deleting the PNG or block, then `check-figure-parity --prune`;
- `DOC_REPO` may agree with the structure but never contradict it, and `documents = []`
  is no-document mode;
- the manifest moves from `figures_html/` into the document once, without duplicates;
- parity runs per analysis over all its targets, and `--figures` over a document's union.

Figures are stubs and the PNGs bare headers; no backend is imported.
"""
import json
import os
import struct
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from doc_analysis import env, notebook_savers, save_figure
from doc_analysis.manifest import MANIFEST_NAME, OwnershipError, write_manifest
from doc_analysis.parity import main as parity_main
from doc_analysis.save_figure import document_repo, target_documents
from doc_analysis.workspace import find_workspace_analysis

SECTION = "Results/ptg"


def png_bytes(width=1125, height=720):
    return (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR"
            + struct.pack(">II", width, height))


class FakePlotlyFigure:
    """Duck-types what the saver asks of a plotly Figure — and nothing else."""

    def __init__(self, width=1125, height=720):
        self.data = [SimpleNamespace(hovertemplate="%{x}")]
        self.size = (width, height)
        self.renders = 0

    def write_image(self, path, **kwargs):
        self.renders += 1
        Path(path).write_bytes(png_bytes(*self.size))

    def write_html(self, path, **kwargs):
        Path(path).write_text("<html>fake</html>", encoding="utf-8")


class FakeMatplotlibFigure:
    def savefig(self, path, **kwargs):
        Path(path).write_bytes(png_bytes())


def make_checkout(path):
    (path / "src" / "doc_analysis").mkdir(parents=True)
    (path / "notebooks").mkdir()
    (path / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    return path


def make_document(path):
    section = path / "Sections" / SECTION
    section.mkdir(parents=True)
    (section / "ptg.tex").write_text("Prose.\n", encoding="utf-8")
    # Loads the section's values.tex, so a value save has nothing to warn about.
    (path / "document_settings.sty").write_text(
        f"\\graphicspath{{}}\n\\InputIfFileExists{{Sections/{SECTION}/values.tex}}{{}}{{}}\n",
        encoding="utf-8")
    return path


def write_workspace(root, validation_documents=("thesis", "paper")):
    """The shape setup_workspace.py writes; keys this package does not read included."""
    data = {
        "schema": 1, "name": "my-phd", "repo": "me/my-phd",
        "members": [
            {"dir": "thesis", "repo": "me/thesis", "kind": "document", "name": "thesis",
             "extras": ["dev", "notebooks", "plotly"]},
            {"dir": "thesis/thesis-analysis", "repo": "me/thesis-analysis",
             "kind": "analysis", "documents": ["thesis"]},
            {"dir": "paper", "repo": "me/paper", "kind": "document", "name": "paper"},
            {"dir": "validation", "repo": "me/validation", "kind": "analysis",
             "documents": list(validation_documents), "extras": ["dev", "plotly"]},
            {"dir": "survey", "repo": "me/survey", "kind": "analysis",
             "documents": ["thesis"]},
        ],
        "connections": {"slack": {"channel": "x"}},
        "state": {"notion": {}},
    }
    (root / ".claude").mkdir(exist_ok=True)
    (root / ".claude" / "workspace.json").write_text(json.dumps(data, indent=2),
                                                     encoding="utf-8")


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = (tmp_path / "my-phd").resolve()
    root.mkdir()
    thesis = make_document(root / "thesis")
    paper = make_document(root / "paper")
    validation = make_checkout(root / "validation")
    survey = make_checkout(root / "survey")
    nested = make_checkout(thesis / "thesis-analysis")
    (thesis / "layout.toml").write_text(
        'layout = "writing-hosts-analysis"\nnested_dir = "thesis-analysis"\n',
        encoding="utf-8")
    write_workspace(root)

    monkeypatch.setattr(os, "environ", dict(os.environ))
    for name in ("DOC_REPO", "DOC_ENV", "FIGURES_HTML_DIR", "FIGURES_CONFIG"):
        os.environ.pop(name, None)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setitem(env.LAST_SEARCH, "fallback", None)
    monkeypatch.setitem(save_figure._NO_DOCUMENT_NOTICE, "shown", False)
    monkeypatch.setitem(sys.modules, "kaleido", SimpleNamespace())
    monkeypatch.chdir(validation)
    return SimpleNamespace(root=root, thesis=thesis, paper=paper, validation=validation,
                           survey=survey, nested=nested)


def savers(checkout, notebook="ptg.ipynb"):
    return notebook_savers(section=SECTION, notebook=notebook,
                           config_path=checkout / "figures_config.toml", values=True)


def manifest(document):
    path = document / MANIFEST_NAME
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def figure(document, name="ptg_scatter.png"):
    return document / "Sections" / SECTION / "Figures" / name


def tex(document):
    return (document / "Sections" / SECTION / "ptg.tex").read_text(encoding="utf-8")


def run_parity(*argv):
    with pytest.raises(SystemExit) as raised:
        parity_main(list(argv))
    return raised.value.code


# --------------------------------------------------------------- resolving


def test_a_workspace_analysis_resolves_its_documents_in_order(ws):
    targets = target_documents()
    assert targets.names == ["thesis", "paper"]
    assert [d.path for d in targets.documents] == [ws.root / "thesis", ws.root / "paper"]
    assert targets.analysis == "validation"


def test_document_repo_refuses_to_pick_one_of_several(ws):
    """A single-document caller gets a clear error, not whichever target is first."""
    with pytest.raises(RuntimeError, match="thesis, paper"):
        document_repo()


def test_a_nested_analysis_resolves_from_its_layout_and_owns_by_directory_name(ws):
    """Being listed in workspace.json changes nothing: layout.toml places it."""
    os.chdir(ws.nested)
    targets = target_documents()
    assert [d.path for d in targets.documents] == [ws.thesis]
    assert targets.analysis == "thesis-analysis"


def test_a_checkout_the_workspace_does_not_list_is_not_a_workspace_analysis(ws):
    """Matched by path, never by name: an unlisted checkout has no structure to read."""
    os.chdir(make_checkout(ws.root / "scratch"))
    assert target_documents().documents == ()


def test_a_member_without_documents_predates_attachment_and_names_none(ws):
    data = json.loads((ws.root / ".claude" / "workspace.json").read_text(encoding="utf-8"))
    del data["members"][3]["documents"]
    (ws.root / ".claude" / "workspace.json").write_text(json.dumps(data), encoding="utf-8")
    assert find_workspace_analysis() is None


@pytest.mark.parametrize("entry, error, complaint", [
    ("missing", NotADirectoryError, "does not exist"),
    ("validation", NotADirectoryError, "no Sections/"),
    ("../elsewhere", ValueError, "relative to the workspace root"),
    ("/abs/doc", ValueError, "relative to the workspace root"),
    (3, ValueError, "non-empty string"),
])
def test_a_bad_documents_entry_raises_naming_it(ws, entry, error, complaint):
    """Anything that names a document and is wrong raises: saving to outputs/ instead
    would look like a successful save."""
    write_workspace(ws.root, validation_documents=["thesis", entry])
    with pytest.raises(error, match=complaint) as raised:
        target_documents()
    assert repr(entry) in str(raised.value)


def test_a_malformed_workspace_file_raises_naming_it(ws):
    (ws.root / ".claude" / "workspace.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValueError, match="workspace.json: not valid JSON"):
        target_documents()


def test_an_empty_documents_list_is_no_document_mode(ws, capsys):
    write_workspace(ws.root, validation_documents=[])
    assert target_documents().documents == ()
    save_fig, _, _ = savers(ws.validation)
    png = save_fig(FakeMatplotlibFigure(), "ptg_scatter.png")
    assert png == ws.validation / "outputs" / "figures" / "ptg_scatter.png"
    assert not figure(ws.thesis).exists() and not figure(ws.paper).exists()
    assert "No document configured" in capsys.readouterr().out


# --------------------------------------------------------------- DOC_REPO


@pytest.mark.parametrize("value", ["absolute", "relative"])
def test_a_doc_repo_naming_a_target_is_silent_and_changes_nothing(ws, value):
    """setup-doc-publish writes DOC_REPO into .env: that must not narrow the targets."""
    os.environ["DOC_REPO"] = (str(ws.paper) if value == "absolute"
                              else os.path.relpath(ws.paper, ws.validation))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert target_documents().names == ["thesis", "paper"]
        save_fig, _, _ = savers(ws.validation)
        save_fig(FakeMatplotlibFigure(), "ptg_scatter.png")
    assert figure(ws.thesis).is_file() and figure(ws.paper).is_file()


def test_a_doc_repo_naming_another_document_raises_quoting_both(ws, tmp_path):
    other = make_document(tmp_path / "other")
    os.environ["DOC_REPO"] = str(other)
    save_fig, _, _ = savers(ws.validation)
    with pytest.raises(RuntimeError) as raised:
        save_fig(FakeMatplotlibFigure(), "ptg_scatter.png")
    message = str(raised.value)
    assert str(other) in message and str(ws.thesis) in message and "workspace.json" in message
    assert not figure(ws.thesis).exists() and not figure(other).exists()


def test_a_doc_repo_left_after_detaching_every_document_raises(ws):
    """detach-analysis empties the list but leaves .env alone; honouring the leftover
    DOC_REPO would keep feeding the document that was just detached."""
    write_workspace(ws.root, validation_documents=[])
    os.environ["DOC_REPO"] = str(ws.paper)
    with pytest.raises(RuntimeError, match="attaches this analysis"):
        target_documents()


# --------------------------------------------------------------- fan-out


def test_save_fig_writes_every_target_and_records_the_owner_in_each(ws):
    fig = FakePlotlyFigure()
    save_fig, _, _ = savers(ws.validation)
    paths = save_fig(fig, "ptg_scatter.png")

    assert paths == [figure(ws.thesis), figure(ws.paper)]
    assert fig.renders == 1  # rendered once, copied: kaleido is not paid per document
    for document in (ws.thesis, ws.paper):
        assert figure(document).read_bytes() == png_bytes()
        assert "%     \\includegraphics[width=\\width]{ptg_scatter.png}" in tex(document)
        entry = manifest(document)["Fig: ptg_scatter"]
        assert entry["analysis"] == "validation"
        assert entry["notebook"] == "ptg.ipynb"
        assert entry["static"] == f"Sections/{SECTION}/Figures/ptg_scatter.png"
        # Relative to the manifest file, as doc-publish's FigureEmitter resolves it.
        assert entry["interactive"] == "../validation/figures_html/ptg_scatter.html"
        assert (document / entry["interactive"]).resolve().is_file()
    assert not (ws.validation / "figures_html" / MANIFEST_NAME).exists()


def test_tables_and_values_fan_out_and_are_owned_too(ws):
    _, save_table, save_value = savers(ws.validation)
    tables = save_table(pd.DataFrame({"a": [1.0]}), "ptg_summary")
    values = save_value(0.873, "ptg_agreement")
    assert len(tables) == len(values) == 2
    for document in (ws.thesis, ws.paper):
        entries = manifest(document)
        assert entries["Tab: ptg_summary"]["analysis"] == "validation"
        assert entries["Tab: ptg_summary"]["notebook"] == "ptg.ipynb"
        assert entries["Val: ptgAgreement"]["analysis"] == "validation"
        assert entries["Val: ptgAgreement"]["library"] == f"Sections/{SECTION}/values.tex"


def test_documents_narrows_the_save_to_a_subset(ws):
    save_fig, save_table, save_value = savers(ws.validation)
    assert save_fig(FakeMatplotlibFigure(), "ptg_scatter.png",
                    documents=["paper"]) == figure(ws.paper)
    save_table(pd.DataFrame({"a": [1.0]}), "ptg_summary", documents=["paper"])
    save_value(1, "ptg_count", decimals=0, documents="paper")
    assert not (ws.thesis / "Sections" / SECTION / "Figures").exists()
    assert not (ws.thesis / MANIFEST_NAME).exists()
    assert set(manifest(ws.paper)) == {"Fig: ptg_scatter", "Tab: ptg_summary",
                                       "Val: ptgCount"}


@pytest.mark.parametrize("documents", [["survey-doc"], ["thesis", "elsewhere"], []])
def test_documents_naming_anything_but_a_target_raises_and_writes_nothing(ws, documents):
    """documents= narrows; it can never add a document the workspace does not list."""
    save_fig, _, _ = savers(ws.validation)
    with pytest.raises(ValueError, match="documents="):
        save_fig(FakeMatplotlibFigure(), "ptg_scatter.png", documents=documents)
    assert not figure(ws.thesis).exists() and not figure(ws.paper).exists()


def test_a_target_missing_the_section_fails_the_save_before_any_write(ws):
    """All or nothing: the thesis must not get a figure the paper then lacks, and the
    section is never created in a document."""
    (ws.paper / "Sections" / SECTION / "ptg.tex").unlink()
    (ws.paper / "Sections" / SECTION).rmdir()
    before = tex(ws.thesis)
    save_fig, save_table, save_value = savers(ws.validation)
    for save in (lambda: save_fig(FakeMatplotlibFigure(), "ptg_scatter.png"),
                 lambda: save_table(pd.DataFrame({"a": [1.0]}), "ptg_summary"),
                 lambda: save_value(1, "ptg_count")):
        with pytest.raises(NotADirectoryError, match="in paper"):
            save()
    assert sorted(p.name for p in (ws.thesis / "Sections" / SECTION).iterdir()) == ["ptg.tex"]
    assert tex(ws.thesis) == before and not (ws.thesis / MANIFEST_NAME).exists()
    assert not (ws.paper / "Sections" / SECTION).exists()



def test_a_target_with_several_tex_files_fails_the_save_before_any_write(ws):
    """The ambiguous-.tex check runs for every target up front too: thesis must not get
    a figure, table or value whose block paper then cannot place."""
    (ws.paper / "Sections" / SECTION / "other.tex").write_text("More.\n", encoding="utf-8")
    before = tex(ws.thesis)
    save_fig, save_table, save_value = savers(ws.validation)
    for save in (lambda **kw: save_fig(FakeMatplotlibFigure(), "ptg_scatter.png", **kw),
                 lambda **kw: save_table(pd.DataFrame({"a": [1.0]}), "ptg_summary", **kw),
                 lambda **kw: save_value(1, "ptg_count", **kw)):
        with pytest.raises(RuntimeError, match="several .tex files"):
            save()
    assert sorted(p.name for p in (ws.thesis / "Sections" / SECTION).iterdir()) == ["ptg.tex"]
    assert tex(ws.thesis) == before
    assert not (ws.thesis / MANIFEST_NAME).exists() and not (ws.paper / MANIFEST_NAME).exists()
    # tex=False needs no .tex at all, so the same saves then go through.
    save_fig(FakeMatplotlibFigure(), "ptg_scatter.png", tex=False)
    assert figure(ws.thesis).exists() and figure(ws.paper).exists()

# --------------------------------------------------------------- ownership


@pytest.mark.parametrize("second", ["survey", "nested"])
def test_another_analysis_cannot_overwrite_an_owned_name(ws, second):
    """Names are never prefixed or renamed, so a clash is refused, naming the owner and
    the way to release it, and nothing is written — not even to a target it would own."""
    save_fig, save_table, save_value = savers(ws.validation)
    save_fig(FakeMatplotlibFigure(), "ptg_scatter.png")
    save_table(pd.DataFrame({"a": [1.0]}), "ptg_summary")
    save_value(0.5, "ptg_agreement")
    def document_files():
        # The nested analysis lives inside thesis/; its own config is not the document.
        return {path: path.read_bytes() for path in ws.thesis.rglob("*")
                if path.is_file() and not path.is_relative_to(ws.nested)}

    owned = document_files()

    os.chdir(getattr(ws, second))
    save_fig, save_table, save_value = savers(getattr(ws, second), "other.ipynb")
    for save in (lambda: save_fig(FakeMatplotlibFigure(), "ptg_scatter.png"),
                 lambda: save_fig(FakeMatplotlibFigure(), "ptg_scatter.png",
                                  label="another_label"),
                 lambda: save_table(pd.DataFrame({"b": [2.0]}), "ptg_summary"),
                 lambda: save_value(0.9, "ptg_agreement")):
        with pytest.raises(OwnershipError) as raised:
            save()
        message = str(raised.value)
        assert "'validation'" in message and "check-figure-parity --prune" in message
    assert document_files() == owned


def test_the_owner_re_saves_freely(ws):
    save_fig, save_table, _ = savers(ws.validation)
    save_fig(FakeMatplotlibFigure(), "ptg_scatter.png")
    save_table(pd.DataFrame({"a": [1.0]}), "ptg_summary")
    save_fig(FakePlotlyFigure(), "ptg_scatter.png")
    save_table(pd.DataFrame({"a": [2.0]}), "ptg_summary")
    assert manifest(ws.thesis)["Fig: ptg_scatter"]["backend"] == "plotly"
    # Re-saving never duplicates the block.
    assert tex(ws.thesis).count("{ptg_scatter.png}") == 1


def test_a_clash_in_one_target_writes_none_of_them(ws):
    """survey owns the name in thesis only; validation saving to thesis and paper must
    not leave paper holding a figure thesis refused."""
    os.chdir(ws.survey)
    save_fig, _, _ = savers(ws.survey)
    save_fig(FakeMatplotlibFigure(), "ptg_scatter.png")

    os.chdir(ws.validation)
    save_fig, _, _ = savers(ws.validation)
    with pytest.raises(OwnershipError, match="'survey'"):
        save_fig(FakeMatplotlibFigure(), "ptg_scatter.png")
    assert not figure(ws.paper).exists() and not (ws.paper / MANIFEST_NAME).exists()
    # Narrowed to the target where the name is free, it goes through.
    assert save_fig(FakeMatplotlibFigure(), "ptg_scatter.png",
                    documents=["paper"]) == figure(ws.paper)


def test_deleting_the_png_and_pruning_releases_the_name(ws):
    save_fig, save_table, _ = savers(ws.validation)
    save_fig(FakePlotlyFigure(), "ptg_scatter.png")
    save_table(pd.DataFrame({"a": [1.0]}), "ptg_summary")
    html = ws.validation / "figures_html" / "ptg_scatter.html"

    os.chdir(ws.survey)
    figure(ws.thesis).unlink()
    library = ws.thesis / "Sections" / SECTION / "tables.tex"
    library.write_text("", encoding="utf-8")  # the block deleted, the file kept
    assert run_parity("--prune") == 0
    assert "Fig: ptg_scatter" not in manifest(ws.thesis)
    assert "Tab: ptg_summary" not in manifest(ws.thesis)
    # Another analysis's HTML is in its repo, which a prune elsewhere never touches.
    assert html.is_file()

    save_fig, save_table, _ = savers(ws.survey)
    save_fig(FakeMatplotlibFigure(), "ptg_scatter.png")
    save_table(pd.DataFrame({"b": [1.0]}), "ptg_summary")
    assert manifest(ws.thesis)["Fig: ptg_scatter"]["analysis"] == "survey"
    assert manifest(ws.thesis)["Tab: ptg_summary"]["analysis"] == "survey"
    # paper still has validation's PNG, and validation still owns it there.
    assert manifest(ws.paper)["Fig: ptg_scatter"]["analysis"] == "validation"


# --------------------------------------------------------------- the manifest


def test_a_nested_analysis_moves_its_old_manifest_into_the_document_once(ws, capsys):
    os.chdir(ws.nested)
    html_dir = ws.nested / "figures_html"
    html_dir.mkdir()
    old_png = figure(ws.thesis, "old_figure.png")
    old_png.parent.mkdir(parents=True)
    old_png.write_bytes(png_bytes())
    (html_dir / "old_figure.html").write_text("<html/>", encoding="utf-8")
    local = ws.nested / "outputs" / "figures" / "local.png"
    write_manifest(html_dir / MANIFEST_NAME, {
        "Fig: old_figure": {"static": str(old_png), "interactive": "old_figure.html",
                            "stem": "old_figure", "backend": "plotly"},
        "Fig: local": {"static": str(local), "interactive": None, "stem": "local"},
    })

    save_fig, _, _ = savers(ws.nested)
    save_fig(FakeMatplotlibFigure(), "ptg_scatter.png")
    out = capsys.readouterr().out
    assert out.count("Moved 1 manifest entry") == 1

    entry = manifest(ws.thesis)["Fig: old_figure"]
    assert entry["analysis"] == "thesis-analysis"
    assert entry["static"] == f"Sections/{SECTION}/Figures/old_figure.png"
    assert entry["interactive"] == "thesis-analysis/figures_html/old_figure.html"
    # The no-document entry is not the document's, and stays where it was.
    old = json.loads((html_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert set(old) == {"Fig: local"}

    save_fig(FakeMatplotlibFigure(), "ptg_scatter.png")
    assert "Moved" not in capsys.readouterr().out
    assert sorted(manifest(ws.thesis)) == ["Fig: old_figure", "Fig: ptg_scatter"]


def test_a_manifest_write_that_fails_leaves_the_old_file_whole(ws, monkeypatch):
    """Written to a temp file and renamed: a crash mid-write never leaves torn JSON."""
    path = ws.thesis / MANIFEST_NAME
    write_manifest(path, {"Fig: a": {"analysis": "x"}})
    before = path.read_text(encoding="utf-8")

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        write_manifest(path, {"Fig: b": {}})
    assert path.read_text(encoding="utf-8") == before
    assert [p.name for p in ws.thesis.iterdir() if p.name.endswith(".tmp")] == []


# --------------------------------------------------------------- parity


def test_parity_snapshots_and_checks_every_target(ws, capsys):
    save_fig, _, _ = savers(ws.validation)
    save_fig(FakeMatplotlibFigure(), "ptg_scatter.png")
    assert run_parity("--snapshot") == 0
    baseline = json.loads((ws.validation / "docs" / "figure_png_baseline.json")
                          .read_text(encoding="utf-8"))
    assert set(baseline["documents"]) == {"thesis", "paper"}
    assert baseline["documents"]["paper"]["ptg_scatter.png"]["path"] == \
        f"Sections/{SECTION}/Figures/ptg_scatter.png"
    assert run_parity() == 0

    figure(ws.paper).write_bytes(png_bytes(width=1400))
    capsys.readouterr()
    assert run_parity() == 1
    assert "DRIFT    paper: ptg_scatter.png" in capsys.readouterr().out


def test_parity_snapshot_covers_only_this_analysis_in_a_shared_document(ws):
    os.chdir(ws.survey)
    savers(ws.survey)[0](FakeMatplotlibFigure(), "survey_map.png")
    os.chdir(ws.validation)
    savers(ws.validation)[0](FakeMatplotlibFigure(), "ptg_scatter.png")
    assert run_parity("--snapshot") == 0
    baseline = json.loads((ws.validation / "docs" / "figure_png_baseline.json")
                          .read_text(encoding="utf-8"))
    assert set(baseline["documents"]["thesis"]) == {"ptg_scatter.png"}


def test_parity_figures_reports_the_union_of_every_feeding_analysis(ws, capsys):
    os.chdir(ws.survey)
    savers(ws.survey)[0](FakeMatplotlibFigure(), "survey_map.png")
    os.chdir(ws.validation)
    savers(ws.validation)[0](FakeMatplotlibFigure(), "ptg_scatter.png")
    capsys.readouterr()
    assert run_parity("--figures") == 0
    out = capsys.readouterr().out
    thesis_report, paper_report = out.split("\n\n1 figures")
    assert "2 figures in figures_manifest.json" in thesis_report
    assert "survey_map" in thesis_report and "ptg_scatter" in thesis_report
    assert "survey_map" not in paper_report
