"""One call that makes a notebook behave the same wherever its kernel started.

    from doc_analysis import notebook_setup
    ROOT = notebook_setup()

The setup used to be a file, `notebooks/setup_notebook.py`, found by walking *up* from
the working directory. In a document workspace the analysis repo is a member *below* the
workspace root, and an IDE that opens the workspace as the project starts its kernel
there — so the walk found nothing, and even past it the `.env` holding `DOC_REPO` was
never reached. The package is installed (editable) into the workspace venv, so it already
knows where its checkout is: that, not the working directory, is what locates the repo.

Idempotent: a notebook re-running its setup cell, or importing the compatibility module
after calling this, changes nothing the first call did not.
"""

import os
import sys
from importlib.util import find_spec
from pathlib import Path

from doc_analysis import env

NOTEBOOKS_DIRNAME = "notebooks"


def notebook_setup(package_dir=None):
    """Load the env, style the backend, move to the analysis repo root; return the root.

    The `.env` resolution is the usual one (real variable, `$DOC_ENV`, nearest `.env`
    above the cwd), then — only if that found nothing — the `.env` of the checkout the
    package is installed from. A real environment variable is never overridden.

    The repo's `notebooks/` goes on `sys.path`, so a helper module kept beside the
    notebooks imports from a notebook in any sub-folder.

    `package_dir` stands in for this package's installed location, for tests. When it is
    not inside a checkout (a non-editable install) the fallback is skipped, the working
    directory is left alone and the root returned is the one holding the `.env` used,
    else the cwd; `document_repo()` then explains what was searched.
    """
    root = env.checkout_root(package_dir)
    found = env.load_env(fallback=root)
    _style()

    if root is None:
        env.LAST_SEARCH["checkout"] = (
            Path(package_dir) if package_dir else Path(env.__file__).resolve().parent
        )
        return found.parent if found is not None else Path.cwd()

    notebooks = str(root / NOTEBOOKS_DIRNAME)
    if notebooks not in sys.path:
        sys.path.insert(0, notebooks)

    os.chdir(root)
    return root


def _style():
    """Re-apply whichever backend's styling is installed, plus the notebook renderer.

    Importing the package already styled it; doing it again here means a setup cell
    re-run after a stray `plt.rcdefaults()` restores the document's look. Probed with
    find_spec, like the package's own imports, so neither backend is required.
    """
    if find_spec("plotly") is not None:
        import plotly.io as pio

        from doc_analysis.theme import activate_template

        activate_template()
        # "notebook" renders in both JupyterLab and VS Code; "jupyterlab" is fine if you
        # only ever use the former.
        pio.renderers.default = "notebook"

    if find_spec("matplotlib") is not None:
        from doc_analysis.theme_mpl import activate_style

        activate_style()
