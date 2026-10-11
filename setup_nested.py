#!/usr/bin/env python3
"""Put the document repo inside this one, as a nested repo of its own (the nested layout).

    python setup_nested.py                    # create it from writing-template, with gh
    python setup_nested.py --from <url|path>  # adopt an existing one (GitHub, Overleaf, local)
    python setup_nested.py                    # on a fresh clone: restore it from layout.toml

The document repo is cloned into a subdirectory — `<this repo's name>-writing` unless
`--dir` says otherwise — which is added to `.gitignore`, and the committed `layout.toml`
records where it is and where it came from. `doc_analysis` reads `DOC_REPO` from that file
at runtime, so this script never writes `.env`: an absolute path there would be wrong on
every other clone, and a relative one would resolve against the notebook's working
directory (docs/adr/0001-doc-repo-from-layout.md).

The nested repo is a **separate repo with its own remote**. Commit to it there; this repo
only ever commits `layout.toml` and the `.gitignore` line.

With no arguments it creates the repo, unless `layout.toml` already exists — then it
restores: clones `nested_remote` into `nested_dir` if that is missing, and does nothing if
it is there. That is the one step a fresh clone of this repo needs.

Stdlib only, and independent of `doc_analysis`: it runs before anything is installed.
It never prompts, and it never moves or modifies the source of `--from`.
"""
import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path, PurePosixPath, PureWindowsPath

ROOT = Path(__file__).resolve().parent
LAYOUT_FILE = ROOT / "layout.toml"
GITIGNORE = ROOT / ".gitignore"

LAYOUT = "analysis-hosts-writing"
# Kept in step with src/doc_analysis/layout.py, which reads the same file at runtime but
# cannot be imported from here.
KNOWN_KEYS = ("layout", "nested_dir", "nested_remote")
TEMPLATE_REPO = "c-energie/writing-template"

# The owner part of a GitHub remote, in https, scp-like ssh and ssh:// form.
GITHUB_OWNER = re.compile(r"github\.com[:/]+([^/]+)/")

NO_GH_HINT = ("Run `gh auth login` and try again, or create the document repo yourself "
              "and adopt it with `python setup_nested.py --from <url>`.")


def fail(message):
    sys.exit(f"setup_nested.py: {message}")


def run(*command, cwd=None):
    """Run a command, its output passed through; return the CompletedProcess."""
    return subprocess.run(command, cwd=cwd, stdin=subprocess.DEVNULL)


def output(*command, cwd=None):
    """A command's stripped stdout, or None if it failed or could not be run."""
    try:
        result = subprocess.run(command, cwd=cwd, stdin=subprocess.DEVNULL,
                                capture_output=True, encoding="utf-8")
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def read_layout():
    """layout.toml as a dict, or None. Malformed is fatal: it is the file being trusted."""
    if not LAYOUT_FILE.is_file():
        return None
    try:
        data = tomllib.loads(LAYOUT_FILE.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        fail(f"{LAYOUT_FILE.name} is not valid TOML ({exc}).")
    unknown = sorted(set(data) - set(KNOWN_KEYS))
    if unknown:
        fail(f"{LAYOUT_FILE.name}: unknown key(s) {', '.join(unknown)}.")
    if data.get("layout") != LAYOUT:
        fail(f"{LAYOUT_FILE.name} declares layout = {data.get('layout')!r}; this script "
             f"only sets up {LAYOUT!r}.")
    if not isinstance(data.get("nested_dir"), str) or not data["nested_dir"].strip():
        fail(f"{LAYOUT_FILE.name}: `nested_dir` is missing.")
    # The same check as --dir, and as doc_analysis's reader: a hand-edited `../x` would
    # otherwise be restored by cloning outside this repo, and gitignored as `/../x/`.
    try:
        checked_dir(data["nested_dir"])
    except argparse.ArgumentTypeError as exc:
        fail(f"{LAYOUT_FILE.name}: nested_dir {exc}")
    return data


def checked_dir(value):
    """--dir as a clean relative posix path inside this repo."""
    for flavour in (PurePosixPath, PureWindowsPath):
        pure = flavour(value)
        if pure.is_absolute() or pure.anchor or ".." in pure.parts:
            raise argparse.ArgumentTypeError(f"{value!r} must be a directory inside this "
                                              f"repo, relative to it.")
    parts = PureWindowsPath(value).parts
    if not parts or parts == (".",):
        raise argparse.ArgumentTypeError("--dir must name a subdirectory.")
    return PurePosixPath(*parts).as_posix()


def toml_string(value):
    """A TOML basic string. json.dumps is close but writes surrogate pairs TOML rejects."""
    escaped = []
    for char in value:
        if char in '"\\':
            escaped.append("\\" + char)
        elif ord(char) < 0x20 or ord(char) == 0x7F:
            escaped.append(f"\\u{ord(char):04x}")
        else:
            escaped.append(char)
    return '"' + "".join(escaped) + '"'


def write_layout(nested_dir, nested_remote):
    LAYOUT_FILE.write_text(
        "# Written by setup_nested.py. Committed: it tells every clone, and doc_analysis,\n"
        "# where the document repo sits. nested_dir is a separate repo with its own remote,\n"
        "# gitignored here — commit there, never here. Restore it on a fresh clone with\n"
        "#     python setup_nested.py\n"
        f"layout = {toml_string(LAYOUT)}\n"
        f"nested_dir = {toml_string(nested_dir)}\n"
        f"nested_remote = {toml_string(nested_remote)}\n",
        encoding="utf-8",
    )


def ignore(nested_dir):
    """Add /<dir>/ to .gitignore unless an equivalent line is there; return whether added."""
    entry = f"/{nested_dir}/"
    equivalent = {entry, f"/{nested_dir}", f"{nested_dir}/", nested_dir}
    text = GITIGNORE.read_text(encoding="utf-8") if GITIGNORE.exists() else ""
    if any(line.strip() in equivalent for line in text.splitlines()):
        return False
    if text and not text.endswith("\n"):
        text += "\n"
    text += ("\n# ---- nested document repo ----\n"
             "# A separate repo with its own remote (see layout.toml): commit there, not here.\n"
             f"{entry}\n")
    GITIGNORE.write_text(text, encoding="utf-8")
    return True


def origin_of(repo):
    url = output("git", "-C", str(repo), "remote", "get-url", "origin")
    if not url:
        fail(f"{repo} has no `origin` remote, so layout.toml cannot record where to restore "
             f"it from. Add one there (git remote add origin <url>) and run this again.")
    return url


def gh_owner(gh):
    """The owner of this repo's GitHub origin, else the authenticated gh user."""
    origin = output("git", "-C", str(ROOT), "remote", "get-url", "origin") or ""
    match = GITHUB_OWNER.search(origin)
    if match:
        return match.group(1)
    login = output(gh, "api", "user", "--jq", ".login")
    if not login:
        fail(f"could not tell which GitHub account to create the repo under. Pass --owner. "
             f"{NO_GH_HINT}")
    return login


def create(target, nested_dir, owner, name, public):
    """`gh repo create --template --clone`, staged in a temp dir and moved into place.

    gh clones into `./<name>`, which is not where --dir may want it; staging inside this
    repo keeps the move on one filesystem, and a refusal leaves nothing behind.
    """
    gh = shutil.which("gh")
    if gh is None:
        fail(f"`gh` (the GitHub CLI) is not installed. {NO_GH_HINT}")
    if output(gh, "auth", "status") is None:
        fail(f"`gh` is not logged in. {NO_GH_HINT}")
    owner = owner or gh_owner(gh)

    staging = Path(tempfile.mkdtemp(prefix=".setup-nested-", dir=ROOT))
    try:
        result = run(gh, "repo", "create", f"{owner}/{name}", "--template", TEMPLATE_REPO,
                     "--public" if public else "--private", "--clone", cwd=staging)
        cloned = staging / name
        if result.returncode != 0 or not (cloned / ".git").exists():
            fail(f"`gh repo create {owner}/{name}` did not complete; nothing was changed "
                 f"here. If the repo was created on GitHub, adopt it with "
                 f"`python setup_nested.py --from <its url>`. {NO_GH_HINT}")
        if target.exists():
            target.rmdir()  # checked empty before anything ran
        target.parent.mkdir(parents=True, exist_ok=True)
        cloned.rename(target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def clone(source, target):
    if shutil.which("git") is None:
        fail("`git` is not installed.")
    if run("git", "clone", source, str(target)).returncode != 0:
        fail(f"`git clone {source}` failed; nothing was changed here.")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        epilog="With no arguments: restore from layout.toml if it exists, else create.")
    parser.add_argument("--from", dest="source", metavar="SRC",
                        help="adopt an existing document repo: anything `git clone` accepts "
                             "(a GitHub or Overleaf git URL, a local path). Never modified.")
    parser.add_argument("--dir", type=checked_dir,
                        help="subdirectory to put it in (default: layout.toml's nested_dir, "
                             "else <this repo's directory name>-writing)")
    parser.add_argument("--owner", help="GitHub owner to create under (default: the owner "
                                        "of this repo's origin, else your gh user)")
    parser.add_argument("--name", help="GitHub repo name to create (default: the --dir name)")
    parser.add_argument("--public", action="store_true",
                        help="create it public (default: private)")
    return parser, parser.parse_args(argv)


def main(argv=None):
    parser, args = parse_args(argv)
    layout = read_layout()
    no_arguments = not any((args.source, args.dir, args.owner, args.name, args.public))

    if layout is not None and no_arguments:
        nested_dir = layout["nested_dir"]
        target = ROOT / nested_dir
        # An empty directory is what a half-finished clone or an IDE leaves: fill it.
        if target.exists() and (not target.is_dir() or any(target.iterdir())):
            print(f"{nested_dir}/ is already here; nothing to do.")
            return 0
        remote = layout.get("nested_remote")
        if not remote:
            fail(f"{LAYOUT_FILE.name} has no nested_remote to restore {nested_dir}/ from. "
                 f"Adopt it with `python setup_nested.py --from <url>`.")
        clone(remote, target)
        ignore(nested_dir)
        print(f"\nRestored {nested_dir}/ from {remote}.")
        return 0

    nested_dir = args.dir or (layout["nested_dir"] if layout else f"{ROOT.name}-writing")
    if layout is not None and layout["nested_dir"] != nested_dir:
        fail(f"{LAYOUT_FILE.name} already puts the document repo at {layout['nested_dir']}/, "
             f"not {nested_dir}/. One host repo nests one document repo.")
    if args.source and (args.owner or args.name or args.public):
        parser.error("--owner, --name and --public only apply when creating, not with --from")

    target = ROOT / nested_dir
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        fail(f"{nested_dir}/ already exists and is not empty. Pick another --dir, or move "
             f"it aside first.")

    if args.source:
        clone(args.source, target)
    else:
        create(target, nested_dir, args.owner, args.name or PurePosixPath(nested_dir).name,
               args.public)

    remote = origin_of(target)
    write_layout(nested_dir, remote)
    ignore(nested_dir)

    print(f"\nThe document repo is at {nested_dir}/ (origin: {remote}).")
    print("Commit here: layout.toml and .gitignore.")
    print(f"The document itself is committed in {nested_dir}/, which is a separate repo — "
          f"never here.")
    print("DOC_REPO needs no setting: doc_analysis reads it from layout.toml.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
