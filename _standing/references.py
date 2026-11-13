"""References that must resolve: objects named in source, the interface
graph, `=>member`, retired names, name lengths, DDIC on disk."""

import re

import _abap
from _config import get
from _pkg import OBJECTS, OWN, ddic, docs
from _runner import Finding, needs
from _standing.package import CODE, INTERFACES, KINDS, SRC


NAME_LIMIT = 30          # ABAP global object name
TABLE_LIMIT = 16         # DDIC transparent table


def check_undrafted():
    """An object the SOURCE references that does not exist on disk.

    SOURCE ONLY, and the boundary matters. Scanning the documents too turns
    this into a report of the whole backlog -- every object a later work
    package builds, plus placeholders like `ZCL_X_<y>`, which are prose
    rather than references. Here the question is narrower and always a
    defect: ABAP names something that is not there.
    """
    if not OBJECTS:
        return needs("[package] objects")
    pat = re.compile(rf"\b(?:{OBJECTS})\b", re.I)
    named = set()
    for text in SRC.values():
        named |= {m.group(0).lower() for m in pat.finditer(_abap.strip_comments(text))}
    missing = [Finding(n, n) for n in sorted(named - set(SRC))]
    return missing, [f"{len(SRC)} objects on disk, {len(named)} referenced"]


def check_graph():
    """The interface dependency graph is acyclic."""
    deps = {n: {d for d in INTERFACES
                if d != n and re.search(rf"\b{re.escape(d)}\b", CODE[n], re.I)}
            for n in INTERFACES}

    def reach(n, seen=None):
        seen = seen if seen is not None else set()
        for d in deps.get(n, ()):
            if d not in seen:
                seen.add(d)
                reach(d, seen)
        return seen

    cycles = sorted(n for n in deps if n in reach(n))
    leaves = sorted(n for n, d in deps.items() if not d)
    return cycles, [f"{len(deps)} interfaces, {len(leaves)} leaves"]


def check_renamed():
    """A retired name still live, and WHERE.

    Suppression happens per (name, location) inside the loop: testing the
    pattern alone before knowing the location suppresses every occurrence,
    including ones nobody has seen.
    """
    retired = get("naming.retired")
    if not retired:
        return needs("[naming] retired")
    bad = []
    for pat in retired:
        for name, text in {**SRC, **docs()}.items():
            if re.search(pat, text):
                bad.append(Finding(f"{pat} in {name}", f"{pat} in {name}"))
    return sorted(bad), [f"{len(retired)} retired pattern(s) watched, "
                         f"{len(docs())} document(s) read"]


def _declared_names(name, text):
    """Names an object exposes to `=>`, from its DECLARATION part only.

    Deliberately LENIENT about what a declaration looks like: any
    `<name> TYPE ...` inside the declaration part counts, which sweeps up
    structure components that are not reachable through `=>` at all. That is
    the safe direction -- this check exists to catch a reference to a name
    the target does not contain ANYWHERE.
    """
    part = _abap.declaration_part(text, KINDS.get(name))
    decl = r"(?:(?:CLASS-)?(?:TYPES|CONSTANTS|DATA)\s*:?\s*)?"
    names = set(re.findall(rf"^\s*{decl}([a-z_]\w*)\s+TYPE\b", part, re.I | re.M))
    names |= set(re.findall(rf"^\s*{decl}BEGIN\s+OF\s+([a-z_]\w*)", part, re.I | re.M))
    names |= {d.name for d in _abap.declarations(part)}
    return {n.lower() for n in names}


def check_qualified():
    """`zif_x=>name` resolves to something ZIF_X declares.

    The graph check only asks WHICH interfaces are referenced, never whether
    the member exists -- so a type moved next to the method that returns it
    leaves every old `..._TYPES=>` reference pointing at an interface that no
    longer has it, and nothing says so until SE24.

    Only the part before the first `-` is checked: `mc_state-done` asks
    whether MC_STATE exists, not whether that component does.
    """
    bad, n = [], 0
    decls = {name: _declared_names(name, text) for name, text in SRC.items()}
    for name, text in CODE.items():
        for target, member in re.findall(r"\b([zy]\w+)\s*=>\s*(\w+)", text, re.I):
            target, member = target.lower(), member.lower()
            if target not in decls:
                continue          # not ours - `undrafted` owns that
            n += 1
            if member in decls[target]:
                continue
            bad.append(Finding(f"{target}=>{member} in {name}", f"{target}=>{member} in {name}"))
    return sorted(set(bad)), [
        f"{n} qualified reference(s) across {len(decls)} objects",
        "member existence only -- whether a `-component` after it is real "
        "is not checked"]


def check_names():
    """Object names inside ABAP's limits, tables inside DDIC's shorter one."""
    bad = [Finding(f"{n} ({len(n)} > {NAME_LIMIT})", n) for n in SRC if len(n) > NAME_LIMIT]
    tables = sorted(ddic("tabl"))
    bad += [Finding(f"{t} ({len(t)} > {TABLE_LIMIT}, DDIC table limit)", t)
            for t in tables if len(t) > TABLE_LIMIT]
    longest = max((len(n) for n in SRC), default=0)
    return sorted(bad), [f"ABAP objects: max {longest} of {NAME_LIMIT}",
                         f"DDIC tables: {len(tables)}, max "
                         f"{max((len(t) for t in tables), default=0)} of {TABLE_LIMIT}"]


def check_ddic():
    """Every customer DDIC object a table or a data element names exists on
    disk, and so does every package type the ABAP names.

    abapGit imports a package as a unit and fails on the first unresolvable
    reference, so a table whose ROLLNAME names a data element nobody
    serialised is a failed import rather than a compile error somewhere --
    and the message names the table, not the missing element.

    A customer name (Z/Y) outside this package -- another package's data
    element -- is a finding too: suppress it, `table: ROLLNAME x`, naming
    the package that delivers it.
    """
    have = set()
    for kind_ in ("doma", "dtel", "tabl", "ttyp", "enqu", "msag", "shlp", "view"):
        have |= set(ddic(kind_))
    refs = list(_ddic_references())
    bad = [Finding(f"{owner}: {what} {name} is not on disk", f"{owner}: {what} {name}")
           for owner, what, name in refs if name.lower() not in have]
    notes = [f"{len(have)} DDIC object(s), {len(refs)} customer reference(s) in DDIC"]
    if not OWN:
        notes.append("TYPE references in ABAP not checked: set `[package] own`")
        return sorted(set(bad)), notes
    known = have | set(SRC) | _badis()
    types = [(name, typ) for name, code in CODE.items()
             for typ in re.findall(rf"(?i)\bTYPE\s+(?:REF\s+TO\s+)?({OWN})\b", code)]
    bad += [Finding(f"{name}: TYPE {typ} resolves to nothing on disk",
                    f"{name}:{typ.lower().split('=>')[0]}")
            for name, typ in types if typ.lower().split("=>")[0] not in known]
    notes.append(f"{len(types)} package TYPE reference(s) in ABAP")
    return sorted(set(bad)), notes


# Where DDIC names other DDIC: (kind, tag) of each reference abapGit resolves.
_DDIC_REFS = (("tabl", "ROLLNAME"), ("tabl", "PRECFIELD"), ("tabl", "CHECKTABLE"),
              ("dtel", "DOMNAME"), ("ttyp", "ROWTYPE"))


def _ddic_references():
    """(owner, tag, name) for each customer (Z/Y) name the DDIC XML references."""
    return [(owner, tag, e.text) for kind_, tag in _DDIC_REFS
            for owner, root in ddic(kind_).items() for e in root.iter(tag)
            if e.text and e.text.lower().startswith(("z", "y"))]


def _badis():
    """BAdI definitions on disk. One is not a file of its own: it lives inside
    its enhancement spot's XML. (Read by tag; no serialised spot has been seen
    yet to confirm abapGit's layout beyond the tag name.)"""
    from _pkg import object_files
    return {b.lower() for f in object_files("enhs.xml").values()
            for b in re.findall(r"<BADI_NAME>(\w+)</BADI_NAME>", f.read_text())}
