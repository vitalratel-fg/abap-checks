#!/usr/bin/env python3
"""Keyed-row check  --  writing through a row its table protects.

WHY THIS EXISTS
---------------
The key fields of a SORTED or HASHED table's row are read-only through any
field symbol or reference onto that row, because changing one would move
the row out of its slot. The runtime enforces this at the WRITE, and a
whole-row CHANGING binding counts as one: the formal parameter would be a
writable alias of the key, so the call itself raises
MOVE_TO_LIT_NOTALLOWED_NODATA, naming the row's first component, before
the callee has run a line.

Five call sites in four classes of one package had that shape. They
read like every other `CHANGING cs_item = <ls_item>` in the package -- the
defect is in the type of a table declared somewhere else, which no reader
holds in mind at the call. One was found by a short dump; the other four
by a search written afterwards.

The same search found the second form of the defect: a table declared
`FINAL(lt_items) = ...` and then written through `<ls_row>`. An immutable
table's rows are all read-only, keys or not.

WHAT IT CHECKS
--------------
  keyed table   a SORTED or HASHED table: a TYPES declaration, a TYPES alias
                of one, or a DATA declared with one inline. Its primary key
                is read from the declaration; DEFAULT KEY and TABLE_LINE
                make every component key.
  row handle    `ASSIGN t[ ... ] TO`, or `LOOP AT t` / `READ TABLE t` with
                ASSIGNING or REFERENCE INTO, where t is keyed or FINAL

  BIND    a handle bound WHOLE to CHANGING / IMPORTING / RECEIVING -- the
          caller's side, where IMPORTING is an output
  KEY     a key component written through a handle or a table expression:
          assigned, CLEARed, read INTO, or bound to an output parameter
  ROW     the whole row overwritten: `<fs> =`, `CLEAR <fs>`,
          MOVE-CORRESPONDING ... TO <fs>, `t[ ... ] =`
  TABLE   APPEND or SORT on a keyed table, or an INDEX write into one --
          legal only while the key order happens to survive
  FINAL   any write to a variable declared FINAL( ), or to any component
          of it, directly or through a handle onto one of its rows

WHAT IS NOT A FINDING
---------------------
  writing a NON-key component through a handle            - legal
  passing a handle whole to EXPORTING (an input)           - read-only
  `MODIFY TABLE t FROM wa`, INSERT ... INTO TABLE          - by key, legal

LIMITS, STATED RATHER THAN DISCOVERED LATER
-------------------------------------------
  - Variables are resolved by name within one method: its locals, its
    parameters, and the attributes of its class. A parameter is looked up
    by method name across the package, so two methods of one name with
    differently typed parameters merge.
  - Only the forms above make a handle. A row reached through a chain of
    calls, `REF #( t[ ... ] )`, a generic `TYPE data` parameter or `LIKE`
    is invisible.
  - Duplicate keys are NOT checked: whether a `SELECT ... INTO TABLE` or
    an unchecked INSERT can collide depends on the data, which a check
    cannot see.
  - Its first version found NOTHING in the baseline: the type pattern
    read `zif_x_types=>mty_item_db` as `zif_x_types`,
    and IMPORTING (an output at a call site) was treated as an input.
    Both are why the counts below are printed -- a check that tracks zero
    tables prints the same "0 findings" as one that tracks them all.

Usage:  python3 check_sorted_rows.py [--file SUBSTR]
Suppress `file:line RULE` under [suppress.sorted_rows.keyedrows].
"""

import re

from _abap import class_definitions, declarations, method_bodies, split_chain, statements, strip_comments
from _pkg import EMPTY, FILTER, package_abap
from _runner import Finding, exit_with, run, suppressions

SCRIPT = "sorted_rows"
suppressed = suppressions(SCRIPT)

I = re.I

OUT_KEYWORDS = ("CHANGING", "IMPORTING", "RECEIVING")
_PARAM_KW = re.compile(r"\b(EXPORTING|IMPORTING|CHANGING|RECEIVING|EXCEPTIONS)\b", I)
_DECL_HEAD = re.compile(r"^(TYPES|DATA|CLASS-DATA|STATICS)\b\s*:?\s*", I)
_KEYED_DECL = re.compile(
    r"^(\w+)\s+TYPE\s+(?:SORTED|HASHED)\s+TABLE\s+OF\s+(?:REF\s+TO\s+)?[\w=>/~-]+"
    r"\s+WITH\s+(?:UNIQUE\s+|NON-UNIQUE\s+)?(DEFAULT\s+KEY|KEY\s+(.*))$", I)
_TYPED = re.compile(r"(?:^|[\s(!,:])!?(\w+)\s+TYPE\s+(?:\w+=>)?(\w+)\b(?!\s*=>)", I)
_RETURNING = re.compile(r"RETURNING\s+VALUE\((\w+)\)\s+TYPE\s+(?:\w+=>)?(\w+)", I)
_INLINE_CALL = re.compile(r"\b(?:DATA|FINAL)\((\w+)\)\s*=\s*[\w>~=-]*?(\w+)\(", I)
_FINAL = re.compile(r"\bFINAL\((\w+)\)", I)

_HANDLE_FORMS = (
    re.compile(r"^ASSIGN\s+(\w+)\[.*\]\s+TO\s+(?:FIELD-SYMBOL\()?(<\w+>)", I),
    re.compile(r"^(?:LOOP\s+AT|READ\s+TABLE)\s+(\w+)\b.*?\b"
               r"(?:ASSIGNING\s+(?:FIELD-SYMBOL\()?(<\w+>)"
               r"|REFERENCE\s+INTO\s+(?:DATA\()?(\w+))", I),
)
_KEY_STOP = re.compile(r"\b(WITH|INITIAL|VALUE|READ-ONLY)\b", I)


def _key_of(match):
    """Key components from a _KEYED_DECL match; ['*'] means every one."""
    if match.group(2).upper().startswith("DEFAULT"):
        return ["*"]
    rest = _KEY_STOP.split(match.group(3))[0]
    words = re.findall(r"\w+", rest)
    if len(words) >= 2 and words[1].upper() == "COMPONENTS":
        words = words[2:]
    words = [w.lower() for w in words]
    return ["*"] if not words or "table_line" in words else words


def _decl_members(stmt):
    """(keyword, member) for each member of a TYPES/DATA statement."""
    head = _DECL_HEAD.match(stmt)
    if not head:
        return []
    return [(head.group(1).upper(), m) for m in map(str.strip, split_chain(stmt[head.end():]))]


def keyed_types(corpus):
    """{type name: key components} package-wide, aliases followed."""
    members = [(kw, member) for text in corpus.values() for _, stmt in statements(text)
               for kw, member in _decl_members(stmt) if kw == "TYPES"]
    types = {m.group(1).lower(): _key_of(m) for _, member in members
             if (m := _KEYED_DECL.match(member))}
    aliases = [(m.group(1).lower(), m.group(2).lower()) for _, member in members
               if (m := _TYPE_ALIAS.match(member))]
    grew = True
    while grew:                    # TYPES b TYPE a, where a is keyed
        grew = False
        for alias, base in aliases:
            if base in types and alias not in types:
                types[alias], grew = types[base], True
    return types


_TYPE_ALIAS = re.compile(r"^(\w+)\s+TYPE\s+(?:\w+=>)?(\w+)$", I)


def _typed_names(text, types):
    """{name: key} for every `name TYPE keyed` and inline-keyed DATA in text."""
    found = {}
    for _, stmt in statements(text):
        found.update(_typed_in(stmt, types))
    return found


def _typed_in(stmt, types):
    """{name: key} STMT declares: an inline-keyed DATA, then every `name TYPE
    keyed` outside a TYPES statement."""
    found = {m.group(1).lower(): _key_of(m) for kw, member in _decl_members(stmt)
             if kw != "TYPES" and (m := _KEYED_DECL.match(member))}
    if not (_DECL_HEAD.match(stmt) and stmt.upper().startswith("TYPES")):
        found.update({m.group(1).lower(): types[m.group(2).lower()]
                      for m in _TYPED.finditer(stmt) if m.group(2).lower() in types})
    return found


def signatures(corpus, types):
    """{method name: ({param: key}, returned key or None)} package-wide."""
    sigs = {}
    for d in (d for text in corpus.values() for d in declarations(strip_comments(text))):
        params, ret = sigs.setdefault(d.name.lower(), ({}, set()))
        params.update({m.group(1).lower(): types[m.group(2).lower()]
                       for m in _TYPED.finditer(d.sig) if m.group(2).lower() in types})
        r = _RETURNING.search(d.sig)
        ret.update(types.get(r.group(2).lower(), ()) if r else ())
    return sigs


def _preceding_keyword(stmt, pos):
    kws = _PARAM_KW.findall(stmt[:pos])
    return kws[-1].upper() if kws else None


def _is_output_bind(stmt, operand):
    """Positions where `= operand` sits in an output parameter list."""
    hits = []
    for m in re.finditer(r"=\s*" + operand, stmt, I):
        if _preceding_keyword(stmt, m.start()) in OUT_KEYWORDS:
            hits.append(m)
    return hits


def _writes_operand(stmt, operand):
    """(how, the operand as written) when the statement overwrites it, else
    (None, None): assigned, CLEARed, a MOVE-CORRESPONDING or INTO target,
    or bound to an output parameter."""
    op = "(?P<op>" + operand + ")"
    m = re.match(op + r"\s*(?:[-+*/]?=)(?!=)", stmt, I)
    if m:
        return "assigned", m.group("op")
    clear = re.match(r"(?:CLEAR|FREE)\b\s*:?\s*(.*)", stmt, I)
    m = clear and re.search(r"(?:^|,)\s*" + op + r"\s*(?:,|$|WITH\b)", clear.group(1), I)
    if m:
        return "cleared", m.group("op")
    m = re.search(r"\bMOVE-CORRESPONDING\b.*\bTO\s+" + op + r"\s*$", stmt, I)
    if m:
        return "MOVE-CORRESPONDING target", m.group("op")
    m = re.search(r"\bINTO\s+@?" + op + r"\s*(?:$|[,.]|WHERE\b|FROM\b)", stmt, I)
    if m:
        return "INTO target", m.group("op")
    binds = _is_output_bind(stmt, op)
    if binds:
        return "bound to an output parameter", binds[0].group("op")
    return None, None


def _scope(text, body, sigs, attrs, types):
    """{name: (key, is_final)} visible in one method body."""
    name = body.name.split("~")[-1].lower()
    scope = {n: (k, False) for n, k in attrs.items()}
    scope.update({n: (k, False) for n, k in sigs.get(name, ({}, set()))[0].items()})
    scope.update({n: (k, False) for n, k in _typed_names(body.body, types).items()})
    for _, stmt in statements(body.body):
        for m in _INLINE_CALL.finditer(stmt):
            ret = sigs.get(m.group(2).lower(), ({}, set()))[1]
            if ret:
                scope[m.group(1).lower()] = (sorted(ret), False)
    for _, stmt in statements(body.body):
        for m in _FINAL.finditer(stmt):
            n = m.group(1).lower()
            scope[n] = (scope.get(n, (None, False))[0], True)
    return scope


def scan(corpus, wanted=()):
    types = keyed_types(corpus)
    sigs = signatures(corpus, types)
    findings, n_vars, n_handles = [], 0, 0
    for fname, text in corpus.items():
        if wanted and not any(w in fname for w in wanted):
            continue
        clean = strip_comments(text)
        attrs = _typed_names("\n".join(c.block for c in class_definitions(clean)), types)
        for body in method_bodies(clean):
            scope = _scope(text, body, sigs, attrs, types)
            stmts = statements(body.body)
            handles = _handles(stmts, scope)
            offset = clean[:body.start].count("\n")
            findings += [(fname, offset + line, *hit) for line, *hit in _writes(stmts, scope, handles)]
            n_vars += sum(1 for k, _ in scope.values() if k)
            n_handles += len(handles)
    return findings, {"keyed types": len(types), "keyed names in scope, summed over methods": n_vars,
                      "row handles": n_handles}


def _writes(stmts, scope, handles):
    """[(line, rule, what, statement)] for every protected write in one method."""
    return [(line, rule, what, stmt) for line, stmt in stmts
            for rule, what in _handle_writes(stmt, handles) + _table_writes(stmt, scope)]


def _handles(stmts, scope):
    """{handle: (table, key, is_final)} for every row handle onto a table in scope."""
    return {fs: (table,) + scope[table] for _, stmt in stmts
            for table, fs in _handle_forms(stmt) if table in scope}


def _handle_forms(stmt):
    """(table, handle) for each form of _HANDLE_FORMS that STMT is."""
    for form in _HANDLE_FORMS:
        m = form.match(stmt)
        fs = m and (m.group(2) or (m.group(3) if m.lastindex >= 3 else None))
        if fs:
            yield m.group(1).lower(), fs.lower()


def _rule(final, rule):
    """Any write onto a FINAL table is FINAL, whatever its form."""
    return "FINAL" if final else rule


def _handle_writes(stmt, handles):
    """[(rule, what)] for each handle STMT writes through."""
    hits = (_handle_write(stmt, h, *target) for h, target in handles.items())
    return [hit for hit in hits if hit]


def _handle_write(stmt, h, table, key, final):
    """(rule, what) when STMT writes through handle H onto a row of TABLE:
    binds it whole to an output, overwrites the row, or writes a key
    component (any component of a FINAL table's row). None otherwise."""
    if h.startswith("<"):
        whole, comp = re.escape(h), re.escape(h) + "-"
    else:
        whole, comp = re.escape(h) + r"->\*", re.escape(h) + "->"
    whole_op = whole + r"(?![\w-])"

    binds = [] if re.match(whole_op + r"\s*=", stmt, I) else \
        _is_output_bind(stmt, whole_op + r"\s*(?:\)|$|\w)")
    if binds:
        return _rule(final, "BIND"), (f"{h} (row of {table}) bound whole to "
                                      f"{_preceding_keyword(stmt, binds[0].start())}")
    how, _ = _writes_operand(stmt, whole_op)
    if how:
        return _rule(final, "ROW"), f"{h} (row of {table}) {how}"
    if not final and not key:
        return None
    comps = r"\w+" if final or key == ["*"] else "(?:" + "|".join(map(re.escape, key)) + ")"
    how, written = _writes_operand(stmt, comp + comps + r"\b(?!-)")
    if how:
        return _rule(final, "KEY"), f"{written} (row of {table}) {how}"
    return None


# Writes that are legal on a keyed table only while its key order survives.
_ORDER_WRITES = (r"APPEND\b.*\bTO\s+{t}\b", r"SORT\s+{t}\b",
                 r"INSERT\b.*\bINTO\s+{t}\s+INDEX\b", r"MODIFY\s+{t}\b.*\bINDEX\b")
_FINAL_CHANGES = (r"(?:APPEND\b.*\bTO|INSERT\b.*\bINTO(?:\s+TABLE)?|"
                  r"MODIFY(?:\s+TABLE)?|DELETE(?:\s+TABLE)?|SORT|REFRESH)\s+")


def _table_writes(stmt, scope):
    """[(rule, what)] for each keyed or FINAL table in scope STMT writes to."""
    out = []
    for table, (key, final) in scope.items():
        t = re.escape(table)
        if key and not final:
            out += _keyed_table_writes(stmt, table, t, key)
        how = final and _final_write(stmt, t)
        if how:
            out.append(("FINAL", f"{table} is FINAL, {how}"))
    return out


def _final_write(stmt, t):
    """How STMT changes the FINAL table T, or None."""
    how, _ = _writes_operand(stmt, t + r"(?:-\w+)*\b(?![-\[(])")
    if not how and re.match(_FINAL_CHANGES + t + r"\b", stmt, I):
        how = "changed"
    return how


def _keyed_table_writes(stmt, table, t, key):
    """TABLE for an order-dependent write, ROW or KEY for a table expression
    assigned whole or by a key component."""
    out = []
    if any(re.match(form.format(t=t), stmt, I) for form in _ORDER_WRITES):
        out.append(("TABLE", f"{table} is keyed"))
    if re.match(t + r"\[.*\]\s*=(?!=)", stmt, I):
        out.append(("ROW", f"{table}[ ... ] assigned whole"))
    elif key != ["*"] and re.match(
            t + r"\[.*\]-(" + "|".join(map(re.escape, key)) + r")\b\s*=(?!=)", stmt, I):
        out.append(("KEY", f"{table}[ ... ] key written"))
    return out


def check_keyedrows():
    """Scan the whole package -- types and signatures are package-wide --
    and report the files `--file` selected, if any."""
    findings, stats = scan(package_abap(), FILTER)
    bad = [Finding(f"{fname}:{line}  {rule:<5}  {what}  |  {stmt[:100]}", f"{fname}:{line} {rule}")
           for fname, line, rule, what, stmt in findings]
    return bad, [f"{v} {k}" for k, v in stats.items()]


CHECKS = [("keyedrows", "no write through a row its table protects", check_keyedrows)]


if __name__ == "__main__":
    exit_with(run(SCRIPT, CHECKS, suppressed, empty=EMPTY))
