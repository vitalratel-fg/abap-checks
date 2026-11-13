"""Access controls: every exposed view has one, of its own name, granting display."""

import re

from _cds import parse, strip, strip_comments
from _runner import Finding


def _check_mode(src):
    m = re.search(r"@AccessControl\.authorizationCheck\s*:\s*#(\w+)", src, re.I)
    return m.group(1).upper() if m else None


def rule_dcl(defs, ctx):
    bad = []
    roles = ctx.kinds["dcls"]
    exposed = set()
    for srvd in ctx.kinds["srvd"].values():
        exposed |= {e.lower() for e in re.findall(r"\bexpose\s+(\w+)", strip(srvd), re.I)}
    for name in sorted(exposed):
        if not ctx.own.match(name):
            continue                    # SAP's own views carry their own roles
        if name not in defs:
            bad.append(f"{name}: exposed, but no data definition on disk")
            continue
        if _check_mode(defs[name]) != "CHECK":
            bad.append(Finding(f"{name}: exposed, authorizationCheck is not #CHECK", f"{name}:mode"))
    bad += [Finding(f"{name}: #CHECK and no access control {name.upper()}", f"{name}:role")
            for name, src in defs.items() if _check_mode(src) == "CHECK" and name not in roles]
    bad += [Finding(f"{name}: access control for a view that is not on disk", f"{name}:orphan")
            for name in roles if name not in defs]
    return bad


def rule_dclgrant(defs, ctx):
    bad = []
    for name, src in ctx.kinds["dcls"].items():
        bad += _role_findings(name, strip_comments(src), defs, ctx)
    return [Finding(b, b.split(":")[0]) for b in bad]


def _role_findings(name, s, defs, ctx):
    """An access control S is a role of its file's name and grants something."""
    bad = []
    role = re.search(r"\bdefine\s+role\s+(\w+)", s, re.I)
    if not role or role.group(1).lower() != name:
        bad.append(f"{name}: role named {role.group(1) if role else 'nothing'}, not as its file")
    grants = list(re.finditer(r"\bgrant\s+select\s+on\s+(\w+)(.*?);", s, re.I | re.S))
    if not grants:
        bad.append(f"{name}: grants nothing")
    elements = {e.name.lower() for b in parse(defs[name]) for e in b.elements} \
        if name in defs else None
    for g in grants:
        bad += _grant_findings(name, g.group(1).lower(), g.group(2), elements, ctx)
    return bad


def _grant_findings(name, target, body, elements, ctx):
    """One grant is on the role's own view, restricted by a pfcg_auth over
    elements the view has (unknown when its view is not on disk) and asking
    for the display activity."""
    bad = []
    if target != name:
        bad.append(f"{name}: grants on {target.upper()}, not on its own view")
    where = re.search(r"\bwhere\b(.*)", body, re.I | re.S)
    aspects = re.findall(r"\(?\s*([\w\s,]+?)\s*\)?\s*=\s*aspect\s+pfcg_auth\s*\(([^)]*)\)",
                         where.group(1), re.I) if where else []
    if not aspects:
        bad.append(f"{name}: grants on {target.upper()} without a pfcg_auth condition")
    for fields, args in aspects:
        bad += [f"{name}: restricts by {f}, which {name.upper()} does not have"
                for f in re.split(r"\s*,\s*", fields.strip())
                if elements is not None and f.lower() not in elements]
        if ctx.dcl_actvt and not re.search(rf"\bactvt\s*=\s*'{ctx.dcl_actvt}'", args, re.I):
            bad.append(f"{name}: pfcg_auth without ACTVT = '{ctx.dcl_actvt}'")
    return bad
