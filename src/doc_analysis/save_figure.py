"""Save document figures: one call writes the LaTeX PNG and, for plotly, a wiki HTML.

Which backend you use is read off the figure object you pass — there is no setting to
keep in step with it, because the object already says which it is.

A **plotly** figure (preferred) produces BOTH outputs from the same object, so the PDF
and the wiki can never drift:

- a static PNG into the LaTeX repo's section Figures/ directory — filename and
  location are never changed by this module, because the LaTeX resolves bare
  filenames via \\graphicspath and the publishing agent indexes them;
- an interactive HTML (same stem) into a local figures directory.

A **matplotlib** figure writes the PNG only. That is a supported choice, not an
unfinished migration: you give up the interactive export and nothing else. Downstream
handles it — the publishing engine's figure emitter falls through to the static PNG
whenever an entry has no interactive export.

Either way the figure is recorded in a figures_manifest.json — the target document's own,
at its root, shared by every analysis feeding it (see manifest.py); with no document, the
html directory's — with a `backend` field and `interactive: null` for the static-only
case. The manifest is the
record of everything this pipeline writes, which is what `check-figure-parity` reads to
guard figure sizes and to report which figures the document actually renders — so a
matplotlib figure is covered by both checks exactly as a plotly one is.

The LaTeX repos are inputs: the **target documents** (`target_documents`), named by the
structure — this repo's committed layout.toml, its host's, or the workspace's
`.claude/workspace.json`, which can attach one analysis to several documents — else by
the DOC_REPO environment variable (the same convention the publishing agent uses), which
may agree with the structure but never contradict it (ADR 0003). A save writes into every
target unless `documents=` narrows it. This package never hardcodes a user path. When
none of those names a document — an analysis repo standing alone, before there is a
write-up — that is no-document mode: the PNG goes to the checkout's own
`outputs/figures/` and nothing touches a .tex file, so the same notebook lands its
figures in the document once one is configured.

Publishing note: anything entering this pipeline has already been approved for
publication (standing policy, 2026-08-05), so the gate is upstream rather than here.
The HTML directory is nonetheless gitignored until the publishing route is built —
see .gitignore.
"""

import os
import re
import shutil
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

from doc_analysis.env import LAST_SEARCH, analysis_root, describe_search
from doc_analysis.layout import find_host_layout, find_layout
from doc_analysis.manifest import (
    FIGURE_PREFIX,
    MANIFEST_NAME,
    migrate_entries,
    refuse_clash,
    relative_to_manifest,
    update_manifest,
)
from doc_analysis.workspace import find_workspace_analysis

DOC_REPO_ENV = "DOC_REPO"
HTML_DIR_ENV = "FIGURES_HTML_DIR"

FIGURES_DIRNAME = "Figures"
SECTIONS_DIRNAME = "Sections"
#: What the document's section tree was called before the rename. Still accepted, so a
#: document repo laid out before it keeps working; Sections/ wins where both exist.
LEGACY_SECTIONS_DIRNAME = "Chapters"

HTML_DIRNAME = "figures_html"


def default_html_dir():
    """The active checkout's `figures_html/` (gitignored; see module docstring).

    Resolved per call against the active checkout (`env.analysis_root`), not once from
    `__file__`: with two checkouts in one venv that sent both repos' manifests and
    interactive exports into the imported package's checkout.
    """
    return analysis_root() / HTML_DIRNAME


def __getattr__(name):
    # The pre-#24 constant, still importable for code that reads it; now resolved on access.
    if name == "DEFAULT_HTML_DIR":
        return default_html_dir()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Artifact sub-directories (figures/tables) are save targets, not sections to descend into.
ARTIFACT_DIRNAMES = (FIGURES_DIRNAME,)

# The .tex libraries save_table and save_value write into a section. Generated, so never a
# target for a commented reference: counting them as candidates would make a one-file
# section look ambiguous as soon as its first table or value was saved, and every later
# save with tex=None would raise.
GENERATED_TEX_NAMES = ("tables.tex", "values.tex")


class TargetDocument(NamedTuple):
    """One document repo a save writes into."""
    #: How `documents=` names it: the `workspace.json` entry as written, else the
    #: document's directory name.
    name: str
    path: Path
    #: What named it, for messages: a `layout.toml`, the `workspace.json`, or $DOC_REPO.
    source: str


class Targets(NamedTuple):
    """Every target document of this analysis, and the name it owns entries under."""
    documents: tuple
    #: The owner recorded in each document's manifest: a workspace analysis's member
    #: `dir`, else (a nested analysis, or one found through $DOC_REPO) its directory name.
    analysis: str

    @property
    def names(self):
        return [document.name for document in self.documents]


def target_documents():
    """This analysis's target documents, in order, and its owner name (ADR 0003).

    The structure names them, strictest first: this repo's own `layout.toml`
    (`analysis-hosts-writing`, ADR 0001); the host repo's, naming this directory
    (`writing-hosts-analysis`, ADR 0002); then this repo's analysis member in the nearest
    `.claude/workspace.json` and its `documents` list, each entry resolved against the
    workspace root. A nested analysis resolves from its layout alone, so not being listed
    in `workspace.json` is normal.

    $DOC_REPO — a real environment variable, else `.env`'s — is checked against the
    structure, never preferred to it: naming one of the targets is accepted silently, and
    anything else raises, quoting both. It used to win with a warning, which is how a
    `.env` left from before the nesting sent figures into the wrong document unnoticed.
    Only where no structure names a document is it the source, as it always was.

    An empty list of documents is no-document mode (see `local_output_dir`): nothing
    names a document, or the workspace attaches this analysis to none. Anything that names
    one and is wrong — a $DOC_REPO without Sections/, a nested dir not cloned yet, a host
    layout naming another directory, a `workspace.json` entry that is not a document —
    raises with an actionable message rather than guessing: writing a figure into the
    wrong tree silently breaks the document build, and falling back to local output would
    hide the mistake just as well.
    """
    value = os.environ.get(DOC_REPO_ENV)
    fallback = LAST_SEARCH["fallback"]
    hosted = find_layout(fallback=fallback)
    # Only looked for when this repo hosts nothing: its own layout.toml is nearer, and
    # the stricter-first precedence of ADR 0001 extends past it rather than around it.
    host = find_host_layout(fallback=fallback) if hosted is None else None
    member = None
    if hosted is not None:
        if not hosted.nested_path.is_dir():
            # The normal state of a fresh clone: the nested repo is gitignored, so it
            # does not come with the host and has to be cloned in once. Raised whatever
            # $DOC_REPO says: it cannot be the document while its directory is absent.
            raise RuntimeError(
                f"{hosted.file} puts the document repo at {hosted.nested_path}, which "
                f"does not exist. Clone it into place with\n"
                f"    python setup_nested.py\n"
                f"run in {hosted.root}."
            )
        structure = [TargetDocument(hosted.nested_dir, hosted.nested_path, str(hosted.file))]
        analysis = hosted.root.name
    elif host is not None and host.matches:
        structure = [TargetDocument(host.layout.root.name, host.layout.root,
                                    str(host.layout.file))]
        analysis = host.root.name
    else:
        member = find_workspace_analysis(fallback=fallback)
        structure = (None if member is None else
                     [TargetDocument(entry, path, str(member.file))
                      for entry, path in member.documents])
        analysis = member.member_dir if member is not None else analysis_root().name

    if structure is not None:
        for document in structure:
            if section_root_name(document.path) is None:
                raise NotADirectoryError(
                    f"{document.path} (from {document.source}) does not look like the "
                    f"document repo (no {SECTIONS_DIRNAME}/ directory).")
        if value:
            _refuse_disagreeing_doc_repo(value, structure, member)
        return Targets(tuple(structure), analysis)

    if value:
        repo = Path(value)
        if section_root_name(repo) is None:
            raise NotADirectoryError(
                f"{DOC_REPO_ENV}={repo} does not look like the document repo "
                f"(no {SECTIONS_DIRNAME}/ directory)."
            )
        return Targets((TargetDocument(repo.resolve().name, repo, f"${DOC_REPO_ENV}"),),
                       analysis)
    if host is None:
        # Nothing names a document: no-document mode, and the savers write to
        # local_output_dir() instead. Never a guess at a document — only the absence of
        # every source gets here; each misconfiguration above and below still raises.
        return Targets((), analysis)

    # Saying where it looked is what tells a notebook started from the wrong directory
    # apart from a .env that is genuinely missing the line.
    looked = "".join(f"\n  - {line}" for line in describe_search())
    # A renamed nested checkout: the host's layout.toml names another directory, so the
    # parent is not known to be this repo's document. Both names, because the fix is
    # renaming one of them to the other. Not no-document mode: the host says a document
    # is meant to be here, and saving locally would hide the rename.
    looked += (f"\n  - {host.layout.file} declares {host.layout.layout}, but its "
               f"nested_dir = {host.layout.nested_dir!r} is not this repo's "
               f"directory, {host.root.name!r}; rename one to match the other")
    raise RuntimeError(
        f"{DOC_REPO_ENV} is not set. Add it to this repo's .env (copy .env.example),\n"
        f"    {DOC_REPO_ENV}=/path/to/my-document\n"
        f"pointing at the LaTeX document repo root — the directory containing "
        f"{SECTIONS_DIRNAME}/."
        + (f"\nWhere it looked:{looked}" if looked else "")
    )


def _refuse_disagreeing_doc_repo(value, structure, member):
    """Raise unless $DOC_REPO names one of the documents the structure names.

    A $DOC_REPO naming a target is the common, harmless case — setup-doc-publish writes
    one into `.env` because doc-publish reads nothing else — so it is silent. Anything
    else is almost always a `.env` from before the nesting or the workspace, and a
    warning in a notebook's output is easy to miss while the figures land elsewhere.
    """
    repo = Path(value).resolve()
    if any(repo == document.path.resolve() for document in structure):
        return
    if not structure:
        # The workspace attaches this analysis to nothing, deliberately: a $DOC_REPO
        # still naming a document is what detach-analysis leaves behind in .env, and
        # honouring it would keep feeding the document that was just detached.
        raise RuntimeError(
            f"{DOC_REPO_ENV}={value} names a document, but {member.file} attaches this "
            f"analysis ({member.member_dir!r}) to none (documents = []). Remove "
            f"{DOC_REPO_ENV} from this repo's .env, or attach the document "
            f"(attach-analysis).")
    named = ", ".join(str(document.path) for document in structure)
    raise RuntimeError(
        f"{DOC_REPO_ENV}={value} disagrees with {structure[0].source}, which puts this "
        f"analysis's target document{'s' if len(structure) > 1 else ''} at {named}. "
        f"Remove {DOC_REPO_ENV} from this repo's .env (the structure locates the "
        f"document without it), or point it at {'one of those' if len(structure) > 1 else 'that'}.")


def document_repos():
    """The target documents' roots, in order; [] in no-document mode."""
    return [document.path for document in target_documents().documents]


def document_repo():
    """Root of the one target document, or None in no-document mode.

    The single-document view of `target_documents`, for callers that can only act on
    one: the picker, `sections_dir()`, `notebook-skeleton`'s section check. A workspace
    analysis attached to several documents raises, naming them, rather than picking one —
    which of them a caller meant is not something to guess.
    """
    targets = target_documents()
    if len(targets.documents) > 1:
        raise RuntimeError(
            f"This analysis has {len(targets.documents)} target documents "
            f"({', '.join(targets.names)}), and document_repo() returns one. Pass an "
            f"explicit section path, or use target_documents() / document_repos().")
    return targets.documents[0].path if targets.documents else None


def section_root_name(repo):
    """"Sections", the legacy "Chapters", or None — whichever *repo* actually has.

    Sections/ wins where both are present, so a half-finished rename resolves to the new
    tree rather than to whichever name happens to be checked first.
    """
    for name in (SECTIONS_DIRNAME, LEGACY_SECTIONS_DIRNAME):
        if (Path(repo) / name).is_dir():
            return name
    return None


def sections_dir():
    """The Sections/ directory of the LaTeX document repo.

    Falls back to a legacy Chapters/ tree when that is the layout the document repo has.
    Raises in no-document mode: there is no section tree, and a path made up relative to
    the cwd would be a guess the savers' local output exists to avoid.
    """
    repo = document_repo()
    if repo is None:
        raise RuntimeError(f"No document is configured, so there is no {SECTIONS_DIRNAME}/ "
                           f"directory. {_HOW_TO_CONFIGURE}")
    return _sections_of(repo)


def _sections_of(repo):
    return repo / (section_root_name(repo) or SECTIONS_DIRNAME)


#: How to leave no-document mode, for every message that mentions it.
_HOW_TO_CONFIGURE = (f"To save into a document, set {DOC_REPO_ENV} in this repo's .env "
                     f"(copy .env.example), nest this repo in a document, or attach it "
                     f"to one in the workspace (attach-analysis).")

#: Where a save goes in no-document mode, under the active checkout.
OUTPUTS_DIRNAME = "outputs"
LOCAL_FIGURES_DIRNAME = "figures"


def local_output_dir():
    """`<active checkout>/outputs`: where saves go when no document is configured.

    The one place that path is spelled, shared by the three savers and by
    `check-figure-parity`, so a snapshot always looks where the savers wrote. Resolved
    per call against the active checkout, like `default_html_dir`.
    """
    return analysis_root() / OUTPUTS_DIRNAME


# Once per process, not per save: a notebook saving thirty figures should say where they
# went, not say it thirty times until the line is scrolled past unread.
_NO_DOCUMENT_NOTICE = {"shown": False}


def _announce_no_document():
    if _NO_DOCUMENT_NOTICE["shown"]:
        return
    _NO_DOCUMENT_NOTICE["shown"] = True
    # Where it looked, because a notebook on the wrong interpreter or started outside its
    # checkout lands here too, and the search record is what tells the two apart.
    looked = "; ".join(describe_search())
    print(f"No document configured: saving to {local_output_dir()} instead "
          f"(figures in {LOCAL_FIGURES_DIRNAME}/, tables and values under the section). "
          f"{_HOW_TO_CONFIGURE}" + (f" Searched: {looked}." if looked else ""))


def _local_section_dir(section):
    """`outputs/<section>` for a relative section name, created; no-document mode only."""
    # In a document the section must already exist, which keeps `..` inside Sections/ in
    # practice; here the directory is created, so `..` would write outside outputs/.
    if ".." in Path(section).parts:
        raise ValueError(f"section={str(section)!r} must stay inside {OUTPUTS_DIRNAME}/ "
                         f"in no-document mode; drop the '..'.")
    section_dir = local_output_dir() / section
    section_dir.mkdir(parents=True, exist_ok=True)
    return section_dir


class SaveTarget(NamedTuple):
    """Where one save writes: a section directory, and the document it belongs to.

    `document` is None for an explicit section — an absolute `section=`, a
    `sections_root=`, the picker — which never consulted the target documents; its
    manifest stays in the html directory, as it always was, and has no owner to check.
    """
    section_dir: Path
    document: "TargetDocument | None"

    @property
    def manifest_path(self):
        return None if self.document is None else self.document.path / MANIFEST_NAME


class SavePlan(NamedTuple):
    """Every target of one saver call, checked before anything is written."""
    targets: tuple
    #: The owner name written into each document's manifest; None for explicit sections.
    analysis: "str | None"


def _choose(targets, documents):
    """The subset of `targets.documents` that `documents=` names, in the targets' order.

    `documents=` can only narrow: a name that is not a target raises rather than adding a
    document, because the list of targets is the workspace's to say, not a notebook's.
    """
    if documents is None:
        return list(targets.documents)
    wanted = [documents] if isinstance(documents, (str, os.PathLike)) else list(documents)
    if not wanted:
        raise ValueError("documents=[] chooses no target document, so nothing would be "
                         "saved; leave documents= out to write to every target.")
    chosen = set()
    for want in wanted:
        match = next((document for document in targets.documents
                      if want == document.name
                      or Path(want).resolve() == document.path.resolve()), None)
        if match is None:
            listed = ", ".join(targets.names) or "none: no document is configured"
            raise ValueError(f"documents= names {str(want)!r}, which is not a target "
                             f"document of this analysis (targets: {listed}). "
                             f"documents= can only narrow the targets, never add one.")
        chosen.add(match)
    return [document for document in targets.documents if document in chosen]


def _plan_save(section, sections_root=None, documents=None):
    """Every section directory a save writes into, or None in no-document mode.

    The target documents apply only where the document would have been consulted — a
    relative section with no sections_root. Each chosen target must already hold the
    section, checked for all of them before the caller writes anything: a save that
    landed in one document and raised for the next would leave the two disagreeing, and
    a section directory created here would be a guess at the document's structure.

    An absolute section or an explicit root is used exactly as before, document or not;
    and section=None still reaches the picker, which raises without a document rather
    than prompting over nothing. On None the caller writes under `local_output_dir()`;
    the notice has already been printed.
    """
    if section is None or sections_root is not None or Path(section).is_absolute():
        if documents is not None:
            raise TypeError("documents= chooses among the target documents, so it needs "
                            "a section relative to their Sections/; this section= or "
                            "sections_root= already names one directory.")
        return SavePlan((SaveTarget(_resolve_section_dir(section, sections_root), None),),
                        None)

    targets = target_documents()
    if not targets.documents:
        if documents is not None:
            _choose(targets, documents)  # raises: there is nothing to choose from
        _announce_no_document()
        return None
    chosen = _choose(targets, documents)
    planned = [SaveTarget(_sections_of(document.path) / section, document)
               for document in chosen]
    missing = [target for target in planned if not target.section_dir.is_dir()]
    if missing:
        where = "; ".join(f"{target.section_dir} (in {target.document.name})"
                          for target in missing)
        raise NotADirectoryError(
            f"Section directory not found: {where}. Nothing was saved to any target "
            f"document. Create the section in "
            f"{'each document' if len(missing) > 1 else 'the document'} first, or narrow "
            f"the save with documents=[...].")
    return SavePlan(tuple(planned), targets.analysis)


def _check_owners(plan, what, release, keys=(), stem=None):
    """Refuse the save when another analysis owns the name in any chosen document.

    All targets first, then the caller writes: a clash in the second document must not
    leave the first one already holding the new version.
    """
    for target in plan.targets:
        if target.document is not None:
            refuse_clash(target.manifest_path, plan.analysis, what,
                         release(target), keys=keys, stem=stem)


def _single_or_list(paths):
    """A saver's return value: the one path as before, a list when it wrote to several."""
    return paths[0] if len(paths) == 1 else paths


def chapters_dir():
    """Deprecated alias for sections_dir(). Chapters/ was renamed to Sections/."""
    warnings.warn("chapters_dir() is deprecated; use sections_dir().",
                  DeprecationWarning, stacklevel=2)
    return sections_dir()


def select_section_dir(sections_root=None, skip_dirnames=ARTIFACT_DIRNAMES):
    """Interactively walk the document's section tree and return a leaf sub-directory.

    Prompts with a numbered menu at each level, hiding the artifact directories (which
    hold outputs rather than sections to descend into). Descending continues until a
    leaf directory is reached, or until "Save here" is chosen. Returns a Path.

    Prefer passing section="Results/ptg_application" to save_document_figure — a
    notebook that prompts cannot be run unattended.
    """
    current = Path(sections_root) if sections_root is not None else sections_dir()
    if not current.is_dir():
        raise NotADirectoryError(f"Sections directory not found: {current}")

    while True:
        sub_dir_names = sorted(
            child.name for child in current.iterdir()
            if child.is_dir() and child.name not in skip_dirnames
        )
        if not sub_dir_names:
            return current  # leaf directory: nowhere left to descend

        print(f"\nCurrent directory: {current}")
        options = sub_dir_names + [f"Save here ({current.name})"]
        for i, option in enumerate(options, start=1):
            print(f"  {i}. {option}")
        choice = input(f"Select 1-{len(options)}: ").strip()
        if not choice.isdigit() or not 1 <= int(choice) <= len(options):
            print("Not a valid choice.")
            continue
        index = int(choice) - 1
        if index == len(sub_dir_names):
            return current  # user chose to stop at this level
        current = current / sub_dir_names[index]


def select_chapter_dir(chapters_root=None, skip_dirnames=ARTIFACT_DIRNAMES):
    """Deprecated alias for select_section_dir()."""
    warnings.warn("select_chapter_dir() is deprecated; use select_section_dir().",
                  DeprecationWarning, stacklevel=2)
    return select_section_dir(chapters_root, skip_dirnames)


def _comment_block(block):
    """Prefix every line of a LaTeX block with "% " so it sits inert in the source."""
    return "\n".join(f"% {line}" if line else "%" for line in block.splitlines())


def _choose_tex(section_dir, exclude=(), tex_name=None):
    """The name of the .tex file in section_dir a reference goes to; None if it has none.

    tex_name picks it explicitly; otherwise a single candidate is used and several raise.
    Separate from _append_commented_block so a save into several documents can ask every
    target before writing to any (see _check_tex_targets): raising for the second after
    the first was written would leave the two documents disagreeing.
    """
    exclude = set(exclude) | set(GENERATED_TEX_NAMES)
    tex_names = sorted(p.name for p in Path(section_dir).glob("*.tex")
                       if p.name not in exclude)
    if not tex_names:
        return None
    if tex_name is not None:
        if tex_name not in tex_names:
            raise FileNotFoundError(
                f"tex file {tex_name!r} not found in {section_dir} (has: {tex_names})"
            )
        return tex_name
    if len(tex_names) == 1:
        return tex_names[0]
    # Ambiguous target. Raise rather than prompt: an input() here hangs an unattended
    # notebook run, and silently picking one risks dropping the block in the wrong
    # section file. The message says exactly how to resolve it.
    raise RuntimeError(
        f"{Path(section_dir).name} has several .tex files ({tex_names}); "
        f"pass tex='<one of them>' to say where the reference should go "
        f"(or tex=False to skip appending one)."
    )


def _check_tex_targets(plan, tex, referenced, exclude=()):
    """Raise before any write when a target's section has no clear .tex for the reference.

    `referenced(section_dir)` says whether the section already references the artefact,
    in which case nothing will be appended there and its .tex files do not matter.
    """
    if tex is False:
        return
    for target in plan.targets:
        if not referenced(target.section_dir):
            _choose_tex(target.section_dir, exclude,
                        None if tex in (None, True) else tex)


def _append_commented_block(section_dir, block, exclude=(), tex_name=None):
    """Append a commented-out LaTeX block to a .tex file in section_dir.

    Looks for .tex files directly inside section_dir, ignoring the generated libraries
    (GENERATED_TEX_NAMES) and any whose name is in exclude. tex_name picks the target file
    explicitly; otherwise a single candidate is used automatically and several raise,
    because prompting would hang an unattended notebook run.

    The block is commented and goes where uncommenting it renders it: when the file has a
    live \\end{document} (a \\subfile section), immediately before the last one, with a
    blank line on either side; otherwise it is appended after a blank line. Commented-out
    \\end{document} lines are ignored. Returns the .tex Path written, or None when there is
    no eligible .tex file.
    """
    section_dir = Path(section_dir)
    tex_name = _choose_tex(section_dir, exclude, tex_name)
    if tex_name is None:
        print(f"No .tex file found in {section_dir}; skipping reference.")
        return None

    tex_path = section_dir / tex_name
    commented = _comment_block(block)

    # Read without newline translation, so a rewrite below can leave every byte outside
    # the inserted block exactly as it was.
    existing = tex_path.read_bytes().decode("utf-8")
    # Follow the file's own line endings rather than the platform's, in both branches: a
    # text-mode write turns \n into \r\n on Windows, and an LF section came back with a
    # CRLF block in it -- mixed endings, and noisy git and Overleaf diffs (issue #17).
    newline = "\r\n" if "\r\n" in existing else "\n"
    commented = commented.replace("\n", newline)
    end = _end_document_offset(existing)
    if end is None:
        # Decide the separator on normalised endings: a CRLF file ending in a blank line
        # ends in "\r\n\r\n", which endswith("\n\n") would miss.
        tail = existing.replace("\r\n", "\n")
        blank_lines = 0 if tail.endswith("\n\n") else 1 if tail.endswith("\n") else 2
        # Append bytes, so nothing already in the file is re-encoded or translated.
        with tex_path.open("ab") as tex_file:
            tex_file.write(f"{newline * blank_lines}{commented}{newline}".encode("utf-8"))
    else:
        # A subfile ends in \end{document}, and LaTeX ignores everything after it: a block
        # appended there is uncommented by the author and then never renders, with no
        # error (issue #4). Insert it before the line instead, rewriting the whole file.
        body = existing[:end].rstrip("\r\n")
        separator = newline * 2 if body else ""
        tex_path.write_bytes(
            f"{body}{separator}{commented}{newline * 2}{existing[end:]}".encode("utf-8"))

    print(f"Added commented reference to: {tex_path}")
    return tex_path


# A live \end{document}: at the start of a line, after nothing but indentation. A line whose
# first non-blank character is % -- including one inside an already-appended commented
# block -- does not end the document, so it must not attract the insertion.
_END_DOCUMENT_RE = re.compile(r"^[ \t]*\\end\{document\}", re.MULTILINE)


def _end_document_offset(text):
    """Offset of the line holding the last live \\end{document}, or None if there is none."""
    matches = list(_END_DOCUMENT_RE.finditer(text))
    return matches[-1].start() if matches else None


def _build_figure_block(figure_name, caption, label):
    """Return the (uncommented) LaTeX figure environment referencing figure_name."""
    return (
        "\\begin{figure}[H]\n"
        "    \\centering\n"
        f"    \\includegraphics[width=\\width]{{{figure_name}}}\n"
        f"    \\caption{{{caption}}}\n"
        f"    \\label{{Fig: {label}}}\n"
        "\\end{figure}"
    )


def _reference_state(text, stem, label):
    """"live", "commented" or None for this figure in one LaTeX source.

    Commented-out blocks count as references: the migration workflow leaves the
    \\begin{figure} block commented until the prose is written, and that block is exactly
    what must not be duplicated. A live reference outranks a commented one.
    """
    include = re.compile(
        r"\\includegraphics(?:\[[^\]]*\])?\{\s*" + re.escape(stem) + r"(?:\.\w+)?\s*\}")
    labelled = re.compile(r"\\label\{\s*Fig:\s*" + re.escape(label) + r"\s*\}")
    state = None
    for raw_line in text.splitlines():
        stripped = raw_line.lstrip()
        line = stripped.lstrip("%").strip()
        if include.search(line) or labelled.search(line):
            if not stripped.startswith("%"):
                return "live"
            state = "commented"
    return state


def search_root(section_dir):
    """Widest sensible scope for a reference scan: the Sections tree above section_dir.

    Figure filenames are unique across the document by rule (the LaTeX resolves them by
    bare name via \\graphicspath), so a block for a figure may legitimately sit in another
    section's .tex file and must still count. Falls back to section_dir when there is no
    Sections ancestor, which keeps the helpers usable on a standalone directory. A legacy
    Chapters/ ancestor counts too, so the scan still widens in a pre-rename document repo.
    """
    section_dir = Path(section_dir)
    roots = (SECTIONS_DIRNAME, LEGACY_SECTIONS_DIRNAME)
    for parent in (section_dir, *section_dir.parents):
        if parent.name in roots:
            return parent
    return section_dir


def figure_reference_state(section_dir, figure_name, label=None):
    """(state, tex_path) for figure_name: state is "live", "commented" or None.

    Scans every .tex under the Sections tree containing section_dir (see search_root),
    preferring a live reference over a commented one.
    """
    stem = Path(figure_name).stem
    label = label if label is not None else stem
    found = (None, None)
    for tex_path in sorted(search_root(section_dir).rglob("*.tex")):
        state = _reference_state(tex_path.read_text(encoding="utf-8", errors="replace"),
                                 stem, label)
        if state == "live":
            return state, tex_path
        if state == "commented" and found[0] is None:
            found = (state, tex_path)
    return found


def find_figure_reference(section_dir, figure_name, label=None):
    """The .tex file already referencing figure_name (commented or live), or None."""
    return figure_reference_state(section_dir, figure_name, label)[1]


def add_commented_figure_to_tex(figure_name, section_dir, caption=None, label=None,
                                tex=True):
    """Append a commented-out \\begin{figure} block for figure_name, if it has none yet.

    The append is gated on the figure not already being referenced anywhere in the
    Sections tree (see find_figure_reference) — commented blocks count, and so does a
    block that lives in another section's .tex — so re-saving a figure never accumulates
    duplicate blocks and tex can safely default to True. caption defaults to a TODO
    placeholder and label to the figure name stem, producing a \\label{Fig: <stem>}.

    tex=True (or None) appends only when the figure is unreferenced, choosing the
    section's sole .tex file and raising if there are several; tex='<name>.tex' names the
    target explicitly; tex=False skips the append entirely. Returns the .tex Path
    written, or None when nothing was appended.
    """
    if tex is False:
        return None
    caption = caption if caption is not None else "TODO: caption"
    label = label if label is not None else Path(figure_name).stem

    already = find_figure_reference(section_dir, figure_name, label)
    if already is not None:
        print(f"Figure '{figure_name}' is already referenced in {already.name}; "
              f"no block appended.")
        return None

    block = _build_figure_block(figure_name, caption, label)
    return _append_commented_block(section_dir, block,
                                   tex_name=None if tex is True else tex)


def _is_plotly_figure(fig):
    """True for a Plotly figure (which is saved via write_image, not savefig)."""
    return hasattr(fig, "write_image") and not hasattr(fig, "savefig")


def _resolve_section_dir(section, sections_root=None):
    """Resolve the section directory, interactively unless section is given.

    section may be an absolute path or a path relative to the Sections/ root (e.g.
    "Results/ptg_application"); passing it skips the interactive picker so a notebook
    can run top to bottom unattended.
    """
    if section is None:
        return select_section_dir(sections_root)
    section_dir = Path(section)
    if not section_dir.is_absolute():
        root = Path(sections_root) if sections_root is not None else sections_dir()
        section_dir = root / section_dir
    if not section_dir.is_dir():
        raise NotADirectoryError(f"Section directory not found: {section_dir}")
    return section_dir


def _one_of(new_name, new_value, old_name, old_value):
    """Resolve a renamed keyword argument, warning when the old spelling is used.

    Passing both is an error rather than a precedence rule: the two spellings naming
    different directories is a mistake worth stopping on, not one to resolve silently.
    """
    if old_value is None:
        return new_value
    if new_value is not None:
        raise TypeError(f"pass either {new_name}= or {old_name}=, not both")
    warnings.warn(f"{old_name}= is deprecated; use {new_name}=.",
                  DeprecationWarning, stacklevel=3)
    return old_value


def _resolve_html_dir(html_dir):
    """The figure output directory: argument, else env var, else default.

    Named for the interactive exports because that is what it mostly holds, but it also
    holds figures_manifest.json — so a matplotlib-only project gets this directory too,
    containing the manifest and nothing else.
    """
    html_dir = Path(html_dir or os.environ.get(HTML_DIR_ENV) or default_html_dir())
    html_dir.mkdir(parents=True, exist_ok=True)
    return html_dir


def _write_static_png(fig, save_path, **write_image_kwargs):
    """Static plotly export via kaleido, with a clear failure when it is missing."""
    try:
        import kaleido  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "Static PNG export of plotly figures needs the 'kaleido' package, which "
            "the plotly extra installs:\n"
            "    uv sync --extra plotly    (or: uv add kaleido / pip install kaleido)"
        ) from exc
    before = _file_state(save_path)
    try:
        fig.write_image(str(save_path), **write_image_kwargs)
    except RuntimeError as exc:
        if not _raised_by_choreographer(exc):
            raise
        # kaleido 1.x renders through choreographer, whose Chrome teardown races on
        # Windows: "Couldn't close or kill browser subprocess" is raised from
        # Browser._close *after* the PNG is on disk (issue #22). Failing the save there
        # stops an unattended nbconvert run over a figure that was written. But a PNG
        # merely existing proves nothing - a committed figure from the last run is
        # there too - so accept only one this call wrote, completely; else retry once.
        if _png_written_since(save_path, before):
            warnings.warn(
                f"Ignored a browser-close failure after writing '{save_path.name}' "
                f"(kaleido/choreographer: {exc}). The PNG is complete.",
                stacklevel=3,
            )
            return
        fig.write_image(str(save_path), **write_image_kwargs)


def _file_state(path):
    """(mtime_ns, size) of path, or None if absent - to tell a fresh write from a stale file."""
    try:
        stat = Path(path).stat()
    except FileNotFoundError:
        return None
    return stat.st_mtime_ns, stat.st_size


def _raised_by_choreographer(exc):
    """True if the traceback passes through choreographer, kaleido's browser driver.

    The close failure is a bare RuntimeError, so its type says nothing; where it came
    from does. Any other RuntimeError from write_image is a real failure and propagates.
    """
    tb = exc.__traceback__
    while tb is not None:
        if "choreographer" in Path(tb.tb_frame.f_code.co_filename).parts:
            return True
        tb = tb.tb_next
    return False


def _png_written_since(path, before):
    """True if path now holds a complete PNG that differs from the `before` state.

    Complete means the signature at the start and the IEND chunk at the end, so a file
    truncated by a browser killed mid-write is not mistaken for a finished figure.
    """
    after = _file_state(path)
    if after is None or after == before or after[1] == 0:
        return False
    data = Path(path).read_bytes()
    return data.startswith(b"\x89PNG\r\n\x1a\n") and b"IEND" in data[-12:]


def _matplotlib_figure():
    """The current matplotlib figure, or an ImportError naming the extra."""
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ImportError(
            "save_document_figure() without a `fig` argument saves the current "
            "matplotlib figure, and matplotlib is not installed:\n"
            "    uv sync --extra matplotlib    (or pass fig=<your figure>)"
        ) from exc
    return plt.gcf()


def _default_hover_warning(fig, stem):
    """Warn when every trace still has plotly's default hover text.

    The interactive export is the reason for the dual output, and a figure whose hover
    text is plotly's default gives a reader nothing the PNG did not already give them.
    """
    if not any(getattr(trace, "hovertemplate", None) for trace in fig.data):
        warnings.warn(
            f"Figure '{stem}' has no hovertemplate on any trace - the interactive "
            "export will show plotly's default hover text. Set an explicit "
            "hovertemplate naming the fields that identify a point, and pass them as "
            "hover_fields=[...].",
            stacklevel=3,
        )


def _detect_notebook():
    """Best-effort name of the calling notebook, for the manifest (None if unknown)."""
    for env_var in ("JPY_SESSION_NAME", "__vsc_ipynb_file__"):
        value = os.environ.get(env_var)
        if value and value.endswith(".ipynb"):
            return Path(value).name
    return None


def _update_manifest(html_dir, key, entry):
    """Create/refresh one entry in <html_dir>/figures_manifest.json.

    The manifest of a save that has no target document — no-document mode, an explicit
    section. Keyed by LaTeX label ("Fig: <label>") to match the publishing agent's
    figures.json, whose FigureEmitter reads `interactive` as a path relative to this
    manifest file — and falls through to the static PNG when it is null, which is how a
    matplotlib figure publishes.
    """
    return update_manifest(Path(html_dir) / MANIFEST_NAME, key, entry)


def _migrate_old_manifest(plan, html_dir):
    """Move this analysis's pre-ADR-0003 entries into each chosen document's manifest.

    Before, every entry lived in `figures_html/figures_manifest.json`; now a document's
    lives in the document. Run on every save into a document, and a no-op once the old
    file has nothing left for it, so the first save after upgrading moves them and later
    ones neither repeat nor duplicate it.
    """
    for target in plan.targets:
        if target.document is not None:
            migrate_entries(Path(html_dir) / MANIFEST_NAME, target.manifest_path,
                            target.document.path, plan.analysis)


def save_document_figure(name, fig=None, caption=None, label=None, *, section=None,
                       tex=None, hover_fields=None, static_scale=2, html_dir=None,
                       sections_root=None, notebook=None, chapter=None,
                       chapters_root=None, documents=None, **save_kwargs):
    """Save a document figure: PNG into the LaTeX tree, plus interactive HTML if plotly.

    name is the figure file name; if it has no extension, ".png" is assumed. fig may be
    a plotly Figure (preferred) or a matplotlib Figure (static only); omitting it saves
    the current matplotlib figure. The section directory is chosen interactively
    unless section is given (a path relative to $DOC_REPO/Sections, e.g.
    "Results/ptg_application"), and the PNG is written to its Figures/ sub-directory —
    same filename and location as always, since the LaTeX and the publishing agent reference it
    by bare name. A commented-out figure block is appended to a .tex file in the
    section directory; tex names that file explicitly (no prompt) and tex=False skips
    the append.

    A relative section is written into **every** target document (`target_documents`)
    — one, for a nested analysis or $DOC_REPO; any number, for a workspace analysis.
    documents=["<name>", ...] narrows that to a subset; a name that is not a target
    raises. Every chosen target is checked before anything is written: one lacking the
    section, or one whose manifest records another analysis as the owner of this
    filename or label, raises and none of them is written.

    chapter= and chapters_root= are the pre-rename spellings of section= and
    sections_root=. They still work and warn; passing both spellings raises.

    With no document configured (no target documents) a relative section names no
    directory, so the PNG goes to `outputs/figures/<name>` in the active checkout
    instead and no .tex block is appended; the manifest is the html directory's, its
    `static` naming the local PNG.

    Plotly figures additionally write <stem>.html into the local html directory
    (html_dir argument, else $FIGURES_HTML_DIR, else the repo's figures_html/)
    with include_plotlyjs="directory", so one shared plotly.min.js sits alongside and
    the exports work offline — the publishing agent's site builder copies both. The
    HTML stays in this repo, whichever documents the PNG goes to.

    Every figure, either backend, gets a manifest entry keyed by "Fig: <label>" and
    carrying {interactive, static, stem, backend, generated, notebook, hover_fields},
    plus `analysis`, its owner, in a document. A document's entry is in the document's
    own figures_manifest.json, its paths relative to that file; anything else's is in the
    html directory's, as before. interactive is null for a matplotlib figure;
    hover_fields documents the identifying fields a plotly figure's hovertemplates
    expose. static_scale is the kaleido export scale (plotly only). Extra keyword
    arguments are forwarded to write_image (plotly) or savefig (matplotlib).

    Returns the saved PNG Path — a list of them, one per document, when it wrote to
    several.
    """
    section = _one_of("section", section, "chapter", chapter)
    sections_root = _one_of("sections_root", sections_root, "chapters_root", chapters_root)
    plan = _plan_save(section, sections_root, documents)

    file_name = Path(name).name if Path(name).suffix else f"{Path(name).name}.png"
    stem = Path(file_name).stem
    key = f"{FIGURE_PREFIX}{label or stem}"
    resolved_html_dir = _resolve_html_dir(html_dir)

    if plan is not None:
        _migrate_old_manifest(plan, resolved_html_dir)
        _check_owners(
            plan, f"The figure {file_name!r}",
            lambda target: (f"delete "
                            f"{_document_relative(target, target.section_dir / FIGURES_DIRNAME / file_name)}"
                            f" (and its \\begin{{figure}} block) from the document"),
            keys=(key,), stem=stem)
        _check_tex_targets(
            plan, tex,
            lambda section_dir: find_figure_reference(section_dir, file_name,
                                                      label) is not None)

    # No document: one flat outputs/figures/, not one per section, because the bare
    # filename is the key everywhere downstream and a section tree would only invite two
    # figures of one name. The name itself is never changed.
    save_paths = ([target.section_dir / FIGURES_DIRNAME / name for target in plan.targets]
                  if plan is not None
                  else [local_output_dir() / LOCAL_FIGURES_DIRNAME / name])
    save_paths = [path if path.suffix else path.with_suffix(".png") for path in save_paths]
    for path in save_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
    save_path = save_paths[0]

    if fig is None:
        fig = _matplotlib_figure()

    html_path = None
    if _is_plotly_figure(fig):
        backend = "plotly"
        save_kwargs.setdefault("scale", static_scale)
        _write_static_png(fig, save_path, **save_kwargs)
        print(f"Saved figure to: {save_path}")

        html_path = resolved_html_dir / f"{stem}.html"
        # "directory" (not "cdn"): the publishing agent's site builder copies the sibling
        # plotly*.js alongside the export so the published site works offline.
        fig.write_html(
            str(html_path),
            include_plotlyjs="directory",
            full_html=True,
            config={"displaylogo": False},
        )
        print(f"Saved interactive figure to: {html_path}")

        _default_hover_warning(fig, stem)
    else:
        # Not a warning: choosing matplotlib is a choice, and a warning on every save
        # is how a project learns to ignore the channel the checks above rely on.
        # ASCII only - this prints to a Windows console under cp1252.
        backend = "matplotlib"
        fig.savefig(save_path, **save_kwargs)
        print(f"Saved figure to: {save_path}")
        print("  static only (matplotlib) - no interactive export")

    # Rendered once and copied: the documents get byte-identical PNGs, and a plotly
    # figure does not pay kaleido's browser start per document.
    for path in save_paths[1:]:
        shutil.copyfile(save_path, path)
        print(f"Saved figure to: {path}")

    entry = {
        "interactive": html_path.name if html_path is not None else None,
        "static": str(save_path),
        "stem": stem,
        "backend": backend,
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "notebook": notebook or _detect_notebook(),
        "hover_fields": list(hover_fields) if hover_fields else [],
    }
    if plan is None or plan.targets[0].document is None:
        _update_manifest(resolved_html_dir, key, entry)
    else:
        for target, path in zip(plan.targets, save_paths):
            manifest_path = target.manifest_path
            update_manifest(manifest_path, key, dict(
                entry, analysis=plan.analysis,
                static=relative_to_manifest(manifest_path, path),
                interactive=(relative_to_manifest(manifest_path, html_path.resolve())
                             if html_path is not None else None)))

    # No document, no .tex to hold the block. Re-run once a document is configured and
    # the block is appended then, gated as always on the figure not being referenced.
    if plan is not None:
        for target, path in zip(plan.targets, save_paths):
            add_commented_figure_to_tex(path.name, target.section_dir, caption=caption,
                                        label=label, tex=tex)
    return _single_or_list(save_paths)


def _document_relative(target, path):
    """`path` relative to its target document's root, for a message; else as given."""
    try:
        return Path(path).relative_to(target.document.path).as_posix()
    except ValueError:
        return str(path)
