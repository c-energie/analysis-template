"""Common notebook setup: consistent working directory, styled plotly, one import line.

Importing this chdir's into the **repository root**. Nothing in this template strictly
requires that — the config and manifest paths are absolute — but it makes every notebook
behave the same regardless of what launched it, which the moment you add a tool resolving
anything relative to the working directory stops being cosmetic. JupyterLab and VS Code
start a kernel in the notebook's own directory; PyCharm starts it in the project root.

    from setup_notebook import ROOT
"""

import os
from pathlib import Path

import plotly.io as pio

# Registers the shared plotly template as the default for every notebook, on import.
import PACKAGE_NAME  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]

os.chdir(ROOT)

# "notebook" renders in both JupyterLab and VS Code; "jupyterlab" is fine if you only
# ever use the former.
pio.renderers.default = "notebook"

# --- your analysis stack ------------------------------------------------------------
# If your data lives behind a package of your own, import it here so every notebook gets
# it from one place and the seam is obvious:
#
#     from your_analysis_package import Cohort   # noqa: E402
#
# Keep it out of PACKAGE_NAME itself: the tooling stays reusable precisely because it
# does not import your data layer.
