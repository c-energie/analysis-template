"""Start a notebook from notebooks/_template.ipynb, or graft its setup onto an existing one.

    notebook-skeleton new Results/ptg_application ptg_fits
    notebook-skeleton new Results/ptg_application ptg_fits --marimo
    notebook-skeleton retrofit notebooks/Results/ptg_application/old_fits.ipynb --section Results/ptg_application

Both fill the template's SECTION, NOTEBOOK and TEX. NOTEBOOK is always the file's real
name, because it keys the notebook's figures_config.toml table and its manifest entries,
and a hand-typed one drifts the first time the file is copied or renamed. TEX is worked
out from the section when $DOC_REPO is set: None when the section holds one .tex file (the
saver finds it), and a refusal naming the candidates when it holds several.

`new` writes notebooks/<section>/<name>.ipynb by default, so the notebooks tree mirrors the
document's Sections/ tree. Figure and table names stay as <<FIGURE>> / <<TABLE>>: the
savers refuse a placeholder, so an unnamed artefact raises instead of being saved.

`new --marimo` writes <name>.py from notebooks/_template_marimo.py instead, with the same
routing. NOTEBOOK is then the .py filename and the config key its stem, exactly as for a
.ipynb, so switching editors does not orphan a notebook's figures_config.toml table. Only
running the result needs marimo installed; writing it is plain text. `retrofit` stays
Jupyter-only: a copied-in notebook is a .ipynb, and marimo converts one itself.

`retrofit` is the step after copying an existing notebook in. It edits notebooks under this
repository's notebooks/ only -- the original stays wherever it was copied from -- inserts
the template's setup cell after the notebook's leading markdown, and lists the lines that
still save, export or change directory the old way, for converting to save_fig/save_table.

A notebook that already calls notebook_savers is not grafted, but its saver calls are
checked against the current signature, and retrofit exits non-zero if any is out of date.
An older fork's call -- `chapter=`, an unknown keyword, three names unpacked from two
savers, a `save_value` nobody asked for, a free-text `label=` -- otherwise reads as
"nothing to graft" and the notebook then fails at its setup cell, or worse, runs.
"""

import argparse
import ast
import inspect
import json
import re
import sys
from importlib.util import find_spec
from pathlib import Path

TEMPLATE = Path("notebooks") / "_template.ipynb"
MARIMO_TEMPLATE = Path("notebooks") / "_template_marimo.py"
# Marks a marimo template cell that belongs to one figure backend; the line itself is dropped.
MARIMO_BACKEND = re.compile(r"^# skeleton-backend: (\w+)\n", re.MULTILINE)
CELL_BREAK = "\n\n\n"  # marimo writes two blank lines between cells
# Split only where two blank lines are followed by the start of a cell (its backend marker
# or decorator) or the run guard. A bare CELL_BREAK split would also cut a cell whose body
# holds two blank lines, and the dropped backend's tail would survive as an unmarked cell.
CELL_START = re.compile(r"\n\n\n(?=# skeleton-backend: |@app\.|if __name__)")
BACKENDS = ("plotly", "matplotlib")
SAVER_CALL = "notebook_savers("

# What an existing notebook does that the savers now own. Listed, never rewritten: each
# one needs a name, caption and label that only the notebook's author can supply.
LEGACY_PATTERNS = {
    "figure save": re.compile(r"\.savefig\(|\.write_image\("),
    "html export": re.compile(r"\.write_html\("),
    "table export": re.compile(r"\.to_latex\(|\.style\.to_latex\("),
    "path hack": re.compile(r"os\.chdir\(|sys\.path\.(append|insert)\("),
}

# IPython syntax ast cannot parse. Blanked rather than dropped, so line numbers still match
# what the author sees in the cell.
MAGIC_LINE = re.compile(r"^\s*[%!]")
SAVER_NAMES = re.compile(r"\b(notebook_savers|save_fig|save_table|save_value)\s*\(")
SECTION_MEANING = ("check: in older forks `section=` meant the config table, which is now "
                   "`config_section=`; make sure this names the document section")


def _parse_cell(text):
    """The cell's syntax tree, or None for a cell magic or code ast cannot read."""
    if text.lstrip().startswith("%%"):
        return None
    # Plain Python first: a continuation line opening with `!=` or `%` looks like a magic,
    # and blanking it would turn a clean cell into an [unparsed] failure.
    for source in (text, "\n".join("" if MAGIC_LINE.match(line) else line
                                   for line in text.splitlines())):
        try:
            return ast.parse(source)
        except SyntaxError:
            pass
    return None


def _called_name(node):
    """`f` for a call to f(...) or to module.f(...), else None."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _constant(node):
    return node.value if isinstance(node, ast.Constant) else None


def savers_findings(cells):
    """Every out-of-date saver call in *cells*, as (cell, line, kind, message, is_problem).

    Parsed rather than pattern-matched: whether `save_value(...)` is wrong depends on
    whether some other cell asked for values=True, and whether a label is free text depends
    on the name passed beside it. The accepted keywords come from notebook_savers' own
    signature, so this check moves with the function instead of being a second list of it.
    """
    from doc_analysis.savers import notebook_savers

    params = inspect.signature(notebook_savers).parameters
    positional = [name for name, p in params.items()
                  if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    findings = []
    calls, unpacked, defined = [], {}, set()

    for index, cell in enumerate(cells):
        if cell.get("cell_type") != "code":
            continue
        text = "".join(cell.get("source", []))
        tree = _parse_cell(text)
        if tree is None:
            # Unreadable is not the same as clean: report it, or a saver call hidden behind
            # a magic would pass as "nothing to graft".
            if SAVER_NAMES.search(text):
                findings.append((index, 1, "unparsed", "cell is not plain Python; check its "
                                 "saver calls by hand", True))
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                calls.append((index, node))
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                unpacked[id(node.value)] = node.targets[0]
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defined.add(node.name)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                defined.update(alias.asname or alias.name for alias in node.names)

    def report(index, node, kind, message, is_problem=True):
        findings.append((index, node.lineno, kind, message, is_problem))

    values_enabled = False
    for index, node in calls:
        if _called_name(node) != "notebook_savers":
            continue
        keywords = {kw.arg: kw.value for kw in node.keywords if kw.arg is not None}
        for name in keywords:
            if name not in params:
                report(index, node, "unknown keyword",
                       f"notebook_savers() does not accept {name}=; it takes "
                       f"{', '.join(n + '=' for n in params)}")
        if len(node.args) > len(positional):
            report(index, node, "positional arguments",
                   f"notebook_savers() takes at most {len(positional)} positional "
                   f"arguments; pass them by keyword")
        if "chapter" in keywords and "chapter" in params:
            report(index, node, "deprecated keyword",
                   "chapter= still works but warns; use section=")
        section = keywords.get("section")
        if section is None and node.args and positional[:1] == ["section"]:
            section = node.args[0]
        # The template's own setup cell passes section=SECTION, documented beside it as a
        # path under Sections; warning on it would bury the calls that need a look.
        templated = isinstance(section, ast.Name) and section.id == "SECTION"
        if section is not None and not templated and "config_section" not in keywords:
            report(index, node, "check", SECTION_MEANING, is_problem=False)

        values = keywords.get("values") if "values" in params else None
        # values=FLAG is taken as asking for it; only a literal falsy value is known not to.
        wants_values = values is not None and (not isinstance(values, ast.Constant)
                                               or bool(values.value))
        values_enabled = values_enabled or wants_values
        target = unpacked.get(id(node))
        # A computed values= or a starred target could unpack anything: not counted.
        if (isinstance(target, (ast.Tuple, ast.List))
                and (values is None or isinstance(values, ast.Constant))
                and not any(isinstance(t, ast.Starred) for t in target.elts)):
            returned = 3 if wants_values else 2
            if len(target.elts) != returned:
                report(index, node, "unpacking",
                       f"unpacks {len(target.elts)} names, but this call returns "
                       f"{returned} savers" + ("" if wants_values or "values" not in params
                                               else "; pass values=True for save_value"))

    for index, node in calls:
        called = _called_name(node)
        if (called == "save_value" and isinstance(node.func, ast.Name)
                and not values_enabled and "save_value" not in defined):
            report(index, node, "save_value",
                   "save_value is only returned by notebook_savers(..., values=True)")
        if called in ("save_fig", "save_table") and isinstance(node.func, ast.Name):
            keywords = {kw.arg: kw.value for kw in node.keywords if kw.arg is not None}
            name = node.args[1] if len(node.args) > 1 else keywords.get("name")
            label = _constant(keywords.get("label"))
            name = _constant(name)
            # Only a label that provably differs from the stem: a variable may well hold it.
            if isinstance(label, str) and isinstance(name, str) and label != Path(name).stem:
                report(index, node, "free-text label",
                       f"label={label!r} must mirror the file stem {Path(name).stem!r}; "
                       f"drop it")
    return sorted(findings, key=lambda f: f[:2])


def report_savers(target, nb):
    """`retrofit` on a notebook that already calls notebook_savers: check, never graft."""
    findings = savers_findings(nb["cells"])
    for index, lineno, kind, message, _ in findings:
        lines = "".join(nb["cells"][index]["source"]).splitlines()
        print(f"  cell {index} line {lineno}  [{kind}]  "
              f"{lines[lineno - 1].strip() if lineno <= len(lines) else ''}")
        print(f"      {message}")
    problems = sum(1 for *_, is_problem in findings if is_problem)
    if problems:
        print(f"{target.name} already calls {SAVER_CALL[:-1]}, but {problems} problem(s) above "
              f"do not fit its current signature; fix them by hand.")
        return 1
    print(f"{target.name} already calls {SAVER_CALL[:-1]}; nothing to graft.")
    return 0


def find_root(start=None):
    """The analysis repo root: the nearest directory above *start* holding the template."""
    start = Path(start or Path.cwd()).resolve()
    for candidate in (start, *start.parents):
        if (candidate / TEMPLATE).exists():
            return candidate
    sys.exit(f"{TEMPLATE.as_posix()} not found above {start}. Run this from the analysis repo.")


def pick_backend(requested):
    if requested:
        return requested
    for backend in BACKENDS:
        if find_spec(backend) is not None:
            return backend
    sys.exit("Neither plotly nor matplotlib is installed: uv sync --extra plotly "
             "(or --extra matplotlib), or pass --backend.")


def resolve_tex(section, tex):
    """TEX for the setup cell, checked against the document when $DOC_REPO is set."""
    from doc_analysis.save_figure import GENERATED_TEX_NAMES, document_repo, sections_dir

    try:
        repo = document_repo()
    except (RuntimeError, NotADirectoryError) as exc:
        print(f"note: section not checked -- {exc}".splitlines()[0], file=sys.stderr)
        return tex
    if repo is None and not Path(section).is_absolute():
        # No-document mode: the notebook saves to outputs/ until a document is set, so
        # there is no section to check yet, and refusing here would block the very
        # analysis that comes before the write-up.
        print("note: section not checked -- no document is configured", file=sys.stderr)
        return tex
    section_dir = Path(section) if Path(section).is_absolute() else sections_dir() / section
    if not section_dir.is_dir():
        sys.exit(f"Section {section!r} not found: {section_dir} does not exist. Create the "
                 f"section in the document first, or check the spelling.")
    candidates = sorted(p.name for p in section_dir.glob("*.tex")
                        if p.name not in GENERATED_TEX_NAMES)
    if tex:
        if tex not in candidates:
            sys.exit(f"--tex {tex!r} is not in {section_dir}; it holds: {', '.join(candidates) or 'no .tex files'}.")
        return tex
    if len(candidates) > 1:
        sys.exit(f"{section_dir} holds several .tex files ({', '.join(candidates)}); "
                 f"pass --tex with the one that should receive figure references.")
    return None


def fill(source, section, notebook, tex, title):
    return (source.replace("<<SECTION>>", section)
                  .replace("<<NOTEBOOK>>", notebook)
                  .replace('"<<TEX>>"', json.dumps(tex) if tex else "None")
                  .replace("<<TITLE>>", title))


def template_cells(root, backend, section, notebook, tex, title):
    """The template's cells for *backend*, filled, with the template-only metadata dropped."""
    template = json.loads((root / TEMPLATE).read_text(encoding="utf-8"))
    cells = []
    for cell in template["cells"]:
        meta = cell.get("metadata", {})
        if meta.get("backend", backend) != backend:
            continue
        cell = dict(cell, metadata={k: v for k, v in meta.items()
                                    if k not in ("skeleton", "backend")})
        cell["source"] = fill("".join(cell["source"]), section, notebook, tex,
                              title).splitlines(keepends=True)
        cells.append((meta.get("skeleton"), cell))
    return template, cells


def write_notebook(path, notebook):
    path.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def new_target(root, args, suffix):
    """The new notebook's name, file name, path and TEX; refuses before anything is written."""
    name = args.name.removesuffix(suffix)
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", name):
        sys.exit(f"Notebook name {name!r}: letters, digits, '_', '-' and '.' only.")
    notebook = f"{name}{suffix}"  # the config key is its stem, whatever the suffix
    target = root / "notebooks" / (args.dir or args.section) / notebook
    if target.exists():
        sys.exit(f"{target} already exists; pick another name or edit that notebook.")
    return name, notebook, target, resolve_tex(args.section, args.tex)


def report_new(root, target, args, tex, kind=""):
    print(f"Wrote {target.relative_to(root).as_posix()}  ({kind}section {args.section}, "
          f"TEX {tex or 'auto'}). Name the figure and table before running it.")
    return 0


def cmd_new(args):
    if args.marimo:
        return cmd_new_marimo(args)
    root = find_root()
    name, notebook, target, tex = new_target(root, args, ".ipynb")
    template, cells = template_cells(root, pick_backend(args.backend), args.section, notebook,
                                     tex, args.title or name)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_notebook(target, dict(template, cells=[cell for _, cell in cells]))
    return report_new(root, target, args, tex)


def marimo_source(root, backend, section, notebook, tex, title):
    """The marimo template for *backend*, filled. Cells are blank-line-separated blocks."""
    blocks = CELL_START.split((root / MARIMO_TEMPLATE).read_text(encoding="utf-8"))
    kept = []
    for block in blocks:
        marker = MARIMO_BACKEND.search(block)
        if marker and marker.group(1) != backend:
            continue
        kept.append(MARIMO_BACKEND.sub("", block))
    return fill(CELL_BREAK.join(kept), section, notebook, tex, title)


def cmd_new_marimo(args):
    """`new --marimo`: the same routing as a Jupyter notebook, written as a marimo app."""
    root = find_root()
    if not (root / MARIMO_TEMPLATE).exists():
        sys.exit(f"{MARIMO_TEMPLATE.as_posix()} not found in {root}.")
    name, notebook, target, tex = new_target(root, args, ".py")
    text = marimo_source(root, pick_backend(args.backend), args.section, notebook, tex,
                         args.title or name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return report_new(root, target, args, tex, kind="marimo; ")


def cmd_retrofit(args):
    root = find_root()
    target = Path(args.notebook).resolve()
    if not target.is_relative_to(root / "notebooks"):
        sys.exit(f"{target} is outside {root / 'notebooks'}. retrofit edits only notebooks "
                 f"already copied into this repo; copy it in first.")
    if target.suffix != ".ipynb" or not target.exists():
        sys.exit(f"{target} is not an existing .ipynb file.")
    nb = json.loads(target.read_text(encoding="utf-8"))
    if any(SAVER_CALL in "".join(cell.get("source", [])) for cell in nb["cells"]):
        return report_savers(target, nb)

    tex = resolve_tex(args.section, args.tex)
    # Only the setup cell is grafted, and it is the same for both backends.
    _, cells = template_cells(root, args.backend or BACKENDS[0], args.section, target.name,
                              tex, target.stem)
    setup = [cell for kind, cell in cells if kind == "setup"]
    heading = next(cell for cell in (c for _, c in cells)
                   if "".join(cell["source"]).startswith("## Setup"))
    at = 0
    while at < len(nb["cells"]) and nb["cells"][at]["cell_type"] == "markdown":
        at += 1
    nb["cells"][at:at] = [heading, *setup]
    write_notebook(target, nb)
    print(f"Grafted the setup cell into {target.relative_to(root).as_posix()} "
          f"(section {args.section}, TEX {tex or 'auto'}).")

    found = 0
    grafted = range(at, at + 1 + len(setup))  # the template's own cells are never legacy
    for index, cell in enumerate(nb["cells"]):
        if cell["cell_type"] != "code" or index in grafted:
            continue
        for lineno, line in enumerate("".join(cell["source"]).splitlines(), 1):
            for kind, pattern in LEGACY_PATTERNS.items():
                if pattern.search(line):
                    found += 1
                    print(f"  cell {index} line {lineno}  [{kind}]  {line.strip()}")
    print(f"{found} line(s) to convert to save_fig / save_table." if found
          else "No legacy save, export or path lines found.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("new", help="a new notebook from the template")
    p.add_argument("section", help="path under $DOC_REPO/Sections, e.g. Results/ptg_application")
    p.add_argument("name", help="notebook file name, with or without .ipynb")
    p.add_argument("--dir", help="directory under notebooks/ (default: the section path)")
    p.add_argument("--title", help="the notebook's heading (default: its name)")
    p.add_argument("--marimo", action="store_true",
                   help="write a marimo app (<name>.py) from notebooks/_template_marimo.py")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("retrofit", help="graft the template's setup onto a copied-in notebook")
    p.add_argument("notebook", help="a notebook under this repo's notebooks/")
    p.add_argument("--section", required=True,
                   help="path under $DOC_REPO/Sections its artefacts belong to")
    p.set_defaults(func=cmd_retrofit)

    for p in sub.choices.values():
        p.add_argument("--tex", help="the section .tex receiving references, when it holds several")
        p.add_argument("--backend", choices=BACKENDS,
                       help="figure cell to use (default: whichever extra is installed)")

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
