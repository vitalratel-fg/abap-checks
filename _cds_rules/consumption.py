"""Consumption views: annotations in their extensions, CamelCase elements, the
mandatory filters, and associations that exist and fit their facets."""

import re

from _cds import TO_ONE, annotations, parse, strip, strip_comments
from _cds_rules import NEEDS
from _runner import Finding, needs


def rule_mde(defs, ctx):
    bad = []
    for name, src in defs.items():
        s = strip(src)
        if re.search(r"@UI\.", s):
            bad.append(Finding(f"{name}: @UI annotation in the data definition; move it to the extension",
                               f"{name}:ui"))
        bad += _consumption_mde(name, s, ctx) if name in ctx.consumption else []
    return bad


def _consumption_mde(name, s, ctx):
    """A consumption view allows extensions and has one."""
    bad = []
    if not re.search(r"@Metadata\.allowExtensions\s*:\s*true", s, re.I):
        bad.append(f"{name}: consumption view without @Metadata.allowExtensions: true")
    if name not in ctx.kinds["ddlx"]:
        bad.append(f"{name}: consumption view without metadata extension")
    return bad


def rule_assocdef(defs, ctx):
    """An association named in an annotation, of the view or of its metadata extension."""
    bad = []
    mdes = ctx.kinds["ddlx"]
    for name, src in defs.items():
        named = set(re.findall(r"'(_\w+)'", strip_comments(src + "\n" + mdes.get(name, ""))))
        defined = {a.lower() for a in re.findall(r"\bas\s+(_\w+)", strip(src), re.I)}
        defined |= {e.name.lower() for b in parse(src) for e in b.elements}
        for a in sorted(named):
            if a.lower() not in defined:
                bad.append(f"{name}: annotation names {a}, which is not defined")
    return bad


def rule_elements(defs, ctx):
    if not ctx.consumption_re:
        return needs(NEEDS["elements"])
    bad = []
    for name in sorted(ctx.consumption & defs.keys()):
        for e in sorted({e.name for b in parse(defs[name]) for e in b.elements}):
            if not e.startswith("_") and e == e.lower():
                bad.append(Finding(f"{name}: element {e} is not CamelCase", f"{name}:{e}"))
    return bad


def rule_mandatory(defs, ctx):
    if not ctx.mandatory:
        return needs(NEEDS["mandatory"])
    bad = []
    mdes = ctx.kinds["ddlx"]
    for name in sorted(ctx.consumption & defs.keys()):
        anns = annotations(defs[name], r"\bdefine\b", ",")
        extra = annotations(mdes[name], r"\bwith\b", ";") if name in mdes else {}
        for field, selection in ctx.mandatory.items():
            selection = ctx.mandatory_override.get(name, {}).get(field, selection)
            why = _not_mandatory(name, field, selection, anns, extra)
            if why:
                bad.append(Finding(why, f"{name}:{field}"))
    return bad


def _not_mandatory(name, field, selection, anns, extra):
    """Why FIELD of view NAME is not the mandatory filter it must be, or None."""
    if field not in anns:
        return f"{name}: no element {field}, a mandatory filter"
    filt = " ".join(re.findall(r"@consumption\.filter(?:\.\w+:[^@]*|:\{[^}]*\})",
                               anns[field] + extra.get(field, "")))
    if "mandatory:true" not in filt:
        return f"{name}: {field} is not a mandatory filter"
    if selection and f"selectiontype:{selection.lower()}" not in filt:
        return f"{name}: {field} filter is not {selection.upper()}"
    return None


def rule_facettable(defs, ctx):
    """A table section on a to-one association: Fiori elements V4 shows nothing there."""
    bad = []
    mdes = ctx.kinds["ddlx"]
    for name, src in defs.items():
        to_one = {m.group(2).lower() for m in TO_ONE.finditer(strip(src))}
        for facet in re.findall(r"\{[^{}]*#LINEITEM_REFERENCE[^{}]*\}", strip_comments(mdes.get(name, ""))):
            target = re.search(r"targetElement\s*:\s*'(_\w+)'", facet)
            if target and target.group(1).lower() in to_one:
                bad.append(f"{name}: table section on to-one {target.group(1)}; use #FIELDGROUP_REFERENCE")
    return bad
