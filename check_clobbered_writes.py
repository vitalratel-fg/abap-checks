#!/usr/bin/env python3
"""Clobbered-write check.

Inside one method body: a write to a FIELD of a structure, followed by a
WHOLESALE assignment to the structure that contains it. The second statement
discards the first, and nothing anywhere says so.

    rs_item-reason = iv_reason.                    " decided here
    rs_item = _mo_engine->read_item( iv_act ).     " ...and thrown away

THIS IS EXACTLY WHAT check_model_writers.py CANNOT SEE
-----------------------------------------------------
That check asks "does anything write this field", and REASON has a writer -
the line above the one that erases it. The two checks are complementary and
neither subsumes the other: one finds fields nobody fills, this one finds
fields somebody fills twice, the second time by accident.

THE SHAPE IS AN OVERRIDE MAGNET, WHICH IS WHY IT IS WORTH A FILE
---------------------------------------------------------------
Every RETURNING-structure method on an engine adapter invites "call the
engine, then patch". Written in that order it is correct and written in the
other order it is silent, so the defect arrives with the next adapter rather
than being fixed once.

WHAT IS AND IS NOT A FINDING
----------------------------
  finding    x-a = ...  then  x = ...          (narrow write, then wholesale)
  finding    x-a-b = ...  then  x-a = ...      (same, one level down)
  fine       x = ...  then  x-a = ...          the patch-after-SUPER shape
  fine       two writes to the same field      not this check's business

LIMITS, STATED RATHER THAN DISCOVERED LATER
-------------------------------------------
  - Statement ORDER only, not reachability. Two branches of an IF/ELSE that
    write the same structure would be reported, and where both branches are
    total that is a false alarm. Blocks are therefore tracked: a write inside an IF/LOOP/CASE
    does not arm a finding for a wholesale write that follows the ENDIF,
    because the two may be alternatives rather than a sequence.
  - Comment lines are skipped, unlike check_model_writers.py, which reads
    them on purpose. Here a sketched `" rs_x-a = ...` is a DESIGN intent
    whose clobber does not exist yet; reporting it would flag every
    cited-sketch method in the package.
  - A CARRIER is a structure named by the house prefixes (rs_/cs_/ls_/
    ms_/rt_ ...): `[clobbered] carrier` in abapcheck.toml replaces the
    regex. A local that is clobbered is usually a real defect too.

Usage:  python3 check_clobbered_writes.py [--file SUBSTR]
Suppress `file:line path` under [suppress.clobbered.clobbered].
"""

import re

import _abap
from _config import get
from _pkg import EMPTY, abap_files
from _runner import Finding, exit_with, run, suppressions

SCRIPT = "clobbered"
suppressed = suppressions(SCRIPT)

CARRIER = "(?:" + get("clobbered.carrier", r"_?[rcilm][st]_\w+") + ")"

# `x-a-b = `, `CLEAR x-a`, `APPEND ... TO x-a`, `INTO @x-a` - any write that
# names a PATH under a carrier. Group 1 is the full path.
WRITE = re.compile(
    rf"\b({CARRIER}(?:-\w+)+)\s*(?:\+\d+\(\d+\))?\s*=(?!=)"
    rf"|\bCLEAR:?\s+({CARRIER}(?:-\w+)+)"
    rf"|\b(?:APPEND|INSERT)\b[^.]*?\b(?:TO|INTO TABLE)\s+({CARRIER}(?:-\w+)+)"
    rf"|\bINTO\s+\(?\s*@?({CARRIER}(?:-\w+)+)",
    re.I)

# `x = ` or `x-a = ` at statement start: the whole thing replaced in one move.
WHOLESALE = re.compile(rf"^\s*({CARRIER}(?:-\w+)*)\s*=(?!=)", re.I)

BLOCK_OPEN = re.compile(r"^\s*(IF|LOOP|CASE|WHILE|DO|TRY)\b", re.I)
BLOCK_CLOSE = re.compile(r"^\s*(ENDIF|ENDLOOP|ENDCASE|ENDWHILE|ENDDO|ENDTRY)\b", re.I)
# A new ARM of the block already open: what the previous arm wrote is not
# in force here. Missing this made one method - a branch filling seven
# fields, the ELSE calling SUPER - seven findings.
BLOCK_ARM = re.compile(r"^\s*(ELSE|ELSEIF|WHEN|CATCH|CLEANUP)\b", re.I)


def code_lines(body, first):
    """(lineno, code) for the lines of a method body that hold code, comments
    stripped. `first` is the line the body starts on."""
    for n, line in enumerate(_abap.strip_comments(body).split("\n"), first):
        if line:
            yield n, line


def scan(text):
    """[(method, lineno, path, clobbered_by_line, narrow_path)]."""
    return [hit for body in _abap.method_bodies(text)
            for hit in _clobbers(body, text.count("\n", 0, body.start) + 1)]


def _clobbers(body, first_line):
    """The clobbered writes of one method body, its first line FIRST_LINE."""
    out, written, depth = [], {}, 0      # written: path -> (lineno, depth it was written at)
    for n, line in code_lines(body.body, first_line):
        depth, written = _block(line, depth, written)
        if m := WHOLESALE.match(line):
            target = m.group(1).lower()
            out += [(body.name, at, path, n, target) for path, (at, _) in sorted(written.items())
                    if path.startswith(target + "-")]
            written = {p: v for p, v in written.items() if not p.startswith(target + "-")}
        for m in WRITE.finditer(line):
            written.setdefault(next(g for g in m.groups() if g).lower(), (n, depth))
    return out


def _block(line, depth, written):
    """The block depth after LINE, and the writes still comparable with what
    follows: a write inside a block just closed, or in the arm just left, may
    be one arm of an alternative."""
    if BLOCK_CLOSE.match(line):
        depth = max(0, depth - 1)
        return depth, {p: v for p, v in written.items() if v[1] <= depth}
    if BLOCK_ARM.match(line):
        return depth, {p: v for p, v in written.items() if v[1] < depth}
    if BLOCK_OPEN.match(line):
        return depth + 1, written
    return depth, written


def check_clobbered():
    bad = []
    for name, text in abap_files().items():
        for method, at, path, clobber_at, target in scan(text):
            bad.append(Finding(f"{name}:{clobber_at}  {method}: {path} written at line {at}, "
                               f"then {target} assigned wholesale", f"{name}:{clobber_at} {path}"))
    return bad, [f"{len(abap_files())} file(s) scanned"]


CHECKS = [("clobbered", "no field write discarded by a wholesale one", check_clobbered)]


if __name__ == "__main__":
    exit_with(run(SCRIPT, CHECKS, suppressed, empty=EMPTY))
