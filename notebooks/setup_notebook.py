"""Compatibility shim: notebooks written as `from setup_notebook import ROOT` keep working.

The setup lives in the package now — `doc_analysis.notebook_setup()` — because a file
found by walking up from the working directory is not found when the kernel starts at a
workspace root. New notebooks call the function directly; this module only keeps the old
import line meaningful, and adds nothing of its own so the two cannot drift.

    from setup_notebook import ROOT
"""

from doc_analysis import notebook_setup

ROOT = notebook_setup()

# --- your analysis stack ------------------------------------------------------------
# If your data lives behind a package of your own, import it from the notebooks (or a
# helper module in notebooks/, which notebook_setup() puts on sys.path), never from
# doc_analysis itself: the tooling stays reusable precisely because it does not import
# your data layer.
