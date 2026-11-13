"""The one reader of the package tree, imported by every check.

RULES THAT COST SOMETHING TO RELEARN
  - rglob from ROOT, never glob: a one-level glob silently scans a subset,
    and a check that scans a subset while printing ok is worse than no check.
    A package split into subpackages turned one such glob into a scan of 18
    of 90 files, and the check kept exiting 0.
  - An object's KIND comes from its file suffix (`.clas.abap`, `.intf.abap`,
    `.prog.abap`), never from a name prefix. A prefix written into a check
    matches nothing in the next package, and a literal that matches nothing
    reads exactly like one that matches everything.
  - A class is its main file PLUS its includes: abapGit serialises
    `.clas.abap`, `.clas.testclasses.abap` and `.clas.locals_imp.abap` as
    files of ONE object, so they are merged rather than letting the last one
    read win.
"""

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import _config
from _config import BASE, ROOT, get, path

# Every object this package owns, as one regex: classes, interfaces, DDIC,
# CDS. `[package] own`. Unset, the checks that need it print `--`.
OWN = get("package.own")

# The ABAP objects this package owns that source can name -- classes,
# interfaces, exception classes -- for `undrafted`. `[package] objects`,
# falling back to OWN.
OBJECTS = get("package.objects") or OWN

# The root ABAP package, for the register: abapGit's PREFIX folder logic names
# each subfolder's package `<devc>_<folder>`, and the XML carries no name.
DEVC = (get("package.devc") or "").lower()

# CDS sources by abapGit file kind.
CDS_KINDS = {"ddls": "asddls", "dcls": "asdcls", "ddlx": "asddlxs", "srvd": "srvdsrv"}

UI_ROOT = path("package.ui", "ui")

_SUFFIXES = (
    (".clas.testclasses.abap", "clas"), (".clas.locals_imp.abap", "clas"),
    (".clas.locals_def.abap", "clas"), (".clas.macros.abap", "clas"),
    (".clas.abap", "clas"), (".intf.abap", "intf"), (".prog.abap", "prog"),
    (".abap", "other"),
)


def _all_abap():
    return {str(p.relative_to(ROOT)): p.read_text(errors="replace")
            for p in sorted(ROOT.rglob("*.abap"))}


_ALL = _all_abap() if ROOT.is_dir() else {}
FILTER = _config.FILE_FILTER

# True while there is no ABAP to scan. Checks that read source report `--`.
EMPTY = not _ALL

if not ROOT.is_dir():
    print(f"WARNING: no source root at {ROOT} - every source check scans an "
          f"EMPTY corpus and its `ok` would mean nothing.", file=sys.stderr)
if FILTER:
    _kept = sum(1 for k in _ALL if any(f in k for f in FILTER))
    print(f"NOTE: --file narrows the corpus to {_kept} of {len(_ALL)} file(s). "
          f"Checks across objects (orphans, owners, impls) see part of the "
          f"package and will say so wrongly.", file=sys.stderr)


def abap_files():
    """{path-relative-to-ROOT: text} for every ABAP file, at any depth, or the
    ones `--file` selects."""
    if not FILTER:
        return dict(_ALL)
    return {k: v for k, v in _ALL.items() if any(f in k for f in FILTER)}


def package_abap():
    """{path-relative-to-ROOT: text} for every ABAP file, whatever `--file`
    selects: for a check whose facts are package-wide -- a type declared in
    one file keys the rows a method in another writes through -- and which
    applies FILTER to its findings itself. Narrowing the facts instead loses
    every finding that rests on a declaration outside the selection."""
    return dict(_ALL)


def stem(path_):
    """The object a file belongs to: `x/zcl_y.clas.testclasses.abap` is `zcl_y`."""
    name = Path(path_).name.lower()
    # A function group's includes and modules are files of ONE object too.
    if ".fugr." in name:
        return name.split(".fugr.")[0]
    for suffix, _ in _SUFFIXES:
        if name.endswith(suffix):
            return name[:-len(suffix)]
    return name


def kind(path_):
    """`clas`, `intf`, `prog`, `fugr` or `other`, from the file suffix."""
    name = Path(path_).name.lower()
    if ".fugr." in name:
        return "fugr"
    return next(k for s, k in _SUFFIXES if name.endswith(s))


def include(path_):
    """Which file of its object PATH is: `main` for the object's own source,
    else the include's name (`testclasses`, `locals_imp`, `locals_def`,
    `macros`). Read from the suffix, like the kind."""
    name = Path(path_).name.lower()
    suffix = next(s for s, _ in _SUFFIXES if name.endswith(s))
    parts = suffix.split(".")[2:-1]          # `.clas.testclasses.abap` -> [testclasses]
    return parts[0] if parts else "main"


def abap_by_stem():
    """{object name: source}, a class's includes merged into it."""
    merged = {}
    for k, v in abap_files().items():
        name = stem(k)
        merged[name] = merged[name] + "\n" + v if name in merged else v
    return merged


def kinds():
    """{object name: kind} for every ABAP object on disk."""
    return {stem(k): kind(k) for k in abap_files()}


def of_kind(src, which):
    """The objects of SRC whose kind is WHICH (`clas`, `intf`, ...)."""
    k = kinds()
    return {n: s for n, s in src.items() if k.get(n) == which}


def object_files(suffix):
    """{object name: path} for every `<name>.<suffix>` file at any depth, e.g.
    `object_files("tabl.xml")`. The name is the file's first dotted part."""
    if not ROOT.is_dir():
        return {}
    return {p.name.split(".")[0].lower(): p for p in sorted(ROOT.rglob(f"*.{suffix}"))}


_DDIC = {}


def ddic(kind_):
    """{object name: parsed XML root} for one serialised DDIC kind (tabl,
    dtel, doma, ...). The one reader of abapGit's DDIC XML, parsed once.

    A file that is not XML ends the run naming it: every check reading the
    kind would otherwise die on a parser traceback that does not say which
    of the package's files it choked on.
    """
    if kind_ not in _DDIC:
        _DDIC[kind_] = {n: read_xml(p) for n, p in object_files(f"{kind_}.xml").items()}
    return _DDIC[kind_]


def read_xml(p):
    """The root of one serialised file; a file that is not XML ends the run
    naming it."""
    try:
        return ET.parse(p).getroot()
    except ET.ParseError as e:
        shown = p.relative_to(BASE) if p.is_relative_to(BASE) else p
        sys.exit(f"{shown}: not well-formed XML ({e})")


def is_value_set(typ, dtels, domas):
    """True when TYP is a data element whose domain carries fixed values.

    `dtels` and `domas` are `ddic("dtel")` and `ddic("doma")`.
    """
    el = dtels.get(typ.split("=>")[-1].lower())
    if el is None:
        return False
    dom = el.findtext(".//DOMNAME") or ""
    doma = domas.get(dom.lower())
    if doma is None:
        return False
    # NOT any(): an Element with no children is falsy, so any() over an
    # iterator of leaf nodes answers False for a domain that HAS fixed
    # values. That bug made every value set look unprotected.
    return len(list(doma.iter("DOMVALUE_L"))) > 0


def cds_files(kind_="ddls"):
    """{object name: source} for one CDS kind (ddls, dcls, ddlx, srvd), any depth."""
    return {n: p.read_text(errors="replace")
            for n, p in object_files(f"{kind_}.{CDS_KINDS[kind_]}").items()}


def packages():
    """Every ABAP package on disk, by name, when `[package] devc` is set.

    A `package.devc.xml` carries no name: PREFIX folder logic derives it from
    the folder, `<devc>_<folder>_<subfolder>`; FULL names it by the folder.
    """
    if not DEVC or not ROOT.is_dir():
        return set()
    out = set()
    for p in ROOT.rglob("package.devc.xml"):
        parts = p.parent.relative_to(ROOT).parts
        if not parts:
            out.add(DEVC)
        elif _config.FOLDER_LOGIC.upper() == "FULL":
            out.add(parts[-1].lower())
        else:
            out.add("_".join((DEVC,) + parts))
    return out


def apps():
    """{BSP application name: its folder}, for every folder under the UI root
    with a manifest."""
    if not UI_ROOT or not UI_ROOT.is_dir():
        return {}
    return {p.parent.name.lower(): p.parent for p in sorted(UI_ROOT.glob("*/manifest.json"))}


def docs():
    """{path relative to BASE: text} for every file `[package] docs` globs.

    Unset, there are no documents: nothing in this suite assumes a project
    keeps its design in Markdown, or where.
    """
    out = {}
    for pattern in get("package.docs", []):
        for p in sorted(BASE.glob(pattern)):
            if p.is_file():
                out[str(p.relative_to(BASE))] = p.read_text(errors="replace")
    return out


def own_regex():
    """OWN compiled to match a whole name, or None."""
    return re.compile(rf"(?:{OWN})$", re.I) if OWN else None
