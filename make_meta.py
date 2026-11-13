#!/usr/bin/env python3
"""Emit the abapGit metadata for classes, interfaces, programs, message
classes and the root package.

    python3 make_meta.py            # write *.clas.xml, *.intf.xml, *.prog.xml, *.msag.xml
    python3 make_meta.py --check    # regenerate into memory and report differences

Same bargain as make_ddic.py: the description belongs in one readable table
rather than in twenty XML files, and `--check` proves the two still agree.

A source file with no entry is a finding, not a default -- an object whose
description is "" reaches SE24 nameless and stays that way.

THE DEFINITION (abapcheck.toml)
  [meta] package        the root package's description (package.devc.xml)
  [meta.interfaces]     name = "description"
  [meta.classes]        name = "description"
  [meta.exceptions]     name = "description" (exception classes, category 40)
  [meta.programs]       name = "title"
  [[meta.msgclass]]     name, text, messages = [["001", "text &1"], ...]

The &1..&4 count in a message text must equal the operand count of the WITH
clause at each raise site -- check_messages.py compares them.
"""

import sys

import _gen
from _config import ROOT, get
from _gen import HEAD, TAIL, esc
from _pkg import object_files

PACKAGE = get("meta.package")
INTERFACES = {k.lower(): v for k, v in get("meta.interfaces", {}).items()}
CLASSES = {**{k.lower(): (v, False) for k, v in get("meta.classes", {}).items()},
           **{k.lower(): (v, True) for k, v in get("meta.exceptions", {}).items()}}
PROGRAMS = {k.lower(): v for k, v in get("meta.programs", {}).items()}
MSGCLASSES = [(m["name"], m["text"], [tuple(r) for r in m.get("messages", [])])
              for m in get("meta.msgclass", [])]

# T100-TEXT is CHAR 73: a longer text is cut off on import, and nothing else
# says so.
T100_TEXT = 73


def intf(name, description):
    return "".join([
        HEAD.format(ser="LCL_OBJECT_INTF"), "   <VSEOINTERF>\n",
        f"    <CLSNAME>{name.upper()}</CLSNAME>\n", "    <LANGU>E</LANGU>\n",
        f"    <DESCRIPT>{esc(description)}</DESCRIPT>\n",
        "    <EXPOSURE>2</EXPOSURE>\n", "    <STATE>1</STATE>\n",
        "    <UNICODE>X</UNICODE>\n", "   </VSEOINTERF>\n", TAIL])


def clas(name, description, exception):
    out = [HEAD.format(ser="LCL_OBJECT_CLAS"), "   <VSEOCLASS>\n",
           f"    <CLSNAME>{name.upper()}</CLSNAME>\n", "    <LANGU>E</LANGU>\n",
           f"    <DESCRIPT>{esc(description)}</DESCRIPT>\n",
           "    <STATE>1</STATE>\n", "    <CLSCCINCL>X</CLSCCINCL>\n",
           "    <FIXPT>X</FIXPT>\n", "    <UNICODE>X</UNICODE>\n"]
    if exception:
        out.append("    <CATEGORY>40</CATEGORY>\n")
    out += ["   </VSEOCLASS>\n"]
    return "".join(out) + TAIL


def prog(name, title):
    return "".join([
        HEAD.format(ser="LCL_OBJECT_PROG"), "   <PROGDIR>\n",
        f"    <NAME>{name.upper()}</NAME>\n", "    <STATE>A</STATE>\n",
        "    <VARCL>X</VARCL>\n", "    <SUBC>1</SUBC>\n",
        "    <RLOAD>E</RLOAD>\n", "    <FIXPT>X</FIXPT>\n",
        "    <UCCHECK>X</UCCHECK>\n", "   </PROGDIR>\n", "   <TPOOL>\n",
        "    <item>\n", "     <ID>R</ID>\n",
        f"     <ENTRY>{esc(title)}</ENTRY>\n",
        f"     <LENGTH>{len(title)}</LENGTH>\n", "    </item>\n",
        "   </TPOOL>\n", TAIL])


def msag(name, description, rows):
    out = [HEAD.format(ser="LCL_OBJECT_MSAG"), "   <T100A>\n",
           f"    <ARBGB>{name}</ARBGB>\n",
           f"    <STEXT>{esc(description)}</STEXT>\n",
           "    <MASTERLANG>E</MASTERLANG>\n", "   </T100A>\n", "   <T100>\n"]
    for number, text in rows:
        out += ["    <T100>\n", "     <SPRSL>E</SPRSL>\n",
                f"     <ARBGB>{name}</ARBGB>\n", f"     <MSGNR>{number}</MSGNR>\n",
                f"     <TEXT>{esc(text)}</TEXT>\n", "    </T100>\n"]
    out.append("   </T100>\n")
    return "".join(out) + TAIL


def devc(description):
    return "".join([HEAD.format(ser="LCL_OBJECT_DEVC"), "   <DEVC>\n",
                    f"    <CTEXT>{esc(description)}</CTEXT>\n", "   </DEVC>\n",
                    TAIL])


def generate():
    files = {"package.devc.xml": devc(PACKAGE)} if PACKAGE else {}
    for name, text, rows in MSGCLASSES:
        files[f"{name.lower()}.msag.xml"] = msag(name, text, rows)
    for name, description in INTERFACES.items():
        files[f"{name}.intf.xml"] = intf(name, description)
    for name, (description, exception) in CLASSES.items():
        files[f"{name}.clas.xml"] = clas(name, description, exception)
    for name, title in PROGRAMS.items():
        files[f"{name}.prog.xml"] = prog(name, title)
    return files


def validate():
    """A source file with no description, a description with no source, or a
    message text longer than T100 holds."""
    bad = []
    described = set(INTERFACES) | set(CLASSES) | set(PROGRAMS)
    on_disk = set()
    for suffix, kind in (("intf.abap", INTERFACES), ("clas.abap", CLASSES),
                         ("prog.abap", PROGRAMS)):
        for name, path in object_files(suffix).items():
            on_disk.add(name)
            if name not in kind:
                bad.append(f"{path.name}: no description in [meta]")
    bad += [f"{n}: described here, but no source file" for n in sorted(described - on_disk)]
    bad += [f"message {c} {n}: {len(t)} characters, T100 holds {T100_TEXT}"
            for c, _, rows in MSGCLASSES for n, t in rows if len(t) > T100_TEXT]
    return bad


def main():
    _gen.reject_unknown_args(__doc__)
    if not (PACKAGE or INTERFACES or CLASSES or PROGRAMS or MSGCLASSES):
        print("--  no [meta] definition in abapcheck.toml: nothing to generate")
        return 0
    bad = validate()
    for line in bad:
        print(f"  ✗ {line}")
    if bad:
        print(f"\n{len(bad)} metadata error(s) -- nothing written")
        return len(bad)

    files = generate()
    if "--check" in sys.argv:
        return _gen.check(files, ROOT)

    _gen.write(files, ROOT)
    print(f"{len(INTERFACES)} interface(s), {len(CLASSES)} class(es), "
          f"{len(PROGRAMS)} program(s), {len(MSGCLASSES)} message class(es) -> {ROOT}")
    return 0


if __name__ == "__main__":
    sys.exit(min(main(), 250))
