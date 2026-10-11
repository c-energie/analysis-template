"""init.py, run the way setup-doc-workspace runs it: flags only, no terminal on stdin.

Each test runs a copy of init.py in a throwaway copy of the files it rewrites, so the
real template is never touched and the script's self-deletion is harmless. A downstream
repo has no init.py — it deleted itself — so there these tests have nothing to test.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parents[1]
INIT = TEMPLATE / "init.py"
SETUP_NESTED = TEMPLATE / "setup_nested.py"

pytestmark = pytest.mark.skipif(not INIT.exists(), reason="init.py has already run")

PYPROJECT = '[project]\nname = "PACKAGE-NAME"\nauthors = [{ name = "<<AUTHOR>>" }]\n'


@pytest.fixture
def checkout(tmp_path):
    (tmp_path / "init.py").write_text(INIT.read_text(encoding="utf-8"), encoding="utf-8")
    # --nest runs it; it stays behind when init.py deletes itself.
    (tmp_path / "setup_nested.py").write_text(SETUP_NESTED.read_text(encoding="utf-8"),
                                              encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_init.py").write_text(PYPROJECT, encoding="utf-8")
    return tmp_path


def run_init(checkout, *flags, env=None):
    # stdin=DEVNULL: not a TTY, so nothing may be prompted for. PYTHONIOENCODING, as
    # setup sets it: init.py prints em dashes, which the Windows code page cannot encode.
    return subprocess.run([sys.executable, "init.py", *flags], cwd=checkout,
                          stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8",
                          env=(env or os.environ) | {"PYTHONIOENCODING": "utf-8"})


def nested_repo(directory):
    """A stand-in nested document repo: its own .git, and files full of tokens that are
    writing-template's or its author's, not ours to fill."""
    (directory / ".git").mkdir(parents=True)
    (directory / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    (directory / "README.md").write_text("# PACKAGE-NAME by <<AUTHOR>>\n", encoding="utf-8")
    (directory / "notes").mkdir()
    (directory / "notes" / "setup.py").write_text("NAME = 'PACKAGE-NAME'\n", encoding="utf-8")
    return directory


def snapshot(directory):
    return {path.relative_to(directory).as_posix(): path.read_bytes()
            for path in sorted(directory.rglob("*")) if path.is_file()}


def unchanged(checkout):
    return (checkout / "pyproject.toml").read_text(encoding="utf-8") == PYPROJECT \
        and (checkout / "init.py").exists() and not (checkout / ".env").exists()


def test_every_flag_given_runs_unattended(checkout):
    result = run_init(checkout, "--distribution", "x-analysis", "--author", "A",
                      "--doc-repo", "/p", "--backend", "plotly")
    assert result.returncode == 0, result.stderr
    pyproject = (checkout / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "x-analysis"' in pyproject and 'name = "A"' in pyproject
    assert "DOC_REPO=/p\n" in (checkout / ".env").read_text(encoding="utf-8")
    assert not (checkout / "init.py").exists()
    # It holds the placeholder tokens and only tests init.py, so it goes with it.
    assert not (checkout / "tests" / "test_init.py").exists()
    for prompt in ("Project name", "Author", "Path to your document repo", "Backend",
                   "Plotting backend"):
        assert prompt not in result.stdout


def test_backend_defaults_to_plotly(checkout):
    result = run_init(checkout, "--distribution", "x-analysis", "--author", "A")
    assert result.returncode == 0, result.stderr
    assert "--extra plotly" in result.stdout


def test_backend_is_case_insensitive(checkout):
    result = run_init(checkout, "--distribution", "x-analysis", "--author", "A",
                      "--backend", "Matplotlib")
    assert result.returncode == 0, result.stderr
    assert "--extra matplotlib" in result.stdout


def test_no_doc_repo_writes_no_env(checkout):
    result = run_init(checkout, "--distribution", "x-analysis", "--author", "A")
    assert result.returncode == 0, result.stderr
    assert not (checkout / ".env").exists()
    assert "copy .env.example to .env" in result.stdout


def test_invalid_distribution_fails_with_the_hint(checkout):
    result = run_init(checkout, "--distribution", "My_Project", "--author", "A")
    assert result.returncode != 0
    assert "Lower case, digits and dashes, starting with a letter." in result.stderr
    assert "Aborted" not in result.stderr
    assert unchanged(checkout)


def test_invalid_backend_fails_with_the_hint(checkout):
    result = run_init(checkout, "--distribution", "x-analysis", "--author", "A",
                      "--backend", "ggplot")
    assert result.returncode != 0
    assert "One of: plotly, matplotlib." in result.stderr
    assert unchanged(checkout)


def test_missing_required_flags_are_named(checkout):
    result = run_init(checkout, "--distribution", "x-analysis")
    assert result.returncode != 0
    assert "--author" in result.stderr
    assert "Aborted" not in result.stderr
    assert unchanged(checkout)


def test_all_missing_required_flags_are_named(checkout):
    result = run_init(checkout)
    assert result.returncode != 0
    assert "--distribution" in result.stderr and "--author" in result.stderr
    assert unchanged(checkout)


def test_already_initialised_wins_over_missing_flags(checkout):
    (checkout / "pyproject.toml").write_text('[project]\nname = "done"\n', encoding="utf-8")
    result = run_init(checkout)
    assert result.returncode == 1
    assert "already been initialised" in result.stdout
    assert "--author" not in result.stderr


def test_nest_leaves_a_nested_repo_byte_for_byte_unchanged(checkout):
    """The placeholder pass used to walk everything under the root — a nested document
    repo included — and would have rewritten its <<…>> tokens as if they were ours."""
    nested = nested_repo(checkout / "doc-writing")
    (checkout / "layout.toml").write_text(
        'layout = "analysis-hosts-writing"\nnested_dir = "doc-writing"\n'
        'nested_remote = "https://example.invalid/doc-writing.git"\n', encoding="utf-8")
    before = snapshot(nested)

    result = run_init(checkout, "--distribution", "x-analysis", "--author", "A", "--nest")
    assert result.returncode == 0, result.stderr
    assert snapshot(nested) == before
    assert 'name = "x-analysis"' in (checkout / "pyproject.toml").read_text(encoding="utf-8")
    # Nested: DOC_REPO comes from layout.toml, so there is no path to ask for or write.
    assert not (checkout / ".env").exists()
    assert "Path to your document repo" not in result.stdout
    assert (checkout / "setup_nested.py").exists()


def test_any_subdirectory_with_its_own_git_is_skipped_without_a_layout(checkout):
    """A repo cloned in by hand, before or without setup_nested.py, is just as foreign."""
    nested = nested_repo(checkout / "cloned-by-hand")
    before = snapshot(nested)
    result = run_init(checkout, "--distribution", "x-analysis", "--author", "A")
    assert result.returncode == 0, result.stderr
    assert snapshot(nested) == before


def test_nest_without_gh_stops_before_anything_is_rewritten(checkout, tmp_path):
    """Nesting runs first, so a refusal leaves the template whole and init.py re-runnable."""
    empty = tmp_path / "empty-path"
    empty.mkdir()
    result = run_init(checkout, "--distribution", "x-analysis", "--author", "A", "--nest",
                      env=os.environ | {"PATH": str(empty)})
    assert result.returncode != 0
    assert "gh auth login" in result.stderr
    assert unchanged(checkout)
    assert not (checkout / "layout.toml").exists()


def test_nest_and_doc_repo_are_alternatives(checkout):
    result = run_init(checkout, "--distribution", "x-analysis", "--author", "A", "--nest",
                      "--doc-repo", "/p")
    assert result.returncode != 0
    assert "--nest" in result.stderr and "--doc-repo" in result.stderr
    assert unchanged(checkout)
