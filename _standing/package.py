"""The package as the standing checks read it, built once: every ABAP object,
its kind, its code without comments, and each class's own definition."""

import _abap
from _pkg import abap_by_stem, kinds, of_kind
from _runner import suppressions


SCRIPT = "standing"
suppressed = suppressions(SCRIPT)

SRC = abap_by_stem()
KINDS = kinds()


# Code only. A name in a comment is prose -- often the uppercase spelling of
# a reference that was renamed since -- and reading comments as code made
# the graph cyclic and `qualified` report members of prose.
CODE = {n: _abap.strip_comments(s) for n, s in SRC.items()}

CLASSES = of_kind(SRC, "clas")
INTERFACES = of_kind(SRC, "intf")


# Each class object's own class: what it declares, inherits and implements.
GLOBAL = {n: c for n in CLASSES if (c := _abap.global_class(CODE[n], n))}


def main_class(name):
    """The class an object is read by: a class pool's own class, a program's
    first local class -- the program's own design, not a helper. None when
    the object defines no class."""
    if KINDS.get(name) == "clas":
        return GLOBAL.get(name)
    return next(iter(_abap.class_definitions(CODE[name])), None)
