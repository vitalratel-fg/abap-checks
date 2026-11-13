#!/usr/bin/env python3
r"""Every method that is a stub or is blocked, and on what.

    python3 check_stubs.py            # table to stdout
    python3 check_stubs.py --md       # Markdown, grouped by open point

A REPORT, NOT A GATE: the exit code is the row count, and a package in
progress has rows. check_all.py leaves it out unless asked.

WHY THIS EXISTS
---------------
"Which methods are not finished?" was answered three times by hand, from
three different greps, and got three different counts -- once because a
grep for `BLOCKED` misses the methods that carry no marker at all (their
bodies are simply prose), once because METHOD/ENDMETHOD spans were eyeballed
across a 300-line file. Same lesson as check_standing.py's header.

WHAT COUNTS
-----------
Two independent axes, and a method can be either, both, or neither:

  EMPTY    the body between METHOD and ENDMETHOD has no executable ABAP
           statement -- comments only, or nothing. Section 3 of a design
           package is allowed to have these; the point is knowing which.
  BLOCKED  the method, or the declaration comment attached to it, cites an
           open point (`[stubs] blockers`, e.g. `\bOPEN-(\d+)\b`) or says
           BLOCKED / OPEN / CONFIRM outright.

A method that is EMPTY but not BLOCKED is unfinished WORK. A method that is
BLOCKED is unfinished DECISION -- no amount of typing closes it. They need
different handling, so the report keeps them apart.

The `!` doc comments above a declaration are attributed to the method they
introduce, because that is where blockers are recorded.
"""

import re
import sys
from collections import defaultdict

import _abap
from _config import get
from _pkg import abap_files, kind

# The package's open-point citation, `[stubs] blockers`. Package vocabulary,
# not a universal one, so there is no default: a bare token pattern matches
# ordinary code -- `\bB[1-4]\b` once matched a batch number in a test
# fixture. Unset, only the markers below make a method BLOCKED.
_BLOCKERS = get("stubs.blockers")
ITEM_RE = re.compile(_BLOCKERS, re.I) if _BLOCKERS else None
# `OPEN` alone matches OPEN DATASET, and `CONFIRM` alone matches
# POPUP_TO_CONFIRM - both were false positives on the first run. Require the
# punctuation the package actually uses when recording an open point.
MARKER_RE = re.compile(
    r"\b(BLOCKED|UNCONFIRMED|UNVERIFIED|NOT DECIDED|NOT WRITTEN|TODO)\b"
    r"|\bOPEN\s*[(:,]|\bSTILL OPEN\b|\bCONFIRM\s+(BEFORE|ONCE|AGAINST)\b")

# The package's own words for "empty on purpose". A no-op base hook is not
# unfinished work, and counting it as such is the fastest way to make this
# output ignorable. The claim is that someone looked, and the class says so
# in the body.
INTENTIONAL_RE = re.compile(r"INTENTIONALLY EMPTY|not a sketch", re.I)

# Lexing lives in _abap.py - one module knows what an ABAP statement looks
# like, and these two names stay so the checks below read unchanged.
code_lines = _abap.code_lines


def strip_comments(body):
    return " ".join(code_lines(body))


# A declaration's RETURNING parameter, wherever that declaration lives.
RETURNING_RE = re.compile(r"RETURNING\s+VALUE\((\w+)\)", re.I)

# Branch openers whose arm may legitimately be empty in real code, and the
# tokens that close an arm.
BRANCH_OPEN_RE = re.compile(r"^(WHEN\b|ELSEIF\b|ELSE\b)", re.I)
BRANCH_CLOSE_RE = re.compile(r"^(WHEN\b|ELSEIF\b|ELSE\b|ENDCASE\b|ENDIF\b)", re.I)


def returning_params(files):
    """{method name: returning param} for every declaration in the package.

    Package-wide because a REDEFINITION's signature lives in the interface
    file, not the class implementing it. Ambiguous names are dropped rather
    than guessed: two declarations of one name make the check unreliable,
    and an unreliable check is worse than a missing one.
    """
    seen, dupes = {}, set()
    for d in (d for text in files.values() for d in _abap.declarations(text)):
        name = d.name.lower().split("~")[-1]
        rv = RETURNING_RE.search(d.sig)
        val = rv.group(1) if rv else None
        if name in seen and seen[name] != val:
            dupes.add(name)
        seen[name] = val
    return {k: v for k, v in seen.items() if v and k not in dupes}


def result_never_assigned(body, rv_name):
    """The method has a result to produce and never mentions it in code.

    THE FALSE NEGATIVE THIS EXISTS FOR. `SURCHARGE_FOR` opened with

        IF has_rec_surcharge( io_ctx ) = abap_false.
          RETURN.
        ENDIF.
        " <twenty lines of prose describing the lookup, never written>

    Three executable statements, so "no executable statement" called it
    WRITTEN and it appeared nowhere in the report. A guard clause is not an
    implementation: if RV_KBETR2 is never so much as named in executable
    code, the method cannot produce a result, whatever else it runs.

    Deliberately a mention test, not an assignment test - RV_ names are also
    passed to helpers as CHANGING, and demanding `rv_x =` would fire on
    correct code.
    """
    if not rv_name:
        return False
    return not any(re.search(rf"\b{re.escape(rv_name)}\b", s, re.I)
                   for s in code_lines(body))


def has_empty_branch(body):
    """A WHEN / ELSE arm containing comments and nothing else.

A method with one written branch and a CASE whose other arms are pure
    comment runs real code and reads as finished. An arm that executes
    nothing is a sketch regardless of what its neighbours do.

    An arm that is empty AND has no comment in it is fall-through - ABAP's
    `WHEN x. WHEN y.` idiom - so it does not count.
    """
    lines = [l.strip() for l in body.splitlines() if l.strip()]
    return any(BRANCH_OPEN_RE.match(line) and _only_comments(lines[i + 1:])
               for i, line in enumerate(lines))


def _only_comments(rest):
    """The arm REST opens holds comments and nothing else before it closes; an
    arm with neither is fall-through, and one with a statement is written."""
    commented = False
    for line in rest:
        if BRANCH_CLOSE_RE.match(line):
            return commented
        if line[:1] not in ('"', '*'):
            return False
        commented = True
    return False


def doc_comment_above(text, pos):
    """The contiguous `"!` / `"` comment block immediately above `pos`.

    POS MUST POINT INSIDE THE DECLARATION LINE, not at its start. The `[:-1]`
    below drops the partial line `pos` sits in; hand it a line-start offset
    and it drops the line ABOVE instead - the nearest comment line, which is
    where the `OPEN-n` citation almost always sits, so every cited
    declaration silently reads as uncited.
    """
    assert pos <= 0 or text[pos - 1:pos] != "\n", \
        "doc_comment_above needs an in-line offset; see the docstring"
    head = text[:pos].splitlines()
    block = []
    for line in reversed(head[:-1] if head else []):
        s = line.strip()
        if s.startswith('"') or s.startswith("*"):
            block.append(s)
        elif not s:
            break
        else:
            break
    return "\n".join(reversed(block))


# An answered blocker still says the word: "NOT BLOCKED - OPEN-8, answered"
# kept reporting, because "NOT BLOCKED" contains "BLOCKED". A resolution
# marker wins over a blocker marker on the same line/block - the answer is
# written where the question was, so both words coexist by design.
RESOLVED_RE = re.compile(r"\bNOT BLOCKED\b|\bANSWERED\b|\bRESOLVED\b|\bCONFIRMED\b",
                         re.I)


def cites(text):
    """Every OPEN-n cited, MINUS the ones cited as answered.

    A method keeps citing an item after it is resolved - the answer is
    written where the question was, and a class that stops naming the item it
    was blocked on loses the trail. So the citation alone cannot mean
    "blocked".

    The absent-method scan below learned this earlier (see RESOLVED_RE); this
    is the same rule at CITATION granularity rather than block granularity,
    because one method can cite an answered item and an open one in adjacent
    lines.

    LIMIT: the marker must be on the SAME LINE as the citation. A
    resolution two lines below still reports blocked, which is the safe
    direction - it over-reports rather than hiding work.
    """
    items = set()
    if ITEM_RE is None:
        return items
    for line in text.splitlines():
        found = {" ".join(m.group(0).split()).upper() for m in ITEM_RE.finditer(line)}
        if found and RESOLVED_RE.search(line):
            continue
        items |= found
    return items


def scan():
    """[{file, method, empty, blocked, items, why}] for the whole package."""
    rows = []
    files = abap_files()
    rv_of = returning_params(files)
    for path, text in files.items():
        notes = _decl_notes(text)
        rows += absent(path, text)
        # Interface files have declarations and no bodies at all.
        rows += _interface_rows(path, notes) if kind(path) == "intf" \
            else [r for b in _abap.method_bodies(text) if (r := _method_row(path, b, notes, rv_of))]
    return rows


def _decl_notes(text):
    """{method: the doc comments above its declarations}. Declarations carry
    the doc comments; implementations carry bodies."""
    notes = {}
    for d in _abap.declarations(text):
        notes[d.name.lower()] = notes.get(d.name.lower(), "") + "\n" + doc_comment_above(text, d.offset)
    return notes


def _interface_rows(path, notes):
    """A row for each declaration that is cited or marked.

    The admission test is "cited OR marked", so the verdict must be too - it
    used to be blocked=bool(items), which classified a marker-only
    declaration as EMPTY-not-blocked: "unfinished work" for something whose
    whole point is that it is marked. And an interface declaration has no
    body, so empty is not a question that can be asked of it. Mirrors
    `_method_row`.
    """
    return [dict(file=path, method=name.upper(), empty=False, blocked=True,
                 items=sorted(items), why=first_sentence(note))
            for name, note in notes.items() if (items := cites(note)) or MARKER_RE.search(note)]


def _method_row(path, b, notes, rv_of):
    """The row for one method body, or None when it is neither empty nor blocked."""
    note = notes.get(b.name.lower(), "")
    blob = b.body + "\n" + note
    if INTENTIONAL_RE.search(b.body):
        return None
    items, marked = cites(blob), bool(MARKER_RE.search(blob))
    empty = (not strip_comments(b.body)
             or result_never_assigned(b.body, rv_of.get(b.name.lower().split("~")[-1]))
             or has_empty_branch(b.body))
    if not (empty or items or marked):
        return None
    return dict(file=path, method=b.name.upper(), empty=empty, blocked=bool(items) or marked,
                items=sorted(items), why=first_sentence(b.body) or first_sentence(note))


ABSENT_RE = re.compile(r"\bBLOCKED\b|\bNOT WRITTEN\b|\bnot written out here\b", re.I)


def absent(path, text):
    """Blockers recorded where NO method exists - the ones a method scan misses.

    The most expensive kind: a requirement recorded in a class whose body is
    empty, or a note at the foot of a file. Nothing to grep for a signature,
    so scan the comment blocks that live OUTSIDE any METHOD ... ENDMETHOD
    span.
    """
    spans = [(b.start, b.end) for b in _abap.method_bodies(text)]
    rows = []
    for start, block in _comment_blocks(text):
        if len(block) < 4 or any(a <= start <= b for a, b in spans):
            continue
        blob = "\n".join(block)
        # Two kinds of block are NOT an absent method: the class header
        # (`shorttext`), and a `"!` doc comment, which belongs to the
        # declaration below it and the decl scan already has.
        is_header = "shorttext" in blob
        is_doc = all(l.startswith('"!') for l in block)
        if (ABSENT_RE.search(blob) and not RESOLVED_RE.search(blob)
                and not is_header and not is_doc):
            rows.append(dict(file=path, method="(no method)", empty=True,
                             blocked=True, items=sorted(cites(blob)),
                             why=first_sentence(blob)))
    return rows


def _comment_blocks(text):
    """(offset, stripped lines) of every run of full-line comments, the last
    one included: a note on the file's final lines has no code after it to
    end it, and waiting for that line lost the note at the foot of a file."""
    block, start, offs = [], 0, 0
    for line in text.splitlines(keepends=True):
        s = line.strip()
        if s.startswith(("*", '"')):
            if not block:
                start = offs
            block.append(s)
        elif block:
            yield start, block
            block = []
        offs += len(line)
    if block:
        yield start, block


def first_sentence(comment):
    """The first real line of a comment block, trimmed of its markers."""
    for line in comment.splitlines():
        s = line.strip().lstrip("*").lstrip('"').lstrip("!").strip()
        if len(s) > 12 and not s.startswith("---"):
            return s[:110]
    return ""


def main():
    rows = scan()
    if "--md" in sys.argv:
        _print_by_item(rows)
    else:
        _print_table(rows)
    return len(rows)


def _print_table(rows):
    for r in sorted(rows, key=lambda r: (r["file"], r["method"])):
        flags = ("E" if r["empty"] else "-") + ("B" if r["blocked"] else "-")
        print(f"{flags}  {r['file']:52} {r['method']:34} {','.join(r['items'])}")
    empty, blocked = sum(r["empty"] for r in rows), sum(r["blocked"] for r in rows)
    both = sum(r["empty"] and r["blocked"] for r in rows)
    print(f"\n{len(rows)} methods: {empty} empty, {blocked} blocked, {both} both")


def _print_by_item(rows):
    """Markdown: each open point, then the blocked methods citing it."""
    by_item = defaultdict(list)
    for r in (r for r in rows if r["blocked"]):
        for it in r["items"]:
            by_item[it].append(r)
    for it in sorted(by_item, key=_order):
        print(f"### {it}")
        for r in by_item[it]:
            print(f"- `{r['method']}` — {r['file']}")


def _order(key):
    """Natural order: `OPEN-2` before `OPEN-10`, `11A` before `11B`.

    Lexicographic order puts OPEN-10 before OPEN-2, which reads as a
    register that skipped eight questions. A sub-letter stays part of the
    key -- OPEN-11a and OPEN-11b are independent questions.
    """
    return [(0, int(p), "") if p.isdigit() else (1, 0, p)
            for p in re.split(r"(\d+)", key)]


if __name__ == "__main__":
    # The row count IS the exit code. It was `0 if main() else 1`, which
    # exits 1 when NOTHING is unfinished - so a package with no stubs left
    # failed the run on the day it became clean.
    sys.exit(min(main(), 250))
