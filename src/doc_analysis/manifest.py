"""`figures_manifest.json`: the record of what was saved, and of who owns each name.

In a document the manifest lives at the document's root — the place doc-publish reads as
its second choice — and every analysis feeding that document writes into the same file.
That is what lets one document be fed by its nested analysis and any number of workspace
analyses without two of them writing the same name: each entry records its **owner**, the
`analysis` that first wrote it, and a save from any other analysis is refused
(docs/adr/0003-target-documents-from-workspace.md). With no document, and for a save into
an explicit absolute section, it stays in the analysis repo's `figures_html/`.

Keys share one namespace per document, because LaTeX's do: `"Fig: <label>"` for a figure
(and its PNG's bare filename, which `\\graphicspath` resolves document-wide), `"Tab: <tag>"`
for a table and `"Val: <macro>"` for a value, whose macro every section's values.tex
defines in one preamble. doc-publish reads only the `Fig:` entries and ignores the rest.

Paths in a document's manifest are relative to the manifest file — `static` to the PNG
inside the document, `interactive` to the HTML, which stays in the analysis repo's
`figures_html/` (so usually `../<analysis>/figures_html/<stem>.html`). doc-publish's
FigureEmitter resolves them that way, so publishing needs no workspace lookup. An entry
written before the move holds an absolute `static`, which `entry_path` still resolves.
"""

import json
import os
import tempfile
import time
from pathlib import Path

MANIFEST_NAME = "figures_manifest.json"
#: Where a document's figures live: Sections/, or the pre-rename Chapters/. Spelled here
#: rather than imported, because save_figure imports this module.
SECTION_TREES = ("Sections", "Chapters")

FIGURE_PREFIX = "Fig: "
TABLE_PREFIX = "Tab: "
VALUE_PREFIX = "Val: "


class OwnershipError(RuntimeError):
    """A save of a name another analysis owns in a document. Nothing was written."""


def read_manifest(path):
    """The manifest at `path` as a dict; {} when there is none yet.

    A file that is not JSON raises naming it: treated as empty, the next save would
    rewrite it with one entry and erase every other analysis's record of ownership.
    """
    path = Path(path)
    if not path.exists():
        return {}
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: not valid JSON ({exc}). Restore it from the "
                         f"document's history before saving into it.") from None
    if not isinstance(manifest, dict):
        raise ValueError(f"{path}: the top level is not a JSON object.")
    return manifest


def write_manifest(path, manifest):
    """Write `manifest` to `path` atomically: a temp file beside it, then a rename.

    Two notebooks saving into one document close together would otherwise interleave
    their writes, or one would read the other's half-written file and fail — and the
    file is the record of ownership for every analysis feeding that document. The rename
    cannot leave a torn file; it can still lose the earlier of two simultaneous updates,
    which the next save of that name restores.
    """
    path = Path(path)
    text = json.dumps(manifest, indent=1, sort_keys=True) + "\n"
    handle, temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        # On Windows the rename fails while another process has the target open for
        # reading — a concurrent save's read, or an editor; that lasts milliseconds.
        for attempt in range(10):
            try:
                os.replace(temp, path)
                break
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(0.05)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return path


def update_manifest(path, key, entry):
    """Create or refresh one entry in the manifest at `path`; returns the path."""
    path = Path(path)
    manifest = read_manifest(path)
    manifest[key] = entry
    return write_manifest(path, manifest)


def entry_path(manifest_path, value):
    """A path recorded in an entry, resolved: relative ones against the manifest file."""
    value = Path(value)
    return value if value.is_absolute() else Path(manifest_path).parent / value


def relative_to_manifest(manifest_path, target):
    """`target` as the manifest records it: relative to the manifest, with / separators.

    Absolute only where no relative path exists — another drive on Windows.
    """
    try:
        return Path(os.path.relpath(Path(target), Path(manifest_path).parent)).as_posix()
    except ValueError:
        return str(target)


def clashing_owner(manifest, analysis, keys=(), stem=None):
    """(key, owner) of an entry another analysis owns that this save would overwrite.

    `keys` are the entry keys the save writes. `stem`, for a figure, also catches a
    figure saved under another label: the PNG's bare filename is the shared key LaTeX
    resolves, whatever the label. An entry with no `analysis` predates ownership and is
    nobody's. Returns None when the save may go ahead.
    """
    for key in keys:
        owner = (manifest.get(key) or {}).get("analysis")
        if owner is not None and owner != analysis:
            return key, owner
    if stem is not None:
        for key, entry in sorted(manifest.items()):
            if (key.startswith(FIGURE_PREFIX) and entry.get("stem") == stem
                    and entry.get("analysis") not in (None, analysis)):
                return key, entry["analysis"]
    return None


def refuse_clash(manifest_path, analysis, what, release, keys=(), stem=None):
    """Raise OwnershipError when another analysis owns a name this save writes.

    The message names the owner and the way to release the name: names are never
    prefixed or renamed (AGENTS.md), so the only ways forward are another name or the
    owner giving this one up.
    """
    clash = clashing_owner(read_manifest(manifest_path), analysis, keys, stem)
    if clash is None:
        return
    key, owner = clash
    raise OwnershipError(
        f"{what} is owned by the analysis {owner!r} in {Path(manifest_path).parent} "
        f"({key!r} in {Path(manifest_path).name}), so {analysis!r} may not write it; "
        f"nothing was saved. Save it under another name, or release it: {release}, then "
        f"run `check-figure-parity --prune`.")


def migrate_entries(old_path, new_path, document_root, analysis):
    """Move this analysis's entries for one document out of its old `figures_html/` manifest.

    Before ADR 0003 every entry lived in the analysis repo's manifest, with an absolute
    `static`. An entry whose PNG lies in `document_root` moves into the document's
    manifest, owned by `analysis`, with both paths made relative to the new file; the
    rest (no-document saves, other documents) stay where they are. An entry the document
    already records is not overwritten — the document's is the shared record — but is
    still dropped from the old file, so a second save finds nothing left to move.

    Returns the number of entries moved; prints one line when it is not zero.
    """
    old_path, new_path = Path(old_path), Path(new_path)
    if old_path.resolve() == new_path.resolve() or not old_path.exists():
        return 0
    old = read_manifest(old_path)
    # The section tree, not the document root: a nested analysis lives inside its
    # document, so its no-document PNGs under outputs/ are inside the root too.
    trees = [Path(document_root).resolve() / name for name in SECTION_TREES]
    moving = {}
    for key, entry in old.items():
        static = entry.get("static")
        if not key.startswith(FIGURE_PREFIX) or not static:
            continue
        if not any(Path(static).resolve().is_relative_to(tree) for tree in trees):
            continue
        moving[key] = entry
    if not moving:
        return 0

    new = read_manifest(new_path)
    moved = 0
    for key, entry in moving.items():
        if key not in new:
            entry = dict(entry, analysis=analysis,
                         static=relative_to_manifest(new_path, Path(entry["static"]).resolve()))
            interactive = entry.get("interactive")
            if interactive:
                entry["interactive"] = relative_to_manifest(
                    new_path, entry_path(old_path, interactive).resolve())
            new[key] = entry
            moved += 1
        del old[key]
    write_manifest(new_path, new)
    # Written second: interrupted between the two, the entries are in both files, and the
    # next save drops them from the old one — never in neither.
    if old:
        write_manifest(old_path, old)
    else:
        old_path.unlink()
    if moved:
        print(f"Moved {moved} manifest entr{'y' if moved == 1 else 'ies'} of {analysis!r} "
              f"from {old_path} into {new_path}.")
    return moved
