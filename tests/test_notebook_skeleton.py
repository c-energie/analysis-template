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
    (document / "Sections" / "Results" / "values.tex").write_text("", encoding="utf-8")
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
    assert "TEX = None" in text  # one candidate besides the generated libraries
    assert "figure_size_in" in text and "plotly" not in text
    assert "<<FIGURE>>" in text  # left for the author to name


def test_new_sets_up_through_the_package_not_a_path_walk(repo):
    assert main(["new", "Results", "fits", "--backend", "plotly"]) == 0
    text = source(repo / "notebooks" / "Results" / "fits.ipynb")
    assert "from doc_analysis import notebook_setup, notebook_savers" in text
    assert "ROOT = notebook_setup()" in text
    assert "sys.path" not in text and "setup_notebook" not in text


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
    grafted = "".join(cells[2]["source"])
    assert 'NOTEBOOK = "old_fits.ipynb"' in grafted
    assert "ROOT = notebook_setup()" in grafted and "sys.path" not in grafted
    out = capsys.readouterr().out
    assert "[path hack]" in out and "[figure save]" in out
    assert "sys.path.insert" not in out  # the grafted setup cell is not reported as legacy
    assert main(["retrofit", str(target), "--section", "Results"]) == 0
    assert "nothing to graft" in capsys.readouterr().out
    assert len(json.loads(target.read_text(encoding="utf-8"))["cells"]) == len(cells)


def savers_notebook(path, *sources):
    """A copied-in notebook whose code cells already call notebook_savers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"cells": [
        {"cell_type": "markdown", "metadata": {}, "source": ["# Old fits\n"]},
        *({"cell_type": "code", "metadata": {}, "outputs": [], "execution_count": None,
           "source": source.splitlines(keepends=True)} for source in sources),
    ], "metadata": {}, "nbformat": 4, "nbformat_minor": 4}), encoding="utf-8")
    return path


def retrofit(repo, *sources):
    target = savers_notebook(repo / "notebooks" / "Results" / "old_fits.ipynb", *sources)
    before = target.read_bytes()
    code = main(["retrofit", str(target), "--section", "Results"])
    assert target.read_bytes() == before  # checked, never grafted or rewritten
    return code


def test_retrofit_reports_an_old_fork_savers_call_instead_of_nothing_to_graft(repo, capsys):
    """An older fork's call read as "nothing to graft", then failed at its setup cell."""
    code = retrofit(repo,
                    '%matplotlib inline\n'
                    'save_fig, save_table, save_value = notebook_savers(\n'
                    '    chapter="X", notebook="n.ipynb", colour=True)\n',
                    'save_value(0.42, "fit_r2")\n'
                    'save_fig(fig, "fit.png", label="Fit of the PtG model")\n')
    out = capsys.readouterr().out
    assert code == 1
    assert "cell 1 line 2  [deprecated keyword]" in out and "use section=" in out
    assert "[unknown keyword]" in out and "colour=" in out
    assert "[unpacking]" in out and "pass values=True" in out
    assert "cell 2 line 1  [save_value]" in out
    assert "cell 2 line 2  [free-text label]" in out and "'fit'" in out
    assert "nothing to graft" not in out


def test_retrofit_accepts_the_values_saver_once_asked_for(repo, capsys):
    """values=True with three names and a save_value call is the current signature (#9)."""
    code = retrofit(repo,
                    'save_fig, save_table, save_value = notebook_savers(\n'
                    '    section=SECTION, notebook=NOTEBOOK, values=True)\n'
                    'save_value(0.42, "fit_r2")\n'
                    'save_fig(fig, "fit.png", label="fit")\n')
    out = capsys.readouterr().out
    assert code == 0
    assert "[" not in out and "nothing to graft" in out


def test_retrofit_fails_the_issue_fixture_on_chapter_alone(repo, capsys):
    """The old fork's call from #6: with save_value ported, chapter= is what is left."""
    code = retrofit(repo, 'save_fig, save_table, save_value = notebook_savers(chapter="X", '
                          'notebook="n.ipynb", values=True)\n'
                          'save_value(0.42, "fit_r2")\n')
    out = capsys.readouterr().out
    assert code == 1
    assert "[deprecated keyword]" in out
    assert "[unpacking]" not in out and "[save_value]" not in out


def test_retrofit_reports_three_names_from_two_savers(repo, capsys):
    """Unpacking three names without values=True fails with a ValueError when run."""
    assert retrofit(repo, 'save_fig, save_table, save_value = notebook_savers(\n'
                          '    section=SECTION, notebook=NOTEBOOK)\n') == 1
    assert "[unpacking]" in capsys.readouterr().out


def test_retrofit_warns_that_section_may_carry_its_old_meaning(repo, capsys):
    """A bare section= may be an old fork's config table: flag it, but cannot fail on it."""
    assert retrofit(repo, 'save_fig, save_table = notebook_savers(section="old_fits", '
                          'notebook="old_fits.ipynb")\n') == 0
    out = capsys.readouterr().out
    assert "[check]" in out and "config_section=" in out and "nothing to graft" in out


def test_retrofit_cannot_check_a_savers_call_it_cannot_parse(repo, capsys):
    """A call in unparseable code must not pass as clean."""
    assert retrofit(repo, 'save_fig, save_table = notebook_savers(section=SECTION,\n') == 1
    assert "[unparsed]" in capsys.readouterr().out


def test_retrofit_does_not_take_a_continuation_line_for_a_magic(repo, capsys):
    """A clean cell whose continuation line opens with `!=` was failed as [unparsed]."""
    assert retrofit(repo, 'save_fig, save_table = notebook_savers(section=SECTION,\n'
                          '    notebook=NOTEBOOK)\n'
                          'changed = (old\n'
                          '           != new)\n') == 0
    assert "nothing to graft" in capsys.readouterr().out


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


# --- marimo -------------------------------------------------------------------------------
# The marimo template is checked as text: marimo itself is never imported here.

MARIMO_TEMPLATE = TEMPLATE.with_name("_template_marimo.py")


@pytest.fixture
def marimo_repo(repo):
    shutil.copy(MARIMO_TEMPLATE, repo / "notebooks" / "_template_marimo.py")
    return repo


def test_new_marimo_writes_an_app_keyed_by_its_py_name(marimo_repo):
    assert main(["new", "Results", "fits", "--marimo", "--backend", "plotly"]) == 0
    text = (marimo_repo / "notebooks" / "Results" / "fits.py").read_text(encoding="utf-8")
    assert not (marimo_repo / "notebooks" / "Results" / "fits.ipynb").exists()
    assert "app = marimo.App(" in text
    assert 'SECTION = "Results"' in text
    assert 'NOTEBOOK = "fits.py"' in text
    assert "TEX = None" in text
    assert "ROOT = notebook_setup()" in text and "sys.path" not in text
    assert "<<FIGURE>>" in text and "<<TABLE>>" in text  # left for the author to name
    assert "<<SECTION>>" not in text and "<<TITLE>>" not in text


@pytest.mark.parametrize("backend, kept, dropped", [
    ("plotly", "go.Figure()", "plt.subplots"),
    ("matplotlib", "plt.subplots", "go.Figure()"),
])
def test_new_marimo_keeps_only_the_chosen_backends_figure_cell(marimo_repo, backend, kept, dropped):
    main(["new", "Results", "fits", "--marimo", "--backend", backend])
    text = (marimo_repo / "notebooks" / "Results" / "fits.py").read_text(encoding="utf-8")
    assert kept in text and dropped not in text
    assert "skeleton-backend" not in text  # template-only markers are stripped
    assert text.count("@app.cell") == 9  # one figure cell of the template's two


def test_new_marimo_drops_a_whole_cell_even_with_blank_lines_inside_it(marimo_repo):
    # Two blank lines inside a cell body look like a cell break; the dropped backend's cell
    # must still go whole, not leave its tail behind as an unmarked cell.
    template = marimo_repo / "notebooks" / "_template_marimo.py"
    text = template.read_text(encoding="utf-8").replace(
        "import matplotlib.pyplot as plt", "import matplotlib.pyplot as plt\n\n\n    TAIL = 1", 1)
    template.write_text(text, encoding="utf-8")
    main(["new", "Results", "fits", "--marimo", "--backend", "plotly"])
    out = (marimo_repo / "notebooks" / "Results" / "fits.py").read_text(encoding="utf-8")
    assert "TAIL" not in out and "plt" not in out
    assert out.count("@app.cell") == 9


def test_new_marimo_never_overwrites(marimo_repo):
    target = marimo_repo / "notebooks" / "Results" / "fits.py"
    main(["new", "Results", "fits", "--marimo", "--backend", "plotly"])
    target.write_text("# edited by hand\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="already exists"):
        main(["new", "Results", "fits.py", "--marimo", "--backend", "plotly"])
    assert target.read_text(encoding="utf-8") == "# edited by hand\n"


def test_new_marimo_refuses_a_section_the_document_lacks(marimo_repo):
    with pytest.raises(SystemExit, match="not found"):
        main(["new", "Methods", "fits", "--marimo", "--backend", "plotly"])
    assert not (marimo_repo / "notebooks" / "Methods").exists()


def test_savers_key_a_marimo_app_by_its_stem(tmp_path):
    config = tmp_path / "figures_config.toml"
    config.write_text("[fits.figures]\noff = false\n", encoding="utf-8")
    save_fig, _ = notebook_savers(section=str(tmp_path), notebook="fits.py", config_path=config)
    assert save_fig(object(), "off.png") is None  # switched off under [fits], not [fits.py]
