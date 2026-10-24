"""Read `.claude/workspace.json`: the target documents of a workspace analysis.

A **workspace analysis** is an analysis repo that is a member of a project workspace in
its own right, inside no document repo, attached to zero or more documents. The workspace
records them on the member (c-energie/claude-tools ADR 0002, plus #41's `documents`):

    { "schema": 1, "members": [
        { "dir": "validation", "kind": "analysis", "documents": ["thesis", "paper"] } ] }

Each `documents` entry is a document member's `dir`, relative to the workspace root; `[]`
is no-document mode. See docs/adr/0003-target-documents-from-workspace.md.

The file is found the way claude-tools finds it: the nearest `.claude/workspace.json` at or
above this repo's root, nearest wins, levels never merge, and a malformed nearest file
stops the walk instead of being skipped — skipping it would read some outer workspace's
members because of a typo in this one. Here it is an error, not a fallback: a broken file
may be the one that names this analysis's documents, and saving into `outputs/` instead
would look like success.

The file is not ours. project-workspace owns `members` and every other key belongs to
some other plugin, so — unlike `layout.toml` and `figures_config.toml` — unknown keys are
ignored here, and only the two fields this reads (`dir`, `documents`, on an analysis
member) are held to a shape. Anything stricter would reject files this package has no
authority over. Read-only: nothing here ever writes the file; `attach-analysis` and
`detach-analysis` do.

Stdlib only (`json`).
"""

import json
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import NamedTuple

from doc_analysis.env import CHECKOUT_MARKER

WORKSPACE_FILE = Path(".claude") / "workspace.json"
ANALYSIS_KIND = "analysis"


class WorkspaceAnalysis(NamedTuple):
    """This repo's analysis member in the nearest workspace."""
    file: Path
    #: The member's `dir` as written: the analysis's name in every manifest it writes.
    member_dir: str
    #: (entry as written, resolved path) per `documents` entry, in the file's order.
    documents: tuple

    @property
    def root(self):
        return self.file.parent.parent


def find_workspace_file(start):
    """The nearest `.claude/workspace.json` at or above `start`, or None.

    Unlike `find_layout` the walk does not stop at this repo's root: the workspace wraps
    its members, so its file is always above them.
    """
    base = Path(start).resolve()
    for directory in (base, *base.parents):
        candidate = directory / WORKSPACE_FILE
        if candidate.is_file():
            return candidate
    return None


def read_workspace(path):
    """Parse one `workspace.json`; raise ValueError naming the file when it is not an object."""
    path = Path(path)
    try:
        # utf-8-sig: a file saved by a Windows editor may carry a BOM, which json rejects.
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"{path}: not valid JSON ({exc}).") from None
    if not isinstance(data, dict):
        raise ValueError(f"{path}: the top level is not a JSON object.")
    members = data.get("members", [])
    if not isinstance(members, list):
        raise ValueError(f"{path}: `members` must be a list.")
    return data


def _check_entry(path, member_dir, entry):
    """Raise unless a `documents` entry is a relative path inside the workspace."""
    where = f"{path}: member {member_dir!r}, documents entry {entry!r}"
    if not isinstance(entry, str) or not entry.strip():
        raise ValueError(f"{where} must be a non-empty string, a document member's dir.")
    # Judged under both flavours, as layout.toml's nested_dir is: a `C:\...` written on
    # Windows is absolute everywhere, and `..` would name a document outside the workspace.
    for flavour in (PurePosixPath, PureWindowsPath):
        pure = flavour(entry)
        if pure.is_absolute() or pure.anchor or ".." in pure.parts:
            raise ValueError(f"{where} must be relative to the workspace root, "
                             f"{path.parent.parent}.")


def _member_for(path, data, root):
    """This repo's analysis member in a parsed file, or None when it has none."""
    workspace_root = path.parent.parent.resolve()
    for member in data.get("members", []):
        if not isinstance(member, dict) or member.get("kind") != ANALYSIS_KIND:
            continue
        member_dir = member.get("dir")
        if not isinstance(member_dir, str) or not member_dir.strip():
            continue
        # By path, not by name: what a directory is is decided by the file, and a name
        # that merely matches would make some other analysis's documents this one's.
        if (workspace_root / member_dir).resolve() == root:
            return member
    return None


def find_workspace_analysis(start=None, fallback=None):
    """This repo's analysis member and its resolved `documents`, or None.

    This repo's root is the nearest directory above `start` (default: the cwd) holding a
    `pyproject.toml`, then `fallback`, the active checkout `notebook_setup()` records, for a
    kernel started outside the repo — the same roots `find_host_layout` uses. The first
    root that is an analysis member of its workspace wins.

    None when no workspace is found, when the workspace lists no analysis member at this
    path (a nested analysis need not be listed: `layout.toml` places it), or when the
    member carries no `documents` key at all — one written before claude-tools#41, which
    attaches it to nothing yet. An empty list is different: it says this analysis feeds no
    document, and is returned as such.

    Raises ValueError naming the file and entry when the list is malformed, and
    NotADirectoryError when an entry is not a document repo — a missing directory or one
    with no Sections/ (or legacy Chapters/).
    """
    base = Path(start).resolve() if start else Path.cwd().resolve()
    roots = [directory for directory in (base, *base.parents)
             if (directory / CHECKOUT_MARKER).is_file()][:1]
    if fallback is not None:
        roots.append(Path(fallback).resolve())

    for root in roots:
        path = find_workspace_file(root)
        if path is None:
            continue
        member = _member_for(path, read_workspace(path), root)
        if member is None or "documents" not in member:
            continue
        entries = member["documents"]
        if not isinstance(entries, list):
            raise ValueError(f"{path}: member {member['dir']!r}: `documents` must be a "
                             f"list of document dirs.")
        documents, seen = [], set()
        for entry in entries:
            _check_entry(path, member["dir"], entry)
            document = path.parent.parent / entry
            # Two spellings of one directory ("thesis", "thesis/") would write every
            # figure twice into the same file.
            if document.resolve() in seen:
                continue
            seen.add(document.resolve())
            if not document.is_dir():
                raise NotADirectoryError(
                    f"{path}: member {member['dir']!r} lists document {entry!r}, but "
                    f"{document} does not exist. Restore it (setup-project-workspace "
                    f"restore), or detach it (detach-analysis).")
            if not any((document / name).is_dir() for name in ("Sections", "Chapters")):
                raise NotADirectoryError(
                    f"{path}: member {member['dir']!r} lists document {entry!r}, but "
                    f"{document} does not look like a document repo (no Sections/ "
                    f"directory).")
            documents.append((entry, document))
        return WorkspaceAnalysis(path, member["dir"], tuple(documents))
    return None
