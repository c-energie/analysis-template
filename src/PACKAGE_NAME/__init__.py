"""Figure and table tooling for the document.

Importing this package registers the shared plotly template as the default, so every
figure is styled consistently without per-notebook setup.

    from PACKAGE_NAME import save_document_figure, save_document_table, figure_size

The LaTeX document repo is located via the DOCUMENT_REPO environment variable;
nothing here hardcodes a path, and nothing here depends on a private package.
"""

from PACKAGE_NAME.theme import (
    TEMPLATE_NAME,
    activate_template,
    figure_size,
)
from PACKAGE_NAME.save_figure import (
    add_commented_figure_to_tex,
    chapters_dir,
    find_figure_reference,
    save_document_figure,
    select_chapter_dir,
    document_repo,
)
from PACKAGE_NAME.save_table import (
    dataframe_to_latex,
    find_table_reference,
    save_document_table,
)
from PACKAGE_NAME.figure_config import (
    config_path,
    is_enabled,
    load_config,
)
from PACKAGE_NAME.savers import notebook_savers

__all__ = [
    "TEMPLATE_NAME",
    "activate_template",
    "figure_size",
    "add_commented_figure_to_tex",
    "chapters_dir",
    "find_figure_reference",
    "save_document_figure",
    "select_chapter_dir",
    "document_repo",
    "dataframe_to_latex",
    "find_table_reference",
    "save_document_table",
    "config_path",
    "is_enabled",
    "load_config",
    "notebook_savers",
]