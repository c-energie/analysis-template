"""save_value: a computed scalar written into the document as a LaTeX macro.

The point of the feature is that a number quoted in the prose cannot drift from the
analysis, so what these tests pin is everything that would let it drift quietly: a macro
name that is not a legal TeX control word, a re-save that appends a second definition
(the document then shows whichever is loaded last), a formatting option that renders
something other than what was asked, a value written into a section the document never
loads, and a figure save broken by the new values.tex sitting beside the section's .tex.

Everything writes to tmp_path; no document repo is needed.
"""
import warnings

import pytest

from doc_analysis import notebook_savers
from doc_analysis.save_figure import _append_commented_block
from doc_analysis.save_value import (check_values_loaded, find_value_reference,
                                       format_value, macro_name, save_document_value)


@pytest.fixture
def section(tmp_path):
    """A standalone section with one .tex: no Sections/ ancestor, so no loading check."""
    (tmp_path / "section.tex").write_text("Some prose.\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def document(tmp_path):
    """A document root with Sections/Results and a settings file holding \\graphicspath."""
    results = tmp_path / "Sections" / "Results"
    results.mkdir(parents=True)
    (results / "results.tex").write_text("Prose.\n", encoding="utf-8")
    (tmp_path / "document_settings.sty").write_text(
        "\\graphicspath{%\n  {Sections/Results/Figures/}%\n}\n", encoding="utf-8")
    return tmp_path


def values_text(section_dir):
    return (section_dir / "values.tex").read_text(encoding="utf-8")


# --------------------------------------------------------------- macro names

@pytest.mark.parametrize("name, macro", [
    ("ptg_mlr_agreement", "ptgMlrAgreement"),
    ("cv_rmse_20", "cvRmseTwoZero"),
    ("r2_score", "rTwoScore"),         # a digit inside a word is spelled out too
    ("20_cv", "twoZeroCv"),            # a leading digit still gives a lower-case start
    ("PTG_MLR", "ptgMlr"),             # case in the name does not leak into the macro
    ("cohort-size", "cohortSize"),
])
def test_macro_name_is_lower_camel_case_letters_only(name, macro):
    """TeX control words are letters only: a digit left in would end the macro early."""
    assert macro_name(name) == macro


def test_macro_override_replaces_the_derived_name(section):
    save_document_value("cv_rmse_20", 1.5, macro="\\rmseTwenty", section=str(section))
    text = values_text(section)
    assert "\\renewcommand{\\rmseTwenty}{1.50}" in text
    assert "cvRmseTwoZero" not in text


@pytest.mark.parametrize("macro", ["rmse20", "rmse_twenty", ""])
def test_macro_override_that_is_not_letters_only_is_refused(section, macro):
    with pytest.raises(ValueError, match="letters only"):
        save_document_value("rmse", 1.0, macro=macro, section=str(section))
    assert not (section / "values.tex").exists()


# --------------------------------------------------------------- formatting

@pytest.mark.parametrize("kwargs, rendered", [
    ({}, "0.87"),
    ({"decimals": 0}, "1"),
    ({"decimals": 3}, "0.873"),
    ({"fmt": "percent"}, "87.30\\%"),
    ({"fmt": "percent", "decimals": 1}, "87.3\\%"),
    ({"fmt": "percent", "scale": 1}, "0.87\\%"),     # scale replaces the implied 100
    ({"scale": 1000, "decimals": 0}, "873"),
    ({"signed": True}, "$+0.87$"),
    ({"unit": "kWh"}, "0.87\\,kWh"),
    ({"fmt": "percent", "signed": True, "decimals": 1}, "$+87.3$\\%"),
    ({"scale": 1000, "decimals": 0, "unit": "W", "signed": True}, "$+873$\\,W"),
])
def test_format_value_options(kwargs, rendered):
    assert format_value(0.873, **kwargs) == rendered


def test_signed_negative_value_uses_a_math_minus():
    assert format_value(-1.25, signed=True) == "$-1.25$"


def test_value_rounding_to_zero_has_no_minus_sign():
    """-0.001 at two decimals is -0.00 in Python's formatting, which reads as a result."""
    assert format_value(-0.001) == "0.00"
    assert format_value(-0.001, signed=True) == "$+0.00$"


def test_string_value_passes_through_unchanged():
    assert format_value("$\\sim$3 weeks", fmt="percent", unit="d", signed=True) == \
        "$\\sim$3 weeks"


def test_unknown_fmt_is_refused():
    """A typo such as fmt="percentage" must not silently render the bare number."""
    with pytest.raises(ValueError, match="fmt"):
        format_value(0.5, fmt="percentage")


# --------------------------------------------------------------- the library file

def test_block_defines_the_macro_robustly(section):
    """\\providecommand then \\renewcommand survives a double input and keeps no stale value."""
    save_document_value("ptg_mlr_agreement", 0.873, section=str(section))
    text = values_text(section)
    assert "%<*ptg_mlr_agreement>" in text and "%</ptg_mlr_agreement>" in text
    assert "% written by save_value" in text and "edit the notebook" in text
    provide = text.index("\\providecommand{\\ptgMlrAgreement}{}")
    renew = text.index("\\renewcommand{\\ptgMlrAgreement}{0.87}")
    assert provide < renew


def test_swapped_value_and_name_raise_type_error(section):
    """The worker takes (name, value) and the saver (value, name): the easy mistake."""
    with pytest.raises(TypeError, match="swapped"):
        save_document_value(0.873, "ptg_mlr_agreement", section=str(section))
    assert not (section / "values.tex").exists()


def test_resave_replaces_the_block_rather_than_appending(section):
    """Two definitions of one macro and the prose shows whichever is loaded last."""
    save_document_value("ptg_mlr_agreement", 0.873, section=str(section))
    save_document_value("ptg_mlr_agreement", 0.912, section=str(section))
    text = values_text(section)
    assert text.count("%<*ptg_mlr_agreement>") == 1
    assert "{0.91}" in text and "{0.87}" not in text


def test_two_values_coexist_in_one_library(section):
    save_document_value("ptg_mlr_agreement", 0.873, section=str(section))
    save_document_value("cv_rmse_20", 4.2, unit="K", section=str(section))
    save_document_value("ptg_mlr_agreement", 0.5, section=str(section))
    text = values_text(section)
    assert "\\renewcommand{\\ptgMlrAgreement}{0.50}" in text
    assert "\\renewcommand{\\cvRmseTwoZero}{4.20\\,K}" in text


def test_two_names_mapping_to_one_macro_are_refused(section):
    """"a_b" and "a__b" are two blocks but one macro; the later would silently win."""
    save_document_value("cv_rmse", 1.0, section=str(section))
    with pytest.raises(ValueError, match="already defined"):
        save_document_value("cv__rmse", 2.0, section=str(section))
    assert "{1.00}" in values_text(section)


# --------------------------------------------------------------- reference hint

def test_reference_is_appended_once_when_the_macro_is_unused(section):
    save_document_value("ptg_mlr_agreement", 0.873, section=str(section))
    save_document_value("ptg_mlr_agreement", 0.9, section=str(section))
    tex = (section / "section.tex").read_text(encoding="utf-8")
    assert tex.count("% \\ptgMlrAgreement") == 1
    assert find_value_reference(section, "ptgMlrAgreement") == section / "section.tex"


def test_no_reference_when_the_prose_already_uses_the_macro(section):
    (section / "section.tex").write_text("Agreement was \\ptgMlrAgreement{}.\n",
                                         encoding="utf-8")
    save_document_value("ptg_mlr_agreement", 0.873, section=str(section))
    assert (section / "section.tex").read_text(encoding="utf-8") == \
        "Agreement was \\ptgMlrAgreement{}.\n"


def test_a_longer_macro_is_not_a_use_of_a_shorter_one(section):
    """\\cvRmseTwoZero in the prose must not count as a use of \\cvRmse."""
    (section / "section.tex").write_text("\\cvRmseTwoZero\n", encoding="utf-8")
    assert find_value_reference(section, "cvRmse") is None


def test_tex_false_skips_the_reference(section):
    save_document_value("ptg_mlr_agreement", 0.873, section=str(section), tex=False)
    assert (section / "section.tex").read_text(encoding="utf-8") == "Some prose.\n"


def test_tex_names_the_target_in_a_section_with_several(section):
    (section / "other.tex").write_text("", encoding="utf-8")
    save_document_value("ptg_mlr_agreement", 0.873, section=str(section), tex="other.tex")
    assert "\\ptgMlrAgreement" in (section / "other.tex").read_text(encoding="utf-8")


def test_values_library_does_not_make_a_figure_target_ambiguous(section):
    """values.tex beside a section's one .tex must not count as a second candidate.

    Otherwise every save with tex=None in that section raises after the first value.
    """
    save_document_value("ptg_mlr_agreement", 0.873, section=str(section))
    (section / "tables.tex").write_text("", encoding="utf-8")
    assert _append_commented_block(section, "\\begin{figure}") == section / "section.tex"


# --------------------------------------------------------------- loading check

def test_warns_with_the_exact_line_when_values_tex_is_not_loaded(document):
    section_dir = document / "Sections" / "Results"
    with pytest.warns(UserWarning, match="document_settings.sty") as caught:
        save_document_value("ptg_mlr_agreement", 0.873, section=str(section_dir))
    assert "\\InputIfFileExists{Sections/Results/values.tex}{}{}" in str(caught[0].message)
    # Never edits the preamble: the line is the author's to add.
    assert "InputIfFileExists" not in (document / "document_settings.sty").read_text(
        encoding="utf-8")


def test_no_warning_when_the_settings_file_loads_it(document):
    settings = document / "document_settings.sty"
    settings.write_text(settings.read_text(encoding="utf-8")
                        + "\\InputIfFileExists{Sections/Results/values.tex}{}{}\n",
                        encoding="utf-8")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert check_values_loaded(document / "Sections" / "Results") is None


def test_a_commented_loading_line_does_not_count(document):
    settings = document / "document_settings.sty"
    settings.write_text(settings.read_text(encoding="utf-8")
                        + "% \\InputIfFileExists{Sections/Results/values.tex}{}{}\n",
                        encoding="utf-8")
    with pytest.warns(UserWarning, match="not loaded"):
        check_values_loaded(document / "Sections" / "Results")


def test_another_sections_line_does_not_count(document):
    settings = document / "document_settings.sty"
    settings.write_text("\\InputIfFileExists{Sections/Other/values.tex}{}{}\n",
                        encoding="utf-8")
    with pytest.warns(UserWarning, match="Sections/Results/values.tex"):
        check_values_loaded(document / "Sections" / "Results")


def test_no_loading_check_outside_a_sections_tree(section):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        save_document_value("ptg_mlr_agreement", 0.873, section=str(section))


# --------------------------------------------------------------- notebook_savers

def test_notebook_savers_still_returns_two_without_values(tmp_path):
    """Every existing notebook unpacks exactly two savers."""
    savers = notebook_savers(section=str(tmp_path), notebook="n.ipynb",
                             config_path=tmp_path / "figures_config.toml")
    assert len(savers) == 2


def test_notebook_savers_returns_save_value_with_values_true(section):
    config = section / "figures_config.toml"
    _, _, save_value = notebook_savers(section=str(section), notebook="n.ipynb",
                                       config_path=config, values=True)
    assert save_value(0.873, "ptg_mlr_agreement") == section / "values.tex"
    assert "by n.ipynb" in values_text(section)
    assert "[n.values]\nptg_mlr_agreement = true" in config.read_text(encoding="utf-8")


def test_values_config_gates_the_write(section):
    config = section / "figures_config.toml"
    config.write_text("default = true\n\n[n.values]\nptg_mlr_agreement = false\n",
                      encoding="utf-8")
    _, _, save_value = notebook_savers(section=str(section), notebook="n.ipynb",
                                       config_path=config, values=True)
    assert save_value(0.873, "ptg_mlr_agreement") is None
    assert not (section / "values.tex").exists()


def test_save_values_master_switch_vetoes(section):
    config = section / "figures_config.toml"
    config.write_text("default = true\nsave_values = false\n", encoding="utf-8")
    _, _, save_value = notebook_savers(section=str(section), notebook="n.ipynb",
                                       config_path=config, values=True)
    assert save_value(0.873, "ptg_mlr_agreement") is None
    assert not (section / "values.tex").exists()


def test_saver_swapped_arguments_raise_before_the_config_records_them(section):
    config = section / "figures_config.toml"
    _, _, save_value = notebook_savers(section=str(section), notebook="n.ipynb",
                                       config_path=config, values=True)
    with pytest.raises(TypeError, match="swapped"):
        save_value("ptg_mlr_agreement", 0.873)
    assert not config.exists()


def test_saver_refuses_a_template_placeholder(section):
    config = section / "figures_config.toml"
    _, _, save_value = notebook_savers(section=str(section), notebook="n.ipynb",
                                       config_path=config, values=True)
    with pytest.raises(ValueError, match="placeholder"):
        save_value(1.0, "<<VALUE>>")
    assert not config.exists()
