"""notebook_setup() finds the analysis repo from wherever the kernel started.

A temporary document workspace — the analysis repo as a member below the workspace root,
its `.env` naming the document — stands in for a real one. The package's installed
location is injected, so no install is involved: the layout says where `src/` is, and
the function is judged only on what it returns, where it leaves the working directory and
what `DOC_REPO` ends up as.
"""
import os
import sys
import warnings

import pytest

from doc_analysis import env, figure_config, notebook_setup, parity, save_figure
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
    # The search record names the checkout as a fallback for every later document_repo()
    # call; left behind, it points the rest of the suite at this test's layout.
    for key in env.LAST_SEARCH:
        monkeypatch.setitem(env.LAST_SEARCH, key, env.LAST_SEARCH[key])
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


def no_document_notice(monkeypatch, capsys):
    """The once-per-process line a save prints in no-document mode, printed afresh."""
    monkeypatch.setitem(save_figure._NO_DOCUMENT_NOTICE, "shown", False)
    capsys.readouterr()
    save_figure._announce_no_document()
    return capsys.readouterr().out


def test_outside_a_checkout_the_notice_says_where_it_looked(workspace, tmp_path,
                                                            monkeypatch, capsys):
    """Nothing found is no-document mode now, not an error (issue #20) — so the search
    record moved into the notice: a non-editable install is the one cause of landing in
    no-document mode by accident that its own message can name."""
    # A wheel in site-packages: two levels up holds no pyproject.toml.
    wheel = tmp_path / "venv" / "site-packages" / "doc_analysis"
    wheel.mkdir(parents=True)

    notebook_setup(package_dir=wheel)

    assert os.getcwd() == str(workspace.root)
    assert document_repo() is None
    message = no_document_notice(monkeypatch, capsys)
    assert str(workspace.root) in message
    assert "non-editable" in message


def test_a_checkout_without_a_dotenv_names_the_file_it_wanted(workspace, monkeypatch,
                                                              capsys):
    (workspace.analysis / ".env").unlink()

    notebook_setup(package_dir=workspace.package_dir)

    assert document_repo() is None
    message = no_document_notice(monkeypatch, capsys)
    assert str(workspace.analysis / ".env") in message
    assert message.count("\n") == 1


# --- two analysis checkouts sharing one venv (issue #24) ------------------------------


def make_hosted_checkout(workspace_root, document_name, analysis_name):
    """A document repo hosting its analysis checkout (`writing-hosts-analysis`), no .env."""
    document = workspace_root / document_name
    (document / "Sections").mkdir(parents=True)
    (document / "layout.toml").write_text(
        f'layout = "writing-hosts-analysis"\nnested_dir = "{analysis_name}"\n',
        encoding="utf-8")
    analysis = document / analysis_name
    (analysis / "src" / "doc_analysis").mkdir(parents=True)
    (analysis / "notebooks").mkdir()
    (analysis / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    return analysis, document


@pytest.fixture
def shared_venv(tmp_path, monkeypatch):
    """Checkouts A and B in one project workspace, the imported doc_analysis being A's.

    The workspace root has a `pyproject.toml` of its own, as a root venv's project does:
    a directory holding one is not thereby an analysis checkout.
    """
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname = 'ws'\n", encoding="utf-8")
    a, a_document = make_hosted_checkout(root, "energy-estimation", "energy-analysis")
    b, b_document = make_hosted_checkout(root, "smeter-validation", "smeter-analysis")

    monkeypatch.setattr(os, "environ", dict(os.environ))
    for name in ("DOC_REPO", "DOC_ENV", figure_config.CONFIG_ENV, save_figure.HTML_DIR_ENV):
        os.environ.pop(name, None)
    monkeypatch.setattr(sys, "path", list(sys.path))
    # The search record names the checkout as a fallback for every later document_repo()
    # call; left behind, it points the rest of the suite at this test's layout.
    for key in env.LAST_SEARCH:
        monkeypatch.setitem(env.LAST_SEARCH, key, env.LAST_SEARCH[key])
    monkeypatch.chdir(root)

    class Layout:
        pass

    layout = Layout()
    layout.root, layout.a, layout.b = root, a, b
    layout.a_document, layout.b_document = a_document, b_document
    layout.package_dir = a / "src" / "doc_analysis"
    return layout


def setup_recording_warnings(package_dir):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        root = notebook_setup(package_dir=package_dir)
    return root, [str(w.message) for w in caught]


def test_a_shadowed_checkout_writes_into_its_own_document(shared_venv):
    """The #24 failure: from B's notebooks, with A's doc_analysis imported, setup moved to A
    and document_repo() named A's document — B's figures landed in the wrong document."""
    os.chdir(shared_venv.b / "notebooks")

    root, _ = setup_recording_warnings(shared_venv.package_dir)

    assert root == shared_venv.b
    assert os.getcwd() == str(shared_venv.b)
    assert str(shared_venv.b / "notebooks") in sys.path
    assert str(shared_venv.a / "notebooks") not in sys.path
    assert document_repo() == shared_venv.b_document


def test_a_shadowed_checkout_uses_its_own_config_html_dir_and_baseline(shared_venv):
    """Computed from the imported package's __file__, these gated B's figures by A's
    config and sent its manifest and baseline into A."""
    os.chdir(shared_venv.b / "notebooks")
    setup_recording_warnings(shared_venv.package_dir)

    assert figure_config.config_path() == shared_venv.b / "figures_config.toml"
    assert save_figure.default_html_dir() == shared_venv.b / "figures_html"
    assert parity.default_baseline_path() == shared_venv.b / "docs" / "figure_png_baseline.json"
    # The old constant names still import, and now follow the active checkout too.
    assert figure_config.DEFAULT_CONFIG_PATH.parent == shared_venv.b
    assert save_figure.DEFAULT_HTML_DIR.parent == shared_venv.b
    assert parity.BASELINE_PATH.parents[1] == shared_venv.b


def test_a_shadowed_checkout_warns_once_naming_both(shared_venv):
    """Proceeding is right, but silently running A's code for B's notebooks is not: the
    two checkouts may carry different versions of the package."""
    os.chdir(shared_venv.b / "notebooks")

    _, messages = setup_recording_warnings(shared_venv.package_dir)

    assert len(messages) == 1
    assert str(shared_venv.a) in messages[0] and str(shared_venv.b) in messages[0]


def test_outside_every_checkout_the_installed_one_is_used(shared_venv):
    """A kernel started at the workspace root (#2) is in no checkout — the root's own
    pyproject.toml does not make it one — so the installed checkout stays the answer."""
    root, messages = setup_recording_warnings(shared_venv.package_dir)

    assert root == shared_venv.a
    assert os.getcwd() == str(shared_venv.a)
    assert document_repo() == shared_venv.a_document
    assert messages == []


def test_inside_the_installed_checkout_nothing_changes(shared_venv):
    """The single-checkout case the cwd-first rule must not disturb: a warning here would
    fire in every ordinary notebook, and a moved config would gate it by another file."""
    os.chdir(shared_venv.a / "notebooks")

    root, messages = setup_recording_warnings(shared_venv.package_dir)

    assert root == shared_venv.a
    assert document_repo() == shared_venv.a_document
    assert figure_config.config_path() == shared_venv.a / "figures_config.toml"
    assert messages == []


def test_leaving_the_checkout_after_setup_keeps_its_config_and_html_dir(shared_venv, tmp_path):
    """A cell moving to a data directory outside B: document_repo() kept B's document via
    the recorded checkout, but config and figures_html/ fell back to the installed one, so
    B's figures were gated by and recorded in another checkout — #24 again."""
    os.chdir(shared_venv.b / "notebooks")
    setup_recording_warnings(shared_venv.package_dir)
    data = tmp_path / "data"
    data.mkdir()
    os.chdir(data)

    assert document_repo() == shared_venv.b_document
    assert figure_config.config_path() == shared_venv.b / "figures_config.toml"
    assert save_figure.default_html_dir() == shared_venv.b / "figures_html"
