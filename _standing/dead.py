"""What nothing uses: private methods and fields, constants, and loops that
copy rows they should assign."""

import re

import _abap
from _pkg import ddic, is_value_set
from _runner import Finding
from _standing.package import CLASSES, CODE, GLOBAL, KINDS, SRC, main_class


def check_deadprivate():
    """A PRIVATE method its own class never calls.

    The sibling of `orphans`, which only walks interfaces -- so a private
    method is invisible to it and to every other check here.

    FRAMEWORK-INVOKED METHODS ARE NOT DEAD: `FOR TESTING` is called by ABAP
    Unit, SETUP / TEARDOWN by its fixture protocol, CONSTRUCTOR by NEW.

    COMMENTS ARE STRIPPED FIRST: a call inside a commented-out body is
    precisely the case where nothing calls it today.

    LIMITS: PRIVATE only -- a PROTECTED method may legitimately be called by
    a subclass in another file. An event handler (`FOR EVENT`) is called by
    SET HANDLER, which names it without parentheses, so it is exempt too.
    """
    bad = []
    for n, cls in GLOBAL.items():
        for d in cls.methods("PRIVATE"):
            meth = d.name.lower()
            if not _framework_called(d) and \
                    not re.search(rf"\b{re.escape(meth)}\s*\(", CODE[n], re.I):
                bad.append(Finding(f"{n}.{meth}", f"{n}.{meth}"))
    return sorted(bad), [f"{len(CLASSES)} classes scanned",
                         "PRIVATE only - PROTECTED may be called by a subclass"]


_FRAMEWORK = {"setup", "teardown", "class_setup", "class_teardown",
              "constructor", "class_constructor"}


def _framework_called(decl):
    """ABAP Unit, the fixture protocol, NEW or SET HANDLER calls it."""
    sig = decl.sig.upper()
    return decl.name.lower() in _FRAMEWORK or "FOR TESTING" in sig or "FOR EVENT" in sig


def check_writeonly():
    """A private field that is assigned and never read.

    Not "never called": passing a field on as an argument is a read. This
    flags a field whose ONLY occurrences are its declaration and its
    assignment.

    PRIVATE ONLY, the same boundary `deadprivate` draws and for the same
    reason: this scan is per class, and a PROTECTED field is read by
    subclasses it cannot see. A program's first local class is read too.
    """
    bad, scanned = [], 0
    for name in sorted(n for n in SRC if KINDS.get(n) in ("clas", "prog")):
        # The DEFINITION block only: a DATA inside a method body is a local.
        cls = main_class(name)
        fields = sorted(set(_abap.data_names(cls.section("PRIVATE")))) if cls else []
        stmts = [stmt for _, stmt in _abap.statements(CODE[name])]
        scanned += len(fields)
        for f in fields:
            if not any(_reads(stmt, f) for stmt in stmts):
                bad.append(Finding(f"{name}: {f.upper()} is assigned and never read",
                                   f"{name}:{f.upper()}"))
    return bad, [f"{scanned} private field(s) scanned"]


def _reads(stmt, field):
    """STMT names FIELD other than by declaring it or assigning to it."""
    if not re.search(rf"\b{re.escape(field)}\b", stmt, re.I):
        return False
    if re.match(rf"(?i)(?:me->)?{re.escape(field)}\s*=(?!=)", stmt):
        return False
    return field.lower() not in {n.lower() for n in _abap.data_names(stmt + ".")}


LOOP_INTO = re.compile(r"^\s*LOOP AT\s+.*?\bINTO\b", re.I | re.M)


def check_loops():
    """LOOP AT ... ASSIGNING FIELD-SYMBOL, not INTO.

    INTO copies the row on every iteration and cannot write back.

    READ TABLE ... INTO is deliberately NOT flagged. An unsuccessful READ
    leaves a field symbol unassigned, so code that reads the target after
    checking sy-subrc, or assigns a default into it, needs the copy.

    A loop that genuinely wants a copy -- because it modifies the work area
    without meaning to touch the table -- takes a suppression with that
    reason.
    """
    bad = []
    for name, text in SRC.items():
        for line in LOOP_INTO.findall(_abap.strip_comments(text)):
            stripped = " ".join(line.split())
            bad.append(Finding(f"{name}: {stripped} - use ASSIGNING FIELD-SYMBOL",
                               f"{name}: {stripped}"))
    return sorted(set(bad)), [f"{len(SRC)} object(s) scanned"]


def check_deadconst():
    """A constant nothing names, where the constant is not a value set.

    WHY THE EXEMPTION IS A RULE AND NOT A LIST. A member of a constant group
    whose data element has a domain with fixed values exists because the
    domain says so, not because code names it: the domain is the contract.
    A member of a group typed `c LENGTH 20`, backed by nothing, exists only
    because a caller asserted it -- and when there is none, it is dead. That
    asymmetry is the whole check, and it is derived from the DDIC rather than
    written down as exceptions. check_design `values` looks behind the
    exemption.

    A group NAME is not checked, only its members: passing a structured
    constant whole is legal and rare, and reporting the group would hide the
    member that is actually dead.
    """
    dtels, domas = ddic("dtel"), ddic("doma")
    body = "\n".join(CODE.values())
    dead, scanned, valuesets = [], 0, []
    for name in SRC:
        for grp, block in _abap.constant_groups(CODE[name]):
            members = _abap.constant_members(block)
            if members and is_value_set(members[0][1], dtels, domas):
                valuesets.append(grp)
                continue
            scanned += len(members)
            dead += [Finding(f"{name}: {grp}-{mem} declared, named nowhere", f"{grp}-{mem}".lower())
                     for mem, _, _ in members if not _named(f"{grp}-{mem}", body)]
        scalars = _abap.scalar_constants(CODE[name])
        scanned += len(scalars)
        # The declaration itself is one hit; anything beyond it is a use.
        dead += [Finding(f"{name}: {scalar} declared, named nowhere", scalar.lower())
                 for scalar, _ in scalars if _named(scalar, body) < 2]
    return sorted(set(dead)), [
        f"{scanned} constant(s) checked",
        f"value sets skipped, their domain is the contract: "
        f"{sorted(valuesets) or 'none'}"]


def _named(token, text):
    """How often TEXT names TOKEN as a whole word."""
    return len(re.findall(r"\b" + re.escape(token) + r"\b", text, re.I))
