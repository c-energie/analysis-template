# Analysis repo

The Python side of a document project: notebooks and code that generate figures and tables into a separate LaTeX document repo.

## Language

### Repos and layouts

**Document repo**:
The LaTeX repo the figures and tables are written into, located by `DOC_REPO`.
_Avoid_: writing repo (in prose about this package), LaTeX repo, thesis repo

**Layout**:
How the analysis repo and the document repo sit relative to each other on disk and in git.
_Avoid_: setup, mode, structure

**Nested layout**:
A layout where one repo is the host and the other is a nested repo inside it: `analysis-hosts-writing` here, `writing-hosts-analysis` from the document side.
_Avoid_: embedded layout, monorepo

**Host repo**:
In a nested layout, the outer repo you open and work from; it gitignores the nested repo.
_Avoid_: parent repo, outer repo

**Nested repo**:
In a nested layout, a separate repo with its own remote that lives in a gitignored subdirectory of the host repo.
_Avoid_: submodule, child repo, inner repo
