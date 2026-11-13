#!/usr/bin/env python3
"""The standing set: ABAP hygiene that holds in any package.

    python3 check_standing.py                  # every check
    python3 check_standing.py graph raising    # named checks only
    python3 check_standing.py --list

Exit code is the number of unsuppressed findings, so it is usable in a hook.

WHY THIS EXISTS
---------------
A check that is retyped is a different check each time. A check in a file is
the same check, and when it is wrong it is wrong once and fixed once. The
predecessor of this file produced four wrong checks in five passes, every one
a false alarm -- which is the direction that teaches people to ignore output.

WHAT LIVES HERE, AND WHAT DOES NOT
  HERE        acyclic interface graph, RAISING propagation, `=>member`
              resolution, name length, type and method prefixes,
              orphan/unimplemented interface methods, dead private methods,
              write-only fields, ASSIGNING loops, dead constants, DDIC
              references on disk, retired names, undrafted objects.
  ELSEWHERE   agreements about tables, values and reports (one table, one
              owner; every column read) are check_design.py: they hold for
              a package that keeps them, and change when its design does.

CONFIG (abapcheck.toml)
  [package] objects / own   `undrafted`, and `ddic`'s TYPE references
  [naming] retired          `renamed`: regexes of names that must not return
  [naming] type_public, type_private, method_private
                            the prefixes `typenames` / `methodnames` enforce;
                            defaults mty_ / _mty_ / _
"""

from _runner import exit_with, run
from _standing.dead import check_deadconst, check_deadprivate, check_loops, check_writeonly
from _standing.interfaces import check_impls, check_orphans, check_raising
from _standing.naming import (
    METHOD_PRIVATE, TYPE_PRIVATE, TYPE_PUBLIC, check_methodnames, check_typenames,
)
from _standing.package import SCRIPT, suppressed
from _standing.references import (
    NAME_LIMIT, TABLE_LIMIT, check_ddic, check_graph, check_names, check_qualified,
    check_renamed, check_undrafted,
)


CHECKS = [
    ("undrafted", "objects named but not on disk", check_undrafted),
    ("graph", "interface dependency graph acyclic", check_graph),
    ("raising", "RAISING propagation", check_raising),
    ("renamed", "retired identifiers still live", check_renamed),
    ("qualified", "interface=>member resolves to its owner", check_qualified),
    ("names", f"object name <= {NAME_LIMIT}, table <= {TABLE_LIMIT}", check_names),
    ("typenames", f"type prefix: {TYPE_PUBLIC} public, {TYPE_PRIVATE} not", check_typenames),
    ("methodnames", f"method prefix: bare public, {METHOD_PRIVATE} not", check_methodnames),
    ("orphans", "interface method with no caller", check_orphans),
    ("impls", "interface method with no implementation", check_impls),
    ("deadprivate", "private method its class never calls", check_deadprivate),
    ("writeonly", "private field assigned and never read", check_writeonly),
    ("loops", "LOOP AT ... ASSIGNING, not INTO", check_loops),
    ("deadconst", "constant nothing names, outside a value set", check_deadconst),
    ("ddic", "every customer DDIC reference exists on disk", check_ddic),
]


# `renamed` also reads documents; `names` and `ddic` read DDIC XML. Every
# other check has nothing to say about a package with no ABAP.
SOURCE_ONLY = {k for k, _, _ in CHECKS} - {"renamed", "names", "ddic"}


if __name__ == "__main__":
    from _pkg import EMPTY
    exit_with(run(SCRIPT, CHECKS, suppressed, empty=EMPTY, source_only=SOURCE_ONLY))
