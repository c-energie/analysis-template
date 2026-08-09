"""The switchboard that decides whether a notebook run may write an artefact.

Two properties matter enough to pin. First, an unlisted name takes the `default` value and
that value is honoured on the spot, so there is no "first run is special" case to reason
about — whatever the config says is what happens, including for names it has never seen.
Second, the file stays hand-editable: appending a newly seen name must not destroy comments
or ordering, which is why entries are inserted textually rather than re-serialised.

The fixture below pins `default = false` so the recording tests are unambiguous; the
shipped config uses `default = true`.
"""
import pytest

from PACKAGE_NAME.figure_config import (FIGURES, TABLES, entry_name, init_config,
                                          is_enabled, load_config)

CONFIG = """\
# A comment that must survive an append.
default = false
save_figures = true
save_tables = true

[dataset_assessment.figures]
coverage_timeline = true    # trailing comment
degree_day_scatter = false

[dataset_assessment.tables]
cohort_summary = true

[clustering_results.figures]
cluster_smeter_results = true
"""


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "figures_config.toml"
    path.write_text(CONFIG, encoding="utf-8")
    return path


# --------------------------------------------------------------- reading

def test_listed_true_enables(config):
    assert is_enabled("dataset_assessment", "coverage_timeline.png", FIGURES, path=config)


def test_listed_false_disables(config):
    assert not is_enabled("dataset_assessment", "degree_day_scatter.png", FIGURES,
                          path=config)


def test_extension_is_ignored(config):
    """'x.png' and 'x' are the same entry - call sites spell it both ways."""
    for name in ("coverage_timeline", "coverage_timeline.png"):
        assert is_enabled("dataset_assessment", name, FIGURES, path=config)
    assert entry_name("a/b/c.png") == "c"


def test_figures_and_tables_are_separate_namespaces(config):
    """A figure and a table may share a name without colliding."""
    assert is_enabled("dataset_assessment", "cohort_summary", TABLES, path=config)
    # Same name as a figure: unlisted there, so it takes the default (false).
    assert not is_enabled("dataset_assessment", "cohort_summary", FIGURES, path=config)


def test_master_switch_vetoes(config, tmp_path):
    path = tmp_path / "off.toml"
    path.write_text(CONFIG.replace("save_figures = true", "save_figures = false"),
                    encoding="utf-8")
    assert not is_enabled("dataset_assessment", "coverage_timeline", FIGURES, path=path)
    # ...and only figures: tables are unaffected.
    assert is_enabled("dataset_assessment", "cohort_summary", TABLES, path=path)


def test_master_switch_cannot_turn_an_entry_on(config, tmp_path):
    """save_figures = true is a veto that is not exercised, not an override."""
    path = tmp_path / "on.toml"
    path.write_text(CONFIG, encoding="utf-8")
    assert not is_enabled("dataset_assessment", "degree_day_scatter", FIGURES, path=path)


# --------------------------------------------------------------- recording

def test_unlisted_name_takes_the_default_and_is_recorded(config):
    assert not is_enabled("clustering_results", "brand_new", FIGURES, path=config)
    assert load_config(config)["clustering_results"][FIGURES]["brand_new"] is False


def test_default_true_saves_new_names_on_sight(tmp_path):
    path = tmp_path / "figures_config.toml"
    path.write_text(CONFIG.replace("default = false", "default = true"), encoding="utf-8")
    assert is_enabled("clustering_results", "brand_new", FIGURES, path=path)
    assert load_config(path)["clustering_results"][FIGURES]["brand_new"] is True


def test_recording_is_idempotent(config):
    for _ in range(3):
        is_enabled("clustering_results", "brand_new", FIGURES, path=config)
    assert config.read_text(encoding="utf-8").count("brand_new") == 1


def test_append_preserves_comments_and_ordering(config):
    is_enabled("dataset_assessment", "brand_new", FIGURES, path=config)
    text = config.read_text(encoding="utf-8")
    assert "# A comment that must survive an append." in text
    assert "# trailing comment" in text
    # Inserted into its own block, not appended to the end of the file.
    figures_block = text.index("[dataset_assessment.figures]")
    tables_block = text.index("[dataset_assessment.tables]")
    assert figures_block < text.index("brand_new") < tables_block


def test_new_section_creates_its_block(config):
    assert not is_enabled("a_new_notebook", "some_figure", FIGURES, path=config)
    text = config.read_text(encoding="utf-8")
    assert "[a_new_notebook.figures]" in text
    assert load_config(config)["a_new_notebook"][FIGURES]["some_figure"] is False


def test_record_false_leaves_the_file_alone(config):
    before = config.read_text(encoding="utf-8")
    is_enabled("clustering_results", "brand_new", FIGURES, path=config, record=False)
    assert config.read_text(encoding="utf-8") == before


# --------------------------------------------------------------- init-figures-config

def test_init_writes_the_flags_it_is_given(tmp_path):
    """Flags supplied up front mean no prompt, so the entry point is scriptable."""
    path = tmp_path / "figures_config.toml"
    assert init_config(path=path, default=False, save_figures=True,
                       save_tables=False) == path
    config = load_config(path)
    assert (config["default"], config["save_figures"], config["save_tables"]) == \
           (False, True, False)


def test_init_leaves_an_existing_config_alone(tmp_path):
    path = tmp_path / "figures_config.toml"
    path.write_text(CONFIG, encoding="utf-8")
    assert init_config(path=path, default=True, save_figures=True,
                       save_tables=True) is None
    assert path.read_text(encoding="utf-8") == CONFIG


def test_init_force_replaces(tmp_path):
    path = tmp_path / "figures_config.toml"
    path.write_text(CONFIG, encoding="utf-8")
    assert init_config(path=path, default=True, save_figures=True, save_tables=True,
                       force=True) == path
    assert "dataset_assessment" not in path.read_text(encoding="utf-8")


def test_init_output_is_a_usable_config(tmp_path):
    """What it writes must parse and gate, not just look right."""
    path = tmp_path / "figures_config.toml"
    init_config(path=path, default=True, save_figures=True, save_tables=False)
    assert is_enabled("a_notebook", "a_figure", FIGURES, path=path)
    assert not is_enabled("a_notebook", "a_table", TABLES, path=path)   # master vetoes


def test_missing_config_is_bootstrapped(tmp_path):
    """No config at all: write one rather than exploding, and take the shipped default."""
    path = tmp_path / "figures_config.toml"
    assert is_enabled("some_notebook", "some_figure", FIGURES, path=path)
    assert path.exists()
    config = load_config(path)
    assert config["default"] is True
    assert config["some_notebook"][FIGURES]["some_figure"] is True
