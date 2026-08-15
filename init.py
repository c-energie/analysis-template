#!/usr/bin/env python3
"""Fill this template's placeholders in, write your `.env`, then delete itself.

GitHub's "Use this template" copies files verbatim — it cannot substitute a project name
or an author — so that job lands here. Run once, immediately after creating your
repository:

    python init.py

The **import package stays `doc_analysis`**, deliberately. Only the distribution name in
`pyproject.toml` is yours to choose: renaming the package directory would rewrite every
`import` in `src/`, `tests/` and your notebooks for no gain, and the two names are
independent in Python anyway (`pillow` imports as `PIL`, `scikit-learn` as `sklearn`).

Nothing outside this directory is touched, and the script refuses to run twice.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST_TOKEN = "PACKAGE-NAME"
AUTHOR_TOKEN = "<<AUTHOR>>"

SUFFIXES = {".py", ".toml", ".md", ".ipynb", ".cfg", ".txt"}
SKIP_DIRS = {".git", ".github", ".venv", "build", "dist", "__pycache__"}

# Distribution names: PEP 503 normalises to these, so ask for one directly.
VALID_DISTRIBUTION = re.compile(r"^[a-z][a-z0-9-]*$")

# The plotting backends, as pyproject extras. plotly first: it is the default answer.
BACKENDS = ("plotly", "matplotlib")


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


def files():
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        if path.name == Path(__file__).name:
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


def main():
    pyproject = ROOT / "pyproject.toml"
    if DIST_TOKEN not in pyproject.read_text(encoding="utf-8"):
        print("No placeholders left — this template has already been initialised.")
        return 1

    print(__doc__.splitlines()[0] + "\n")
    distribution = ask("Project name (distribution, e.g. gridflex-analysis)",
                       validator=VALID_DISTRIBUTION.match,
                       hint="Lower case, digits and dashes, starting with a letter.")
    author = ask("Author")
    doc_repo = ask("Path to your document repo (blank to set DOC_REPO later)",
                   required=False)

    print("\n  Plotting backend. plotly is preferred: one figure object produces the\n"
          "  committed PNG and an interactive HTML export, so the PDF and anything you\n"
          "  publish cannot drift. matplotlib writes static PNGs only; everything else\n"
          "  works the same. Reversible - it only decides which extra you install.")
    backend = ask("Backend", default="plotly",
                  validator=lambda answer: answer.lower() in BACKENDS,
                  hint=f"One of: {', '.join(BACKENDS)}.").lower()

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
    print("  * Add your analysis stack as an extra in pyproject.toml — keep it out of the")
    print("    package itself, so the tooling stays installable on its own.")

    Path(__file__).unlink()
    print("\nDeleted init.py.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (EOFError, KeyboardInterrupt):
        print("\nAborted; nothing was changed.", file=sys.stderr)
        sys.exit(1)
