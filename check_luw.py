#!/usr/bin/env python3
"""LUW ownership: who may close the database LUW, and who may choose it.

    python3 check_luw.py [commit sync inject] [--file SUBSTR]

WHY THIS EXISTS
---------------
`COMMIT WORK` is not scoped to the object that issues it. It closes the whole
database LUW, so every object able to issue one is an authority over work it
did not write. Every package these checks were written for made the same
rule: the package does not commit, except one unit-of-work class -- the
caller, the framework or the job's unit of work closes the LUW.

WHAT IT CHECKS
--------------
  commit   COMMIT / ROLLBACK WORK or ENTITIES, BAPI_TRANSACTION_COMMIT /
           ROLLBACK, DB_COMMIT -- anywhere but in an owner's main source.
           `COMMIT ENTITIES` counts: it commits implicitly. Convention: on,
           with no owner, until `[luw] owners` names one.
  sync     an object running inside its caller's LUW naming an API that
           commits unless told not to (e.g. SAP_WAPI_CREATE_EVENT on an MDG
           workflow path). Fact: `[luw] synchronous` and `forbidden_on_sync`.
  inject   when the LUW is chosen by whoever assembles the objects -- a
           constructor parameter typed with the package's LUW interface --
           the choice must reach every collaborator. Fact: `[luw.inject]`.

             HIDDEN   a class that builds a LUW-aware class without being
                      LUW-aware itself: it owns a commit authority its own
                      caller cannot reach
             DROPPED  a LUW-aware class building a LUW-aware class without
                      passing its LUW on: the choice stops there
             SPLIT    one method giving its collaborators different LUWs, or
                      one to some and none to others. All-or-none is not a
                      finding: an assembler that passes none chooses the
                      default for all

           Found by reading, not by any tool: a service with no LUW parameter
           defaulted to the committing LUW, was dispatched in a changeset
           whose other two services shared a deferred one, and issued COMMIT
           WORK AND WAIT mid-changeset. Nothing about that is visible at the
           call site; it is visible in what the constructor does NOT have.

LIMITS, STATED RATHER THAN DISCOVERED LATER
-------------------------------------------
  - A commit reached indirectly -- a function module that commits inside, an
    UPDATE TASK -- is invisible beyond the names in `forbidden_on_sync`.
  - `synchronous` is a list, not a reachability analysis.
  - `inject` reads ownership off the constructor signature and constructions
    off `NEW class(`. Two inline `NEW luw( )` in one method compare equal.
"""

import re
from collections import namedtuple

import _abap
from _config import get
from _pkg import EMPTY, abap_by_stem, abap_files, include, kind, of_kind, stem
from _runner import Finding, exit_with, needs, run, suppressions

SCRIPT = "luw"
suppressed = suppressions(SCRIPT)

OWNERS = {o.lower() for o in get("luw.owners", [])}
# What an owner may issue: the LUW statements and the BAPI wrappers of them.
# COMMIT ENTITIES and DB_COMMIT stay findings even there: one belongs to RAP,
# the other commits the database connection without the update task.
LUW_MAY = re.compile(r"^((COMMIT|ROLLBACK)\s+WORK(\s+AND\s+WAIT)?"
                     r"|'BAPI_TRANSACTION_(COMMIT|ROLLBACK)')$", re.I)

# One re.I for the whole pattern. An inline `(?i)` repeated per alternative is
# a global flag not at position 0, which Python 3.11+ rejects outright.
COMMIT = re.compile(r"\b(COMMIT|ROLLBACK)\s+(WORK|ENTITIES)\b(\s+AND\s+WAIT)?"
                    r"|'BAPI_TRANSACTION_(COMMIT|ROLLBACK)'"
                    r"|\bDB_COMMIT\b", re.I)


def _line(text, pos):
    return text.count("\n", 0, pos) + 1


def check_commit():
    """Nobody commits but the owners, in their own main source."""
    bad, files = [], abap_files()
    for path, raw in files.items():
        obj = stem(path)
        code = _abap.strip_comments(raw)
        for m in COMMIT.finditer(code):
            if obj in OWNERS and kind(path) == "clas" and include(path) == "main" \
                    and LUW_MAY.match(" ".join(m.group(0).split())):
                continue
            key = f"{path}:{_line(code, m.start())}"
            bad.append(Finding(f"{key}  {' '.join(m.group(0).split())}", key))
    owners = ", ".join(sorted(OWNERS)) or "none - the package never commits"
    return bad, [f"owners: {owners}", f"{len(files)} file(s) scanned"]


def check_sync():
    """Objects in a caller's LUW naming an API that commits by default."""
    sync = {s.lower() for s in get("luw.synchronous", [])}
    methods = {k.lower(): {m.lower() for m in v}
               for k, v in get("luw.synchronous_methods", {}).items()}
    forbidden = [f.lower() for f in get("luw.forbidden_on_sync", [])]
    if not forbidden or not (sync or methods):
        return needs("[luw] synchronous (or synchronous_methods) and forbidden_on_sync")
    bad = []
    watched = {p: t for p, t in abap_files().items() if stem(p) in sync or stem(p) in methods}
    for path, raw in watched.items():
        obj = stem(path)
        code = _abap.strip_comments(raw)
        bodies = [(b, b.name.lower().split("~")[-1]) for b in _abap.method_bodies(code)]
        bad += [Finding(f"{path}:{_line(code, b.start)}  {obj.upper()}~{name.upper()} names "
                        f"{api.upper()}, which commits unless told not to", f"{obj}~{name}:{api}")
                for b, name in bodies if obj in sync or name in methods.get(obj, ())
                for api in forbidden if api in b.body.lower()]
    return bad, [f"{len(sync)} synchronous object(s), {len(methods)} by method, "
                 f"{len(forbidden)} API(s) watched"]


_METHOD = re.compile(r"^\s*METHOD\s+([\w~/]+)\s*\.", re.I)


def _takes(code, name, param_re):
    """The class's constructor declares the LUW parameter. Read off the
    constructor only: a method taking a LUW later does not let the class's
    caller choose the one it is built with."""
    cls = _abap.global_class(code, name)
    ctor = cls and cls.constructor()
    return bool(ctor and param_re.search(ctor.sig))


def _constructions(text, built):
    """(lineno, method, class, argument text) for every NEW of a class whose
    name matches BUILT.

    The argument text is scanned with a paren counter rather than a regex:
    such calls nest (`io_msg = _mo_msg`), and a non-greedy `\\(.*?\\)` stops
    at the first inner close -- which reads as "no LUW passed" for a call
    that passes one.
    """
    code = _abap.strip_comments(text)
    new = re.compile(rf"\bNEW\s+({built})\s*\(", re.I)
    lines = code.split("\n")
    starts = {i: m.group(1).lower() for i, ln in enumerate(lines)
              if (m := _METHOD.match(ln))}
    offsets, pos = [], 0
    for ln in lines:
        offsets.append(pos)
        pos += len(ln) + 1
    current = "(definition)"
    for i, ln in enumerate(lines):
        current = starts.get(i, current)
        for m in new.finditer(ln):
            j = offsets[i] + m.end()
            depth, k = 1, j
            while k < len(code) and depth:
                depth += (code[k] == "(") - (code[k] == ")")
                k += 1
            yield i + 1, current, m.group(1).lower(), code[j:k]


def check_inject():
    """The LUW chosen by the assembler reaches every collaborator."""
    iface = get("luw.inject.interface")
    if not iface:
        return needs("[luw.inject] interface")
    param = get("luw.inject.param", "io_luw")
    aware_re = re.compile(rf"\b{param}\s+TYPE\s+REF\s+TO\s+{iface}\b", re.I)
    inject = _Inject(param, get("luw.inject.builds", r"\w+"),
                     re.compile(get("luw.inject.forwarders", r".*"), re.I),
                     {n for n, text in of_kind(abap_by_stem(), "clas").items()
                      if _takes(_abap.strip_comments(text), n, aware_re)})
    # Every file of a class: a local helper building a collaborator is the
    # class building it, and moving the NEW there must not hide it.
    bad = [f for path, text in sorted(abap_files().items()) if kind(path) == "clas"
           for f in _inject_findings(path, text, inject)]
    return bad, [f"{len(inject.aware)} LUW-aware class(es): "
                 f"{', '.join(sorted(inject.aware)) or 'none'}"]


# The [luw.inject] facts, and the classes whose constructor takes the LUW.
_Inject = namedtuple("_Inject", "param built forwarders aware")


def _inject_findings(path, text, inject):
    """HIDDEN and DROPPED for each construction a forwarder in PATH makes,
    SPLIT for each of its methods handing out different LUWs."""
    me, bad, made = stem(path), [], {}
    for lineno, method, cls, args in _constructions(text, inject.built):
        # Consulted here, not by the runner: an excused construction is also
        # left out of the SPLIT comparison below.
        if cls not in inject.aware or suppressed("inject", f"{me}->{cls}"):
            continue
        passed = re.search(rf"\b{inject.param}\s*=\s*([\w>_-]+)", args, re.I)
        made.setdefault(method, []).append((cls, passed.group(1).lower() if passed else None))
        if inject.forwarders.search(me) and include(path) != "testclasses":
            bad += _forwarding(f"{path}:{lineno}", me, cls, passed, inject)
    return bad + [f"SPLIT    {path}  {method}: {_handed_out(given)}"
                  for method, given in made.items() if _split(given)]


def _forwarding(where, me, cls, passed, inject):
    """A forwarder building a LUW-aware class must be LUW-aware and pass its LUW on."""
    if me not in inject.aware:
        return [f"HIDDEN   {where}  {me} builds {cls} but takes no {inject.param.upper()} of its own"]
    if not passed:
        return [f"DROPPED  {where}  {me} builds {cls} without passing {inject.param.upper()} on"]
    return []


def _handed_out(made):
    """`class=luw, ...` for each collaborator a method builds."""
    return ", ".join(f"{cls}={luw or 'none'}" for cls, luw in made)


def _split(made):
    """One method gives its collaborators different LUWs, or some and not others."""
    given = {p for _, p in made if p}
    return len(given) > 1 or (bool(given) and any(not p for _, p in made))


CHECKS = [
    ("commit", "only the owners close the database LUW", check_commit),
    ("sync", "nothing in a caller's LUW calls a committing API", check_sync),
    ("inject", "the assembler's LUW reaches every collaborator", check_inject),
]


if __name__ == "__main__":
    exit_with(run(SCRIPT, CHECKS, suppressed, empty=EMPTY))
