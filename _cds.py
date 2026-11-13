"""The one CDS lexer the rules share: comments, literals, annotations, joins,
and what each SELECT branch reads, joins and projects.

Lifted out of check_cds.py, where it had grown in four places between the
rules, with two comment strippers 170 lines apart. The rules agree on what an
element or a source is only if one module says so; a form these miss is fixed
HERE, never by a local regex in a rule -- the same bargain as _abap.py.

NOT A PARSER either: regexes and brace depth. Two strippers on purpose:
`strip` blanks literals (`'OR'` in a CASE is not a join condition),
`strip_comments` keeps them (annotation values name things).
"""

import functools
import re
from collections import namedtuple


def strip_comments(text):
    """Comments removed, string literals KEPT (annotation values name things)."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    return re.sub(r"--[^\n]*", " ", text)


def strip(text):
    """CDS source with comments removed and string literals blanked.

    Blanking literals matters: `'OR'` in a CASE must not read as an OR in a
    join, and a literal like `'ZC_X'` is data, not a dependency.
    """
    return re.sub(r"'[^'\n]*'", "''", strip_comments(text))


CARD = r"(?:exact\s+one|many|one)"
# `left outer many to one join`, `inner to one join`, `join` -- the
# cardinality, if any, sits between the join type and JOIN.
JOIN = re.compile(rf"\b(?P<kind>inner|left\s+outer|right\s+outer|cross)?\s*"
                  rf"(?P<card>(?:{CARD}\s+)?to\s+{CARD}\s+)?join\b", re.I)
# Not an annotation: `@ObjectModel.text.association: '_Text'` names one.
ASSOC = re.compile(r"(?<![.\w])(association|composition)\b(?!\s*:)(?P<rest>[^\n]*)", re.I)
ON_END = re.compile(r"\b(?:inner|left|right|cross|join|association|composition|"
                    r"where|group|having|union|except|intersect)\b|\{", re.I)


def on_clauses(text):
    """The text of every ON condition, up to the next clause or the brace."""
    for m in re.finditer(r"\bon\b", text, re.I):
        end = ON_END.search(text, m.end())
        yield text[m.end():end.start() if end else len(text)]


ANNO = re.compile(r"@<?(?P<path>[\w.]+)(?P<colon>\s*:\s*)?")
# Annotations that make an element an amount or a quantity survive as a
# marker inside the element, so `keyamount` can see them.
MARKERS = {"semantics.amount.currencycode": " __amount__ ",
           "semantics.quantity.unitofmeasure": " __quantity__ "}


def _skip_value(s, j):
    if j < len(s) and s[j] in "[{":
        depth = 0
        for k in range(j, len(s)):
            depth += s[k] in "[{"
            depth -= s[k] in "]}"
            if depth == 0:
                return k + 1
        return len(s)
    m = re.compile(r"''|#\w+|[\w.+-]+").match(s, j)
    return m.end() if m else j


def drop_annotations(s):
    """`s` (literals blanked) without annotations; amount/quantity markers kept."""
    out, i = [], 0
    for m in ANNO.finditer(s):
        if m.start() < i:
            continue
        out.append(s[i:m.start()])
        out.append(MARKERS.get(m.group("path").lower(), " "))
        i = _skip_value(s, m.end()) if m.group("colon") else m.end()
    out.append(s[i:])
    return "".join(out)


def split_top(text, sep=","):
    parts, depth, start = [], 0, 0
    for k, ch in enumerate(text):
        depth += ch in "([{"
        depth -= ch in ")]}"
        if ch == sep and depth == 0:
            parts.append(text[start:k])
            start = k + 1
    parts.append(text[start:])
    return parts


def depth_at(text, pos):
    return text.count("(", 0, pos) - text.count(")", 0, pos)


Element = namedtuple("Element", "key expr name amount")
Branch = namedtuple("Branch", "head elements tail aliases sources joins")

# `X( p: … )` takes parameters; the alias follows them.
SOURCE = re.compile(r"\b(?:from|join|projection\s+on)\s+([\w/]+)(?:\s*\([^)]*\))?"
                    r"(?:\s+as\s+(\w+))?", re.I)
JOIN_ON = re.compile(r"\bjoin\s+([\w/]+)(?:\s*\([^)]*\))?(?:\s+as\s+(\w+))?\s+on\b", re.I)


def element(chunk):
    c = chunk.strip()
    amount = "__amount__" in c or "__quantity__" in c
    c = c.replace("__amount__", " ").replace("__quantity__", " ").strip()
    if not c:
        return None
    key = bool(re.match(r"key\b", c, re.I))
    if key:
        c = c[3:].strip()
    top_as = [m for m in re.finditer(r"\bas\b", c, re.I) if depth_at(c, m.start()) == 0]
    if top_as:
        expr, name = c[:top_as[-1].start()].strip(), c[top_as[-1].end():].strip()
    else:
        words = re.findall(r"[\w$]+", c)
        expr, name = c, words[-1] if words else ""
    return Element(key, " ".join(expr.split()), name, amount)


@functools.lru_cache(maxsize=None)
def parse(src):
    """[Branch] for one data definition, one per UNION branch."""
    s = drop_annotations(strip(src))
    out = []
    for b in re.split(r"\b(?:union(?:\s+all)?|except|intersect)\b", s, flags=re.I):
        head, body, tail = _split_braces(b, b.find("{")) or (b, "", "")
        sources = [(n.lower(), (a or n).lower()) for n, a in SOURCE.findall(head)]
        elements = [e for e in map(element, split_top(body)) if e]
        out.append(Branch(head, elements, tail, {a: n for n, a in sources},
                          [n for n, _ in sources], _joins(head)))
    return out


def _split_braces(s, i):
    """(before, inside, after) the brace opening at I and its match; None
    when there is no brace there or it never closes."""
    if i < 0:
        return None
    depth = 0
    for k in range(i, len(s)):
        depth += s[k] == "{"
        depth -= s[k] == "}"
        if depth == 0:
            return s[:i], s[i + 1:k], s[k + 1:]
    return None


def _joins(head):
    """(target, alias, ON condition) for each join in a branch's head."""
    out = []
    for m in JOIN_ON.finditer(head):
        end = ON_END.search(head, m.end())
        out.append((m.group(1).lower(), (m.group(2) or m.group(1)).lower(),
                    head[m.end():end.start() if end else len(head)]))
    return out


def conditions(src):
    """Every boolean condition: CASE WHEN … THEN, ON, WHERE and HAVING."""
    s = drop_annotations(strip(src))
    found = [m.group(1) for m in re.finditer(r"\bwhen\b(.*?)\bthen\b", s, re.I | re.S)]
    found += list(on_clauses(s))
    found += [m.group(2) for m in re.finditer(
        r"\b(where|having)\b(.*?)(?=\bgroup\s+by\b|\bhaving\b|\bunion\b|\bexcept\b|"
        r"\bintersect\b|\}|$)", s, re.I | re.S)]
    return found


def brace_body(s, opener):
    """The text inside the brace that follows the first match of `opener`."""
    m = re.search(opener, s, re.I)
    i = s.find("{", m.end()) if m else -1
    if i < 0:
        return ""
    parts = _split_braces(s, i)
    return parts[1] if parts else s[i + 1:]


def annotations(src, opener, sep):
    """{element: its annotations, lowercased and without blanks} of the first element list."""
    out = {}
    for chunk in split_top(brace_body(strip(src), opener), sep):
        e = element(drop_annotations(chunk))
        if e and e.name:
            out[e.name.lower()] = out.get(e.name.lower(), "") + re.sub(r"\s+", "", chunk.lower())
    return out


# `inner many to one join X as x on`, `association of many to one X as _x on`.
# The source side is optional: `left outer to one join` states the target's
# cardinality alone, and requiring `many to one` let such a join through
# unchecked.
TO_ONE = re.compile(rf"\b(?:(?:inner|left\s+outer)\s+(?:{CARD}\s+)?to\s+(?:exact\s+one|one)\s+join"
                    rf"|association\s+of\s+{CARD}\s+to\s+(?:exact\s+one|one))"
                    r"\s+([\w/]+)(?:\s*\([^)]*\))?\s+as\s+(\w+)\s+on\b", re.I)
