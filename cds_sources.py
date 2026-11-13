#!/usr/bin/env python3
"""Data-source references under a CDS view, counted through the whole stack.

    python3 cds_sources.py ZC_SOME_VIEW [ZI_OTHER ...]
    python3 cds_sources.py --views legacy/cds_views --amdp legacy/classes ZC_X

A measurement, not a check: it prints and exits 0.

WHY THIS EXISTS
---------------
"How many tables does this view drag into every statement" should be counted,
not estimated: every `from` / `join` is expanded until it reaches something
that is not a view in the corpus, and each reference counts once per
occurrence, the way the statement text contains it.

A table function is expanded through its AMDP body: every `from` / `join` in
the method's SQLScript that names an object of its USING list, once per
occurrence. The body runs with the statement, so leaving it out hides most of
the cost: one legacy stack read 690 references in the statement text and
5,788 with its three functions' bodies. String literals are blanked first, so
a label such as 'Extract Data from MBEW' is not a source.

WHERE IT READS
  --views DIR   view sources: *.asddls, and *.txt (copies pasted from ADT);
                default [cds_sources] views, else the package's own ddls
  --amdp DIR    classes holding AMDP bodies: *.abap and *.txt; default
                [cds_sources] amdp, else the package's ABAP

What it does not see: what SAP views read underneath (they are leaves here, so
the physical table count is higher). Whether HANA reads a repeated subtree
once or several times is a plan question; ADT's Dependency Analyzer gives
SAP's own count.
"""
import collections
import re
import sys
from pathlib import Path

from _config import _consume, path

SOURCE = re.compile(r"\b(?:from|join)\s+([A-Za-z_/][\w/]*)\b", re.I)
AMDP = re.compile(r"FOR\s+TABLE\s+FUNCTION\s+(\w+).*?USING\s+([\w/\s]+?)\.(.*?)ENDMETHOD",
                  re.I | re.S)


def _dir(flag, key):
    given = _consume(sys.argv, flag)
    return Path(given[-1]).resolve() if given else path(key)


def _read(folder, patterns):
    if not folder or not folder.is_dir():
        return {}
    return {p.name.split(".")[0].upper(): p.read_text(errors="ignore")
            for pat in patterns for p in sorted(folder.rglob(pat))}


VIEWS_DIR = _dir("--views", "cds_sources.views")
AMDP_DIR = _dir("--amdp", "cds_sources.amdp")

if VIEWS_DIR:
    VIEWS = _read(VIEWS_DIR, ("*.asddls", "*.txt"))
else:
    from _pkg import cds_files
    VIEWS = {k.upper(): v for k, v in cds_files("ddls").items()}
if AMDP_DIR:
    CLASSES = _read(AMDP_DIR, ("*.abap", "*.txt"))
else:
    from _pkg import abap_files
    CLASSES = abap_files()


def _functions():
    """{table function: its body's sources}, from the AMDP classes."""
    bodies = {}
    for text in CLASSES.values():
        for name, using, body in AMDP.findall(text):
            body = re.sub(r"^\*.*$", "", body, flags=re.M)
            body = re.sub(r"--.*", "", body)
            body = re.sub(r"'[^'\n]*'", "''", body)
            allowed = {u.upper() for u in using.split()}
            bodies[name.upper()] = [m.upper() for m in SOURCE.findall(body)
                                    if m.upper() in allowed]
    return bodies


FUNCTIONS = _functions()


def sources(name):
    if name in FUNCTIONS:
        return FUNCTIONS[name]
    text = re.sub(r"/\*.*?\*/", "", VIEWS[name], flags=re.S)
    text = re.sub(r"//.*", "", text)
    text = re.sub(r"'[^'\n]*'", "''", text)
    return [m.upper() for m in SOURCE.findall(text)]


def expand(name, path_=()):
    leaves = collections.Counter()
    for src in sources(name):
        expandable = src in FUNCTIONS or (
            src in VIEWS and "table function" not in VIEWS[src].lower())
        if expandable and src not in path_:
            leaves += expand(src, path_ + (name,))
        else:
            leaves[src] += 1
    return leaves


def main(names):
    if not names:
        print(__doc__.strip().split("\n\n")[0])
        return 2
    for name in names:
        if name.upper() not in VIEWS and name.upper() not in FUNCTIONS:
            print(f"{name.upper()}: not among {len(VIEWS)} view(s) read from "
                  f"{VIEWS_DIR or 'the package'}")
            continue
        leaves = expand(name.upper())
        print(f"{name.upper()}: {sum(leaves.values())} data-source references")
        for src, n in leaves.most_common():
            print(f"  {n:4}  {src}")
    return 0


if __name__ == "__main__":
    sys.exit(main([a for a in sys.argv[1:] if not a.startswith("-")]))
