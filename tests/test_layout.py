"""document_repo() in the nested layout: DOC_REPO from layout.toml, after env and .env.

A temporary host repo stands in for a real one — `layout.toml` at its root, the document
repo (just a `Sections/`) in the subdirectory it names. No git, no install: the function is
judged only on the path it returns, what it warns and what it raises.
"""
import os
import warnings

import pytest

from doc_analysis import env
from doc_analysis.env import load_env
from doc_analysis.layout import find_host_layout, find_layout, read_layout
from doc_analysis.save_figure import document_repo

LAYOUT = ('layout = "analysis-hosts-writing"\n'
          'nested_dir = "my-study-writing"\n'
          'nested_remote = "https://github.com/someone/my-study-writing.git"\n')


@pytest.fixture
def host(tmp_path, monkeypatch):
    root = (tmp_path / "my-study").resolve()
    (root / "notebooks").mkdir(parents=True)
    (root / "layout.toml").write_text(LAYOUT, encoding="utf-8")
    # What makes it a checkout: the upward search for layout.toml stops here.
    (root / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    nested = root / "my-study-writing"
    (nested / "Sections" / "Results").mkdir(parents=True)

    # Each test sets DOC_REPO its own way; one left behind would satisfy the next without
    # the layout ever being read. Nor may an earlier notebook_setup()'s fallback leak in.
    monkeypatch.setattr(os, "environ", dict(os.environ))
    for name in ("DOC_REPO", "DOC_ENV"):
        os.environ.pop(name, None)
    monkeypatch.setitem(env.LAST_SEARCH, "fallback", None)
    monkeypatch.chdir(root)
    return root


@pytest.mark.parametrize("where", ["", "notebooks", "my-study-writing",
                                   "my-study-writing/Sections/Results"])
def test_layout_alone_locates_the_nested_document_from_anywhere_in_the_host(host, where):
    """No env, no .env: the layout is all there is, and the cwd must not matter — a
    notebook runs from notebooks/, and an agent may well be inside the nested repo."""
    os.chdir(host / where)
    assert document_repo() == host / "my-study-writing"


def test_a_kernel_started_beside_the_host_finds_it_through_the_checkout_fallback(
        host, tmp_path):
    """The same reach as .env: notebook_setup() records the installed checkout, and a
    kernel started at a workspace root never walks into the host to find layout.toml."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    os.chdir(elsewhere)
    assert find_layout() is None
    env.LAST_SEARCH["fallback"] = host
    assert document_repo() == host / "my-study-writing"


def test_an_exported_doc_repo_that_disagrees_wins_and_warns_naming_both(host, tmp_path):
    exported = tmp_path / "exported"
    (exported / "Sections").mkdir(parents=True)
    os.environ["DOC_REPO"] = str(exported)
    with pytest.warns(UserWarning) as caught:
        assert document_repo() == exported
    message = str(caught[0].message)
    assert str(exported) in message and str(host / "my-study-writing") in message
    assert "\n" not in message


def test_a_stale_dotenv_doc_repo_wins_and_warns(host, tmp_path):
    """The usual mismatch: a .env written for the side-by-side layout, kept after nesting."""
    old = tmp_path / "old-document"
    (old / "Sections").mkdir(parents=True)
    (host / ".env").write_text(f'DOC_REPO="{old}"\n', encoding="utf-8")
    load_env(start=host)
    with pytest.warns(UserWarning, match="layout.toml"):
        assert document_repo() == old


@pytest.mark.parametrize("value", ["absolute", "relative"])
def test_a_doc_repo_that_agrees_with_the_layout_is_silent(host, value):
    """A warning on every save for a setting that is merely redundant would teach people
    to ignore the one that matters."""
    os.environ["DOC_REPO"] = (str(host / "my-study-writing") if value == "absolute"
                              else "my-study-writing")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        document_repo()


def test_a_missing_nested_repo_says_to_run_setup_nested(host):
    """The normal state of a fresh clone: the nested repo is gitignored and absent."""
    (host / "my-study-writing" / "Sections" / "Results").rmdir()
    (host / "my-study-writing" / "Sections").rmdir()
    (host / "my-study-writing").rmdir()
    with pytest.raises(RuntimeError, match="setup_nested.py"):
        document_repo()


def test_a_nested_dir_that_is_not_a_document_names_the_layout(host):
    (host / "elsewhere").mkdir()
    (host / "layout.toml").write_text(LAYOUT.replace("my-study-writing\"\n",
                                                     "elsewhere\"\n", 1), encoding="utf-8")
    with pytest.raises(NotADirectoryError, match="layout.toml"):
        document_repo()


def test_without_a_layout_the_not_set_error_is_unchanged(host):
    (host / "layout.toml").unlink()
    with pytest.raises(RuntimeError, match="DOC_REPO is not set") as raised:
        document_repo()
    assert "setup_nested" not in str(raised.value)


def test_the_document_sides_layout_file_is_walked_past(host):
    """writing-hosts-analysis is the document repo's half of the contract; finding one
    nearer must not stop the search for this repo's own."""
    (host / "my-study-writing" / "layout.toml").write_text(
        'layout = "writing-hosts-analysis"\nnested_dir = "analysis"\n', encoding="utf-8")
    os.chdir(host / "my-study-writing")
    assert document_repo() == host / "my-study-writing"


def test_a_foreign_layout_above_the_checkout_is_never_read(host, tmp_path):
    """Every layout.toml reached is parsed strictly, so one belonging to whatever sits
    above a checkout with no layout of its own would fail every save, DOC_REPO or not.
    Two levels up: the direct parent is the one place a host layout is looked for."""
    checkout = tmp_path / "projects" / "plain-analysis"
    (checkout / "notebooks").mkdir(parents=True)
    (checkout / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    (tmp_path / "layout.toml").write_text(LAYOUT + 'other_tool = "x"\n', encoding="utf-8")
    os.environ["DOC_REPO"] = str(host / "my-study-writing")
    os.chdir(checkout / "notebooks")
    assert document_repo() == host / "my-study-writing"


def test_outside_any_checkout_a_foreign_layout_is_never_read(host, tmp_path):
    """The reviewer's case: DOC_REPO exported, run from a directory that is no checkout,
    under a layout.toml that is not ours. Only the installed checkout is looked at."""
    (tmp_path / "layout.toml").write_text(LAYOUT + 'other_tool = "x"\n', encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    os.chdir(work)
    assert find_layout() is None
    os.environ["DOC_REPO"] = str(host / "my-study-writing")
    assert document_repo() == host / "my-study-writing"


@pytest.mark.parametrize("text, complaint", [
    (LAYOUT + 'nested_drr = "x"\n', "nested_drr"),
    ('layout = "analysis-hosts-writing"\n', "nested_dir"),
    ('layout = "side-by-side"\nnested_dir = "x"\n', "side-by-side"),
    ('layout = "analysis-hosts-writing"\nnested_dir = "/abs/doc"\n', "inside the repo"),
    ('layout = "analysis-hosts-writing"\nnested_dir = "../sibling"\n', "inside the repo"),
    ('layout = "analysis-hosts-writing"\nnested_dir = "."\n', "subdirectory"),
    ('layout = "analysis-hosts-writing"\nnested_dir = "./"\n', "subdirectory"),
    ('layout = "analysis-hosts-writing"\nnested_dir = 3\n', "non-empty string"),
    ("layout = \n", "not valid TOML"),
])
def test_a_malformed_layout_is_an_error_naming_the_problem(host, text, complaint):
    """A typo silently ignored would leave DOC_REPO unset with nothing pointing at it."""
    (host / "layout.toml").write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match=complaint):
        read_layout(host / "layout.toml")


# Layout 3a: the other way up. The document repo is the host repo, and this repo is the
# nested repo inside it; the host's layout.toml names this repo's directory.

HOST_LAYOUT = 'layout = "writing-hosts-analysis"\nnested_dir = "my-thesis-analysis"\n'


@pytest.fixture
def hosted(tmp_path, monkeypatch):
    """`<tmp>/my-thesis` (document, layout.toml) holding `my-thesis-analysis` (this repo)."""
    document = (tmp_path / "my-thesis").resolve()
    (document / "Sections" / "Results").mkdir(parents=True)
    (document / "layout.toml").write_text(HOST_LAYOUT, encoding="utf-8")
    analysis = document / "my-thesis-analysis"
    (analysis / "notebooks").mkdir(parents=True)
    (analysis / "pyproject.toml").write_text("[project]\nname = \"x\"\n", encoding="utf-8")

    monkeypatch.setattr(os, "environ", dict(os.environ))
    for name in ("DOC_REPO", "DOC_ENV"):
        os.environ.pop(name, None)
    monkeypatch.setitem(env.LAST_SEARCH, "fallback", None)
    monkeypatch.chdir(analysis)
    return document


@pytest.mark.parametrize("where", ["", "notebooks"])
def test_the_host_layout_makes_the_parent_the_document_from_root_and_notebooks(hosted,
                                                                                where):
    """No env, no .env, no layout.toml of our own: an absolute DOC_REPO in .env is what
    ADR 0001 rejected, so the host's committed file is the only place left to say it."""
    os.chdir(hosted / "my-thesis-analysis" / where)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert document_repo() == hosted


def test_a_kernel_started_in_the_host_finds_this_repo_through_the_checkout_fallback(
        hosted):
    """From the document's own directory the upward search never enters this repo, so its
    root comes from the installed checkout notebook_setup() records."""
    os.chdir(hosted)
    with pytest.raises(RuntimeError, match="DOC_REPO is not set"):
        document_repo()
    env.LAST_SEARCH["fallback"] = hosted / "my-thesis-analysis"
    assert document_repo() == hosted


def test_a_renamed_nested_checkout_gets_no_fallback_and_the_error_names_both(hosted):
    """A host naming another directory nests some other repo, or this one was renamed;
    guessing the parent then could write figures into a document that is not ours."""
    renamed = hosted / "thesis-analysis-old"
    (hosted / "my-thesis-analysis").rename(renamed)
    os.chdir(renamed)
    with pytest.raises(RuntimeError, match="DOC_REPO is not set") as raised:
        document_repo()
    message = str(raised.value)
    assert "'my-thesis-analysis'" in message and "'thesis-analysis-old'" in message


@pytest.mark.parametrize("how", ["environment", "dotenv"])
def test_env_and_dotenv_override_the_host_layout_and_warn_when_they_differ(
        hosted, tmp_path, how):
    other = tmp_path / "other-document"
    (other / "Sections").mkdir(parents=True)
    analysis = hosted / "my-thesis-analysis"
    if how == "environment":
        os.environ["DOC_REPO"] = str(other)
    else:
        (analysis / ".env").write_text(f'DOC_REPO="{other}"\n', encoding="utf-8")
        load_env(start=analysis)
    with pytest.warns(UserWarning) as caught:
        assert document_repo() == other
    message = str(caught[0].message)
    assert str(other) in message and str(hosted / "layout.toml") in message


@pytest.mark.parametrize("how", ["environment", "dotenv"])
def test_env_and_dotenv_that_agree_with_the_host_layout_are_silent(hosted, how):
    analysis = hosted / "my-thesis-analysis"
    if how == "environment":
        os.environ["DOC_REPO"] = str(hosted)
    else:
        (analysis / ".env").write_text(f'DOC_REPO="{hosted}"\n', encoding="utf-8")
        load_env(start=analysis)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert document_repo() == hosted


def test_a_parent_layout_of_any_other_kind_is_not_a_host(hosted):
    """analysis-hosts-writing in the parent says the parent is an analysis repo hosting a
    document — the contract's other half, which #7's upward search already owns. It must
    not also make the parent this repo's document."""
    (hosted / "layout.toml").write_text(
        'layout = "analysis-hosts-writing"\nnested_dir = "my-thesis-analysis"\n',
        encoding="utf-8")
    assert find_host_layout() is None
    assert find_host_layout(fallback=hosted / "my-thesis-analysis") is None


def test_only_the_direct_parent_is_a_host(hosted):
    """One level, never further: a layout.toml two directories up describes another
    nesting, and walking to it would make any ancestor a candidate document."""
    deeper = hosted / "my-thesis-analysis" / "inner"
    (deeper / "notebooks").mkdir(parents=True)
    (deeper / "pyproject.toml").write_text("[project]\nname = \"y\"\n", encoding="utf-8")
    os.chdir(deeper / "notebooks")
    with pytest.raises(RuntimeError, match="DOC_REPO is not set"):
        document_repo()


def test_this_repos_own_layout_wins_over_the_hosts(hosted):
    """Its own layout.toml is the nearer, stricter statement (ADR 0001 before ADR 0002)."""
    analysis = hosted / "my-thesis-analysis"
    (analysis / "doc").mkdir()
    (analysis / "doc" / "Sections").mkdir()
    (analysis / "layout.toml").write_text(
        'layout = "analysis-hosts-writing"\nnested_dir = "doc"\n', encoding="utf-8")
    assert document_repo() == analysis / "doc"
