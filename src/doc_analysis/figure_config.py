"""Which figures and tables a notebook run is allowed to write.

A notebook re-run regenerates every artefact it can, which is rarely what you want: most
runs are exploratory, and writing into `$DOC_REPO` on each one churns committed PNGs
and the LaTeX tree. The old answer was a `SAVE_FIGURES = False` constant per notebook,
which is all-or-nothing and has to be flipped by hand in the source.

This module replaces that with one file, `figures_config.toml` at the repo root::

    default = false        # what a name not yet listed here does
    save_figures = true    # master switch; false stops every figure
    save_tables = true

    [dataset_assessment.figures]
    coverage_timeline = true
    degree_day_scatter = false

    [dataset_assessment.tables]
    cohort_summary = true

A name that is not listed yet is **recorded with the `default` value and that value is
honoured on the spot** — there is no special case for the first run. The shipped
`default = true`, so a newly named figure saves on sight and appends itself to the config
as `true`; set `default = false` to have new figures record themselves as off and wait for
you to switch them on.

New keys are appended textually rather than by re-serialising the document, so hand-written
comments, ordering and grouping survive. Reading is stdlib `tomllib`: this package carries
no dependency for it.
"""

import argparse
import os
import re
import sys
import tomllib
from pathlib import Path

CONFIG_ENV = "FIGURES_CONFIG"
CONFIG_NAME = "figures_config.toml"

# Repo-relative default, resolved the same way as DEFAULT_HTML_DIR in save_figure.
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / CONFIG_NAME

FIGURES = "figures"
TABLES = "tables"
MASTER_KEY = {FIGURES: "save_figures", TABLES: "save_tables"}

DEFAULT_KEY = "default"

_BOOTSTRAP_TEMPLATE = """\
# Which figures and tables a notebook run may write. See doc_analysis.figure_config.
#
# A name not listed here is appended with the `{default_key}` value below and that value is
# honoured immediately. Flip an entry to false to stop that artefact being written; flip a
# master switch to false to stop a whole kind at once.
#
# Sections are notebook stems, each with a figures and a tables block, and fill themselves
# in as notebooks run:
#
#     [clustering_results.figures]
#     cluster_smeter_results = true

{default_key} = {default}
{figures_key} = {figures}
{tables_key} = {tables}
"""


def bootstrap_text(default=True, save_figures=True, save_tables=True):
    """The contents of a fresh config file."""
    literal = {True: "true", False: "false"}
    return _BOOTSTRAP_TEMPLATE.format(
        default_key=DEFAULT_KEY, figures_key=MASTER_KEY[FIGURES],
        tables_key=MASTER_KEY[TABLES], default=literal[bool(default)],
        figures=literal[bool(save_figures)], tables=literal[bool(save_tables)])


_BOOTSTRAP = bootstrap_text()


def config_path(path=None):
    """The config file: argument, else $FIGURES_CONFIG, else the repo default."""
    return Path(path or os.environ.get(CONFIG_ENV) or DEFAULT_CONFIG_PATH)


def load_config(path=None):
    """Parse the config file, or return an empty mapping when it does not exist yet."""
    resolved = config_path(path)
    if not resolved.exists():
        return {}
    with resolved.open("rb") as config_file:
        return tomllib.load(config_file)


def entry_name(name):
    """Config key for an artefact name: the stem, so 'x.png' and 'x' are one entry."""
    return Path(str(name)).stem


def _section_table(config, section, kind):
    """The [section.kind] mapping, or {} when either level is absent."""
    entries = config.get(section)
    if not isinstance(entries, dict):
        return {}
    table = entries.get(kind)
    return table if isinstance(table, dict) else {}


def _append_entry(path, section, kind, key, value):
    """Add `key = value` under [section.kind], creating the file or the block as needed.

    Textual on purpose: re-serialising through a TOML writer would discard the comments
    and grouping that make this file worth hand-editing.
    """
    path = Path(path)
    if not path.exists():
        path.write_text(_BOOTSTRAP, encoding="utf-8")

    text = path.read_text(encoding="utf-8")
    line = f"{key} = {'true' if value else 'false'}\n"
    header = f"[{section}.{kind}]"

    start = text.find(f"\n{header}")
    if start == -1 and not text.startswith(header):
        separator = "" if text.endswith("\n\n") else "\n" if text.endswith("\n") else "\n\n"
        path.write_text(f"{text}{separator}{header}\n{line}", encoding="utf-8")
        return path

    # Insert after the block's existing entries: scan to the next table header or EOF.
    block_start = text.index(header) + len(header)
    next_header = re.search(r"^\s*\[", text[block_start:], re.MULTILINE)
    block_end = block_start + (next_header.start() if next_header else len(text[block_start:]))

    block = text[block_start:block_end]
    trailing = len(block) - len(block.rstrip("\n"))
    insert_at = block_end - trailing
    joiner = "" if text[:insert_at].endswith("\n") else "\n"
    path.write_text(f"{text[:insert_at]}{joiner}{line}{text[insert_at:]}", encoding="utf-8")
    return path


def is_enabled(section, name, kind=FIGURES, path=None, record=True):
    """Whether this artefact may be written, recording it when it is not yet listed.

    section is the notebook (its stem by convention), name the figure/table name with or
    without an extension, kind "figures" or "tables". An unlisted name is appended with
    the config's `default` (true unless set otherwise) and that value is returned, so the
    config self-populates and a newly named artefact is saved rather than silently missed.
    """
    resolved = config_path(path)
    config = load_config(resolved)
    key = entry_name(name)

    table = _section_table(config, section, kind)
    if key in table:
        listed = bool(table[key])
    else:
        listed = bool(config.get(DEFAULT_KEY, True))
        if record:
            _append_entry(resolved, section, kind, key, listed)

    # The master switch can only ever veto: it never turns a per-artefact false on.
    return listed and bool(config.get(MASTER_KEY[kind], True))


def _ask(question, default):
    """Yes/no prompt defaulting to *default* when the answer is empty."""
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        answer = input(f"{question} {suffix} ").strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("  Please answer y or n.")


def init_config(path=None, default=None, save_figures=None, save_tables=None,
                force=False):
    """Write a fresh config file, asking for any flag not supplied.

    Returns the path written, or None when an existing file was left alone.
    """
    resolved = config_path(path)
    if resolved.exists() and not force:
        print(f"{resolved} already exists; leaving it alone (use --force to replace it).")
        return None

    if default is None:
        print("A figure or table not yet listed in the config takes this value, and is\n"
              "recorded with it. true saves new artefacts on sight; false records them\n"
              "as off and waits for you to switch them on.")
        default = _ask(f"  {DEFAULT_KEY} =", True)
    if save_figures is None:
        save_figures = _ask(f"  {MASTER_KEY[FIGURES]} = (master switch for figures)", True)
    if save_tables is None:
        save_tables = _ask(f"  {MASTER_KEY[TABLES]} = (master switch for tables)", True)

    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(bootstrap_text(default, save_figures, save_tables),
                        encoding="utf-8")
    print(f"Wrote {resolved}\n"
          f"  {DEFAULT_KEY} = {str(bool(default)).lower()}, "
          f"{MASTER_KEY[FIGURES]} = {str(bool(save_figures)).lower()}, "
          f"{MASTER_KEY[TABLES]} = {str(bool(save_tables)).lower()}\n"
          f"Sections fill themselves in as notebooks run.")
    return resolved


def _flag(parser, name, help_text):
    """--x / --no-x pair defaulting to None, so 'unset' can mean 'ask'."""
    group = parser.add_mutually_exclusive_group()
    group.add_argument(f"--{name}", dest=name.replace("-", "_"), action="store_true",
                       default=None, help=help_text)
    group.add_argument(f"--no-{name}", dest=name.replace("-", "_"),
                       action="store_false", default=None,
                       help=argparse.SUPPRESS)


def main():
    parser = argparse.ArgumentParser(
        description="Create figures_config.toml, prompting for the global flags.")
    parser.add_argument("--path", type=Path, default=None,
                        help="Where to write it (default: $FIGURES_CONFIG, else the "
                             "repo's figures_config.toml)")
    _flag(parser, "default", "Value taken by an artefact not yet listed (--no-default for false)")
    _flag(parser, "save-figures", "Master switch for figures (--no-save-figures for false)")
    _flag(parser, "save-tables", "Master switch for tables (--no-save-tables for false)")
    parser.add_argument("--force", action="store_true",
                        help="Replace an existing config instead of leaving it alone")
    args = parser.parse_args()

    try:
        init_config(path=args.path, default=args.default,
                    save_figures=args.save_figures,
                    save_tables=args.save_tables, force=args.force)
    except (EOFError, KeyboardInterrupt):
        # Non-interactive shell, or the user gave up: say how to skip the prompts.
        print("\nNo answer given. Pass --default / --save-figures / --save-tables to run "
              "without prompting.", file=sys.stderr)
        return 1
    # Finding a config already in place is the desired state, not a failure: this is safe
    # to put in a setup script and run twice.
    return 0
