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

Loaded once, on import of this package. Stdlib only: `KEY=value` does not justify a
dependency, and this file is short enough to read in full.
"""

import os
from pathlib import Path

ENV_FILENAME = ".env"

#: Points `load_env` at one specific file instead of the upward search. Same name
#: doc-publish uses, so one setting steers both tools.
ENV_PATH_VAR = "DOC_ENV"


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


def load_env(start=None, override=False):
    """Merge a `.env` into `os.environ`; returns the file used, or None.

    Existing variables are left alone unless override is set — the file is a default
    for the checkout, not an authority over the shell that launched it.
    """
    path = find_env_file(start)
    if path is None:
        return None

    for key, value in parse_env(path.read_text(encoding="utf-8")).items():
        if override:
            os.environ[key] = value
        else:
            os.environ.setdefault(key, value)
    return path
