#!/usr/bin/env python3
"""Fill this template's placeholders in, rename the package, then delete itself.

GitHub's "Use this template" copies files verbatim — it cannot rename a package
directory or substitute an author — so that job lands here. Run once, immediately after
creating your repository:

    python init.py

Nothing outside this directory is touched, and the script refuses to run twice.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PACKAGE_TOKEN = "PACKAGE_NAME"
DIST_TOKEN = "PACKAGE-NAME"

SUFFIXES = {".py", ".toml", ".md", ".ipynb", ".cfg", ".txt"}
SKIP_DIRS = {".git", ".github", ".venv", "build", "dist", "__pycache__"}

VALID_PACKAGE = re.compile(r"^[a-z][a-z0-9_]*$")


def ask(prompt, default=None, validator=None, hint=""):
    suffix = f" [{default}]" if default else ""
    while True:
        answer = input(f"  {prompt}{suffix}: ").strip() or (default or "")
        if not answer:
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


def main():
    package_dir = ROOT / "src" / PACKAGE_TOKEN
    if not package_dir.is_dir():
        print("src/PACKAGE_NAME not found — this template has already been initialised.")
        return 1

    print(__doc__.splitlines()[0] + "\n")
    package = ask("Package name (importable, e.g. gridflex_figures)",
                  validator=VALID_PACKAGE.match,
                  hint="Lower case, digits and underscores, starting with a letter.")
    author = ask("Author")

    # Distribution name mirrors the package with dashes: the usual Python convention.
    distribution = package.replace("_", "-")

    changed = 0
    for path in files():
        text = original = path.read_text(encoding="utf-8")
        text = text.replace(DIST_TOKEN, distribution)
        text = text.replace(PACKAGE_TOKEN, package)
        text = text.replace("<<AUTHOR>>", author)
        if text != original:
            path.write_text(text, encoding="utf-8")
            changed += 1

    package_dir.rename(ROOT / "src" / package)

    print(f"\nRewrote {changed} file(s); renamed src/{PACKAGE_TOKEN} -> src/{package}.")
    print("\nNext:")
    print("  * Point DOC_REPO at your document repository:")
    print('        $env:DOC_REPO = "<...>/my-document"     # PowerShell')
    print('        export DOC_REPO=<...>/my-document       # bash')
    print("  * uv sync --extra dev --extra notebooks   (or pip install -e '.[dev,notebooks]')")
    print("  * Run notebooks/example/example_figure.ipynb to prove the wiring, then")
    print("    `check-figure-parity --snapshot` to record the baseline.")
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
