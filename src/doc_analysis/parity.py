"""Guard the committed figures against silent change.

Two questions, neither of which a successful build answers.

**Did a figure quietly change size?** A committed PNG is placed at a particular size and
a caption written around it. Regenerate it from a notebook whose layout has drifted — a
legend moved, a default picked up — and the document reflows with nothing failing.
`--snapshot` records the current dimensions; later runs compare against that record and
exit non-zero on drift, so this can gate a batch of regeneration.

Dimension parity is necessary but not sufficient: text legibility at print size is what
usually breaks, and two figures of identical dimensions can differ wildly in whether their
axis labels are readable. Eyeball anything you have restyled.

**Is a figure actually in the document?** `--figures` cross-references the manifest of
everything saved against the section sources. A figure whose `\\begin{figure}` block was
never written, or is still commented out, passes every other check and is invisible in the
PDF. That mode is a report, not a gate, and always exits 0.

**What retires a figure?** The manifest is only ever added to, one entry per save, so a
figure whose PNG was deleted keeps its entry for good: `--snapshot` reports it as skipped
on every run and `--figures` lists it as unreferenced. `--prune` removes those entries and
their interactive HTML. It is explicit rather than part of a snapshot because a PNG can
also be missing transiently — a document checkout on the wrong branch — and dropping the
entry then would lose its record until the notebook is re-run.

Usage:
    check-figure-parity --snapshot                  # record the current dimensions
    check-figure-parity [--tolerance 0.05] [--stems stem1 stem2 ...]
    check-figure-parity --figures
    check-figure-parity --prune [--dry-run]         # drop entries whose PNG is gone

**Per analysis, over every target document.** A workspace analysis can feed several
documents and a document can be fed by several analyses (ADR 0003), so each document's
manifest is shared, at its root. `--snapshot` and the default check cover this analysis's
own entries in each of its target documents, and the baseline records each PNG relative
to its document, keyed by document. `--figures` reports over a document's whole manifest
— the union of every analysis feeding it — since what the PDF renders is a fact about
the document, not about who saved the figure. `--prune` also drops a stale entry that
another analysis owns: that is what releases a name for someone else to claim.

**With no document configured** (no-document mode; see `target_documents`) the PNGs live
in the checkout's `outputs/`, and `--snapshot` and the default check run against that
instead. A baseline taken there says so (`"target": "local"`), and checking it against a
document — or a document's baseline against `outputs/` — is an error, not a pass: the
paths would resolve to nothing, or to a different set of figures. `--figures` has no
section sources to read, says so, and exits 0.
"""

import argparse
import json
import os
import struct
import sys
from pathlib import Path

from doc_analysis.env import analysis_root
from doc_analysis.manifest import (
    FIGURE_PREFIX,
    MANIFEST_NAME,
    entry_path,
    read_manifest,
    write_manifest,
)
from doc_analysis.save_figure import (
    SECTIONS_DIRNAME,
    HTML_DIR_ENV,
    TargetDocument,
    figure_reference_state,
    default_html_dir,
    local_output_dir,
    section_root_name,
    target_documents,
)


def png_size(path):
    """(width, height) from the PNG IHDR header, no imaging dependency needed."""
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Not a PNG: {path}")
    return struct.unpack(">II", head[16:24])


# The baseline is tooling data and lives with the tooling; only the PNGs it describes
# live in the LaTeX repo, resolved against each target document below.
BASELINE_RELATIVE = Path("docs") / "figure_png_baseline.json"


#: Marks a baseline taken in no-document mode. Never a figure's key: those are
#: filenames, which always have a suffix.
TARGET_KEY = "target"
LOCAL_TARGET = "local"
#: A document baseline's one top-level key: {document name: {png name: dimensions}}.
#: One written before several documents existed is flat, {png name: dimensions}, and is
#: still read as the baseline of the only target.
DOCUMENTS_KEY = "documents"


def _as_documents(documents):
    """None (no-document mode), or a tuple of TargetDocument.

    A bare path is accepted, as the single document repo every caller passed before
    there could be several; it is named by its directory, as $DOC_REPO's is.
    """
    if documents is None:
        return None
    if isinstance(documents, (str, os.PathLike)):
        path = Path(documents)
        return (TargetDocument(path.resolve().name, path, "--document-repo"),)
    return tuple(documents)


def _html_dir(html_dir):
    return Path(html_dir or os.environ.get(HTML_DIR_ENV) or default_html_dir())


def _document_manifest(document, html_dir):
    """The manifest describing `document`: an explicit html_dir's, else the document's own."""
    return (Path(html_dir) if html_dir else document.path) / MANIFEST_NAME


def _inside(path, root):
    try:
        return Path(path).resolve().relative_to(Path(root).resolve())
    except ValueError:
        return None


def default_baseline_path():
    """The active checkout's baseline, resolved per call (see `env.analysis_root`).

    Not computed from `__file__` at import: with two checkouts in one venv, one repo's
    `--snapshot` overwrote the other's baseline and its checks ran against the wrong one.
    """
    return analysis_root() / BASELINE_RELATIVE


def __getattr__(name):
    # The pre-#24 constant, still importable for code that reads it; now resolved on access.
    if name == "BASELINE_PATH":
        return default_baseline_path()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _dimensions(static, relative):
    width, height = png_size(static)
    return dict(path=str(relative).replace("\\", "/"), width=width, height=height,
                aspect=round(width / height, 6))


def snapshot(documents, html_dir=None, baseline_path=None, analysis=None):
    """Record the current dimensions of every saved figure as the baseline to hold to.

    Reads the manifest rather than scanning the document repo, so the baseline covers
    exactly the figures this pipeline produces and not, say, a logo committed by hand.
    Run it once the figures look right; re-run it deliberately when a size change is
    intended, and commit the diff so the change is reviewable.

    documents is the target documents (a single path is accepted too); each one's
    manifest is the document's own unless html_dir names another, and only the entries
    `analysis` owns are recorded — the baseline guards this analysis's figures, not those
    of another analysis feeding the same document. analysis None records every entry.

    documents None is no-document mode: the html directory's manifest, paths recorded
    relative to `outputs/`, and the baseline marked local.
    """
    documents = _as_documents(documents)
    baseline_path = Path(baseline_path or default_baseline_path())
    if documents is None:
        return _snapshot_local(_html_dir(html_dir), baseline_path)

    recorded, missing, stale, found = {}, [], False, False
    for document in documents:
        manifest_path = _document_manifest(document, html_dir)
        if not manifest_path.exists():
            continue
        found = True
        figures = recorded.setdefault(document.name, {})
        for key, entry in sorted(read_manifest(manifest_path).items()):
            if not key.startswith(FIGURE_PREFIX) or not entry.get("static"):
                continue
            if analysis is not None and entry.get("analysis") not in (None, analysis):
                continue
            static = entry_path(manifest_path, entry["static"])
            relative = _inside(static, document.path)
            if relative is None:
                # A shared html_dir manifest holds every document's entries; one in
                # another target is that target's, not an outsider.
                if not any(_inside(static, other.path) for other in documents):
                    missing.append(f"{static} (outside {document.path})")
                continue
            if not static.exists():
                missing.append(str(static))
                stale = True
                continue
            figures[static.name] = _dimensions(static, relative)

    if not found:
        where = ", ".join(str(_document_manifest(d, html_dir)) for d in documents)
        print(f"No manifest at {where}: save a figure before snapshotting.")
        return 1

    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(json.dumps({DOCUMENTS_KEY: recorded}, indent=1,
                                        sort_keys=True) + "\n", encoding="utf-8")
    count = sum(len(figures) for figures in recorded.values())
    print(f"Wrote {count} figure(s) in {len(recorded)} document(s) to {baseline_path}")
    _report_skipped(missing, stale)
    return 0


def _snapshot_local(html_dir, baseline_path):
    """`snapshot` in no-document mode: one manifest, paths relative to `outputs/`."""
    root = local_output_dir()
    manifest_path = html_dir / MANIFEST_NAME
    if not manifest_path.exists():
        print(f"No manifest at {manifest_path}: save a figure before snapshotting.")
        return 1

    baseline, missing, stale = {}, [], False
    for key, entry in read_manifest(manifest_path).items():
        if not key.startswith(FIGURE_PREFIX) or not entry.get("static"):
            continue
        static = entry_path(manifest_path, entry["static"])
        if not static.exists():
            missing.append(str(static))
            stale = True
            continue
        relative = _inside(static, root)
        if relative is None:
            missing.append(f"{static} (outside {root})")
            continue
        baseline[static.name] = _dimensions(static, relative)

    baseline[TARGET_KEY] = LOCAL_TARGET
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(json.dumps(baseline, indent=1, sort_keys=True) + "\n",
                             encoding="utf-8")
    print(f"Wrote {len(baseline) - 1} figure(s) to {baseline_path} "
          f"(no document: relative to {root})")
    _report_skipped(missing, stale)
    return 0


def _report_skipped(missing, stale):
    for line in missing:
        print(f"  skipped: {line}")
    # Without the hint a retired figure is reported as skipped on every run, and the only
    # visible fix is editing the manifest by hand. The outside-the-repo case gets no hint:
    # --prune deliberately leaves those entries alone.
    if stale:
        print("  A skipped figure whose PNG was deleted stays in the manifest until "
              "`check-figure-parity --prune` removes it.")


def _is_stale(manifest_path, key, entry):
    """Whether what an entry records is gone: a figure's PNG, a table's or value's block.

    A PNG is the only test for a figure. For a table or value it is the tagged block in
    its library: deleting the block is how a name is given up, and the library file
    itself usually stays, holding the section's other blocks.
    """
    if entry.get("static"):
        return not entry_path(manifest_path, entry["static"]).exists()
    if entry.get("library") and entry.get("tag"):
        library = entry_path(manifest_path, entry["library"])
        return (not library.is_file()
                or f"%<*{entry['tag']}>" not in library.read_text(encoding="utf-8",
                                                                  errors="replace"))
    return False


def prune(html_dir=None, dry_run=False, documents=(), analysis=None):
    """Remove manifest entries whose PNG or block no longer exists, with their own HTML.

    Prunes the html directory's manifest — no-document saves, and entries from before
    ADR 0003 — and the shared manifest of each target document in `documents`. In a
    document that also drops a stale entry another analysis owns, which is the point: the
    entry is the record of ownership, so pruning it once the owner's PNG or block is gone
    is what releases the name for another analysis to claim.

    Deletes nothing but the entries and the interactive HTML of entries `analysis` owns
    (or that predate ownership) — never another analysis's HTML, which lives in that
    analysis's repo — and never a PNG, a notebook, the baseline or anything else in the
    document. A missing PNG or block is the only reason an entry goes.
    """
    manifests = [_html_dir(html_dir) / MANIFEST_NAME]
    for document in _as_documents(documents) or ():
        path = document.path / MANIFEST_NAME
        if all(path.resolve() != known.resolve() for known in manifests):
            manifests.append(path)
    present = [path for path in manifests if path.exists()]
    if not present:
        print(f"No manifest at {', '.join(str(path) for path in manifests)}; "
              f"nothing to prune.")
        return 0
    for manifest_path in present:
        _prune_one(manifest_path, dry_run, analysis)
    return 0


def _prune_one(manifest_path, dry_run, analysis):
    manifest = read_manifest(manifest_path)
    stale = sorted(key for key, entry in manifest.items()
                   if _is_stale(manifest_path, key, entry))
    if not stale:
        print(f"No stale entries in {manifest_path}; nothing changed.")
        return

    verb = "would prune" if dry_run else "pruned"
    pruned = {key: manifest.pop(key) for key in stale}
    # The HTML is named by stem alone, so a stem re-saved elsewhere under another label
    # shares it with the retired entry; deleting it then would break the live figure.
    live_html = {entry_path(manifest_path, entry["interactive"]).resolve()
                 for entry in manifest.values() if entry.get("interactive")}
    for key, entry in pruned.items():
        # `interactive` is relative to the manifest file (the publishing engine resolves
        # it the same way), and null for a matplotlib figure, which has no HTML.
        interactive = entry.get("interactive")
        html = (entry_path(manifest_path, interactive)
                if interactive and entry.get("analysis") in (None, analysis) else None)
        if html is not None and html.resolve() not in live_html and html.is_file():
            if not dry_run:
                html.unlink()
            print(f"  {verb}: {key}  (and {html})")
        else:
            owner = entry.get("analysis")
            print(f"  {verb}: {key}"
                  + (f"  (owned by {owner!r}: released)" if owner not in (None, analysis)
                     else ""))

    if dry_run:
        print(f"{len(stale)} stale entr{'y' if len(stale) == 1 else 'ies'} in "
              f"{manifest_path}; nothing written (--dry-run).")
        return
    # Same format as the savers' manifest writes, so the next save's rewrite is the only
    # diff it produces.
    write_manifest(manifest_path, manifest)
    print(f"Pruned {len(stale)} stale entr{'y' if len(stale) == 1 else 'ies'} "
          f"from {manifest_path}")


def check(documents, tolerance, stems=None, baseline_path=None):
    """Compare every baseline figure's current PNG with its recorded dimensions.

    documents is the target documents (a single path is accepted too); each baseline
    figure is looked for under the document it was recorded in. A document the baseline
    records that is no longer a target fails the check: its figures can no longer be
    found, and silently skipping them would pass a check that guarded nothing.

    documents None is no-document mode: the PNGs are looked for under `outputs/`,
    and only a baseline marked local is accepted.
    """
    documents = _as_documents(documents)
    local = documents is None
    baseline_path = Path(baseline_path or default_baseline_path())
    if not baseline_path.exists():
        print(f"No baseline at {baseline_path}.\n"
              f"Run `check-figure-parity --snapshot` once the figures look right; "
              f"later runs then guard them against silent resizing.")
        return 0

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    recorded_local = baseline.pop(TARGET_KEY, None) == LOCAL_TARGET
    if recorded_local != local:
        # Either way round every path resolves against the wrong root: each figure would
        # be MISSING, or — where the names happen to exist in both — compared with a
        # different file. Neither is a parity result, so neither may pass.
        if local:
            print(f"The baseline at {baseline_path} records figures in a document, but no "
                  f"document is configured (no-document mode). Configure the document it "
                  f"was taken against, or re-run `check-figure-parity --snapshot` to "
                  f"record the local figures in {local_output_dir()}.")
        else:
            print(f"The baseline at {baseline_path} was taken with no document "
                  f"(\"{TARGET_KEY}\": \"{LOCAL_TARGET}\"), but "
                  f"{', '.join(str(d.path) for d in documents)} is configured. "
                  f"Re-run the notebooks so the figures land in the document, then "
                  f"re-run `check-figure-parity --snapshot`.")
        return 1

    if local:
        per_document = {None: baseline}
        roots = {None: local_output_dir()}
    elif DOCUMENTS_KEY in baseline:
        per_document = baseline[DOCUMENTS_KEY]
        roots = {document.name: document.path for document in documents}
    elif len(documents) == 1:
        # Flat: taken before a baseline was keyed by document, against the one there was.
        per_document = {documents[0].name: baseline}
        roots = {documents[0].name: documents[0].path}
    else:
        print(f"The baseline at {baseline_path} records one document's figures, from "
              f"before an analysis could have several, and this one has "
              f"{len(documents)} ({', '.join(d.name for d in documents)}). Re-run "
              f"`check-figure-parity --snapshot` to record each of them.")
        return 1
    if not any(per_document.values()):
        print(f"Baseline at {baseline_path} is empty; nothing to check.")
        return 0

    failures, checked = [], 0
    for name, figures in sorted(per_document.items(), key=lambda item: str(item[0])):
        root = roots.get(name)
        if root is None:
            failures.append(f"DOCUMENT {name}: recorded in the baseline, but not a target "
                            f"document any more; re-run --snapshot")
            continue
        for figure, ref in sorted(figures.items()):
            if stems and Path(figure).stem not in stems:
                continue
            checked += 1
            current = Path(root) / ref["path"]
            label = figure if name is None else f"{name}: {figure}"
            if not current.exists():
                failures.append(f"MISSING  {label}: expected at {ref['path']}")
                continue
            width, height = png_size(current)
            d_width = abs(width - ref["width"]) / ref["width"]
            d_height = abs(height - ref["height"]) / ref["height"]
            d_aspect = abs(width / height - ref["aspect"]) / ref["aspect"]
            if max(d_width, d_height, d_aspect) > tolerance:
                failures.append(
                    f"DRIFT    {label}: {ref['width']}x{ref['height']} -> {width}x{height} "
                    f"(dW {d_width:.1%}, dH {d_height:.1%}, aspect {d_aspect:.1%})"
                )

    against = ", ".join(str(root) for root in roots.values())
    print(f"Checked {checked} baseline figures against {against}")
    unrecorded = [name for name in roots if name is not None and name not in per_document]
    if unrecorded:
        print(f"  not in the baseline yet: {', '.join(unrecorded)} "
              f"(run --snapshot to guard its figures)")
    if failures:
        print(f"\n{len(failures)} parity failure(s):")
        print("\n".join(f"  {line}" for line in failures))
        return 1
    print("All within tolerance.")
    return 0


def check_figures_placed(documents, html_dir=None):
    """Report saved figures that the document does not actually render.

    A figure can be regenerated perfectly and still be invisible in the PDF: its
    \\begin{figure} block may never have been written, or may still be commented out
    (which is the normal state during migration — the block is added commented and
    uncommented once the prose lands). Parity cannot see that, because the PNG is
    correct either way. Cross-references the manifest of everything saved against the
    Sections tree and buckets each figure by how it is referenced.

    Per target document, over the document's whole manifest: every analysis feeding it,
    not only this one, because whether a figure renders is a question about the document.

    Returns 0 always: a commented block is a legitimate work-in-progress state, not a
    failure. This is a report, not a gate. With no document (documents None) there
    are no section sources to read, which it says.
    """
    documents = _as_documents(documents)
    if documents is None:
        print("No document configured (no-document mode): there are no section sources "
              "to check the saved figures against. Set DOC_REPO, nest this repo in a "
              "document, or attach it to one, to report which figures it renders.")
        return 0
    for index, document in enumerate(documents):
        if index:
            print()
        _report_document(document, html_dir, documents)
    return 0


def _report_document(document, html_dir, documents):
    manifest_path = _document_manifest(document, html_dir)
    if not manifest_path.exists():
        print(f"No manifest at {manifest_path}; nothing to report.")
        return
    repo = document.path
    sections = repo / (section_root_name(repo) or SECTIONS_DIRNAME)

    entries = {}
    for key, entry in sorted(read_manifest(manifest_path).items()):
        if not key.startswith(FIGURE_PREFIX):
            continue
        # A shared html_dir manifest also holds the other targets' figures.
        static = entry.get("static")
        if (html_dir and len(documents) > 1 and static
                and _inside(entry_path(manifest_path, static), repo) is None):
            continue
        entries[key] = entry

    buckets = {"live": [], "commented": [], None: []}
    for key, entry in entries.items():
        stem = entry.get("stem") or key.removeprefix(FIGURE_PREFIX)
        label = key.removeprefix(FIGURE_PREFIX)
        state, tex_path = figure_reference_state(sections, stem, label)
        where = tex_path.relative_to(repo) if tex_path else None
        buckets[state].append((stem, where, entry.get("notebook"), entry.get("analysis")))

    print(f"{len(entries)} figures in {manifest_path.name}, checked against {sections}\n")
    print(f"  rendered (live block)      {len(buckets['live'])}")
    print(f"  commented block only       {len(buckets['commented'])}")
    print(f"  no reference at all        {len(buckets[None])}")

    # ASCII only: this prints to a Windows console under cp1252, where an em dash
    # arrives as a replacement character.
    for state, heading in (("commented", "Commented out - will not appear in the PDF "
                                         "until the block is uncommented"),
                           (None, "Unreferenced - no \\begin{figure} block anywhere")):
        if not buckets[state]:
            continue
        print(f"\n{heading}:")
        for stem, where, notebook, analysis in buckets[state]:
            location = f"  in {where}" if where else ""
            source = ", ".join(part for part in (notebook, analysis) if part)
            print(f"  {stem}{location}" + (f"  (from {source})" if source else ""))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--document-repo", type=Path, default=None,
                        help="LaTeX document repo root, instead of this analysis's target "
                             "documents (DOC_REPO, layout.toml or workspace.json; with "
                             "none, the local outputs/)")
    # Default None, not 0.05, so that an explicit --tolerance can be told apart and
    # rejected alongside --prune; check() still gets 0.05.
    parser.add_argument("--tolerance", type=float, default=None,
                        help="Max fractional drift in width/height/aspect (default 0.05)")
    parser.add_argument("--stems", nargs="*", default=None,
                        help="Only check these figure stems (default: all in the baseline)")
    parser.add_argument("--figures", action="store_true",
                        help="Instead of the dimension check, report which saved figures "
                             "each document renders, which have a commented-out block, "
                             "and which are unreferenced")
    parser.add_argument("--snapshot", action="store_true",
                        help="Record the current dimensions of every saved figure as the "
                             "baseline, instead of checking against it")
    parser.add_argument("--prune", action="store_true",
                        help="Remove manifest entries whose PNG or block no longer "
                             "exists, and their interactive HTML; touches nothing else")
    parser.add_argument("--dry-run", action="store_true",
                        help="With --prune: report what would be pruned, change nothing")
    parser.add_argument("--html-dir", type=Path, default=None,
                        help="Directory holding figures_manifest.json (--figures, "
                             "--snapshot and --prune only; default: each target "
                             "document's root, and with no document $FIGURES_HTML_DIR, "
                             "else the repo's figures_html/)")
    args = parser.parse_args(argv)
    # Checked by hand rather than with a mutually exclusive group, which would also
    # start rejecting combinations of the existing modes that have always been accepted.
    if args.prune:
        clashing = [flag for flag, given in (("--snapshot", args.snapshot),
                                             ("--figures", args.figures),
                                             ("--stems", args.stems is not None),
                                             ("--tolerance", args.tolerance is not None))
                    if given]
        if clashing:
            parser.error(f"--prune cannot be combined with {', '.join(clashing)}")
    elif args.dry_run:
        parser.error("--dry-run is only valid with --prune")

    if args.document_repo is not None:
        documents, analysis = _as_documents(args.document_repo), None
    else:
        targets = target_documents()
        documents, analysis = (targets.documents or None), targets.analysis
    if args.prune:
        sys.exit(prune(args.html_dir, dry_run=args.dry_run, documents=documents or (),
                       analysis=analysis))
    if args.snapshot:
        sys.exit(snapshot(documents, args.html_dir, analysis=analysis))
    if args.figures:
        sys.exit(check_figures_placed(documents, args.html_dir))
    tolerance = 0.05 if args.tolerance is None else args.tolerance
    sys.exit(check(documents, tolerance, args.stems))


if __name__ == "__main__":
    main()
