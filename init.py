#!/usr/bin/env python3
"""Fill this template's placeholders in, write your `.env`, then delete itself.

GitHub's "Use this template" copies files verbatim — it cannot substitute a project name
or an author — so that job lands here. Run once, immediately after creating your
repository:

    python init.py

It asks for each answer in turn. To run it unattended, give them as flags instead
(`python init.py --help`): a flag's value is used as-is, and with no terminal on stdin
anything left out takes its default or, if it is required, stops the script.

The **import package stays `doc_analysis`**, deliberately. Only the distribution name in
`pyproject.toml` is yours to choose: renaming the package directory would rewrite every
`import` in `src/`, `tests/` and your notebooks for no gain, and the two names are
independent in Python anyway (`pillow` imports as `PIL`, `scikit-learn` as `sklearn`).

Nothing outside this directory is touched, and the script refuses to run twice.
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST_TOKEN = "PACKAGE-NAME"
AUTHOR_TOKEN = "<<AUTHOR>>"
# Tests only this script, and spells out the placeholder tokens: left behind, it would be
# rewritten into nonsense and then skip forever.
OWN_TEST = ROOT / "tests" / "test_init.py"

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
    parser.add_argument("--backend",
                        type=checked(lambda answer: answer in BACKENDS, BACKEND_HINT,
                                     lambda value: value.strip().lower()),
                        help=f"plotting backend, one of {', '.join(BACKENDS)} "
                             f"(default: {BACKENDS[0]})")
    return parser.parse_args(argv)


def files():
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        if path == Path(__file__).resolve() or path == OWN_TEST:
            continue
        yield path


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
    doc_repo = args.doc_repo
    if doc_repo is None:
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

    changed = 0
    for path in files():
        text = original = path.read_text(encoding="utf-8")
        text = text.replace(DIST_TOKEN, distribution)
        text = text.replace(AUTHOR_TOKEN, author)
        if text != original:
            path.write_text(text, encoding="utf-8")
            changed += 1

    print(f"\nRewrote {changed} file(s). The package stays importable as `doc_analysis`.")

    if doc_repo:
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
