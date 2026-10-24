"""No-document mode: an analysis repo that stands alone, before any write-up exists.

With no `DOC_REPO`, no `.env` line and no `layout.toml` on either side, `document_repo()`
returns None and the savers write to the checkout's own `outputs/` instead of raising —
so an analysis no longer needs a placeholder document just for its tooling to run
(issue #20). What is worth pinning:

- it is entered only when *nothing* names a document. A `DOC_REPO` without Sections/, a
  nested repo not cloned yet and a host layout naming another directory all still raise,
  and write nothing locally: falling back would hide the misconfiguration;
- figures keep their bare filename (`outputs/figures/<name>.png`), the manifest is
  written as always, and no `Sections/` directory or `.tex` block appears anywhere;
- the notice saying so is printed once per process, not once per save;
- `check-figure-parity` works against `outputs/`, and a local baseline is never checked
  against a document, or the reverse, without an error.

A temporary checkout stands in for the analysis repo, so `outputs/`, `figures_html/`, the
config and the baseline all land under tmp_path. Figures are stubs; no backend is imported.
"""
import json
import os
import struct
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from doc_analysis import (env, notebook_savers, notebook_setup, save_document_value,
                          save_figure)
from doc_analysis.notebook_skeleton import resolve_tex
from doc_analysis.parity import main as parity_main
from doc_analysis.save_figure import MANIFEST_NAME, document_repo, sections_dir

HOST_LAYOUT = 'layout = "writing-hosts-analysis"\nnested_dir = "{}"\n'


def png_bytes(width=1125, height=720):
    """A PNG header parity.png_size can read: signature, then IHDR width/height."""
    return (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR"
            + struct.pack(">II", width, height))


class FakePlotlyFigure:
    """Duck-types what the saver asks of a plotly Figure — and nothing else."""

    def __init__(self, width=1125, height=720):
        self.data = [SimpleNamespace(hovertemplate="%{x}")]
        self.size = (width, height)

    def write_image(self, path, **kwargs):
        Path(path).write_bytes(png_bytes(*self.size))

    def write_html(self, path, **kwargs):
        Path(path).write_text("<html>fake</html>", encoding="utf-8")


class FakeMatplotlibFigure:
    def savefig(self, path, **kwargs):
        Path(path).write_bytes(png_bytes())


@pytest.fixture
def standalone(tmp_path, monkeypatch):
    """A checkout with no document anywhere: no env, no .env, no layout on either side."""
    checkout = (tmp_path / "workspace" / "my-analysis").resolve()
    (checkout / "src" / "doc_analysis").mkdir(parents=True)
    (checkout / "notebooks").mkdir()
    (checkout / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")

    monkeypatch.setattr(os, "environ", dict(os.environ))
    for name in ("DOC_REPO", "DOC_ENV", "FIGURES_HTML_DIR", "FIGURES_CONFIG"):
        os.environ.pop(name, None)
    monkeypatch.setattr(sys, "path", list(sys.path))
    for key in env.LAST_SEARCH:
        monkeypatch.setitem(env.LAST_SEARCH, key, env.LAST_SEARCH[key])
    monkeypatch.setitem(env.LAST_SEARCH, "fallback", None)
    # Once per process: each test is a fresh process as far as the notice is concerned.
    monkeypatch.setitem(save_figure._NO_DOCUMENT_NOTICE, "shown", False)
    monkeypatch.setitem(sys.modules, "kaleido", SimpleNamespace())
    monkeypatch.chdir(checkout)
    return checkout


def savers(checkout):
    return notebook_savers(section="Results/ptg", notebook="ptg.ipynb",
                           config_path=checkout / "figures_config.toml", values=True)


def manifest_of(checkout):
    return json.loads((checkout / "figures_html" / MANIFEST_NAME).read_text(encoding="utf-8"))


def run_parity(*argv):
    with pytest.raises(SystemExit) as raised:
        parity_main(list(argv))
    return raised.value.code


# --------------------------------------------------------------- the savers


def test_nothing_configured_saves_all_three_to_outputs(standalone, capsys):
    """The acceptance case: notebook_setup(), then every saver, with no document."""
    notebook_setup(package_dir=standalone / "src" / "doc_analysis")
    assert document_repo() is None
    save_fig, save_table, save_value = savers(standalone)

    png = save_fig(FakePlotlyFigure(), "ptg_scatter.png")
    tables = save_table(pd.DataFrame({"a": [1.0]}), "ptg_summary")
    values = save_value(0.873, "ptg_agreement")

    outputs = standalone / "outputs"
    assert png == outputs / "figures" / "ptg_scatter.png" and png.is_file()
    assert tables == outputs / "Results" / "ptg" / "tables.tex"
    assert "%<*ptg_summary>" in tables.read_text(encoding="utf-8")
    assert values == outputs / "Results" / "ptg" / "values.tex"
    assert "\\renewcommand{\\ptgAgreement}{0.87}" in values.read_text(encoding="utf-8")

    entry = manifest_of(standalone)["Fig: ptg_scatter"]
    assert entry["static"] == str(png)
    assert entry["interactive"] == "ptg_scatter.html"
    assert (standalone / "figures_html" / "ptg_scatter.html").is_file()

    # Three saves, one notice: it says where output went and how to get a document.
    out = capsys.readouterr().out
    assert out.count("No document configured") == 1
    assert str(outputs) in out and "DOC_REPO" in out


def test_no_sections_directory_or_tex_block_is_created_anywhere(standalone):
    """There is no document to place a block in, and a Sections/ under outputs/ would
    look like one to anything that walks the tree for figures."""
    save_fig, save_table, save_value = savers(standalone)
    save_fig(FakeMatplotlibFigure(), "ptg_scatter")
    save_table(pd.DataFrame({"a": [1.0]}), "ptg_summary")
    save_value(1, "ptg_count", decimals=0)

    tree = list(standalone.parent.rglob("*"))
    assert not [p for p in tree if p.name in ("Sections", "Chapters", "Figures")]
    # The generated libraries are the only .tex written: no section file got a reference.
    assert sorted(p.name for p in tree if p.suffix == ".tex") == ["tables.tex", "values.tex"]


def test_a_matplotlib_figure_keeps_its_bare_name_and_a_null_interactive(standalone):
    """The filename is the key LaTeX, the manifest and publishing share; no-document mode
    must not prefix it, or the later re-run into a document would be a rename."""
    save_fig, _, _ = savers(standalone)
    png = save_fig(FakeMatplotlibFigure(), "ptg_scatter")
    assert png == standalone / "outputs" / "figures" / "ptg_scatter.png"
    assert manifest_of(standalone)["Fig: ptg_scatter"]["interactive"] is None


def test_the_config_still_gates_a_save_in_no_document_mode(standalone):
    (standalone / "figures_config.toml").write_text(
        "default = true\n\n[ptg.figures]\nptg_scatter = false\n", encoding="utf-8")
    save_fig, _, _ = savers(standalone)
    assert save_fig(FakeMatplotlibFigure(), "ptg_scatter.png") is None
    assert not (standalone / "outputs").exists()


def test_the_picker_and_sections_dir_raise_rather_than_prompt(standalone, monkeypatch):
    """section=None asks for the interactive picker, which has no tree to walk; an
    input() over nothing would hang an unattended run."""
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("prompted"))
    with pytest.raises(RuntimeError, match="No document is configured"):
        sections_dir()
    with pytest.raises(RuntimeError, match="No document is configured"):
        save_figure.save_document_figure("x.png", fig=FakeMatplotlibFigure())


def test_a_section_climbing_out_of_outputs_is_refused(standalone):
    """In a document the section must exist; here it is created, so '..' would write
    wherever it pointed."""
    with pytest.raises(ValueError, match=r"\.\."):
        save_document_value("n", 1, section="../escaped")
    assert not (standalone.parent / "escaped").exists()


def test_an_absolute_section_is_used_as_before_without_a_document(standalone, tmp_path):
    """Tests and exploratory runs pass an absolute temp section; that never consulted the
    document, so it must not start going to outputs/ either."""
    section = tmp_path / "scratch"
    section.mkdir()
    png = save_figure.save_document_figure("x.png", fig=FakeMatplotlibFigure(),
                                           section=section, tex=False)
    assert png == section / "Figures" / "x.png"
    assert not (standalone / "outputs").exists()


# --------------------------------------------------------------- staying loud


def test_a_doc_repo_without_sections_still_raises(standalone, tmp_path):
    not_a_document = tmp_path / "not-a-document"
    not_a_document.mkdir()
    os.environ["DOC_REPO"] = str(not_a_document)
    save_fig, _, _ = savers(standalone)
    with pytest.raises(NotADirectoryError, match="no Sections/"):
        save_fig(FakeMatplotlibFigure(), "x.png")
    assert not (standalone / "outputs").exists()


def test_a_missing_nested_repo_still_says_to_run_setup_nested(standalone):
    (standalone / "layout.toml").write_text(
        'layout = "analysis-hosts-writing"\nnested_dir = "my-writing"\n', encoding="utf-8")
    save_fig, _, _ = savers(standalone)
    with pytest.raises(RuntimeError, match="setup_nested.py"):
        save_fig(FakeMatplotlibFigure(), "x.png")
    assert not (standalone / "outputs").exists()


def test_a_host_layout_naming_another_directory_still_raises(standalone):
    """A renamed nested checkout: the host says a document is meant to be here, so
    saving locally would hide the rename until the figures were found missing."""
    (standalone.parent / "Sections").mkdir()
    (standalone.parent / "layout.toml").write_text(HOST_LAYOUT.format("other-analysis"),
                                                   encoding="utf-8")
    save_fig, _, _ = savers(standalone)
    with pytest.raises(RuntimeError, match="'other-analysis'"):
        save_fig(FakeMatplotlibFigure(), "x.png")
    assert not (standalone / "outputs").exists()


def test_once_a_document_is_configured_saves_land_in_it(standalone, tmp_path, capsys):
    """Setting DOC_REPO later is the whole migration: the same call lands in the
    document, outputs/ is left as it was, and the notice is not printed."""
    save_fig, _, _ = savers(standalone)
    save_fig(FakeMatplotlibFigure(), "ptg_scatter.png")
    before = sorted((standalone / "outputs").rglob("*"))
    capsys.readouterr()

    document = tmp_path / "document"
    section = document / "Sections" / "Results" / "ptg"
    section.mkdir(parents=True)
    (section / "ptg.tex").write_text("Prose.\n", encoding="utf-8")
    os.environ["DOC_REPO"] = str(document)
    save_figure._NO_DOCUMENT_NOTICE["shown"] = False

    png = save_fig(FakeMatplotlibFigure(), "ptg_scatter.png")
    assert png == section / "Figures" / "ptg_scatter.png"
    assert "ptg_scatter.png" in (section / "ptg.tex").read_text(encoding="utf-8")
    assert manifest_of(standalone)["Fig: ptg_scatter"]["static"] == str(png)
    assert sorted((standalone / "outputs").rglob("*")) == before
    assert "No document configured" not in capsys.readouterr().out


def test_the_nested_layout_ends_no_document_mode(standalone):
    """add-analysis --from nests the repo in a document: from then on the parent is it."""
    (standalone.parent / "Sections").mkdir()
    (standalone.parent / "layout.toml").write_text(HOST_LAYOUT.format(standalone.name),
                                                   encoding="utf-8")
    assert document_repo() == standalone.parent


def test_notebook_skeleton_does_not_check_a_section_with_no_document(standalone, capsys):
    """The analysis comes before the write-up; refusing an unknown section would block it."""
    assert resolve_tex("Results/ptg", None) is None
    assert "no document is configured" in capsys.readouterr().err


# --------------------------------------------------------------- parity


def test_parity_snapshot_then_check_passes_and_catches_drift(standalone):
    save_fig, _, _ = savers(standalone)
    save_fig(FakePlotlyFigure(), "ptg_scatter.png")

    assert run_parity("--snapshot") == 0
    baseline = json.loads((standalone / "docs" / "figure_png_baseline.json")
                          .read_text(encoding="utf-8"))
    assert baseline["target"] == "local"
    assert baseline["ptg_scatter.png"]["path"] == "figures/ptg_scatter.png"
    assert run_parity() == 0

    save_fig(FakePlotlyFigure(width=1400), "ptg_scatter.png")
    assert run_parity() == 1


def test_parity_figures_reports_no_document_and_exits_zero(standalone, capsys):
    save_fig, _, _ = savers(standalone)
    save_fig(FakeMatplotlibFigure(), "ptg_scatter.png")
    capsys.readouterr()
    assert run_parity("--figures") == 0
    assert "No document configured" in capsys.readouterr().out


def test_a_local_baseline_checked_against_a_document_is_an_error(standalone, tmp_path,
                                                                 capsys):
    """Every path would resolve under the wrong root; that is not a parity result."""
    save_fig, _, _ = savers(standalone)
    save_fig(FakeMatplotlibFigure(), "ptg_scatter.png")
    assert run_parity("--snapshot") == 0

    document = tmp_path / "document"
    (document / "Sections").mkdir(parents=True)
    os.environ["DOC_REPO"] = str(document)
    capsys.readouterr()
    assert run_parity() == 1
    assert "taken with no document" in capsys.readouterr().out


def test_a_document_baseline_checked_with_no_document_is_an_error(standalone, tmp_path,
                                                                  capsys):
    document = tmp_path / "document"
    section = document / "Sections" / "Results" / "ptg"
    section.mkdir(parents=True)
    os.environ["DOC_REPO"] = str(document)
    save_fig, _, _ = savers(standalone)
    save_fig(FakeMatplotlibFigure(), "ptg_scatter.png")
    assert run_parity("--snapshot") == 0
    baseline = json.loads((standalone / "docs" / "figure_png_baseline.json")
                          .read_text(encoding="utf-8"))
    # A document's baseline is written exactly as before no-document mode existed.
    assert "target" not in baseline

    del os.environ["DOC_REPO"]
    capsys.readouterr()
    assert run_parity() == 1
    assert "no document is configured" in capsys.readouterr().out
