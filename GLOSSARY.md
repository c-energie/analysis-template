# Analysis repo

The Python side of a document project: notebooks and code that generate figures and tables into a separate LaTeX document repo.

## Language

### Repos and layouts

**Document repo**:
The LaTeX repo the figures and tables are written into.
_Avoid_: writing repo (in prose about this package), LaTeX repo, thesis repo

**Target document**:
A document repo an analysis repo writes into: the host repo of a nested analysis, one of the documents a workspace analysis is attached to, or the one `DOC_REPO` names.
_Avoid_: destination, output document

**No-document mode**:
An analysis repo with no target document, which keeps its figures, tables and values in its own `outputs/` until it gets one; entered only when nothing names a document, so a document named wrongly is still an error.
_Avoid_: standalone mode, local mode

**Owner**:
The analysis repo that first wrote a given figure, table or value into a document; no other analysis may write that name there.
_Avoid_: author, source

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

**Nested analysis**:
An analysis repo that lives inside one document repo and feeds only that document.
_Avoid_: embedded analysis, document analysis

**Workspace analysis**:
An analysis repo that is a member of a project workspace in its own right, not inside any document repo, and feeds zero or more documents.
_Avoid_: standalone analysis, root analysis, shared analysis
