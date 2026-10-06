"""notebook-skeleton fills the template's routing, and retrofit stays inside this repo.

The template file is the real one from notebooks/, copied into a temporary repo, so these
tests fail the moment the template and the script stop agreeing on a placeholder.
"""
import json
import shutil
from pathlib import Path

import pytest

from doc_analysis import notebook_savers
from doc_analysis.notebook_skeleton import main

TEMPLATE = Path(__file__).resolve().parents[1] / "notebooks" / "_template.ipynb"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    analysis = tmp_path / "analysis"
    (analysis / "notebooks").mkdir(parents=True)
    shutil.copy(TEMPLATE, analysis / "notebooks" / "_template.ipynb")
    document = tmp_path / "document"
    (document / "Sections" / "Results").mkdir(parents=True)
    (document / "Sections" / "Results" / "results.tex").write_text("", encoding="utf-8")
    (document / "Sections" / "Results" / "tables.tex").write_text("", encoding="utf-8")
    monkeypatch.setenv("DOC_REPO", str(document))
    monkeypatch.chdir(analysis)
    return analysis


def source(path):
    return "".join("".join(c["source"]) for c in json.loads(path.read_text(encoding="utf-8"))["cells"])


def test_new_fills_routing_and_mirrors_the_section(repo):
    assert main(["new", "Results", "fits", "--backend", "matplotlib"]) == 0
    text = source(repo / "notebooks" / "Results" / "fits.ipynb")
    assert 'SECTION = "Results"' in text
    assert 'NOTEBOOK = "fits.ipynb"' in text
    assert "TEX = None" in text  # one candidate besides tables.tex: the saver finds it
    assert "figure_size_in" in text and "plotly" not in text
    assert "<<FIGURE>>" in text  # left for the author to name


def test_new_refuses_a_section_the_document_lacks(repo):
    with pytest.raises(SystemExit, match="not found"):
        main(["new", "Methods", "fits", "--backend", "plotly"])


def test_new_asks_for_tex_when_the_section_has_several(repo):
    (Path.cwd().parent / "document" / "Sections" / "Results" / "extra.tex").write_text("")
    with pytest.raises(SystemExit, match="--tex"):
        main(["new", "Results", "fits", "--backend", "plotly"])
    assert main(["new", "Results", "fits", "--backend", "plotly", "--tex", "extra.tex"]) == 0
    assert 'TEX = "extra.tex"' in source(repo / "notebooks" / "Results" / "fits.ipynb")


def test_new_never_overwrites(repo):
    main(["new", "Results", "fits", "--backend", "plotly"])
    with pytest.raises(SystemExit, match="already exists"):
        main(["new", "Results", "fits", "--backend", "plotly"])


def legacy_notebook(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"cells": [
        {"cell_type": "markdown", "metadata": {}, "source": ["# Old fits\n"]},
        {"cell_type": "code", "metadata": {}, "outputs": [], "execution_count": None,
         "source": ["import os\n", "os.chdir('..')\n", "fig.savefig('figs/fit.png')\n"]},
    ], "metadata": {}, "nbformat": 4, "nbformat_minor": 4}), encoding="utf-8")


def test_retrofit_grafts_setup_after_the_title_and_lists_legacy_lines(repo, capsys):
    target = repo / "notebooks" / "Results" / "old_fits.ipynb"
    legacy_notebook(target)
    assert main(["retrofit", str(target), "--section", "Results"]) == 0
    cells = json.loads(target.read_text(encoding="utf-8"))["cells"]
    assert "".join(cells[0]["source"]) == "# Old fits\n"
    assert 'NOTEBOOK = "old_fits.ipynb"' in "".join(cells[2]["source"])
    out = capsys.readouterr().out
    assert "[path hack]" in out and "[figure save]" in out
    assert "sys.path.insert" not in out  # the grafted setup cell is not reported as legacy
    with pytest.raises(SystemExit, match="already calls"):
        main(["retrofit", str(target), "--section", "Results"])


def test_retrofit_leaves_notebooks_outside_the_repo_alone(repo, tmp_path):
    original = tmp_path / "old_repo" / "notebooks" / "fits.ipynb"
    legacy_notebook(original)
    before = original.read_bytes()
    with pytest.raises(SystemExit, match="outside"):
        main(["retrofit", str(original), "--section", "Results"])
    assert original.read_bytes() == before


@pytest.mark.parametrize("kind", ["figure", "table"])
def test_savers_refuse_template_placeholders(tmp_path, kind):
    save_fig, save_table = notebook_savers(section=str(tmp_path), notebook="n.ipynb",
                                           config_path=tmp_path / "figures_config.toml")
    with pytest.raises(ValueError, match="placeholder"):
        if kind == "figure":
            save_fig(object(), "<<FIGURE>>.png")
        else:
            save_table(None, "<<TABLE>>")
    assert not (tmp_path / "figures_config.toml").exists()
