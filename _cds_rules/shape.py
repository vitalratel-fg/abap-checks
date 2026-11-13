"""The shape of a statement: what a view entity's SELECT, conditions and
element list may not do."""

import re

from _cds import conditions, on_clauses, parse, strip
from _runner import Finding


def rule_entity(defs, ctx):
    bad = []
    for name, src in defs.items():
        s = strip(src)
        if re.search(r"@AbapCatalog\.sqlViewName", s, re.I) or \
           re.search(r"\bdefine\s+view\s+(?!entity\b)", s, re.I):
            bad.append(f"{name}: classic DDIC-based view; define a view entity")
        if re.search(r"\bdefine\s+table\s+function\b", s, re.I):
            bad.append(f"{name}: table function")
    return bad


def rule_distinct(defs, ctx):
    return [f"{n}: SELECT DISTINCT" for n, s in defs.items()
            if re.search(r"\bselect\s+distinct\b", strip(s), re.I)]


def rule_orjoin(defs, ctx):
    bad = []
    for name, src in defs.items():
        for cond in on_clauses(strip(src)):
            if re.search(r"\bor\b", cond, re.I):
                bad.append(f"{name}: OR in ON condition: {' '.join(cond.split())[:80]}")
    return bad


def rule_selfcmp(defs, ctx):
    bad = []
    for name, src in defs.items():
        for cond in on_clauses(strip(src)):
            for left, right in re.findall(r"([\w$]+\.\w+)\s*=\s*([\w$]+\.\w+)", cond):
                if left.lower() == right.lower():
                    bad.append(f"{name}: {left} = {right} compares a field with itself")
    return bad


def rule_window(defs, ctx):
    return [f"{n}: window function (OVER)" for n, s in defs.items()
            if re.search(r"\bover\s*\(", strip(s), re.I)]


def rule_likejoin(defs, ctx):
    return [f"{n}: LIKE in ON condition: {' '.join(c.split())[:80]}"
            for n, s in defs.items() for c in on_clauses(strip(s))
            if re.search(r"\blike\b", c, re.I)]


def _mixed(cond):
    cond = re.sub(r"\bbetween\b.*?\band\b", " between ", cond, flags=re.I | re.S)
    stack = [set()]
    for tok in re.finditer(r"\(|\)|\band\b|\bor\b", cond, re.I):
        t = tok.group(0).lower()
        if t == "(":
            stack.append(set())
        elif t == ")":
            if len(stack) > 1 and {"and", "or"} <= stack.pop():
                return True
        else:
            stack[-1].add(t)
    return any({"and", "or"} <= level for level in stack)


def rule_andor(defs, ctx):
    return [f"{n}: AND and OR at one level: {' '.join(c.split())[:80]}"
            for n, s in defs.items() for c in conditions(s) if _mixed(c)]


TAUTOLOGY = re.compile(r"([\w$.]+)\s*(?:!=|<>)\s*[^()\s]+\s+or\s+\1\s*(?:!=|<>)", re.I)


def rule_tautology(defs, ctx):
    return [f"{n}: `{m.group(1)} != … or {m.group(1)} != …` is always true"
            for n, s in defs.items() for m in TAUTOLOGY.finditer(strip(s))]


def rule_keyamount(defs, ctx):
    return [f"{n}: key {e.name} is an amount, a quantity or ABS()"
            for n, s in defs.items() for b in parse(s) for e in b.elements
            if e.key and (e.amount or re.search(r"\babs\s*\(", e.expr, re.I))]


_CASE_WORD = re.compile(r"\b(case|end|else)\b", re.I)


def rule_caseelse(defs, ctx):
    bad = []
    for name, src in defs.items():
        s = strip(src)
        for m in re.finditer(r"\bcase\b", s, re.I):
            end, has_else = _case_span(s, m.start())
            key = f"{name}:{s.count(chr(10), 0, m.start()) + 1}"
            if not has_else:
                bad.append(Finding(f"{key}: CASE without ELSE: {' '.join(s[m.start():end].split())[:80]}",
                                   key))
    return bad


def _case_span(s, start):
    """(end, has its own ELSE) of the CASE at START, nested CASEs skipped."""
    depth, has_else = 0, False
    for w in _CASE_WORD.finditer(s, start):
        word = w.group(1).lower()
        depth += {"case": 1, "end": -1}.get(word, 0)
        has_else |= word == "else" and depth == 1
        if depth == 0:
            return w.end(), has_else
    return len(s), has_else


def rule_keyfirst(defs, ctx):
    bad = []
    for name, src in defs.items():
        for b in parse(src):
            first = next((i for i, e in enumerate(b.elements) if not e.key), len(b.elements))
            late = [e.name for e in b.elements[first:] if e.key]
            if late:
                bad.append(Finding(f"{name}: key {', '.join(late)} after non-key {b.elements[first].name}",
                                   f"{name}:{late[0].lower()}"))
    return bad
