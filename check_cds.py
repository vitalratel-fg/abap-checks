#!/usr/bin/env python3
"""The CDS rules, executable.

    python3 check_cds.py                 # every rule
    python3 check_cds.py orjoin distinct # named rules only
    python3 check_cds.py --list

Exit code is the number of unsuppressed findings, so it is usable in a hook.

WHY THIS EXISTS
---------------
A legacy CDS stack can be slow and partly wrong for reasons that are all
visible in its source and none of them a syntax error: SELECT DISTINCT over
joins that multiplied rows, OR in join conditions, a join comparing a table
with itself, `#CHECK` on every view and no access control anywhere, classic
DDIC-based views throughout. abaplint parses CDS and says nothing about any
of that. These rules are those lessons in a form a laptop can fail.

THREE KINDS OF RULE (see _config.py)
  defect      always on: wrong in any view (selfcmp, tautology, andor,
              assocdef, keyfirst, constjoin, facettable, toone, keyamount)
  convention  on, house style; `[checks] off = ["cds.<rule>"]` turns one off
              (entity, distinct, orjoin, cardinality, crossjoin, window,
              likejoin, repeat, slots, dcl, dclgrant, mde, caseelse)
  fact        off until `[cds]` states what it needs (names, legacy,
              sources, budget, basecol, mandatory, elements, abapfree)

WHAT EACH RULE CHECKS
  entity       every data definition is a view entity: no `define view`
               with sqlViewName, no table function
  distinct     no SELECT DISTINCT
  orjoin       no OR in a join or association ON condition
  selfcmp      no ON condition comparing a field with itself (`b.x = b.x`):
               always true, so the join is a cross join
  cardinality  every join and association states its cardinality in words.
               The default when none is written is MANY TO ONE, which is
               wrong for a to-many target and silently so
  crossjoin    no CROSS JOIN and no RIGHT OUTER JOIN
  window       no window function (`OVER (`): view entities have none
  legacy       nothing names a legacy object ([cds] legacy, a regex): the
               new stack must not depend on the one it replaces
  dcl          every exposed entity of the package is `#CHECK` and has an
               access control of the same name; every `#CHECK` view has one
  mde          no `@UI` annotation in a data definition; every consumption
               view ([cds] consumption) allows extensions and has a
               metadata extension of the same name
  names        data definitions and service definitions match
               [cds.names] ddls / srvd; nothing is longer than 30
  sources      no data source in [cds] forbidden_sources
  likejoin     no LIKE in an ON condition
  repeat       one data source at most once per SELECT branch
  slots        no family of elements X1, X2, X3 in one view: a slot is a row
  budget       an exposed view expands to at most [cds] budget data-source
               references
  basecol      every [cds] filter_fields element of an exposed view is a
               plain column path, view by view, down to a table
  abapfree     ([cds] abapfree = true) no custom entity, virtual element,
               AMDP or behaviour definition in the package
  andor        no condition with AND and OR at one level without parentheses
  tautology    no `x != a or x != b` (always true)
  constjoin    every join's ON condition names a field of the side joined
               from; constants alone repeat each row per target row
  keyamount    no key element that is an amount, a quantity or an ABS()
  assocdef     every association an annotation names, in the view or its
               metadata extension, is defined or exposed
  elements     consumption view elements are CamelCase, not DDIC names
  facettable   no table section (#LINEITEM_REFERENCE) on a to-one
               association: Fiori elements V4 renders a table only for a
               to-many one
  toone        a `to one` join or association binds every key element of its
               target by equality: otherwise the stated cardinality is a hope,
               and a wrong one lets HANA drop the join for `$count` while the
               rows multiply. The target's key comes from the package's
               views and tables, then _sap.KEYS, then [cds.keys]; an unknown
               one is a finding. Each assumption that makes an unbound key
               safe is a suppression, `view:alias:keys`, so that it excuses
               those keys and no more
  dclgrant     an access control is a role of its file's name, grants on that
               view only, restricts by elements the view has, and asks for
               [cds] dcl_actvt (default '03', display) in pfcg_auth
  mandatory    every consumption view has the [cds.mandatory] elements as
               mandatory filters, of the stated selection type
  caseelse     every CASE has an ELSE, `ELSE NULL` where no value is meant:
               ADT warns on a CASE without one
  keyfirst     key elements come first, with no other element between them:
               ADT refuses the view otherwise

LIMITS, STATED RATHER THAN DISCOVERED LATER
-------------------------------------------
  - Text-level, after comments and string literals are blanked.
  - `basecol` proves the filter fields are columns in the CDS source. Whether
    the filter then reaches the table in the SQL is a plan question.
  - The element and source parser (_cds.py) reads `select from X as a …
    join Y as b on …`, `projection on X`, UNION branches and `{ … }` element
    lists. A form it does not recognise yields no elements, so the element
    rules stay silent on it rather than wrong.
  - Whether a stated cardinality matches the data is a runtime question:
    HANA's CHECK_JOIN_CARDINALITY hint.
"""

import re
from dataclasses import dataclass

import _sap
from _cds import strip
from _cds_rules.access import rule_dcl, rule_dclgrant
from _cds_rules.consumption import (
    rule_assocdef, rule_elements, rule_facettable, rule_mandatory, rule_mde,
)
from _cds_rules.facts import (
    rule_abapfree, rule_basecol, rule_budget, rule_legacy, rule_names, rule_slots, rule_sources,
)
from _cds_rules.joins import (
    rule_cardinality, rule_constjoin, rule_crossjoin, rule_repeat, rule_toone,
)
from _cds_rules.shape import (
    rule_andor, rule_caseelse, rule_distinct, rule_entity, rule_keyamount, rule_keyfirst,
    rule_likejoin, rule_orjoin, rule_selfcmp, rule_tautology, rule_window,
)
from _config import get
from _pkg import CDS_KINDS, abap_files, cds_files, ddic, object_files, own_regex
from _runner import Skip, exit_with, run, suppressions


SCRIPT = "cds"
suppressed = suppressions(SCRIPT)

RULES = [
    ("entity", "view entities only, no table functions", rule_entity),
    ("distinct", "no SELECT DISTINCT", rule_distinct),
    ("orjoin", "no OR in ON conditions", rule_orjoin),
    ("selfcmp", "no ON condition comparing a field with itself", rule_selfcmp),
    ("cardinality", "joins and associations state cardinality in words", rule_cardinality),
    ("crossjoin", "no CROSS or RIGHT OUTER JOIN", rule_crossjoin),
    ("window", "no window functions", rule_window),
    ("legacy", "no reference to the legacy stack", rule_legacy),
    ("dcl", "exposed and #CHECK views have an access control", rule_dcl),
    ("mde", "UI annotations in metadata extensions", rule_mde),
    ("names", "CDS object names follow [cds.names]", rule_names),
    ("sources", "no forbidden data source", rule_sources),
    ("likejoin", "no LIKE in ON conditions", rule_likejoin),
    ("repeat", "one data source at most once per branch", rule_repeat),
    ("slots", "no numbered element families", rule_slots),
    ("budget", "exposed views stay within the source budget", rule_budget),
    ("basecol", "filter fields are plain columns down to a table", rule_basecol),
    ("abapfree", "no custom entity, virtual element, AMDP, BDEF", rule_abapfree),
    ("andor", "no AND and OR at one level", rule_andor),
    ("tautology", "no x != a or x != b", rule_tautology),
    ("constjoin", "every join condition names the other side", rule_constjoin),
    ("keyamount", "no amount, quantity or ABS() in a key", rule_keyamount),
    ("assocdef", "annotated associations are defined", rule_assocdef),
    ("elements", "consumption elements are CamelCase", rule_elements),
    ("toone", "to-one joins bind their target's whole key", rule_toone),
    ("dclgrant", "access controls grant display on their own view", rule_dclgrant),
    ("mandatory", "consumption views have the mandatory filters", rule_mandatory),
    ("facettable", "table sections only on to-many associations", rule_facettable),
    ("caseelse", "every CASE has an ELSE (ELSE NULL for none)", rule_caseelse),
    ("keyfirst", "key elements first and contiguous", rule_keyfirst),
]


def own_table_keys():
    """{table: key fields, client left out} of the package's tables on disk."""
    out = {}
    for name, root in ddic("tabl").items():
        # `.INCLUDE` / `.APPEND` rows carry KEYFLAG too, but they name a
        # structure, not a field a join could bind.
        fields = ((f.findtext("FIELDNAME") or "", f.findtext("KEYFLAG")) for f in root.iter("DD03P"))
        out[name] = {f.lower() for f, key in fields
                     if key == "X" and f != "MANDT" and not f.startswith(".") and f}
    return out


@dataclass(frozen=True)
class Context:
    """What the rules read beyond the sources. `context()` builds it from the
    config; a test builds its own, or `replace()`s a field of one."""
    kinds: dict[str, dict[str, str]]    # every CDS kind -> {object: source}
    consumption: set[str]               # consumption views
    consumption_re: str                 # what made them so; "" when unset
    exposed: set[str]                   # exposed by a service definition, or consumption
    own: re.Pattern                     # the package's names: dcl skips the rest
    filter_fields: set[str]
    mandatory: dict[str, str]           # element -> selection type, "" for any
    mandatory_override: dict[str, dict[str, str]]   # view -> element -> type
    table_keys: dict[str, set[str]]     # `to one` targets -> key fields
    budget: int
    forbidden_sources: set[str]
    sap_numbered: dict[str, str]
    names: dict[str, str]               # cds kind -> name regex
    legacy: str
    dcl_actvt: str
    abapfree: bool
    abap: dict[str, str]
    bdef: list[str]


def context(defs, kinds, abap=None, bdef=(), own_keys=None, cfg=None):
    """The package's Context, from CFG (the `[cds]` table; default: the
    config's). Reads nothing from disk: `main` passes what it loaded, so a
    test's context is only what it says."""
    cfg = get("cds", {}) if cfg is None else cfg
    kinds = {k: kinds.get(k, {}) for k in CDS_KINDS}
    exposed = set()
    for srvd in kinds["srvd"].values():
        exposed |= {e.lower() for e in re.findall(r"\bexpose\s+(\w+)", strip(srvd), re.I)}
    cons_re = cfg.get("consumption", "")
    cons = {n for n in defs if cons_re and re.match(cons_re, n, re.I)}
    keys = {**_sap.KEYS, **{k.lower(): {f.lower() for f in v}
                           for k, v in cfg.get("keys", {}).items()}, **(own_keys or {})}
    return Context(
        kinds=kinds, consumption=cons, consumption_re=cons_re, exposed=exposed | cons,
        own=own_regex() or re.compile(r"(?:[zy]\w*|/\w+/\w+)$", re.I),
        filter_fields={f.lower() for f in cfg.get("filter_fields", [])},
        mandatory={k.lower(): v for k, v in cfg.get("mandatory", {}).items()},
        mandatory_override={k.lower(): {f.lower(): t for f, t in v.items()}
                            for k, v in cfg.get("mandatory_override", {}).items()},
        table_keys=keys, budget=cfg.get("budget", 0),
        forbidden_sources={s_.lower() for s_ in cfg.get("forbidden_sources", [])},
        sap_numbered={**_sap.NUMBERED, **cfg.get("sap_numbered", {})},
        names=cfg.get("names", {}), legacy=cfg.get("legacy", ""),
        dcl_actvt=cfg.get("dcl_actvt", "03"), abapfree=cfg.get("abapfree", False),
        abap=abap or {}, bdef=list(bdef))


def main():
    all_kinds = {k: cds_files(k) for k in CDS_KINDS}
    defs = all_kinds["ddls"]
    ctx = context(defs, all_kinds, abap=abap_files(),
                  bdef=sorted(object_files("bdef.asbdef")), own_keys=own_table_keys())
    empty = not any(ctx.kinds.values())
    checks = [(key, text, (lambda fn=fn: _wrap(fn(defs, ctx)))) for key, text, fn in RULES]
    return run(SCRIPT, checks, suppressed, empty=empty, empty_why="no CDS source on disk")


def _wrap(result):
    """A rule returns its findings, or a Skip; the runner wants notes too."""
    return result if isinstance(result, Skip) else (result, [])


if __name__ == "__main__":
    exit_with(main())
