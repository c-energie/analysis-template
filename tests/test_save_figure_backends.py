"""Both plotting backends, and the manifest that has to cover them equally.

Plotly is the preferred backend and matplotlib the static-only fallback; the saver picks
between them by looking at the figure object, so these tests hand it stubs rather than
real figures. That is deliberate — it keeps `dev` free of either backend, so `pytest`
runs on a bare install and CI never waits for kaleido's Chrome download. The stubs
duck-type exactly what `save_document_figure` asks of a figure and nothing more, which
is also a readable statement of what that contract is.

What is worth pinning here:

- a matplotlib figure gets a manifest entry too (`interactive: null`), because the
  manifest is what `check-figure-parity` reads. Without the entry both parity modes are
  blind to every matplotlib figure, and nothing fails to say so;
- the matplotlib path emits no warning. Choosing a backend is not a defect, and a
  warning on every save is how a project learns to ignore the channel the hover check
  and the ambiguous-.tex check depend on;
- the missing-extra messages name the extra, since that is the whole recovery.
"""
import json
import struct
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

import pytest

from doc_analysis import save_document_figure
from doc_analysis.parity import snapshot
from doc_analysis.save_figure import MANIFEST_NAME


def png_bytes(width=1125, height=720):
    """A PNG header parity.png_size can read: signature, then IHDR width/height."""
    return (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR"
            + struct.pack(">II", width, height))


class FakePlotlyFigure:
    """Duck-types what the saver asks of a plotly Figure — and nothing else."""

    def __init__(self, hovertemplate=None):
        self.data = [SimpleNamespace(hovertemplate=hovertemplate)]
        self.image_kwargs = None
        self.html_kwargs = None

    def write_image(self, path, **kwargs):
        self.image_kwargs = kwargs
        Path(path).write_bytes(png_bytes())

    def write_html(self, path, **kwargs):
        self.html_kwargs = kwargs
        Path(path).write_text("<html>fake</html>", encoding="utf-8")


class FakeMatplotlibFigure:
    """A figure with savefig and no write_image: the static-only branch."""

    def __init__(self):
        self.savefig_kwargs = None

    def savefig(self, path, **kwargs):
        self.savefig_kwargs = kwargs
        Path(path).write_bytes(png_bytes())


@pytest.fixture
def document(tmp_path):
    """A document repo layout plus an html dir, as (section_dir, html_dir, repo)."""
    section = tmp_path / "repo" / "Sections" / "Example"
    section.mkdir(parents=True)
    (section / "example.tex").write_text("", encoding="utf-8")
    html_dir = tmp_path / "figures_html"
    return section, html_dir, tmp_path / "repo"


@pytest.fixture
def kaleido(monkeypatch):
    """Satisfy the saver's kaleido probe without installing it."""
    monkeypatch.setitem(sys.modules, "kaleido", SimpleNamespace())


def manifest_of(html_dir):
    return json.loads((html_dir / MANIFEST_NAME).read_text(encoding="utf-8"))


def save(fig, document, name="example_scatter.png", **kwargs):
    section, html_dir, _ = document
    return save_document_figure(name, fig=fig, section=section, html_dir=html_dir,
                                **kwargs)


# --------------------------------------------------------------- matplotlib

def test_matplotlib_save_writes_only_the_png(document):
    section, html_dir, _ = document
    path = save(FakeMatplotlibFigure(), document)

    assert path == section / "Figures" / "example_scatter.png"
    assert path.exists()
    assert not (html_dir / "example_scatter.html").exists()


def test_matplotlib_save_records_a_manifest_entry(document):
    _, html_dir, _ = document
    save(FakeMatplotlibFigure(), document)

    entry = manifest_of(html_dir)["Fig: example_scatter"]
    assert entry["interactive"] is None
    assert entry["backend"] == "matplotlib"
    assert entry["stem"] == "example_scatter"
    assert entry["static"].endswith("example_scatter.png")


def test_matplotlib_save_emits_no_warning(document):
    """Choosing the fallback is a choice, not something to be nagged about."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        save(FakeMatplotlibFigure(), document)
    assert [str(w.message) for w in caught] == []


def test_matplotlib_save_appends_the_commented_block(document):
    """The LaTeX side is backend-blind: same append, same gate."""
    section, _, _ = document
    save(FakeMatplotlibFigure(), document)
    tex = (section / "example.tex").read_text(encoding="utf-8")
    assert "example_scatter" in tex
    assert all(line.startswith("%") for line in tex.splitlines() if line.strip())


def test_fig_none_without_matplotlib_names_the_extra(document, monkeypatch):
    monkeypatch.setitem(sys.modules, "matplotlib.pyplot", None)
    with pytest.raises(ImportError) as excinfo:
        save(None, document)
    assert "--extra matplotlib" in str(excinfo.value)


# --------------------------------------------------------------- plotly

def test_plotly_save_writes_png_and_html(document, kaleido):
    section, html_dir, _ = document
    fig = FakePlotlyFigure(hovertemplate="case=%{customdata[0]}")
    path = save(fig, document)

    assert path.exists()
    assert (html_dir / "example_scatter.html").exists()
    # "directory", never "cdn": the published site has to work offline.
    assert fig.html_kwargs["include_plotlyjs"] == "directory"


def test_plotly_manifest_entry_points_at_the_export(document, kaleido):
    _, html_dir, _ = document
    save(FakePlotlyFigure(hovertemplate="x"), document, hover_fields=["case"])

    entry = manifest_of(html_dir)["Fig: example_scatter"]
    assert entry["interactive"] == "example_scatter.html"
    assert entry["backend"] == "plotly"
    assert entry["hover_fields"] == ["case"]


def test_default_hover_warns_without_naming_a_domain(document, kaleido):
    with pytest.warns(UserWarning) as caught:
        save(FakePlotlyFigure(), document)
    message = str(caught[0].message)
    assert "hovertemplate" in message and "hover_fields" in message
    # This is a template: the warning must not describe someone else's dataset.
    assert "dwelling" not in message.lower()


def test_hovertemplate_suppresses_the_warning(document, kaleido):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        save(FakePlotlyFigure(hovertemplate="case=%{x}"), document)
    assert [str(w.message) for w in caught] == []


def test_missing_kaleido_names_the_extra(document, monkeypatch):
    # None in sys.modules makes `import kaleido` fail whether or not it is installed.
    monkeypatch.setitem(sys.modules, "kaleido", None)
    with pytest.raises(ImportError) as excinfo:
        save(FakePlotlyFigure(), document)
    assert "--extra plotly" in str(excinfo.value)


def test_static_scale_reaches_write_image(document, kaleido):
    fig = FakePlotlyFigure(hovertemplate="x")
    save(fig, document, static_scale=3)
    assert fig.image_kwargs["scale"] == 3


# --------------------------------------------------------------- together

def test_one_parity_baseline_covers_both_backends(document, kaleido, tmp_path):
    """The payoff of giving matplotlib figures a manifest entry.

    `snapshot` builds its baseline by walking the manifest, so a backend missing from
    the manifest is a backend the size-drift guard silently does not protect.
    """
    _, html_dir, repo = document
    save(FakePlotlyFigure(hovertemplate="x"), document, name="from_plotly.png")
    save(FakeMatplotlibFigure(), document, name="from_matplotlib.png")

    baseline_path = tmp_path / "baseline.json"
    assert snapshot(repo, html_dir=html_dir, baseline_path=baseline_path) == 0

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert set(baseline) == {"from_plotly.png", "from_matplotlib.png"}
    assert all(entry["width"] == 1125 for entry in baseline.values())
