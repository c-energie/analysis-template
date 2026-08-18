"""One save_fig / save_table pair, shared by every notebook.

Each notebook used to carry its own copy of these closures plus a SAVE_FIGURES constant.
That put the same eight lines in eight places and made the on/off decision a source edit.
Here the pair is built once and bound to the notebook's section, so a cell still reads::

    save_fig(fig, "coverage_timeline.png", hover_fields=["dwelling", "stream"])

and whether that writes anything is decided by figures_config.toml (see figure_config).

Section, notebook and tex stay declared at the top of the notebook: they say where a
figure belongs, which is part of what the notebook *is*, whereas the config says whether
this particular run should write it.

Note the two senses of "section" that meet here, and are kept apart by name: `section` is
the division of the document (a directory under $DOC_REPO/Sections), while
`config_section` is the TOML table in figures_config.toml, keyed by notebook stem.
"""

import warnings

from doc_analysis.figure_config import FIGURES, TABLES, entry_name, is_enabled
from doc_analysis.save_figure import save_document_figure
from doc_analysis.save_table import save_document_table


def notebook_savers(section=None, notebook=None, tex=None, config_section=None,
                    config_path=None, chapter=None):
    """Return (save_fig, save_table) bound to one notebook's section.

    section is the path under $DOC_REPO/Sections, notebook the .ipynb filename (it is
    recorded in the figure manifest), and tex names the section .tex file that should
    receive a commented reference when an artefact is not referenced yet — required in
    sections holding several .tex files, which otherwise raise rather than guess.
    config_section is the figures_config.toml table, defaulting to the notebook's stem.

    Neither helper forces tex=False any more: appending is gated on the section not
    already referencing the artefact, so a re-save cannot produce a duplicate block.

    chapter= is the pre-rename spelling of section=; it still works and warns. The old
    `section=` argument — which meant the config table, not the document division — is
    now `config_section=`, so a call passing the old `section=` positionally or by
    keyword now names the document division instead. That is the one change here that
    cannot be detected at runtime: both spellings take a plain string.
    """
    if chapter is not None:
        if section is not None:
            raise TypeError("pass either section= or chapter=, not both")
        warnings.warn("chapter= is deprecated; use section=.",
                      DeprecationWarning, stacklevel=2)
        section = chapter
    if section is None:
        raise TypeError("notebook_savers() needs section= (the path under "
                        "$DOC_REPO/Sections)")
    if notebook is None:
        raise TypeError("notebook_savers() needs notebook= (the .ipynb filename)")

    config_section = config_section if config_section is not None else entry_name(notebook)

    def save_fig(fig, name, hover_fields=None, **kwargs):
        """Write the section PNG and the interactive export, if the config allows it."""
        if not is_enabled(config_section, name, FIGURES, path=config_path):
            return None
        kwargs.setdefault("tex", tex)
        return save_document_figure(name, fig=fig, section=section, notebook=notebook,
                                  hover_fields=hover_fields, **kwargs)

    def save_table(df, name, caption=None, **kwargs):
        """Write a DataFrame into the section's tables.tex, if the config allows it."""
        if not is_enabled(config_section, name, TABLES, path=config_path):
            return None
        kwargs.setdefault("tex", tex)
        return save_document_table(df, name, caption=caption, section=section, **kwargs)

    return save_fig, save_table
