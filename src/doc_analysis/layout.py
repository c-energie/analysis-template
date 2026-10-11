"""Read `layout.toml`: where the document repo sits when this repo hosts it.

In the nested layout (`analysis-hosts-writing`) the document repo is a separate repo
cloned into a gitignored subdirectory of this one, and the committed `layout.toml` says
which:

    layout = "analysis-hosts-writing"
    nested_dir = "my-study-writing"
    nested_remote = "https://github.com/<owner>/my-study-writing.git"

`document_repo()` falls back to `<root>/<nested_dir>` when neither the environment nor a
`.env` sets `DOC_REPO`. The location is a fact about the project, not the machine, so it
is committed rather than written into `.env` per clone — and a relative `DOC_REPO` in
`.env` is no substitute, because it would resolve against the notebook's working
directory. See docs/adr/0001-doc-repo-from-layout.md.

The file is found the way `.env` is: the nearest one above the working directory, so it
is reached from the root, from `notebooks/` and from inside the nested repo itself; then,
for a notebook that called `notebook_setup()`, the checkout the package is installed from.

`setup_nested.py` writes the file and cannot import this package (it runs before the
install), so it carries its own reader. Keep the two in step: the keys and the values of
`layout` are a contract shared, mirrored, with writing-template's `writing-hosts-analysis`.

Stdlib only (`tomllib`).
"""

import tomllib
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import NamedTuple

LAYOUT_FILENAME = "layout.toml"

#: This repo hosts the document repo. The only layout this module resolves.
HOSTS_WRITING = "analysis-hosts-writing"
#: The document repo hosts this one — writing-template's side of the same contract. A
#: file declaring it belongs to the document repo, so the search walks past it.
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
    return Layout(path, data["layout"], nested_dir, data.get("nested_remote"))


def find_layout(start=None, fallback=None):
    """The nearest `layout.toml` declaring `analysis-hosts-writing`, or None.

    Searched upward from `start` (default: the cwd), then in `fallback` — the checkout
    `notebook_setup()` falls back to for `.env`, for the same reason: a kernel started
    beside the repo never walks into it. A file declaring the other side of the contract
    is walked past, not returned: it describes the document repo, not this one.
    """
    base = Path(start).resolve() if start else Path.cwd().resolve()
    candidates = [directory / LAYOUT_FILENAME for directory in (base, *base.parents)]
    if fallback is not None:
        candidates.append(Path(fallback).resolve() / LAYOUT_FILENAME)
    for candidate in candidates:
        if candidate.is_file():
            layout = read_layout(candidate)
            if layout.layout == HOSTS_WRITING:
                return layout
    return None
