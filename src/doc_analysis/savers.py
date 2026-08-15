"""One save_fig / save_table pair, shared by every notebook.

Each notebook used to carry its own copy of these closures plus a SAVE_FIGURES constant.
That put the same eight lines in eight places and made the on/off decision a source edit.
Here the pair is built once and bound to the notebook's chapter, so a cell still reads::

    save_fig(fig, "coverage_timeline.png", hover_fields=["dwelling", "stream"])

and whether that writes anything is decided by figures_config.toml (see figure_config).

Chapter, notebook and tex stay declared at the top of the notebook: they say where a
figure belongs, which is part of what the notebook *is*, whereas the config says whether
this particular run should write it.
"""

from doc_analysis.figure_config import FIGURES, TABLES, entry_name, is_enabled
from doc_analysis.save_figure import save_document_figure
from doc_analysis.save_table import save_document_table


def notebook_savers(chapter, notebook, tex=None, section=None, config_path=None):
    """Return (save_fig, save_table) bound to one notebook's chapter.

    chapter is the path under $DOC_REPO/Chapters, notebook the .ipynb filename (it is
    recorded in the figure manifest), and tex names the chapter .tex file that should
    receive a commented reference when an artefact is not referenced yet — required in
    chapters holding several .tex files, which otherwise raise rather than guess. section
    is the config section, defaulting to the notebook's stem.

    Neither helper forces tex=False any more: appending is gated on the chapter not
    already referencing the artefact, so a re-save cannot produce a duplicate block.
    """
    section = section if section is not None else entry_name(notebook)

    def save_fig(fig, name, hover_fields=None, **kwargs):
        """Write the chapter PNG and the interactive export, if the config allows it."""
        if not is_enabled(section, name, FIGURES, path=config_path):
            return None
        kwargs.setdefault("tex", tex)
        return save_document_figure(name, fig=fig, chapter=chapter, notebook=notebook,
                                  hover_fields=hover_fields, **kwargs)

    def save_table(df, name, caption=None, **kwargs):
        """Write a DataFrame into the chapter's tables.tex, if the config allows it."""
        if not is_enabled(section, name, TABLES, path=config_path):
            return None
        kwargs.setdefault("tex", tex)
        return save_document_table(df, name, caption=caption, chapter=chapter, **kwargs)

    return save_fig, save_table
