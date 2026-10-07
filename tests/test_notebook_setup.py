"""notebook_setup() finds the analysis repo from wherever the kernel started.

A temporary document workspace — the analysis repo as a member below the workspace root,
its `.env` naming the document — stands in for a real one. The package's installed
location is injected, so no install is involved: the layout says where `src/` is, and
the function is judged only on what it returns, where it leaves the working directory and
what `DOC_REPO` ends up as.
"""
import os
import sys

import pytest

from doc_analysis import notebook_setup
from doc_analysis.env import load_env
from doc_analysis.save_figure import document_repo


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    analysis = root / "analysis"
    (analysis / "src" / "doc_analysis").mkdir(parents=True)
    (analysis / "notebooks").mkdir()
    (analysis / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    document = root / "document"
    (document / "Sections").mkdir(parents=True)
    (analysis / ".env").write_text(f'DOC_REPO="{document}"\n', encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    # notebook_setup() writes to the process: environment, sys.path, cwd. Each is put
    # back, or one test's DOC_REPO would quietly satisfy the next.
    monkeypatch.setattr(os, "environ", dict(os.environ))
    for name in ("DOC_REPO", "DOC_ENV"):
        os.environ.pop(name, None)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.chdir(root)

    class Layout:
        pass

    layout = Layout()
    layout.root, layout.analysis, layout.document = root, analysis, document
    layout.elsewhere = elsewhere
    layout.package_dir = analysis / "src" / "doc_analysis"
    return layout


@pytest.mark.parametrize("start", ["root", "analysis", "notebooks", "elsewhere"])
def test_finds_the_analysis_repo_from_any_working_directory(workspace, start):
    cwd = {
        "root": workspace.root,
        "analysis": workspace.analysis,
        "notebooks": workspace.analysis / "notebooks",
        "elsewhere": workspace.elsewhere,
    }[start]
    os.chdir(cwd)

    root = notebook_setup(package_dir=workspace.package_dir)

    assert root == workspace.analysis
    assert os.getcwd() == str(workspace.analysis)
    assert document_repo() == workspace.document


def test_a_real_environment_variable_still_wins(workspace, tmp_path):
    exported = tmp_path / "exported"
    (exported / "Sections").mkdir(parents=True)
    os.environ["DOC_REPO"] = str(exported)

    notebook_setup(package_dir=workspace.package_dir)

    assert document_repo() == exported


def test_a_helper_module_beside_the_notebooks_imports(workspace, monkeypatch):
    (workspace.analysis / "notebooks" / "nb_helper_t1.py").write_text(
        "ANSWER = 42\n", encoding="utf-8")
    monkeypatch.delitem(sys.modules, "nb_helper_t1", raising=False)

    notebook_setup(package_dir=workspace.package_dir)
    import nb_helper_t1

    assert nb_helper_t1.ANSWER == 42


def test_calling_it_twice_changes_nothing(workspace):
    first = notebook_setup(package_dir=workspace.package_dir)
    path_after_first = list(sys.path)

    assert notebook_setup(package_dir=workspace.package_dir) == first
    assert sys.path == path_after_first
    assert os.getcwd() == str(workspace.analysis)


def test_a_plain_load_env_does_not_reach_the_checkout(workspace):
    # The import-time behaviour: without the opt-in, a kernel at the workspace root
    # finds no .env, exactly as before notebook_setup() existed.
    assert load_env() is None
    assert "DOC_REPO" not in os.environ


def test_outside_a_checkout_the_error_says_where_it_looked(workspace, tmp_path):
    # A wheel in site-packages: two levels up holds no pyproject.toml.
    wheel = tmp_path / "venv" / "site-packages" / "doc_analysis"
    wheel.mkdir(parents=True)

    notebook_setup(package_dir=wheel)

    assert os.getcwd() == str(workspace.root)
    with pytest.raises(RuntimeError) as raised:
        document_repo()
    message = str(raised.value)
    assert str(workspace.root) in message
    assert "non-editable" in message


def test_a_checkout_without_a_dotenv_names_the_file_it_wanted(workspace):
    (workspace.analysis / ".env").unlink()

    notebook_setup(package_dir=workspace.package_dir)

    with pytest.raises(RuntimeError, match="DOC_REPO is not set") as raised:
        document_repo()
    assert str(workspace.analysis / ".env") in str(raised.value)
