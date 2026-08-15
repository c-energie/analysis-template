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
everything saved against the chapter sources. A figure whose `\\begin{figure}` block was
never written, or is still commented out, passes every other check and is invisible in the
PDF. That mode is a report, not a gate, and always exits 0.

Usage:
    check-figure-parity --snapshot                  # record the current dimensions
    check-figure-parity [--tolerance 0.05] [--stems stem1 stem2 ...]
    check-figure-parity --figures
"""

import argparse
import json
import os
import struct
import sys
from pathlib import Path

from doc_analysis.save_figure import (
    CHAPTERS_DIRNAME,
    DEFAULT_HTML_DIR,
    HTML_DIR_ENV,
    MANIFEST_NAME,
    figure_reference_state,
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
BASELINE_PATH = Path(__file__).resolve().parents[2] / "docs" / "figure_png_baseline.json"


def snapshot(document_repo, html_dir=None, baseline_path=BASELINE_PATH):
    """Record the current dimensions of every saved figure as the baseline to hold to.

    Reads the manifest rather than scanning the document repo, so the baseline covers
    exactly the figures this pipeline produces and not, say, a logo committed by hand.
    Run it once the figures look right; re-run it deliberately when a size change is
    intended, and commit the diff so the change is reviewable.
    """
    html_dir = Path(html_dir or os.environ.get(HTML_DIR_ENV) or DEFAULT_HTML_DIR)
    manifest_path = html_dir / MANIFEST_NAME
    if not manifest_path.exists():
        print(f"No manifest at {manifest_path}: save a figure before snapshotting.")
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    baseline, missing = {}, []
    for entry in manifest.values():
        static = Path(entry["static"])
        if not static.exists():
            missing.append(str(static))
            continue
        width, height = png_size(static)
        try:
            relative = static.relative_to(document_repo)
        except ValueError:
            missing.append(f"{static} (outside {document_repo})")
            continue
        baseline[static.name] = dict(path=str(relative).replace("\\", "/"),
                                     width=width, height=height,
                                     aspect=round(width / height, 6))

    baseline_path = Path(baseline_path)
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(json.dumps(baseline, indent=1, sort_keys=True) + "\n",
                             encoding="utf-8")
    print(f"Wrote {len(baseline)} figure(s) to {baseline_path}")
    for line in missing:
        print(f"  skipped: {line}")
    return 0


def check(document_repo, tolerance, stems=None, baseline_path=BASELINE_PATH):
    baseline_path = Path(baseline_path)
    if not baseline_path.exists():
        print(f"No baseline at {baseline_path}.\n"
              f"Run `check-figure-parity --snapshot` once the figures look right; "
              f"later runs then guard them against silent resizing.")
        return 0

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    if not baseline:
        print(f"Baseline at {baseline_path} is empty; nothing to check.")
        return 0

    failures, checked = [], 0
    for name, ref in sorted(baseline.items()):
        if stems and Path(name).stem not in stems:
            continue
        checked += 1
        current = document_repo / ref["path"]
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

    print(f"Checked {checked} baseline figures against {document_repo}")
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
    Chapters tree and buckets each figure by how it is referenced.

    Returns 0 always: a commented block is a legitimate work-in-progress state, not a
    failure. This is a report, not a gate.
    """
    html_dir = Path(html_dir or os.environ.get(HTML_DIR_ENV) or DEFAULT_HTML_DIR)
    manifest_path = html_dir / MANIFEST_NAME
    if not manifest_path.exists():
        print(f"No manifest at {manifest_path}; nothing to report.")
        return 0

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chapters = document_repo / CHAPTERS_DIRNAME

    buckets = {"live": [], "commented": [], None: []}
    for key, entry in sorted(manifest.items()):
        stem = entry.get("stem") or key.removeprefix("Fig: ")
        label = key.removeprefix("Fig: ")
        state, tex_path = figure_reference_state(chapters, stem, label)
        where = tex_path.relative_to(document_repo) if tex_path else None
        buckets[state].append((stem, where, entry.get("notebook")))

    print(f"{len(manifest)} figures in {manifest_path.name}, checked against {chapters}\n")
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


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--document-repo", type=Path, default=None,
                        help="LaTeX document repo root (default: the DOC_REPO env var)")
    parser.add_argument("--tolerance", type=float, default=0.05,
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
    parser.add_argument("--html-dir", type=Path, default=None,
                        help="Directory holding figures_manifest.json (--figures and "
                             "--snapshot only; default: $FIGURES_HTML_DIR, else the "
                             "repo's figures_html/)")
    args = parser.parse_args()
    repo = args.document_repo if args.document_repo is not None else resolve_document_repo()
    if args.snapshot:
        sys.exit(snapshot(repo, args.html_dir))
    if args.figures:
        sys.exit(check_figures_placed(repo, args.html_dir))
    sys.exit(check(repo, args.tolerance, args.stems))


if __name__ == "__main__":
    main()
