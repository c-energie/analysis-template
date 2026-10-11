"""setup_nested.py, run as a user runs it, against a throwaway host repo.

Each test copies the script into a temporary host checkout, so the real repo is never
touched. No network: `--from` clones a local git repo, and `gh` is a stub on `PATH` —
or is missing from it — so the create path is judged on what it does with gh's answers.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "setup_nested.py"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


@pytest.fixture
def git_env(tmp_path):
    """Git that reads no user or system config, so a test cannot inherit a hook, a
    template or an identity from whoever runs it."""
    config = tmp_path / "gitconfig"
    config.write_text("[init]\n\tdefaultBranch = main\n", encoding="utf-8")
    return os.environ | {
        "GIT_CONFIG_GLOBAL": str(config), "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
        "PYTHONIOENCODING": "utf-8",
    }


def git(env, *args, cwd):
    subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True)


@pytest.fixture
def host(tmp_path):
    root = tmp_path / "my-study"
    root.mkdir()
    shutil.copy(SCRIPT, root / "setup_nested.py")
    (root / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    return root


@pytest.fixture
def document(tmp_path, git_env):
    """A local document repo to adopt: stands in for a GitHub or Overleaf remote."""
    source = tmp_path / "source-document"
    (source / "Sections").mkdir(parents=True)
    (source / "Sections" / "main.tex").write_text("\\section{A}\n", encoding="utf-8")
    git(git_env, "init", "-q", cwd=source)
    git(git_env, "add", ".", cwd=source)
    git(git_env, "commit", "-q", "-m", "init", cwd=source)
    return source


def run(host, env, *args):
    return subprocess.run([sys.executable, "setup_nested.py", *args], cwd=host, env=env,
                          stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8")


def snapshot(directory):
    """Every file under *directory*, bytes and all, .git included."""
    return {path.relative_to(directory).as_posix(): path.read_bytes()
            for path in sorted(Path(directory).rglob("*")) if path.is_file()}


def layout(host):
    import tomllib
    return tomllib.loads((host / "layout.toml").read_text(encoding="utf-8"))


def fake_gh(directory, *, logged_in=True, owner="someone", creates=False):
    """A `gh` that answers auth and owner questions and refuses everything else, so a
    test that reaches `gh repo create` fails loudly rather than touching GitHub.

    With *creates*, `repo create ... --clone` instead does locally what gh would: a repo
    in ./<name> whose origin is the GitHub URL. Its argv is kept in gh_calls.txt."""
    directory.mkdir()
    script = directory / "fake_gh.py"
    script.write_text(
        "import pathlib, subprocess, sys\n"
        "args = sys.argv[1:]\n"
        f"pathlib.Path({str(directory / 'gh_calls.txt')!r}).open('a').write(' '.join(args) + '\\n')\n"
        f"if args[:2] == ['auth', 'status']: sys.exit(0 if {logged_in!r} else 1)\n"
        f"if args[:2] == ['api', 'user']: print({owner!r}); sys.exit(0)\n"
        f"if {creates!r} and args[:2] == ['repo', 'create']:\n"
        "    name = args[2].split('/')[1]\n"
        f"    git = {shutil.which('git')!r}\n"
        "    subprocess.run([git, 'init', '-q', name], check=True)\n"
        "    subprocess.run([git, '-C', name, 'remote', 'add', 'origin',\n"
        "                    f'https://github.com/{args[2]}.git'], check=True)\n"
        "    sys.exit(0)\n"
        "print('refused: ' + ' '.join(args), file=sys.stderr); sys.exit(1)\n",
        encoding="utf-8")
    if os.name == "nt":
        (directory / "gh.cmd").write_text(f'@"{sys.executable}" "{script}" %*\n',
                                          encoding="utf-8")
    else:
        gh = directory / "gh"
        gh.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n',
                      encoding="utf-8")
        gh.chmod(0o755)
    return directory


def path_of(git_env, directory):
    """PATH holding *directory* alone. Not git's directory too: a real gh is often
    installed beside git, in /usr/bin. The create path fails before it needs git."""
    return git_env | {"PATH": str(directory)}


def test_adopt_clones_into_the_default_dir_and_records_the_layout(host, document, git_env):
    before = snapshot(document)
    result = run(host, git_env, "--from", str(document))
    assert result.returncode == 0, result.stderr

    nested = host / "my-study-writing"
    assert (nested / "Sections" / "main.tex").is_file()
    assert layout(host) == {"layout": "analysis-hosts-writing",
                            "nested_dir": "my-study-writing",
                            "nested_remote": str(document)}
    assert "/my-study-writing/" in (host / ".gitignore").read_text(encoding="utf-8")
    assert "layout.toml" in result.stdout and ".gitignore" in result.stdout
    # "Never moves or modifies the source": it may be someone's only checkout.
    assert snapshot(document) == before


def test_gitignore_gets_the_entry_exactly_once_across_two_runs(host, document, git_env):
    """Adopting again into the emptied directory must not stack a second line on the
    first: the .gitignore is committed, and a duplicate is noise in someone's diff."""
    assert run(host, git_env, "--from", str(document)).returncode == 0
    shutil.rmtree(host / "my-study-writing")
    assert run(host, git_env, "--from", str(document)).returncode == 0
    lines = (host / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert lines.count("/my-study-writing/") == 1


def test_the_layout_is_readable_by_doc_analysis(host, document, git_env, monkeypatch):
    """The script carries its own writer; the package's reader must accept what it writes."""
    from doc_analysis.layout import read_layout

    assert run(host, git_env, "--from", str(document), "--dir", "docs/writing").returncode == 0
    parsed = read_layout(host / "layout.toml")
    assert parsed.nested_path == host / "docs" / "writing"
    assert (parsed.nested_path / "Sections").is_dir()


def test_no_arguments_restores_a_deleted_nested_repo(host, document, git_env):
    """A fresh clone of the host: layout.toml is committed, the nested repo is not."""
    assert run(host, git_env, "--from", str(document)).returncode == 0
    shutil.rmtree(host / "my-study-writing")
    layout_before = (host / "layout.toml").read_bytes()

    result = run(host, git_env)
    assert result.returncode == 0, result.stderr
    assert (host / "my-study-writing" / "Sections" / "main.tex").is_file()
    assert (host / "layout.toml").read_bytes() == layout_before


def test_no_arguments_with_the_nested_repo_present_does_nothing(host, document, git_env):
    assert run(host, git_env, "--from", str(document)).returncode == 0
    before = snapshot(host)
    result = run(host, git_env)
    assert result.returncode == 0
    assert "already here" in result.stdout
    assert snapshot(host) == before


def test_a_non_empty_target_is_refused(host, document, git_env):
    (host / "my-study-writing").mkdir()
    (host / "my-study-writing" / "notes.txt").write_text("mine\n", encoding="utf-8")
    before = snapshot(host)
    result = run(host, git_env, "--from", str(document))
    assert result.returncode != 0
    assert "not empty" in result.stderr
    assert snapshot(host) == before


def test_a_dir_other_than_the_layouts_is_refused(host, document, git_env):
    assert run(host, git_env, "--from", str(document)).returncode == 0
    before = snapshot(host)
    result = run(host, git_env, "--from", str(document), "--dir", "second-document")
    assert result.returncode != 0
    assert "my-study-writing" in result.stderr
    assert snapshot(host) == before


@pytest.mark.parametrize("gh", ["missing", "logged-out", "refused"])
def test_create_without_a_working_gh_changes_nothing(host, git_env, tmp_path, gh):
    """Exit before anything is written, and say both ways forward."""
    if gh == "missing":
        env = path_of(git_env, tmp_path / "empty")
    else:
        env = path_of(git_env, fake_gh(tmp_path / "bin", logged_in=gh != "logged-out"))
    before = snapshot(host)

    result = run(host, env)
    assert result.returncode != 0
    assert "gh auth login" in result.stderr and "--from" in result.stderr
    if gh == "refused":
        assert "refused: repo create" in result.stderr  # got as far as asking
    assert snapshot(host) == before
    assert sorted(p.name for p in host.iterdir()) == [".gitignore", "setup_nested.py"]


def test_the_script_never_writes_doc_repo(host, document, git_env):
    """layout.toml is the source of DOC_REPO; an absolute path in .env would be wrong on
    every other clone and would override the layout everywhere it was copied."""
    assert run(host, git_env, "--from", str(document)).returncode == 0
    assert not (host / ".env").exists()
    assert "DOC_REPO" not in (host / "layout.toml").read_text(encoding="utf-8")


def test_create_uses_the_template_privately_and_moves_the_clone_into_place(
        host, git_env, tmp_path):
    """gh clones into ./<name>; the script stages that and moves it to --dir, leaving no
    staging directory behind in the host."""
    bin_dir = fake_gh(tmp_path / "bin", creates=True)
    env = git_env | {"PATH": os.pathsep.join([str(bin_dir), str(Path(shutil.which("git")).parent)])}

    result = run(host, env, "--dir", "writing")
    assert result.returncode == 0, result.stderr
    calls = (bin_dir / "gh_calls.txt").read_text(encoding="utf-8")
    assert ("repo create someone/writing --template c-energie/writing-template "
            "--private --clone") in calls
    assert (host / "writing" / ".git").exists()
    assert layout(host)["nested_remote"] == "https://github.com/someone/writing.git"
    assert sorted(p.name for p in host.iterdir()) == [
        ".gitignore", "layout.toml", "setup_nested.py", "writing"]
