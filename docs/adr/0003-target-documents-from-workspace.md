---
status: accepted
---

# A workspace analysis takes its target documents from workspace.json; DOC_REPO may agree but never contradict

An analysis repo can now be a **workspace analysis**: a member of a project workspace in its own right, attached to zero or more documents (c-energie/claude-tools#41, which records them in `.claude/workspace.json` as `members[] { dir, kind: "analysis", documents: [...] }`). `doc_analysis` reads that list. It walks up to the nearest `.claude/workspace.json`, finds this repo's member by `dir`, and resolves each `documents` entry against the workspace root. Those are its **target documents**. An empty list is no-document mode (#20).

Every source of a document is now structural except `DOC_REPO`. The sources are:

1. this repo's own `layout.toml` (ADR 0001);
2. the host repo's `layout.toml` (ADR 0002);
3. `workspace.json`.

`DOC_REPO` stays, for a document that lives somewhere these cannot describe: the older sibling layout, or a document elsewhere on disk. The rule between them, which **supersedes the "DOC_REPO wins with a warning" clause of ADRs 0001 and 0002**, is:

- If no structure names a document, `DOC_REPO` is the only source and works as before.
- If a structure names one or more target documents, a `DOC_REPO` that names one of them is accepted silently. A `DOC_REPO` that names anything else **raises**, quoting both paths.

The silent case is the common one. `setup-doc-publish` writes `DOC_REPO` into an analysis repo's `.env` because doc-publish has read nothing else. The disagreeing case is, as ADR 0001 already noted, almost always a `.env` left over from before the nesting. A warning in a notebook's output is easy to miss, and the cost is figures in the wrong document, so it now stops instead.

With several target documents, a single saver call writes to all of them, and `documents=` can narrow that to a subset. Every target is checked before anything is written. Clashes are refused, not renamed. The first analysis to write a figure filename, table tag or value macro into a document is its **owner**, recorded in that document's `figures_manifest.json`. AGENTS.md's rule never to rename a figure rules out per-analysis prefixes.

## Considered Options

- **`DOC_REPO` keeps winning, and narrows the targets to the one it names.** Rejected: a `.env` written for doc-publish would quietly stop every other target document from receiving figures.
- **Drop `DOC_REPO` entirely.** Rejected: a document that is neither nested nor in a workspace would have no way to be found.
- **Ignore `DOC_REPO` silently inside a structure.** Rejected: a disagreeing value is a misconfiguration worth stopping on, not one to hide.
