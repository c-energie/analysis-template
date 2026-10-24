"""Read `layout.toml`: where the document repo sits in a nested layout, either side up.

In the nested layout (`analysis-hosts-writing`) the document repo is a separate repo
cloned into a gitignored subdirectory of this one, and the committed `layout.toml` says
which:

    layout = "analysis-hosts-writing"
    nested_dir = "my-study-writing"
    nested_remote = "https://github.com/<owner>/my-study-writing.git"

`target_documents()` puts the document at `<root>/<nested_dir>`; a `DOC_REPO` from the
environment or a `.env` must then name that same directory, or the save raises
(docs/adr/0003-target-documents-from-workspace.md). The location is a fact about the project, not the machine, so it
is committed rather than written into `.env` per clone — and a relative `DOC_REPO` in
`.env` is no substitute, because it would resolve against the notebook's working
directory. See docs/adr/0001-doc-repo-from-layout.md.

The file is found nearly the way `.env` is: the nearest one above the working directory,
but never above this repo's root, so it is reached from the root, from `notebooks/` and
from inside the nested repo itself; then, for a notebook that called `notebook_setup()`,
the active checkout it recorded (the cwd's, else the one the package is installed from).

`setup_nested.py` writes the file and cannot import this package (it runs before the
install), so it carries its own reader.

The same contract read from the other side is the last fallback: when this repo is the
nested repo, cloned into a document repo whose own `layout.toml` declares
`writing-hosts-analysis` and names this repo's directory as its `nested_dir`, the document
repo is simply the parent directory (`find_host_layout`). One parent, never further: a
file two levels up describes some other nesting, not this one. See
docs/adr/0002-doc-repo-from-host-layout.md. Keep the two in step: the keys and the values of
`layout` are a contract shared, mirrored, with writing-template's `writing-hosts-analysis`.

Stdlib only (`tomllib`).
"""

import tomllib
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import NamedTuple

from doc_analysis.env import CHECKOUT_MARKER

LAYOUT_FILENAME = "layout.toml"

#: This repo hosts the document repo: `find_layout` resolves it to `<root>/<nested_dir>`.
HOSTS_WRITING = "analysis-hosts-writing"
#: The document repo hosts this one — writing-template's side of the same contract. A
#: file declaring it belongs to the document repo, so `find_layout` walks past it; only
#: `find_host_layout`, looking one directory above this repo's root, reads it.
HOSTED_BY_WRITING = "writing-hosts-analysis"
LAYOUTS = (HOSTS_WRITING, HOSTED_BY_WRITING)

REQUIRED_KEYS = ("layout", "nested_dir")
KNOWN_KEYS = (*REQUIRED_KEYS, "nested_remote")


class Layout(NamedTuple):
    file: Path
    layout: str
    nested_dir: str
    nested_remote: str | None

    @property
    def root(self):
        return self.file.parent

    @property
    def nested_path(self):
        return self.root / self.nested_dir


def read_layout(path):
    """Parse and validate one `layout.toml`; raise ValueError naming the file and key.

    Unknown keys are errors, not warnings: a misspelt `nested_dir` silently ignored would
    leave `DOC_REPO` unset with nothing pointing at the typo.
    """
    path = Path(path)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path}: not valid TOML ({exc}).") from None

    unknown = sorted(set(data) - set(KNOWN_KEYS))
    if unknown:
        raise ValueError(f"{path}: unknown key(s) {', '.join(unknown)}; "
                         f"expected only {', '.join(KNOWN_KEYS)}.")
    for key in KNOWN_KEYS:
        if key in REQUIRED_KEYS and key not in data:
            raise ValueError(f"{path}: `{key}` is missing.")
        if key in data and (not isinstance(data[key], str) or not data[key].strip()):
            raise ValueError(f"{path}: `{key}` must be a non-empty string.")
    if data["layout"] not in LAYOUTS:
        raise ValueError(f"{path}: layout = {data['layout']!r} is not one of "
                         f"{', '.join(LAYOUTS)}.")

    nested_dir = data["nested_dir"]
    # Judged under both path flavours: a `C:\...` committed on Windows is just as absolute
    # on every other clone, and `..` would put the "nested" repo outside the host.
    for flavour in (PurePosixPath, PureWindowsPath):
        pure = flavour(nested_dir)
        if pure.is_absolute() or pure.anchor or ".." in pure.parts:
            raise ValueError(f"{path}: nested_dir = {nested_dir!r} must be a path inside "
                             f"the repo, relative to {path.parent}.")
        # "." or "./" names the host itself: accepted here it would only fail later as
        # "no Sections/", and setup_nested.py already refuses it.
        if not pure.parts or pure.parts == (".",):
            raise ValueError(f"{path}: nested_dir = {nested_dir!r} must name a "
                             f"subdirectory of {path.parent}, not the repo itself.")
    return Layout(path, data["layout"], nested_dir, data.get("nested_remote"))


def find_layout(start=None, fallback=None):
    """The nearest `layout.toml` declaring `analysis-hosts-writing`, or None.

    Searched upward from `start` (default: the cwd) as far as this repo's root — the
    nearest directory holding a `pyproject.toml` — then in `fallback`, the checkout
    `notebook_setup()` falls back to for `.env`, for the same reason: a kernel started
    beside the repo never walks into it. A file declaring the other side of the contract
    is walked past, not returned: it describes the document repo, not this one.

    Never past the root: every file reached is parsed strictly, so a foreign
    `layout.toml` higher up would otherwise fail every save, an exported `DOC_REPO`
    included. Outside any checkout, only `fallback` is looked at, for the same reason.
    """
    base = Path(start).resolve() if start else Path.cwd().resolve()
    upward = (base, *base.parents)
    root = next((i for i, directory in enumerate(upward)
                 if (directory / CHECKOUT_MARKER).is_file()), None)
    candidates = ([] if root is None
                  else [directory / LAYOUT_FILENAME for directory in upward[:root + 1]])
    if fallback is not None:
        candidates.append(Path(fallback).resolve() / LAYOUT_FILENAME)
    for candidate in candidates:
        if candidate.is_file():
            layout = read_layout(candidate)
            if layout.layout == HOSTS_WRITING:
                return layout
    return None


class HostLayout(NamedTuple):
    """A host repo's `layout.toml` one directory above `root`, this repo's root."""
    layout: Layout
    root: Path

    @property
    def matches(self):
        # Compared as paths, so `nested_dir = "x/"` still names the directory `x`. A
        # nested_dir naming some other directory means the host nests a different repo
        # (or this one was renamed): the parent is then not known to be our document.
        return Path(self.layout.nested_dir) == Path(self.root.name)


def find_host_layout(start=None, fallback=None):
    """The host repo's `writing-hosts-analysis` layout one level above this repo, or None.

    This repo's root is the nearest directory above `start` (default: the cwd) holding a
    `pyproject.toml` — which reaches it from the root and from `notebooks/` — then
    `fallback`, the active checkout `notebook_setup()` records, for a kernel started
    outside the repo. Only the parent of that root is looked at.

    A layout whose `nested_dir` names another directory is still returned, with `matches`
    false, so the "DOC_REPO is not set" error can name both names; one that matches wins
    over one that does not.
    """
    base = Path(start).resolve() if start else Path.cwd().resolve()
    roots = [directory for directory in (base, *base.parents)
             if (directory / CHECKOUT_MARKER).is_file()][:1]
    if fallback is not None:
        roots.append(Path(fallback).resolve())

    found = []
    for root in roots:
        candidate = root.parent / LAYOUT_FILENAME
        # root.parent == root only at a filesystem root, which hosts nothing.
        if root.parent == root or not candidate.is_file():
            continue
        # The parent is whatever directory the checkout was cloned into, so its
        # layout.toml is usually not ours: parsed strictly, a foreign one would fail every
        # save, an exported DOC_REPO included. Only a file declaring this side of the
        # contract is held to it.
        try:
            declared = tomllib.loads(candidate.read_text(encoding="utf-8")).get("layout")
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            continue
        if declared == HOSTED_BY_WRITING:
            found.append(HostLayout(read_layout(candidate), root))
    return next((host for host in found if host.matches), found[0] if found else None)
