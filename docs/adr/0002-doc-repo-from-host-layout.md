---
status: accepted
---

# When this repo is the nested repo, DOC_REPO comes from the host repo's layout.toml

ADR 0001 covers the nested layout with this repo as the host repo. The same layout also works the other way up (`writing-hosts-analysis`, issue #11). There, the document repo is the host repo, and this repo is the nested repo in a gitignored subdirectory of it:

```
my-thesis/                ← host repo: the document repo, has layout.toml
└── my-thesis-analysis/   ← nested repo: this one
```

`doc_analysis` derives `DOC_REPO` at runtime as the parent directory when all of these hold:

- the parent of this repo's root has a `layout.toml`;
- that file declares `layout = "writing-hosts-analysis"`;
- its `nested_dir` equals the name of this repo's root directory.

The root is the nearest directory holding `pyproject.toml` above the working directory, so the rule works from the root and from `notebooks/`. A kernel that `notebook_setup()` started elsewhere falls back to the installed checkout. Only the direct parent is looked at.

Precedence extends ADR 0001's, strictest first:

1. a real environment variable;
2. `.env`'s `DOC_REPO`;
3. this repo's own `layout.toml`;
4. the host repo's `layout.toml`.

As in ADR 0001, a `DOC_REPO` that disagrees with the derived location still wins, but it warns. (Superseded by ADR 0003: it now raises.) `init.py` applies the same rule: in a matching position, it asks for no document path and writes no `.env`, unless `--doc-repo` is given.

A `nested_dir` that names another directory gives no fallback. The "DOC_REPO is not set" error names both directory names. Matching on the name is the evidence that the host means this repo, rather than some other analysis repo it nests, or this one under an old name. Without that evidence, writing figures into the parent could put them in the wrong document.

## Considered Options

- **Setup writes an absolute `DOC_REPO` into `.env`.** Rejected for the reason in ADR 0001: `.env` is gitignored, so every fresh clone or restore loses it, and a moved host silently keeps the old path.
- **Accept any `writing-hosts-analysis` parent, whatever its `nested_dir`.** Rejected: it guesses in exactly the case where the guess is most likely wrong, a renamed or second checkout.
- **Walk further up than one parent.** Rejected: a `layout.toml` two levels up describes some other nesting, and walking to it would make any ancestor a candidate document repo.
