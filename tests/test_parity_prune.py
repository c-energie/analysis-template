"""`check-figure-parity --prune`: retiring a figure whose PNG was deleted.

The manifest is only ever added to, so before --prune a retired figure stayed in it for
good — reported as `skipped:` by every --snapshot and as unreferenced by every --figures,
with hand-editing the JSON the only way out. What is worth pinning:

- only entries whose static PNG is missing go, and only with their own HTML;
- --dry-run changes nothing, and a prune with nothing stale does not rewrite the file;
- it is explicit: argparse rejects it alongside another mode, and it needs no DOC_REPO,
  since it never reads the document repo.

Everything lives under tmp_path; the PNGs are bare headers, so no backend is imported.
"""
import json
import struct

import pytest

from doc_analysis.parity import main, prune, snapshot
from doc_analysis.save_figure import MANIFEST_NAME


def png_bytes(width=1125, height=720):
    """A PNG header parity.png_size can read: signature, then IHDR width/height."""
    return (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR"
            + struct.pack(">II", width, height))


@pytest.fixture
def layout(tmp_path):
    """A document repo with two saved plotly figures, and the html dir that records them."""
    figures = tmp_path / "doc" / "Sections" / "Results" / "Figures"
    figures.mkdir(parents=True)
    html_dir = tmp_path / "figures_html"
    html_dir.mkdir()
    manifest = {}
    for stem in ("foo", "bar"):
        (figures / f"{stem}.png").write_bytes(png_bytes())
        (html_dir / f"{stem}.html").write_text("<html>fake</html>", encoding="utf-8")
        manifest[f"Fig: {stem}"] = {"interactive": f"{stem}.html",
                                    "static": str(figures / f"{stem}.png"),
                                    "stem": stem, "backend": "plotly"}
    write_manifest(html_dir, manifest)
    return tmp_path / "doc", figures, html_dir


def write_manifest(html_dir, manifest):
    (html_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def read_manifest(html_dir):
    return json.loads((html_dir / MANIFEST_NAME).read_text(encoding="utf-8"))


def test_prune_removes_only_the_entry_and_html_of_a_deleted_png(layout):
    """Pruning foo must not take bar's entry or files with it."""
    _, figures, html_dir = layout
    (figures / "foo.png").unlink()

    assert prune(html_dir) == 0

    manifest = read_manifest(html_dir)
    assert set(manifest) == {"Fig: bar"}
    assert not (html_dir / "foo.html").exists()
    assert (html_dir / "bar.html").exists()
    assert (figures / "bar.png").exists()
    # Same format as the savers write, so the next save adds no spurious diff.
    assert (html_dir / MANIFEST_NAME).read_text(encoding="utf-8") == (
        json.dumps(manifest, indent=1, sort_keys=True) + "\n")


def test_prune_removes_a_matplotlib_entry_with_no_html(layout):
    """`interactive: null` must not be joined onto the manifest path and crash."""
    _, figures, html_dir = layout
    manifest = read_manifest(html_dir)
    manifest["Fig: foo"]["interactive"] = None
    write_manifest(html_dir, manifest)
    (figures / "foo.png").unlink()

    assert prune(html_dir) == 0
    assert set(read_manifest(html_dir)) == {"Fig: bar"}


def test_prune_removes_an_entry_whose_html_is_already_gone(layout):
    """An HTML file deleted by hand must not stop the entry from going."""
    _, figures, html_dir = layout
    (figures / "foo.png").unlink()
    (html_dir / "foo.html").unlink()

    assert prune(html_dir) == 0
    assert set(read_manifest(html_dir)) == {"Fig: bar"}


def test_dry_run_reports_but_changes_nothing(layout, capsys):
    """--dry-run that wrote anything would make it useless as a preview."""
    _, figures, html_dir = layout
    (figures / "foo.png").unlink()
    before = (html_dir / MANIFEST_NAME).read_bytes()
    html_before = (html_dir / "foo.html").read_bytes()

    assert prune(html_dir, dry_run=True) == 0

    out = capsys.readouterr().out
    assert "Fig: foo" in out and "Fig: bar" not in out
    assert (html_dir / MANIFEST_NAME).read_bytes() == before
    assert (html_dir / "foo.html").read_bytes() == html_before


def test_prune_with_nothing_stale_does_not_rewrite_the_manifest(layout, capsys):
    """A needless rewrite reformats the file and churns its mtime; nothing stale must
    mean nothing written."""
    _, _, html_dir = layout
    # A layout the savers would not produce, so a rewrite would show.
    path = html_dir / MANIFEST_NAME
    path.write_text(json.dumps(read_manifest(html_dir)), encoding="utf-8")
    before = path.read_bytes()

    assert prune(html_dir) == 0
    assert path.read_bytes() == before
    assert "nothing changed" in capsys.readouterr().out


def test_prune_without_a_manifest_exits_zero(tmp_path, capsys):
    assert prune(tmp_path / "figures_html") == 0
    assert "No manifest" in capsys.readouterr().out


def test_snapshot_stops_reporting_a_figure_once_pruned(layout, tmp_path, capsys):
    """The point of the issue: a retired figure is skipped on every snapshot until pruned,
    and the skip line says how to stop it."""
    doc, figures, html_dir = layout
    (figures / "foo.png").unlink()
    baseline = tmp_path / "baseline.json"

    snapshot(doc, html_dir, baseline_path=baseline)
    out = capsys.readouterr().out
    assert "skipped:" in out and "--prune" in out

    prune(html_dir)
    capsys.readouterr()
    snapshot(doc, html_dir, baseline_path=baseline)
    out = capsys.readouterr().out
    assert "skipped:" not in out
    assert set(json.loads(baseline.read_text(encoding="utf-8"))) == {"bar.png"}


def test_snapshot_gives_no_prune_hint_for_a_figure_outside_the_repo(layout, tmp_path,
                                                                    capsys):
    """--prune leaves outside-the-repo entries alone, so pointing at it would mislead."""
    _, _, html_dir = layout
    other = tmp_path / "other"
    (other / "Sections").mkdir(parents=True)

    snapshot(other, html_dir, baseline_path=tmp_path / "baseline.json")
    out = capsys.readouterr().out
    assert "outside" in out and "--prune" not in out


@pytest.mark.parametrize("other", [["--snapshot"], ["--figures"], ["--stems", "foo"],
                                   ["--tolerance", "0.1"]])
def test_prune_combined_with_another_mode_is_rejected(other, tmp_path):
    """Silently running one mode of two would leave the user believing both ran."""
    with pytest.raises(SystemExit) as exc:
        main(["--prune", "--html-dir", str(tmp_path), *other])
    assert exc.value.code == 2


def test_dry_run_without_prune_is_rejected(tmp_path):
    """Otherwise `--snapshot --dry-run` would write the baseline it seemed to preview."""
    with pytest.raises(SystemExit) as exc:
        main(["--snapshot", "--dry-run", "--html-dir", str(tmp_path)])
    assert exc.value.code == 2


def test_prune_runs_without_doc_repo(layout, monkeypatch):
    """Pruning never reads the document repo, so it must not fail for want of DOC_REPO."""
    _, figures, html_dir = layout
    monkeypatch.delenv("DOC_REPO", raising=False)
    (figures / "foo.png").unlink()

    with pytest.raises(SystemExit) as exc:
        main(["--prune", "--html-dir", str(html_dir)])
    assert exc.value.code == 0
    assert set(read_manifest(html_dir)) == {"Fig: bar"}


def test_prune_keeps_html_still_named_by_a_live_entry(layout):
    """The HTML is named by stem alone, so a stem re-saved in another section under a new
    label shares it with the retired entry; deleting it would break the live figure."""
    doc, figures, html_dir = layout
    moved = doc / "Sections" / "Discussion" / "Figures"
    moved.mkdir(parents=True)
    (moved / "foo.png").write_bytes(png_bytes())
    manifest = read_manifest(html_dir)
    manifest["Fig: foo-moved"] = dict(manifest["Fig: foo"], static=str(moved / "foo.png"))
    write_manifest(html_dir, manifest)
    (figures / "foo.png").unlink()

    assert prune(html_dir) == 0
    assert set(read_manifest(html_dir)) == {"Fig: bar", "Fig: foo-moved"}
    assert (html_dir / "foo.html").exists()
