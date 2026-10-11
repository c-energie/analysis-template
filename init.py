#!/usr/bin/env python3
"""Fill this template's placeholders in, write your `.env`, then delete itself.

GitHub's "Use this template" copies files verbatim — it cannot substitute a project name
or an author — so that job lands here. Run once, immediately after creating your
repository:

    python init.py

It asks for each answer in turn. To run it unattended, give them as flags instead
(`python init.py --help`): a flag's value is used as-is, and with no terminal on stdin
anything left out takes its default or, if it is required, stops the script.

One question is whether to nest the document repo inside this one (`--nest`). Yes hands
over to `setup_nested.py`, which creates it in a gitignored subdirectory and records it in
`layout.toml`; no `DOC_REPO` path is asked for then.

The **import package stays `doc_analysis`**, deliberately. Only the distribution name in
`pyproject.toml` is yours to choose: renaming the package directory would rewrite every
`import` in `src/`, `tests/` and your notebooks for no gain, and the two names are
independent in Python anyway (`pillow` imports as `PIL`, `scikit-learn` as `sklearn`).

Nothing outside this directory is touched, nor anything inside a nested repo — a
subdirectory with its own `.git`, or the one `layout.toml` names — and the script refuses
to run twice.
"""
import argparse
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST_TOKEN = "PACKAGE-NAME"
AUTHOR_TOKEN = "<<AUTHOR>>"
# Tests only this script, and spells out the placeholder tokens: left behind, it would be
# rewritten into nonsense and then skip forever.
OWN_TEST = ROOT / "tests" / "test_init.py"
# Stays after init.py is gone: a fresh clone of a nested layout runs it to restore.
SETUP_NESTED = ROOT / "setup_nested.py"
LAYOUT_FILE = ROOT / "layout.toml"

SUFFIXES = {".py", ".toml", ".md", ".ipynb", ".cfg", ".txt"}
SKIP_DIRS = {".git", ".github", ".venv", "build", "dist", "__pycache__"}

# Distribution names: PEP 503 normalises to these, so ask for one directly.
VALID_DISTRIBUTION = re.compile(r"^[a-z][a-z0-9-]*$")

# The plotting backends, as pyproject extras. plotly first: it is the default answer.
BACKENDS = ("plotly", "matplotlib")

DISTRIBUTION_HINT = "Lower case, digits and dashes, starting with a letter."
BACKEND_HINT = f"One of: {', '.join(BACKENDS)}."


def ask(prompt, default=None, validator=None, hint="", required=True):
    suffix = f" [{default}]" if default else ""
    while True:
        answer = input(f"  {prompt}{suffix}: ").strip() or (default or "")
        if not answer:
            if not required:
                return ""
            print("    Required.")
            continue
        if validator and not validator(answer):
            print(f"    {hint}")
            continue
        return answer


def at_terminal():
    """Whether a person can answer a prompt on stdin. isatty() alone is wrong both ways on
    Windows: the NUL device claims to be a TTY, so input() hit EOF and said "Aborted";
    and Git Bash's mintty hands Python a pipe, so a person there would be refused."""
    if sys.stdin is None:
        return False
    if sys.platform != "win32":
        return sys.stdin.isatty()
    import ctypes
    import msvcrt
    from ctypes import wintypes
    try:
        handle = msvcrt.get_osfhandle(sys.stdin.fileno())
    except (OSError, ValueError):
        return False
    kernel32 = ctypes.windll.kernel32
    kernel32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    if kernel32.GetConsoleMode(handle, ctypes.byref(wintypes.DWORD())):
        return True
    # mintty's end of the pty is a named pipe called msys-<hash>-ptyN-from-master
    # (cygwin-... under Cygwin). FileNameInfo is 2: a DWORD length, then UTF-16.
    kernel32.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    info = ctypes.create_string_buffer(4 + 2 * 512)
    if not kernel32.GetFileInformationByHandleEx(handle, 2, info, ctypes.sizeof(info)):
        return False
    length = int.from_bytes(info.raw[:4], "little")
    name = info.raw[4:4 + length].decode("utf-16-le", errors="replace")
    return "-pty" in name and name.endswith("-from-master")


def checked(validator, hint, transform=str.strip):
    """An argparse type that applies the same rule, and hint, as the prompt does. A
    piped answer the prompt rejected used to re-prompt, hit EOF and say only "Aborted"."""
    def check(value):
        value = transform(value)
        if not validator(value):
            raise argparse.ArgumentTypeError(hint)
        return value
    return check


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        epilog="Each flag left out is prompted for at a terminal. Without one, a left-out "
               "--distribution or --author stops the script; the rest take their defaults.")
    parser.add_argument("--distribution", type=checked(VALID_DISTRIBUTION.match,
                                                       DISTRIBUTION_HINT),
                        help="distribution name in pyproject.toml, e.g. gridflex-analysis")
    parser.add_argument("--author", type=checked(bool, "Required."), help="author name")
    parser.add_argument("--doc-repo", type=str.strip,
                        help="path to your document repo, written to .env as DOC_REPO "
                             "(left out: .env is not written)")
    parser.add_argument("--nest", action="store_true",
                        help="nest the document repo inside this one: runs setup_nested.py "
                             "(which needs gh) instead of asking for a DOC_REPO path")
    parser.add_argument("--backend",
                        type=checked(lambda answer: answer in BACKENDS, BACKEND_HINT,
                                     lambda value: value.strip().lower()),
                        help=f"plotting backend, one of {', '.join(BACKENDS)} "
                             f"(default: {BACKENDS[0]})")
    args = parser.parse_args(argv)
    if args.nest and args.doc_repo is not None:
        parser.error("--nest and --doc-repo are alternatives: a nested document repo is "
                     "found from layout.toml, not from DOC_REPO")
    return args


def nested_dir():
    """The nested repo layout.toml names, or None. Read, not trusted: a malformed file
    only means there is no name to skip, and the `.git` check still catches the repo."""
    try:
        name = tomllib.loads(LAYOUT_FILE.read_text(encoding="utf-8")).get("nested_dir")
    except (OSError, tomllib.TOMLDecodeError):
        return None
    return (ROOT / name).resolve() if isinstance(name, str) and name.strip() else None


def files():
    # Pruned while walking, not filtered after: a nested repo is somebody else's history,
    # and a <<…>> token in its files — a writing-template placeholder, say — is not ours
    # to fill. Any subdirectory with its own .git counts, layout.toml or not.
    nested = nested_dir()
    for directory, subdirs, names in os.walk(ROOT):
        here = Path(directory)
        subdirs[:] = [name for name in subdirs
                      if name not in SKIP_DIRS and not (here / name / ".git").exists()
                      and (here / name).resolve() != nested]
        for name in names:
            path = here / name
            if path.suffix not in SUFFIXES:
                continue
            if path == Path(__file__).resolve() or path == OWN_TEST:
                continue
            yield path


def nest():
    """Run setup_nested.py with its defaults; stop here if it did not succeed."""
    result = subprocess.run([sys.executable, str(SETUP_NESTED)], cwd=ROOT,
                            stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        sys.exit("init.py: nesting the document repo did not succeed (see above); nothing "
                 "else was changed. Fix that and run init.py again, or run it without "
                 "--nest and set DOC_REPO.")


def write_env(doc_repo):
    """Write the checkout's .env. Gitignored: it is a per-machine path, not a setting."""
    env_file = ROOT / ".env"
    if env_file.exists():
        print(f"\n{env_file.name} already exists — left alone.")
        return
    env_file.write_text(
        "# Local to this checkout and gitignored: paths here are per-machine.\n"
        "# A variable already set in your shell wins over this file.\n"
        f"DOC_REPO={doc_repo}\n",
        encoding="utf-8",
    )
    print(f"\nWrote {env_file.name} with DOC_REPO={doc_repo}.")


def main(argv=None):
    args = parse_args(argv)
    interactive = at_terminal()
    pyproject = ROOT / "pyproject.toml"
    if DIST_TOKEN not in pyproject.read_text(encoding="utf-8"):
        print("No placeholders left — this template has already been initialised.")
        return 1

    # Checked before anything is written. Without a terminal there is nobody to ask, and
    # input() would only hit EOF and hide which answer was missing.
    missing = [flag for flag, value in (("--distribution", args.distribution),
                                        ("--author", args.author)) if value is None]
    if missing and not interactive:
        sys.exit(f"init.py: no terminal to prompt on; pass {' and '.join(missing)}.")

    print(__doc__.splitlines()[0] + "\n")
    # A flag's value is used as-is and its prompt is not shown.
    distribution = args.distribution or ask(
        "Project name (distribution, e.g. gridflex-analysis)",
        validator=VALID_DISTRIBUTION.match, hint=DISTRIBUTION_HINT)
    author = args.author or ask("Author")
    nested = args.nest
    if not nested and args.doc_repo is None and interactive:
        nested = ask("Nest the document inside this repo? [y/N]", required=False,
                     validator=lambda answer: answer.lower() in ("y", "yes", "n", "no"),
                     hint="y or n.").lower() in ("y", "yes")
    doc_repo = args.doc_repo
    if doc_repo is None and not nested:
        doc_repo = ask("Path to your document repo (blank to set DOC_REPO later)",
                       required=False) if interactive else ""

    backend = args.backend
    if backend is None and interactive:
        print("\n  Plotting backend. plotly is preferred: one figure object produces the\n"
              "  committed PNG and an interactive HTML export, so the PDF and anything you\n"
              "  publish cannot drift. matplotlib writes static PNGs only; everything else\n"
              "  works the same. Reversible - it only decides which extra you install.")
        backend = ask("Backend", default=BACKENDS[0],
                      validator=lambda answer: answer.lower() in BACKENDS,
                      hint=BACKEND_HINT).lower()
    backend = backend or BACKENDS[0]

    # Before the placeholder pass, so a refused gh leaves the template exactly as it was
    # and init.py can simply be run again.
    if nested:
        nest()

    changed = 0
    for path in files():
        text = original = path.read_text(encoding="utf-8")
        text = text.replace(DIST_TOKEN, distribution)
        text = text.replace(AUTHOR_TOKEN, author)
        if text != original:
            path.write_text(text, encoding="utf-8")
            changed += 1

    print(f"\nRewrote {changed} file(s). The package stays importable as `doc_analysis`.")

    if nested:
        print("\nDOC_REPO needs no .env: doc_analysis reads it from layout.toml.")
    elif doc_repo:
        write_env(doc_repo)
    else:
        print("\nNext, copy .env.example to .env and point DOC_REPO at your document repo.")

    print("\nThen:")
    print(f"  * uv sync --extra dev --extra notebooks --extra {backend}")
    print(f"    (or pip install -e '.[dev,notebooks,{backend}]')")
    if backend == "plotly":
        print("  * Run notebooks/example/example_figure.ipynb to prove the wiring, then")
        print("    `check-figure-parity --snapshot` to record the baseline.")
    else:
        # The example notebook is plotly and will not import under this backend; the
        # README carries the matplotlib version of the same six lines.
        print("  * The example notebook is plotly, so it will not run here. Copy the")
        print("    matplotlib usage block from the README into a notebook of your own to")
        print("    prove the wiring, then `check-figure-parity --snapshot`.")
    print("  * Start each notebook with `notebook-skeleton new <section> <name>`.")
    print("  * Add your analysis stack as an extra in pyproject.toml — keep it out of the")
    print("    package itself, so the tooling stays installable on its own.")

    Path(__file__).unlink()
    OWN_TEST.unlink(missing_ok=True)
    print("\nDeleted init.py and its test.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (EOFError, KeyboardInterrupt):
        print("\nAborted; nothing was changed.", file=sys.stderr)
        sys.exit(1)
