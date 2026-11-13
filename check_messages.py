#!/usr/bin/env python3
"""Message classes: every T100 number raised, reconciled -- and, where a
package collects messages in a buffer, who owns the buffer.

    python3 check_messages.py [missing unraised arity placeholder buffer export]

WHY THIS EXISTS
---------------
It was reconstructed by hand four times in one session, differently each
time, and one of those hand-written versions used `\\d` inside a `grep -E`
pattern -- unsupported in ERE, so it matched nothing and reported every
message as unraised. A check that silently matches zero is the failure
this suite exists to prevent.

WHAT IT CHECKS
--------------
  raised      a literal MESSAGE xNNN(class) anywhere in the package
  defined     a <MSGNR> in the serialised message class, when one exists
  arity       the number of WITH operands at each raise site

and reports:

  missing     raised but neither defined nor listed as pre-existing
  unraised    defined here but raised nowhere -- dead surface
  arity       one number raised with two different operand counts. A T100
              row is keyed (ARBGB, MSGNR) and the severity letter is NOT
              part of it, so w017 and s017 are the SAME text
  placeholder a defined text whose &1..&4 count disagrees with the arity
              its call sites use
  buffer      (fact: [messages.buffer]) a class that takes an injected
              buffer AND exports one: a caller can alias the buffer it also
              gets back, and every message in it is collected twice
  export      (fact: [messages.buffer] export) a method that exports the
              buffer as its last statement must not RETURN or CHECK above
              it: the caller gets an empty table while the reason sits in
              the buffer

CONFIG (abapcheck.toml)
  [messages] classes        the classes to reconcile; default: every
                            *.msag.xml on disk
  [messages.pre_existing]   class = ["001", ...]: numbers that live in a class
                            this package does not own
  [messages.buffer]         inject = "io_msg" (constructor parameter),
                            exporting = "et_messages", export = regex of the
                            statement that hands the buffer back

WHAT IT CANNOT SEE
------------------
The dynamic form, `MESSAGE ID x TYPE y NUMBER z`, where the number is a
variable or constant. That is exactly why a package should raise literals:
SE91 where-used and ATC are blind to the dynamic form too. Sites using it are
counted and listed, never silently skipped.
"""
import re
from collections import defaultdict
from dataclasses import dataclass, field

import _abap
from _config import get
from _pkg import EMPTY, abap_by_stem, abap_files, object_files, of_kind, read_xml
from _runner import Finding, Skip, exit_with, needs, run, suppressions

SCRIPT = "messages"
suppressed = suppressions(SCRIPT)

PRE_EXISTING = {k.lower(): set(v) for k, v in get("messages.pre_existing", {}).items()}
LITERAL = re.compile(r"MESSAGE\s+([aeiswx])([0-9]{3})\(([a-z_0-9]+)\)(.*?)(?:INTO|\.)\s",
                     re.I | re.S)
# The other way a number reaches a raise: a T100 key constant group on an
# exception class, handed to RAISE EXCEPTION as TEXTID. Discouraged here --
# the number belongs at the raise site, where SE91 where-used and
# ATC can see it, which is the same reason the literal form is preferred over
# `MESSAGE ID ... NUMBER`. Recognised here so such a group is REPORTED rather
# than read as an unraised number, which is what it looks like otherwise.
T100KEY = re.compile(r"BEGIN OF\s+(\w+)\s*,(.*?)END OF\s+\1", re.I | re.S)
MSGID = re.compile(r"\bmsgid\b[^,]*VALUE\s+'([^']*)'", re.I)
MSGNO = re.compile(r"\bmsgno\b[^,]*VALUE\s+'([^']*)'", re.I)
ATTR = re.compile(r"\battr[1-4]\b[^,]*VALUE\s+'([^']*)'", re.I)
DYNAMIC = re.compile(r"MESSAGE\s+ID\b", re.I)
OPERAND = re.compile(r"\|[^|]*\||'[^']*'|`[^`]*`|[\w\-<>]+")


def _arity(with_clause):
    """How many operands a WITH clause carries, string templates counted as one."""
    # DISPLAY LIKE and RAISING take one operand each and may stand before or
    # after WITH; neither is a message variable.
    s = re.sub(r"(?i)\b(?:DISPLAY\s+LIKE|RAISING)\s+(?:'[^']*'|[\w\-<>]+)", " ",
               with_clause).strip()
    if not s.upper().startswith("WITH"):
        return 0
    s = re.sub(r"(?i)^WITH\s+", "", s)
    # EXPORTING ends the operand list. RAISE ... MESSAGE xNNN(c) WITH a b
    # EXPORTING it_return = ... is one statement, and everything after
    # EXPORTING is constructor parameters, not message variables. Without
    # this, a site carrying a BAPI RETURN reports a phantom arity of 5 or
    # 6 against a 2-slot text.
    s = re.split(r"(?i)\bEXPORTING\b", s, maxsplit=1)[0]
    # Collapse anything that is one operand but tokenises as several:
    # a string template |{ ... }| , and a table expression x[ ... ]-y ,
    # which cost this check a phantom arity of 3 on WITH lt_items[ 1 ]-ztempl.
    s = re.sub(r"\|\{[^}]*\}\|", "|X|", s)
    s = re.sub(r"\[[^\]]*\]", "", s)
    return len(OPERAND.findall(s))


@dataclass
class Raised:
    """Every raise site of one (class, number)."""
    arity: set[int] = field(default_factory=set)       # WITH operand counts seen
    letters: set[str] = field(default_factory=set)     # severity letters seen
    sites: list[str] = field(default_factory=list)     # `file:line`


def watched():
    """The message classes reconciled: `[messages] classes`, else every class
    serialised under the root. Never derived from a package or prefix name: a
    prefix that matches for one package matches nothing for the next, and the
    check then reports "0 number(s) raised" against live raise sites."""
    return {c.lower() for c in get("messages.classes", [])} or set(object_files("msag.xml"))


def raised():
    """{(class, number): Raised}.

    Keyed by (ARBGB, MSGNR) because that is the T100 key. Keying on the
    number alone is correct only while a package raises out of exactly one
    class; with two live it reports a phantom ARITY clash the moment their
    020s carry different operands.
    """
    found = defaultdict(Raised)
    dynamic, textid = [], []
    for name, raw in abap_files().items():
        # Comments stripped, line numbering preserved: a class comment
        # carrying a worked RAISE ... MESSAGE example would otherwise
        # report an arity clash against real code.
        text = _abap.strip_comments(raw)
        _literal_raises(name, text, found)
        dynamic += [f"{name}:{_lineno(text, m)}" for m in DYNAMIC.finditer(text)]
        textid += _text_ids(name, text)
    return found, dynamic, textid


def _lineno(text, m):
    return text[:m.start()].count("\n") + 1


def _literal_raises(name, text, found):
    """Record each `MESSAGE xNNN(class)` of a watched class in FOUND. A package
    may raise out of more than one class (its own, plus a pre-existing one it
    does not own); numbers are keyed (ARBGB, MSGNR), so arity is grouped per
    class."""
    for m in LITERAL.finditer(text):
        letter, num, cls, rest = m.group(1), m.group(2), m.group(3).lower(), m.group(4)
        if cls in WATCHED:
            e = found[(cls, num)]
            e.arity.add(_arity(rest))
            e.letters.add(letter.lower())
            e.sites.append(f"{name}:{_lineno(text, m)}")


def _text_ids(name, text):
    """`file:line GROUP = class number` for each T100 text-id constant of a
    watched class."""
    out = []
    for m in T100KEY.finditer(text):
        cls, num = MSGID.search(m.group(2)), MSGNO.search(m.group(2))
        if cls and num and cls.group(1).lower() in WATCHED:
            out.append(f"{name}:{_lineno(text, m)} {m.group(1).upper()} "
                       f"= {cls.group(1).lower()} {num.group(1)}")
    return out


def defined():
    """{class: {number: text}} for every serialised message class found.

    Every *.msag.xml, not the first: the first is right for a package with
    one class and silently ignores the second. The class name comes from the
    file stem (`zx.msag.xml`), so an unserialised class simply has no entry
    and its numbers are neither missing nor unraised - unknown, not wrong.
    """
    out = {}
    for cls, f in object_files("msag.xml").items():
        rows = {}
        for t100 in read_xml(f).iter("T100"):
            num = t100.findtext("MSGNR")
            if num:
                rows[num] = t100.findtext("TEXT") or ""
        out[cls] = (rows, f)
    return out


WATCHED = watched()
USED, DYNAMIC, TEXTID = raised() if not EMPTY else ({}, [], [])
DEFS = defined()


def _slots(text):
    return len(set(re.findall(r"&([1-4])", text))) or text.count("&")


def _notes():
    serialised = ", ".join(f"{c} ({len(r)})" for c, (r, _) in sorted(DEFS.items()))
    notes = [f"{len(USED)} (class, number) pair(s) raised across "
             f"[{', '.join(sorted(WATCHED)) or 'no class'}], defined: "
             f"{serialised or 'none - no *.msag.xml found'}"]
    if TEXTID:
        notes.append(f"{len(TEXTID)} number(s) held in a T100 text-id constant, "
                     f"invisible to SE91 where-used, ATC and `arity`: " + "; ".join(TEXTID))
    if DYNAMIC:
        notes.append(f"{len(DYNAMIC)} dynamic MESSAGE ID site(s), invisible to this "
                     f"check, SE91 where-used and ATC: " + ", ".join(DYNAMIC))
    return notes


def check_missing():
    if not DEFS:
        return Skip("no *.msag.xml on disk to reconcile against")
    bad = []
    for cls, (have, msag) in sorted(DEFS.items()):
        pre = PRE_EXISTING.get(cls, set())
        for (c, num) in sorted(USED):
            if c == cls and num not in have and num not in pre:
                bad.append(Finding(f"{cls} {num} raised at {USED[(c, num)].sites[0]}, "
                                   f"not in {msag.name} and not pre-existing", f"{cls} {num}"))
    return bad, _notes()


def check_unraised():
    if not DEFS:
        return Skip("no *.msag.xml on disk to reconcile against")
    bad = []
    for cls, (have, msag) in sorted(DEFS.items()):
        mine = {num for c, num in USED if c == cls}
        bad += [Finding(f"{cls} {num} defined in {msag.name}, raised nowhere", f"{cls} {num}")
                for num in sorted(have) if num not in mine]
    return bad, []


def check_arity():
    bad = []
    for (cls, num), e in sorted(USED.items()):
        if len(e.arity) > 1:
            bad.append(Finding(f"{cls} {num} raised with {sorted(e.arity)} operands as "
                               f"{'/'.join(sorted(e.letters))} -- one T100 text cannot serve "
                               f"both: {', '.join(e.sites)}", f"{cls} {num}"))
    return bad, []


def check_placeholder():
    if not DEFS:
        return Skip("no *.msag.xml on disk to reconcile against")
    defined = [(cls, num, e, have[num]) for cls, (have, _) in sorted(DEFS.items())
               for (c, num), e in sorted(USED.items()) if c == cls and num in have]
    return [Finding(f"{cls} {num} text has {_slots(text)} slot(s), raised with "
                    f"{n} operand(s) at {e.sites[0]}", f"{cls} {num}")
            for cls, num, e, text in defined for n in sorted(e.arity) if _slots(text) != n], []


def check_buffer():
    """A component RETURNS its messages or takes an injected buffer, never both.

    Convention alone did not hold: a dispatcher shared one with a service two
    lines below a comment saying buffers must not be shared.
    """
    inject, exporting = get("messages.buffer.inject"), get("messages.buffer.exporting")
    if not inject or not exporting:
        return needs("[messages.buffer] inject and exporting")
    bad, collectors, services = [], 0, 0
    for name, body in sorted(of_kind(abap_by_stem(), "clas").items()):
        code = _abap.strip_comments(body)
        cls = _abap.global_class(code, name)
        ctor = cls and cls.constructor()
        takes = bool(ctor and re.search(rf"!?\b{inject}\s+TYPE\s+REF\s+TO", ctor.sig, re.I))
        # NOT anchored on the EXPORTING keyword: in a multi-parameter block
        # only the first line carries it.
        exports = bool(re.search(rf"!?\b{exporting}\s+TYPE\s", code, re.I))
        if takes and exports:
            bad.append(Finding(f"{name}: takes {inject.upper()} and exports {exporting.upper()} "
                               f"- a caller can alias the buffer it also gets back", name))
        collectors += takes and not exports
        services += exports and not takes
    return bad, [f"{collectors} collector(s), {services} service(s)"]


_LOOP_OPEN = re.compile(r"(loop at|do\b|while\b|select\b(?!.*\binto table\b))", re.I)
_LOOP_CLOSE = re.compile(r"(endloop|enddo|endwhile|endselect)\b", re.I)


def check_export():
    """A method that exports the buffer last must not be able to leave before it.

    Four entry points of one service and both of another returned early,
    handing the caller an empty table while the reason sat in the buffer.
    The fix is an envelope over a private body, where returning early is
    what a guard is for.

    Method level only: a RETURN or CHECK inside a LOOP is loop control, not
    an exit. A RETURN right after the export statement hands the buffer back
    itself and is fine.
    """
    export = get("messages.buffer.export")
    if not export:
        return needs("[messages.buffer] export")
    export_re = re.compile(rf"^\s*{export}\s*$", re.I)
    bad, scanned = [], 0
    for name, b, lines in _exporting_methods(export_re):
        scanned += 1
        key = f"{name}~{b.name.lower()}"
        bad += [Finding(f"{key} exports the buffer at the end and can leave before it: '{ln}'", key)
                for ln in _early_exits(lines[:-1], export_re)]
    return bad, [f"{scanned} exporting method(s) scanned"]


def _exporting_methods(export_re):
    """(object, method, its code lines) for each method whose last statement
    exports the buffer."""
    for name, body in sorted(abap_by_stem().items()):
        for b in _abap.method_bodies(body):
            lines = [ln.strip() for ln in _abap.strip_comments(b.body).split("\n") if ln.strip()]
            if lines and export_re.match(lines[-1].rstrip(".")):
                yield name, b, lines


def _early_exits(lines, export_re):
    """The RETURN and CHECK lines outside every loop -- inside one they are
    loop control -- but a RETURN right after an export, which hands the
    buffer back itself."""
    depth, prev = 0, ""
    for ln in lines:
        low = ln.lower()
        if _LOOP_OPEN.match(low):
            depth += 1
        elif _LOOP_CLOSE.match(low):
            depth = max(0, depth - 1)
        elif depth == 0 and re.match(r"(return\s*\.|check\b)", low) \
                and not (low.startswith("return") and export_re.match(prev.rstrip("."))):
            yield ln
        prev = ln


CHECKS = [
    ("missing", "every raised number is defined", check_missing),
    ("unraised", "every defined number is raised", check_unraised),
    ("arity", "one operand count per number", check_arity),
    ("placeholder", "text slots match the operands", check_placeholder),
    ("buffer", "a buffer is injected or returned, not both", check_buffer),
    ("export", "no exit above the buffer export", check_export),
]


if __name__ == "__main__":
    exit_with(run(SCRIPT, CHECKS, suppressed, empty=EMPTY))
