"""Joins and associations: stated cardinality, and the keys a `to one` binds."""

import re
from collections import Counter

from _cds import ASSOC, CARD, JOIN, ON_END, TO_ONE, drop_annotations, parse, strip
from _runner import Finding


def rule_cardinality(defs, ctx):
    bad = []
    for name, src in defs.items():
        s = strip(src)
        bad += [f"{name}: {' '.join(m.group(0).split())} without cardinality"
                for m in JOIN.finditer(s) if _kind(m) in ("inner", "left") and not m.group("card")]
        bad += [f"{name}: association without cardinality in words: {' '.join(m.group(0).split())[:80]}"
                for m in ASSOC.finditer(s) if not _states_cardinality(m)]
    return bad


def _kind(join):
    """`inner`, `left`, `right` or `cross`: a JOIN without a kind is inner."""
    return (join.group("kind") or "inner").lower().split()[0]


def _states_cardinality(assoc):
    """An association states `of X to Y`; a composition and `to parent` need not."""
    rest = assoc.group("rest")
    return assoc.group(1).lower() == "composition" or re.match(r"\s*to\s+parent\b", rest, re.I) \
        or re.match(rf"\s*of\s+{CARD}\s+to\s+{CARD}\b", rest, re.I)


def rule_crossjoin(defs, ctx):
    bad = []
    for name, src in defs.items():
        for m in JOIN.finditer(strip(src)):
            kind = (m.group("kind") or "").lower().split()
            if kind and kind[0] in ("cross", "right"):
                bad.append(f"{name}: {' '.join(m.group(0).split())}")
    return bad


def rule_repeat(defs, ctx):
    bad = []
    for name, src in defs.items():
        for b in parse(src):
            for target, n in Counter(b.sources).items():
                if n > 1:
                    bad.append(Finding(f"{name}: {target} read {n} times in one branch", f"{name}:{target}"))
    return bad


def rule_constjoin(defs, ctx):
    return [Finding(f"{name}: join {target} as {alias} on its own fields and constants only",
                    f"{name}:{alias}")
            for name, src in defs.items() for b in parse(src) for target, alias, cond in b.joins
            if (refs := {r.lower() for r in re.findall(r"([\w$]+)\s*\.\s*\w+", cond)})
            and refs <= {alias}]


def _keys(defs, ctx, target):
    """The key element names of `target`, lowercased; None if unknown."""
    if target in defs:
        branches = parse(defs[target])
        return {e.name.lower() for e in branches[0].elements if e.key} if branches else None
    return ctx.table_keys.get(target)


def _bound(cond, alias):
    """Fields of `alias` that the condition sets equal to something (not <=, >=, <>)."""
    out = set()
    for t in re.finditer(r"([\w$]+)\s*\.\s*(\w+)", cond):
        if t.group(1).lower() != alias:
            continue
        before, after = cond[:t.start()].rstrip(), cond[t.end():].lstrip()
        if after.startswith("=") or (before.endswith("=") and not re.search(r"[<>!]=$", before)):
            out.add(t.group(2).lower())
    return out


def rule_toone(defs, ctx):
    bad = []
    for name, src in defs.items():
        s = drop_annotations(strip(src))
        bad += [f for m in TO_ONE.finditer(s) if (f := _unbound_key(name, s, m, defs, ctx))]
    return bad


def _unbound_key(name, s, m, defs, ctx):
    """The finding for one `to one` join or association M of view NAME, or None."""
    target, alias = m.group(1).lower(), m.group(2).lower()
    keys = _keys(defs, ctx, target)
    if keys is None:
        return Finding(f"{name}: to one {target} as {alias}: its key is unknown; "
                       f"add it to [cds.keys] (from SE11)", f"{name}:{alias}:?")
    end = ON_END.search(s, m.end())
    # The suppression names the unbound keys it excuses, so losing one more fails.
    missing = ",".join(sorted(keys - _bound(s[m.end():end.start() if end else len(s)], alias)))
    return Finding(f"{name}: to one {target} as {alias} leaves key {missing} unbound",
                   f"{name}:{alias}:{missing}") if missing else None
