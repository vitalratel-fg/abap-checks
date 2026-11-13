"""The one ABAP lexer the checks share.

Eleven hand-written regexes for "find a method" across two scripts disagreed
with each other: one hardcoded two spaces of indent, three required whitespace
after METHODS so a chained declaration was invisible, only some handled
CLASS-METHODS or `zif~name`. One place now knows what an ABAP declaration
looks like; a form these miss is fixed HERE, once.

NOT A PARSER. A careful line lexer, with those limits: literals are blanked
but not otherwise tracked, no macro expansion, a period followed by
whitespace ends a statement. A
construct that breaks it is fixed by teaching this module, never by a local
regex in a check -- a local regex is how there came to be eleven.
"""

import re
from collections import namedtuple

Decl = namedtuple("Decl", "name sig is_redef is_static offset")
Body = namedtuple("Body", "name body start end")

# A statement head: optional CLASS- prefix, the keyword, optional chain colon.
_METHODS_HEAD = re.compile(r"^([ \t]*)(CLASS-)?METHODS[ \t]*(:)?[ \t]*", re.I | re.M)
_METHOD_OPEN = re.compile(r"^[ \t]*METHOD[ \t]+([\w~/]+)[ \t]*\.", re.I | re.M)
_METHOD_CLOSE = re.compile(r"^[ \t]*ENDMETHOD[ \t]*\.", re.I | re.M)
_SECTION = re.compile(r"^[ \t]*(PUBLIC|PROTECTED|PRIVATE)[ \t]+SECTION[ \t]*\.",
                      re.I | re.M)


def strip_comments(text):
    """Text with full-line `"`/`*` comments and trailing `"` comments removed.

    Naive about string literals containing a double quote, and deliberately
    so: they are rare in hand-written ABAP, and the alternative is a lexer
    that has to know about them everywhere. One in a `|...|` template drops
    the rest of its line from the scan.
    """
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith('"') or s.startswith("*"):
            out.append("")
            continue
        out.append(s.split('"')[0].rstrip())
    return "\n".join(out)


def code_lines(text):
    """Non-blank executable lines. `strip_comments` keeps blanks for offsets."""
    return [l.strip() for l in strip_comments(text).splitlines() if l.strip()]


def statements(text):
    """(lineno, statement) per statement: comments stripped, literals blanked,
    whitespace collapsed, the closing period dropped.

    A statement ends at a period followed by whitespace or the end of the
    text, so `a = 1. b = 2.` is two statements and `1.5` is none. Literals are
    blanked first because a period inside one ends nothing: `'x.'` becomes
    `''`, and a template keeps only its embedded expressions.
    """
    text = strip_comments(text)
    text = re.sub(r"'[^'\n]*'", "''", text)
    text = re.sub(r"\|[^|\n]*\|",
                  lambda m: " ".join(re.findall(r"\{([^}]*)\}", m.group(0))), text)
    out, start = [], 0
    for m in [*re.finditer(r"\.(?=\s|$)", text), None]:
        end = m.start() if m else len(text)
        chunk = text[start:end]
        if chunk.strip():
            lead = len(chunk) - len(chunk.lstrip())
            out.append((text.count("\n", 0, start + lead) + 1, " ".join(chunk.split())))
        start = end + 1
    return out


_CONST_GROUP = re.compile(r"(?is)BEGIN OF\s+(\w+)\s*,(.*?)END OF\s+\1")


def constant_groups(text):
    """[(group, block)] for every `BEGIN OF g, ... END OF g` structure."""
    return _CONST_GROUP.findall(text)


# `name TYPE t [LENGTH n] [DECIMALS n] VALUE v`: a member typed `c LENGTH 1`
# was invisible to a pattern wanting VALUE right after the type, and that is
# the member `deadconst` exists for -- typed by nothing that gives it meaning.
_CONST_MEMBER = re.compile(r"(?im)^\s*(\w+)\s+TYPE\s+([\w=>~]+)(?:\s+LENGTH\s+\d+)?"
                           r"(?:\s+DECIMALS\s+\d+)?\s+VALUE\s+('[^']*'|[^\s,.]+)")


def constant_members(block):
    """(member, type, value) for each member of a constant group's BLOCK; a
    literal value without its quotes."""
    return [(n, t, v[1:-1] if v.startswith("'") else v)
            for n, t, v in _CONST_MEMBER.findall(block)]


def scalar_constants(text):
    """(name, type) for every constant outside a `BEGIN OF` group, chains
    expanded: `CONSTANTS: a TYPE i VALUE 1, b TYPE i VALUE 2.` declares both."""
    return typed_names(text, "CONSTANTS")


def declaration_part(text, kind):
    """The part of an object of KIND (`_pkg.kind`) where declarations live.

    A class: everything before the first ENDCLASS -- the implementation part
    declares LOCALS, and counting those as exposed members is how the
    `qualified` check would let `zcl_x=>lv_something` pass. An interface: the
    whole file, it has no implementation. The kind comes from the file
    suffix, never from the name: `INTERFACE z...` matched no package whose
    names start otherwise.
    """
    return text if kind == "intf" else text.split("ENDCLASS.")[0]


_CLASS_HEAD = re.compile(r"^[ \t]*CLASS[ \t]+(\w+)[ \t]+(DEFINITION|IMPLEMENTATION)\b([^.]*)\.",
                         re.I | re.M)
_CLASS_END = re.compile(r"^[ \t]*ENDCLASS[ \t]*\.", re.I | re.M)


class ClassDef:
    """One `CLASS x DEFINITION ... ENDCLASS.`: what a class says about itself.

    THE HEAD STATEMENT IS READ, NOT THE FILE. `INHERITING FROM` searched
    across a class's files made a local helper's parent the global class's,
    and a head matched only at column 0 missed an indented ABSTRACT class.
    Four regexes for a class head in one script disagreed on both.
    """

    def __init__(self, name, additions, block):
        self.name = name.lower()
        self.additions = " ".join(additions.split()).upper()
        self.block = block              # between the head and ENDCLASS

    @property
    def abstract(self):
        return bool(re.search(r"\bABSTRACT\b", self.additions))

    @property
    def for_testing(self):
        return "FOR TESTING" in self.additions

    @property
    def parent(self):
        m = re.search(r"\bINHERITING FROM (\w+)", self.additions)
        return m.group(1).lower() if m else None

    def section(self, vis):
        return section(self.block, vis)

    def methods(self, vis=None):
        """Every METHODS declaration, of one visibility or of all."""
        visibilities = [vis] if vis else ["PUBLIC", "PROTECTED", "PRIVATE"]
        return [d for v in visibilities for d in declarations(self.section(v))]

    def constructor(self):
        """The instance constructor's declaration, or None."""
        return next((d for d in self.methods() if d.name.lower() == "constructor"), None)

    def interfaces(self):
        """{interface: deferred methods} for every INTERFACES statement, chains
        expanded: ALL for `ALL METHODS ABSTRACT`, else the set `ABSTRACT
        METHODS` names (empty for none)."""
        out = {}
        for _, stmt in statements(self.block):
            m = re.match(r"INTERFACES\b\s*:?\s*(.*)", stmt, re.I)
            for part in split_chain(m.group(1)) if m else []:
                name, _, add = part.strip().partition(" ")
                out[name.lower()] = _deferred(add)
        return out


ALL = "ALL"


def _deferred(additions):
    if re.search(r"\bALL METHODS ABSTRACT\b", additions, re.I):
        return ALL
    m = re.search(r"\bABSTRACT METHODS\s+([\w\s]+)", additions, re.I)
    return {w.lower() for w in m.group(1).split()} if m else set()


def class_definitions(code):
    """Every class CODE (comments stripped) defines, in order. A DEFERRED,
    LOCAL FRIENDS or LOAD statement names a class without defining it."""
    out = []
    for head in _CLASS_HEAD.finditer(code):
        additions = head.group(3).upper()
        if head.group(2).upper() != "DEFINITION" or \
                re.search(r"\b(DEFERRED|LOCAL FRIENDS|LOAD)\b", additions):
            continue
        end = _CLASS_END.search(code, head.end())
        out.append(ClassDef(head.group(1), head.group(3),
                            code[head.end():end.start() if end else len(code)]))
    return out


def global_class(code, name):
    """The class definition named NAME (an object's own class), or None."""
    return next((c for c in class_definitions(code) if c.name == name.lower()), None)


def class_implementation(code, name):
    """The text of `CLASS name IMPLEMENTATION.` up to its ENDCLASS, or ''."""
    for head in _CLASS_HEAD.finditer(code):
        if head.group(1).lower() == name.lower() and head.group(2).upper() == "IMPLEMENTATION":
            end = _CLASS_END.search(code, head.end())
            return code[head.end():end.start() if end else len(code)]
    return ""


def section(text, name):
    """One visibility section's text, or '' when absent."""
    marks = [(m.group(1).upper(), m.end()) for m in _SECTION.finditer(text)]
    for i, (kind, start) in enumerate(marks):
        if kind != name.upper():
            continue
        end = marks[i + 1][1] if i + 1 < len(marks) else len(text)
        end = min(end, text.find("ENDCLASS.") if "ENDCLASS." in text else len(text))
        return text[start:end]
    return ""


def declarations(text):
    """Every METHODS declaration, chains expanded.

    THE CHAIN IS THE POINT. `METHODS: a IMPORTING ..., b RETURNING ...` is
    one statement declaring two methods, and three call sites in
    check_standing.py silently saw neither because they required whitespace
    after METHODS. Each returned Decl carries its own signature slice, so
    RAISING / REDEFINITION tests work per method rather than per statement.
    """
    out = []
    for head in _METHODS_HEAD.finditer(text):
        chained = bool(head.group(3))
        rest = text[head.end():]
        # A statement ends at the first period that ends a line.
        stop = re.search(r"\.[ \t]*(?:\"[^\n]*)?$", rest, re.M)
        stmt = rest[:stop.start()] if stop else rest
        # Within a chain, members are comma-separated at depth 0.
        parts = split_chain(stmt) if chained else [stmt]
        pos = head.end()
        for part in parts:
            m = re.match(r"[ \t\n]*([\w~]+)", part)
            if not m:
                pos += len(part) + 1
                continue
            out.append(Decl(name=m.group(1),
                            sig=part[m.end():],
                            is_redef=bool(re.search(r"\bREDEFINITION\b", part, re.I)),
                            is_static=bool(head.group(2)),
                            offset=pos))
            pos += len(part) + 1
    return out


def chain_parts(text, keyword):
    """(depth, member) for each member of every KEYWORD statement in TEXT
    (`TYPES`, `DATA`, `CONSTANTS`, ...), chains expanded and in order. DEPTH
    counts the `BEGIN OF` structures open around the member, across
    statements and chains alike: `BEGIN OF x` itself is at the depth it
    opens from, its `END OF` at the depth it closes to."""
    depth = 0
    for part in (p.strip() for _, stmt in statements(text) for p in _members(stmt, keyword)):
        if re.match(r"(?i)END\s+OF\b", part):
            depth = max(0, depth - 1)
        yield depth, part
        if re.match(r"(?i)BEGIN\s+OF\b", part):
            depth += 1


def _members(stmt, keyword):
    """The chain members of STMT when it is a KEYWORD statement, else none."""
    m = re.match(rf"(?:{keyword})\b\s*:?\s*(.*)", stmt, re.I)
    return split_chain(m.group(1)) if m else []


def typed_names(text, keyword):
    """(name, type) for each `name TYPE t` member of KEYWORD statements outside
    any structure."""
    return [m.groups() for depth, part in chain_parts(text, keyword) if depth == 0
            and (m := re.match(r"(?i)(\w+)\s+TYPE\s+([\w=>~]+)", part))]


def data_names(text):
    """The names DATA and CLASS-DATA statements in TEXT declare with TYPE,
    chains expanded: `DATA: a TYPE i, b TYPE i.` declares both, and a regex
    for `DATA name TYPE` saw only the first. The components of a
    `BEGIN OF ... END OF` structure are not names of their own."""
    return [name for name, _ in typed_names(text, "(?:CLASS-)?DATA")]


def split_chain(stmt):
    """Split a chained declaration on top-level commas.

    Depth-aware because a signature contains parentheses -- `VALUE(rv_x)` --
    and splitting naively would cut a member in half.
    """
    parts, depth, cur = [], 0, []
    for ch in stmt:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        parts.append("".join(cur))
    return parts


def method_bodies(text):
    """Every METHOD ... ENDMETHOD span.

    NO INDENT ASSUMPTION. The RAISING check matched `^  METHOD` with exactly
    two spaces; a method written at any other indent was simply not checked,
    and nothing said so.
    """
    out = []
    for open_m in _METHOD_OPEN.finditer(text):
        close = _METHOD_CLOSE.search(text, open_m.end())
        if not close:
            continue
        out.append(Body(name=open_m.group(1),
                        body=text[open_m.end():close.start()],
                        start=open_m.end(), end=close.start()))
    return out


def interface_methods(text):
    """Declared method names, for an interface file."""
    return [d.name for d in declarations(text)]


def implemented_methods(text):
    """`zif_x~method` names a class actually implements."""
    return {b.name for b in method_bodies(text) if "~" in b.name}
