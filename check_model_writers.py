#!/usr/bin/env python3
"""Model-field writer check.

    python3 check_model_writers.py [--struct NAME ...]

For every field of every structure in the package's model interface
(`[model] interface`), find whether anything in the package writes it. A
field the read model exposes and nothing fills is blank in every consumer,
with no error anywhere.

WHY THIS IS A FILE AND NOT A REGEX IN SOMEONE'S SHELL HISTORY
-------------------------------------------------------------
As a throwaway one-liner it was wrong repeatedly, every time reporting a
written field as unwritten: it missed `APPEND ... TO cs_x-tab` (table
fields), `VALUE #( f = ... )` (constructors) and `rs_a-b-c` (nested paths).
All false alarms, which is the direction that gets a check ignored. The fix
is not a better regex; it is enumerating the ways ABAP writes a field ONCE,
in a file that can be corrected when a new one turns up.

WRITE FORMS RECOGNISED
----------------------
  direct        x-field = ...            x-y-field = ...   x-field+3(2) = ...
  clear         CLEAR x-field            CLEAR: a, x-field, b
  table         APPEND ... TO x-field    INSERT ... INTO TABLE x-field
  db            INTO @x-field            INTO (x-a, x-b)
  parameter     IMPORTING p = x-field
  field symbol  <fs>-field = ...         (any field symbol; see LIMITS)
  constructor   VALUE #( field = ... )   VALUE ty_x( field = ... )
  wholesale     x = <expr>               CORRESPONDING #( ) / MOVE-CORRESPONDING

CONFIDENCE, AND WHY IT IS REPORTED SEPARATELY
---------------------------------------------
A false "no writer" wastes a reviewer's time. A false "written" hides the
defect the check exists to find, so the two are not symmetric and are not
collapsed into one verdict:

  WRITTEN    a prefixed write -- x-field, where x is a plausible carrier
  PROBABLE   a constructor or field-symbol write naming the field, with no
             way to prove the target is THIS structure. Real evidence, not
             proof; listed in the notes so nobody treats it as proof.
  UNWRITTEN  no evidence anywhere -- the finding. One with a known reason is
             suppressed, `structure-field`, under
             [suppress.model_writers.unwritten].

LIMITS, STATED RATHER THAN DISCOVERED LATER
-------------------------------------------
  - Field-symbol and constructor writes are matched on the field NAME
    alone. A field called `belnr` is written by any structure's `belnr`, so
    common names lean PROBABLE rather than WRITTEN. That is why the two
    tiers exist.
  - It reads comment lines too. A body sketched as `" cs_doc-x = ...` counts
    as a writer, which is right for "is this designed" and wrong for "does
    this compile". Pair it with the uncited-sketch check, which is what
    distinguishes the two.
  - INCLUDE TYPE members are not expanded.
  - A wholesale write is followed exactly ONE HOP. `rs_item-key =
    is_event-key` marks every key field written without asking whether the
    SOURCE's fields are - so a field nothing fills anywhere still reports
    WRITTEN as long as some structure containing it is copied from a
    variable. A "written" verdict whose only evidence is a container copy is
    worth reading as a question.
  - AN OVERRIDE COUNTS AS THE WRITER, which is the second way a false
    "written" gets through: the one writer may be an adapter-specific path
    that does not run on an ordinary handle, while the base write is
    missing. Reading the WRITERS column and asking "is every writer an
    adapter?" catches it.
  - The tree walk is `_pkg.abap_files`, shared with every check. Layout
    changes go there, not here.
  - Dynamic writes are invisible: a mapper filling a structure through
    ASSIGN COMPONENT names no field anywhere. Such a structure shows up
    wholly UNWRITTEN and the answer is to check the containing assignment,
    not to loosen the patterns.

CONFIG (abapcheck.toml)
  [model] interface     the model interface, e.g. "zif_x_types"
  [model] carrier       regex of a variable that carries a model structure
  [model] dictwriters   [[object, regex with group 1 = field, structure]]:
                        a label dictionary that fills fields through
                        ASSIGN COMPONENT, credited by its static declaration
"""

import re

import _abap
import sys

from _config import _consume, get
from _pkg import abap_by_stem, abap_files, kind, stem
from _runner import Finding, Skip, exit_with, needs, run, suppressions

SCRIPT = "model_writers"
suppressed = suppressions(SCRIPT)

INTERFACE = (get("model.interface") or "").lower()
# `--struct NAME`, repeatable: those structures only. Consumed here so the
# runner does not read NAME as a check.
STRUCTS = [s_.lower() for s_ in _consume(sys.argv, "--struct")]
DICTWRITERS = [tuple(d) for d in get("model.dictwriters", [])]

# Names that plausibly carry a model structure. Anything else prefixing a
# field is some other object and does not count as a write. A carrier
# variable, plus any number of intervening components: the field may sit at
# the end of a PATH, not just one level down -- `rs_state-bank-applied_rules`
# was reported unwritten until this allowed it.
CARRIER = "(?:" + get("model.carrier", r"_?r[st]_\w+|_?c[st]_\w+|_?[il]s_\w+|_?ms_\w+|<[\w]+>") + \
    r")(?:-\w+)*"


def structures(text):
    """{name: [(field, type), ...]}.

    CONSTANTS groups are skipped: `BEGIN OF c_channel` is a constant group,
    not a structure, and its members are values nothing writes. Reporting
    them as unwritten produced 15 false findings on the first full run.
    """
    out, stack = {}, []
    # TYPES statements only, chains expanded by the lexer: `TYPES: BEGIN OF
    # x,` and `TYPES BEGIN OF x.` with an INCLUDE after it alike (a chained
    # form once read nothing, an unchained one was once never scanned), two
    # members on one line both. A CONSTANTS group is no TYPES statement.
    for _, part in _abap.chain_parts(text, "TYPES"):
        if m := re.match(r"(?i)BEGIN\s+OF\s+(\w+)", part):
            stack.append((m.group(1), []))
        elif re.match(r"(?i)END\s+OF\b", part) and stack:
            name, fields = stack.pop()
            out[name] = fields
            if stack:                          # nested: also a field of the parent
                stack[-1][1].append((name, name))
        elif stack and (m := re.match(r"(\w+)\s+TYPE\s+(?:REF TO\s+)?([\w=>]+)", part, re.I)):
            stack[-1][1].append((m.group(1), m.group(2)))
    return out


def paths_to(target, types):
    """Every `parent-child-...` path that reaches structure TARGET.

    A field is written when its own name is written OR when any structure
    CONTAINING it is assigned wholesale - `rs_doc-legal = ...` writes every
    field of MTY_LEGAL without naming one of them. Missing this reported all
    of MTY_LEGAL_AR/CO/PE as unwritten.
    """
    out = []
    for parent, fields in types.items():
        for fname, ftype in fields:
            if ftype.split("=>")[-1].lower() == target:
                out.append(fname)
                out += [f"{p}-{fname}" for p in paths_to(parent, types)]
    return out


def sources():
    """Every ABAP file except the model interface itself."""
    return {k: v for k, v in abap_files().items()
            if not (kind(k) == "intf" and stem(k) == INTERFACE.lower())}


def dict_written():
    """{(structure, field): object} for every TABLE-DRIVEN write.

    A label dictionary names the model fields it fills and something else
    assigns them through ASSIGN COMPONENT, so no `x-field =` exists anywhere
    and every such field reads UNWRITTEN. The declaration that DRIVES the
    dynamic write is still static, and reading it is not the same as
    loosening the write patterns above: the object, the pattern and the
    structure it fills all come from _pkg, one entry per package, so an
    object a package does not have credits nothing instead of matching
    everything.

    LIMIT: this credits the field NAME, not the assignment. It says a
    dictionary claims the field, which is what decides whether the field is
    filled at all; whether the value beside it is right is not a question a
    static check can answer.
    """
    out = {}
    if not DICTWRITERS:
        return out
    by_stem = abap_by_stem()
    for obj, pattern, struct in DICTWRITERS:
        for f in re.findall(pattern, by_stem.get(obj, ""), re.I):
            out[(struct.lower(), f.lower())] = obj
    return out


def verdict(field, src, container_paths=()):
    """('WRITTEN'|'PROBABLE'|'UNWRITTEN', [files])."""
    f = re.escape(field)

    # Wholesale: the whole containing structure assigned in one statement.
    #
    # ONLY FROM A VARIABLE, never from a call. `rs_doc-totals =
    # build_totals( ... )` is a wholesale assignment whose SOURCE may leave
    # fields unset - and treating it as a write hid six confirmed findings
    # on the first run, which is the failure direction that matters. When
    # the source is a method, the fields it does fill are already caught by
    # the direct scan below (`rs_totals-currency =` inside that method), so
    # nothing is lost by excluding calls here.
    for path in container_paths:
        pat = (rf"{CARRIER}-{re.escape(path)}\s*=\s*(?![^.\n]*\()"
               rf"|MOVE-CORRESPONDING[^.]*?TO\s+{CARRIER}-{re.escape(path)}\b")
        hits = [n for n, s in src.items() if re.search(pat, s, re.M)]
        if hits:
            return "WRITTEN", hits
    definite = [
        rf"{CARRIER}-{f}\b[\w-]*(?:\+\d+\(\d+\))?\s*=",          # direct
        rf"CLEAR:?\s*(?:[^.]*?,\s*)?{CARRIER}-{f}\b",            # clear
        rf"(?:APPEND|INSERT)[^.]*?\b(?:TO|INTO TABLE)\s+{CARRIER}-{f}\b",
        rf"INTO\s+\(?\s*@?{CARRIER}-{f}\b",                      # SELECT ... INTO
        rf"=\s*{CARRIER}-{f}\b\s*\)?\s*\.$",                     # IMPORTING p = x-f
        rf"IMPORTING[^.]*?=\s*{CARRIER}-{f}\b",
    ]
    probable = [
        rf"VALUE\s+[\w#]*\(\s*(?:[^()]|\([^()]*\))*?\b{f}\s*=",  # constructor
        rf"<\w+>-{f}\b\s*=",                                     # field symbol
        rf"\b{f}\s*=\s*\w",                                      # bare, in a VALUE list
    ]
    hits = [n for n, s in src.items()
            if any(re.search(p, s, re.M) for p in definite)]
    if hits:
        return "WRITTEN", hits
    hits = [n for n, s in src.items()
            if any(re.search(p, s, re.M | re.S) for p in probable)]
    if hits:
        return "PROBABLE", hits
    return "UNWRITTEN", []


def check_unwritten():
    if not INTERFACE:
        return needs("[model] interface")
    src_all = abap_by_stem()
    if INTERFACE not in src_all:
        return Skip(f"{INTERFACE} is not on disk")
    types = {k.lower(): v for k, v in structures(src_all[INTERFACE]).items()}
    wanted = STRUCTS or sorted(types)
    src, dicts = sources(), dict_written()
    bad, verdicts = [], []
    for name in wanted:
        if name not in types:
            bad.append(f"unknown structure {name}")
            continue
        found = [(f"{name}-{f.lower()}", v, where) for f, v, where in _verdicts(name, types, src, dicts)]
        bad += [Finding(f"{key}: nothing writes it", key) for key, v, _ in found if v == "UNWRITTEN"]
        verdicts += found
    probable = [f"{key} [{', '.join(sorted(where)[:2])}]" for key, v, where in verdicts if v == "PROBABLE"]
    notes = [f"{len(wanted)} structure(s), {len(verdicts)} field(s) in {INTERFACE}"]
    if probable:
        notes.append(f"PROBABLE, by field name only: {'; '.join(probable)}")
    return bad, notes


def _verdicts(name, types, src, dicts):
    """(field, verdict, writers) for each field of structure NAME; a field a
    label dictionary fills is written."""
    containers = paths_to(name, types)
    for f, _ in types[name]:
        v, where = verdict(f, src, containers)
        yield f, "WRITTEN" if v == "UNWRITTEN" and (name, f.lower()) in dicts else v, where


CHECKS = [("unwritten", "every model field has a writer", check_unwritten)]


if __name__ == "__main__":
    from _pkg import EMPTY
    exit_with(run(SCRIPT, CHECKS, suppressed, empty=EMPTY))
