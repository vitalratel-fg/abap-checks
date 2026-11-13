#!/usr/bin/env python3
"""Bare-boolean-condition check.

A functional method call used DIRECTLY as a condition:

    IF io_ctx->mo_consts->has_entry( iv_const = ... iv_low = ... ).
    IF is_edi_event( io_ctx ).

ABAP has no truthiness. A condition is a relational or predicate
expression, and a method returning ABAP_BOOL is neither - it needs an
explicit `= abap_true`. Both lines above are SYNTAX ERRORS, not style.

WHY A CHECK AND NOT A COMPILER
------------------------------
Because a package written offline has no compiler until it reaches the
system, and until then the only thing standing between a plausible-looking
condition and a shipped one is a reader. Seven sites had this in one
package - in six different classes, written at six different times - so it
is not a slip that gets caught by being rare. It also survives review
particularly well: `IF has_entry( ... ).` reads like every other
line_exists( ) gate in the package, and `line_exists` IS legal, because it
is a predicate function.

WHAT COUNTS AS A CONDITION HERE
-------------------------------
The statement opened by IF / ELSEIF / CHECK / WHILE, joined across
continuation lines up to its terminating period, comments stripped.

WHAT IS NOT A FINDING
---------------------
  predicate functions  line_exists( ) / matches( ) / contains( )   - legal
  a comparison anywhere in the statement                            - fine
  `IS INITIAL`, `CS`, `CP`, `IN`, `BETWEEN`                         - fine

LIMITS, STATED RATHER THAN DISCOVERED LATER
-------------------------------------------
  - Argument lists are stripped before the operator test, so a named
    parameter (`iv_low = x`) cannot be mistaken for a comparison. That
    stripping is what the first version got wrong - it reported three of
    the seven sites and looked clean.
  - `->` and `=>` are removed before the test for the same reason: the `>`
    in a selector matched the relational-operator pattern and hid the four
    sites that call through an object reference.
  - A condition mixing a legal comparison with a bare call
    (`IF a = b AND is_x( )`) is NOT reported - one operator anywhere in the
    statement is enough to satisfy the test. Rare enough to leave; the
    alternative is parsing boolean structure.

Usage:  python3 check_bare_bool.py [--file SUBSTR]
Suppress `file:line` under [suppress.bare_bool.barebool].
"""

import re

import _abap
from _pkg import EMPTY, abap_files
from _runner import Finding, exit_with, run, suppressions

SCRIPT = "bare_bool"
suppressed = suppressions(SCRIPT)

OPEN = re.compile(r"^\s*(IF|ELSEIF|CHECK|WHILE)\b", re.I)
REL = re.compile(r"(<>|<=|>=|=|<|>)"
                 r"|\b(EQ|NE|LT|GT|LE|GE|IS|CS|CP|CA|NA|CO|CN|BETWEEN|IN)\b", re.I)
PREDICATE = re.compile(r"\b(line_exists|matches|contains|contains_any_of)\s*\(", re.I)
CALL = re.compile(r"[\w>~-]+\(")


def conditions(text):
    """(lineno, statement) for every IF/ELSEIF/CHECK/WHILE."""
    return [(n, stmt) for n, stmt in _abap.statements(text) if OPEN.match(stmt)]


def is_bare(stmt):
    if not CALL.search(stmt) or PREDICATE.search(stmt):
        return False
    bare = stmt.replace("->", ".").replace("=>", ".")
    while True:                       # drop argument lists: `f( a = 1 )` -> `f`
        shorter = re.sub(r"\([^()]*\)", "", bare)
        if shorter == bare:
            return not REL.search(bare)
        bare = shorter


def check_barebool():
    bad = []
    for name, text in abap_files().items():
        for lineno, stmt in conditions(text):
            if is_bare(stmt):
                bad.append(Finding(f"{name}:{lineno}  {stmt[:110]}", f"{name}:{lineno}"))
    return bad, [f"{len(abap_files())} file(s) scanned"]


CHECKS = [("barebool", "no functional call used bare as a condition", check_barebool)]


if __name__ == "__main__":
    exit_with(run(SCRIPT, CHECKS, suppressed, empty=EMPTY))
