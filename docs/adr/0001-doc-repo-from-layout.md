---
status: accepted
---

# In a nested layout, DOC_REPO comes from layout.toml

When this repo hosts its document repo as a nested repo (layout `analysis-hosts-writing`, issue #7), `doc_analysis` derives `DOC_REPO` at runtime as `<repo root>/<nested_dir>` from the committed `layout.toml`, instead of setup writing an absolute path into `.env`. The location is a fact about the project, not about the machine: every clone gets a working `DOC_REPO` with no per-machine step, and a relative path in `.env` is not an option because it would resolve against the notebook's working directory.

Precedence stays strictest-first: a real environment variable, then `.env`'s `DOC_REPO`, then `layout.toml`. A `.env` value that disagrees with the layout warns, since it is almost always stale.

## Considered Options

- **Setup writes an absolute `DOC_REPO` into `.env`.** Rejected: every fresh clone would need setup re-run before anything worked, and a moved checkout would silently keep pointing at the old path.
