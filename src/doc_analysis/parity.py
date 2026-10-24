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

**With no document configured** (no-document mode; see `document_repo`) the PNGs live
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
from doc_analysis.save_figure import (
    SECTIONS_DIRNAME,
    HTML_DIR_ENV,
    MANIFEST_NAME,
    figure_reference_state,
    default_html_dir,
    local_output_dir,
    section_root_name,
    document_repo as resolve_document_repo,
)


def png_size(path):
    """(width, height) from the PNG IHDR header, no imaging dependency needed."""
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Not a PNG: {path}")
    return struct.unpack(">II", head[16:24])


# The baseline is tooling data and lives with the tooling; only the PNGs it describes
# live in the LaTeX repo, resolved against document_repo below.
BASELINE_RELATIVE = Path("docs") / "figure_png_baseline.json"


#: Marks a baseline taken in no-document mode. A document's baseline carries no marker —
#: it is written exactly as before no-document mode existed, so committed baselines read
#: unchanged. Never a figure's key: those are filenames, which always have a suffix.
TARGET_KEY = "target"
LOCAL_TARGET = "local"


def _target(document_repo):
    """(root the baseline paths are relative to, is_local) for a run."""
    if document_repo is None:
        return local_output_dir(), True
    return Path(document_repo), False


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


def snapshot(document_repo, html_dir=None, baseline_path=None):
    """Record the current dimensions of every saved figure as the baseline to hold to.

    Reads the manifest rather than scanning the document repo, so the baseline covers
    exactly the figures this pipeline produces and not, say, a logo committed by hand.
    Run it once the figures look right; re-run it deliberately when a size change is
    intended, and commit the diff so the change is reviewable.

    document_repo None is no-document mode: paths are recorded relative to `outputs/`,
    and the baseline is marked local.
    """
    root, local = _target(document_repo)
    html_dir = Path(html_dir or os.environ.get(HTML_DIR_ENV) or default_html_dir())
    manifest_path = html_dir / MANIFEST_NAME
    if not manifest_path.exists():
        print(f"No manifest at {manifest_path}: save a figure before snapshotting.")
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    baseline, missing, stale = {}, [], False
    for entry in manifest.values():
        static = Path(entry["static"])
        if not static.exists():
            missing.append(str(static))
            stale = True
            continue
        width, height = png_size(static)
        try:
            relative = static.relative_to(root)
        except ValueError:
            missing.append(f"{static} (outside {root})")
            continue
        baseline[static.name] = dict(path=str(relative).replace("\\", "/"),
                                     width=width, height=height,
                                     aspect=round(width / height, 6))

    if local:
        baseline[TARGET_KEY] = LOCAL_TARGET
    baseline_path = Path(baseline_path or default_baseline_path())
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(json.dumps(baseline, indent=1, sort_keys=True) + "\n",
                             encoding="utf-8")
    print(f"Wrote {len(baseline) - local} figure(s) to {baseline_path}"
          + (f" (no document: relative to {root})" if local else ""))
    for line in missing:
        print(f"  skipped: {line}")
    # Without the hint a retired figure is reported as skipped on every run, and the only
    # visible fix is editing the manifest by hand. The outside-the-repo case gets no hint:
    # --prune deliberately leaves those entries alone.
    if stale:
        print("  A skipped figure whose PNG was deleted stays in the manifest until "
              "`check-figure-parity --prune` removes it.")
    return 0


def prune(html_dir=None, dry_run=False):
    """Remove manifest entries whose static PNG no longer exists, with their HTML.

    Deletes nothing but the entry and that entry's own interactive HTML: never a PNG, a
    notebook, the baseline or anything in the document repo, which is why this needs no
    DOC_REPO. A missing PNG is the only reason an entry goes; one that merely lies
    outside the document repo is a configuration question, not a retired figure.
    """
    html_dir = Path(html_dir or os.environ.get(HTML_DIR_ENV) or default_html_dir())
    manifest_path = html_dir / MANIFEST_NAME
    if not manifest_path.exists():
        print(f"No manifest at {manifest_path}; nothing to prune.")
        return 0

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    stale = sorted(key for key, entry in manifest.items()
                   if not Path(entry["static"]).exists())
    if not stale:
        print(f"No stale entries in {manifest_path}; nothing changed.")
        return 0

    verb = "would prune" if dry_run else "pruned"
    pruned = {key: manifest.pop(key) for key in stale}
    # The HTML is named by stem alone, so a stem re-saved elsewhere under another label
    # shares it with the retired entry; deleting it then would break the live figure.
    live_html = {entry.get("interactive") for entry in manifest.values()}
    for key, entry in pruned.items():
        # `interactive` is relative to the manifest file (the publishing engine resolves
        # it the same way), and null for a matplotlib figure, which has no HTML.
        interactive = entry.get("interactive")
        html = (manifest_path.parent / interactive
                if interactive and interactive not in live_html else None)
        if html is not None and html.is_file():
            if not dry_run:
                html.unlink()
            print(f"  {verb}: {key}  (and {html})")
        else:
            print(f"  {verb}: {key}")

    if dry_run:
        print(f"{len(stale)} stale entr{'y' if len(stale) == 1 else 'ies'} in "
              f"{manifest_path}; nothing written (--dry-run).")
        return 0
    # Same format as the savers' _update_manifest, so the next save's rewrite is the
    # only diff it produces.
    manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n",
                             encoding="utf-8")
    print(f"Pruned {len(stale)} stale entr{'y' if len(stale) == 1 else 'ies'} "
          f"from {manifest_path}")
    return 0


def check(document_repo, tolerance, stems=None, baseline_path=None):
    """Compare every baseline figure's current PNG with its recorded dimensions.

    document_repo None is no-document mode: the PNGs are looked for under `outputs/`,
    and only a baseline marked local is accepted.
    """
    root, local = _target(document_repo)
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
                  f"record the local figures in {root}.")
        else:
            print(f"The baseline at {baseline_path} was taken with no document "
                  f"(\"{TARGET_KEY}\": \"{LOCAL_TARGET}\"), but {root} is configured. "
                  f"Re-run the notebooks so the figures land in the document, then "
                  f"re-run `check-figure-parity --snapshot`.")
        return 1
    if not baseline:
        print(f"Baseline at {baseline_path} is empty; nothing to check.")
        return 0

    failures, checked = [], 0
    for name, ref in sorted(baseline.items()):
        if stems and Path(name).stem not in stems:
            continue
        checked += 1
        current = root / ref["path"]
        if not current.exists():
            failures.append(f"MISSING  {name}: expected at {ref['path']}")
            continue
        width, height = png_size(current)
        d_width = abs(width - ref["width"]) / ref["width"]
        d_height = abs(height - ref["height"]) / ref["height"]
        d_aspect = abs(width / height - ref["aspect"]) / ref["aspect"]
        if max(d_width, d_height, d_aspect) > tolerance:
            failures.append(
                f"DRIFT    {name}: {ref['width']}x{ref['height']} -> {width}x{height} "
                f"(dW {d_width:.1%}, dH {d_height:.1%}, aspect {d_aspect:.1%})"
            )

    print(f"Checked {checked} baseline figures against {root}")
    if failures:
        print(f"\n{len(failures)} parity failure(s):")
        print("\n".join(f"  {line}" for line in failures))
        return 1
    print("All within tolerance.")
    return 0


def check_figures_placed(document_repo, html_dir=None):
    """Report saved figures that the document does not actually render.

    A figure can be regenerated perfectly and still be invisible in the PDF: its
    \\begin{figure} block may never have been written, or may still be commented out
    (which is the normal state during migration — the block is added commented and
    uncommented once the prose lands). Parity cannot see that, because the PNG is
    correct either way. Cross-references the manifest of everything saved against the
    Sections tree and buckets each figure by how it is referenced.

    Returns 0 always: a commented block is a legitimate work-in-progress state, not a
    failure. This is a report, not a gate. With no document (document_repo None) there
    are no section sources to read, which it says.
    """
    if document_repo is None:
        print("No document configured (no-document mode): there are no section sources "
              "to check the saved figures against. Set DOC_REPO, or nest this repo in a "
              "document, to report which figures it renders.")
        return 0
    html_dir = Path(html_dir or os.environ.get(HTML_DIR_ENV) or default_html_dir())
    manifest_path = html_dir / MANIFEST_NAME
    if not manifest_path.exists():
        print(f"No manifest at {manifest_path}; nothing to report.")
        return 0

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sections = document_repo / (section_root_name(document_repo) or SECTIONS_DIRNAME)

    buckets = {"live": [], "commented": [], None: []}
    for key, entry in sorted(manifest.items()):
        stem = entry.get("stem") or key.removeprefix("Fig: ")
        label = key.removeprefix("Fig: ")
        state, tex_path = figure_reference_state(sections, stem, label)
        where = tex_path.relative_to(document_repo) if tex_path else None
        buckets[state].append((stem, where, entry.get("notebook")))

    print(f"{len(manifest)} figures in {manifest_path.name}, checked against {sections}\n")
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
        for stem, where, notebook in buckets[state]:
            location = f"  in {where}" if where else ""
            source = f"  (from {notebook})" if notebook else ""
            print(f"  {stem}{location}{source}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--document-repo", type=Path, default=None,
                        help="LaTeX document repo root (default: the DOC_REPO env var, "
                             "else layout.toml; with neither, the local outputs/)")
    # Default None, not 0.05, so that an explicit --tolerance can be told apart and
    # rejected alongside --prune; check() still gets 0.05.
    parser.add_argument("--tolerance", type=float, default=None,
                        help="Max fractional drift in width/height/aspect (default 0.05)")
    parser.add_argument("--stems", nargs="*", default=None,
                        help="Only check these figure stems (default: all in the baseline)")
    parser.add_argument("--figures", action="store_true",
                        help="Instead of the dimension check, report which saved figures "
                             "the document renders, which have a commented-out block, and "
                             "which are unreferenced")
    parser.add_argument("--snapshot", action="store_true",
                        help="Record the current dimensions of every saved figure as the "
                             "baseline, instead of checking against it")
    parser.add_argument("--prune", action="store_true",
                        help="Remove manifest entries whose static PNG no longer exists, "
                             "and their interactive HTML; touches nothing else")
    parser.add_argument("--dry-run", action="store_true",
                        help="With --prune: report what would be pruned, change nothing")
    parser.add_argument("--html-dir", type=Path, default=None,
                        help="Directory holding figures_manifest.json (--figures, "
                             "--snapshot and --prune only; default: $FIGURES_HTML_DIR, "
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
        # Before the document repo is resolved: pruning never reads it, so it must not
        # fail for want of a DOC_REPO.
        sys.exit(prune(args.html_dir, dry_run=args.dry_run))
    if args.dry_run:
        parser.error("--dry-run is only valid with --prune")
    repo = args.document_repo if args.document_repo is not None else resolve_document_repo()
    if args.snapshot:
        sys.exit(snapshot(repo, args.html_dir))
    if args.figures:
        sys.exit(check_figures_placed(repo, args.html_dir))
    tolerance = 0.05 if args.tolerance is None else args.tolerance
    sys.exit(check(repo, tolerance, args.stems))


if __name__ == "__main__":
    main()
