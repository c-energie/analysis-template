"""Start a notebook from notebooks/_template.ipynb, or graft its setup onto an existing one.

    notebook-skeleton new Results/ptg_application ptg_fits
    notebook-skeleton retrofit notebooks/Results/ptg_application/old_fits.ipynb --section Results/ptg_application

Both fill the template's SECTION, NOTEBOOK and TEX. NOTEBOOK is always the file's real
name, because it keys the notebook's figures_config.toml table and its manifest entries,
and a hand-typed one drifts the first time the file is copied or renamed. TEX is worked
out from the section when $DOC_REPO is set: None when the section holds one .tex file (the
saver finds it), and a refusal naming the candidates when it holds several.

`new` writes notebooks/<section>/<name>.ipynb by default, so the notebooks tree mirrors the
document's Sections/ tree. Figure and table names stay as <<FIGURE>> / <<TABLE>>: the
savers refuse a placeholder, so an unnamed artefact raises instead of being saved.

`retrofit` is the step after copying an existing notebook in. It edits notebooks under this
repository's notebooks/ only -- the original stays wherever it was copied from -- inserts
the template's setup cell after the notebook's leading markdown, and lists the lines that
still save, export or change directory the old way, for converting to save_fig/save_table.
"""

import argparse
import json
import re
import sys
from importlib.util import find_spec
from pathlib import Path

TEMPLATE = Path("notebooks") / "_template.ipynb"
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
    from doc_analysis.save_figure import document_repo, sections_dir

    try:
        document_repo()
    except (RuntimeError, NotADirectoryError) as exc:
        print(f"note: section not checked -- {exc}".splitlines()[0], file=sys.stderr)
        return tex
    section_dir = Path(section) if Path(section).is_absolute() else sections_dir() / section
    if not section_dir.is_dir():
        sys.exit(f"Section {section!r} not found: {section_dir} does not exist. Create the "
                 f"section in the document first, or check the spelling.")
    candidates = sorted(p.name for p in section_dir.glob("*.tex") if p.name != "tables.tex")
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


def cmd_new(args):
    root = find_root()
    name = args.name.removesuffix(".ipynb")
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", name):
        sys.exit(f"Notebook name {name!r}: letters, digits, '_', '-' and '.' only.")
    notebook = f"{name}.ipynb"
    target = root / "notebooks" / (args.dir or args.section) / notebook
    if target.exists():
        sys.exit(f"{target} already exists; pick another name or edit that notebook.")
    tex = resolve_tex(args.section, args.tex)
    template, cells = template_cells(root, pick_backend(args.backend), args.section, notebook,
                                     tex, args.title or name)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_notebook(target, dict(template, cells=[cell for _, cell in cells]))
    print(f"Wrote {target.relative_to(root).as_posix()}  (section {args.section}, "
          f"TEX {tex or 'auto'}). Name the figure and table before running it.")
    return 0


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
        sys.exit(f"{target.name} already calls {SAVER_CALL[:-1]}; nothing to graft.")

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
    grafted = range(at, at + 1 + len(setup))  # the template's own sys.path line is not legacy
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
