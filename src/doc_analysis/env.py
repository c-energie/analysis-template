"""Read a repo-local `.env`, so nothing has to be set at the user or machine level.

The document repo's location is per-checkout, not per-user: the moment a second checkout
exists, a user-level `DOC_REPO` points at the wrong one, and the failure is silent —
figures land in somebody else's document. A file next to the code cannot make that
mistake, and it travels with the checkout instead of living in a shell profile.

Resolution deliberately mirrors `doc_publish.config.load_env`, because the two run
against the same `.env` in the same checkout and a second set of rules would be a trap:

    real environment variable  ->  $DOC_ENV, else the nearest `.env` above the cwd

so CI can export variables with no `.env` present, and a local file never silently
overrides an explicit export:

    DOC_REPO=/tmp/scratch pytest tests -q      # beats .env

Loaded once, on import of this package. `notebook_setup()` widens the search by one
step — the `.env` at the root of the checkout the package is installed from — because a
notebook kernel started at a workspace root sits *beside* the analysis repo, not inside
it, and the upward search never reaches its `.env`. That step is an explicit argument
(`fallback=`), so a plain import keeps exactly the rules above.

Stdlib only: `KEY=value` does not justify a
dependency, and this file is short enough to read in full.
"""

import os
from pathlib import Path

ENV_FILENAME = ".env"

#: Points `load_env` at one specific file instead of the upward search. Same name
#: doc-publish uses, so one setting steers both tools.
ENV_PATH_VAR = "DOC_ENV"

#: The marker of a checkout root. Without it the package is installed from somewhere
#: that is not a source tree (a wheel in site-packages), and no `.env` lives there.
CHECKOUT_MARKER = "pyproject.toml"

#: What the last `load_env` call looked at, for the "DOC_REPO is not set" error: a
#: missing setting is only fixable once the user knows which files were searched.
LAST_SEARCH = {"start": None, "found": None, "fallback": None, "checkout": None}


def parse_env(text):
    """Parse `KEY=value` lines; comments, blanks and a leading `export` are ignored.

    No interpolation and no multi-line values: a path is all this has to carry, and
    anything cleverer would be a dependency wearing thirty lines as a disguise.
    """
    values = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # `export FOO=bar` is common in files shared with a POSIX shell.
        if line.startswith("export "):
            line = line[len("export "):].lstrip()

        key, separator, value = line.partition("=")
        if not separator:
            continue

        value = value.strip()
        # Strip one matching pair of quotes: a Windows path with spaces needs them, and
        # leaving them in produces a path that fails exists() for no visible reason.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]

        key = key.strip()
        if key:
            values[key] = value
    return values


def find_env_file(start=None):
    """The `.env` to use: `$DOC_ENV` if set, else the nearest one above `start`.

    Returns None when there is none — a missing `.env` is not an error here, only a
    missing *setting* is, and that raises later with the variable name in the message.
    """
    explicit = os.environ.get(ENV_PATH_VAR)
    if explicit:
        path = Path(explicit)
        return path if path.is_file() else None

    base = Path(start).resolve() if start else Path.cwd().resolve()
    for directory in (base, *base.parents):
        candidate = directory / ENV_FILENAME
        if candidate.is_file():
            return candidate
    return None


def checkout_root(package_dir=None):
    """The analysis checkout this package is installed from, or None.

    An editable install imports from `<checkout>/src/doc_analysis`, so the checkout is
    two levels up — but only if it holds a `pyproject.toml`. A wheel install sits in
    site-packages, where two levels up is a Python prefix that must never be mistaken
    for a checkout. `package_dir` defaults to this package's own directory; tests pass
    a temporary layout instead of installing anything.
    """
    package_dir = Path(package_dir) if package_dir else Path(__file__).resolve().parent
    root = package_dir.resolve().parents[1]
    return root if (root / CHECKOUT_MARKER).is_file() else None


def load_env(start=None, override=False, fallback=None, skipped_checkout=None):
    """Merge a `.env` into `os.environ`; returns the file used, or None.

    Existing variables are left alone unless override is set — the file is a default
    for the checkout, not an authority over the shell that launched it.

    `fallback` is a directory whose `.env` is used only when the usual resolution finds
    none. Off by default: only `notebook_setup()` opts in, passing the checkout root.

    `skipped_checkout` is where the package is installed from when that is not a checkout,
    so no fallback was possible; it is only recorded, for `describe_search()`. Recording
    it here, in the same update as the rest, keeps the search record whole after one call.
    """
    path = find_env_file(start)
    if path is None and fallback is not None:
        candidate = Path(fallback) / ENV_FILENAME
        path = candidate if candidate.is_file() else None

    LAST_SEARCH.update(
        start=Path(start).resolve() if start else Path.cwd().resolve(),
        found=path,
        fallback=Path(fallback) if fallback is not None else None,
        checkout=Path(skipped_checkout) if skipped_checkout is not None else None,
    )
    if path is None:
        return None

    for key, value in parse_env(path.read_text(encoding="utf-8")).items():
        if override:
            os.environ[key] = value
        else:
            os.environ.setdefault(key, value)
    return path


def describe_search():
    """Where the last `load_env` looked, as lines for the "is not set" error.

    A missing setting is only fixable once the user knows which file was meant to
    carry it — and, for a notebook, why the analysis checkout's `.env` was not reached.
    """
    if LAST_SEARCH["start"] is None:
        return []
    explicit = os.environ.get(ENV_PATH_VAR)
    if explicit:
        lines = [f"${ENV_PATH_VAR} names {explicit}"]
    else:
        lines = [f"searched for {ENV_FILENAME} from {LAST_SEARCH['start']} upward"]

    if LAST_SEARCH["found"] is not None:
        lines.append(f"loaded {LAST_SEARCH['found']}, which does not set it")
    elif LAST_SEARCH["fallback"] is not None:
        lines.append(f"then the analysis checkout: no {LAST_SEARCH['fallback'] / ENV_FILENAME}")
    elif LAST_SEARCH["checkout"] is not None:
        lines.append(
            f"skipped the analysis checkout's {ENV_FILENAME}: doc_analysis is installed "
            f"from {LAST_SEARCH['checkout']}, which has no {CHECKOUT_MARKER} above it — "
            f"a non-editable install. Install the analysis repo editable (uv sync), "
            f"or set ${ENV_PATH_VAR} to its {ENV_FILENAME}."
        )
    return lines
