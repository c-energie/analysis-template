"""One call that makes a notebook behave the same wherever its kernel started.

    from doc_analysis import notebook_setup
    ROOT = notebook_setup()

The setup used to be a file, `notebooks/setup_notebook.py`, found by walking *up* from
the working directory. In a document workspace the analysis repo is a member *below* the
workspace root, and an IDE that opens the workspace as the project starts its kernel
there — so the walk found nothing, and even past it the `.env` holding `DOC_REPO` was
never reached. The package is installed (editable) into the workspace venv, so it already
knows where its checkout is: that is what locates the repo when the working directory is
in none.

When the working directory *is* in a checkout, that checkout wins. Two analysis repos
installed into one venv share whichever `doc_analysis` comes first on `sys.path`, so the
package's location named the same checkout for both, and the other's notebooks wrote into
its document (issue #24). Only the cwd tells them apart.

Idempotent: a notebook re-running its setup cell, or importing the compatibility module
after calling this, changes nothing the first call did not.
"""

import os
import sys
import warnings
from importlib.util import find_spec
from pathlib import Path

from doc_analysis import env

NOTEBOOKS_DIRNAME = "notebooks"


def notebook_setup(package_dir=None):
    """Load the env, style the backend, move to the analysis repo root; return the root.

    The root is the active checkout (`env.active_checkout`): the analysis checkout the
    working directory is in, else the one the package is installed from. When the two
    differ it warns, naming both — the code running is the installed checkout's, which
    may not be the version the active one expects — and carries on with the active one.

    The `.env` resolution is the usual one (real variable, `$DOC_ENV`, nearest `.env`
    above the cwd), then — only if that found nothing — the active checkout's `.env`. A
    real environment variable is never overridden.

    The repo's `notebooks/` goes on `sys.path`, so a helper module kept beside the
    notebooks imports from a notebook in any sub-folder.

    `package_dir` stands in for this package's installed location, for tests. When the
    cwd is in no checkout and `package_dir` is not inside one either (a non-editable
    install) the fallback is skipped, the working directory is left alone and the root
    returned is the one holding the `.env` used, else the cwd. With no document found
    that is no-document mode, and the first save's notice says what was searched.
    """
    installed_from = Path(package_dir) if package_dir else Path(env.__file__).resolve().parent
    installed = env.checkout_root(installed_from)
    root = env.active_checkout(package_dir=installed_from)
    if root is not None and root != installed:
        # Not an error: running another checkout's notebooks from a shared venv is the
        # case this resolution exists for. But the code is not this checkout's own.
        source = installed if installed is not None else installed_from
        warnings.warn(f"notebook_setup(): working in the analysis checkout {root}, but "
                      f"doc_analysis is imported from {source}. Figures, config and "
                      f"DOC_REPO follow {root}; the code running is {source}'s.",
                      stacklevel=2)
    found = env.load_env(fallback=root, skipped_checkout=installed_from if root is None else None)
    _style()

    if root is None:
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
