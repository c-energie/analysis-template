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

pytestmark = pytest.mark.skipif(not INIT.exists(), reason="init.py has already run")

PYPROJECT = '[project]\nname = "PACKAGE-NAME"\nauthors = [{ name = "<<AUTHOR>>" }]\n'


@pytest.fixture
def checkout(tmp_path):
    (tmp_path / "init.py").write_text(INIT.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    return tmp_path


def run_init(checkout, *flags):
    # stdin=DEVNULL: not a TTY, so nothing may be prompted for. PYTHONIOENCODING, as
    # setup sets it: init.py prints em dashes, which the Windows code page cannot encode.
    return subprocess.run([sys.executable, "init.py", *flags], cwd=checkout,
                          stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8",
                          env=os.environ | {"PYTHONIOENCODING": "utf-8"})


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
