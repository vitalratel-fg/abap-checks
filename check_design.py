#!/usr/bin/env python3
"""Design agreements, executable: what a package's design states in prose
and nothing else enforces.

    python3 check_design.py                  # every check
    python3 check_design.py owners register  # named checks only
    python3 check_design.py --list

Exit code is the number of unsuppressed findings, so it is usable in a hook.

WHY APART FROM check_standing.py
--------------------------------
These are agreements rather than syntax: one table, one owning class; every
column read and every stored value assigned; a report's event blocks only
declare, construct and call; the object register and the objects on disk are
the same set. They drift because they are agreements, and they are the ones
that change when a design does.

CONFIG (abapcheck.toml)
  [register] file           the document naming every object (`register`)
  [register] names          regex, group 1 = a name; default: backticked
                            names matching [package] own
  [register] planned_ignore regex of register names never built (enhancements)
  [[register.subset]]       another document whose list must reach the
                            register: file, section (heading regex), names
"""

import re
from pathlib import Path

import _abap
from _config import BASE, ROOT, get, path, regex
from _pkg import DEVC, OWN, abap_by_stem, apps, cds_files, ddic, is_value_set, of_kind, packages
from _runner import Finding, exit_with, needs, run, suppressions

SCRIPT = "design"
suppressed = suppressions(SCRIPT)

SRC = abap_by_stem()


def _sql_touch(table):
    """SQL against one table -- not a TYPE reference to it.

    `IMPORTING is_row TYPE zt_outbox` and `TYPES lty TYPE STANDARD TABLE OF
    zt_act` name a table without touching it, and counting those made every
    consumer an owner.
    """
    return re.compile(
        rf"(?i)\b(?:SELECT\b[^.]*?\b(?:FROM|JOIN)\s+{table}\b"
        rf"|INSERT\s+(?:INTO\s+)?{table}\b"
        rf"|UPDATE\s+{table}\b"
        rf"|MODIFY\s+{table}\b"
        rf"|DELETE\s+FROM\s+{table}\b)")


def check_owners():
    """Every table of the package is touched by exactly one object.

    Written when a rule held for one table only and every other table was on
    trust, and an outbox table quietly acquired two owners -- the facade
    wrote intents, the processor updated their status -- with the
    idempotency key in one class and the status transitions in the other.

    Two owners means the table's invariants are known in two places and can
    be violated by calling one without the other. A CDS view over the table
    is how everyone else reads it, and is not an owner.
    """
    bad, notes = [], []
    for table in sorted(ddic("tabl")):
        pattern = _sql_touch(table)
        owners = sorted(n for n, text in SRC.items()
                        if pattern.search(_abap.strip_comments(text)))
        # Consulted here, not by the runner: an excused owner is no owner, and
        # the count of owners is the finding.
        owners = [o for o in owners if not suppressed("owners", f"{table}:{o}")]
        if len(owners) > 1:
            bad.append(f"{table} is written or read by {', '.join(owners)} - "
                       f"one table, one owner")
        elif owners:
            notes.append(f"{table}: {owners[0]}")
    return bad, notes


def _clause(stmt, start, stops):
    """The text of one clause: from keyword START up to the first of STOPS."""
    m = re.search(rf"(?is)\b{start}\b(.*)", stmt)
    if not m:
        return ""
    body = m.group(1)
    cut = [x.start() for x in (re.search(rf"(?i)\b{s}\b", body) for s in stops) if x]
    return body[:min(cut)] if cut else body


def check_columns():
    """A table column nothing reads, or an application column nothing writes.

    A check by field NAME across structures missed three columns the only
    writer never filled, because a policy filled fields of that name in
    another structure, and a SELECT of an always-blank column counted as a
    write. This check reads the SQL.

      written   an INSERT / MODIFY names it in its VALUE, an UPDATE in its
                SET, or the statement writes a whole work area. Required of
                delivery class A only: C tables are maintained in SM30.
      read      a WHERE / ORDER BY / GROUP BY on the table names it, a
                SELECT fetches it (or `*`) and `-column` appears in the
                source, or a CDS view selecting from the table names it
                through its alias. By name, so a column shares credit with
                any field of the same name - it can miss a dead column, not
                invent one.

    A table no statement reads is ONE finding, not one per column.
    """
    bad = []
    stmts = [s for _, text in sorted(SRC.items()) for _, s in _abap.statements(text)]
    views = cds_files("ddls").values()
    checked = 0
    for table, root in sorted(ddic("tabl").items()):
        cols = [f.findtext("FIELDNAME").lower() for f in root.iter("DD03P")
                if f.findtext("FIELDNAME") and f.findtext("FIELDNAME") != "MANDT"
                and not f.findtext("FIELDNAME").startswith(".")]
        appl = (root.findtext(".//DD02V/CONTFLAG") or "") == "A"
        written, read, fetched, reader = _sql_use(table, cols, stmts)
        read |= fetched & _dashed(table, stmts)
        cds_read, cds_reader = _cds_use(table, cols, views)
        checked += len(cols)
        bad += _column_findings(table, cols, appl, written, read | cds_read, reader or cds_reader)
    return bad, [f"{checked} column(s) across {len(ddic('tabl'))} table(s)"]


def _named(cols, text, form=r"\b{c}\b"):
    """The columns COLS that TEXT names in FORM, ignoring case."""
    return {c for c in cols if re.search("(?i)" + form.format(c=c), text)}


def _sql_use(table, cols, stmts):
    """(written, read, fetched, reader): what the package's SQL does with one
    table's columns, and whether any statement reads the table."""
    written, read, fetched, reader = set(), set(), set(), False
    for s in stmts:
        if re.match(rf"(?i)(INSERT|MODIFY)\s+(?:INTO\s+)?{table}\b", s):
            whole = re.search(r"(?i)\bFROM\s+(TABLE\s+)?@(?!\()", s)
            written |= set(cols) if whole else _named(cols, s, r"\b{c}\s*=")
        elif re.match(rf"(?i)UPDATE\s+{table}\b", s):
            written |= _named(cols, _clause(s, "SET", ["WHERE"]), r"\b{c}\s*=")
            read |= _named(cols, _clause(s, "WHERE", []))
        elif _reads_from(s, table):
            reader = True
            read |= _filtered(cols, s)
            fetched |= _fetched(cols, s)
        elif (join := re.search(rf"(?i)\bSELECT\b.*\bJOIN\s+{table}\b(?:\s+AS\s+(\w+))?",
                                s, re.S)):
            # A joined table is read through its alias: `t~werks` in the
            # ON, WHERE or field list.
            reader = True
            read |= _named(cols, s, rf"\b{join.group(1) or table}~{{c}}\b")
    return written, read, fetched, reader


def _reads_from(stmt, table):
    """A SELECT or DELETE whose FROM is the table."""
    return bool(re.search(rf"(?i)\bSELECT\b.*\bFROM\s+{table}\b", stmt, re.S)
                or re.match(rf"(?i)DELETE\s+FROM\s+{table}\b", stmt))


def _filtered(cols, stmt):
    """The columns a WHERE, ORDER BY or GROUP BY of STMT names."""
    stops = ["ORDER BY", "GROUP BY", "INTO", "WHERE", "UP TO"]
    return set().union(*(_named(cols, _clause(stmt, kw, stops))
                         for kw in ("WHERE", "ORDER BY", "GROUP BY")))


def _fetched(cols, stmt):
    """The columns STMT's field list fetches: every one for `*`."""
    field_list = _clause(stmt, "SELECT", ["FROM"]) + \
        _clause(stmt, "FIELDS", ["WHERE", "INTO", "ORDER BY"])
    return set(cols) if "*" in field_list else _named(cols, field_list)


def _dashed(table, stmts):
    """Every `-name` in the source, outside the table's own writes.

    `-column` inside the table's own write is the value going IN - the
    source of an INSERT - and crediting it as a read hid a column.
    """
    writes_here = re.compile(rf"(?i)(INSERT|MODIFY|UPDATE)\s+(?:INTO\s+)?{table}\b")
    return {m.lower() for s in stmts if not writes_here.match(s)
            for m in re.findall(r"-([a-z_][a-z0-9_]*)\b", s, re.I)}


def _cds_use(table, cols, views):
    """(read, reader) of one table's columns by the CDS views selecting from it."""
    read, reader = set(), False
    for cds in views:
        for m in re.finditer(rf"(?i)\b(?:from|join)\s+{table}\b(?:\s+as\s+(\w+))?", cds):
            reader = True
            read |= _named(cols, cds, rf"\b{m.group(1) or table}\.{{c}}\b")
    return read, reader


def _column_findings(table, cols, appl, written, read, reader):
    bad = []
    if not reader:
        bad.append(Finding(f"{table}: no statement reads the table", f"{table}:unread"))
    for c in cols:
        if reader and c not in read:
            bad.append(Finding(f"{table}.{c}: nothing reads it", f"{table}.{c}:unread"))
        if appl and c not in written:
            bad.append(Finding(f"{table}.{c}: nothing writes it", f"{table}.{c}:unwritten"))
    return bad


_BEFORE_VALUE = re.compile(r"(?i)(<>|<=|>=|=|<|>|\bNE\b|\bEQ\b|\bLT\b|\bGT\b|\bLE\b"
                           r"|\bGE\b|\bWHEN\b|\bTHEN\b|\bELSE\b)\s*$")
_CONTEXT_KW = re.compile(r"(?i)\b(WHERE|SET|IF|ELSEIF|CHECK|WHILE|XSDBOOL|BOOLC"
                         r"|WHEN|THEN|ELSE|KEY|VALUE)\b")


def _assigns(stmt, start):
    """Whether the constant at START is assigned, rather than compared against."""
    before = stmt[:start].rstrip().rstrip("@").rstrip()
    if before.count("[") > before.count("]"):
        return False
    op = _BEFORE_VALUE.search(before)
    if not op:
        return True
    op = op.group(1).upper()
    if op in ("THEN", "ELSE"):
        return True
    if op not in ("=", "EQ"):
        return False
    context = _CONTEXT_KW.findall(before)
    return not context or context[-1].upper() in ("SET", "THEN", "ELSE", "VALUE")


def check_values():
    """A fixed value an application table can hold, and nothing assigns.

    `deadconst` exempts a domain-backed constant group, because there the
    domain is the contract. That exemption also hid a value nobody produces:
    a gate status CANCELLED was named only in a WHERE that excluded it,
    while the one cancellation path closed the handle as CLOSED. A value that
    is only ever compared against is a branch for a state that cannot occur.

      scope     a value set whose data element types a column of a delivery
                class A table. A class C table is maintained in SM30, so its
                values arrive from outside the code by design.
      assigns   the member appears after `=` in a VALUE, a SET or a parameter
                binding, after THEN or ELSE, or as a positional argument. After
                `=` in a WHERE, IF, CHECK, xsdbool( ), WHEN or WITH KEY, after
                a comparison operator or after a CASE / SWITCH WHEN, it is
                compared against.

    LIMITS: lexical. A constant bound to a parameter inside an IF condition
    counts as compared.
    """
    stmts = [s for _, text in sorted(SRC.items()) for _, s in _abap.statements(text)]
    bad, checked, skipped = [], [], []
    for grp, members, doma, held_in in _value_groups():
        if not held_in:
            skipped.append(grp)
            continue
        checked.append(grp)
        bad += _value_findings(grp, members, doma, held_in, stmts)
    return bad, [f"checked, held in application tables: {checked or 'none'}",
                 f"skipped, not held in an application table: {skipped or 'none'}"]


def _value_groups():
    """(group, members, domain, application tables holding it) for every
    constant group typed by a data element whose domain has fixed values."""
    dtels, domas, tabls = ddic("dtel"), ddic("doma"), ddic("tabl")
    for _name, text in sorted(SRC.items()):
        for grp, block in _abap.constant_groups(_abap.strip_comments(text)):
            members = _abap.constant_members(block)
            if not members or not is_value_set(members[0][1], dtels, domas):
                continue
            dtel = members[0][1].split("=>")[-1].lower()
            held_in = sorted(
                t for t, root in tabls.items()
                if (root.findtext(".//DD02V/CONTFLAG") or "") == "A"
                and any((f.findtext("ROLLNAME") or "").lower() == dtel
                        for f in root.iter("DD03P")))
            yield grp, members, domas[dtels[dtel].findtext(".//DOMNAME").lower()], held_in


def _value_findings(grp, members, doma, held_in, stmts):
    """A finding for each fixed value of DOMA that no member of GRP is assigned."""
    by_value = {value.upper(): mem for mem, _typ, value in members}
    bad = []
    for value in [e.text.upper() for e in doma.iter("DOMVALUE_L") if e.text]:
        why = _unassigned(grp, by_value.get(value), stmts)
        if why:
            bad.append(Finding(f"{grp}: {', '.join(held_in)} can hold {value}, and {why}",
                               f"{grp}:{value}"))
    return bad


def _unassigned(grp, mem, stmts):
    """Why member MEM of GRP is never assigned, or None when something assigns it."""
    if not mem:
        return "no member of the group carries it"
    token = re.compile(rf"(?i)(?:\w+=>)?\b{grp}-{mem}\b")
    uses = [_assigns(s, m.start()) for s in stmts for m in token.finditer(s)]
    if any(uses):
        return None
    return "nothing names it" if not uses else "nothing assigns it - it is only compared against"


_EVENT = re.compile(r"(?i)^(START-OF-SELECTION|END-OF-SELECTION|INITIALIZATION"
                    r"|AT\s+SELECTION-SCREEN|TOP-OF-PAGE|AT\s+LINE-SELECTION"
                    r"|AT\s+USER-COMMAND|LOAD-OF-PROGRAM)\b")
_LEAVES_EVENT = re.compile(r"(?i)^(CLASS|ENDCLASS|FORM|ENDFORM|MODULE|ENDMODULE)\b")
_LOGIC = re.compile(r"(?i)^(IF|LOOP|CASE|WHILE|DO|TRY)\b|^SELECT\b(?!-)")


def check_eventblocks():
    """A report event block declares, constructs and calls -- nothing else.

    Control flow at that level is logic, and logic belongs in a class where it
    can be named, tested and reached by every other check here. Three of four
    reports in one package drifted into it without anyone noticing: one was
    seven lines and correct, one put fifty-eight in one block, one a hundred
    and twelve.

    NOT a line-count threshold. A threshold is arbitrary, gets argued about,
    and says nothing about why. `IF` at the top level of START-OF-SELECTION is
    wrong at four lines and at four hundred, because the alternative -- a
    constructor parameter and a guarded method -- is better at both.

    Known exception: AT SELECTION-SCREEN validation legitimately needs an IF.
    The first should take a suppression, `program:event`, with a reason
    rather than weaken the rule.
    """
    programs = sorted(of_kind(SRC, "prog"))
    bad = [Finding(f"{name}:{n} {stmt.split()[0].upper()} inside {event}"
                   f" - an event block declares, constructs and calls", f"{name}:{event}")
           for name in programs for n, stmt, event in _logic_in_events(SRC[name])]
    return sorted(set(bad)), [f"{len(programs)} program(s) scanned"]


def _logic_in_events(text):
    """(line, statement, event) for each logic statement inside an event block;
    a CLASS, FORM or MODULE ends the block it follows."""
    event = ""
    for n, stmt in _abap.statements(text):
        if _EVENT.match(stmt):
            event = stmt
        elif _LEAVES_EVENT.match(stmt):
            event = ""
        elif event and _LOGIC.match(stmt):
            yield n, stmt, event


def _on_disk():
    """Every object on disk under ROOT, by name: the first dotted part of
    every serialised file, every package, every UI app."""
    # `<name>.<type>.<ext>`: two dots at least. A README beside the source
    # is not an object.
    names = {p.name.split(".")[0].lower() for p in ROOT.rglob("*.*.*")
             if p.is_file() and p.name != "package.devc.xml"} if ROOT.is_dir() else set()
    return names | packages() | set(apps())


def _names(text, pattern):
    return {m.group(1).lower() for m in re.finditer(pattern, text, re.I | re.M)}


def check_register():
    """The object register and the objects on disk are the same set.

    A convention document that nobody can fail is a convention nobody keeps.

    IT COMPARES LISTS, NOT COUNTS, and that is the point. A number in prose
    has no owner: one README said an interface had five methods while its
    plan said four, and nothing could say which was wrong. A list IS its own
    count, and this check reads the list.

    The reverse difference -- named, not built yet -- is a note, not a
    finding: a register legitimately names what a later step builds. NAMED,
    not counted: a count hid a stale entry left over from a rename among the
    objects a later step builds.
    """
    reg_path = path("register.file")
    if not reg_path:
        return needs("[register] file")
    if not reg_path.is_file():
        return [f"{reg_path.name} not found"], []
    pattern = get("register.names") or (rf"`({OWN})`" if OWN else None)
    if not pattern:
        return needs("[register] names, or [package] own")
    listed = _names(reg_path.read_text(), pattern)
    if DEVC:
        listed |= _names(reg_path.read_text(), rf"`({re.escape(DEVC)})`")

    on_disk = _on_disk()
    bad = [Finding(f"on disk, not in the object register: {n}", n)
           for n in sorted(on_disk - listed)]
    notes = [f"{len(on_disk)} object(s) on disk, {len(listed)} in the register"]

    for sub in get("register.subset", []):
        sub_bad, sub_note = _subset(sub, listed, on_disk)
        bad += sub_bad
        notes += sub_note

    ignore = regex("register.planned_ignore")
    planned = sorted(n for n in listed - on_disk if not (ignore and ignore.search(n)))
    notes.append(f"{len(planned)} named but not built yet: "
                 + (", ".join(n.upper() for n in planned) or "none"))
    return bad, notes


def _subset(sub, listed, on_disk):
    """([findings], [note]) for one [[register.subset]]: its section is found,
    and every name it lists is in the register."""
    f = (BASE / sub["file"]).resolve()
    text = f.read_text() if f.is_file() else ""
    sec = re.search(rf"{sub['section']}(.*?)(?=^#{{1,2}} |\Z)", text, re.S | re.M) if text else None
    label = sub.get("label", Path(sub["file"]).name)
    if not sec:
        return [f"{label}: section /{sub['section']}/ not found in {sub['file']}"], []
    named = _names(sec.group(1), sub["names"])
    return ([f"{label} names {n}, the object register does not" for n in sorted(named - listed)],
            [f"{label}: {len(named)} name(s), {len(named & on_disk)} built"])


CHECKS = [
    ("owners", "one table, one owning object", check_owners),
    ("columns", "column read, and written if application data", check_columns),
    ("values", "application value nothing assigns", check_values),
    ("eventblocks", "report event block declares, constructs and calls", check_eventblocks),
    ("register", "object register vs objects on disk", check_register),
]

SOURCE_ONLY = {"owners", "columns", "values", "eventblocks"}


if __name__ == "__main__":
    from _pkg import EMPTY
    exit_with(run(SCRIPT, CHECKS, suppressed, empty=EMPTY, source_only=SOURCE_ONLY))
