"""Figure and table tooling for the document.

    from doc_analysis import save_document_figure, save_document_table, figure_size

The LaTeX document repo is located via `DOC_REPO`, read from the checkout's own `.env`;
nothing here hardcodes a path, and nothing here depends on a private package.

**Both plotting backends are optional extras.** Plotly is the preferred one — a plotly
figure produces the committed PNG *and* an interactive HTML export from the same object
— and matplotlib is the static-only fallback:

    uv sync --extra plotly        # or --extra matplotlib

Whichever is installed styles itself on import of this package, exactly as before: the
plotly template registers as the default, the matplotlib rcParams are applied, and both
are built from the same constants in `style.py`. Reaching for a name that needs an
extra you have not installed raises an ImportError naming the extra, rather than an
AttributeError a long way from the cause.
"""

from importlib.util import find_spec

# Before anything reads the environment, so DOC_REPO can live in the checkout rather
# than in a shell profile. A variable already set in the shell still wins — see env.py.
from doc_analysis.env import load_env

load_env()

from doc_analysis.style import CATEGORICAL, DIVERGING
from doc_analysis.save_figure import (
    add_commented_figure_to_tex,
    chapters_dir,
    find_figure_reference,
    save_document_figure,
    sections_dir,
    select_chapter_dir,
    select_section_dir,
    document_repo,
)
from doc_analysis.save_table import (
    dataframe_to_latex,
    find_table_reference,
    save_document_table,
)
from doc_analysis.figure_config import (
    config_path,
    is_enabled,
    load_config,
)
from doc_analysis.savers import notebook_savers

__all__ = [
    "load_env",
    "CATEGORICAL",
    "DIVERGING",
    "add_commented_figure_to_tex",
    "find_figure_reference",
    "save_document_figure",
    "sections_dir",
    "select_section_dir",
    "document_repo",
    "dataframe_to_latex",
    "find_table_reference",
    "save_document_table",
    "config_path",
    "is_enabled",
    "load_config",
    "notebook_savers",
    # Deprecated spellings, kept importable for pre-rename notebooks.
    "chapters_dir",
    "select_chapter_dir",
]

# Which names come from which extra. Probing with find_spec rather than catching
# ImportError is deliberate: a genuine failure *inside* theme.py — a broken plotly
# install, a typo in the template — must still propagate, and a bare except here would
# swallow it and leave figures silently unstyled.
_EXTRA_NAMES = {
    "plotly": ("TEMPLATE_NAME", "activate_template", "figure_size"),
    "matplotlib": ("STYLE", "activate_style", "diverging_cmap", "figure_size_in"),
}

if find_spec("plotly") is not None:
    from doc_analysis.theme import TEMPLATE_NAME, activate_template, figure_size

    __all__ += list(_EXTRA_NAMES["plotly"])

if find_spec("matplotlib") is not None:
    from doc_analysis.theme_mpl import (
        STYLE,
        activate_style,
        diverging_cmap,
        figure_size_in,
    )

    __all__ += list(_EXTRA_NAMES["matplotlib"])

_MISSING = {name: extra
            for extra, names in _EXTRA_NAMES.items()
            if find_spec(extra) is None
            for name in names}


def __getattr__(name):
    """Explain a name that needs an uninstalled extra, instead of AttributeError."""
    extra = _MISSING.get(name)
    if extra is not None:
        raise ImportError(
            f"doc_analysis.{name} needs the '{extra}' extra, which is not installed:\n"
            f"    uv sync --extra {extra}    (or: pip install -e '.[{extra}]')"
        )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
