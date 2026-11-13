"""Rules on what the project states in `[cds]`: names, legacy objects,
forbidden sources, the source budget, base columns, slots, ABAP-free."""

import re
from collections import Counter

from _cds import parse, strip
from _cds_rules import NEEDS
from _runner import Finding, needs


def rule_legacy(defs, ctx):
    if not ctx.legacy:
        return needs(NEEDS["legacy"])
    pat = re.compile(rf"\b({ctx.legacy})\b", re.I)
    bad = []
    for kind, objs in ctx.kinds.items():
        for name, src in objs.items():
            bad += [Finding(f"{name} ({kind}): names legacy object {hit}", f"{name}:{hit}")
                    for hit in sorted({h.upper() for h in pat.findall(strip(src))})]
    return bad


def rule_names(defs, ctx):
    if not ctx.names.get("ddls"):
        return needs(NEEDS["names"])
    bad = [Finding(f"{n}: data definition outside /{ctx.names['ddls']}/", n)
           for n in defs if not re.match(ctx.names["ddls"], n, re.I)]
    for kind in ("dcls", "ddlx", "srvd"):
        if ctx.names.get(kind):
            bad += [Finding(f"{n}: {kind} outside /{ctx.names[kind]}/", n) for n in ctx.kinds[kind]
                    if not re.match(ctx.names[kind], n, re.I)]
    bad += [f"{n}: longer than 30 characters" for kind in ctx.kinds.values()
            for n in kind if len(n) > 30]
    return bad


def rule_sources(defs, ctx):
    if not ctx.forbidden_sources:
        return needs(NEEDS["sources"])
    pat = re.compile(r"\b(?:from|join|to|projection\s+on)\s+(" +
                     "|".join(sorted(ctx.forbidden_sources)) + r")\b", re.I)
    bad = []
    for name, src in defs.items():
        bad += [Finding(f"{name}: reads {hit.upper()} in the request path", f"{name}:{hit}")
                for hit in sorted({h.lower() for h in pat.findall(strip(src))})]
    return bad


def rule_slots(defs, ctx):
    return [Finding(f"{name}: slot family {stem}{','.join(sorted(digits))}", f"{name}:{stem}")
            for name, src in defs.items() for stem, digits in sorted(_slot_families(src).items())
            if len(digits) > 1 and stem not in ctx.sap_numbered]


def _slot_families(src):
    """{stem: digits} of the elements named `<stem><digit>`."""
    stems = {}
    for m in (re.match(r"(.*[a-z_])([1-9])$", e.name.lower()) for b in parse(src) for e in b.elements):
        if m:
            stems.setdefault(m.group(1), set()).add(m.group(2))
    return stems


def _leaves(defs, name, path=()):
    leaves = Counter()
    for b in parse(defs[name]):
        for s in b.sources:
            # A table function reads nothing in CDS: it is a leaf here.
            # cds_sources.py expands one through its AMDP body, which runs
            # with the statement.
            if s in defs and s not in path and any(x.sources for x in parse(defs[s])):
                leaves += _leaves(defs, s, path + (name,))
            else:
                leaves[s] += 1
    return leaves


def rule_budget(defs, ctx):
    if not ctx.budget:
        return needs(NEEDS["budget"])
    bad = []
    for name in sorted(ctx.exposed & defs.keys()):
        n = sum(_leaves(defs, name).values())
        if n > ctx.budget:
            bad.append(Finding(f"{name}: {n} data-source references, budget {ctx.budget}", name))
    return bad


def _trace(defs, view, field, seen=frozenset()):
    """None if `field` of `view` is a plain column path down to a table, else why."""
    if (view, field) in seen:
        return None
    return next((why for b in parse(defs[view])
                 if (why := _trace_branch(defs, view, field, b, seen | {(view, field)}))), None)


def _trace_branch(defs, view, field, b, seen):
    """Why FIELD of VIEW is not a plain column in branch B, followed down the
    views it reads; None when it is."""
    el = next((e for e in b.elements if e.name.lower() == field), None)
    if el is None:
        return f"{view}.{field}: not in every branch"
    m = re.fullmatch(r"(?:([\w$]+)\.)?(\w+)", el.expr)
    if not m:
        return f"{view}.{field} is `{el.expr[:60]}`"
    alias, col = m.group(1), m.group(2).lower()
    if alias and alias.startswith("_"):
        return f"{view}.{field} comes through association {alias}"
    target = b.aliases.get(alias.lower()) if alias else (b.sources or [None])[0]
    if target is None:
        return f"{view}.{field}: alias {alias} not resolved"
    if target not in defs:
        return None
    if not any(x.sources for x in parse(defs[target])):
        return f"{view}.{field} comes from table function {target}: a barrier"
    return _trace(defs, target, col, seen)


def rule_basecol(defs, ctx):
    if not ctx.filter_fields:
        return needs(NEEDS["basecol"])
    # Sorted: a set of names iterates in a different order on every run.
    fields = [(name, e) for name in sorted(ctx.exposed & defs.keys())
              for e in sorted({e.name.lower() for b in parse(defs[name]) for e in b.elements})
              if e in ctx.filter_fields]
    return [Finding(f"{name}: filter field {e}: {why}", f"{name}:{e}")
            for name, e in fields if (why := _trace(defs, name, e))]


def rule_abapfree(defs, ctx):
    if not ctx.abapfree:
        return needs(NEEDS["abapfree"])
    bad = []
    for name, src in defs.items():
        s = strip(src)
        if re.search(r"\bdefine\s+(?:root\s+)?custom\s+entity\b", s, re.I):
            bad.append(f"{name}: custom entity")
        if re.search(r"virtualElementCalculatedBy", s, re.I):
            bad.append(f"{name}: virtual element")
    for path, text in ctx.abap.items():
        if re.search(r"\bBY\s+DATABASE\s+(?:PROCEDURE|FUNCTION)\b", text, re.I):
            bad.append(Finding(f"{path}: AMDP", path))
    bad += [f"{b}: behaviour definition" for b in ctx.bdef]
    return bad
